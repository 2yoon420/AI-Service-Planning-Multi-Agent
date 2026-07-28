"""(2) API 계약 테스트 — 외부검토 2차 2-①.

응답 코드 계약(404 / 409 / 202)만 본다. 그래프와 runner는 mock으로 끊는다 —
여기서 검증할 것은 "라우트가 옳은 코드를 돌려주는가"이지 실행이 아니다.
실행은 test_registry_runner.py가 본다."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import registry, runner
from api.routes import router

FAKE_SNAPSHOT = {
    "next_nodes": ["market_research"],
    "draft_markdown": None,
    "draft_docx_path": None,
    "revision_count": 0,
    "qa_count": 0,
    "prompt": None,
    "interrupted": False,
}


@pytest.fixture
def client(registry_db, event_bus, monkeypatch):
    """lifespan을 태우지 않는다. 실제 lifespan은 체크포인터를 열고 그래프를
    컴파일하는데, 계약 테스트에는 불필요하고 CI를 느리고 불안정하게 만든다."""
    import api.routes as routes

    monkeypatch.setattr(routes, "get_session_state", lambda pid, graph: dict(FAKE_SNAPSHOT))
    monkeypatch.setattr(routes, "start_project", lambda *a, **k: {"paused": False})
    monkeypatch.setattr(routes, "submit_message", lambda *a, **k: {"paused": False})

    async def _noop_launch(project_id, fn):
        return None

    monkeypatch.setattr(runner, "launch", _noop_launch)
    monkeypatch.setattr(runner, "is_busy", lambda pid: False)

    app = FastAPI()
    app.include_router(router)
    app.state.graph = object()
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_없는_프로젝트는_404(client):
    assert client.get("/projects/없는아이디").status_code == 404


def test_없는_프로젝트에_메시지를_보내면_404(client):
    r = client.post("/projects/없는아이디/messages", json={"message": "안녕"})
    assert r.status_code == 404


def test_프로젝트_생성은_202와_project_id(client):
    r = client.post(
        "/projects",
        json={"topic": "웨어러블 헬스케어 기기", "target_market": "북미 시니어 시장"},
    )
    assert r.status_code == 202
    body = r.json()
    assert body["project_id"]
    assert body["status"] == registry.STATUS_RUNNING


def test_running_중_메시지는_409(client, registry_db):
    registry_db.create_project("p1", "t", "m")   # 생성 직후 기본 상태가 running
    r = client.post("/projects/p1/messages", json={"message": "다시 해줘"})
    assert r.status_code == 409


def test_completed_프로젝트에_메시지는_409(client, registry_db):
    registry_db.create_project("p1", "t", "m")
    registry_db.update_project("p1", status=registry.STATUS_COMPLETED)
    r = client.post("/projects/p1/messages", json={"message": "더 고쳐줘"})
    assert r.status_code == 409
    assert "종료된" in r.json()["detail"]


def test_awaiting_review에서는_메시지가_202(client, registry_db):
    """승인 UI가 실제로 동작하려면 이 경로가 열려 있어야 한다."""
    registry_db.create_project("p1", "t", "m")
    registry_db.update_project("p1", status=registry.STATUS_AWAITING)
    r = client.post("/projects/p1/messages", json={"message": "승인"})
    assert r.status_code == 202


def test_failed_프로젝트에도_메시지가_열려있다(client, registry_db):
    """BUSY/CLOSED 어느 집합에도 failed가 없으므로 API는 막지 않는다.
    막는 것은 프론트(MessageInput.canType)뿐이다 — 계약을 여기 명시해 둔다."""
    registry_db.create_project("p1", "t", "m")
    registry_db.update_project("p1", status=registry.STATUS_FAILED, error="x")
    r = client.post("/projects/p1/messages", json={"message": "재시도"})
    assert r.status_code == 202


def test_실행_중_삭제는_409(client, registry_db, monkeypatch):
    registry_db.create_project("p1", "t", "m")
    monkeypatch.setattr(runner, "is_busy", lambda pid: True)
    assert client.delete("/projects/p1").status_code == 409


def test_삭제는_204_이후_404(client, registry_db):
    registry_db.create_project("p1", "t", "m")
    assert client.delete("/projects/p1").status_code == 204
    assert client.get("/projects/p1").status_code == 404


def test_상세조회에_next_nodes가_실린다(client, registry_db):
    """프론트가 한글 라벨을 파싱하지 않도록 넣은 기계용 필드
    (프론트엔드_설계도 8-2절). 빠지면 진행 단계 표시가 통째로 죽는다."""
    registry_db.create_project("p1", "웨어러블", "북미")
    body = client.get("/projects/p1").json()
    assert body["next_nodes"] == ["market_research"]
    assert body["current_step"]          # running이므로 사람이 읽는 라벨도 채워진다


def test_완료_상태면_current_step은_비어야_한다(client, registry_db):
    registry_db.create_project("p1", "웨어러블", "북미")
    registry_db.update_project("p1", status=registry.STATUS_COMPLETED)
    assert client.get("/projects/p1").json()["current_step"] is None


def test_초안이_없으면_다운로드는_404(client, registry_db):
    registry_db.create_project("p1", "t", "m")
    assert client.get("/projects/p1/document").status_code == 404
