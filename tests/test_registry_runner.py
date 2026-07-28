"""(1) 상태 전이 테스트 — 외부검토 2차 2-①.

running → awaiting_review / completed / failed 로 옳게 옮겨가는지 본다.
LLM도 그래프도 필요 없다. runner.launch()에 가짜 fn을 넣으면 되기 때문이다.

이 계층을 먼저 덮는 이유: 상태 머신 오류는 로그를 눈으로 봐서는 안 잡힌다.
2026-07-27에 '성공한 실행이 failed로 기록되는' 사고가 실제로 있었다."""

import asyncio

import pytest

from api import registry, runner


def _drive(project_id: str, fn):
    """launch()가 만든 백그라운드 태스크가 끝날 때까지 몰아준다.

    pytest-asyncio를 쓰지 않는 이유는 의존성을 하나라도 줄이기 위함이다 —
    이 테스트들은 CI에서 매번 도는 것이라 설치가 가벼울수록 좋다."""

    async def _go():
        await runner.launch(project_id, fn)
        task = runner._tasks.get(project_id)
        if task is not None:
            await task

    asyncio.run(_go())


def _make(registry_db, pid="p1"):
    registry_db.create_project(pid, "웨어러블 헬스케어 기기", "북미 시니어 시장")
    return pid


def test_완료되면_completed로_간다(registry_db):
    pid = _make(registry_db)
    _drive(pid, lambda: {"paused": False, "draft_docx_path": "/tmp/a.docx"})

    row = registry_db.get_project(pid)
    assert row["status"] == registry.STATUS_COMPLETED
    assert row["docx_path"] == "/tmp/a.docx"
    assert row["error"] is None


def test_interrupt로_멈추면_awaiting_review로_간다(registry_db):
    pid = _make(registry_db)
    _drive(pid, lambda: {"paused": True, "draft_docx_path": None})

    assert registry_db.get_project(pid)["status"] == registry.STATUS_AWAITING


def test_예외가_나면_failed로_가고_사유가_남는다(registry_db):
    pid = _make(registry_db)

    def _boom():
        raise ValueError("검색 백엔드 응답 없음")

    _drive(pid, _boom)

    row = registry_db.get_project(pid)
    assert row["status"] == registry.STATUS_FAILED
    assert "ValueError" in row["error"]
    assert "검색 백엔드 응답 없음" in row["error"]


def test_타임아웃이면_failed로_간다(registry_db, monkeypatch):
    """GRAPH_TIMEOUT_SECONDS는 근거 없는 임의값이다(설계값_레지스터.md 1절).
    값 자체가 아니라 '초과 시 failed로 간다'는 계약만 검증한다."""
    pid = _make(registry_db)
    monkeypatch.setattr(runner, "GRAPH_TIMEOUT_SECONDS", 0.05)

    import time

    _drive(pid, lambda: time.sleep(0.5) or {"paused": False})

    row = registry_db.get_project(pid)
    assert row["status"] == registry.STATUS_FAILED
    assert "상한" in row["error"]


def test_재실행하면_이전_error가_지워진다(registry_db):
    """clear_error 경로. 실패 후 재시도했는데 옛 에러 문구가 화면에 남으면
    사용자가 또 실패한 줄로 오해한다."""
    pid = _make(registry_db)
    registry_db.update_project(pid, status=registry.STATUS_FAILED, error="이전 실패")

    _drive(pid, lambda: {"paused": False})

    row = registry_db.get_project(pid)
    assert row["status"] == registry.STATUS_COMPLETED
    assert row["error"] is None


def test_실행_중에는_is_busy가_참이고_끝나면_거짓이다(registry_db):
    pid = _make(registry_db)
    observed = {}

    async def _go():
        await runner.launch(pid, lambda: {"paused": False})
        observed["during"] = runner.is_busy(pid)
        await runner._tasks[pid]

    asyncio.run(_go())

    assert observed["during"] is True
    assert runner.is_busy(pid) is False


def test_작업이_끝나면_tasks에서_빠진다(registry_db):
    """_tasks 누수 없음의 회귀 방어. 외부검토 2차 2-③이 '_locks/_tasks 무한 증가'로
    지적했으나 _tasks는 add_done_callback으로 정리된다 — 그 사실을 여기 박제한다."""
    pid = _make(registry_db)
    _drive(pid, lambda: {"paused": False})

    assert pid not in runner._tasks


def test_스레드_안에서_project_id가_귀속된다(registry_db):
    """ContextVar가 asyncio.to_thread를 건너 전달되는지. 이게 깨지면 진행 이벤트가
    어느 프로젝트 것인지 알 수 없게 되어 화면이 통째로 빈다."""
    from api.logbus import current_project_id

    pid = _make(registry_db)
    seen = {}

    def _job():
        seen["pid"] = current_project_id.get()
        return {"paused": False}

    _drive(pid, _job)

    assert seen["pid"] == pid


def test_running_project_ids는_running만_반환한다(registry_db):
    """좀비 세션 복구(main.py _recover_zombie_sessions)가 이 함수에 의존한다."""
    registry_db.create_project("a", "t", "m")
    registry_db.create_project("b", "t", "m")
    registry_db.update_project("b", status=registry.STATUS_COMPLETED)

    assert registry_db.running_project_ids() == ["a"]
