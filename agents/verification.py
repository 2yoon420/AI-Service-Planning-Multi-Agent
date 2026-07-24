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

비용 절감을 위해 Solar Pro2가 아니라 Solar Mini를 쓴다 — 관련성/근거지지도 판단은
복잡한 추론이 필요한 작업이 아니라 단순 분류에 가까워서, 굳이 비싼 모델을 쓸 필요가
없다고 판단함(사용자가 확인한 Upstage 모델 목록 중 Solar Mini가 이 용도에 적합).
"""

import json
import os
import statistics
from typing import Literal, Optional

from openai import OpenAI

from fact_store.schema import Fact, VerificationStatus
from fact_store.store import save_fact
from rag.query import search_corpus

VERIFICATION_MODEL = os.getenv("LIGHT_MODEL", "solar-mini")

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
다른 것(근거 여부 등)은 신경 쓰지 말고 오직 "이 fact가 연구대상·목표시장과 실제로
관련 있는 내용인가"만 1~5점으로 채점하세요.
- 5점: 연구대상·목표시장에 정확히 부합
- 3점: 부분적으로만 관련(예: 인접 카테고리, 인접 지역)
- 1점: 전혀 다른 주제/지역/카테고리""",
    "groundedness": """당신은 fact의 근거지지도(groundedness)만 엄격하게 채점하는 검수자입니다.
다른 것(주제 관련성 등)은 신경 쓰지 말고 오직 "이 fact 문장이 원본 본문 내용에
근거하고 있는가, 아니면 원문에 없는 내용을 지어낸 것으로 보이는가"만 1~5점으로 채점하세요.

중요 — 이 fact 문장은 원문을 그대로 베낀 것이 아니라, 원문 내용을 "사실 하나당 한 줄"로
요약·재구성한 것입니다. 원문과 표현(단어, 어순, 문장 구조)이 다른 것은 정상이며 감점 사유가
아닙니다. 오직 원문에 등장하지 않는 새로운 사실·수치·주장이 추가되었는지만 확인하세요.

- 5점: 원문 내용을 표현만 바꿔 정확히 요약함 (표현이 다른 것은 무관)
- 3점: 원문에 비슷한 내용은 있으나, 원문에 없는 세부사항(구체적 수치, 조건 등)이 추가되어
  다소 확대해석됨
- 1점: 원문 어디에도 이런 내용이 없어 완전히 지어낸 것으로 보임

애매하면 관대하게(3점 이상으로) 채점하세요 — 이 단계는 "명백한 조작"만 걸러내는 것이
목적이지, 요약의 표현 방식을 트집 잡는 것이 목적이 아닙니다.""",
}


def grade_fact(
    client: OpenAI,
    fact_text: str,
    source_content: str,
    topic: str,
    target_market: str,
    perspective: Perspective,
) -> tuple[int, str]:
    """fact 하나를 한 관점(관련성 또는 근거지지도)으로 채점한다."""
    prompt = f"""{PERSPECTIVE_PROMPTS[perspective]}

연구대상: {topic}
목표시장: {target_market}

원본 본문(이 fact를 추출한 출처):
{source_content[:3000] or "(원본 본문 없음)"}

채점 대상 fact:
"{fact_text}"

위 기준에 따라 1~5점을 매기세요."""

    response = client.chat.completions.create(
        model=VERIFICATION_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=GRADE_SCHEMA,
    )
    parsed = json.loads(response.choices[0].message.content)
    return parsed["score"], parsed["reasoning"]


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
    rel_score, rel_reason = grade_fact(client, fact.text, source_content, topic, target_market, "relevance")
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
    for fact, source_content in facts_with_content:
        rel_score, rel_reason = grade_fact(client, fact.text, source_content, topic, target_market, "relevance")
        grd_score, grd_reason = grade_fact(client, fact.text, source_content, topic, target_market, "groundedness")
        combined = min(rel_score, grd_score)
        reasoning = f"[관련성 {rel_score}점: {rel_reason}] [근거지지도 {grd_score}점: {grd_reason}]"
        graded.append((fact, source_content, combined, reasoning))

    threshold = compute_adaptive_threshold([s for _, _, s, _ in graded])
    print(f"  [검증] 이번 배치 적응형 임계값: {threshold:.2f}점 (fact {len(graded)}개 채점 완료)")

    counts = {"accepted": 0, "ambiguous": 0, "rejected": 0}
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
            print(f"  [검증:{status.value}] ({combined}점) {fact.text[:60]}")
            print(f"    사유: {reasoning}")

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
        print(f"  [방법론 근거 조회 실패] '{query}' 조회 중 오류({type(e).__name__}: {e}) — 근거 없이 진행합니다.")
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
