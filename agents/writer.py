"""
Writer 에이전트 (기획서 초안 조립)

지금까지 4개 에이전트(시장조사·PESTEL·경쟁사비교·검증출처)가 만든 결과물을 하나의
기획서 초안(마크다운)으로 조립하는 역할만 한다. 이 에이전트는 새로 웹검색을 하거나
새로운 fact를 만들어내지 않는다 — 순수하게 "이미 있는 결과를 글로 조립"하는 단계.

섹션 구성 (파이프라인 문서 20절 설계 논의 기준):
  1) 개요 + 핵심 요약(Executive Summary)
  2) 시장 규모 분석 (TAM/SAM/SOM)
  3) PESTEL 환경분석
  4) 경쟁사 분석 (비교 프로필 + 포지셔닝 서술)
  5) 종합 시사점
  6) 출처 부록

주의: cite_pestel_methodology()/cite_fact_metadata_standard()(RAG 코퍼스에서 NCS/TTA 표준
원문을 그대로 인용해오는 함수)는 실제 기획서 본문에는 더 이상 넣지 않는다(2026-07-22 변경).
"우리 분석 절차·출처 메타데이터 구성이 표준을 따른다"는 근거는 필요하지만, 표준 문서 원문을
그대로 잘라 붙이면 투자자/심사자가 읽는 기획서의 전문성을 해친다는 판단 때문 — 이런 근거는
기획서 본문이 아니라 멘토링 질의응답 등 별도 설명 자료를 만들 때 agents.verification에서
직접 호출해서 쓴다.

시장조사·PESTEL·경쟁사비교 에이전트에서 반복적으로 겪은 "출처 조작(hallucination)"
문제를 반복하지 않기 위해, 한 번의 LLM 호출에 모든 근거를 다 던져주지 않고 섹션별로
나눠서 호출한다(예: PESTEL 챕터를 쓸 때는 pestel_summaries만 주고 경쟁사 정보는
안 준다). 유일한 예외는 5) 종합 시사점인데, 이건 성격상 앞선 섹션들을 다시 엮어야
하므로 위 섹션의 "요약된 결과물"(원본 fact가 아니라 이미 한 번 걸러진 narrative/
프로필)만 입력으로 주고, "새로운 사실을 지어내지 말고 위 내용만 재구성하라"는
프롬프트 제약을 검증 에이전트·PESTEL 에이전트와 동일한 원칙으로 건다.
"""

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Optional

from openai import OpenAI

from agents.docx_export import export_to_docx
from agents.market_research import get_client
from agents.pestel import run_pestel_analysis
from fact_store.schema import Competitor, Fact, MarketSizing, VerificationStatus
from fact_store.store import get_fact, init_db, latest_market_sizing, list_competitors

WRITER_MODEL = os.getenv("HEAVY_MODEL", "solar-pro2")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

EXEC_SUMMARY_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "executive_summary",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "3~5문장의 핵심 요약. 반드시 주어진 시장규모 수치·PESTEL 기회/위협 "
                        "개수·경쟁사 수 등 아래에 제공된 통계만 근거로 쓰고, 새로운 사실이나 "
                        "수치를 지어내지 말 것."
                    ),
                }
            },
            "required": ["summary"],
        },
    },
}

POSITIONING_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "positioning_narrative",
        "schema": {
            "type": "object",
            "properties": {
                "narrative": {
                    "type": "string",
                    "description": (
                        "경쟁사 프로필들을 비교해 시장 내 포지셔닝을 서술하는 2~3문단. "
                        "반드시 아래 주어진 프로필 내용만 근거로 쓰고, 프로필에 없는 "
                        "가격·기능·수치를 새로 지어내지 말 것. 정보가 부족한 항목은 "
                        "'정보 부족'이라고 명시할 것."
                    ),
                }
            },
            "required": ["narrative"],
        },
    },
}

SYNTHESIS_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "synthesis",
        "schema": {
            "type": "object",
            "properties": {
                "synthesis": {
                    "type": "string",
                    "description": (
                        "시장규모·PESTEL·경쟁사 분석을 종합한 시사점 3~5개. 반드시 각 "
                        "항목을 줄바꿈으로 구분하고 '숫자. 제목: 본문' 형식으로 쓸 것 "
                        "(예: '1. 시장 세분화 전략: 주요 경쟁사가 프리미엄부터 예산형까지...'). "
                        "제목은 10자 내외의 짧은 문구, 본문은 1~3문장. 이 형식은 문서 "
                        "레이아웃(번호 카드)에 그대로 파싱되어 쓰이므로 반드시 지킬 것. "
                        "반드시 아래 제공된 섹션 내용만 재구성하고, 새로운 사실·수치를 "
                        "지어내지 말 것."
                    ),
                }
            },
            "required": ["synthesis"],
        },
    },
}


