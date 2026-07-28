"""
검증·출처(Reviewer) 에이전트

파이프라인 문서 13절(CRAG/DataCamp/Self-RAG/MAIN-RAG 논문 검토) 설계안을 구현한다.
두 단계로 구성:

  1) 청크 관련성 필터링 (CRAG의 decompose-then-recompose 적용)
     - 검색된 페이지 본문을 web_search.chunk_text()로 잘게 쪼갠 뒤, 청크 단위로
       관련성을 배치 채점해서 관련 있는 청크만 다시 이어붙인다.
     - fact 추출(extract_facts/extract_competitor_facts) 이전 단계에 끼워 넣어,
       무관한 본문이 애초에 LLM 눈에 보이지 않게 한다.

  2) fact 단위 검증 (관련성 + 근거지지도 두 관점, MAIN-RAG식 다중 에이전트 합의)
     - 관점 A: "이 fact가 topic·target_market과 실제로 관련 있는가" (Relevance)
     - 관점 B: "이 fact 문장이 실제로 원본 본문에 근거를 두고 있는가" (Groundedness,
       Self-RAG의 ISSUP 개념을 프롬프트 관점으로 차용)
     - 같은 모델(Solar Mini)에 관점만 다른 프롬프트를 줘서 독립적인 두 판단을 얻고,
       보수적으로 결합(min)한다.
     - 임계값은 고정 숫자가 아니라, 이번 배치(한 번의 실행)에서 나온 점수 분포를 보고
       동적으로 정한다(MAIN-RAG의 adaptive filtering threshold).

  3) 방법론 근거 조회 (RAG 코퍼스 연결, 파이프라인 문서 19절)
     - 1)·2)는 "이 fact가 사실로서 맞는가"를 검증하지만, 이 3)은 성격이 다르다 —
       "이 보고서의 형식·분석 절차가 공인된 표준을 따르고 있는가"를 뒷받침하는 것.
     - Fact 하나하나마다 호출하는 게 아니라, 최종 문서를 조립하는 단계에서 "출처
       메타데이터 필드는 왜 이렇게 구성했는가", "PESTEL 분석 절차는 왜 이 순서를
       따르는가" 같은 질문에 한두 번만 호출해 TTA/NCS 코퍼스에서 근거 구절을 찾아온다.
     - rag/query.py의 search_corpus()(Upstage 임베딩 + Chroma 벡터검색)를 그대로
       재사용한다 — 이 파일에서 새로 벡터DB 접근 코드를 만들지 않는다.

채점 모델 선택 (2026-07-28 갱신 — 근거는 eval/judge_self_test.py 실측):
  당초에는 "관련성/근거지지도 판단은 단순 분류에 가까우니 싼 모델로 충분하다"고 보고
  Solar Mini를 썼다. 근거는 없는 추측이었다. 그래서 self-test 20케이스를 3회 반복해
  세 모델을 비교했고(총 60회 채점 × 3모델), 결과가 그 추측을 뒤집었다.

    모델          종합     판정 뒤집힘   비고
    solar-mini    85%      3건          정상 근거를 실행마다 다르게 처리
    solar-pro2   100%      0건          모든 항목 5/5, 판정이 재현 가능
    solar-pro3    85%      2건          근거·채택 3/5로 붕괴

  "판정 뒤집힘"은 같은 fact·같은 원문에 대해 반복 실행 시 채택↔기각이 바뀐 건수다.
  점수가 흔들리더라도 등급 경계를 넘지 않으면(예: 기각기대 케이스가 [2,1,1]) 운영에는
  영향이 없으므로 따로 센다. pro2는 흔들림 3건이 전부 등급 안이었다.

  pro2는 세 차례 측정에서 85% → 85% → 100%로 일관됐고, mini는 90 → 75 → 85,
  pro3는 80 → 75 → 85로 진동했다. 단발 측정으로는 mini가 1위였던 적도 있어,
  반복 없이는 이 결론에 도달할 수 없었다.

  그래서 검증 단계만 pro2로 올린다. LIGHT_MODEL을 그대로 쓰면 router.py의
  capability QA까지 함께 바뀌므로, 이 단계 전용 VERIFICATION_MODEL을 따로 둔다.

  한계: self-test는 극단 케이스만 본다(20개, 명백한 정답/명백한 조작). 경계 케이스의
  정확도는 사람 라벨과의 정렬도를 재야 알 수 있고, 아직 재지 않았다.
"""

