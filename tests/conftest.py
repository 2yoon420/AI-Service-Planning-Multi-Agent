"""공통 픽스처.

이 프로젝트의 저장소 3종은 전부 모듈 전역 DB_PATH를 본다. 테스트가 실제
sessions.db / fact_store.db를 건드리면 개발 데이터가 오염되므로, 매 테스트마다
tmp_path로 갈아끼운다."""

import pytest


@pytest.fixture
def registry_db(tmp_path, monkeypatch):
    """api.registry를 임시 SQLite로 격리한다."""
    from api import registry

    monkeypatch.setattr(registry, "DB_PATH", tmp_path / "sessions.db")
    registry.init_db()
    return registry


@pytest.fixture
def fact_db(tmp_path, monkeypatch):
    """fact_store.store를 임시 SQLite로 격리한다."""
    from fact_store import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "fact_store.db")
    store.init_db()
    return store


@pytest.fixture
def event_bus():
    """EVENT_BUS는 프로세스 전역 싱글턴이라 테스트 간 상태가 샌다. 앞뒤로 비운다."""
    from api.logbus import EVENT_BUS

    EVENT_BUS._buffers.clear()
    EVENT_BUS._seq.clear()
    EVENT_BUS._subscribers.clear()
    yield EVENT_BUS
    EVENT_BUS._buffers.clear()
    EVENT_BUS._seq.clear()
    EVENT_BUS._subscribers.clear()


@pytest.fixture(autouse=True)
def _clean_runner_state():
    """runner의 _locks/_tasks도 전역이다. 테스트 간 격리를 위해 비운다.
    (_locks가 정리되지 않는 것은 알려진 한계 — api/runner.py 상단 주석 참고)"""
    from api import runner

    runner._locks.clear()
    runner._tasks.clear()
    yield
    runner._locks.clear()
    runner._tasks.clear()
