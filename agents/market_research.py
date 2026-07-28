"""
시장조사 에이전트 (Day 3 프로토타입)

흐름:
  1) 주제+목표시장 입력 받음
  2) Solar Pro 2에게 리서치 질문 3~5개를 뽑게 함 (구조화 출력)
  3) 질문마다 웹검색(ddgs) 실행
  4) 각 검색 결과 스니펫에서 "사실 하나당 한 줄" 형태로 fact를 추출 (구조화 출력)
  5) Fact 객체로 만들어 Fact Store(SQLite)에 저장

주의: Solar Pro 2만 response_format(JSON 스키마 강제 출력)을 지원하므로,
구조화된 결과가 필요한 이 두 단계(질문 생성, fact 추출)는 전부 solar-pro2를 쓴다.
"""

import os
import uuid
from datetime import date

from dotenv import load_dotenv
from openai import OpenAI

from agents.verification import filter_relevant_chunks, verify_facts_batch
from agents.web_search import chunk_text, search_web
from fact_store.schema import Fact, MarketSizing, SourceTier
from fact_store.store import init_db, save_fact_if_new, save_market_sizing

import logging

log = logging.getLogger(__name__)

load_dotenv()

HEAVY_MODEL = os.getenv("HEAVY_MODEL", "solar-pro2")

QUESTIONS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "research_questions",
        "schema": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "시장조사를 위한 핵심 리서치 질문 목록",
                }
            },
            "required": ["questions"],
        },
    },
}

FACTS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_facts",
        "schema": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "이 검색결과 스니펫에서 뽑아낸, 사실 하나당 한 줄로 압축된 문장들. 근거가 될 만한 내용이 없으면 빈 배열.",
                }
            },
            "required": ["facts"],
        },
    },
}


MARKET_SIZING_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "market_sizing_topdown",
        "schema": {
            "type": "object",
            "properties": {
                "tam_found": {
                    "type": "boolean",
                    "description": "facts 중에 전체 시장 규모(TAM)를 추정할 만한 수치가 있었는지 여부",
                },
                # 2026-07-28 변경 — 원래는 tam_usd(number) 하나로 "LLM이 직접 USD로 환산해서
                # 답하라"는 계약이었다. 실제 실행에서 "116.13억 달러"를 116.13으로 그대로 답해
                # 기획서에 "TAM 116 USD"가 찍히는 사고가 났다(유럽 친환경 포장재, 2026-07-28).
                # 환산은 산술이므로 코드가 해야 한다는 이 프로젝트의 원칙에 맞춰, LLM에게는
                # "원문에 적힌 대로" 값과 배율 단어를 분리해 보고하게 하고 곱셈은 코드가 한다.
                "tam_value": {
                    "type": "number",
                    "description": "TAM 수치를 원문에 적힌 숫자 그대로. 배율 단어(억/billion 등)는 여기 반영하지 말 것. 예) '116.13억 달러' -> 116.13, '$505B' -> 505, '2,956억 2천만 달러' -> 2956.2. tam_found가 false면 0. 가능하면 미래 예측 종료 연도(예: 2031년, 2034년)의 값이 아니라 fact 목록에 있는 가장 최근 실측(또는 실측에 가장 가까운) 연도의 시장 규모를 우선 사용할 것.",
                },
                "tam_scale": {
                    "type": "string",
                    "enum": ["없음", "천", "만", "억", "조",
                             "thousand", "million", "billion", "trillion"],
                    "description": "tam_value에 곱해야 할 배율 단어를 원문 표기 그대로. 예) '116.13억 달러' -> '억', '$505B' -> 'billion', '5,793만 달러' -> '만', '3,200달러' -> '없음'. 원문에 배율 단어가 없으면 '없음'.",
                },
                "tam_year": {
                    "type": "string",
                    "description": "이 TAM 수치가 어느 연도 기준인지 (예: '2025', '2024~2030 평균' 등). 실측치가 아니라 예측치를 쓴 경우 '(예측치)'를 함께 표기할 것 (예: '2031 (예측치)').",
                },
                "tam_source_snippet": {
                    "type": "string",
                    "description": "TAM 값을 뽑아낸 근거 fact 원문 (그대로 인용)",
                },
                "sam_ratio": {
                    "type": "number",
                    "description": "TAM 중 목표시장(지역·세그먼트) 비중. 0~1 사이 값. facts에 지역별 점유율이 있으면 그 값을 근거로 쓰고, 없으면 합리적으로 추정.",
                },
                "sam_ratio_reasoning": {
                    "type": "string",
                    "description": "sam_ratio를 이렇게 잡은 근거 (근거 fact 인용 또는 추정 논리)",
                },
                "som_ratio": {
                    "type": "number",
                    "description": "SAM 중 신규 진입자가 3~5년 내 현실적으로 확보 가능한 점유율. 0~1 사이 값. 통상 1~10% 수준.",
                },
                "som_ratio_reasoning": {
                    "type": "string",
                    "description": "som_ratio를 이렇게 잡은 근거",
                },
            },
            "required": [
                "tam_found",
                "tam_value",
                "tam_scale",
                "tam_year",
                "tam_source_snippet",
                "sam_ratio",
                "sam_ratio_reasoning",
                "som_ratio",
                "som_ratio_reasoning",
            ],
        },
    },
}