import json
import os
import statistics
from typing import Literal, Optional

from openai import OpenAI

from fact_store.schema import Fact, VerificationStatus
from fact_store.store import save_fact
from agents.web_search import looks_mojibake
from rag.query import search_corpus

import logging

log = logging.getLogger(__name__)

# 검증 단계 전용 모델. LIGHT_MODEL을 공유하지 않는 이유는 router.py도 그 변수를 쓰기
# 때문이다 — 공유하면 "검증기만 정확한 모델로 올린다"는 선택 자체가 불가능해진다.
# LIGHT_MODEL을 폴백으로 두지 않는다. 두면 LIGHT_MODEL=solar-mini가 설정된 기존 서버가
# 이 변수를 지정하지 않는 한 계속 mini로 돌아, 분리한 의미가 없어진다.
# 기본값은 실측 1위인 solar-pro2다 — 아무도 설정하지 않은 서버가 조용히 나쁜 쪽으로
# 도는 것보다, 비싸더라도 정확한 쪽으로 도는 편이 안전하다고 판단했다.
VERIFICATION_MODEL = os.getenv("VERIFICATION_MODEL", "solar-pro2")

CHUNK_RELEVANCE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "chunk_relevance",
        "schema": {
            "type": "object",
            "properties": {
                "relevant_chunk_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "연구대상·목표시장과 실제로 관련 있는 내용을 담은 청크의 index(0부터) 목록",
                }
            },
            "required": ["relevant_chunk_indices"],
        },
    },
}

GRADE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "fact_grade",
        "schema": {
            "type": "object",
            "properties": {
                "score": {
                    "type": "integer",
                    # minimum/maximum을 명시한다 (2026-07-28 추가). 이게 없던 동안
                    # solar-pro3가 self-test에서 0점을 반환한 것이 관측됐다. 범위 밖
                    # 점수는 compute_adaptive_threshold()의 평균을 끌어내리고 표준편차를
                    #키워, 단 한 건이 그 배치 전체의 임계값을 낮추는 부작용을 낳는다.
                    # 스키마만으로는 공급자에 따라 강제되지 않을 수 있어 grade_fact()에서
                    # 한 번 더 clamp한다.
                    "minimum": 1,
                    "maximum": 5,
                    "description": "1(전혀 아님)~5(명백히 맞음) 척도의 채점 점수",
                },
                "reasoning": {"type": "string", "description": "이 점수를 준 이유 (한두 문장)"},
            },
            "required": ["score", "reasoning"],
        },
    },
}


def filter_relevant_chunks(
    client: OpenAI, chunks: list[str], topic: str, target_market: str, query: str
) -> str:
    """청크 목록 중 실제로 관련 있는 것만 골라 다시 이어붙인 본문을 반환한다.

    청크가 1개 이하면(본문이 애초에 짧아서 chunk_text가 분해하지 않은 경우) LLM 호출
    없이 그대로 반환한다 — 비용 절감을 위해 "본문이 충분히 길 때만" 이 단계를 적용한다는
    파이프라인 문서 13-4절 방침."""
    if len(chunks) <= 1:
        return chunks[0] if chunks else ""

    chunks_block = "\n\n".join(f"[청크 {i}]\n{c}" for i, c in enumerate(chunks))
    prompt = f"""리서치 질문: {query}
연구대상(제품/서비스): {topic}
목표시장: {target_market}

아래는 한 웹페이지 본문을 여러 조각(청크)으로 나눈 것입니다. 이 중 연구대상과
목표시장에 실제로 관련 있는 내용을 담은 청크의 index만 골라내세요.

{chunks_block}

기준:
- 목표시장({target_market})과 다른 국가/지역 얘기만 있는 청크는 제외하세요.
- 연구대상({topic})과 다른 제품/서비스 카테고리 얘기만 있는 청크는 제외하세요.
- 네비게이션·광고·페이지 안내 문구만 있는 청크도 제외하세요.
- 애매하면 포함하세요 (여기서는 넓게 거르고, 이후 fact 단위에서 다시 한번 정밀하게
  검증합니다 — 이 단계에서 너무 엄격하게 걸러 recall을 해치지 마세요)."""

    response = client.chat.completions.create(
        model=VERIFICATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=CHUNK_RELEVANCE_SCHEMA,
    )
    parsed = json.loads(response.choices[0].message.content)
    relevant_indices = set(parsed["relevant_chunk_indices"])
    if not relevant_indices:
        # 전부 무관하다고 판정되면 빈 문자열을 반환해, 호출부가 "이 검색결과는 버림" 처리하게 한다.
        return ""
    kept = [chunks[i] for i in sorted(relevant_indices) if 0 <= i < len(chunks)]
    return " ".join(kept)


