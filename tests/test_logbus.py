"""(3) 로그 파이프라인 테스트 — 외부검토 2차 2-①.

print → log.info 치환이 약 120곳 있었고, 설계도 스스로 "검증을 건너뛰면 조용히
출력이 사라지는 사고가 난다"고 경고한 지점이다. 그런데 이를 확인할 자동 수단이
없었다. 이 파일이 그 안전망이다."""

import logging

from api.logbus import EVENT_BUS, ProjectLogHandler, current_project_id


def _emit(logger_name="agents.market_research", msg="테스트", **extra):
    log = logging.getLogger(logger_name)
    log.setLevel(logging.INFO)
    handler = ProjectLogHandler()
    handler.setLevel(logging.INFO)
    log.addHandler(handler)
    try:
        log.info(msg, extra=extra or None)
    finally:
        log.removeHandler(handler)


def test_로그_한_줄이_이벤트로_도착한다(event_bus):
    token = current_project_id.set("p1")
    try:
        _emit(msg="[검색] 북미 웨어러블 시장 규모")
    finally:
        current_project_id.reset(token)

    events = event_bus.events_since("p1")
    assert len(events) == 1
    assert events[0]["message"] == "[검색] 북미 웨어러블 시장 규모"
    assert events[0]["kind"] == "text"       # extra가 없으면 기본값
    assert events[0]["seq"] == 1


def test_구조화_필드가_그대로_실린다(event_bus):
    """프론트 출처 카드가 url·tier·title에 의존한다(프론트엔드_설계도 4-3절).
    이 세 필드가 빠지면 출처 카드가 통째로 안 그려진다."""
    token = current_project_id.set("p1")
    try:
        _emit(
            msg="[fact 저장] 시장 규모 84억 달러",
            kind="fact",
            url="https://census.gov/x",
            tier="2차",
            title="US Census",
        )
    finally:
        current_project_id.reset(token)

    e = event_bus.events_since("p1")[0]
    assert e["kind"] == "fact"
    assert e["url"] == "https://census.gov/x"
    assert e["tier"] == "2차"
    assert e["title"] == "US Census"


def test_허용목록_밖의_extra는_버려진다(event_bus):
    """_STRUCTURED_FIELDS에 없는 필드가 이벤트로 새어나가면 API 스키마가 흔들린다."""
    token = current_project_id.set("p1")
    try:
        _emit(msg="x", kind="fact", secret_field="새면_안_됨")
    finally:
        current_project_id.reset(token)

    assert "secret_field" not in event_bus.events_since("p1")[0]


def test_project_id가_없으면_아무_일도_없다(event_bus):
    """CLI 실행 경로. 이 핸들러를 붙여둬도 CLI 동작이 바뀌지 않아야 한다
    (설계도 7절의 핵심 전제).

    주의 — 특정 project_id의 버퍼가 비었는지 보면 안 된다. 핸들러가 'unknown' 같은
    다른 키로 발행하도록 잘못 고쳐져도 그 검사는 통과해버린다(2026-07-28 변조
    실험에서 실제로 뚫림). 어느 프로젝트에도 발행되지 않았음을 봐야 한다."""
    assert current_project_id.get() is None
    _emit(msg="CLI에서 찍은 로그")

    assert event_bus._buffers == {}, f"CLI 로그가 새어나갔다: {list(event_bus._buffers)}"
    assert event_bus._seq == {}


def test_프로젝트별로_분리된다(event_bus):
    for pid in ("p1", "p2"):
        token = current_project_id.set(pid)
        try:
            _emit(msg=f"{pid}의 로그")
        finally:
            current_project_id.reset(token)

    assert len(event_bus.events_since("p1")) == 1
    assert event_bus.events_since("p1")[0]["message"] == "p1의 로그"
    assert event_bus.events_since("p2")[0]["message"] == "p2의 로그"


def test_seq는_1부터_증가하고_since로_잘린다(event_bus):
    """프론트 폴링이 since=latest_seq로 증분만 받아온다. 여기가 틀리면
    이벤트가 중복 표시되거나 유실된다."""
    token = current_project_id.set("p1")
    try:
        for i in range(5):
            _emit(msg=f"{i}번째")
    finally:
        current_project_id.reset(token)

    assert [e["seq"] for e in event_bus.events_since("p1")] == [1, 2, 3, 4, 5]
    assert [e["seq"] for e in event_bus.events_since("p1", since=3)] == [4, 5]
    assert event_bus.latest_seq("p1") == 5


def test_링버퍼_상한을_넘으면_오래된_것부터_버린다(event_bus, monkeypatch):
    """MAX_EVENTS_PER_PROJECT=2000은 근거 없는 임의값이다(설계값_레지스터.md 1절).
    값이 아니라 '상한을 넘으면 오래된 것이 밀려난다'는 동작만 검증한다."""
    import api.logbus as logbus

    monkeypatch.setattr(logbus, "MAX_EVENTS_PER_PROJECT", 3)
    token = current_project_id.set("p1")
    try:
        for i in range(5):
            _emit(msg=f"{i}")
    finally:
        current_project_id.reset(token)

    events = event_bus.events_since("p1")
    assert len(events) == 3
    assert [e["message"] for e in events] == ["2", "3", "4"]
    assert event_bus.latest_seq("p1") == 5     # seq는 버려져도 계속 증가한다


def test_로깅_예외가_앱을_죽이지_않는다(event_bus, monkeypatch):
    """핸들러 안에서 무슨 일이 나든 파이프라인은 계속 돌아야 한다."""
    import api.logbus as logbus

    def _boom(*a, **k):
        raise RuntimeError("버스 고장")

    monkeypatch.setattr(logbus.EVENT_BUS, "publish", _boom)

    token = current_project_id.set("p1")
    try:
        _emit(msg="이게 예외를 던지면 안 된다")   # 여기서 raise되면 테스트 실패
    finally:
        current_project_id.reset(token)
