"""인코딩 모지바케 3층 방어 회귀 테스트 (결함 F, 2026-07-28).

## 사고 경위

배포 서버의 유럽 실행에서 fact 5건이 깨진 채로 저장됐다.

    저장된 원문: "í í¸ë¼Pak ì¸í°ë´ì ë, ìì½ë¥´, ... 51% ì ìì¥ ì ì ì¨"
    실제 내용  : "테트라Pak 인터내셔널, 아스코르, ... 51%의 시장 점유율"

원인은 `agents/web_search.py`의 `resp.text` 한 줄이었다. requests는 Content-Type에
charset이 없으면 RFC 2616에 따라 ISO-8859-1로 가정하는데, 출처 페이지
(gminsights.com/ko)가 charset을 헤더에 주지 않고 HTML <meta>에만 넣었다.

## 피해가 세 겹이었다

  ① 수집: 본문이 깨졌다
  ② 추출: LLM이 깨진 글자를 회사명으로 해석해 실재하지 않는 기업을 만들었다 —
          `Ìndusanal Inc.`(14.1%), `Monoco Group`(51%)이 시장 점유율 순위표에 실렸다
  ③ 검증: **관련성 5점 · 근거지지도 5점으로 채택되고 citation_verified=True 도장을 받았다.**
          근거지지도는 "fact가 원문에 있는가"만 묻는데, 원문과 fact가 함께 깨져 있으면
          논리적으로 '일치'가 성립한다. 판정 로직이 틀린 게 아니라, 판정할 수 없는
          입력이 판정 단계까지 들어온 것이다

부수 피해: 문자열 유사도가 0에 가까워져 중복 제거(임계 0.85)가 무력화됐다.
같은 사실이 '깨진 판'과 '정상 판'으로 두 번 저장됐다.

## 그래서 세 층 모두 막는다

수집만 고치면 이 사이트는 해결되지만, charset을 틀리게 주는 사이트는 또 나온다.
"정규식으로 확실히 판정할 수 있는 것은 LLM에 묻지 않는다"는 결함 C의 교훈을 적용해,
검증 앞단에서 즉시 기각한다.
"""

import pytest
from requests.structures import CaseInsensitiveDict

from agents.market_research import _is_no_info_statement, _is_unusable_fact
from agents.verification import prescreen_fact
from agents.web_search import decode_html, looks_mojibake

# 실제 사고에서 저장됐던 문장 그대로
BROKEN = ("í í¸ë¼Pak ì¸í°ë´ì ë, ìì½ë¥´, ì¸í°ë´ì ë íì´í¼, "
          "ëª¬ë ê·¸ë£¹, ì¤ë¤ ìì´ ì½í¼ë ì´ì  ì´ë©°, ì´ë¤ì´ 2024ë  51%")
CLEAN = ("주요 기업인 테트라팍(Tetra Pak), 인터내셔널 페이퍼, 몬디 그룹이 "
         "2024년 유럽 친환경 포장재 시장에서 51%의 점유율을 차지하고 있음.")
KO_LONG = "테트라Pak 인터내셔널, 아스코르, 몬디 그룹이 2024년 51%의 시장 점유율을 차지했습니다. " * 3


class _Resp:
    """가짜 응답. headers를 반드시 CaseInsensitiveDict로 만든다.

    처음에는 평범한 dict를 썼는데, requests.utils.get_encoding_from_headers()가
    내부에서 headers.get("content-type")(소문자)로 조회하기 때문에 dict로는 항상
    None이 나왔다. 그래서 헤더 charset 경로가 한 번도 실행되지 않은 채
    "테스트가 통과"하고 있었다 — 엉뚱한 경로를 통과한 것이다.
    """

    def __init__(self, content: bytes, headers: dict):
        self.content = content
        self.headers = CaseInsensitiveDict(headers)


def _page(body: str, *, head: str = "", encoding: str = "utf-8") -> bytes:
    return f"<html><head>{head}</head><body>{body}</body></html>".encode(encoding)


# ───────────────────────────────── 판정기 자체
def test_실제_사고_문장을_모지바케로_판정한다():
    assert looks_mojibake(BROKEN)


def test_정상_한국어는_모지바케로_오판하지_않는다():
    assert not looks_mojibake(CLEAN)


@pytest.mark.parametrize("text", [
    "Tetra Pak held 51% of the market share in 2024.",
    "TAM은 2조 5000억 원으로 추산된다(2021년 기준).",
    "온실가스 배출량이 전년 대비 12.4% 감소했다 — 환경부 발표.",
    "가격: €1,200 / £980 / ¥150,000",       # 통화 기호가 있어도 정상
    "품질(品質)과 안전(安全)을 우선한다",        # 한자 혼용도 정상
    "",
    None,
])
def test_정상_텍스트를_오판하지_않는다(text):
    assert not looks_mojibake(text)