# --- 배율 환산 (2026-07-28 추가) --------------------------------------------
# LLM은 "원문에 적힌 숫자 + 배율 단어"만 보고하고, 실제 곱셈은 여기서 코드가 한다.
# 이 프로젝트의 원칙("LLM은 판단만, 산술·검증은 코드가")을 시장규모 계산에도
# 실제로 적용하기 위한 것 — 그전까지는 이 환산만 LLM에게 맡겨져 있었다.
_SCALE_MULTIPLIER: dict[str, float] = {
    "없음": 1.0,
    "천": 1e3,
    "만": 1e4,
    "억": 1e8,
    "조": 1e12,
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
    "trillion": 1e12,
}

# 국가·권역 단위 시장의 TAM이 100만 USD 미만인 경우는 사실상 없다. 이 선 아래로
# 나오면 LLM이 배율을 잘못 읽었을 가능성이 높다고 보고 경고를 남긴다.
# 값을 조용히 버리지 않는 이유: 무엇이 왜 이상한지 문서에 드러나야 사람이 판단할 수 있다.
_TAM_SANITY_MIN_USD = 1_000_000.0


def scale_to_multiplier(scale: str | None) -> float:
    """배율 단어를 곱할 수를 돌려준다. 모르는 표현이면 1.0(=배율 없음)으로 처리한다.

    한계: enum에 없는 지역 표현(인도의 lakh/crore 등)은 여전히 못 잡는다."""
    if not scale:
        return 1.0
    return _SCALE_MULTIPLIER.get(scale.strip(), 1.0)


