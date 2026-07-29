"""
경쟁사비교 에이전트 (Day 5 프로토타입)

파이프라인 문서 3-4절 절차를 구현:
  1) 경쟁사 식별에 특화된 검색 질문 생성 (브랜드명, 시장 점유율, 가격, 기능 위주)
  2) 질문마다 웹검색(ddgs) 실행 -> 경쟁사 관련 fact 추출 -> Fact Store에 저장
     (시장조사 에이전트와 같은 Fact Store를 공유하므로, save_fact_if_new()로 저장해
     이미 있는 fact와 중복되면 자동으로 건너뜀)
  3) topic으로 필터링한 fact 전체(이번에 새로 모은 것 + 이전에 시장조사 에이전트가
     모아둔 것)에서, 실제로 언급된 경쟁사 후보를 LLM이 식별 (직접/간접(대체재)/잠재 진입자 분류)
  4) 경쟁사별로 "그 경쟁사가 언급된 fact만" 근거로 비교축(가격/핵심기능/타깃고객/채널/
     투자·매출/강점/약점)을 구조화
  5) Competitor 객체로 만들어 Fact Store(SQLite competitors 테이블)에 저장
  6) 경쟁사(행) x 비교축(열) 매트릭스 형태로 출력

주의: 시장조사 에이전트에서 겪은 "출처 조작(hallucination)" 문제를 반복하지 않도록,
프로필 구조화 단계는 반드시 주어진 fact만 근거로 쓰게 하고, 근거가 없는 항목은
지어내지 말고 빈 문자열/빈 배열로 남기도록 프롬프트에 명시한다.

client 생성 함수는 파일마다 중복 정의하지 않고 agents.market_research의
get_client()를 그대로 재사용한다 (파이프라인 문서 6-1절에서 지적한 중복 문제 완화).
"""

import json
import os
import uuid
from datetime import date
from typing import Optional

from openai import OpenAI

from agents.market_research import _is_unusable_fact, get_client, normalize_region, simplify_query
from agents.verification import filter_relevant_chunks, verify_facts_batch
from agents.web_search import chunk_text, search_web
from fact_store.schema import Competitor, CompetitorType, Fact, SourceTier, VerificationStatus
from fact_store.store import init_db, list_facts, save_competitor, save_fact_if_new

import logging

log = logging.getLogger(__name__)

HEAVY_MODEL = os.getenv("HEAVY_MODEL", "solar-pro2")

COMPETITOR_TYPE_VALUES = [t.value for t in CompetitorType]

QUERIES_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "competitor_search_queries",
        "schema": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "실제 경쟁 브랜드/기업명, 시장 점유율, 가격, 핵심 기능을 찾기 위한 검색 질문 목록",
                }
            },
            "required": ["queries"],
        },
    },
}

COMPETITOR_FACTS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "extracted_competitor_facts",
        "schema": {
            "type": "object",
            "properties": {
                # 2026-07-28 — market_research.FACTS_SCHEMA와 같은 이유로 객체 배열로
                # 바꿨다(결함 G). fact 문장에서 지역이 빠지면 관련성을 판정할 수 없다.
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": (
                                    "특정 기업/브랜드명이 실제로 등장하는 경쟁 관련 사실 하나를 한 줄로. "
                                    "이 문장만 따로 읽어도 '어느 시장의 어느 기업 이야기인지' 알 수 있게 "
                                    "지역을 문장 안에 포함할 것."
                                ),
                            },
                            "region": {
                                "type": "string",
                                "description": (
                                    "이 사실이 어느 지역 시장에 관한 것인지 원문 근거대로. "
                                    "예) '유럽', '한국', '미국', '북미', '글로벌'. 원문에 지역 근거가 "
                                    "없으면 '불명'. 추측해서 목표시장 이름을 적지 말 것."
                                ),
                            },
                        },
                        "required": ["text", "region"],
                    },
                    "description": (
                        "이 검색결과에서 뽑아낸 경쟁사 관련 사실들(가격, 기능, 시장점유율, 투자유치 등). "
                        "기업명이 특정되지 않는 일반론은 제외. 근거 될 만한 내용이 없으면 빈 배열."
                    ),
                }
            },
            "required": ["facts"],
        },
    },
}

IDENTIFY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "competitor_candidates",
        "schema": {
            "type": "object",
            "properties": {
                "competitors": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "실제 fact 목록에 등장하는 기업/브랜드명"},
                            "type": {"type": "string", "enum": COMPETITOR_TYPE_VALUES},
                            "mentioned_fact_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "이 경쟁사가 실제로 언급된 fact_id 목록 (반드시 주어진 fact_id 중에서만)",
                            },
                        },
                        "required": ["name", "type", "mentioned_fact_ids"],
                    },
                    "description": "fact 목록에 실제로 등장하는 경쟁사만. 목록에 없는 회사명을 지어내지 말 것.",
                }
            },
            "required": ["competitors"],
        },
    },
}

# 2026-07-22 실제 산출물(기획서 초안)에서 "Apple Inc"/"Apple", "OMRON Healthcare, Inc."/"오므론",
# "Koninklijke Philips N.V"/"필립스"처럼 PRODUCT_TO_COMPANY_MAP에 없는 새로운 표기 변형이
# 여전히 별도 경쟁사로 잡히는 문제가 관찰됨(파이프라인 문서 25절 참고). 하드코딩 사전을 계속
# 넓히는 방식은 새 표기가 나올 때마다 또 놓치는 한계가 있어, 최종 후보 리스트 전체를 한 번에
# 놓고 LLM이 직접 "같은 회사인지" 판단해 통합하는 마지막 단계를 추가한다.
CONSOLIDATION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "competitor_consolidation",
        "schema": {
            "type": "object",
            "properties": {
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "canonical_name": {
                                "type": "string",
                                "description": "이 그룹을 대표할 이름 (그룹 안에서 가장 널리 쓰이는/간결한 이름)",
                            },
                            "members": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "이 그룹에 속하는 이름들. 반드시 입력 후보명 목록에 있는 이름 그대로만 사용.",
                            },
                        },
                        "required": ["canonical_name", "members"],
                    },
                    "description": "입력 후보명 목록의 모든 이름이 정확히 하나의 그룹에 속해야 함(중복 없는 이름은 혼자 그룹을 이룸).",
                }
            },
            "required": ["groups"],
        },
    },
}

PROFILE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "competitor_profiles",
        "schema": {
            "type": "object",
            "properties": {
                "profiles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "price": {"type": "string", "description": "가격 정보. 근거 fact에 없으면 빈 문자열."},
                            "key_features": {"type": "array", "items": {"type": "string"}},
                            "target_customer": {"type": "string", "description": "근거 fact에 없으면 빈 문자열."},
                            "channel": {"type": "string", "description": "근거 fact에 없으면 빈 문자열."},
                            "funding_or_revenue": {
                                "type": "string",
                                "description": (
                                    "투자 유치·인수(피인수 포함)·매출액·기업가치 등 '돈과 직접 관련된 사실'. "
                                    "예: '2016년 Mars Petcare에 $117M에 인수됨', '시리즈B $20M 투자 유치', "
                                    "'연매출 500만 달러'. 이런 내용이 fact에 있으면 strengths가 아니라 "
                                    "반드시 이 필드에 넣을 것 — 피인수 사실이 '시장에서 인정받았다'는 "
                                    "의미로도 읽히더라도, 금액이 언급된 재무 사실 자체는 이 필드가 우선이다. "
                                    "근거 fact에 없으면 빈 문자열."
                                ),
                            },
                            "strengths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "기능·기술·시장 포지셔닝 등 정성적 장점만. 투자·인수·매출 등 금액이 있는 사실은 여기 말고 funding_or_revenue에 넣을 것.",
                            },
                            "weaknesses": {"type": "array", "items": {"type": "string"}},
                            "source_fact_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "이 프로필 내용의 근거가 된 fact_id (반드시 이 경쟁사에 배정된 fact_id 중에서만)",
                            },
                        },
                        "required": [
                            "name", "price", "key_features", "target_customer",
                            "channel", "funding_or_revenue", "strengths", "weaknesses",
                            "source_fact_ids",
                        ],
                    },
                }
            },
            "required": ["profiles"],
        },
    },
}


