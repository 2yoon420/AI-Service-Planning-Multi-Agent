"""
LangGraph Orchestrator (2차 구현 — Router + Human-in-the-loop 확장, 2026-07-24)

1차 구현(research -> {pestel, competitor} -> join -> writer -> END)은 "한 번 실행하면
끝까지 자동으로 도는" 고정 파이프라인이었다. 이번 확장은 router_orchestrator_설계안.md
"B안"을 반영해, writer 뒤에 사용자와 채팅으로 상호작용하는 구간을 이어붙인다:

    START -> research -> {pestel, competitor} (팬아웃) -> join -> writer
          -> await_review(사용자 확인 대기, interrupt()) -> router(LLM 판단)
          -> {research_revision, pestel_revision, competitor_revision, capability_qa,
              finalize} -> (재실행 노드는 다시 writer로) ... -> finalize -> END

기존 5개 노드(research/pestel/competitor/join/writer)와 그 사이 엣지는 설계안 3-2절
지침대로 그대로 둔다 — 이번 확장은 "갈아엎기"가 아니라 writer 뒤에 새 구간을 이어붙이는
것이다. writer_node만 딱 한 줄(awaiting_user 플래그) 추가됐다.

핵심 기술 요소(설계안 2절 참고):
  - interrupt(): 노드 안에서 호출하면 그 지점에서 그래프 실행이 멈추고, 호출부(FastAPI
    핸들러 또는 지금의 CLI 루프)에 payload를 반환한다. 사용자가 응답하면
    Command(resume=사용자입력)으로 정확히 멈췄던 지점부터 이어간다 — 처음부터 다시
    도는 게 아니다.
  - Command(goto=...): router_node만 이걸 쓴다 — 유일하게 "다음에 어디로 갈지"가
    사용자 메시지에 따라 실행 시점에 갈리는 노드이기 때문. 나머지 새 노드들
    (research_revision 등)은 항상 정해진 곳(writer 또는 await_review)으로만 가므로
    보통의 add_edge()로 충분하다 — Command는 진짜 분기가 필요한 곳에만 쓴다.
  - checkpointer: interrupt()가 동작하려면 그래프 상태를 저장소에 남겨야 한다.

체크포인터 선택에 대한 판단(설계안은 AsyncSqliteSaver를 제안했으나 이번 구현은 동기
SqliteSaver를 씀): FastAPI(Task #7)는 비동기라 AsyncSqliteSaver가 맞지만, 지금 이
파일과 모든 agents/*.py는 전부 동기 함수다. Task #4 시점에 굳이 비동기를 앞당겨
들이면 이 프로젝트의 모든 함수 호출 경로에 async/await를 새로 얹어야 해서, 2주
MVP 막바지에 위험이 큰 변경이라고 판단했다. 그래서 지금은 동기 SqliteSaver로 CLI에서
바로 테스트 가능한 상태로 구현하고, Task #7에서 FastAPI를 실제로 붙일 때
AsyncSqliteSaver + ainvoke()로 교체한다 — 그 시점엔 어차피 FastAPI 핸들러 자체가
비동기라 자연스러운 전환점이다.
"""

import operator
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from paths import data_path
from typing import Annotated, Optional, TypedDict

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agents.competitor import run_competitor_analysis
from agents.market_research import (
    calculate_market_sizing,
    get_client,
    run_market_research,
    run_targeted_research,
)
from agents.pestel import run_pestel_analysis
from agents.router import QA_CAP, REVISION_CAP, answer_capability_question, decide_next_action
from agents.writer import run_writer
from fact_store.schema import Competitor, Fact, MarketSizing
from fact_store.store import list_facts

import logging

log = logging.getLogger(__name__)

CHECKPOINT_DB_PATH = data_path("checkpoints.db", Path(__file__).parent / "checkpoints.db")

