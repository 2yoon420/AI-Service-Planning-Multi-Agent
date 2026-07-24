"""
LangGraph Orchestrator (1차 구현)

지금까지 시장조사·PESTEL·경쟁사비교 세 에이전트는 `python -m agents.xxx` CLI로
사람이 순서대로 하나씩 실행해야 했다. 실제로는 공유 Fact Store(SQLite)를 통해
간접적으로 이어져 있었으나(시장조사가 저장한 fact를 PESTEL·경쟁사비교가
list_facts()로 재조회), 실행 순서·재시도·에러 처리는 전부 수동이었다.

이 모듈은 지금까지의 네 에이전트(시장조사·PESTEL·경쟁사비교·Writer)를 하나의 그래프로 묶는다:

    START -> research -> {pestel, competitor} (팬아웃) -> join -> writer -> END

PESTEL과 경쟁사비교는 서로 다른 state 키(pestel_summaries / competitors)에만
쓰고, 이미 Fact Store만 공유하는 독립적인 로직이라 병렬 실행이 자연스럽다.

Writer는 2026-07-22에 연결했다(파이프라인 문서 24절 참고) — join 뒤에 이어붙여
market_sizing/pestel_summaries/competitors를 종합해 기획서 초안(.md)을 조립·저장한다.
Human Checkpoint는 아직 로직 자체가 없어 이번 구현 범위에서 의도적으로 제외했다
(파이프라인 문서 20절 참고).
"""

import operator
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.competitor import run_competitor_analysis
from agents.market_research import run_market_research
from agents.pestel import run_pestel_analysis
from agents.writer import run_writer
from fact_store.schema import Competitor, Fact, MarketSizing


class PlanningState(TypedDict):
    topic: str
    target_market: str
    facts: list[Fact]
    market_sizing: Optional[MarketSizing]
    pestel_summaries: list[dict]
    competitors: list[Competitor]
    draft_markdown: Optional[str]
    # 여러 노드(pestel, competitor)가 같은 스텝에서 동시에 값을 추가할 수 있으므로
    # operator.add를 리듀서로 지정한다 (그냥 list[str]로 두면 LangGraph가
    # "같은 키에 두 값이 동시에 들어옴" 오류를 낸다).
    errors: Annotated[list[str], operator.add]


def research_node(state: PlanningState) -> dict:
    """시장조사 에이전트 실행 — 리서치 질문 생성부터 TAM/SAM/SOM 계산까지."""
    try:
        facts, sizing = run_market_research(state["topic"], state["target_market"])
        return {"facts": facts, "market_sizing": sizing}
    except Exception as e:
        return {"errors": [f"[시장조사] {type(e).__name__}: {e}"]}


def pestel_node(state: PlanningState) -> dict:
    """PESTEL 에이전트 실행 — Fact Store에 이미 저장된 fact를 재조회해 6축 태깅·요약."""
    try:
        summaries = run_pestel_analysis(state["topic"], state["target_market"])
        return {"pestel_summaries": summaries}
    except Exception as e:
        return {"errors": [f"[PESTEL] {type(e).__name__}: {e}"]}


def competitor_node(state: PlanningState) -> dict:
    """경쟁사비교 에이전트 실행 — 경쟁사 식별부터 심층조사·프로필 구조화까지."""
    try:
        competitors = run_competitor_analysis(state["topic"], state["target_market"])
        return {"competitors": competitors}
    except Exception as e:
        return {"errors": [f"[경쟁사비교] {type(e).__name__}: {e}"]}


def join_node(state: PlanningState) -> dict:
    """PESTEL·경쟁사비교 결과를 합쳐 중간 요약 로그를 출력. 파이프라인은 여기서 끝나지
    않고 뒤이어 writer 노드로 넘어간다."""
    print("\n[Orchestrator] research/PESTEL/경쟁사비교 완료 요약")
    print(f"  - fact: {len(state.get('facts', []))}개")
    print(f"  - PESTEL 축 요약: {len(state.get('pestel_summaries', []))}개")
    print(f"  - 경쟁사 프로필: {len(state.get('competitors', []))}개")
    errors = state.get("errors", [])
    if errors:
        print(f"  - 오류 {len(errors)}건 발생:")
        for e in errors:
            print(f"    · {e}")
    else:
        print("  - 오류 없음")
    return {}


def writer_node(state: PlanningState) -> dict:
    """Writer 에이전트 실행 — 앞선 세 에이전트의 결과(market_sizing/pestel_summaries/
    competitors)를 종합해 기획서 초안(.md)을 조립하고 저장한다.

    앞선 노드가 실패해서 state 값이 비어 있는 경우(예: competitor_node 실패 시
    state["competitors"]는 초기값인 빈 리스트로 남음), run_writer()에 그대로 빈 리스트를
    넘기면 "이번 실행 결과가 원래 없다"와 구분이 안 돼 Fact Store 재조회 폴백이 발동하지
    않는다. 그래서 falsy 값(빈 리스트/None)은 명시적으로 None으로 바꿔 넘겨, run_writer()가
    Fact Store에서 다시 조회하도록 유도한다."""
    try:
        doc = run_writer(
            state["topic"],
            state["target_market"],
            market_sizing=state.get("market_sizing") or None,
            pestel_summaries=state.get("pestel_summaries") or None,
            competitors=state.get("competitors") or None,
        )
        return {"draft_markdown": doc}
    except Exception as e:
        return {"errors": [f"[Writer] {type(e).__name__}: {e}"]}


def build_graph():
    graph = StateGraph(PlanningState)
    graph.add_node("research", research_node)
    graph.add_node("pestel", pestel_node)
    graph.add_node("competitor", competitor_node)
    graph.add_node("join", join_node)
    graph.add_node("writer", writer_node)

    graph.add_edge(START, "research")
    graph.add_edge("research", "pestel")
    graph.add_edge("research", "competitor")
    graph.add_edge("pestel", "join")
    graph.add_edge("competitor", "join")
    graph.add_edge("join", "writer")
    graph.add_edge("writer", END)

    return graph.compile()


def run(topic: str, target_market: str) -> PlanningState:
    app = build_graph()
    initial_state: PlanningState = {
        "topic": topic,
        "target_market": target_market,
        "facts": [],
        "market_sizing": None,
        "pestel_summaries": [],
        "competitors": [],
        "draft_markdown": None,
        "errors": [],
    }
    result = app.invoke(initial_state)
    if result.get("draft_markdown"):
        print(f"\n[Orchestrator] 기획서 초안 조립 완료 ({len(result['draft_markdown'])}자)")
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print('사용법: python -m orchestrator.graph "<연구대상>" "<목표시장>"')
        sys.exit(1)

    run(sys.argv[1], sys.argv[2])