def _estimate_topdown(client: OpenAI, topic: str, target_market: str, facts: list[Fact]) -> dict:
    """수집된 fact들을 근거로 Top-down TAM/SAM/SOM에 필요한 값들을 LLM이 추출·제안한다.
    실제 곱셈(TAM*sam_ratio 등)은 여기서 하지 않고, 호출부(calculate_market_sizing)에서
    코드가 직접 계산한다 — LLM은 '숫자 해석/합리적 비율 제안'까지만 담당."""
    facts_text = "\n".join(f"- ({f.source_tier.value}) {f.text}" for f in facts) or "(수집된 fact 없음)"

    prompt = f"""당신은 20년 경력의 시장조사 컨설턴트입니다.

연구대상: {topic}
목표시장: {target_market}

아래는 지금까지 웹검색으로 수집한 fact 목록입니다. 이 목록이 당신이 참조할 수 있는 근거의 전부입니다.

{facts_text}

이 fact들을 바탕으로 Top-down 방식 시장규모 추정에 필요한 값을 제안하세요.
- TAM: facts 중 전체 시장 규모를 나타내는 수치를 찾아 tam_value(숫자)와 tam_scale(배율 단어)로 분리해 보고
- SAM 비중: TAM 중 목표시장(지역/세그먼트)이 차지하는 비중 (facts에 지역별 점유율이 있으면 활용)
- SOM 비중: SAM 중 신규 진입자가 현실적으로 확보 가능한 점유율

TAM으로 쓸 만한 수치가 facts에 전혀 없으면 tam_found를 false로 하세요.

매우 중요 — 단위 환산은 하지 마세요:
- tam_value에는 **원문에 적힌 숫자를 그대로** 넣고, 배율 단어는 tam_scale에 따로 넣으세요.
  올바른 예) "116.13억 달러" -> tam_value=116.13, tam_scale="억"
  올바른 예) "$505B"        -> tam_value=505,    tam_scale="billion"
  틀린 예)  "116.13억 달러" -> tam_value=11613000000  (직접 환산하지 마세요)
  틀린 예)  "116.13억 달러" -> tam_value=116.13, tam_scale="없음"  (배율을 빠뜨렸습니다)
- 실제 곱셈은 프로그램이 수행하므로, 당신은 원문을 정확히 옮기기만 하면 됩니다.

매우 중요 — TAM 기준 연도 선택:
- fact 목록에 여러 연도의 시장 규모 수치가 있다면(예: "2024년 X달러", "2031년 Y달러로 성장 전망"),
  미래 예측의 종료 연도(가장 먼 미래) 값이 아니라 **가장 최근 실측치 또는 실측에 가장 가까운
  연도의 수치**를 TAM으로 우선 사용하세요. TAM은 "현재 시장이 얼마나 큰가"를 보여주는 것이지
  "미래에 얼마나 커질까"를 보여주는 지표가 아닙니다. 성장 전망(CAGR 등)은 별도로 언급해도 되지만,
  TAM 값 자체를 미래 예측치로 대체하지 마세요.
- 부득이하게 예측치밖에 없어 그 값을 TAM으로 쓸 경우, tam_year에 "(예측치)"를 함께 표기해
  실측치가 아님을 명확히 하세요.

매우 중요 — 출처 조작 금지:
- sam_ratio_reasoning, som_ratio_reasoning에는 위 fact 목록에 실제로 있는 내용만 근거로 인용하세요.
- 위 목록에 없는 리서치 기관명, 보고서 제목, 연도별 통계(예: "Statista 20xx 보고서", "CB Insights 분석")를
  지어내서 인용하지 마세요. 이는 존재하지 않는 출처를 만들어내는 것으로 절대 금지됩니다.
- fact 목록에 직접적 근거가 없어 컨설턴트로서의 일반적 경험/업계 관행으로 추정한 것이라면,
  반드시 "(업계 일반적 추정치, 별도 출처 없음)"이라고 명시하세요. 없는 출처를 만드느니
  "출처 없음"이라고 솔직히 쓰는 쪽이 훨씬 낫습니다."""

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=MARKET_SIZING_SCHEMA,
    )
    import json

    result = json.loads(response.choices[0].message.content)
    _flag_fabricated_citations(result, facts_text)
    return result


# fact 목록에 없는데 근거 설명에 등장하면 "출처 조작 의심"으로 취급할 리서치 기관/기관명 패턴.
# 완벽한 목록일 수 없으므로(휴리스틱), 여기 없는 가짜 출처는 못 걸러낼 수 있음.
KNOWN_RESEARCH_FIRMS = [
    "Statista", "Gartner", "McKinsey", "BCG", "IBISWorld", "CB Insights",
    "Deloitte", "PwC", "KPMG", "Forrester", "Nielsen", "IDC", "Frost & Sullivan",
    "통계청", "KOTRA", "산업연구원", "한국은행",
]


def _flag_fabricated_citations(result: dict, facts_text: str) -> None:
    """sam/som reasoning에 fact 목록에 없는 리서치 기관명이 등장하면 경고를 덧붙인다.
    (완전 자동 검증이 아니라 사람이 알아채기 쉽게 표시만 하는 수준의 안전장치)"""
    for key in ("sam_ratio_reasoning", "som_ratio_reasoning"):
        reasoning = result.get(key, "")
        for firm in KNOWN_RESEARCH_FIRMS:
            if firm.lower() in reasoning.lower() and firm.lower() not in facts_text.lower():
                result[key] = (
                    f"{reasoning} [⚠️ 자동검증 경고: '{firm}'는 수집된 fact 목록에 없는 출처입니다. "
                    f"LLM이 지어냈을 가능성이 높으니 이 근거는 사람이 직접 재확인하기 전까지 신뢰하지 마세요.]"
                )