# 검색 질문 생성 프롬프트에 참고자료로 넣을 기존 fact 상한. 시장조사 단계에서 이미
# 수백 개가 쌓여 있을 수 있어 전부 넣으면 프롬프트가 과도하게 커지므로, 질문에 영감을
# 줄 정도의 샘플만 넣는다(전수 조사가 목적이 아니라 "이미 뭐가 언급됐는지 참고"가 목적).
EXISTING_FACTS_HINT_CAP = 30


def _existing_facts_hint_block(facts: list[Fact]) -> str:
    """이미 Fact Store에 있는 fact(주로 시장조사 단계에서 모은 것)를 검색 질문 생성 프롬프트에
    참고자료로 넣기 위한 텍스트 블록을 만든다. 없으면 빈 문자열을 반환한다."""
    if not facts:
        return ""
    sample = facts[:EXISTING_FACTS_HINT_CAP]
    lines = "\n".join(f"- {f.text}" for f in sample)
    return f"""

참고 — 이미 시장조사 단계에서 수집된 관련 fact 일부입니다(질문에 영감을 주는 참고자료일
뿐이니, 여기 내용을 그대로 베끼거나 이미 답이 나온 걸 다시 묻는 질문은 만들지 마세요):
{lines}

위에 특정 기업/브랜드명이 이미 언급돼 있다면, 그 기업의 정확한 가격·시장점유율·투자현황
등 더 구체적인 후속 질문을 우선적으로 만드세요."""


def generate_competitor_queries(
    client: OpenAI,
    topic: str,
    target_market: str,
    n: int = 3,
    existing_facts: Optional[list[Fact]] = None,
) -> list[str]:
    """경쟁사 식별에 특화된 검색 질문 n개를 생성한다 (일반 시장조사 질문과는 목적이 다름).

    2026-07-23 변경: 기존에는 topic·target_market 문자열만 보고 질문을 백지에서 생성해,
    시장조사 단계에서 이미 브랜드명이 언급된 fact가 있어도 전혀 참고하지 않는 문제가
    있었다(파이프라인 문서 30절 참고). existing_facts를 주면 프롬프트에 참고자료로
    넣어 더 맞춤화된(이미 언급된 브랜드를 겨냥한) 질문을 유도한다."""
    facts_hint = _existing_facts_hint_block(existing_facts or [])
    prompt = f"""당신은 20년 경력의 경쟁사 분석 컨설턴트입니다.

연구대상(제품/서비스): {topic}
목표시장: {target_market}

이 시장에서 실제로 경쟁하는 기업/브랜드명, 시장 점유율 순위, 가격, 핵심 기능을 찾기 위한
검색 질문을 {n}개 작성하세요. 각 질문은 "구체적인 기업명이 검색결과에 나올 가능성이 높은"
형태여야 합니다 (예: "~시장 점유율 1~3위 기업", "~ 브랜드별 가격 비교").{facts_hint}"""

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=QUERIES_SCHEMA,
    )
    parsed = json.loads(response.choices[0].message.content)
    return parsed["queries"][:n]


def extract_competitor_facts(
    client: OpenAI, query: str, result: dict, topic: str, target_market: str
) -> list[tuple[str, Optional[str]]]:
    """검색결과 하나(제목+본문)에서 '특정 기업명이 등장하는' 경쟁사 관련 fact를 추출한다.
    result['content']는 가능하면 페이지 실제 본문(fetch_full_text=True일 때), 없으면 스니펫.

    페이지 본문 전체를 넣기 시작한 뒤(recall 개선, 12절), topic·target_market과 무관한
    내용(다른 국가/지역, 다른 제품 카테고리 회사)까지 경쟁사로 뽑히는 문제가 관찰되어
    (파이프라인 문서 12-5절), 관련성 체크를 프롬프트에 명시적으로 추가함."""
    content = result.get("content") or result.get("snippet", "")
    prompt = f"""검색 질문: {query}
연구대상(제품/서비스): {topic}
목표시장: {target_market}

아래는 이 질문에 대한 웹검색 결과입니다. 페이지 본문 전체가 들어있을 수 있으므로,
리서치 질문과 우연히 겹치는 키워드가 있을 뿐 실제로는 무관한 내용도 섞여 있을 수 있습니다.

제목: {result['title']}
내용: {content}

이 내용에서 실제 기업/브랜드명이 명시되면서, 동시에 연구대상({topic})과 목표시장
({target_market})에 실제로 관련 있는 경쟁 관련 사실(가격, 기능, 시장점유율, 투자유치,
매출 등)만 사실 하나당 한 줄로 뽑아내세요. 기업명이 특정되지 않는 일반적인 시장 설명은
제외하세요.

중요 — 관련성 필터:
- 목표시장({target_market})과 다른 국가/지역의 회사·통계(예: 목표시장이 북미인데 한국
  시장 사례)는 제외하세요.
- 연구대상({topic})과 다른 제품 카테고리의 회사(예: 웨어러블 헬스케어 기기가 아닌
  카테터·IV 의료기기 제조사, 건설사의 부대시설 얘기)는 제외하세요.
- 쓸만한 내용이 없으면 반드시 빈 배열(facts: [])만 반환하세요. "정보가 없습니다" 같은
  정보 부재 설명 문장 자체를 fact로 넣지 마세요.

매우 중요 — 각 fact는 혼자서도 읽히게 쓰세요:
- fact 문장은 나중에 원문 없이 따로 읽힙니다. **어느 시장의 어느 기업 이야기인지**를
  문장 안에 넣으세요.

  (나쁨) "2024년 51%의 시장 점유율을 차지했다"
         → 누가, 어느 시장에서인지 알 수 없습니다.
  (좋음) "테트라팍 등 상위 5개사가 2024년 유럽 친환경 포장재 시장에서 51%를 차지했다"

- region 필드에는 그 사실이 **어느 지역 시장에 관한 것인지 원문 근거대로** 적으세요.
  원문에 근거가 없으면 "불명"으로 두고, 목표시장({target_market})을 베껴 적지 마세요."""

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=COMPETITOR_FACTS_SCHEMA,
    )
    parsed = json.loads(response.choices[0].message.content)
    out: list[tuple[str, Optional[str]]] = []
    for item in parsed["facts"]:
        if isinstance(item, str):          # 구조화 출력이 계약을 어긴 경우 대비
            text, region = item, None
        else:
            text, region = item.get("text", ""), item.get("region")
        if not text or _is_unusable_fact(text):
            continue
        out.append((text, normalize_region(region)))
    return out


# 경쟁사가 아닌데 fact에 자주 같이 등장해 잘못 식별될 수 있는 정부기관/규제기관/표준기구 이름
# 휴리스틱 목록. 실제로 "FDA"가 경쟁사로 잘못 식별된 사례가 관찰되어 추가함(코드 레벨 이중 안전장치).
# 완벽한 목록일 수 없으므로, 여기 없는 다른 비경쟁 기관명은 여전히 놓칠 수 있음.
NON_COMPETITOR_ENTITY_PATTERNS = [
    "FDA", "식약처", "식품의약품안전처", "ISO", "통계청", "KOTRA", "산업연구원",
    "한국은행", "FCC", "CE 인증", "보건복지부", "질병관리청", "CDC",
]