def test_긴_정상문서에_깨짐_신호가_한두_번_섞여도_오판하지_않는다():
    """임계값을 두는 이유를 실제로 시험한다.

    처음 쓴 이 테스트는 "A"*500 + "Ã" 였는데, 'Ã' 뒤에 문자가 없어 패턴 자체가
    적중하지 않았다. 그래서 임계값을 0으로 바꾸는 변조를 넣어도 통과했다 —
    임계값을 시험한다고 믿었지만 아무것도 시험하지 않던 테스트다.
    """
    text = "정상적인 한국어 문서입니다. " * 40 + "Ã©"   # 적중 1회 / 640자 ≈ 0.0016
    assert looks_mojibake(text, threshold=0.0), "패턴이 실제로 적중해야 시험이 성립한다"
    assert not looks_mojibake(text), "임계값(0.005) 아래이므로 깨짐이 아니다"


def test_깨짐_신호가_임계값을_넘으면_판정한다():
    text = "정상 문서 " * 10 + "Ã©" * 5      # 적중 5회 / 약 60자 ≈ 0.08
    assert looks_mojibake(text)


# ───────────────────────────────── ① 수집 계층
def test_charset_헤더가_없는_UTF8_한국어_페이지를_제대로_읽는다():
    """이것이 실제 사고 조건이다. requests의 .text는 여기서 ISO-8859-1을 쓴다."""
    raw = _page(KO_LONG)
    assert looks_mojibake(raw.decode("latin-1")), "사고 조건 재현 확인"
    out = decode_html(_Resp(raw, {"Content-Type": "text/html"}))
    assert "테트라Pak 인터내셔널" in out
    assert not looks_mojibake(out)


def test_meta에만_charset이_선언된_경우를_읽는다():
    raw = _page(KO_LONG, head='<meta charset="utf-8">')
    out = decode_html(_Resp(raw, {"Content-Type": "text/html"}))
    assert "테트라Pak" in out


def test_meta가_틀린_charset을_주장해도_결과로_판단한다():
    """선언을 맹신하지 않는다. 디코딩 결과가 깨졌으면 다음 후보로 넘어간다."""
    raw = _page(KO_LONG, head='<meta charset="iso-8859-1">')
    out = decode_html(_Resp(raw, {"Content-Type": "text/html"}))
    assert "테트라Pak" in out


def test_cp949_레거시_페이지를_읽는다():
    raw = _page(KO_LONG, encoding="cp949")
    out = decode_html(_Resp(raw, {"Content-Type": "text/html"}))
    assert "테트라Pak" in out


def test_헤더가_ISO_8859_1을_명시해도_내용으로_판단한다():
    """일부 서버는 charset을 아예 안 주는 대신 ISO-8859-1을 명시한다. 그 값은
    'RFC 기본값을 그대로 적은 것'일 뿐이므로 신뢰하면 한글이 전부 깨진다.

    이 테스트가 없던 동안, 헤더 charset을 무조건 신뢰하도록 바꾸는 변조가 통과했다."""
    raw = _page(KO_LONG)
    out = decode_html(_Resp(raw, {"Content-Type": "text/html; charset=ISO-8859-1"}))
    assert "테트라Pak" in out
    assert not looks_mojibake(out)


def test_헤더의_utf8_선언을_신뢰한다():
    raw = _page(KO_LONG)
    out = decode_html(_Resp(raw, {"Content-Type": "text/html; charset=utf-8"}))
    assert "테트라Pak" in out


def test_영어_페이지를_망가뜨리지_않는다():
    raw = _page("Tetra Pak held 51% market share in 2024.")
    out = decode_html(_Resp(raw, {"Content-Type": "text/html"}))
    assert "Tetra Pak held 51%" in out


def test_빈_응답에서_죽지_않는다():
    assert decode_html(_Resp(b"", {"Content-Type": "text/html"})) == ""


def test_어떤_바이트가_와도_예외를_던지지_않는다():
    """수집 실패가 파이프라인을 멈추는 원인이 되면 안 된다."""
    out = decode_html(_Resp(bytes(range(256)) * 4, {"Content-Type": "text/html"}))
    assert isinstance(out, str)


# ───────────────────────────────── ② 추출 계층
def test_깨진_fact는_추출_단계에서_버려진다():
    assert _is_unusable_fact(BROKEN)


def test_정상_fact는_추출_단계를_통과한다():
    assert not _is_unusable_fact(CLEAN)


def test_기존_정보없음_필터가_함께_유지된다():
    """모지바케 필터를 추가하면서 원래 기능을 잃지 않았는지 확인한다."""
    meta = "제공된 본문에는 해당 정보가 포함되어 있지 않습니다."
    assert _is_no_info_statement(meta)
    assert _is_unusable_fact(meta)


# ───────────────────────────────── ③ 검증 계층
def test_깨진_fact는_LLM에_묻지_않고_기각된다():
    reason = prescreen_fact(BROKEN, CLEAN)
    assert reason is not None
    assert "모지바케" in reason


