"""Tavily 연동 테스트 (2026-07-28).

실제 API는 호출하지 않는다 — requests를 monkeypatch한다. 이 샌드박스는 외부
네트워크가 막혀 있어 실호출 검증이 불가능하고, CI에서도 외부 API에 의존하는
테스트는 불안정하기 때문이다. 따라서 여기서 보장하는 것은 **분기 로직과 계약**
이지 Tavily 응답 형식의 정확성이 아니다(그건 수요일 실행에서 확인).
"""

import pytest

from agents import web_search as ws


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = {"Content-Type": "text/html"}
        self.text = ""

    def json(self):
        return self._payload


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")


# ── 키 부재 시 폴백 (배포 환경에서 env 주입이 빠져도 죽지 않아야 한다) ──────

def test_키가_없으면_extract는_호출조차_안_한다(no_key, monkeypatch):
    called = []
    monkeypatch.setattr(ws.requests, "post", lambda *a, **k: called.append(1))

    assert ws._extract_tavily("https://x.com") is None
    assert called == []


def test_키가_없으면_search도_빈_리스트(no_key, monkeypatch):
    called = []
    monkeypatch.setattr(ws.requests, "post", lambda *a, **k: called.append(1))

    assert ws._search_tavily("질의", 3) == []
    assert called == []


def test_빈_문자열_키는_없는_것으로_취급한다(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "   ")
    assert ws._tavily_api_key() is None


# ── 추출 계층 분기 ─────────────────────────────────────────────────────────

def test_간이추출이_충분하면_Tavily를_안_부른다(with_key, monkeypatch):
    """비용이 실패 시에만 발생한다는 설계의 핵심. 여기가 깨지면 매 페이지마다
    크레딧이 나간다."""
    monkeypatch.setattr(ws, "_fetch_page_text_direct", lambda u, m: "가" * 1000)
    called = []
    monkeypatch.setattr(ws, "_extract_tavily", lambda *a, **k: called.append(1))

    out = ws.fetch_page_text("https://x.com")
    assert out == "가" * 1000
    assert called == [], "간이추출이 성공했는데 Tavily를 불렀다"


def test_간이추출이_실패하면_Tavily로_폴백한다(with_key, monkeypatch):
    monkeypatch.setattr(ws, "_fetch_page_text_direct", lambda u, m: None)
    monkeypatch.setattr(ws, "_extract_tavily", lambda u, m: "JS로 렌더링된 본문")

    assert ws.fetch_page_text("https://x.com") == "JS로 렌더링된 본문"


def test_간이추출이_너무_짧으면_Tavily로_폴백한다(with_key, monkeypatch):
    """18절 '가격 정보 전멸'의 실제 형태 — 페이지는 200을 주는데 본문은
    네비게이션 몇 글자뿐인 경우."""
    short = "메뉴 로그인 장바구니"
    assert len(short) < ws.PAGE_FETCH_MIN_USEFUL_CHARS
    monkeypatch.setattr(ws, "_fetch_page_text_direct", lambda u, m: short)
    monkeypatch.setattr(ws, "_extract_tavily", lambda u, m: "제품 가격은 299달러입니다")

    assert ws.fetch_page_text("https://x.com") == "제품 가격은 299달러입니다"


def test_Tavily까지_실패하면_짧은_본문이라도_쓴다(with_key, monkeypatch):
    """없는 것보다는 낫다. 무관한 내용은 후단 청크 필터가 걸러낸다."""
    monkeypatch.setattr(ws, "_fetch_page_text_direct", lambda u, m: "짧은 본문")
    monkeypatch.setattr(ws, "_extract_tavily", lambda u, m: None)

    assert ws.fetch_page_text("https://x.com") == "짧은 본문"


def test_둘_다_실패하면_None과_fetch_failed(with_key, monkeypatch, caplog):
    monkeypatch.setattr(ws, "_fetch_page_text_direct", lambda u, m: None)
    monkeypatch.setattr(ws, "_extract_tavily", lambda u, m: None)

    with caplog.at_level("INFO"):
        assert ws.fetch_page_text("https://x.com") is None
    assert any(getattr(r, "kind", None) == "fetch_failed" for r in caplog.records)


def test_성공_경로에서는_fetch_failed를_찍지_않는다(with_key, monkeypatch, caplog):
    """중간 실패를 fetch_failed로 찍으면 프론트 출처 카드가 흐려진 뒤 성공
    이벤트가 뒤따라 와 화면이 어긋난다. 그래서 최종 판정만 찍는다."""
    monkeypatch.setattr(ws, "_fetch_page_text_direct", lambda u, m: None)
    monkeypatch.setattr(ws, "_extract_tavily", lambda u, m: "본문")

    with caplog.at_level("INFO"):
        ws.fetch_page_text("https://x.com")
    kinds = [getattr(r, "kind", None) for r in caplog.records]
    assert "fetch_failed" not in kinds
    assert "fetch" in kinds