def _fmt_num(value: Optional[float], unit: str) -> str:
    if value is None:
        return "계산 불가"
    return f"{value:,.0f} {unit}"


def _format_market_sizing_md(sizing: Optional[MarketSizing]) -> str:
    if sizing is None:
        return "(시장조사 에이전트 실행 이력이 없어 시장 규모 데이터가 없습니다.)"

    lines = [
        f"- TAM (Top-down): {_fmt_num(sizing.tam_topdown, sizing.unit)}",
        f"- SAM (Top-down): {_fmt_num(sizing.sam_topdown, sizing.unit)}",
        f"- SOM (Top-down): {_fmt_num(sizing.som_topdown, sizing.unit)}",
    ]
    if sizing.som_bottomup:
        lines.append(f"- SOM (Bottom-up): {_fmt_num(sizing.som_bottomup, sizing.unit)}")
    if sizing.discrepancy_flag:
        lines.append("- ⚠️ Top-down/Bottom-up 추정치가 10배 이상 차이납니다 — 가정치 재검토 필요")
    if sizing.assumptions:
        lines.append("\n**가정 및 근거**")
        lines.extend(f"- {a}" for a in sizing.assumptions)
    return "\n".join(lines)


def _format_pestel_md(pestel_summaries: list[dict]) -> str:
    if not pestel_summaries:
        return "(PESTEL 분석 대상 fact가 없습니다.)"

    blocks = []
    for s in pestel_summaries:
        block = f"### {s['axis']}\n\n{s['narrative']}"
        if s.get("excluded_low_materiality_fact_ids"):
            block += (
                f"\n\n*(중요도가 낮아 요약에서 제외한 fact: "
                f"{len(s['excluded_low_materiality_fact_ids'])}건)*"
            )
        blocks.append(block)
    return "\n\n".join(blocks)


def _format_competitors_table_md(competitors: list[Competitor]) -> str:
    if not competitors:
        return "(식별된 경쟁사가 없습니다.)"

    header = "| 경쟁사 | 유형 | 가격 | 핵심 기능 | 타깃 고객 | 채널 | 투자/매출 |"
    sep = "|---|---|---|---|---|---|---|"
    rows = []
    for c in competitors:
        rows.append(
            "| "
            + " | ".join(
                [
                    c.name,
                    c.type.value,
                    c.price or "(정보 없음)",
                    "; ".join(c.key_features) or "(정보 없음)",
                    c.target_customer or "(정보 없음)",
                    c.channel or "(정보 없음)",
                    c.funding_or_revenue or "(정보 없음)",
                ]
            )
            + " |"
        )
    return "\n".join([header, sep] + rows)


def write_executive_summary(
    client: OpenAI,
    topic: str,
    target_market: str,
    sizing: Optional[MarketSizing],
    pestel_summaries: list[dict],
    competitors: list[Competitor],
) -> str:
    """개요 섹션의 핵심 요약. 원본 fact가 아니라 이미 집계된 통계(수치·개수)만 넘겨서
    새로운 사실을 지어낼 여지를 최소화한다."""
    opportunity_count = sum(
        1
        for s in pestel_summaries
        for _ in [None]
        if "기회" in s.get("narrative", "")
    )
    stats_block = f"""연구대상: {topic}
목표시장: {target_market}
TAM(Top-down): {_fmt_num(sizing.tam_topdown, sizing.unit) if sizing else '계산 불가'}
SAM(Top-down): {_fmt_num(sizing.sam_topdown, sizing.unit) if sizing else '계산 불가'}
SOM(Top-down): {_fmt_num(sizing.som_topdown, sizing.unit) if sizing else '계산 불가'}
PESTEL 분석 축 수: {len(pestel_summaries)}개
식별된 경쟁사 수: {len(competitors)}개 (직접 {sum(1 for c in competitors if c.type.value == '직접 경쟁자')}개)"""

    prompt = f"""당신은 20년 경력의 전략 컨설턴트입니다. 아래 통계만 근거로 이 사업 기획서의
핵심 요약(Executive Summary)을 3~5문장으로 작성하세요. 아래에 없는 수치나 사실은
절대 지어내지 마세요.

{stats_block}"""

    response = client.chat.completions.create(
        model=WRITER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=EXEC_SUMMARY_SCHEMA,
    )
    return json.loads(response.choices[0].message.content)["summary"]