Perspective = Literal["relevance", "groundedness"]

PERSPECTIVE_PROMPTS: dict[Perspective, str] = {
    "relevance": """당신은 시장조사 fact의 관련성만 엄격하게 채점하는 검수자입니다.
오직 "이 fact가 연구대상·목표시장과 실제로 관련 있는 내용인가"만 1~5점으로 채점하세요.

중요 — 이 fact의 출처 본문은 일부러 제공하지 않았습니다. "원문에 이런 내용이 있는가",
"근거가 있는가"는 다른 검수자가 따로 채점하므로 당신의 판단 대상이 아닙니다. 근거가
없어 보인다는 이유로 감점하지 마세요. 당신은 fact 문장 자체가 연구대상·목표시장의
범위 안에 들어오는지만 보면 됩니다.

지역 판정 규칙 (2026-07-28 추가):
- fact에 "이 사실이 어느 지역에 관한 것인가"가 함께 주어집니다. 그 값이 목표시장의
  지역과 다르면(예: 목표시장이 유럽인데 지역이 인도) 주제가 맞더라도 2점 이하입니다.
  다른 시장에 대한 서술은 이 기획서의 근거가 될 수 없습니다.
- 지역이 "불명"이면 추측해서 목표시장으로 간주하지 마십시오. 지역을 확인할 수 없는
  fact는 목표시장에 부합한다고 볼 근거가 없으므로 3점을 넘지 않습니다.

- 5점: 연구대상·목표시장에 정확히 부합
- 3점: 부분적으로만 관련(예: 인접 카테고리, 인접 지역, 지역 불명)
- 1점: 전혀 다른 주제/지역/카테고리""",
    "groundedness": """당신은 fact의 근거지지도(groundedness)만 엄격하게 채점하는 검수자입니다.
다른 것(주제 관련성 등)은 신경 쓰지 말고 오직 "이 fact 문장이 원본 본문 내용에
근거하고 있는가, 아니면 원문에 없는 내용을 지어낸 것으로 보이는가"만 1~5점으로 채점하세요.

이 fact 문장은 원문을 그대로 베낀 것이 아니라, 원문 내용을 "사실 하나당 한 줄"로
요약·재구성한 것입니다. 원문과 표현(단어, 어순, 문장 구조)이 다른 것은 정상이며 감점
사유가 아닙니다.

■ 규칙 1 (최우선) — 수치·날짜·고유명사는 원문에 있어야 한다
fact에 등장하는 숫자(금액·비율·성장률·개수), 연도·날짜, 기관·기업·제품의 고유명사는
원문에 같은 값으로 나와 있어야 합니다.
- 원문이 방향만 말했는데(예: "증가했다", "확대되고 있다", "요구하고 있다") fact가
  구체적인 수치나 시점을 붙였다면, 그 값은 지어낸 것입니다 → 반드시 2점 이하.
- 원문에 있는 값과 다른 값을 쓴 경우도 → 반드시 2점 이하.
- "그럴듯하다", "업계 상식에 부합한다", "대체로 맞는 수치다"는 근거가 되지 않습니다.
  원문 안에 그 값이 있는지만 확인하세요.
- 단, 원문의 값을 단위·표기만 바꿔 옮긴 것(예: "50억 달러" → "5,000백만 달러",
  "2030년" → "2030년까지")은 감점하지 않습니다.

■ 규칙 2 — 규칙 1에 걸리지 않으면 관대하게
표현·어순·문장 구조의 차이나 요약 과정의 압축은 감점하지 마세요. 이 단계의 목적은
"명백한 조작"을 걸러내는 것이지 요약 방식을 트집 잡는 것이 아닙니다. 규칙 1 위반이
아니면서 애매한 경우는 3점 이상으로 채점하세요.

2점은 규칙 1 위반(원문에 없는 수치·날짜·고유명사)에만 쓰는 등급입니다. 표현이 단정적이다,
어감이 강하다, 원문보다 범위가 넓어 보인다 같은 이유로는 2점을 주지 마세요 — 그런 경우는
3점입니다. fact에 원문에 없는 숫자나 날짜나 고유명사가 실제로 들어 있는지 먼저 확인하고,
없다면 2점은 후보에서 제외하세요.

- 5점: 원문 내용을 표현만 바꿔 정확히 요약함 (표현이 다른 것은 무관)
- 3점: 수치·날짜·고유명사는 원문과 일치하나, 원문에 없는 단정·인과·조건이 덧붙어
  다소 확대해석됨
- 2점: 원문에 없는 수치·날짜·고유명사가 들어갔다 (규칙 1 위반)
- 1점: 원문 어디에도 이런 내용이 없어 완전히 지어낸 것으로 보임""",
}


