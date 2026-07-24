"""
PESTEL 에이전트 (Day 4 프로토타입)

파이프라인 문서 3-3절 절차를 그대로 구현:
  1) Fact 단위 분해 — 이미 Fact Store에 fact 하나당 한 줄로 저장돼 있으므로 별도 작업 불필요
  2) 6축 태깅 — Political/Economic/Social/Technological/Environmental/Legal (중복 태깅 허용)
  3) 임팩트 방향·시급성 판정 — 기회/위협/중립, 즉시/단기/장기
  4) 축별 내러티브 압축 — 같은 축의 fact들을 하나의 요약 문단으로
  5) Materiality Filter — 중요도 낮은 fact는 요약에서 빼되, "뺐다는 사실"은 투명하게 기록
     (Fact 자체는 삭제하지 않음 — Fact Store는 항상 추적 가능해야 한다는 원칙 유지)

주의: 시장조사 에이전트에서 겪었던 "출처 조작(hallucination)" 문제를 반복하지 않도록,
요약문은 반드시 주어진 fact 내용만 근거로 쓰도록 프롬프트에 명시한다.
"""

import json
import os

from dotenv import load_dotenv
from openai import OpenAI

from fact_store.schema import Fact, ImpactDirection, PestelAxis, Urgency, VerificationStatus
from fact_store.store import init_db, list_facts, save_fact

load_dotenv()

HEAVY_MODEL = os.getenv("HEAVY_MODEL", "solar-pro2")

AXIS_VALUES = [a.value for a in PestelAxis]
DIRECTION_VALUES = [d.value for d in ImpactDirection]
URGENCY_VALUES = [u.value for u in Urgency]

# STEEP 프레임워크 축 정의 (RAG 코퍼스 "03+정보기술전략+정보기술+R&D+전략+수립" 문서의
# <표 1-15> STEEP 프레임 참고, 2026-07-23 확인). 원문은 5축(Political/Legal 통합)이라
# 저희 6축(Political·Legal 분리) 스키마에 맞춰 재구성함 — Political은 "정책 방향·이념·
# 안정성"(원문의 좌/우파 정책성향과 이론), Legal은 "실제 시행되는 법·제도 변화"(원문의
# 탈규제화·민영화·산업구조조정·시장자율 경쟁체제 전환)로 나눴다. 이건 일반적인 PESTEL
# 교재가 Political/Legal을 구분하는 기준과도 일치한다. Environmental은 원문의
# "Ecological"과 이름만 다르고 내용은 동일해서 그대로 대응시켰다.
#
# 타 팀(PICO) 비교에서 배운 "RAG를 장식용 인용이 아니라 분석 프롬프트에 직접 삽입해
# 분류·요약 품질 자체를 높이는 용도로 쓴다"는 아이디어를 적용한 것(파이프라인 문서 27절
# 참고). 다만 매번 실시간 벡터 검색을 태우는 대신, 이미 확인한 좋은 정의를 상수로
# 고정해서 쓴다 — 유사도 검색은 실행마다 같은 청크가 나온다는 보장이 없어, 검증된 내용을
# 고정값으로 두는 쪽이 안정적이라고 판단했다.
AXIS_DEFINITIONS: dict[str, str] = {
    "Social": "인구통계, 사회문화, 문맹율, 교육수준, 행동양식/규범, 사회 전반의 가치관, "
    "LifeStyle, 나이/지역별 인구 분포 및 이동",
    "Technological": "기술 인력 양성 정책/예산, 디지털 통신, 생명공학, 화학공학, 에너지, "
    "의학 등 기술 발전 동향",
    "Economic": "환율, 금리, 무역수지, 예산운영, 취업률, 인플레이션, GDP 대비 가계부채, "
    "가처분소득 수준",
    "Environmental": "천연자원 소진율, 재활용율, 소음/먼지 등 공해 정도, 기후변화·ESG "
    "관련 규제 및 소비 트렌드",
    "Political": "정부의 정책 방향과 산업 진흥/규제 성향, 좌/우파 정책 성향과 이론, "
    "정치적 안정성",
    "Legal": "탈규제화, 민영화, 산업구조조정, 시장자율 경쟁체제로의 전환 등 실제 시행되는 "
    "법률·인허가·규제 변화",
}
AXIS_DEFINITIONS_BLOCK = "\n".join(
    f"- {axis}: {AXIS_DEFINITIONS[axis]}" for axis in AXIS_VALUES if axis in AXIS_DEFINITIONS
)

