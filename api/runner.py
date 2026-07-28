"""백그라운드 실행 · 동시성 제어 · 상태 전이 (설계도 5절).

여기가 "동기 그래프 코드"와 "비동기 FastAPI" 사이의 유일한 경계다.
asyncio.to_thread()로 동기 함수를 별도 스레드에서 돌리므로, agents/*.py와
orchestrator/graph.py는 async를 전혀 몰라도 된다(설계도 6-3절)."""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from api import registry
from api.logbus import current_project_id

# 그래프 실행 상한. 근거 없는 임의값이다(REVISION_CAP=5와 같은 종류의 안전장치).
GRAPH_TIMEOUT_SECONDS = 1800  # 30분

# --- 알고 있는 한계: _locks는 정리되지 않는다 (2026-07-28, 외부검토 2-③) ---
#
# _tasks는 누수가 아니다. launch()에서 add_done_callback으로 작업 종료 시 스스로
# 빠진다(아래 참고). 외부 검토 보고서가 "_locks / _tasks 딕셔너리 무한 증가"라고
# 지적했으나, 코드를 확인한 결과 _tasks는 해당하지 않는다.
#
# 반면 _locks는 lock_for()가 프로젝트마다 Lock을 만들고 어디서도 삭제하지 않으므로
# 프로세스 수명 동안 계속 쌓인다. 삭제하지 않는 이유는, 삭제 시점을 안전하게 잡기가
# 까다롭기 때문이다 — 락을 지우는 순간 그 락을 기다리던 코루틴이 있으면 새로 만들어진
# 다른 락을 잡게 되어 상호배제가 깨진다.
#
# 단일 사용자 MVP에서는 무해하다. Lock 객체 하나가 수십 바이트이고 프로젝트 수가
# 수백 단위를 넘지 않으며, 서버 재시작 때마다 초기화된다. 다중 사용자로 가거나
# 프로세스를 장기 상주시킬 때는 "완료 후 일정 시간이 지난 프로젝트의 락을 회수"하는
# 정리 주기가 필요하다.
_locks: dict[str, asyncio.Lock] = {}
_tasks: dict[str, asyncio.Task] = {}


def lock_for(project_id: str) -> asyncio.Lock:
    lock = _locks.get(project_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[project_id] = lock
    return lock


def _run_with_context(project_id: str, fn: Callable[[], dict]) -> dict:
    """백그라운드 스레드 안에서 실행되는 래퍼.

    여기서 ContextVar를 세팅하는 것이 핵심이다 — asyncio.to_thread()가 컨텍스트를
    복사해 넘겨주므로, 이 스레드에서 발생하는 모든 로그 레코드가 이 project_id로
    귀속된다(logbus.ProjectLogHandler 참고)."""
    current_project_id.set(project_id)
    return fn()


async def _execute(project_id: str, fn: Callable[[], dict]) -> None:
    """그래프 호출 하나를 백그라운드에서 수행하고, 결과에 따라 레지스트리 상태를 옮긴다."""
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_run_with_context, project_id, fn),
            timeout=GRAPH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        registry.update_project(
            project_id,
            status=registry.STATUS_FAILED,
            error=f"실행 시간이 상한({GRAPH_TIMEOUT_SECONDS}초)을 초과했습니다.",
        )
        return
    except Exception as exc:  # noqa: BLE001 — 어떤 예외든 상태로 남겨야 한다
        registry.update_project(
            project_id,
            status=registry.STATUS_FAILED,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    docx_path = response.get("draft_docx_path")
    if response.get("paused"):
        registry.update_project(
            project_id,
            status=registry.STATUS_AWAITING,
            docx_path=docx_path,
            clear_error=True,
        )
    else:
        registry.update_project(
            project_id,
            status=registry.STATUS_COMPLETED,
            docx_path=docx_path,
            clear_error=True,
        )


async def launch(project_id: str, fn: Callable[[], dict]) -> None:
    """레지스트리를 running으로 옮기고 백그라운드 작업을 띄운다.
    호출부(routes.py)가 이미 409 검사를 마쳤다는 전제이며, 락은 그 검사와 이
    호출 사이의 경합을 막는 두 번째 안전장치다(설계도 5-3절)."""
    async with lock_for(project_id):
        registry.update_project(
            project_id, status=registry.STATUS_RUNNING, clear_error=True
        )
        task = asyncio.create_task(_execute(project_id, fn))
        _tasks[project_id] = task
        # 종료 시 스스로 빠진다 — _tasks가 누수되지 않는 근거(위 _locks 주석 참고).
        task.add_done_callback(lambda t: _tasks.pop(project_id, None))


def is_busy(project_id: str) -> bool:
    task = _tasks.get(project_id)
    return task is not None and not task.done()