# 2026-07-24 추가: PlanningState에 fact_store.schema의 Pydantic 모델(Fact/MarketSizing/
# Competitor)과 그 안에 쓰이는 Enum(SourceTier/VerificationStatus/CompetitorType)이 그대로
# 담기는데, 체크포인터가 이걸 msgpack으로 직렬화하면서 "등록 안 된 타입 — 향후 버전에서
# 기본 차단될 수 있음" 경고를 냈다. allowed_msgpack_modules=True(전체 허용)로 끄지 않고
# 이 6개를 정확히 나열하는 이유는, 이 허용 목록 자체가 "신뢰 안 되는 데이터의 역직렬화로
# 인한 임의 코드 실행 방지"라는 보안 목적을 가지고 있어서다 — 실제로 이 프로젝트가 쓰는
# 타입만 정확히 열어주는 편이 안전하다(실제 경고 로그에 나온 6개와 정확히 일치).
_ALLOWED_MSGPACK_MODULES = [
    ("fact_store.schema", "SourceTier"),
    ("fact_store.schema", "VerificationStatus"),
    ("fact_store.schema", "Fact"),
    ("fact_store.schema", "MarketSizing"),
    ("fact_store.schema", "CompetitorType"),
    ("fact_store.schema", "Competitor"),
]