# 관점별로 프롬프트에 넣는 입력을 분리한다 (2026-07-28 수정, judge self-test로 발견).
#
# 원인: 이전 구현은 perspective와 무관하게 하나의 템플릿을 써서, 관련성을 채점할 때도
#   원본 본문 3,000자를 함께 넣었다. 프롬프트가 "근거 여부는 신경 쓰지 말라"고 지시해도
#   원문이 눈앞에 있으면 모델은 그것을 쓴다. self-test에서 실제로 관측된 채점 근거:
#     [R-OK-3] "…'낙상 감지 기능'에 대한 구체적인 언급이 원문에 없어 부분적 관련성만 인정됨"
#   관련성을 재라고 했는데 근거지지도를 재고 있다. solar-mini/pro2/pro3 세 모델 모두에서
#   같은 현상이 나왔으므로 모델 문제가 아니라 프롬프트 설계 문제다.
#
# 왜 문제인가: 두 점수를 min으로 결합하는 것은 비보상적(non-compensatory) 결합이고,
#   이 방식이 정당한 전제는 "두 축이 서로 독립"이라는 것이다. 관련성 점수 안에
#   근거지지도가 섞여 있으면 min은 근거지지도를 두 번 감점하는 이중 처벌이 된다.
#   self-test에서 세 모델 전부 relevance 채택기대 항목이 무너진 근본 원인이 이것이다.
#
# 그래서: 각 관점은 자기 판단에 필요한 입력만 본다. 대칭을 위해 근거지지도에서도
#   연구대상·목표시장을 뺀다 — 근거지지도는 "fact가 원문에 있는가"만 보면 되고,
#   주제가 무엇인지 알 필요가 없다.
PERSPECTIVE_INPUT_KEYS: dict[Perspective, tuple[str, ...]] = {
    "relevance": ("topic", "target_market"),
    "groundedness": ("source_content",),
}


SCORE_MIN, SCORE_MAX = 1, 5


def clamp_score(score: int, perspective: Perspective) -> int:
    """채점 점수를 1~5로 강제한다 (2026-07-28 추가).

    원인: GRADE_SCHEMA에 minimum/maximum이 없던 동안 solar-pro3가 self-test에서
      0점을 반환한 것이 관측됐다(R-NG-5, [0, 5, 5]). 구조화 출력 스키마는 공급자·모델에
      따라 강제 수준이 다르므로 스키마만 믿을 수 없다.
    왜 위험한가: compute_adaptive_threshold()가 배치의 평균과 표준편차로 임계값을
      정하기 때문에, 범위 밖 점수 한 건이 평균을 끌어내리고 표준편차를 키워 임계값을
      두 방향에서 낮춘다. 즉 한 건의 계약 위반이 그 배치 전체를 관대하게 만든다.
    한계: clamp는 잘못된 점수를 "가장 가까운 유효값"으로 바꾸는 것이므로 원래 의도를
      복원하지는 못한다. 그래서 조용히 넘기지 않고 경고 로그를 남긴다.
    """
    if not isinstance(score, int) or isinstance(score, bool):
        log.warning("채점 점수가 정수가 아님(%s, %r) — %d점으로 처리", perspective, score, SCORE_MIN)
        return SCORE_MIN
    if score < SCORE_MIN or score > SCORE_MAX:
        fixed = max(SCORE_MIN, min(SCORE_MAX, score))
        log.warning(
            "채점 점수가 범위(%d~%d)를 벗어남(%s, %d) — %d점으로 보정",
            SCORE_MIN, SCORE_MAX, perspective, score, fixed,
        )
        return fixed
    return score