def calculate_market_sizing(
    client: OpenAI,
    topic: str,
    target_market: str,
    facts: list[Fact],
    bottom_up_inputs: dict | None = None,
) -> MarketSizing:
    """
    TAM/SAM/SOM을 Top-down(+ 선택적으로 Bottom-up)으로 계산한다.

    bottom_up_inputs (선택): {"potential_customers": int, "avg_price_usd": float, "target_capture_rate": float}
    실제 사업모델 파라미터가 없으면 None으로 두고, Bottom-up은 계산하지 않고 assumptions에
    "데이터 부족으로 미계산"을 남긴다. 웹검색 fact만으로는 이 파라미터를 알 수 없기 때문이다.
    """
    assumptions: list[str] = []
    source_fact_ids = [f.id for f in facts]

    # --- Top-down: LLM이 숫자 해석/비율 제안, 코드가 실제 곱셈 계산 ---
    topdown = _estimate_topdown(client, topic, target_market, facts)

    tam_topdown = sam_topdown = som_topdown = None
    if topdown["tam_found"]:
        # 배율 환산은 코드가 한다(2026-07-28). LLM은 tam_value/tam_scale만 보고한다 —
        # 이전에는 LLM이 직접 USD로 환산하게 두었고, "116.13억 달러"를 116.13으로
        # 답하는 바람에 기획서에 "TAM 116 USD"가 찍히는 사고가 났다.
        raw_value = float(topdown.get("tam_value", 0) or 0)
        scale_word = topdown.get("tam_scale", "없음")
        multiplier = scale_to_multiplier(scale_word)
        tam_topdown = raw_value * multiplier
        sam_topdown = tam_topdown * topdown["sam_ratio"]
        som_topdown = sam_topdown * topdown["som_ratio"]

        scale_note = "" if multiplier == 1.0 else f" [원문 {raw_value:,.4g}{scale_word} x {multiplier:,.0f}]"
        assumptions.append(
            f"[Top-down] TAM={tam_topdown:,.0f} USD{scale_note} ({topdown['tam_year']} 기준, 근거: "
            f"\"{topdown['tam_source_snippet']}\")"
        )

        # 상식 검산 — 권역/국가 시장 TAM이 100만 USD 미만이면 배율 해석이 틀렸을 공산이 크다.
        # 값을 지우지 않고 경고를 남겨, 사람이 초안에서 바로 알아볼 수 있게 한다.
        if 0 < tam_topdown < _TAM_SANITY_MIN_USD:
            assumptions.append(
                f"⚠️ [검산 경고] TAM이 {tam_topdown:,.0f} USD로 계산되었습니다. 국가·권역 단위 "
                f"시장 규모로는 비정상적으로 작습니다(기준 {_TAM_SANITY_MIN_USD:,.0f} USD). "
                f"원문의 배율 단위(억/billion 등)를 잘못 읽었을 가능성이 있으니 "
                f"근거 문장을 직접 확인하십시오."
            )
        assumptions.append(
            f"[Top-down] SAM 비중={topdown['sam_ratio']:.2%} — {topdown['sam_ratio_reasoning']}"
        )
        assumptions.append(
            f"[Top-down] SOM 비중={topdown['som_ratio']:.2%} — {topdown['som_ratio_reasoning']}"
        )
    else:
        assumptions.append("[Top-down] facts 중 TAM으로 쓸 만한 시장규모 수치를 찾지 못함")

    # --- Bottom-up: 사업모델 파라미터가 주어졌을 때만 계산 ---
    tam_bottomup = sam_bottomup = som_bottomup = None
    if bottom_up_inputs:
        customers = bottom_up_inputs["potential_customers"]
        price = bottom_up_inputs["avg_price_usd"]
        capture_rate = bottom_up_inputs["target_capture_rate"]
        sam_bottomup = customers * price  # 잠재 고객 수 x 단가
        som_bottomup = sam_bottomup * capture_rate  # 확보 가능 점유율 적용
        if topdown["tam_found"] and topdown["sam_ratio"] > 0:
            tam_bottomup = sam_bottomup / topdown["sam_ratio"]  # 같은 sam_ratio로 역산
        assumptions.append(
            f"[Bottom-up] 잠재고객={customers:,}명 x 단가={price:,.0f} USD => SAM={sam_bottomup:,.0f} USD, "
            f"확보율={capture_rate:.2%} => SOM={som_bottomup:,.0f} USD"
        )
    else:
        assumptions.append(
            "[Bottom-up] 미계산 — 사업모델 파라미터(잠재고객 수, 단가, 목표 확보율)가 입력되지 않음. "
            "웹검색 fact만으로는 이 값을 알 수 없어 사용자 입력이 필요함."
        )

    # --- 교차검증: 두 SOM 값이 10배 이상 차이나면 discrepancy_flag ---
    discrepancy = False
    if som_topdown is not None and som_bottomup is not None:
        larger, smaller = max(som_topdown, som_bottomup), min(som_topdown, som_bottomup)
        if smaller > 0 and (larger / smaller) >= 10:
            discrepancy = True
            assumptions.append(
                f"[교차검증] Top-down SOM({som_topdown:,.0f})과 Bottom-up SOM({som_bottomup:,.0f})이 "
                f"10배 이상 차이남 — 가정치 재검토 필요. 보수적으로 Bottom-up 값을 우선 채택 권장."
            )

    sizing = MarketSizing(
        topic=topic,
        tam_topdown=tam_topdown,
        sam_topdown=sam_topdown,
        som_topdown=som_topdown,
        tam_bottomup=tam_bottomup,
        sam_bottomup=sam_bottomup,
        som_bottomup=som_bottomup,
        unit="USD",
        assumptions=assumptions,
        discrepancy_flag=discrepancy,
        source_fact_ids=source_fact_ids,
    )
    save_market_sizing(sizing)
    return sizing