@contextmanager
def open_checkpointer(conn_string: str):
    """SqliteSaver.from_conn_string()과 동작은 같지만(연결을 열고, 끝나면 닫음),
    allowed_msgpack_modules를 지정한 커스텀 serde를 써서 위 경고를 없앤다.
    from_conn_string()은 serde를 받는 인자가 없어(langgraph 소스 확인함), 직접
    sqlite3.connect()로 연결을 열고 SqliteSaver(conn, serde=...)로 감싸는 방식으로
    똑같이 재현했다."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
    with closing(sqlite3.connect(conn_string, check_same_thread=False)) as conn:
        yield SqliteSaver(conn, serde=serde)


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

    # --- 2026-07-24 추가 (설계안 3-2절) ---
    # 매 턴 사용자/어시스턴트 메시지가 계속 쌓여야 하므로 operator.add로 누적한다.
    chat_history: Annotated[list[dict], operator.add]
    # router가 몇 번이나 재작업을 시켰는지 — REVISION_CAP(5회) 도달 시 자동 종료.
    revision_count: int
    # writer 완료 직후(재실행 포함) True, await_review에서 사용자 응답을 받으면 False.
    # interrupt() 자체는 "멈춰있음"을 상태값으로 커밋하지 못하므로(함수가 아직 return을
    # 안 한 시점이라), writer_node가 "곧 멈출 것"을 미리 표시해두는 방식으로 우회했다.
    awaiting_user: bool
    # router가 판단한 target_query를 재실행 노드/capability_qa에 전달하는 통로.
    pending_action_query: Optional[str]

    # --- 2026-07-27 추가 (FastAPI 설계도 10-2절) ---
    # writer_node가 만든 DOCX의 절대경로. 다운로드 엔드포인트가 이 값을 쓴다.
    draft_docx_path: Optional[str]
    # capability_qa 호출 횟수. revision_count와 달리 에이전트를 재실행하지 않으므로
    # 기존엔 아무 상한이 없었는데, API로 열면 무제한 LLM 비용이 된다(외부 검토 ⑥).
    qa_count: int


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
    log.info("\n[Orchestrator] research/PESTEL/경쟁사비교 완료 요약")
    log.info(f"  - fact: {len(state.get('facts', []))}개")
    log.info(f"  - PESTEL 축 요약: {len(state.get('pestel_summaries', []))}개")
    log.info(f"  - 경쟁사 프로필: {len(state.get('competitors', []))}개")
    errors = state.get("errors", [])
    if errors:
        log.info(f"  - 오류 {len(errors)}건 발생:")
        for e in errors:
            log.info(f"    · {e}")
    else:
        log.info("  - 오류 없음")
    return {}


def writer_node(state: PlanningState) -> dict:
    """Writer 에이전트 실행 — 앞선 세 에이전트의 결과(market_sizing/pestel_summaries/
    competitors)를 종합해 기획서 초안(.md)을 조립하고 저장한다.

    앞선 노드가 실패해서 state 값이 비어 있는 경우(예: competitor_node 실패 시
    state["competitors"]는 초기값인 빈 리스트로 남음), run_writer()에 그대로 빈 리스트를
    넘기면 "이번 실행 결과가 원래 없다"와 구분이 안 돼 Fact Store 재조회 폴백이 발동하지
    않는다. 그래서 falsy 값(빈 리스트/None)은 명시적으로 None으로 바꿔 넘겨, run_writer()가
    Fact Store에서 다시 조회하도록 유도한다.

    2026-07-24 추가: awaiting_user=True를 반환한다 — 이 노드 다음은 항상 await_review로
    가서 interrupt()로 멈추기 때문에, "곧 사용자 응답 대기 상태가 된다"를 여기서 미리
    커밋해둔다(interrupt() 자체는 실행 중인 함수 안에서 멈추는 것이라 상태값을 커밋할
    시점이 없음 — 자세한 설명은 파일 상단 PlanningState 주석 참고). Writer가 예외로
    실패해도 다음은 어차피 await_review이므로 awaiting_user는 True로 둔다.

    2026-07-24 추가(Task #5): revision_count가 0이면(최초 실행) revision_note 없이
    호출하고, 1 이상이면(재실행 노드를 거쳐 되돌아온 경우) "N차 수정본" 문구를 만들어
    run_writer()에 넘긴다 — 문서(마크다운·DOCX)와 저장 파일명 양쪽에 몇 차 수정본인지
    남기기 위함(설계안 3-5절, 사용자 요청으로 파일명까지 반영하도록 확장함)."""
    revision_count = state.get("revision_count", 0)
    revision_note = f"{revision_count}차 수정본" if revision_count > 0 else None
    try:
        doc, docx_path = run_writer(
            state["topic"],
            state["target_market"],
            market_sizing=state.get("market_sizing") or None,
            pestel_summaries=state.get("pestel_summaries") or None,
            competitors=state.get("competitors") or None,
            revision_note=revision_note,
            return_paths=True,
        )
        return {
            "draft_markdown": doc,
            "draft_docx_path": str(docx_path) if docx_path else None,
            "awaiting_user": True,
        }
    except Exception as e:
        return {"errors": [f"[Writer] {type(e).__name__}: {e}"], "awaiting_user": True}


def await_review_node(state: PlanningState) -> dict:
    """writer(또는 재실행 노드 경유 후 writer)가 초안을 만든 뒤 여기서 멈춰 사용자 확인을
    기다린다. interrupt()를 호출하면 그래프 실행이 이 지점에서 정지되고, 호출부(지금은
    CLI 루프, 나중엔 FastAPI 핸들러)에 payload가 반환된다. 사용자가
    Command(resume=사용자입력)으로 재개하면, 그 입력값이 이 interrupt() 호출의 반환값이
    되어 아래 코드가 이어서 실행된다 — 그래프가 처음부터 다시 도는 게 아니라 정확히 이
    지점부터 재개된다는 것이 핵심(설계안 4절 "효율성")."""
    user_message = interrupt(
        {
            "draft_markdown": state.get("draft_markdown"),
            "prompt": "초안을 확인한 후 수정사항이 있으면 채팅으로 입력해 주세요. 만족하시면 '완료' 또는 '승인'이라고 답해주세요.",
        }
    )
    return {
        "chat_history": [{"role": "user", "content": user_message}],
        "awaiting_user": False,
    }


def router_node(state: PlanningState) -> Command:
    """await_review에서 재개된 사용자 메시지를 보고 다음 행선지를 정한다(설계안 3-3절
    '옵션 B'). 실제 판단 로직(LLM 호출·스키마)은 agents.router.decide_next_action()에
    있다 — 이 노드는 그 결과를 받아 Command(goto=...)로 옮기기만 하는 얇은 배선
    역할이다(에이전트 로직과 그래프 배선을 분리하는 이 프로젝트의 기존 원칙).

    이 그래프에서 Command(goto=...)를 쓰는 유일한 노드다 — 목적지가 사용자 메시지에
    따라 매번 달라지는 진짜 분기이기 때문. 나머지 새 노드는 항상 정해진 한 곳으로만
    가므로 보통의 add_edge로 충분하다."""
    user_message = state["chat_history"][-1]["content"] if state.get("chat_history") else ""
    revision_count = state.get("revision_count", 0)

    if revision_count >= REVISION_CAP:
        return Command(
            goto="finalize",
            update={
                "chat_history": [
                    {
                        "role": "assistant",
                        "content": f"재작업 한도({REVISION_CAP}회)에 도달해 이번 초안으로 마무리합니다.",
                    }
                ]
            },
        )

    try:
        decision = decide_next_action(user_message, revision_count)
    except Exception as e:
        return Command(
            goto="await_review",
            update={
                "chat_history": [
                    {"role": "assistant", "content": "판단 중 오류가 발생했습니다. 다시 한번 말씀해 주시겠어요?"}
                ],
                "errors": [f"[Router] {type(e).__name__}: {e}"],
                "awaiting_user": True,
            },
        )

    log.info(f"[Router] action={decision['action']} | 근거: {decision['reasoning']}")
    action = decision["action"]
    target_query = decision.get("target_query", "")

    if action == "approve":
        return Command(
            goto="finalize",
            update={"chat_history": [{"role": "assistant", "content": "승인 확인 — 최종본으로 마무리합니다."}]},
        )
    if action == "revise_market_research":
        return Command(goto="research_revision", update={"pending_action_query": target_query})
    if action == "revise_pestel":
        return Command(goto="pestel_revision", update={"pending_action_query": target_query})
    if action == "revise_competitor":
        return Command(goto="competitor_revision", update={"pending_action_query": target_query})
    if action == "capability_question":
        if state.get("qa_count", 0) >= QA_CAP:
            return Command(
                goto="await_review",
                update={
                    "chat_history": [{
                        "role": "assistant",
                        "content": f"기능 질문 답변 한도({QA_CAP}회)에 도달했습니다. "
                                   f"초안 수정 요청만 처리할 수 있습니다.",
                    }],
                    "awaiting_user": True,
                },
            )
        return Command(goto="capability_qa", update={"pending_action_query": target_query})

    # action == "unclear" (또는 스키마 enum 밖의 예상 못 한 값 — 방어적으로 같은 경로로 처리)
    reply = decision.get("user_facing_reply") or "어떤 부분을 수정하면 될지 조금 더 구체적으로 말씀해 주세요."
    return Command(
        goto="await_review",
        update={
            "chat_history": [{"role": "assistant", "content": reply}],
            "awaiting_user": True,
        },
    )


def research_revision_node(state: PlanningState) -> dict:
    """Router가 revise_market_research로 판단했을 때 실행. run_targeted_research()로
    pending_action_query 하나만 좁게 검색해 Fact Store에 추가한 뒤, 새로 늘어난 fact를
    반영해 시장 규모(TAM/SAM/SOM)를 다시 계산한다 — 설계안엔 명시되지 않았지만, 재검색만
    하고 시장 규모를 그대로 두면 이 재작업의 실질적 의미가 없다고 판단해 추가했다.

    끝나면 항상 writer로 돌아간다(보통의 add_edge로 연결 — 이 노드의 다음 행선지는
    항상 writer 하나뿐이라 Command가 필요 없다)."""
    topic, target_market = state["topic"], state["target_market"]
    query = state.get("pending_action_query") or f"{topic} 관련 추가 정보"
    try:
        run_targeted_research(topic, target_market, query)
        client = get_client()
        all_facts = list_facts(topic=topic)
        sizing = calculate_market_sizing(client, topic, target_market, all_facts)
        return {
            "facts": all_facts,
            "market_sizing": sizing,
            "revision_count": state.get("revision_count", 0) + 1,
        }
    except Exception as e:
        return {
            "errors": [f"[시장조사 재실행] {type(e).__name__}: {e}"],
            "revision_count": state.get("revision_count", 0) + 1,
        }


def pestel_revision_node(state: PlanningState) -> dict:
    """Router가 revise_pestel로 판단했을 때 실행. PESTEL 에이전트는 원래 새 웹검색을 하지
    않으므로(Fact Store에 이미 있는 fact를 재태깅·재요약할 뿐), 여기서도 새 검색 없이
    run_pestel_analysis()만 다시 부른다. 재검색이 필요한 요청이면 Router가
    revise_market_research로 먼저 보내야 한다."""
    topic, target_market = state["topic"], state["target_market"]
    try:
        summaries = run_pestel_analysis(topic, target_market)
        return {"pestel_summaries": summaries, "revision_count": state.get("revision_count", 0) + 1}
    except Exception as e:
        return {
            "errors": [f"[PESTEL 재실행] {type(e).__name__}: {e}"],
            "revision_count": state.get("revision_count", 0) + 1,
        }


def competitor_revision_node(state: PlanningState) -> dict:
    """Router가 revise_competitor로 판단했을 때 실행. run_competitor_analysis()를 통째로
    다시 돌린다 — 경쟁사 가격/투자유치 정보는 시간에 따라 바뀌고 처음부터 못 찾은 항목도
    있을 수 있어, PESTEL과 달리 재검색부터 다시 하는 쪽을 택했다(시장조사 재실행과 같은
    패턴)."""
    topic, target_market = state["topic"], state["target_market"]
    try:
        competitors = run_competitor_analysis(topic, target_market)
        return {"competitors": competitors, "revision_count": state.get("revision_count", 0) + 1}
    except Exception as e:
        return {
            "errors": [f"[경쟁사비교 재실행] {type(e).__name__}: {e}"],
            "revision_count": state.get("revision_count", 0) + 1,
        }


def capability_qa_node(state: PlanningState) -> dict:
    """Router가 capability_question으로 판단했을 때 실행. fact_store나 다른 에이전트를
    전혀 건드리지 않고 서비스 기능 RAG(capability_corpus)에서만 답을 찾아 chat_history에
    추가한다. 에이전트 재실행이 아니므로 revision_count는 올리지 않는다(설계안 3-2절).

    2026-07-27 추가: qa_count는 올린다 — API로 노출되면 호출 횟수 자체엔 상한이
    없었으므로(REVISION_CAP과 달리), router_node가 QA_CAP 도달 여부를 판단하는
    근거로 여기서 센다."""
    question = state.get("pending_action_query", "")
    next_qa_count = state.get("qa_count", 0) + 1
    try:
        answer = answer_capability_question(question)
        return {
            "chat_history": [{"role": "assistant", "content": answer}],
            "qa_count": next_qa_count,
        }
    except Exception as e:
        return {
            "chat_history": [{"role": "assistant", "content": "죄송합니다, 답변 생성 중 오류가 발생했습니다."}],
            "errors": [f"[capability_qa] {type(e).__name__}: {e}"],
            "qa_count": next_qa_count,
        }


def finalize_node(state: PlanningState) -> dict:
    """세션 종료 처리 — 승인 또는 재작업 한도 도달로 도달한다. 새 부가 로직은 없고,
    join_node와 같은 원칙으로 종료 사유를 로그에 남긴다."""
    log.info("\n[Orchestrator] 세션 종료 처리")
    if state.get("revision_count", 0) >= REVISION_CAP:
        log.info(f"  - 재작업 한도({REVISION_CAP}회) 도달로 자동 종료")
    else:
        log.info("  - 사용자 승인으로 종료")
    return {}


def build_graph(checkpointer=None):
    graph = StateGraph(PlanningState)
    graph.add_node("research", research_node)
    graph.add_node("pestel", pestel_node)
    graph.add_node("competitor", competitor_node)
    graph.add_node("join", join_node)
    graph.add_node("writer", writer_node)
    graph.add_node("await_review", await_review_node)
    graph.add_node("router", router_node)
    graph.add_node("research_revision", research_revision_node)
    graph.add_node("pestel_revision", pestel_revision_node)
    graph.add_node("competitor_revision", competitor_revision_node)
    graph.add_node("capability_qa", capability_qa_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "research")
    graph.add_edge("research", "pestel")
    graph.add_edge("research", "competitor")
    graph.add_edge("pestel", "join")
    graph.add_edge("competitor", "join")
    graph.add_edge("join", "writer")

    # --- 2026-07-24 추가 구간 (설계안 3-2절) ---
    graph.add_edge("writer", "await_review")
    graph.add_edge("await_review", "router")
    # research_revision/pestel_revision/competitor_revision/capability_qa/finalize는
    # router_node의 Command(goto=...)로만 진입한다(정적 add_edge로 들어오는 경로는 없음).
    # 그 다음 행선지는 각각 항상 하나뿐이라 여기는 보통의 add_edge로 충분하다.
    graph.add_edge("research_revision", "writer")
    graph.add_edge("pestel_revision", "writer")
    graph.add_edge("competitor_revision", "writer")
    graph.add_edge("capability_qa", "await_review")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


def _initial_state(topic: str, target_market: str) -> PlanningState:
    return {
        "topic": topic,
        "target_market": target_market,
        "facts": [],
        "market_sizing": None,
        "pestel_summaries": [],
        "competitors": [],
        "draft_markdown": None,
        "errors": [],
        "chat_history": [],
        "revision_count": 0,
        "awaiting_user": False,
        "pending_action_query": None,
        "draft_docx_path": None,
        "qa_count": 0,
    }


def _extract_response(result: dict) -> dict:
    """FastAPI(Task #7)와 지금의 CLI 루프가 함께 재사용할 응답 요약. interrupt 중이면
    아직 사용자 응답을 기다리는 중(paused=True)이고, 아니면 finalize를 거쳐 END에
    도달한 것(paused=False)이다."""
    interrupts = result.get("__interrupt__")
    if interrupts:
        payload = interrupts[0].value
        return {
            "paused": True,
            "draft_markdown": payload.get("draft_markdown"),
            "draft_docx_path": result.get("draft_docx_path"),
            "prompt": payload.get("prompt"),
        }
    return {
        "paused": False,
        "draft_markdown": result.get("draft_markdown"),
        "draft_docx_path": result.get("draft_docx_path"),
        "errors": result.get("errors", []),
    }


def start_project(
    topic: str, target_market: str, thread_id: str, checkpointer=None, graph=None
) -> dict:
    """새 프로젝트를 최초 실행한다. research -> ... -> writer까지 실행된 뒤 await_review의
    interrupt()에서 멈추고, 초안과 안내 문구를 담은 응답을 반환한다.

    thread_id는 project_id와 같은 개념으로 쓰인다 — LangGraph는 이 값으로 체크포인터에
    저장된 그래프 상태를 구분한다(설계안 3-2절 참고).

    graph를 주면(FastAPI가 앱 시작 시 미리 컴파일해둔 그래프를 넘기는 경우) checkpointer를
    다시 열거나 build_graph()를 다시 부르지 않고 그 그래프를 그대로 쓴다 — 매 요청마다
    sqlite 연결을 새로 여는 낭비를 없애기 위함(설계도 4-3절). graph도 checkpointer도
    안 주면(기존 CLI 동작) 이 프로젝트 폴더의 orchestrator/checkpoints.db를 쓰는 동기
    SqliteSaver를 연다. 테스트 코드에서는 checkpointer로 MemorySaver 등을 직접 넘겨 파일
    없이 검증할 수 있다."""
    config = {"configurable": {"thread_id": thread_id}}
    initial = _initial_state(topic, target_market)
    if graph is not None:
        return _extract_response(graph.invoke(initial, config=config))
    if checkpointer is not None:
        return _extract_response(build_graph(checkpointer).invoke(initial, config=config))
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        return _extract_response(build_graph(saver).invoke(initial, config=config))


def submit_message(thread_id: str, message: str, checkpointer=None, graph=None) -> dict:
    """await_review에서 멈춰 있는 프로젝트에 사용자 메시지를 전달해 재개한다.
    router가 판단해 재실행 노드를 거치면 다시 await_review에서 멈추고(paused=True),
    승인되거나 재작업 한도에 도달하면 finalize를 거쳐 END에 도달한다(paused=False).

    graph 재사용 규칙은 start_project()와 같다."""
    config = {"configurable": {"thread_id": thread_id}}
    command = Command(resume=message)
    if graph is not None:
        return _extract_response(graph.invoke(command, config=config))
    if checkpointer is not None:
        return _extract_response(build_graph(checkpointer).invoke(command, config=config))
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        return _extract_response(build_graph(saver).invoke(command, config=config))


def get_session_state(thread_id: str, graph) -> dict:
    """지금 이 세션이 어느 노드를 실행 중이고 어떤 상태인지 반환한다.
    _check_existing_session()이 하던 일을 일반화한 것 — 그 함수는 이 함수를 부르는
    얇은 래퍼로 바뀐다(CLI 동작은 그대로)."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = graph.get_state(config)
    values = snapshot.values or {}

    interrupted = False
    prompt = None
    for task in snapshot.tasks:
        if task.interrupts:
            interrupted = True
            prompt = task.interrupts[0].value.get("prompt")
            break

    return {
        "exists": bool(values),
        "next_nodes": tuple(snapshot.next or ()),
        "interrupted": interrupted,
        "prompt": prompt,
        "draft_markdown": values.get("draft_markdown"),
        "draft_docx_path": values.get("draft_docx_path"),
        "chat_history": values.get("chat_history", []),
        "revision_count": values.get("revision_count", 0),
        "qa_count": values.get("qa_count", 0),
    }


def _check_existing_session(thread_id: str) -> Optional[dict]:
    """thread_id에 await_review로 이미 멈춰있는 세션이 있으면 그 payload를 반환하고,
    없으면(새 thread_id이거나 이미 finalize까지 끝난 thread_id) None을 반환한다.
    CLI 전용. get_session_state()의 얇은 래퍼로 축소한다(2026-07-27).

    2026-07-24 추가: 사용자가 같은 topic으로 CLI를 반복 실행하면(예: 세션 중간에
    Ctrl-C 후 재실행) 매번 research_node부터 다시 돌아 Fact Store에 fact가 계속
    쌓이는 문제를 지적함. 재현해 확인한 원인 — LangGraph는 같은 thread_id라도
    "이미 실행한 적 있으니 건너뛴다" 같은 자동 판단을 하지 않고, 새 initial state로
    invoke하면 매번 START부터 그대로 다시 실행한다(start_project()는 항상 "새 프로젝트
    시작"이라는 뜻). 그래서 CLI가 먼저 "이미 멈춰있는 세션이 있는지"를 확인해, 있으면
    start_project() 호출 자체를 건너뛰도록 했다."""
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        snapshot = get_session_state(thread_id, build_graph(saver))
    if not snapshot["next_nodes"]:
        return None
    if not snapshot["interrupted"]:
        return None
    return {
        "paused": True,
        "draft_markdown": snapshot["draft_markdown"],
        "prompt": snapshot["prompt"],
    }


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 3:
        print('사용법: python -m orchestrator.graph "<연구대상>" "<목표시장>" [thread_id]')
        sys.exit(1)

    topic_arg, target_market_arg = sys.argv[1], sys.argv[2]
    thread_id_arg = sys.argv[3] if len(sys.argv) > 3 else f"{topic_arg}_{target_market_arg}"

    response = _check_existing_session(thread_id_arg)
    if response is not None:
        log.info(f"[Orchestrator] 기존 세션을 이어갑니다 (thread_id={thread_id_arg}) — 리서치를 다시 하지 않습니다.")
    else:
        log.info(f"[Orchestrator] 새 프로젝트 시작 (thread_id={thread_id_arg})")
        response = start_project(topic_arg, target_market_arg, thread_id_arg)

    while response.get("paused"):
        draft_preview = (response.get("draft_markdown") or "")[:500]
        log.info(f"\n{response.get('prompt', '')}")
        log.info(f"\n--- 초안 미리보기(앞부분 500자) ---\n{draft_preview}\n---")
        try:
            user_input = input("\n> ")
        except EOFError:
            log.info("\n(입력 종료 — 세션은 저장되어 있으니 같은 thread_id로 나중에 다시 이어갈 수 있습니다.)")
            break
        response = submit_message(thread_id_arg, user_input)

    if not response.get("paused"):
        log.info("\n[Orchestrator] 세션 종료 — 최종 기획서 초안이 완성되었습니다.")
        if response.get("errors"):
            log.info(f"  (참고: 진행 중 오류 {len(response['errors'])}건 — 위 로그 참고)")