def write_positioning_narrative(client: OpenAI, competitors: list[Competitor]) -> str:
    if not competitors:
        return "(식별된 경쟁사가 없어 포지셔닝 서술을 생략합니다.)"

    profiles_block = "\n\n".join(
        f"- {c.name} ({c.type.value}): 가격={c.price or '정보없음'}, "
        f"기능={'; '.join(c.key_features) or '정보없음'}, "
        f"타깃={c.target_customer or '정보없음'}, 채널={c.channel or '정보없음'}, "
        f"투자/매출={c.funding_or_revenue or '정보없음'}, "
        f"강점={'; '.join(c.strengths) or '정보없음'}, "
        f"약점={'; '.join(c.weaknesses) or '정보없음'}"
        for c in competitors
    )
    prompt = f"""당신은 20년 경력의 경쟁 전략 컨설턴트입니다. 아래 경쟁사 프로필만 근거로
시장 내 포지셔닝을 서술하세요. 프로필에 없는 내용은 지어내지 말고 '정보 부족'이라고
쓰세요.

{profiles_block}"""

    response = client.chat.completions.create(
        model=WRITER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=POSITIONING_SCHEMA,
    )
    return json.loads(response.choices[0].message.content)["narrative"]


def write_synthesis(
    client: OpenAI,
    topic: str,
    target_market: str,
    sizing_md: str,
    pestel_md: str,
    competitor_md: str,
) -> str:
    """종합 시사점. 유일하게 여러 섹션을 다시 엮는 단계라, 원본 fact가 아니라 이미
    조립된 섹션 텍스트만 입력으로 준다 — 그래도 '새 사실 생성 금지' 제약은 동일하게 건다."""
    prompt = f"""당신은 20년 경력의 전략 컨설턴트입니다. 아래는 '{topic}' ({target_market})에 대해
이미 작성된 시장규모·PESTEL·경쟁사 분석 섹션입니다. 이 내용만 근거로 종합 시사점을
3~5개 작성하세요. 아래에 없는 새로운 사실·수치를 지어내지 마세요.

[시장 규모]
{sizing_md}

[PESTEL 환경분석]
{pestel_md}

[경쟁사 분석]
{competitor_md}"""

    response = client.chat.completions.create(
        model=WRITER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format=SYNTHESIS_SCHEMA,
    )
    return json.loads(response.choices[0].message.content)["synthesis"]


def _collect_source_fact_ids(
    sizing: Optional[MarketSizing], pestel_summaries: list[dict], competitors: list[Competitor]
) -> list[str]:
    ids: list[str] = []
    if sizing:
        ids.extend(sizing.source_fact_ids)
    for s in pestel_summaries:
        ids.extend(s.get("included_fact_ids", []))
    for c in competitors:
        ids.extend(c.source_fact_ids)
    # 순서를 유지하면서 중복 제거
    seen = set()
    unique_ids = []
    for fid in ids:
        if fid not in seen:
            seen.add(fid)
            unique_ids.append(fid)
    return unique_ids


def _format_source_appendix_md(fact_ids: list[str]) -> str:
    if not fact_ids:
        return "(이 보고서가 직접 인용한 fact가 없습니다.)"

    rows = []
    for fid in fact_ids:
        fact = get_fact(fid)
        if fact is None:
            continue
        status = fact.verification_status.value if fact.verification_status else "검증 미실시"
        rows.append(
            f"- `{fid}` [{fact.source_tier.value}/{status}] {fact.text}\n"
            f"  - 출처: {fact.source_url} (조회일: {fact.retrieved_date})"
        )
    return "\n".join(rows) if rows else "(이 보고서가 직접 인용한 fact가 없습니다.)"


def _slugify(text: str) -> str:
    text = re.sub(r"\s+", "_", text.strip())
    return re.sub(r"[^\w가-힣_-]", "", text)


def _versioned_base_name(
    output_dir: Path, base_name: str, revision_note: Optional[str] = None
) -> str:
    """같은 topic/target_market으로 재실행하면 파일명이 그대로라 저장할 때마다
    덮어써지는 문제가 있었다(2026-07-23 사용자 지적). 처음엔 'base_name_v2, _v3 ...
    다음 번호 찾기'로만 막았는데, 2026-07-24 Task #5에서 revision_note(문서 표지에
    쓰는 "N차 수정본" 표시)가 생기면서 파일명도 같은 문구를 쓰도록 바꿨다 — 문서를
    열어보지 않아도 파일명만으로 몇 차 수정본인지 바로 알 수 있어야 한다는 사용자
    지적을 반영함(2026-07-24).

    revision_note가 있으면(재작업 결과) 그 문구를 슬러그로 붙인 이름을 쓰고, 없으면
    (최초 초안) 기존처럼 접미사 없는 이름을 그대로 쓴다. 두 경우 모두 혹시라도 같은
    이름의 파일이 이미 있으면(예: 같은 topic/시장으로 완전히 새 세션을 다시 시작해
    revision_count가 다시 0부터 도는 경우) 그때만 번호를 하나 더 붙이는 안전장치를
    유지한다 — 평소엔 안 보이고, 이름이 겹칠 때만 작동한다."""
    if revision_note:
        slug = _slugify(revision_note)
        candidate = f"{base_name}_{slug}"
        collision_suffix = 2
        while (output_dir / f"{candidate}.md").exists() or (output_dir / f"{candidate}.docx").exists():
            candidate = f"{base_name}_{slug}_{collision_suffix}"
            collision_suffix += 1
        return candidate

    candidate = base_name
    version = 1
    while (output_dir / f"{candidate}.md").exists() or (output_dir / f"{candidate}.docx").exists():
        version += 1
        candidate = f"{base_name}_v{version}"
    return candidate