def test_원문이_깨졌으면_fact가_정상이어도_기각된다():
    """실제 사고의 핵심 — 원문과 fact가 함께 깨져 '일치'가 성립했다.
    fact만 읽을 수 있어도 근거 대조가 불가능하므로 채택할 수 없다."""
    reason = prescreen_fact(CLEAN, BROKEN * 3)
    assert reason is not None
    assert "근거 대조" in reason


def test_둘_다_정상이면_LLM_채점으로_넘긴다():
    assert prescreen_fact(CLEAN, CLEAN) is None


def test_원문이_없어도_fact가_정상이면_통과시킨다():
    """원문 없이 채점하는 경로(스니펫 폴백)를 막아선 안 된다."""
    assert prescreen_fact(CLEAN, "") is None


# ───────────────────────────────── 배선 (가장 중요)
def test_수집_경로가_실제로_decode_html을_거친다(monkeypatch):
    """가장 큰 구멍이었다.

    처음 쓴 테스트들은 decode_html()을 직접 호출하기만 했다. 그래서
    `html = decode_html(resp)` 를 `html = resp.text` 로 되돌리는 변조(= 결함 F
    원상복구)를 넣어도 25개가 전부 통과했다. 함수를 고쳤는지만 보고 그 함수가
    실제로 쓰이는지는 아무도 확인하지 않은 것이다.

    여기서는 진짜 requests.Response를 만들어 넣는다. `.text`를 쓰면 ISO-8859-1로
    읽혀 깨지고, decode_html을 거치면 정상이므로 결과만 보면 배선을 알 수 있다.
    """
    import requests
    from agents import web_search as W

    raw = _page(KO_LONG)          # charset 헤더 없는 UTF-8 한국어 페이지
    resp = requests.Response()
    resp.status_code = 200
    resp._content = raw
    resp.headers["Content-Type"] = "text/html"
    # requests가 실제 전송 경로(Session.send)에서 하는 일을 그대로 재현한다.
    # text/html에 charset이 없으면 RFC 2616에 따라 ISO-8859-1이 들어간다 —
    # 이것이 결함 F의 근본 원인이다.
    resp.encoding = requests.utils.get_encoding_from_headers(resp.headers)
    assert resp.encoding == "ISO-8859-1", "사고 조건: 헤더에서 ISO-8859-1이 유도된다"

    # 사고 조건 확인 — .text 는 깨진다
    assert looks_mojibake(resp.text), "이 조건에서 resp.text는 깨져야 시험이 성립한다"

    monkeypatch.setattr(W.requests, "get", lambda *a, **k: resp)
    out = W._fetch_page_text_direct("https://example.com/ko/page", 4000)

    assert out is not None
    assert "테트라Pak 인터내셔널" in out
    assert not looks_mojibake(out)


def test_수집_경로가_HTML_태그를_제거한다(monkeypatch):
    """배선 테스트가 디코딩만 보고 후처리를 놓치지 않게 한다."""
    import requests
    from agents import web_search as W

    resp = requests.Response()
    resp.status_code = 200
    resp._content = _page("<script>var x=1;</script><p>테트라Pak 점유율 51%</p>")
    resp.headers["Content-Type"] = "text/html"
    resp.encoding = requests.utils.get_encoding_from_headers(resp.headers)

    monkeypatch.setattr(W.requests, "get", lambda *a, **k: resp)
    out = W._fetch_page_text_direct("https://example.com", 4000)
    assert "테트라Pak 점유율 51%" in out
    assert "var x" not in out and "<p>" not in out


def test_어느_한_단계가_틀려도_결과_검사가_흡수한다():
    """다층 방어의 성질을 박제한다.

    변조실험에서 "헤더의 ISO-8859-1을 무조건 신뢰하도록" 코드를 바꿨을 때 테스트가
    전부 통과했다. 처음에는 테스트 구멍인가 했는데, 따져보니 구멍이 아니었다 —
    ISO-8859-1로 디코딩하면 결과가 깨지고, 그 결과를 검사해 다음 후보(utf-8)로
    넘어가므로 최종 결과는 정상이다. **한 단계의 오판이 결함으로 이어지지 않는다.**

    이 성질이 이 설계의 요점이다. charset 선언은 어디서든 틀릴 수 있으므로
    (헤더·meta·서버 설정), 선언을 믿는 대신 결과를 본다.
    """
    raw = _page(KO_LONG)
    # 헤더·meta 둘 다 틀린 charset을 주장하는 최악의 경우
    worst = _page(KO_LONG, head='<meta charset="iso-8859-1">')
    for label, data, hdr in (
        ("헤더가 틀림", raw, {"Content-Type": "text/html; charset=ISO-8859-1"}),
        ("meta가 틀림", worst, {"Content-Type": "text/html"}),
        ("둘 다 틀림", worst, {"Content-Type": "text/html; charset=ISO-8859-1"}),
    ):
        out = decode_html(_Resp(data, hdr))
        assert "테트라Pak" in out, f"{label}: 복구 실패"
        assert not looks_mojibake(out), f"{label}: 깨진 결과가 통과했다"