def build_grading_prompt(
    fact_text: str,
    source_content: str,
    topic: str,
    target_market: str,
    perspective: Perspective,
    region: Optional[str] = None,
) -> str:
    """관점에 맞는 입력만 담은 채점 프롬프트를 만든다.

    region은 관련성 채점에만 넘긴다(결함 G). fact 문장에서 지역이 빠져 있으면 관련성을
    판정할 근거가 없는데, 결함 A 수정으로 원문까지 뺐으므로 이 값이 유일한 지역 근거다.
    근거지지도에는 넘기지 않는다 — 두 축의 입력을 겹치지 않게 유지해야 min 결합의
    독립 가정이 유지된다."""
    blocks: list[str] = [PERSPECTIVE_PROMPTS[perspective]]
    keys = PERSPECTIVE_INPUT_KEYS[perspective]
    if "topic" in keys:
        blocks.append(f"연구대상: {topic}\n목표시장: {target_market}")
        blocks.append(f"이 fact가 다루는 지역: {region or '불명'}")
    if "source_content" in keys:
        body = source_content[:3000] or "(원본 본문 없음)"
        blocks.append(f"원본 본문(이 fact를 추출한 출처):\n{body}")
    blocks.append(f'채점 대상 fact:\n"{fact_text}"')
    blocks.append("위 기준에 따라 1~5점을 매기세요.")
    return "\n\n".join(blocks)


def prescreen_fact(fact_text: str, source_content: str) -> Optional[str]:
    """LLM에 묻기 전에 코드로 확실히 판정할 수 있는 것을 먼저 처리한다.

    반환값: 기각 사유 문자열(기각해야 함) 또는 None(LLM 채점으로 넘김)

    왜 필요한가 (2026-07-28) — 결함 F에서 배운 것:
      출처 페이지의 charset 미탐지로 본문이 모지바케가 됐을 때, 검증기는 이 fact를
      **관련성 5점 · 근거지지도 5점으로 채택**하고 citation_verified 도장을 찍었다.
      근거지지도 검증은 "fact가 원문에 있는가"만 묻기 때문에, 원문과 fact가 **함께**
      깨져 있으면 논리적으로 '일치'가 성립한다. 판정 로직이 틀린 것이 아니라,
      판정할 수 없는 입력이 판정 단계까지 들어온 것이다.

      결함 C에서도 같은 교훈을 얻었다 — 정규식으로 확실히 판정할 수 있는 것을 LLM에
      물으면 답이 흔들린다. 그때는 "정보 없음" 메타발언이었고, 이번은 깨진 인코딩이다.

    한계: 모지바케 판정은 휴리스틱이다. 깨진 글자와 정상 특수문자가 섞인 문서에서
    오탐이 날 수 있다. 그래서 임계(threshold)를 두고, 기각 사유를 반드시 남겨
    사람이 초안에서 확인할 수 있게 한다.
    """
    if looks_mojibake(fact_text):
        return ("문자 인코딩이 깨진 문장입니다(모지바케). 출처 페이지의 charset을 잘못 "
                "해석해 수집된 것으로, 내용을 판정할 수 없으므로 기각합니다.")
    if source_content and looks_mojibake(source_content):
        return ("출처 본문의 문자 인코딩이 깨져 있어(모지바케) 근거 대조가 불가능합니다. "
                "fact 자체는 읽을 수 있어도 근거를 확인할 수 없으므로 기각합니다.")
    return None


def grade_fact(
    client: OpenAI,
    fact_text: str,
    source_content: str,
    topic: str,
    target_market: str,
    perspective: Perspective,
    region: Optional[str] = None,
) -> tuple[int, str]:
    """fact 하나를 한 관점(관련성 또는 근거지지도)으로 채점한다."""
    prompt = build_grading_prompt(
        fact_text, source_content, topic, target_market, perspective, region
    )

    response = client.chat.completions.create(
        model=VERIFICATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=GRADE_SCHEMA,
    )
    # 토큰 사용량을 실측해서 남긴다 (2026-07-28 추가).
    # 모델 교체(mini→pro2)의 비용 영향을 물어봤을 때, 프롬프트 글자 수로 추정하는 수밖에
    # 없었다. 한국어 토크나이저의 글자당 토큰 수를 모르니 그 추정은 근거가 약하다.
    # API 응답의 usage 필드가 정확한 값을 주므로, 한 번 실제로 돌리면 추정이 필요 없어진다.
    _log_token_usage(response, perspective)

    parsed = json.loads(response.choices[0].message.content)
    return clamp_score(parsed["score"], perspective), parsed["reasoning"]