def _is_non_competitor_entity(name: str) -> bool:
    return any(pattern.lower() in name.lower() for pattern in NON_COMPETITOR_ENTITY_PATTERNS)


# 한 번의 LLM 호출에 넣을 fact 수 상한(파이프라인 문서 22절 참고). identify_competitors()는
# fact가 많아지면(이번 실행에서 455개) 경쟁사마다 mentioned_fact_ids 배열이 길어져
# build_competitor_profiles()와 같은 이유로 응답 JSON이 잘리는 문제가 있었다.
IDENTIFY_BATCH_SIZE = 60


def _consolidate_duplicate_competitors(client: OpenAI, candidates: list[dict]) -> list[dict]:
    """배치 병합(같은 이름 정규화)까지 끝난 최종 후보 리스트를 한 번에 놓고, 표기만
    다를 뿐 실제로는 같은 회사인 항목을 LLM으로 통합한다.

    PRODUCT_TO_COMPANY_MAP 기반 정규화(코드 레벨)는 미리 등록해둔 표기만 병합하므로,
    거기 없는 새로운 변형(2026-07-22 실제 산출물에서 관찰된 "Apple Inc" vs "Apple",
    "OMRON Healthcare, Inc." vs "오므론", "Koninklijke Philips N.V" vs "필립스")은
    여전히 별도 항목으로 남는다. 하드코딩 사전을 계속 넓히는 대신, 최종 후보명 전체를
    한 번에 LLM에게 보여주고 "같은 회사인지" 직접 판단하게 하는 마지막 안전장치를
    추가한다(파이프라인 문서 25절 참고)."""
    if len(candidates) <= 1:
        return candidates

    names_block = "\n".join(f"- {c['name']}" for c in candidates)
    prompt = f"""당신은 20년 경력의 경쟁사 분석 컨설턴트입니다. 아래는 식별된 경쟁사 후보명
목록입니다. 이 중 표기만 다를 뿐 실제로는 같은 회사를 가리키는 이름이 있으면 그룹으로
묶어주세요 (예: "Apple Inc"와 "Apple", "OMRON Healthcare, Inc."와 "오므론",
"Koninklijke Philips N.V"와 "필립스"는 각각 같은 회사입니다).

후보명 목록:
{names_block}

중요:
- 목록에 있는 이름만 정확히 그대로 사용하세요. 새 이름을 지어내지 마세요.
- 정말 같은 회사인 경우에만 묶으세요. 이름이 비슷해 보여도 실제로 다른 회사면 묶지 마세요.
- 목록의 모든 이름이 정확히 하나의 그룹에 속해야 합니다 — 중복이 없는 이름도 혼자 그룹을
  이뤄서 반드시 결과에 포함하세요(목록에서 빠뜨리지 마세요).
- canonical_name은 그 그룹 안에서 가장 널리 쓰이는/간결한 이름으로 고르세요."""

    response = client.chat.completions.create(
        model=HEAVY_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=CONSOLIDATION_SCHEMA,
    )
    parsed = json.loads(response.choices[0].message.content)
    groups = parsed["groups"]

    by_name = {c["name"]: c for c in candidates}
    consolidated: list[dict] = []
    seen_names: set = set()

    for g in groups:
        members = [m for m in g["members"] if m in by_name]
        if not members:
            continue
        seen_names.update(members)
        if len(members) == 1:
            consolidated.append(by_name[members[0]])
            continue
        # 여러 표기를 하나로 합친다 — fact 언급이 가장 많은 항목의 type을 기준으로 쓰고,
        # mentioned_fact_ids는 전부 합집합으로 합친다(기존 배치 병합 로직과 같은 원칙).
        base = max((by_name[m] for m in members), key=lambda c: len(c.get("mentioned_fact_ids", [])))
        merged_ids: set = set()
        for m in members:
            merged_ids.update(by_name[m].get("mentioned_fact_ids", []))
        log.info(f"  [엔티티 통합] {', '.join(members)} → {g['canonical_name']}")
        consolidated.append({**base, "name": g["canonical_name"], "mentioned_fact_ids": list(merged_ids)})

    # LLM이 목록의 이름을 하나라도 그룹에서 빠뜨릴 수 있어(완전한 커버리지가 보장되지 않음),
    # 코드 레벨에서 누락분을 단독 항목으로 그대로 추가한다(이중 안전장치).
    for c in candidates:
        if c["name"] not in seen_names:
            consolidated.append(c)

    return consolidated