def get_client() -> OpenAI:
    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 없습니다.")
    return OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")


def generate_research_questions(
    client: OpenAI, topic: str, target_market: str, n: int = 4
) -> list[str]:
    """주제+목표시장에 대한 핵심 리서치 질문 n개를 생성한다."""
    prompt = f"""당신은 20년 경력의 시장조사 컨설턴트입니다.
다음 사업 아이템에 대해 시장조사를 시작하려고 합니다.

연구대상(제품/서비스): {topic}
목표시장: {target_market}

시장 규모, 성장률, 핵심 고객, 진입 타이밍 등을 파악하기 위한 핵심 리서치 질문을 {n}개 작성하세요.
각 질문은 웹검색으로 답을 찾을 수 있는, 구체적이고 검색 가능한 형태여야 합니다."""

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=QUESTIONS_SCHEMA,
    )
    import json

    parsed = json.loads(response.choices[0].message.content)
    return parsed["questions"][:n]


# LLM이 "정보를 못 찾았다"는 말 자체를 fact처럼 채워 넣는 경우가 있어(실제 관찰됨),
# 프롬프트 지시만으로는 100% 안 걸러지므로 코드 레벨에서 한 번 더 필터링한다.
NO_INFO_PATTERNS = [
    "포함되어 있지 않습니다",
    "포함되어 있지 않",
    "제공되지 않았습니다",
    "제공되지 않",
    "찾을 수 없습니다",
    "찾을 수 없",
    "정보가 없습니다",
    "정보는 없습니다",
    "확인되지 않았습니다",
    "구체적인 정보는",
    "언급되지 않았습니다",
    "명시되어 있지 않",
]


def _is_no_info_statement(text: str) -> bool:
    return any(pattern in text for pattern in NO_INFO_PATTERNS)


SIMPLIFY_QUERY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "simplified_query",
        "schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "더 일반적이고 검색 가능성이 높은 형태로 재구성한 검색어",
                }
            },
            "required": ["query"],
        },
    },
}