TAGGING_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "pestel_tags",
        "schema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact_id": {"type": "string"},
                            "pestel_axis": {
                                "type": "array",
                                "items": {"type": "string", "enum": AXIS_VALUES},
                                "description": "이 fact가 해당하는 PESTEL 축. 경계 사례는 여러 축 동시 태깅 허용.",
                            },
                            "impact_direction": {"type": "string", "enum": DIRECTION_VALUES},
                            "urgency": {"type": "string", "enum": URGENCY_VALUES},
                        },
                        "required": ["fact_id", "pestel_axis", "impact_direction", "urgency"],
                    },
                }
            },
            "required": ["tags"],
        },
    },
}

SUMMARY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "pestel_axis_summaries",
        "schema": {
            "type": "object",
            "properties": {
                "summaries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "axis": {"type": "string", "enum": AXIS_VALUES},
                            "narrative": {
                                "type": "string",
                                "description": "이 축의 요약 문단. 사업 의사결정에 실제 영향을 주는 내용만 포함 (materiality filter). 반드시 주어진 fact 내용만 근거로 쓰고, 없는 내용을 지어내지 말 것.",
                            },
                            "included_fact_ids": {"type": "array", "items": {"type": "string"}},
                            "excluded_low_materiality_fact_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "이 축에 태깅됐지만 중요도가 낮아 요약 문단에서 제외한 fact id 목록",
                            },
                        },
                        "required": [
                            "axis",
                            "narrative",
                            "included_fact_ids",
                            "excluded_low_materiality_fact_ids",
                        ],
                    },
                }
            },
            "required": ["summaries"],
        },
    },
}


def get_client() -> OpenAI:
    api_key = os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 없습니다.")
    return OpenAI(api_key=api_key, base_url="https://api.upstage.ai/v1")


# 한 번의 LLM 호출로 배치 처리할 때 넣을 수 있는 fact 수 상한(파이프라인 문서 22절 참고).
# fact가 너무 많으면 응답 JSON이 모델의 출력 토큰 한도를 넘어 중간에 잘리는 문제가
# 실제로 발생했음(경쟁사비교 에이전트의 build_competitor_profiles()에서 최초 관찰).
# fact 하나당 태깅 결과가 짧아서(축/방향/시급성 세 값) 태깅은 임계값을 조금 더 넉넉히 잡았다.
TAG_BATCH_SIZE = 40
SUMMARY_MAX_FACTS_PER_CALL = 40


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def tag_facts(client: OpenAI, facts: list[Fact]) -> list[Fact]:
    """fact 목록을 TAG_BATCH_SIZE개씩 나눠 배치 태깅한다.

    원래는 fact 전체를 한 번의 LLM 호출로 처리했으나(그래야 비용·시간이 적게 듦),
    fact 수가 많아지면 응답이 커져 잘리는 문제가 있어 배치로 나눴다."""
    if not facts:
        return []

    updated: list[Fact] = []
    for batch in _chunked(facts, TAG_BATCH_SIZE):
        facts_block = "\n".join(f"- id={f.id}: {f.text}" for f in batch)
        prompt = f"""당신은 20년 경력의 전략 컨설턴트입니다. 아래 fact들을 PESTEL 6축
(Political/Economic/Social/Technological/Environmental/Legal)으로 태깅하세요.

각 축의 정의(STEEP 프레임워크 기준)는 다음과 같습니다 — 특히 Political과 Legal의
경계가 헷갈리기 쉬우니(Political=정책 방향/이념, Legal=실제 시행되는 법·제도) 이
정의를 기준으로 판단하세요:
{AXIS_DEFINITIONS_BLOCK}

각 fact마다:
- pestel_axis: 해당하는 축 (경계 사례는 여러 축 동시 태깅 가능)
- impact_direction: 이 사업에 기회/위협/중립 중 무엇인지
- urgency: 즉시/단기/장기 중 언제 영향을 미치는지

fact 목록:
{facts_block}

모든 fact_id에 대해 빠짐없이 태깅 결과를 반환하세요."""

        response = client.chat.completions.create(
            model=HEAVY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=TAGGING_SCHEMA,
        )
        parsed = json.loads(response.choices[0].message.content)
        tags_by_id = {t["fact_id"]: t for t in parsed["tags"]}

        for fact in batch:
            tag = tags_by_id.get(fact.id)
            if not tag:
                print(f"  [경고] fact_id={fact.id} 태깅 결과 누락 — 원본 그대로 둠")
                updated.append(fact)
                continue
            fact.pestel_axis = [PestelAxis(a) for a in tag["pestel_axis"]]
            fact.impact_direction = ImpactDirection(tag["impact_direction"])
            fact.urgency = Urgency(tag["urgency"])
            save_fact(fact)  # upsert — 기존 fact 레코드에 태깅 결과 반영
            updated.append(fact)
    return updated