# 프로세스 수명 동안 누적한다. 실행 1회의 총량을 알려면 개별 호출값만으로는 부족하다.
TOKEN_USAGE: dict[str, dict[str, int]] = {}


def _log_token_usage(response, perspective: str) -> None:
    """채점 호출 1건의 토큰 사용량을 누적하고 기록한다.

    usage 필드는 공급자에 따라 없을 수도 있으므로 실패해도 채점을 막지 않는다 —
    비용 계측은 부가 기능이고, 이것 때문에 파이프라인이 죽으면 안 된다."""
    try:
        u = getattr(response, "usage", None)
        if u is None:
            return
        bucket = TOKEN_USAGE.setdefault(
            VERIFICATION_MODEL, {"calls": 0, "prompt": 0, "completion": 0}
        )
        bucket["calls"] += 1
        bucket["prompt"] += getattr(u, "prompt_tokens", 0) or 0
        bucket["completion"] += getattr(u, "completion_tokens", 0) or 0
        log.debug(
            "  [검증] 토큰 %s/%s: 입력 %s · 출력 %s (누적 호출 %d회, 입력 %d, 출력 %d)",
            VERIFICATION_MODEL, perspective,
            getattr(u, "prompt_tokens", "?"), getattr(u, "completion_tokens", "?"),
            bucket["calls"], bucket["prompt"], bucket["completion"],
        )
    except Exception:  # noqa: BLE001 — 계측 실패가 채점을 막아선 안 된다
        log.debug("  [검증] 토큰 사용량 기록 실패(무시함)", exc_info=True)


def token_usage_report() -> str:
    """누적 토큰 사용량을 사람이 읽을 한 줄로 만든다. 단가를 곱하면 실행당 비용이 나온다."""
    if not TOKEN_USAGE:
        return "토큰 사용량 기록 없음(usage 미제공 또는 호출 없음)"
    lines = []
    for model, u in sorted(TOKEN_USAGE.items()):
        lines.append(
            f"{model}: 호출 {u['calls']}회 · 입력 {u['prompt']:,} 토큰 · "
            f"출력 {u['completion']:,} 토큰"
        )
    return " | ".join(lines)


def compute_adaptive_threshold(scores: list[int]) -> float:
    """MAIN-RAG의 adaptive filtering 아이디어: 고정 임계값 대신 이번 배치의 점수 분포를 보고
    동적으로 임계값을 정한다. 평균이 낮은 배치(원래 검색 품질이 나쁜 topic)에서는 임계값을
    낮춰 recall을 지키고, 평균이 높은 배치에서는 임계값을 높여 precision을 더 타이트하게
    가져간다. 다만 3~4점 범위를 벗어나지 않도록 clamp해, 너무 관대하거나 너무 엄격해지는
    극단을 막는다 (완전히 배치에만 의존하면 배치 자체가 나쁠 때 전부 통과시켜버릴 위험이 있음)."""
    if not scores:
        return 4.0
    mean = statistics.mean(scores)
    stdev = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    threshold = mean - 0.5 * stdev
    return max(3.0, min(4.0, threshold))


def verify_fact(
    client: OpenAI,
    fact: Fact,
    source_content: str,
    topic: str,
    target_market: str,
    threshold: float,
) -> Fact:
    """fact 하나를 관련성·근거지지도 두 관점으로 채점하고, 보수적 결합(min) 점수와
    주어진 임계값을 비교해 최종 판정을 내린 뒤 Fact 객체에 반영한다 (저장은 호출부 책임)."""
    # LLM에 묻기 전에 코드로 확실히 판정할 수 있는 것을 먼저 처리한다(결함 F).
    blocked = prescreen_fact(fact.text, source_content)
    if blocked:
        fact.verification_score = SCORE_MIN
        fact.verification_status = VerificationStatus.REJECTED
        fact.verification_reasoning = f"[사전검사 기각] {blocked}"
        fact.citation_verified = False
        fact.needs_source_check = True
        log.info(f"  [검증] 사전검사 기각: {fact.text[:40]}… — {blocked[:36]}…")
        return fact

    rel_score, rel_reason = grade_fact(client, fact.text, source_content, topic,
                                                   target_market, "relevance", fact.region)
    grd_score, grd_reason = grade_fact(client, fact.text, source_content, topic, target_market, "groundedness")

    combined = min(rel_score, grd_score)
    reasoning = f"[관련성 {rel_score}점: {rel_reason}] [근거지지도 {grd_score}점: {grd_reason}]"

    if combined >= threshold:
        status = VerificationStatus.ACCEPTED
    elif combined <= threshold - 2:
        status = VerificationStatus.REJECTED
    else:
        status = VerificationStatus.AMBIGUOUS

    fact.verification_score = combined
    fact.verification_status = status
    fact.verification_reasoning = reasoning
    fact.citation_verified = status == VerificationStatus.ACCEPTED
    fact.needs_source_check = status != VerificationStatus.ACCEPTED
    return fact