def simplify_query(client: OpenAI, question: str) -> str:
    """이 질문으로 검색했는데 쓸만한 fact가 하나도 안 나왔을 때, 더 일반적인 검색어로
    재구성한다(파이프라인 문서 9절 recall 개선 아이디어 중 query rewriting 적용)."""
    prompt = f"""다음 리서치 질문은 너무 구체적이어서 검색결과에 답이 없었습니다.

원래 질문: {question}

이 질문의 핵심 의도는 유지하되, 검색엔진에서 결과가 나올 확률이 높도록 더 일반적이고
간결한 검색어로 재구성하세요. (예: 특정 연도·세부조건을 빼고 핵심 키워드 중심으로)"""

    import json

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=SIMPLIFY_QUERY_SCHEMA,
    )
    parsed = json.loads(response.choices[0].message.content)
    return parsed["query"]


def extract_facts(client: OpenAI, question: str, result: dict, topic: str, target_market: str) -> list[str]:
    """검색결과 하나(제목+본문)에서 fact 문장들을 추출한다.
    result['content']는 가능하면 페이지 실제 본문(fetch_full_text=True일 때), 없으면 스니펫.

    페이지 본문 전체를 넣기 시작한 뒤(recall 개선, 12절), 검색 질문과는 억지로 연결되지만
    실제로는 topic·target_market과 무관한 내용(예: 다른 국가/지역, 다른 제품 카테고리)까지
    fact로 뽑히는 문제가 관찰되어(파이프라인 문서 12-5절), topic·target_market 관련성
    체크를 프롬프트에 명시적으로 추가함."""
    content = result.get("content") or result.get("snippet", "")
    prompt = f"""리서치 질문: {question}
연구대상(제품/서비스): {topic}
목표시장: {target_market}

아래는 이 질문에 대한 웹검색 결과입니다. 페이지 본문 전체가 들어있을 수 있으므로,
이 중에는 리서치 질문과 우연히 겹치는 키워드가 있을 뿐 실제로는 무관한 내용도 섞여
있을 수 있습니다.

제목: {result['title']}
내용: {content}

이 내용에서 리서치 질문에 답이 되면서, 동시에 연구대상({topic})과 목표시장({target_market})에
실제로 관련 있는 검증 가능한 사실(수치, 통계, 정책, 트렌드 등)만 사실 하나당 한 줄로
뽑아내세요. 광고성 문구, 페이지 안내, 근거 없는 주장은 제외하세요.

중요 — 관련성 필터:
- 목표시장({target_market})과 다른 국가/지역 얘기(예: 목표시장이 북미인데 한국 시장 통계)는
  제외하세요.
- 연구대상({topic})과 다른 제품 카테고리 얘기(예: 웨어러블 헬스케어 기기가 아닌 카테터,
  일반 의료기기, 무관한 질병 통계)는 제외하세요.
- 쓸만한 내용이 없으면 반드시 빈 배열(facts: [])만 반환하세요.
- "정보가 없습니다", "포함되어 있지 않습니다" 같이 정보 부재를 설명하는 문장 자체를
  fact로 넣지 마세요. 그런 문장은 사실이 아니라 메타 발언입니다."""

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=FACTS_SCHEMA,
    )
    import json

    parsed = json.loads(response.choices[0].message.content)
    facts = parsed["facts"]
    # 프롬프트로 못 막은 "정보 없음" 메타 발언을 코드에서 한 번 더 제거 (이중 안전장치)
    return [f for f in facts if not _is_no_info_statement(f)]