def _bin_pack_axis_blocks(
    non_empty: dict[str, list[Fact]], max_facts: int
) -> list[dict[str, list[Fact]]]:
    """축 그룹들을 한 번의 LLM 호출에 넘길 fact 총합이 max_facts를 넘지 않도록 배치로 묶는다.
    축 하나만으로도 max_facts를 넘으면 그 축의 fact를 다시 쪼개 별도 배치 여러 개로
    나눈다 — 이 경우 같은 축에 대해 narrative가 여러 개 나오는데, 호출부에서 합친다."""
    batches: list[dict[str, list[Fact]]] = []
    current: dict[str, list[Fact]] = {}
    current_count = 0

    def flush():
        nonlocal current, current_count
        if current:
            batches.append(current)
        current = {}
        current_count = 0

    for axis, facts in non_empty.items():
        if len(facts) > max_facts:
            flush()
            for sub in _chunked(facts, max_facts):
                batches.append({axis: sub})
            continue
        if current_count + len(facts) > max_facts:
            flush()
        current[axis] = facts
        current_count += len(facts)
    flush()
    return batches


def summarize_by_axis(client: OpenAI, tagged_facts: list[Fact]) -> list[dict]:
    """축별로 fact를 묶어서 하나의 요약 문단으로 압축한다 (materiality filter 포함).

    축 그룹을 SUMMARY_MAX_FACTS_PER_CALL 기준으로 배치를 나눠 여러 번 호출한다(22절 —
    한 번에 다 넣으면 응답이 잘리는 문제 방지). 같은 축이 여러 배치에 걸쳐 쪼개진
    경우에는 narrative를 이어붙이고 fact id 목록을 합쳐 하나의 요약으로 반환한다."""
    axis_groups: dict[str, list[Fact]] = {v: [] for v in AXIS_VALUES}
    for fact in tagged_facts:
        for axis in fact.pestel_axis or []:
            axis_groups[axis.value].append(fact)

    non_empty = {axis: facts for axis, facts in axis_groups.items() if facts}
    if not non_empty:
        return []

    batches = _bin_pack_axis_blocks(non_empty, SUMMARY_MAX_FACTS_PER_CALL)

    partial_summaries: dict[str, list[dict]] = {}
    for batch in batches:
        blocks = []
        for axis, facts in batch.items():
            lines = "\n".join(
                f"  - id={f.id} ({f.impact_direction.value if f.impact_direction else '?'}/"
                f"{f.urgency.value if f.urgency else '?'}): {f.text}"
                for f in facts
            )
            blocks.append(f"[{axis}]\n{lines}")
        facts_by_axis_block = "\n\n".join(blocks)

        prompt = f"""당신은 20년 경력의 전략 컨설턴트입니다. 아래는 PESTEL 축별로 태깅된 fact들입니다.

각 축의 정의(STEEP 프레임워크 기준)는 다음과 같습니다 — 요약 문단이 이 축의 원래
범위를 벗어나지 않도록 참고하세요:
{AXIS_DEFINITIONS_BLOCK}

{facts_by_axis_block}

각 축마다 하나의 요약 문단(narrative)을 작성하세요. 요약 문단은:
- 사업 의사결정에 실제 영향을 주는 내용만 포함하세요 (사소하거나 중복되는 fact는 제외 가능 —
  이때 제외한 fact id는 excluded_low_materiality_fact_ids에 반드시 기록하세요)
- 반드시 위에 주어진 fact 내용만 근거로 쓰고, fact에 없는 통계나 사실을 새로 지어내지 마세요.
- fact가 없는 축은 결과에 포함하지 마세요."""

        response = client.chat.completions.create(
            model=HEAVY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format=SUMMARY_SCHEMA,
        )
        parsed = json.loads(response.choices[0].message.content)
        for s in parsed["summaries"]:
            partial_summaries.setdefault(s["axis"], []).append(s)

    merged: list[dict] = []
    for axis, parts in partial_summaries.items():
        if len(parts) == 1:
            merged.append(parts[0])
            continue
        merged.append(
            {
                "axis": axis,
                "narrative": "\n\n".join(p["narrative"] for p in parts),
                "included_fact_ids": [fid for p in parts for fid in p["included_fact_ids"]],
                "excluded_low_materiality_fact_ids": [
                    fid for p in parts for fid in p["excluded_low_materiality_fact_ids"]
                ],
            }
        )
    return merged