# ── Tavily 응답 파싱 ───────────────────────────────────────────────────────

def test_extract가_raw_content를_읽는다(with_key, monkeypatch):
    payload = {"results": [{"url": "https://x.com", "raw_content": "  본문   내용  "}],
               "failed_results": []}
    monkeypatch.setattr(ws.requests, "post", lambda *a, **k: _Resp(200, payload))

    assert ws._extract_tavily("https://x.com") == "본문 내용"


def test_extract가_failed_results만_받으면_None(with_key, monkeypatch):
    monkeypatch.setattr(
        ws.requests, "post",
        lambda *a, **k: _Resp(200, {"results": [], "failed_results": [{"url": "https://x.com"}]}),
    )
    assert ws._extract_tavily("https://x.com") is None


def test_extract는_max_chars로_자른다(with_key, monkeypatch):
    monkeypatch.setattr(
        ws.requests, "post",
        lambda *a, **k: _Resp(200, {"results": [{"raw_content": "가" * 9999}]}),
    )
    assert len(ws._extract_tavily("https://x.com", max_chars=100)) == 100


def test_search가_결과를_정규화하고_tier를_매긴다(with_key, monkeypatch):
    payload = {"results": [
        {"title": "US Census", "url": "https://www.census.gov/a", "content": "스니펫"},
    ]}
    monkeypatch.setattr(ws.requests, "post", lambda *a, **k: _Resp(200, payload))

    out = ws._search_tavily("질의", 3)
    assert len(out) == 1
    assert out[0]["url"] == "https://www.census.gov/a"
    assert out[0]["snippet"] == "스니펫"
    assert out[0]["content"] == "스니펫"
    assert out[0]["source_tier"]          # classify_source_tier가 값을 채웠다


def test_search는_url이_없는_결과를_버린다(with_key, monkeypatch):
    payload = {"results": [{"title": "제목만", "content": "x"}]}
    monkeypatch.setattr(ws.requests, "post", lambda *a, **k: _Resp(200, payload))
    assert ws._search_tavily("질의", 3) == []


# ── 실패 흡수 (이 파일 전체가 지키는 원칙) ─────────────────────────────────

@pytest.mark.parametrize("boom", [
    lambda *a, **k: _Resp(401),
    lambda *a, **k: _Resp(429),
    lambda *a, **k: (_ for _ in ()).throw(TimeoutError("타임아웃")),
])
def test_HTTP_오류나_예외는_흡수된다(with_key, monkeypatch, boom):
    """한쪽 백엔드가 죽어도 파이프라인 전체가 멈추면 안 된다."""
    monkeypatch.setattr(ws.requests, "post", boom)

    assert ws._search_tavily("질의", 3) == []
    assert ws._extract_tavily("https://x.com") is None


def test_search_web은_ddgs가_죽어도_Tavily로_결과를_낸다(with_key, monkeypatch):
    """지금까지는 폴백이 아예 없어 ddgs 실패 = 빈손이었다. 시연 중 레이트리밋이
    나면 파이프라인이 통째로 빈손이 되는 문제를 막는 것이 이 테스트의 목적이다."""
    class _DeadDDGS:
        def __enter__(self): raise RuntimeError("레이트리밋")
        def __exit__(self, *a): return False

    monkeypatch.setattr(ws, "DDGS", _DeadDDGS)
    monkeypatch.setattr(
        ws, "_search_tavily",
        lambda q, n: [{"title": "T", "url": "https://a.com", "snippet": "s",
                       "content": "s", "source_tier": "3차"}],
    )

    out = ws.search_web("질의", max_results=3)
    assert len(out) == 1 and out[0]["url"] == "https://a.com"


def test_search_web은_ddgs가_충분하면_Tavily를_안_부른다(with_key, monkeypatch):
    class _OkDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, q, max_results):
            return [{"title": f"t{i}", "href": f"https://x{i}.com", "body": "b"}
                    for i in range(max_results)]

    monkeypatch.setattr(ws, "DDGS", _OkDDGS)
    called = []
    monkeypatch.setattr(ws, "_search_tavily", lambda q, n: called.append(1) or [])

    out = ws.search_web("질의", max_results=3)
    assert len(out) == 3
    assert called == [], "ddgs가 충분한데 Tavily를 불렀다 — 불필요한 크레딧 소모"