def _search_extract_and_save(
    client: OpenAI,
    query: str,
    topic: str,
    target_market: str,
    results_per_question: int,
    all_facts: list[Fact],
    counters: dict,
) -> int:
    """질문(query) 하나에 대해 검색 -> 청크 필터링 -> fact 추출 -> Fact Store 저장 ->
    검증·출처 에이전트 채점까지 수행하고, 이번 질문에서 새로 다룬(신규+중복 포함) fact
    개수를 반환한다. fetch_full_text=True로 스니펫 대신 페이지 실제 본문을 우선
    활용한다(recall 개선, 9절).

    검증 단계(파이프라인 문서 13절): 본문이 길면 chunk_text()로 쪼갠 뒤 관련 있는
    청크만 남기고(CRAG decompose-then-recompose), 그렇게 걸러진 본문으로 fact를
    추출한다. 새로 저장된 fact는 검색결과 1건이 끝날 때마다가 아니라 이 질문(query)
    전체가 끝난 뒤 한 배치로 묶어 검증한다 — MAIN-RAG의 적응형 임계값 계산이
    배치 단위 점수 분포를 필요로 하기 때문이다."""
    results = search_web(query, max_results=results_per_question, fetch_full_text=True)
    log.info(f"  검색결과 {len(results)}건")

    n_facts_this_query = 0
    newly_saved_with_content: list[tuple[Fact, str]] = []
    for result in results:
        raw_content = result.get("content") or result.get("snippet", "")
        chunks = chunk_text(raw_content)
        filtered_content = filter_relevant_chunks(client, chunks, topic, target_market, query)
        if not filtered_content:
            log.info(f"  [청크필터] 관련 청크 없음 — 건너뜀: {result['url']}")
            continue
        result = {**result, "content": filtered_content}

        fact_texts = extract_facts(client, query, result, topic, target_market)
        for text in fact_texts:
            new_fact = Fact(
                id=f"fact_{uuid.uuid4().hex[:10]}",
                text=text,
                source_url=result["url"],
                source_tier=SourceTier(result["source_tier"]),
                retrieved_date=date.today(),
                topic_relevance=query,
                topic=topic,
            )
            stored_fact, is_new = save_fact_if_new(new_fact)
            all_facts.append(stored_fact)
            n_facts_this_query += 1
            if is_new:
                log.info(
                    f"  [fact 저장] ({stored_fact.source_tier.value}) {text}",
                    extra={
                        "kind": "fact",
                        "url": stored_fact.source_url,
                        "tier": stored_fact.source_tier.value,
                    },
                )
                counters["n_saved"] += 1
                newly_saved_with_content.append((stored_fact, filtered_content))
            else:
                log.info(f"  [중복 건너뜀 — 기존 {stored_fact.id}와 유사] {text}")
                counters["n_duplicates"] += 1

    if newly_saved_with_content:
        log.info(f"  [검증] 신규 fact {len(newly_saved_with_content)}개 배치 검증 중...")
        verify_facts_batch(client, newly_saved_with_content, topic, target_market)

    return n_facts_this_query


def run_targeted_research(
    topic: str,
    target_market: str,
    focus_query: str,
    results_per_question: int = 6,
    client: OpenAI | None = None,
) -> list[Fact]:
    """Router가 '투자/매출 정보 더 찾아줘'처럼 특정 항목을 콕 집어 재검색을 요청했을 때
    호출하는, 좁은 범위의 검색 함수(2026-07-24 추가, Router 설계안 3-4절).

    run_market_research()처럼 리서치 질문 여러 개를 새로 생성하지 않고, 주어진
    focus_query 하나만 검색해 Fact Store에 추가한다. 이미 있던 _search_extract_and_save()
    (검색 -> 청크 필터링 -> fact 추출 -> 저장 -> 배치 검증까지 수행)를 그대로 재사용하므로
    새로 만든 로직이 아니라 기존 검증된 흐름을 노출만 한 것이다.

    TAM/SAM/SOM 재계산은 여기서 하지 않는다 — 시장 규모를 다시 계산해야 하면 호출부가
    별도로 calculate_market_sizing()을 다시 부르면 된다(이 함수는 fact 보강만 책임진다).
    """
    init_db()
    if client is None:
        client = get_client()

    all_facts: list[Fact] = []
    counters = {"n_saved": 0, "n_duplicates": 0}
    log.info(f"[시장조사 에이전트-타겟검색] '{focus_query}' 검색 중...")
    n_found = _search_extract_and_save(
        client, focus_query, topic, target_market, results_per_question, all_facts, counters
    )

    if n_found == 0:
        retry_query = simplify_query(client, focus_query)
        log.info(f"  [재시도] 이 질의에서 fact를 못 찾음 → 더 일반적인 검색어로 재검색: {retry_query}")
        _search_extract_and_save(
            client, retry_query, topic, target_market, results_per_question, all_facts, counters
        )

    log.info(f"[시장조사 에이전트-타겟검색] fact {counters['n_saved']}개 신규 저장, "
          f"중복 {counters['n_duplicates']}개 건너뜀 (관련 fact 총 {len(all_facts)}개)")
    return all_facts