def identify_competitors(client: OpenAI, facts: list[Fact]) -> list[dict]:
    """fact 목록에서 실제로 언급된 경쟁사 후보를 식별하고 직접/간접/잠재 진입자로 분류한다.
    fact를 IDENTIFY_BATCH_SIZE개씩 나눠 여러 번 호출한 뒤, 같은 회사로 정규화되는
    이름(대소문자 무시 + PRODUCT_TO_COMPANY_MAP 정규화)은 mentioned_fact_ids를
    합쳐 하나로 병합한다.

    2026-07-22 재검증 실행에서 "애플"·"애플워치"·"애플 헬스킷"이 실제로는 같은 회사인데
    프롬프트의 "브랜드명이 언급될 때마다 빠짐없이 별도 항목으로 포함하라"는 완전성 지시
    (recall 확보 목적) 때문에 3개의 별도 경쟁사로 쪼개지는 문제가 관찰됨. 이중 안전장치로
    대응: (1) 프롬프트에 "같은 모기업의 제품·서비스·플랫폼명은 모기업명 하나로 통합하라"는
    지시 추가, (2) 병합 시 `_canonical_company_name()`으로 이름을 정규화한 뒤 키로 사용.

    한계: 배치가 나뉘면서 같은 회사가 PRODUCT_TO_COMPANY_MAP에 없는 새로운 표기(예: 매핑에
    없는 제품명, 두 표기 모두 신조어)로 식별될 경우 여전히 병합되지 않고 별도 항목으로
    남을 수 있다 — 11-2절에서 이미 기록된 거짓 양성/중복 표기 한계와 같은 종류의 문제로,
    완전히 해결된 것은 아니다."""
    if not facts:
        return []

    merged: dict[str, dict] = {}
    all_dropped: list[str] = []

    for batch in [facts[i : i + IDENTIFY_BATCH_SIZE] for i in range(0, len(facts), IDENTIFY_BATCH_SIZE)]:
        facts_block = "\n".join(f"- id={f.id}: {f.text}" for f in batch)
        prompt = f"""당신은 20년 경력의 경쟁사 분석 컨설턴트입니다. 아래 fact 목록에서 실제로 언급된
경쟁사(기업/브랜드명)를 찾아 분류하세요.

분류 기준:
- 직접 경쟁자: 동일한 제품/서비스로 같은 고객을 두고 경쟁
- 간접 경쟁자(대체재): 다른 방식이지만 같은 문제를 해결하는 대안
- 잠재 진입자: 아직 이 시장에 없지만 진입 가능성이 있는 인접 산업 기업

fact 목록:
{facts_block}

중요:
- 위 fact 목록에 실제로 이름이 등장하는 기업만 포함하세요. 목록에 없는 회사명을 지어내지 마세요.
- 가장 유명하거나 눈에 띄는 기업 하나만 고르지 마세요. fact 목록 전체를 끝까지 훑어서,
  서로 다른 "회사"가 언급될 때마다 빠짐없이 별도 항목으로 포함하세요
  (예: 애플, 핏빗, 가민, 삼성, 화웨이가 각각 언급되어 있다면 5개 모두 별도 항목).
- 단, 같은 모기업의 제품명·서비스명·플랫폼명이 다른 표현으로 언급되더라도 실제로는
  같은 회사면 절대 별도 항목으로 나누지 말고 모기업명 하나로 통합하세요
  (예: "애플워치"와 "애플 헬스킷"은 둘 다 "애플"로 통합, "갤럭시 워치"는 "삼성"으로 통합).
  즉 "서로 다른 회사인지"가 기준이지, "표현이 다른지"가 기준이 아닙니다.
- 정부기관·규제기관·표준기구(예: FDA, 식약처, ISO, 통계청)는 시장에서 제품/서비스로
  경쟁하는 주체가 아니므로 절대 경쟁사로 포함하지 마세요. fact에 "OO가 FDA 승인을 받았다"처럼
  규제기관이 언급되더라도, 그건 그 기업(OO)의 속성일 뿐 FDA 자체를 경쟁사로 넣으라는 뜻이
  아닙니다.
- mentioned_fact_ids에는 그 경쟁사가 실제로 언급된 fact_id만 넣으세요."""

        response = client.chat.completions.create(
            model=HEAVY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=IDENTIFY_SCHEMA,
        )
        parsed = json.loads(response.choices[0].message.content)
        candidates = parsed["competitors"]

        # 프롬프트 지시만으로 100% 안 걸러질 수 있어 코드 레벨에서 한 번 더 제거한다(이중 안전장치).
        # NO_INFO_PATTERNS(시장조사 에이전트)와 같은 패턴 — 실제로 FDA가 경쟁사로 잘못
        # 식별된 사례가 관찰됨(파이프라인 문서 11-5절 참고).
        filtered = [c for c in candidates if not _is_non_competitor_entity(c["name"])]
        all_dropped.extend(c["name"] for c in candidates if c not in filtered)

        for c in filtered:
            # 이름을 회사 단위로 정규화한 뒤 병합 키로 쓴다 — "애플워치"/"애플 헬스킷"이
            # 프롬프트 지시를 못 따라도 여기서 "Apple"로 합쳐지도록 하는 코드 레벨 안전장치.
            canonical_name = _canonical_company_name(c["name"])
            key = canonical_name.strip().lower()
            if key in merged:
                existing_ids = set(merged[key]["mentioned_fact_ids"])
                existing_ids.update(c["mentioned_fact_ids"])
                merged[key]["mentioned_fact_ids"] = list(existing_ids)
            else:
                merged[key] = {**c, "name": canonical_name}

    if all_dropped:
        log.info(f"  [필터링] 경쟁사가 아닌 것으로 판단해 제외: {all_dropped}")

    result = list(merged.values())
    # 배치 병합 + 코드 레벨 정규화까지 끝난 뒤에도, PRODUCT_TO_COMPANY_MAP에 없는 새로운
    # 표기 변형(예: "Apple Inc" vs "Apple")이 남을 수 있어 마지막으로 LLM 통합 단계를
    # 한 번 더 거친다.
    result = _consolidate_duplicate_competitors(client, result)
    return result


# 이 시장(웨어러블 헬스케어)에서 자주 언급되는 브랜드명 휴리스틱 목록.
# identify_competitors()가 fact에 실제로 등장하는 브랜드를 놓쳤는지 코드 레벨에서
# 한 번 더 점검하기 위한 이중 안전장치 — KNOWN_RESEARCH_FIRMS/_flag_fabricated_citations와
# 반대 방향(있는데 못 찾은 것)의 완전성 체크. 목록에 없는 브랜드가 새로 등장하면 여전히
# 놓칠 수 있다는 한계가 있음(완벽한 목록일 수 없는 휴리스틱).
KNOWN_COMPETITOR_BRANDS = [
    "애플", "Apple", "애플워치",
    "핏빗", "Fitbit", "핏비트",
    "가민", "Garmin",
    "삼성", "갤럭시", "Galaxy", "Samsung",
    "화웨이", "Huawei",
    "샤오미", "Xiaomi",
    "구글", "Google", "Fitbit Sense",
    "오라링", "Oura",
    "Whoop",
]


def _flag_missed_competitor_mentions(facts: list[Fact], candidates: list[dict]) -> list[str]:
    """fact 텍스트에 등장하는 알려진 브랜드명 중, identify_competitors()가 후보로
    포함하지 않은 것이 있으면 경고를 출력한다 (완전 자동 보정이 아니라 사람이
    알아채기 쉽게 표시만 하는 수준의 안전장치)."""
    candidate_names_lower = [c["name"].lower() for c in candidates]
    mentioned_brands = {
        brand for brand in KNOWN_COMPETITOR_BRANDS
        if any(brand.lower() in f.text.lower() for f in facts)
    }
    missed = sorted(
        brand for brand in mentioned_brands
        if not any(brand.lower() in name or name in brand.lower() for name in candidate_names_lower)
    )
    if missed:
        log.info(f"  [⚠️ 완전성 경고] fact에 언급된 것으로 보이나 경쟁사 후보에서 누락된 브랜드명: {missed}"
              f" — identify_competitors()가 놓쳤을 가능성이 있으니 원본 fact를 사람이 재확인하세요.")
    return missed


# 유형별 경쟁사 표시 상한(2026-07-23 산출물 검토에서 도입, 파이프라인 문서 27절 참고).
# identify_competitors()가 fact에 이름이 한 번이라도 언급되면 다 후보로 잡다 보니(recall
# 우선 설계), 특히 "잠재 진입자"가 7개까지 늘어나 기획서 4절 표가 3페이지로 늘어지는
# 문제가 실제 산출물에서 발견됨. KOSENA 강의자료(M2.3절, "직접 3+간접 2+잠재 1")를
# 참고해 상한을 정함 — 회사 수를 늘리는 게 아니라 비교 항목을 촘촘히 채우는 게 목적이라는
# KOSENA의 원래 취지에 맞춤. 직접 경쟁자는 KOSENA 권장(3개)보다 조금 여유를 둬서 5개로 함
# (실제 근거량 분포를 보면 5위 안에서도 근거 fact 수 차이가 뚜렷해 변별력이 있었음).
DIRECT_COMPETITOR_CAP = 5
INDIRECT_COMPETITOR_CAP = 3
POTENTIAL_COMPETITOR_CAP = 2

_COMPETITOR_TYPE_CAPS = {
    CompetitorType.DIRECT.value: DIRECT_COMPETITOR_CAP,
    CompetitorType.INDIRECT.value: INDIRECT_COMPETITOR_CAP,
    CompetitorType.POTENTIAL.value: POTENTIAL_COMPETITOR_CAP,
}

# source_tier 문자열("1차"/"2차"/"3차")을 정렬용 점수로 변환 — 숫자가 클수록 신뢰도 높음.
_SOURCE_TIER_RANK = {
    SourceTier.PRIMARY.value: 2,
    SourceTier.SECONDARY.value: 1,
    SourceTier.TERTIARY.value: 0,
}


