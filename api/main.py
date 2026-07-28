"""FastAPI 앱 진입점.

실행: uvicorn api.main:app --reload --port 8000  (반드시 워커 1개 — 설계도 13절 한계)
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import registry
from api.logbus import EVENT_BUS, install_log_handler
from api.routes import router
from orchestrator.graph import (
    CHECKPOINT_DB_PATH,
    build_graph,
    get_session_state,
    open_checkpointer,
)


def _recover_zombie_sessions(graph) -> None:
    """서버가 죽었을 때 running으로 남은 레코드를 정리한다(설계도 5-4절).

    체크포인터에 interrupt가 남아 있으면 사용자 대기 상태로 복구할 수 있고,
    아니면 실행이 중간에 유실된 것이므로 interrupted로 표시해 사용자에게 알린다."""
    for project_id in registry.running_project_ids():
        try:
            snapshot = get_session_state(project_id, graph)
        except Exception:
            snapshot = {"interrupted": False}
        if snapshot.get("interrupted"):
            registry.update_project(project_id, status=registry.STATUS_AWAITING)
        else:
            registry.update_project(
                project_id,
                status=registry.STATUS_INTERRUPTED,
                error="서버가 재시작되어 실행이 중단되었습니다. 메시지를 다시 보내면 이어집니다.",
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry.init_db()
    install_log_handler()
    EVENT_BUS.bind_loop(asyncio.get_running_loop())

    # 체크포인터 연결과 컴파일된 그래프를 앱 수명 동안 하나만 유지한다(설계도 4-3절).
    with open_checkpointer(str(CHECKPOINT_DB_PATH)) as saver:
        app.state.graph = build_graph(saver)
        _recover_zombie_sessions(app.state.graph)
        yield


app = FastAPI(
    title="AI 서비스 기획 보조 Multi-Agent API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)

# --- CORS (2026-07-27 활성화, 프론트엔드_설계도.md 8-1절) ---
# 프론트엔드(Vite 개발 서버 5173)와 API(8000)의 출처가 달라서 필요하다.
# 로컬 개발 전용이므로 출처를 정확히 나열한다 — allow_origins=["*"]로 열지 않는다.
# import는 상단에 있다(2026-07-28, 외부검토 2-⑤). add_middleware는 app 객체가
# 만들어진 뒤에만 호출할 수 있으므로 이 호출부는 여기 남는다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
    expose_headers=["Content-Disposition"],   # DOCX 다운로드 파일명에 필요
)
