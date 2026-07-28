"""요청/응답 Pydantic 모델 + 노드 라벨 매핑."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# 초안 미리보기 길이. 전문은 GET /projects/{id}/draft/markdown 으로 받는다.
DRAFT_PREVIEW_CHARS = 1000

# graph.get_state().next에 담긴 노드 이름 → 사람이 읽는 한글 라벨 (설계도 5-2절).
# 팬아웃 구간에서는 여러 개가 동시에 나오므로 호출부가 " · "로 이어 붙인다.
NODE_LABELS: dict[str, str] = {
    "research": "시장조사 진행 중",
    "pestel": "PESTEL 분석 진행 중",
    "competitor": "경쟁사 분석 진행 중",
    "join": "중간 집계 중",
    "writer": "기획서 초안 작성 중",
    "await_review": "사용자 확인 대기",
    "router": "요청 판단 중",
    "research_revision": "시장조사 재실행 중",
    "pestel_revision": "PESTEL 재분석 중",
    "competitor_revision": "경쟁사 재분석 중",
    "capability_qa": "기능 질문 답변 중",
    "finalize": "마무리 중",
}


def describe_steps(node_names: tuple[str, ...]) -> Optional[str]:
    if not node_names:
        return None
    return " · ".join(NODE_LABELS.get(n, n) for n in node_names)


class CreateProjectRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="연구대상 (예: 스마트 반려동물 건강관리 기기)")
    target_market: str = Field(..., min_length=1, description="목표시장 (예: 북미 반려동물 오너 시장)")


class CreateProjectResponse(BaseModel):
    project_id: str
    status: str
    created_at: str


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1, description="사용자가 초안을 보고 입력한 채팅")


class ProjectSummary(BaseModel):
    project_id: str
    topic: str
    target_market: str
    status: str
    created_at: str
    updated_at: str


class ProjectDetail(ProjectSummary):
    current_step: Optional[str] = Field(None, description="running일 때만 채워진다")
    next_nodes: list[str] = Field(
        default_factory=list,
        description="지금 실행 중인 그래프 노드 ID. 프론트엔드 단계 표시용 "
                    "(current_step은 사람이 읽는 라벨, 이쪽은 기계가 읽는 ID)",
    )
    revision_count: int = 0
    qa_count: int = 0
    prompt: Optional[str] = Field(None, description="interrupt() payload의 안내 문구")
    draft_preview: Optional[str] = None
    draft_available: bool = False
    latest_event_seq: int = Field(0, description="이 값을 다음 /events 호출의 since로 넘긴다")
    error: Optional[str] = None


class EventItem(BaseModel):
    seq: int
    ts: str
    kind: str
    level: str
    message: str
    # kind에 따라 선택적으로 채워지는 구조화 필드 (설계도 7-3절)
    url: Optional[str] = None
    tier: Optional[str] = None
    title: Optional[str] = None
    step: Optional[str] = None
    count: Optional[int] = None


class EventsResponse(BaseModel):
    project_id: str
    events: list[EventItem]
    latest_seq: int


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    project_id: str
    messages: list[ChatMessage]


class FactStatsResponse(BaseModel):
    """외부 검토보고서 ④ — 기각/애매 fact 통계를 초안 밖으로 노출하는 자리."""

    project_id: str
    total: int
    by_verification: dict[str, int]
    by_source_tier: dict[str, int]
    needs_source_check: int