def run_market_research(
    topic: str,
    target_market: str,
    n_questions: int = 4,
    results_per_question: int = 6,
    bottom_up_inputs: dict | None = None,
) -> tuple[list[Fact], MarketSizing]:
    """전체 파이프라인 실행: 질문 생성 -> 웹검색 -> fact 추출 -> Fact Store 저장 -> TAM/SAM/SOM 계산

    recall 개선(파이프라인 문서 9절) 적용 내역:
    - results_per_question 기본값 4 -> 6
    - 스니펫 대신 페이지 실제 본문 활용(search_web(fetch_full_text=True))
    - 한 질문에서 fact를 하나도 못 뽑으면, 더 일반적인 검색어로 재구성해 1회 재검색(query rewriting)
    """
    init_db()
    client = get_client()

    log.info(f"[시장조사 에이전트] 연구대상: {topic} / 목표시장: {target_market}")
    questions = generate_research_questions(client, topic, target_market, n=n_questions)
    log.info(f"[시장조사 에이전트] 리서치 질문 {len(questions)}개 생성:")
    for q in questions:
        log.info(f"  - {q}")

    all_facts: list[Fact] = []
    counters = {"n_saved": 0, "n_duplicates": 0}
    for question in questions:
        log.info(f"\n[검색] {question}")
        n_this_q = _search_extract_and_save(
            client, question, topic, target_market, results_per_question, all_facts, counters
        )

        if n_this_q == 0:
            retry_query = simplify_query(client, question)
            log.info(f"  [재시도] 이 질문에서 fact를 못 찾음 → 더 일반적인 검색어로 재검색: {retry_query}")
            _search_extract_and_save(
                client, retry_query, topic, target_market, results_per_question, all_facts, counters
            )

    log.info(f"\n[시장조사 에이전트] fact {counters['n_saved']}개 신규 저장, 중복 {counters['n_duplicates']}개 건너뜀 "
          f"(관련 fact 총 {len(all_facts)}개)")

    log.info("\n[시장조사 에이전트] TAM/SAM/SOM 계산 중...")
    sizing = calculate_market_sizing(client, topic, target_market, all_facts, bottom_up_inputs)
    log.info(f"  TAM(Top-down): {sizing.tam_topdown:,.0f} {sizing.unit}" if sizing.tam_topdown else "  TAM(Top-down): 계산 불가")
    log.info(f"  SAM(Top-down): {sizing.sam_topdown:,.0f} {sizing.unit}" if sizing.sam_topdown else "  SAM(Top-down): 계산 불가")
    log.info(f"  SOM(Top-down): {sizing.som_topdown:,.0f} {sizing.unit}" if sizing.som_topdown else "  SOM(Top-down): 계산 불가")
    if sizing.som_bottomup:
        log.info(f"  SOM(Bottom-up): {sizing.som_bottomup:,.0f} {sizing.unit}")
    if sizing.discrepancy_flag:
        log.info("  ⚠️ Top-down/Bottom-up 10배 이상 차이 — 가정치 재검토 필요")
    log.info("  가정 및 근거:")
    for a in sizing.assumptions:
        log.info(f"    - {a}")

    return all_facts, sizing


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python -m agents.market_research "<연구대상>" "<목표시장>" [잠재고객수] [평균단가USD] [목표확보율]')
        print('예시(Bottom-up 없이): python -m agents.market_research "웨어러블 헬스케어 기기" "북미 시니어 건강관리 시장"')
        print('예시(Bottom-up 포함): python -m agents.market_research "..." "..." 50000 200 0.05')
        sys.exit(1)

    bu_inputs = None
    if len(sys.argv) >= 6:
        bu_inputs = {
            "potential_customers": int(sys.argv[3]),
            "avg_price_usd": float(sys.argv[4]),
            "target_capture_rate": float(sys.argv[5]),
        }

    run_market_research(topic=sys.argv[1], target_market=sys.argv[2], bottom_up_inputs=bu_inputs)