def _competitor_sort_key(candidate: dict, facts_by_id: dict[str, Fact]) -> tuple:
    """유형별 상한을 적용하기 전, 같은 유형 안에서 어떤 경쟁사를 남길지 정하는 정렬 키.

    2026-07-23 실제 데이터로 확인한 결과, price/channel/funding_or_revenue 필드는
    Apple·Samsung처럼 잘 알려진 회사조차 대부분 비어 있어(각각 6%/0%/12% 채움률)
    "채워진 필드 개수"는 변별력이 없었다(전부 4~5개로 몰림). 대신 실제로 차이가 나는
    지표인 근거 fact 개수(mentioned_fact_ids)를 1순위 기준으로 쓴다.

    1순위: 근거 fact 개수 (많을수록 시장에서의 존재감이 크다는 대리지표)
    2순위(동점 시): 근거 fact 중 검증 에이전트가 매긴 verification_score 최고값
                    (같은 1건이라도 더 확실하게 검증된 사실을 가진 쪽을 우선)
    3순위(그래도 동점 시): 근거 fact 중 source_tier 최고값 (1차>2차>3차)
    그래도 전부 동점이면 Python sorted()가 안정 정렬(stable sort)이라 identify_competitors()가
    찾아낸 원래 순서가 그대로 유지된다 — 의미 있는 기준은 아니지만 실행마다 결과가
    흔들리지 않게 하는 최종 폴백 역할."""
    mentioned_ids = candidate.get("mentioned_fact_ids", [])
    mentioned_facts = [facts_by_id[fid] for fid in mentioned_ids if fid in facts_by_id]
    fact_count = len(mentioned_ids)
    best_score = max((f.verification_score or 0 for f in mentioned_facts), default=0)
    best_tier = max(
        (_SOURCE_TIER_RANK.get(f.source_tier.value, 0) for f in mentioned_facts), default=0
    )
    return (-fact_count, -best_score, -best_tier)


def select_top_competitors(candidates: list[dict], facts: list[Fact]) -> list[dict]:
    """유형(직접/간접/잠재)별로 상한을 두고, _competitor_sort_key() 기준 상위 N개만 남긴다.
    deep_dive_competitors()·build_competitor_profiles() 이전에 호출해서, 이후 단계의
    검색·LLM 호출 비용도 같이 줄인다."""
    facts_by_id = {f.id: f for f in facts}
    by_type: dict[str, list[dict]] = {}
    for c in candidates:
        by_type.setdefault(c["type"], []).append(c)

    selected: list[dict] = []
    for type_value, group in by_type.items():
        cap = _COMPETITOR_TYPE_CAPS.get(type_value, len(group))
        ranked = sorted(group, key=lambda c: _competitor_sort_key(c, facts_by_id))
        kept, dropped = ranked[:cap], ranked[cap:]
        if dropped:
            log.info(
                f"  [경쟁사 상한 적용] {type_value}: {len(group)}개 중 상위 {cap}개만 유지 "
                f"({', '.join(c['name'] for c in kept)}), 제외: {[c['name'] for c in dropped]}"
            )
        selected.extend(kept)
    return selected


# 한 번의 LLM 호출에 처리하는 경쟁사 수 상한(파이프라인 문서 22절 참고). 경쟁사가
# 많아지면(딥다이브까지 거치면 20개 이상도 흔함) 응답 JSON이 모델의 출력 토큰 한도를
# 넘어 중간에 잘리는 문제가 실제로 발생했음 — 이 함수에서 최초로 관찰된 문제라
# PESTEL 쪽(tag_facts/summarize_by_axis)에도 같은 배치 처리를 적용했다.
PROFILE_BATCH_SIZE = 8


def build_competitor_profiles(client: OpenAI, facts: list[Fact], candidates: list[dict]) -> list[dict]:
    """식별된 경쟁사 후보마다, 그 경쟁사가 언급된 fact만 근거로 비교 프로필을 구조화한다.
    후보를 PROFILE_BATCH_SIZE개씩 나눠 여러 번 호출한다."""
    if not candidates:
        return []

    facts_by_id = {f.id: f for f in facts}
    all_profiles: list[dict] = []

    for i in range(0, len(candidates), PROFILE_BATCH_SIZE):
        batch = candidates[i : i + PROFILE_BATCH_SIZE]
        blocks = []
        for c in batch:
            mentioned = [facts_by_id[fid] for fid in c["mentioned_fact_ids"] if fid in facts_by_id]
            lines = "\n".join(f"    - id={f.id}: {f.text}" for f in mentioned) or "    (근거 fact 없음)"
            blocks.append(f"- {c['name']} ({c['type']})\n{lines}")
        candidates_block = "\n".join(blocks)

        prompt = f"""당신은 20년 경력의 경쟁사 분석 컨설턴트입니다. 아래는 경쟁사 후보와 각 경쟁사가
언급된 fact 목록입니다.

{candidates_block}

각 경쟁사마다 비교 프로필(가격, 핵심기능, 타깃고객, 채널, 투자·매출 규모, 강점, 약점)을
작성하세요.

필드 구분 기준(중요 — 2026-07-24 추가, 실제 산출물에서 재무 정보가 strengths로 잘못
분류된 사례 발견):
- 투자 유치, 인수(피인수 포함), 매출액, 기업가치처럼 "금액이 언급된 재무 사실"은
  strengths가 아니라 반드시 funding_or_revenue 필드에 넣으세요. 예: "2016년 Mars
  Petcare에 $117M에 인수됨"은 강점이 아니라 funding_or_revenue에 들어가야 합니다 —
  피인수 사실이 시장에서의 인지도를 보여주는 지표로도 읽히지만, 금액이 있는 재무
  사실은 재무 필드가 우선입니다.
- strengths/weaknesses에는 기능·기술·시장 포지셔닝처럼 금액이 없는 정성적 장단점만
  담으세요.

매우 중요 — 출처 조작 금지:
- 반드시 해당 경쟁사 아래 나열된 fact 내용만 근거로 쓰세요.
- fact에 없는 정보(예: 가격, 투자 규모)는 절대 지어내지 말고, 해당 필드를 빈 문자열
  또는 빈 배열로 남기세요. "추정치입니다" 같은 표현으로 없는 숫자를 채우지 마세요.
- source_fact_ids에는 실제로 이 프로필 작성에 쓴 fact_id만 넣으세요."""

        response = client.chat.completions.create(
            model=HEAVY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=PROFILE_SCHEMA,
        )
        parsed = json.loads(response.choices[0].message.content)
        all_profiles.extend(parsed["profiles"])

    return all_profiles


def print_comparison_table(competitors: list[Competitor]) -> None:
    """경쟁사(행) x 비교축(열) 형태로 콘솔에 출력한다 (파이프라인 문서 3-4절)."""
    if not competitors:
        log.info("[경쟁사비교 에이전트] 식별된 경쟁사가 없습니다.")
        return

    for c in competitors:
        log.info(f"\n=== {c.name} ({c.type.value}) ===")
        log.info(f"  가격: {c.price or '(정보 없음)'}")
        log.info(f"  핵심 기능: {', '.join(c.key_features) or '(정보 없음)'}")
        log.info(f"  타깃 고객: {c.target_customer or '(정보 없음)'}")
        log.info(f"  채널: {c.channel or '(정보 없음)'}")
        log.info(f"  투자/매출: {c.funding_or_revenue or '(정보 없음)'}")
        log.info(f"  강점: {', '.join(c.strengths) or '(정보 없음)'}")
        log.info(f"  약점: {', '.join(c.weaknesses) or '(정보 없음)'}")
        log.info(f"  근거 fact: {c.source_fact_ids}")