def run_pestel_analysis(topic: str, target_market: str) -> list[dict]:
    """Fact Store에 이미 저장된 fact들을 불러와 PESTEL 분석을 수행한다.
    (새로운 웹검색은 하지 않음 — 시장조사 에이전트가 수집한 fact를 재사용)"""
    init_db()
    client = get_client()

    # topic 필드(정확히 일치)를 우선 사용하고, topic 필드가 없는 레거시 fact만
    # topic_relevance(리서치 질문 문구) 부분 문자열 매칭으로 보조 판정한다.
    # (여러 주제로 시장조사를 반복 실행했을 경우 서로 섞이지 않도록 하는 목적은 동일하나,
    # 검색 질문이 topic 문구를 그대로 포함하지 않게 재구성되는 경우 substring 매칭만으로는
    # fact를 놓칠 수 있음 — agents/competitor.py 11-3절에서 실제로 발견된 문제와 동일한 유형)
    all_facts = list_facts()
    facts = [
        f for f in all_facts
        if (f.topic == topic if f.topic is not None else topic in (f.topic_relevance or ""))
    ]
    if not facts:
        print(f"[PESTEL 에이전트] 경고: '{topic}' 관련 fact가 Fact Store에 없습니다. 시장조사 에이전트를 먼저 실행하세요.")
        return []

    # 검증·출처 에이전트가 "기각"한 fact는 PESTEL 분석 근거에서 제외 (경쟁사비교 에이전트와
    # 동일한 원칙 — 파이프라인 문서 13절). 검증 미실시(None) 레거시 fact는 그대로 포함.
    verified_facts = [f for f in facts if f.verification_status != VerificationStatus.REJECTED]
    n_rejected = len(facts) - len(verified_facts)
    if n_rejected:
        print(f"[PESTEL 에이전트] 검증 에이전트가 기각한 fact {n_rejected}개를 분석 대상에서 제외")
    facts = verified_facts

    print(f"[PESTEL 에이전트] 대상 fact {len(facts)}개 로드 완료")
    print("[PESTEL 에이전트] 6축 태깅 중...")
    tagged = tag_facts(client, facts)
    for f in tagged:
        axis_str = ", ".join(a.value for a in (f.pestel_axis or []))
        print(f"  [{axis_str}] ({f.impact_direction.value if f.impact_direction else '?'}/"
              f"{f.urgency.value if f.urgency else '?'}) {f.text}")

    print("\n[PESTEL 에이전트] 축별 요약 생성 중...")
    summaries = summarize_by_axis(client, tagged)
    for s in summaries:
        print(f"\n=== {s['axis']} ===")
        print(s["narrative"])
        if s["excluded_low_materiality_fact_ids"]:
            print(f"  (중요도 낮아 제외된 fact: {s['excluded_low_materiality_fact_ids']})")

    return summaries


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python -m agents.pestel "<연구대상>" "<목표시장>"')
        print('(먼저 python -m agents.market_research로 같은 연구대상에 대해 fact를 수집해둬야 합니다)')
        sys.exit(1)

    run_pestel_analysis(topic=sys.argv[1], target_market=sys.argv[2])
