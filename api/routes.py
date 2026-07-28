"""엔드포인트 정의. 로직은 registry/runner/graph로 위임하고 여기는 얇게 유지한다
(이 프로젝트가 지켜온 '노드 함수는 얇게, 실제 로직은 별도 모듈에' 원칙의 연장)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, PlainTextResponse

from api import registry, runner
from api.logbus import EVENT_BUS
from api.schemas import (
    ChatHistoryResponse,
    ChatMessage,
    CreateProjectRequest,
    CreateProjectResponse,
    EventsResponse,
    FactStatsResponse,
    MessageRequest,
    ProjectDetail,
    ProjectSummary,
    DRAFT_PREVIEW_CHARS,
    describe_steps,
)
from fact_store.store import list_facts
from orchestrator.graph import get_session_state, start_project, submit_message

router = APIRouter()


def _require_project(project_id: str) -> dict:
    row = registry.get_project(project_id)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"프로젝트를 찾을 수 없습니다: {project_id}"
        )
    return row


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post(
    "/projects",
    response_model=CreateProjectResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project(payload: CreateProjectRequest, request: Request):
    project_id = str(uuid.uuid4())
    row = registry.create_project(project_id, payload.topic, payload.target_market)

    graph = request.app.state.graph

    def _job() -> dict:
        return start_project(
            payload.topic, payload.target_market, project_id, graph=graph
        )

    await runner.launch(project_id, _job)
    return CreateProjectResponse(
        project_id=project_id,
        status=registry.STATUS_RUNNING,
        created_at=row["created_at"],
    )


@router.get("/projects", response_model=list[ProjectSummary])
def list_all_projects():
    return [ProjectSummary(**row) for row in registry.list_projects()]


@router.get("/projects/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: str, request: Request):
    row = _require_project(project_id)
    snapshot = get_session_state(project_id, request.app.state.graph)

    draft_markdown = snapshot.get("draft_markdown")
    docx_path = row.get("docx_path") or snapshot.get("draft_docx_path")

    return ProjectDetail(
        project_id=row["project_id"],
        topic=row["topic"],
        target_market=row["target_market"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        current_step=(
            describe_steps(snapshot["next_nodes"])
            if row["status"] == registry.STATUS_RUNNING
            else None
        ),
        next_nodes=list(snapshot["next_nodes"]),
        revision_count=snapshot.get("revision_count", 0),
        qa_count=snapshot.get("qa_count", 0),
        prompt=snapshot.get("prompt"),
        draft_preview=(draft_markdown or "")[:DRAFT_PREVIEW_CHARS] or None,
        draft_available=bool(docx_path and Path(docx_path).exists()),
        latest_event_seq=EVENT_BUS.latest_seq(project_id),
        error=row.get("error"),
    )


@router.post(
    "/projects/{project_id}/messages", status_code=status.HTTP_202_ACCEPTED
)
async def post_message(project_id: str, payload: MessageRequest, request: Request):
    row = _require_project(project_id)

    if row["status"] in registry.BUSY_STATUSES or runner.is_busy(project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "이 프로젝트는 아직 처리 중입니다. 완료 후 다시 시도해 주세요.",
        )
    if row["status"] in registry.CLOSED_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "이미 종료된 프로젝트입니다."
        )

    graph = request.app.state.graph

    def _job() -> dict:
        return submit_message(project_id, payload.message, graph=graph)

    await runner.launch(project_id, _job)
    return {"project_id": project_id, "status": registry.STATUS_RUNNING}


@router.get("/projects/{project_id}/events", response_model=EventsResponse)
def get_events(project_id: str, since: int = 0):
    _require_project(project_id)
    return EventsResponse(
        project_id=project_id,
        events=EVENT_BUS.events_since(project_id, since),
        latest_seq=EVENT_BUS.latest_seq(project_id),
    )


@router.get("/projects/{project_id}/messages", response_model=ChatHistoryResponse)
def get_chat_history(project_id: str, request: Request):
    _require_project(project_id)
    snapshot = get_session_state(project_id, request.app.state.graph)
    return ChatHistoryResponse(
        project_id=project_id,
        messages=[ChatMessage(**m) for m in snapshot.get("chat_history", [])],
    )


@router.get("/projects/{project_id}/draft")
def download_draft(project_id: str):
    row = _require_project(project_id)
    docx_path = row.get("docx_path")
    if not docx_path or not Path(docx_path).exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "아직 생성된 기획서 초안(DOCX)이 없습니다."
        )
    return FileResponse(
        path=docx_path,
        filename=Path(docx_path).name,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )


@router.get("/projects/{project_id}/draft/markdown", response_class=PlainTextResponse)
def get_draft_markdown(project_id: str, request: Request):
    _require_project(project_id)
    snapshot = get_session_state(project_id, request.app.state.graph)
    markdown = snapshot.get("draft_markdown")
    if not markdown:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "아직 초안이 없습니다.")
    return PlainTextResponse(markdown)


@router.get("/projects/{project_id}/facts", response_model=FactStatsResponse)
def get_fact_stats(project_id: str):
    row = _require_project(project_id)
    facts = list_facts(topic=row["topic"])

    by_verification: dict[str, int] = {}
    by_source_tier: dict[str, int] = {}
    needs_check = 0
    for fact in facts:
        # verification_status가 None인 레거시 fact는 '기각'과 구분해서 센다
        # (fact_store/schema.py의 필드 주석이 명시한 지시).
        label = fact.verification_status.value if fact.verification_status else "미검증"
        by_verification[label] = by_verification.get(label, 0) + 1
        tier = fact.source_tier.value
        by_source_tier[tier] = by_source_tier.get(tier, 0) + 1
        if fact.needs_source_check:
            needs_check += 1

    return FactStatsResponse(
        project_id=project_id,
        total=len(facts),
        by_verification=by_verification,
        by_source_tier=by_source_tier,
        needs_source_check=needs_check,
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str):
    _require_project(project_id)
    if runner.is_busy(project_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "실행 중인 프로젝트는 삭제할 수 없습니다."
        )
    registry.delete_project(project_id)
    EVENT_BUS.clear(project_id)
    # 체크포인터의 해당 thread 기록은 남는다 — LangGraph가 소유한 데이터를
    # 우리가 직접 지우지 않는다는 원칙(설계도 6-2절). 필요하면 별도 정리 스크립트로.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