def verify_facts_batch(
    client: OpenAI,
    facts_with_content: list[tuple[Fact, str]],
    topic: str,
    target_market: str,
) -> dict[str, int]:
    """검색 한 회차에서 새로 저장한 fact들을 한 배치로 묶어 검증한다.

    1) 배치 전체를 먼저 채점해 점수 분포를 얻고,
    2) 그 분포로 적응형 임계값을 계산한 뒤,
    3) 그 임계값으로 각 fact의 최종 판정(채택/애매/기각)을 확정해 저장한다.

    반환값: {"accepted": n, "ambiguous": n, "rejected": n}
    """
    if not facts_with_content:
        return {"accepted": 0, "ambiguous": 0, "rejected": 0}

    # 1차 패스: 관점별 점수와 이유를 함께 모아 배치 분포를 파악한다.
    # (이유를 버리지 않고 반드시 들고 다닌다 — 초기 구현에서 combined 점수만 남기고
    # reasoning을 버려서, 오탐이 나와도 "왜" 그런 점수가 나왔는지 진단할 수 없었던
    # 문제가 실제 사용자 테스트에서 발견됨. 파이프라인 문서 13-8절 참고.)
    graded: list[tuple[Fact, str, int, str]] = []  # (fact, source_content, combined_score, reasoning)
    # 사전검사에서 기각된 fact는 배치 점수 분포에 넣지 않는다(결함 F).
    # 넣으면 최저점이 평균을 끌어내려 임계값이 낮아지고, 결함 D와 같은 방식으로
    # 나머지 fact 전체가 관대하게 판정된다 — 오염이 전파되지 않게 분리한다.
    prescreened: list[tuple[Fact, str]] = []
    for fact, source_content in facts_with_content:
        blocked = prescreen_fact(fact.text, source_content)
        if blocked:
            prescreened.append((fact, f"[사전검사 기각] {blocked}"))
            continue
        rel_score, rel_reason = grade_fact(client, fact.text, source_content, topic,
                                                   target_market, "relevance", fact.region)
        grd_score, grd_reason = grade_fact(client, fact.text, source_content, topic, target_market, "groundedness")
        combined = min(rel_score, grd_score)
        reasoning = f"[관련성 {rel_score}점: {rel_reason}] [근거지지도 {grd_score}점: {grd_reason}]"
        graded.append((fact, source_content, combined, reasoning))

    if prescreened:
        log.info(f"  [검증] 사전검사로 {len(prescreened)}건 기각 (LLM 호출 없음)")

    threshold = compute_adaptive_threshold([s for _, _, s, _ in graded])
    log.info(f"  [검증] 이번 배치 적응형 임계값: {threshold:.2f}점 (fact {len(graded)}개 채점 완료)")

    counts = {"accepted": 0, "ambiguous": 0, "rejected": 0}
    for fact, reasoning in prescreened:
        fact.verification_score = SCORE_MIN
        fact.verification_status = VerificationStatus.REJECTED
        fact.verification_reasoning = reasoning
        fact.citation_verified = False
        fact.needs_source_check = True
        save_fact(fact)
        counts["rejected"] += 1
    for fact, source_content, combined, reasoning in graded:
        if combined >= threshold:
            status = VerificationStatus.ACCEPTED
            counts["accepted"] += 1
        elif combined <= threshold - 2:
            status = VerificationStatus.REJECTED
            counts["rejected"] += 1
        else:
            status = VerificationStatus.AMBIGUOUS
            counts["ambiguous"] += 1

        fact.verification_score = combined
        fact.verification_status = status
        fact.verification_reasoning = reasoning
        fact.citation_verified = status == VerificationStatus.ACCEPTED
        fact.needs_source_check = status != VerificationStatus.ACCEPTED
        save_fact(fact)

        if status != VerificationStatus.ACCEPTED:
            log.info(f"  [검증:{status.value}] ({combined}점) {fact.text[:60]}")
            log.info(f"    사유: {reasoning}")

    return counts