def _search_extract_and_save(
    client: OpenAI,
    query: str,
    topic: str,
    target_market: str,
    results_per_query: int,
    run_facts: list[Fact],
    counters: dict,
) -> int:
    """질문(query) 하나에 대해 검색 -> 청크 필터링 -> 경쟁사 관련 fact 추출 -> Fact Store
    저장 -> 검증·출처 에이전트 채점까지 수행하고, 이번 질문에서 새로 다룬(신규+중복 포함)
    fact 개수를 반환한다. fetch_full_text=True로 스니펫 대신 페이지 실제 본문을 우선
    활용한다(recall 개선, 9절). 검증 단계 설계는 market_research.py와 동일
    (파이프라인 문서 13절 참고)."""
    results = search_web(query, max_results=results_per_query, fetch_full_text=True)
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

        extracted = extract_competitor_facts(client, query, result, topic, target_market)
        for text, region in extracted:
            new_fact = Fact(
                id=f"fact_{uuid.uuid4().hex[:10]}",
                text=text,
                source_url=result["url"],
                source_tier=SourceTier(result["source_tier"]),
                retrieved_date=date.today(),
                topic_relevance=query,
                topic=topic,
                region=region,          # 2026-07-28: 결함 G
            )
            stored_fact, is_new = save_fact_if_new(new_fact)
            run_facts.append(stored_fact)
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


# 심층조사(3단계) 대상 직접 경쟁자 수 상한. 식별 단계에서 후보가 20개 넘게 나올 수 있는데
# (실제로 24개까지 관찰됨), 전부에 개별 검색을 돌리면 검색·LLM 채점 비용이 몇 배로
# 늘어나므로 상위 N개로만 제한한다 — 파이프라인 문서 14절 참고.
DEEP_DIVE_TOP_N = 5
DEEP_DIVE_RESULTS_PER_QUERY = 4


# 가격 비교 리뷰 기사 질의를 영어로 할지 한국어로 할지 판단하는 키워드 목록(2026-07-23,
# 파이프라인 문서 31절). 목표시장이 북미/영어권이면 영어 리뷰 기사가 압도적으로 많아
# 영어로 질의하고(_deep_dive_queries 원래 설계 근거), 그 외(국내·한국 등)는 한국어 비교
# 리뷰 기사를 타겟팅한다. 완벽한 언어 감지가 아니라, 이 프로젝트가 실제로 다룰 법한
# 목표시장 표현들을 커버하는 휴리스틱이므로, 목록에 없는 새로운 지역 표현은 기본값(한국어)로
# 처리된다는 한계가 있다.
# 2026-07-28 추가 — 유럽이 빠져 있어 실제 사고가 났다. 목표시장이 "유럽 B2B 유통 시장"인
# 실행에서 이 목록에 걸리지 않아 한국어 질의("테트라팍 가격 비교 리뷰 추천 2026")가 나갔고,
# 유럽 B2B 포장재 기업 9곳의 가격을 하나도 못 건졌다. 유럽 기업의 가격·리뷰 정보는 영어
# 기사에 압도적으로 많으므로 영어권과 같은 취급을 한다.
_ENGLISH_REVIEW_MARKET_KEYWORDS = [
    "북미", "미국", "캐나다", "영어권",
    "north america", "usa", "u.s.", "united states", "canada",
    # 유럽 (2026-07-28 추가)
    "유럽", "eu", "europe", "european", "영국", "독일", "프랑스", "네덜란드",
    "uk", "united kingdom", "germany", "france", "netherlands",
    # 그 밖의 영어 우세 시장
    "호주", "싱가포르", "australia", "singapore", "global", "글로벌",
]


def _use_english_price_query(target_market: str) -> bool:
    market_lower = target_market.lower()
    return any(kw.lower() in market_lower for kw in _ENGLISH_REVIEW_MARKET_KEYWORDS)


def _deep_dive_queries(name: str, target_market: str = "",
                       current_year: Optional[int] = None) -> list[str]:
    """경쟁사 이름이 이미 확정된 상태이므로, 시장조사 단계(generate_competitor_queries)처럼
    LLM으로 질문을 새로 만들 필요 없이 고정 템플릿으로 가격·투자매출·판매채널을 겨냥한
    질의를 만든다 — 회사명이 정해진 뒤의 질문 생성에 LLM 호출을 쓰는 건 낭비라고 판단.

    가격 질의(파이프라인 문서 18절)는 애초에 "{name} 가격 공식 홈페이지 제품"이었으나,
    실행 결과 5개 경쟁사 전부 가격을 하나도 못 건졌다. 원인은 (1) 공식 홈페이지·쇼핑몰은
    가격을 자바스크립트로 렌더링하는 경우가 많아 지금의 requests+정규식 방식으로는 애초에
    가격 숫자가 안 보이고, (2) 설령 정적 HTML이어도 봇 차단(CAPTCHA 등)에 걸리기 쉽다는 점.
    이를 헤드리스 브라우저 도입으로 우회하는 대신(속도·봇차단 리스크가 더 크다고 판단),
    "가격 비교 리뷰 기사"(예: "best smartwatch 2026" 류의 정리 글)를 타겟팅하는 쪽으로
    질의를 바꿨다 — 이런 글들은 대체로 정적 HTML로 서버 렌더링되고 봇 차단도 덜하면서,
    이미 여러 제품 가격을 표로 정리해두는 경우가 많다.

    2026-07-23 변경: 가격 질의 언어를 target_market에 따라 동적으로 결정하도록 함(파이프라인
    문서 31절) — 기존엔 목표시장이 항상 북미라는 전제로 영어를 하드코딩했으나, 다른 목표시장
    (예: 한국 국내)에는 영어 리뷰 기사 타겟팅이 안 맞을 수 있어 `_use_english_price_query()`로
    분기한다.

    ## 2026-07-29 변경: 질의의 연도를 실행 시각에서 가져온다

    이전에는 `f"{name} price review comparison 2026"` 처럼 **연도가 문자열에 박혀
    있었다.** 2027년에 실행하면 한 해 지난 리뷰 기사를 겨냥한다. 조용히 낡아가고,
    검색 결과가 나빠져도 원인이 코드에 있다는 것을 알기 어렵다.

    **결함 I(기획서 개요의 `"2022년 시장 규모 기준"` 하드코딩)와 같은 유형이다.**
    결함 I는 문서 출력 쪽이었고 이쪽은 검색 입력 쪽이라, 파이프라인에서 더 이르다 —
    입력이 낡으면 그 뒤 모든 단계가 낡은 자료를 받는다.

    `current_year`를 인자로 받는 이유: 테스트에서 연도를 고정해야 검증이 재현된다.
    기본값 `None`이면 실행 시각의 연도를 쓴다."""
    year = current_year if current_year is not None else date.today().year
    if _use_english_price_query(target_market):
        price_query = f"{name} price review comparison {year}"
    else:
        price_query = f"{name} 가격 비교 리뷰 추천 {year}"
    return [
        price_query,
        f"{name} 투자 유치 매출 실적 규모",
        f"{name} 판매 채널 유통 파트너십",
    ]