def run_writer(
    topic: str,
    target_market: str,
    market_sizing: Optional[MarketSizing] = None,
    pestel_summaries: Optional[list[dict]] = None,
    competitors: Optional[list[Competitor]] = None,
    save: bool = True,
    revision_note: Optional[str] = None,
) -> str:
    """기획서 초안(마크다운 문자열)을 조립해 반환한다.

    market_sizing/pestel_summaries/competitors를 이미 가지고 있으면(Orchestrator가
    같은 실행 안에서 넘겨주는 경우) 그대로 받아 재계산을 피하고, 없으면(단독 CLI 실행)
    Fact Store에서 다시 조회/재계산한다. PESTEL은 새 웹검색 없이 이미 저장된 fact를
    다시 태깅하는 것뿐이라 재실행 비용이 크지 않다.

    revision_note(예: "1차 수정본")를 주면 문서 헤더와 저장 파일명 양쪽에 반영된다
    (Task #5, 2026-07-24) — orchestrator.graph의 writer_node가 revision_count를 보고
    자동으로 채워서 넘긴다. None이면(최초 초안) 기존과 완전히 동일하게 동작한다."""
    init_db()
    client = get_client()

    if market_sizing is None:
        market_sizing = latest_market_sizing(topic=topic)
    if competitors is None:
        competitors = list_competitors(topic=topic)
    if pestel_summaries is None:
        pestel_summaries = run_pestel_analysis(topic, target_market)

    print("[Writer 에이전트] 개요/핵심 요약 작성 중...")
    exec_summary = write_executive_summary(
        client, topic, target_market, market_sizing, pestel_summaries, competitors
    )

    sizing_md = _format_market_sizing_md(market_sizing)
    pestel_md = _format_pestel_md(pestel_summaries)
    competitor_table_md = _format_competitors_table_md(competitors)

    print("[Writer 에이전트] 경쟁사 포지셔닝 서술 작성 중...")
    positioning_md = write_positioning_narrative(client, competitors)

    print("[Writer 에이전트] 종합 시사점 작성 중...")
    synthesis_md = write_synthesis(
        client, topic, target_market, sizing_md, pestel_md, competitor_table_md
    )

    source_fact_ids = _collect_source_fact_ids(market_sizing, pestel_summaries, competitors)
    source_appendix_md = _format_source_appendix_md(source_fact_ids)

    revision_line = f"\n- 수정 차수: {revision_note}" if revision_note else ""

    doc = f"""# {topic} 사업 기획서 (초안)

- 목표시장: {target_market}
- 작성일: {date.today().isoformat()}
- 작성: AI 서비스 기획 보조 Multi-Agent (자동 생성 초안 — 사람 검수 필요){revision_line}

## 1. 개요

{exec_summary}

## 2. 시장 규모 분석 (TAM/SAM/SOM)

{sizing_md}

## 3. PESTEL 환경분석

{pestel_md}

## 4. 경쟁사 분석

{competitor_table_md}

{positioning_md}

## 5. 종합 시사점

{synthesis_md}

## 6. 출처 부록

{source_appendix_md}
"""

    print(f"[Writer 에이전트] 기획서 초안 조립 완료 ({len(doc)}자)")

    if save:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        base_name = f"{_slugify(topic)}_{_slugify(target_market)}_기획서초안"
        base_name = _versioned_base_name(OUTPUT_DIR, base_name, revision_note=revision_note)

        docx_path = export_to_docx(
            topic=topic,
            target_market=target_market,
            created_date=date.today().isoformat(),
            exec_summary=exec_summary,
            market_sizing=market_sizing,
            pestel_summaries=pestel_summaries,
            competitors=competitors,
            positioning_narrative=positioning_md,
            synthesis=synthesis_md,
            source_fact_ids=source_fact_ids,
            output_path=OUTPUT_DIR / f"{base_name}.docx",
            revision_note=revision_note,
        )
        print(f"[Writer 에이전트] 저장 완료(docx, 제출용): {docx_path}")

    return doc


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python -m agents.writer "<연구대상>" "<목표시장>"')
        print("(먼저 market_research/pestel/competitor 에이전트를 같은 연구대상으로 실행해둬야 합니다)")
        sys.exit(1)

    run_writer(sys.argv[1], sys.argv[2])