# --- 방법론 근거 조회 (RAG 코퍼스 연결) ---
#
# 위 grade_fact/verify_facts_batch는 "이 fact가 사실로서 맞는가"를 검증하지만,
# 아래 함수들은 성격이 다르다 — "이 보고서의 형식·분석 절차가 공인된 표준(TTA/NCS)을
# 따르고 있는가"를 뒷받침하는 것. Fact 하나하나마다 부르는 게 아니라, 문서를 최종
# 조립하는 단계(Writer 에이전트 또는 검증·출처 에이전트의 문서합성 단계, 아직 미구현)에서
# "출처 메타데이터 필드 구성 근거", "PESTEL 분석 절차 근거" 같은 질문에 한두 번만
# 호출하는 용도다.

MIN_METHODOLOGY_CITATION_CHARS = 300  # 인용문은 근거를 확인할 수 있는 정도면 충분, 전문을 다 보여줄 필요는 없음


def get_methodology_citation(query: str, doc_type: Optional[str] = None, k: int = 2) -> list[dict]:
    """TTA/NCS 코퍼스에서 query와 관련된 상위 k개 구절을 찾아 인용 형태로 반환한다.

    rag/query.py의 search_corpus()(Upstage 임베딩 + Chroma 벡터검색)를 그대로
    재사용한다 — 여기서 새로 벡터DB 접근 코드를 만들지 않는다.

    doc_type: "TTA"(표준문서, 예: 메타데이터·저작권정보 구성 지침) 또는
              "NCS"(국가직무능력표준 학습모듈, 예: 전략기획·통합관리) 중 하나로
              필터링. None이면 두 종류 다 검색.

    반환값: [{"text": 인용 발췌(앞부분만), "source_file": 원본 파일명, "doc_type": ...}]
    코퍼스가 비어있거나 검색 실패 시(예: UPSTAGE_API_KEY 미설정) 빈 리스트를 반환해
    호출부가 "근거를 못 찾았다"로 자연스럽게 처리할 수 있게 한다.
    """
    try:
        hits = search_corpus(query, k=k, doc_type=doc_type)
    except Exception as e:
        log.info(f"  [방법론 근거 조회 실패] '{query}' 조회 중 오류({type(e).__name__}: {e}) — 근거 없이 진행합니다.")
        return []

    return [
        {
            "text": hit["text"][:MIN_METHODOLOGY_CITATION_CHARS],
            "source_file": hit["source_file"],
            "doc_type": hit["doc_type"],
        }
        for hit in hits
    ]


def format_methodology_citation(citations: list[dict]) -> str:
    """get_methodology_citation()의 결과를 최종 문서에 그대로 넣을 수 있는 인용 문구로 조립한다."""
    if not citations:
        return "(관련 표준 근거를 찾지 못함 — 코퍼스 미조회 또는 무관련)"
    lines = [f"[{c['doc_type']} — {c['source_file']}] {c['text']}..." for c in citations]
    return "\n".join(lines)


def cite_fact_metadata_standard() -> str:
    """Fact Store의 출처 메타데이터 필드(source_url, retrieved_date, source_tier 등) 구성
    근거를 TTA 표준(10.1595 메타데이터, 10.1601 저작권정보 구성)에서 찾아 인용한다.
    fact_store/schema.py 상단 주석이 텍스트로만 언급하던 근거를, 실제 RAG 조회로
    대체하는 첫 연결 지점."""
    citations = get_methodology_citation("출처 메타데이터 구성 저작권 정보 표기", doc_type="TTA", k=2)
    return format_methodology_citation(citations)


def cite_pestel_methodology() -> str:
    """PESTEL/전략기획 분석 절차가 따르는 방법론적 근거를 NCS 코퍼스(전략기획 학습모듈 등)에서
    찾아 인용한다. PESTEL 에이전트나 Writer 에이전트가 방법론 섹션을 작성할 때 참고할 용도."""
    citations = get_methodology_citation("전략기획 환경분석 절차 방법론", doc_type="NCS", k=2)
    return format_methodology_citation(citations)
