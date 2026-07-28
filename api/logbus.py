"""프로젝트별 진행 이벤트 버스 (설계도 7절).

agents/*.py가 logging으로 남기는 진행 로그를 project_id 단위로 모아 API가 조회할 수
있게 한다. 백그라운드 스레드에서 발생하는 로그를 어느 프로젝트 것인지 구분하는 문제는
ContextVar로 푼다 — runner.py가 스레드 진입 직후 current_project_id를 세팅하면,
그 스레드에서 발생하는 모든 로그 레코드가 해당 프로젝트로 귀속된다.

SSE 승격 대비(설계도 7-3절): 이벤트는 처음부터 객체(dict)로 만들고, 이벤트 루프
참조와 구독자 큐를 들고 있을 자리를 비워둔다. 지금은 구독자가 0이라 실질적으로
아무 일도 하지 않지만, 나중에 SSE 엔드포인트를 추가할 때 이 자리만 쓰면 된다.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

# 프로젝트 하나당 보관할 최대 이벤트 수. 넘으면 오래된 것부터 버린다(deque maxlen).
# fact 119건 실행에서 로그가 대략 500~800줄이었으므로 2000이면 한 세션은 충분히 담긴다.
MAX_EVENTS_PER_PROJECT = 2000

# 지금 이 스레드가 어느 프로젝트를 처리 중인지. runner.py가 세팅한다.
current_project_id: ContextVar[Optional[str]] = ContextVar("current_project_id", default=None)

# logging 레코드에서 이벤트로 옮겨 실을 구조화 필드. 여기 없는 extra는 무시된다.
_STRUCTURED_FIELDS = ("url", "tier", "title", "step", "count")


class ProjectEventBus:
    """프로젝트별 이벤트 링버퍼. 스레드에서 write, 이벤트 루프에서 read 하므로
    threading.Lock으로 보호한다(asyncio.Lock이 아니다 — 쓰는 쪽이 스레드다)."""

    def __init__(self) -> None:
        self._buffers: dict[str, deque] = {}
        self._seq: dict[str, int] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """FastAPI lifespan에서 한 번 호출. SSE 승격 시 스레드→async 브리지에 필요하다."""
        self._loop = loop

    def publish(self, project_id: str, event: dict) -> None:
        with self._lock:
            seq = self._seq.get(project_id, 0) + 1
            self._seq[project_id] = seq
            full_event = {"seq": seq, **event}
            buffer = self._buffers.setdefault(
                project_id, deque(maxlen=MAX_EVENTS_PER_PROJECT)
            )
            buffer.append(full_event)
            subscribers = list(self._subscribers.get(project_id, []))

        # --- SSE 승격 자리 (지금은 subscribers가 항상 비어 있어 아무 일도 안 함) ---
        if self._loop is not None and subscribers:
            for queue in subscribers:
                self._loop.call_soon_threadsafe(queue.put_nowait, full_event)

    def events_since(self, project_id: str, since: int = 0) -> list[dict]:
        with self._lock:
            buffer = self._buffers.get(project_id)
            if not buffer:
                return []
            return [e for e in buffer if e["seq"] > since]

    def latest_seq(self, project_id: str) -> int:
        with self._lock:
            return self._seq.get(project_id, 0)

    def clear(self, project_id: str) -> None:
        with self._lock:
            self._buffers.pop(project_id, None)
            self._seq.pop(project_id, None)
            self._subscribers.pop(project_id, None)

    # --- 아래 둘은 SSE 승격 시에만 쓴다. 지금은 호출되지 않는다. ---
    def subscribe(self, project_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subscribers.setdefault(project_id, []).append(queue)
        return queue

    def unsubscribe(self, project_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            subscribers = self._subscribers.get(project_id)
            if subscribers and queue in subscribers:
                subscribers.remove(queue)


EVENT_BUS = ProjectEventBus()


class ProjectLogHandler(logging.Handler):
    """logging 레코드를 EVENT_BUS로 옮기는 핸들러.

    current_project_id가 None이면(= CLI 실행이거나 API의 요청 처리 스레드) 아무것도
    하지 않는다. 즉 이 핸들러를 루트 로거에 붙여둬도 CLI 동작에는 영향이 없다."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            project_id = current_project_id.get()
            if project_id is None:
                return
            event = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "kind": getattr(record, "kind", "text"),
                "level": record.levelname,
                "message": record.getMessage(),
            }
            for field in _STRUCTURED_FIELDS:
                value = getattr(record, field, None)
                if value is not None:
                    event[field] = value
            EVENT_BUS.publish(project_id, event)
        except Exception:  # 로깅이 앱을 죽이면 안 된다
            self.handleError(record)


def install_log_handler() -> None:
    """FastAPI lifespan에서 한 번 호출. agents/orchestrator 로거에만 붙인다
    (루트에 붙이면 uvicorn 내부 로그까지 이벤트로 섞여 들어온다)."""
    handler = ProjectLogHandler()
    handler.setLevel(logging.INFO)
    for logger_name in ("agents", "orchestrator", "fact_store", "rag"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        # 서버 콘솔에도 그대로 보이도록 propagate는 켜둔다(기본값 True).