# identify_competitors()가 회사명 대신 제품/브랜드명을 후보명으로 뽑는 경우가 실제로
# 관찰됨(예: "삼성 갤럭시 워치"). 재무 정보(투자·매출)는 보통 제품 단위가 아니라 회사
# 단위로만 공시되므로, 제품명 그대로 "투자 유치 매출 실적"을 검색하면 결과가 나오지
# 않는다(2026-07-21 실행에서 실제로 삼성 갤럭시 워치/Fitbit/Omron 세 곳이 3개 질의 모두
# 결과는 받았지만 fact를 하나도 못 건진 것으로 확인 — 파이프라인 문서 16절 참고).
#
# 원래는 "심층조사 질의 생성"에만 쓰던 매핑이었으나(프로필에 표시되는 경쟁사명은 식별
# 단계의 원래 표기를 그대로 유지한다는 방침이었음), 2026-07-22 재검증 실행에서 "애플",
# "애플워치", "애플 헬스킷"이 실제로는 같은 회사인데 identify_competitors()가 3개의
# 별도 경쟁사로 쪼개 잡는 문제가 발견되어, 이 매핑을 식별 단계의 이름 병합(canonicalize)
# 에도 재사용하도록 용도를 넓혔다. 그래서 함수명도 _company_name_for_deep_dive에서
# _canonical_company_name으로 바꿨다(호출부는 deep_dive_competitors와
# identify_competitors 두 곳).
#
# 가격 질의를 영어 리뷰 기사 타겟팅으로 바꾸면서(위 _deep_dive_queries 참고), 회사명도
# 한글 정식명("삼성전자")보다 영어권 리뷰 기사에 실제로 쓰이는 이름("Samsung")으로
# 매핑해야 검색·귀속(attribution) 둘 다에 유리하다고 판단해 값을 영어로 통일함. 식별
# 단계 병합에 재사용하면서 같은 회사의 한글/영문 표기 중복(예: "가민"="Garmin",
# "오우라 링"="Oura")도 같이 정리했다.
PRODUCT_TO_COMPANY_MAP = {
    "삼성 갤럭시 워치": "Samsung",
    "갤럭시 워치": "Samsung",
    "galaxy watch": "Samsung",
    "samsung galaxy watch": "Samsung",
    "애플 워치": "Apple",
    "애플워치": "Apple",
    "apple watch": "Apple",
    "애플 헬스킷": "Apple",
    "apple healthkit": "Apple",
    "healthkit": "Apple",
    "구글 픽셀 워치": "Google",
    "픽셀 워치": "Google",
    "pixel watch": "Google",
    "google pixel watch": "Google",
    "redmi": "Xiaomi",
    "redmi watch": "Xiaomi",
    "미밴드": "Xiaomi",
    "mi band": "Xiaomi",
    "갤럭시 버즈": "Samsung",
    "galaxy buds": "Samsung",
    "가민": "Garmin",
    "오우라 링": "Oura",
    "오우라": "Oura",
    "oura ring": "Oura",
    # 회사 기본명(한글 표기)도 매핑해야 "애플워치"→"Apple"과 "애플"이 같은 키로
    # 합쳐진다 — 둘 다 매핑 없이 두면 "애플"은 그대로 "애플"로 남고 "애플워치"만
    # "Apple"로 바뀌어, 소문자 키가 "애플"과 "apple"로 갈라져 병합이 안 되는 문제가 있었음.
    "애플": "Apple",
    "삼성": "Samsung",
    "삼성전자": "Samsung",
    "구글": "Google",
    "핏빗": "Fitbit",
    "화웨이": "Huawei",
    "샤오미": "Xiaomi",
}


def _canonical_company_name(name: str) -> str:
    """제품·서비스·플랫폼명을 회사명으로 정규화한다(원래는 심층조사 질의 생성 전용이었으나,
    identify_competitors()의 경쟁사 중복(예: 애플/애플워치/애플 헬스킷이 별도 항목으로
    잡히는 문제) 병합에도 재사용한다). 목록에 없는 이름(대부분의 경우 이미 회사명)은
    그대로 반환한다 — 완벽한 매핑일 수 없는 휴리스틱이므로, 목록에 없는 새로운 제품명·
    표기는 여전히 별도 항목으로 남을 수 있다는 한계가 있음."""
    return PRODUCT_TO_COMPANY_MAP.get(name.strip().lower(), name)


def deep_dive_competitors(
    client: OpenAI,
    candidates: list[dict],
    topic: str,
    target_market: str,
    top_n: int = DEEP_DIVE_TOP_N,
    results_per_query: int = DEEP_DIVE_RESULTS_PER_QUERY,
) -> list[Fact]:
    """식별된 경쟁사 후보 중 '직접 경쟁자' 상위 top_n개에 대해서만, 회사명 기반 타겟
    질의로 가격·판매채널·투자매출 정보를 추가 검색한다.

    사람이 실제로 경쟁사 분석을 할 때 밟는 절차(1.시장조사 → 2.경쟁사 후보 확정 →
    3.경쟁사 개별 조사(홈페이지·SNS·증시) → 4.프로필 작성)에서 지금까지 빠져 있던
    3단계를 채우는 것 — 기존 코드는 2단계(식별) 직후 바로 4단계(프로필)로 넘어가서,
    시장 전체를 훑는 질문에 우연히 걸린 정보만 프로필에 채워지고 가격·채널·투자매출처럼
    회사를 정조준해야 나오는 정보는 계속 비어있었다(파이프라인 문서 14절).

    비용 통제:
    - 간접 경쟁자·잠재 진입자는 제외하고 직접 경쟁자만 대상으로 한다(시장에서 실제로
      정면 경쟁하는 상대를 우선 정밀 조사한다는 판단).
    - mentioned_fact_ids 개수(=fact에 언급된 빈도, 시장에서의 존재감을 보여주는 대리지표)가
      많은 순으로 top_n개만 고른다. 식별 단계에서 후보가 20개 넘게 나와도 전부 심층조사하지
      않는다.
    - 질의 생성에 LLM을 쓰지 않고 고정 템플릿을 쓴다(회사명이 이미 정해졌으므로 질문
      생성 자체가 창의적 작업이 아님).
    """
    direct = [c for c in candidates if c["type"] == CompetitorType.DIRECT.value]
    ranked = sorted(direct, key=lambda c: len(c.get("mentioned_fact_ids", [])), reverse=True)
    targets = ranked[:top_n]

    if not targets:
        log.info("[경쟁사비교 에이전트] 심층조사 대상 직접 경쟁자가 없어 3단계를 건너뜁니다.")
        return []

    log.info(f"[경쟁사비교 에이전트] 심층조사(가격·채널·투자매출) 대상 {len(targets)}개: "
          f"{', '.join(c['name'] for c in targets)}")

    new_facts: list[Fact] = []
    counters = {"n_saved": 0, "n_duplicates": 0}
    for candidate in targets:
        name = candidate["name"]
        search_name = _canonical_company_name(name)
        if search_name != name:
            log.info(f"\n[심층조사] {name} (검색은 실제 회사명 '{search_name}'으로 정규화)")
        else:
            log.info(f"\n[심층조사] {name}")
        for query in _deep_dive_queries(search_name, target_market):
            log.info(f"  [검색] {query}")
            _search_extract_and_save(
                client, query, topic, target_market, results_per_query, new_facts, counters
            )

        # 이 회사명 기반 질의로 찾은 fact 중, 후보명(name) 또는 정규화된 회사명(search_name)
        # 중 하나라도 텍스트에 등장하는 것만 이 경쟁사의 근거(mentioned_fact_ids)로
        # 귀속시킨다. extract_competitor_facts가 이미 "실제 기업명이 등장하는 fact만"
        # 추출하도록 필터링하지만, 검색 질의에 이름을 넣어도 결과에 다른 회사 얘기가
        # 섞여 나올 수 있어 한 번 더 확인한다(이중 안전장치 — KNOWN_COMPETITOR_BRANDS류
        # 패턴과 같은 원칙). search_name도 함께 확인하는 이유는, "삼성 갤럭시 워치"로
        # 식별된 후보의 심층조사 결과가 "삼성전자"라는 표현으로만 등장하고 "갤럭시 워치"라는
        # 문구는 없을 수 있기 때문.
        attributed = [
            f for f in new_facts
            if f.id not in candidate["mentioned_fact_ids"]
            and (name.lower() in f.text.lower() or search_name.lower() in f.text.lower())
        ]
        candidate["mentioned_fact_ids"].extend(f.id for f in attributed)
        if attributed:
            log.info(f"  [귀속] {name}에 새 근거 fact {len(attributed)}개 추가")

    log.info(f"\n[경쟁사비교 에이전트] 심층조사로 fact {counters['n_saved']}개 신규 저장, "
          f"중복 {counters['n_duplicates']}개 건너뜀")
    return new_facts


def run_competitor_analysis(
    topic: str,
    target_market: str,
    n_queries: int = 3,
    results_per_query: int = 6,
    deep_dive_top_n: int = DEEP_DIVE_TOP_N,
) -> list[Competitor]:
    """전체 파이프라인 실행: 검색질문 생성 -> 웹검색 -> fact 저장 -> 경쟁사 식별 ->
    (신규) 상위 직접 경쟁자 심층조사 -> 프로필 구조화 -> 저장/출력

    recall 개선(파이프라인 문서 9절) 적용 내역:
    - results_per_query 기본값 4 -> 6
    - 스니펫 대신 페이지 실제 본문 활용(search_web(fetch_full_text=True))
    - 한 질문에서 fact를 하나도 못 뽑으면, 더 일반적인 검색어로 재구성해 1회 재검색(query rewriting)

    심층조사 단계(파이프라인 문서 14절) 적용 내역:
    - 경쟁사 식별 직후, 프로필 구조화 이전에 상위 직접 경쟁자 deep_dive_top_n개에 대해
      회사명 기반 타겟 질의(가격/채널/투자매출)로 추가 검색을 수행한다.
    - deep_dive_top_n=0으로 주면 이 단계를 건너뛰고 기존 동작(식별 → 바로 프로필링)과
      동일하게 동작한다.
    """
    init_db()
    client = get_client()

    log.info(f"[경쟁사비교 에이전트] 연구대상: {topic} / 목표시장: {target_market}")

    # 검색 질문을 짜기 전에, 시장조사 단계 등에서 이미 모아둔 관련 fact가 있는지 먼저
    # 확인한다(2026-07-23 변경, 파이프라인 문서 30절). topic 일치 판정 로직은 2026-07-24부터
    # fact_store.list_facts()의 topic 파라미터로 통합했다(중복 제거 — 이전엔 여기와 아래
    # historical_facts 두 곳에 같은 필터가 따로 있었음).
    existing_topic_facts = list_facts(topic=topic)
    queries = generate_competitor_queries(
        client, topic, target_market, n=n_queries, existing_facts=existing_topic_facts
    )
    log.info(f"[경쟁사비교 에이전트] 검색 질문 {len(queries)}개 생성:")
    for q in queries:
        log.info(f"  - {q}")

    counters = {"n_saved": 0, "n_duplicates": 0}
    run_facts: list[Fact] = []  # 이번 실행에서 실제로 다룬 fact (검색 질문 문구와 무관하게 반드시 포함시키기 위함)
    for query in queries:
        log.info(f"\n[검색] {query}")
        n_this_q = _search_extract_and_save(
            client, query, topic, target_market, results_per_query, run_facts, counters
        )

        if n_this_q == 0:
            retry_query = simplify_query(client, query)
            log.info(f"  [재시도] 이 질문에서 fact를 못 찾음 → 더 일반적인 검색어로 재검색: {retry_query}")
            _search_extract_and_save(
                client, retry_query, topic, target_market, results_per_query, run_facts, counters
            )

    log.info(f"\n[경쟁사비교 에이전트] fact {counters['n_saved']}개 신규 저장, 중복 {counters['n_duplicates']}개 건너뜀")

    # 이번 실행에서 다룬 fact(run_facts)는 검색 질문(topic_relevance) 문구와 무관하게 항상 포함한다.
    # 과거 fact는 fact_store.list_facts(topic=topic)에 판정을 위임한다(topic 필드가 있으면
    # 정확히 일치하는 것만, 없는 레거시 fact는 topic_relevance 부분 문자열 매칭으로 보조 판정 —
    # 로직 자체는 그대로이고 2026-07-24에 중복 제거만 함).
    run_fact_ids = {f.id for f in run_facts}
    historical_facts = [f for f in list_facts(topic=topic) if f.id not in run_fact_ids]
    all_facts = run_facts + historical_facts
    log.info(f"[경쟁사비교 에이전트] 대상 fact {len(all_facts)}개 로드 완료 "
          f"(이번 실행 {len(run_facts)}개 + 과거 fact 중 topic 일치 {len(historical_facts)}개)")

    if not all_facts:
        log.info("[경쟁사비교 에이전트] 경고: 관련 fact가 없어 경쟁사 식별을 진행할 수 없습니다.")
        return []

    # 검증·출처 에이전트가 "기각"(REJECTED) 판정한 fact는 경쟁사 식별·프로필링 근거에서
    # 아예 제외한다 (파이프라인 문서 13절) — 원본은 Fact Store에 그대로 남아 있으니 삭제가
    # 아니라 이 분석 단계에서만 보이지 않게 하는 것. 검증을 아직 거치지 않은(verification_status
    # is None) 레거시 fact는 하위 호환을 위해 그대로 포함한다.
    verified_facts = [f for f in all_facts if f.verification_status != VerificationStatus.REJECTED]
    n_rejected = len(all_facts) - len(verified_facts)
    if n_rejected:
        log.info(f"[경쟁사비교 에이전트] 검증 에이전트가 기각한 fact {n_rejected}개를 분석 대상에서 제외")
    all_facts = verified_facts

    log.info("[경쟁사비교 에이전트] 경쟁사 식별 중...")
    candidates = identify_competitors(client, all_facts)
    if not candidates:
        log.info("[경쟁사비교 에이전트] fact 목록에서 실제로 언급된 경쟁사를 찾지 못했습니다.")
        return []
    log.info(f"[경쟁사비교 에이전트] 경쟁사 후보 {len(candidates)}개 식별: "
          f"{', '.join(c['name'] + '(' + c['type'] + ')' for c in candidates)}")
    _flag_missed_competitor_mentions(all_facts, candidates)

    candidates = select_top_competitors(candidates, all_facts)
    log.info(f"[경쟁사비교 에이전트] 유형별 상한 적용 후 최종 {len(candidates)}개: "
          f"{', '.join(c['name'] + '(' + c['type'] + ')' for c in candidates)}")

    if deep_dive_top_n > 0:
        log.info("\n[경쟁사비교 에이전트] 상위 직접 경쟁자 심층조사 시작...")
        deep_dive_facts = deep_dive_competitors(
            client, candidates, topic, target_market, top_n=deep_dive_top_n
        )
        all_facts = all_facts + deep_dive_facts

    log.info("\n[경쟁사비교 에이전트] 경쟁사별 비교 프로필 구조화 중...")
    profiles = build_competitor_profiles(client, all_facts, candidates)

    type_by_name = {c["name"]: c["type"] for c in candidates}
    saved: list[Competitor] = []
    for p in profiles:
        competitor = Competitor(
            name=p["name"],
            topic=topic,
            type=CompetitorType(type_by_name.get(p["name"], CompetitorType.DIRECT.value)),
            price=p["price"] or None,
            key_features=p["key_features"],
            target_customer=p["target_customer"] or None,
            channel=p["channel"] or None,
            funding_or_revenue=p["funding_or_revenue"] or None,
            strengths=p["strengths"],
            weaknesses=p["weaknesses"],
            source_fact_ids=p["source_fact_ids"],
        )
        save_competitor(competitor)
        saved.append(competitor)

    print_comparison_table(saved)
    return saved


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python -m agents.competitor "<연구대상>" "<목표시장>"')
        print('(먼저 python -m agents.market_research로 같은 연구대상에 대해 fact를 수집해두면 더 풍부하게 활용됩니다)')
        sys.exit(1)

    run_competitor_analysis(topic=sys.argv[1], target_market=sys.argv[2])
