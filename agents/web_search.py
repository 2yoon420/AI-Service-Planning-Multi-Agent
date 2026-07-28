"""
시장조사 에이전트가 쓰는 웹검색 tool.

API 키가 필요 없는 ddgs(구 duckduckgo-search) 라이브러리를 사용한다.
검색 결과 자체는 tier(출처 신뢰도)를 판정해주지 않으므로, URL 도메인을 보고
파이프라인 문서 3-1절의 "1차/2차/3차 자료" 분류에 최대한 가깝게 휴리스틱으로
tier를 매긴다. 1차 자료(인터뷰·설문 등)는 웹검색으로 얻을 수 없는 성격이라
이 휴리스틱은 2차/3차만 자동 판정하고, 1차는 사람이 직접 넣는 경우에만 붙는다.
"""

import os
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from ddgs import DDGS

from fact_store.schema import SourceTier

import logging

log = logging.getLogger(__name__)

# ── 보조 백엔드: Tavily (2026-07-28) ──────────────────────────────────────
#
# 2026-07-23에 Brave Search API를 보조 백엔드로 넣었으나, .env에 BRAVE_API_KEY를
# 끝내 넣지 않아 `_search_brave()`는 첫 줄에서 빈 리스트를 반환하고 끝났다 —
# **한 번도 실행된 적이 없다.** 지금 DB의 fact 650건은 전부 ddgs 단독으로 모인 것이다.
# 즉 "다중 백엔드"라고 문서에 적혀 있었지만 실상은 폴백이 아예 없는 상태였고,
# ddgs가 레이트리밋이나 빈 결과를 주면 그대로 빈손이 됐다.
#
# Brave는 2026년 2월부로 신규 무료 티어도 없앴으므로 되살릴 이유가 없다. 대신
# Tavily를 넣는데, Brave가 못 하던 역할이 하나 더 있어서다.
#
#   검색 계층: ddgs (무료·기본)  →  부족하면 Tavily Search
#   추출 계층: 정규식 간이 추출  →  실패·과소하면 Tavily Extract   ← Brave에 없던 것
#
# 추출 계층이 핵심이다. 파이프라인 문서 18절의 "심층조사 가격 정보 전멸"은 검색이
# 아니라 **추출** 단계의 문제였다 — 가격이 JS로 렌더링되는 페이지에서 정규식 태그
# 제거로는 아무것도 못 건진다. Brave는 스니펫만 돌려주므로 이 문제를 못 푼다.
#
# 두 계층 모두 "무료 빠른 경로 우선, 실패 시에만 비싼 경로"라는 이 프로젝트의 기존
# 패턴을 따른다. TAVILY_API_KEY가 없으면 조용히 건너뛰고 ddgs 단독으로 폴백한다 —
# 배포 환경에서 env 주입이 빠져도 파이프라인이 죽지 않아야 하기 때문이다.
TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"
TAVILY_EXTRACT_ENDPOINT = "https://api.tavily.com/extract"
TAVILY_TIMEOUT = 15          # 검색보다 추출이 느리다(렌더링 대기). 근거 없는 임의값.

# 검색 스니펫(1~2문장)만으로는 fact 추출이 부족한 경우가 많아(파이프라인 문서 9절 recall 이슈),
# 상위 결과의 실제 페이지 본문을 가져와 함께 활용한다. HTML을 정교하게 파싱(readability 등)하지
# 않고 태그를 정규식으로 제거하는 간이 추출이라, 네비게이션·광고 텍스트가 섞여 들어올 수 있는
# 한계가 있음 — 빠른 MVP 구현을 위한 트레이드오프로 문서에 기록해둠.
PAGE_FETCH_TIMEOUT = 8
PAGE_FETCH_MAX_CHARS = 4000

# 간이 추출 결과가 이 길이에 못 미치면 "JS 렌더링 때문에 못 건졌다"고 보고 Tavily로
# 재시도한다. 근거 없는 임의값이다(설계값_레지스터.md 4절) — 값을 낮추면 Tavily 호출이
# 늘고, 높이면 진짜 짧은 페이지에도 불필요한 호출이 간다.
PAGE_FETCH_MIN_USEFUL_CHARS = 300

# 2차 자료로 간주할 도메인 (정부·공공기관, 산업조사기관, 상장사 IR 등)
#
# 기존 목록은 국내기관 위주(.go.kr, .or.kr 등)라 북미/글로벌 대상 시장조사에서는
# 대부분의 결과가 이 목록에 안 걸려 기본값인 3차(TERTIARY)로 떨어지는 문제가 있었음
# (파이프라인 문서 15절 참고). Precedence Research, Grand View Research,
# MarketsandMarkets, Fortune Business Insights, Allied Market Research 등
# 북미/글로벌 시장조사 결과에 실제로 자주 등장하는 리서치 회사 도메인을 추가해
# 이 문제를 완화함 — "검색이 안 되는" 게 아니라 "분류 목록이 좁아서 못 알아보는"
# 문제였으므로, 검색 로직은 그대로 두고 분류 목록만 확장.
SECONDARY_DOMAIN_PATTERNS = [
    r"\.go\.kr$",  # 정부기관
    r"kostat\.go\.kr",
    r"kotra\.or\.kr",
    r"kiet\.re\.kr",
    r"bok\.or\.kr",  # 한국은행
    r"statista\.com$",
    r"gartner\.com$",
    r"mckinsey\.com$",
    r"bcg\.com$",
    r"ibisworld\.com$",
    r"sec\.gov$",  # 미국 상장사 공시
    r"dart\.fss\.or\.kr$",  # 한국 상장사 공시(전자공시)
    r"\.or\.kr$",  # 협회류(산업 협회 등, 대체로 2차 자료 성격)
    # 북미/글로벌 시장조사 전문회사 (2026-07-21 추가)
    r"precedenceresearch\.com$",
    r"grandviewresearch\.com$",
    r"marketsandmarkets\.com$",
    r"fortunebusinessinsights\.com$",
    r"alliedmarketresearch\.com$",
    r"researchandmarkets\.com$",
    r"marketresearchfuture\.com$",
    r"globenewswire\.com$",  # 상장사·리서치사 보도자료 배포 채널
    r"prnewswire\.com$",
    r"businesswire\.com$",
    r"mordorintelligence\.com$",
    r"futuremarketinsights\.com$",
    r"transparencymarketresearch\.com$",
    r"coherentmarketinsights\.com$",
    r"emergenresearch\.com$",
    r"straitsresearch\.com$",
    r"cdc\.gov$",  # 미국 질병통제예방센터
    r"fda\.gov$",  # 미국 식품의약국
    r"census\.gov$",  # 미국 인구조사국
    r"cms\.gov$",  # 미국 메디케어·메디케이드 서비스센터
    r"\.gov$",  # 그 외 미국 정부기관 전반
]


def classify_source_tier(url: str) -> SourceTier:
    """URL 도메인 기반으로 2차/3차 자료를 휴리스틱 분류한다."""
    domain = urlparse(url).netloc.lower()
    for pattern in SECONDARY_DOMAIN_PATTERNS:
        if re.search(pattern, domain):
            return SourceTier.SECONDARY
    return SourceTier.TERTIARY


# 2026-07-23 변경: 기존 User-Agent("Mozilla/5.0 (compatible; ResearchBot/1.0)")가 문자열
# 안에 "ResearchBot"이라고 스스로 봇임을 밝히고 있었음 — 많은 사이트의 1차 방어선은 정교한
# 탐지가 아니라 User-Agent에 "bot" 같은 단어가 있는지 보는 단순 필터라, 이 문자열 자체가
# 불필요하게 차단을 자초하고 있었다. 실제 크롬 브라우저가 보내는 것과 동일한 형태의
# User-Agent로 교체 — 완전한 봇 탐지 회피는 아니지만(그건 이 프로젝트 규모에서 다루지
# 않기로 한 영역, 파이프라인 문서 33절 참고), 단순 문자열 필터 수준의 불필요한 차단은
# 피할 수 있다.
PAGE_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _tavily_api_key() -> Optional[str]:
    """호출 시점에 읽는다. 임포트 시점에 캐시하면 테스트에서 monkeypatch가 안 먹고,
    배포 후 env를 고쳤을 때 재시작 없이는 반영되지 않는다."""
    key = os.getenv("TAVILY_API_KEY")
    return key.strip() or None if key else None


def _extract_tavily(url: str, max_chars: int = PAGE_FETCH_MAX_CHARS) -> Optional[str]:
    """Tavily Extract로 본문을 가져온다. JS 렌더링 페이지 대응이 목적이다.

    정규식 간이 추출이 실패하거나 결과가 너무 짧을 때만 호출되므로 **비용이 실패
    시에만 발생**한다. 키가 없거나 호출이 실패하면 None을 반환해 호출부가 기존
    동작을 그대로 이어가게 한다(이 파일 전체가 지키는 "실패를 흡수한다" 원칙)."""
    api_key = _tavily_api_key()
    if not api_key:
        return None
    try:
        resp = requests.post(
            TAVILY_EXTRACT_ENDPOINT,
            json={"urls": [url], "extract_depth": "basic", "format": "text"},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TAVILY_TIMEOUT,
        )
        if resp.status_code != 200:
            log.info(f"  [Tavily 추출 실패] {url} — HTTP {resp.status_code}")
            return None
        data = resp.json() or {}
        for item in data.get("results") or []:
            raw = (item.get("raw_content") or "").strip()
            if raw:
                return re.sub(r"\s+", " ", raw)[:max_chars]
        return None
    except Exception as e:
        log.info(f"  [Tavily 추출 실패] {url} ({type(e).__name__}: {e})")
        return None


MOJIBAKE_PAT = re.compile(
    # UTF-8 한글(EA~ED 시작)을 latin-1로 읽으면 'ê ë ì í' + 라틴확장 문자가 이어진다.
    # 정상적인 한국어·영어 문서에는 이 조합이 나타나지 않는다.
    r"[êëìí][\u0080-\u00bf\u00c0-\u00ff]"
    # 다른 CJK/키릴 계열이 잘못 읽힌 흔적
    r"|Ã[\u0080-\u00bf\u00a0-\u00ff]"
    r"|â€[\u0099\u009c\u009d\u0093\u0094]"
)


def looks_mojibake(text: str, threshold: float = 0.005) -> bool:
    """문자 인코딩이 깨진 텍스트인지 판정한다.

    2026-07-28 추가. gminsights.com/ko 페이지가 Content-Type에 charset을 주지 않아
    requests가 RFC 2616 기본값(ISO-8859-1)으로 UTF-8 한글을 읽었고, 그 결과
    "테트라Pak 인터내셔널"이 "í í¸ë¼Pak ì¸í°ë´ì ë"로 깨졌다.

    피해가 수집 단계에서 멈추지 않았다는 점이 중요하다:
      · 깨진 글자에서 LLM이 없는 회사명(`Ìndusanal Inc.`)을 만들어냈다
      · 검증기는 "fact가 원문에 있는가"만 보므로, 원문도 fact도 함께 깨져 있으면
        '일치'로 판정한다 — 실제로 근거지지도 5점·관련성 5점으로 채택됐다
      · 문자열 유사도가 0에 가까워져 중복 제거(0.85 임계)가 무력화됐다.
        같은 사실이 '깨진 판'과 '정상 판'으로 두 번 저장됐다

    그래서 수집 계층만 고치지 않고 이 판정기를 추출·검증 앞단에도 둔다.
    charset을 틀리게 주는 사이트는 언제든 또 나온다.

    threshold: 전체 길이 대비 깨짐 신호 비율. 0으로 두지 않는 이유는 정상 문서에도
    특수문자가 우연히 섞일 수 있어서다. 0.005는 1,000자에 5회 이상이면 깨짐으로 본다.
    """
    if not text:
        return False
    hits = len(MOJIBAKE_PAT.findall(text))
    if hits == 0:
        return False
    return hits / max(len(text), 1) >= threshold


def decode_html(resp) -> str:
    """HTTP 응답 본문을 문자셋을 제대로 골라 문자열로 만든다.

    `resp.text`를 그대로 쓰면 안 되는 이유: Content-Type에 charset이 없을 때
    requests는 ISO-8859-1로 가정한다(RFC 2616). 한국어 페이지 상당수가 charset을
    헤더에 넣지 않고 HTML <meta>에만 넣으므로, 그대로 두면 한글이 전부 깨진다.

    순서대로 시도한다 — 앞쪽이 더 신뢰할 수 있는 근거다:
      1) 헤더의 charset (단, ISO-8859-1은 '기본값일 뿐'이므로 신뢰하지 않는다)
      2) HTML <meta charset> 선언
      3) UTF-8 (오늘 웹의 사실상 표준)
      4) charset_normalizer 자동 탐지
      5) cp949 (charset 없는 한국 레거시 페이지)
      6) latin-1 (실패하지 않는 마지막 수단 — 여기까지 오면 모지바케 필터가 잡는다)
    """
    raw: bytes = resp.content
    if not raw:
        return ""

    candidates: list[str] = []

    header_enc = requests.utils.get_encoding_from_headers(resp.headers)
    if header_enc and header_enc.lower() not in ("iso-8859-1", "latin-1"):
        candidates.append(header_enc)

    # <meta charset="..."> / <meta http-equiv="Content-Type" content="...charset=...">
    head = raw[:4096].decode("ascii", "ignore")
    for m in re.finditer(r'charset=["\']?\s*([\w\-]+)', head, re.IGNORECASE):
        candidates.append(m.group(1))

    candidates.append("utf-8")

    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best and best.encoding:
            candidates.append(best.encoding)
    except Exception:  # noqa: BLE001 — 탐지 실패가 수집을 막아선 안 된다
        pass

    candidates += ["cp949", "latin-1"]

    seen: set[str] = set()
    for enc in candidates:
        key = enc.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            text = raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        if looks_mojibake(text):
            # 디코딩은 성공했지만 결과가 깨졌다 — 다음 후보로 넘어간다.
            # latin-1은 어떤 바이트도 받아들이므로 이 검사가 없으면 항상 여기서 멈춘다.
            continue
        if enc.lower() != "utf-8":
            log.info(f"  [인코딩] {enc} 로 해석 (헤더값: {header_enc or '없음'})")
        return text

    log.info(f"  [인코딩] 후보 {len(seen)}개 모두 깨짐 — latin-1로 강제 해석")
    return raw.decode("latin-1", "replace")


def _fetch_page_text_direct(url: str, max_chars: int) -> Optional[str]:
    """정규식 기반 간이 추출(무료·빠른 경로).

    실패 사유는 남기되 kind는 붙이지 않는다 — 최종 실패 판정(kind=fetch_failed)은
    Tavily 폴백까지 다 해본 뒤 fetch_page_text()가 내린다. 여기서 fetch_failed를
    찍으면 프론트 출처 카드가 흐려진 뒤 성공 이벤트가 뒤따라 와 화면이 어긋난다."""
    try:
        resp = requests.get(
            url,
            timeout=PAGE_FETCH_TIMEOUT,
            headers={
                "User-Agent": PAGE_FETCH_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )
        content_type = resp.headers.get("Content-Type", "")
        if resp.status_code != 200 or "html" not in content_type.lower():
            log.info(
                f"  [읽기건너뜀] {url} (상태 {resp.status_code}, {content_type or '타입 없음'})"
            )
            return None
        html = decode_html(resp)
        html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception:
        log.info(f"  [읽기실패] {url}")
        return None


def fetch_page_text(url: str, max_chars: int = PAGE_FETCH_MAX_CHARS) -> Optional[str]:
    """스니펫 대신 쓸 수 있도록 페이지 실제 본문 텍스트를 가져온다. 실패하면 None을 반환해
    호출부가 스니펫으로 폴백할 수 있게 한다(네트워크 오류·404·PDF 등 어떤 이유로든 실패를
    전체 파이프라인이 멈추는 원인으로 만들지 않기 위함).

    2026-07-28 — 2단 구조로 바뀌었다.

        ① 정규식 간이 추출(무료)
        ② ①이 실패했거나 결과가 PAGE_FETCH_MIN_USEFUL_CHARS 미만이면 Tavily Extract

    ②를 넣은 이유는 파이프라인 18절 "심층조사 가격 정보 전멸"이다. 가격이 JS로
    렌더링되는 페이지에서 ①은 빈 문자열이나 네비게이션 텍스트만 건진다.

    ②까지 실패해도 ①이 짧게라도 건진 게 있으면 그걸 쓴다 — 없는 것보다는 낫고,
    후단 청크 필터(agents/verification.py)가 무관한 내용은 어차피 걸러낸다."""
    direct = _fetch_page_text_direct(url, max_chars)

    if direct and len(direct) >= PAGE_FETCH_MIN_USEFUL_CHARS:
        log.info(
            f"  [본문읽기] {url} ({len(direct)}자)",
            extra={"kind": "fetch", "url": url, "count": len(direct)},
        )
        return direct

    extracted = _extract_tavily(url, max_chars)
    if extracted:
        log.info(
            f"  [본문읽기·Tavily] {url} ({len(extracted)}자)",
            extra={"kind": "fetch", "url": url, "count": len(extracted)},
        )
        return extracted

    if direct:
        log.info(
            f"  [본문읽기·짧음] {url} ({len(direct)}자)",
            extra={"kind": "fetch", "url": url, "count": len(direct)},
        )
        return direct

    log.info(f"  [본문없음] {url}", extra={"kind": "fetch_failed", "url": url})
    return None


# CRAG(arXiv 2401.15884)의 decompose-then-recompose 아이디어를 적용하기 위한 청크 분해 유틸.
# fetch_page_text()가 공백을 전부 단일 스페이스로 뭉개기 때문에(정규식 기반 태그 제거의 부작용으로
# 문단 경계 정보가 사라짐) 문단 단위 분해 대신 고정 길이 슬라이딩 윈도우로 자른다. overlap을 두는
# 이유는 fact 하나가 청크 경계에 걸쳐 있을 때 양쪽 청크 중 최소 하나는 그 내용을 온전히 포함하게
# 하기 위함이다. 실제 관련성 채점(LLM 호출)은 agents/verification.py에서 수행한다 — 이 파일은
# 순수 텍스트 유틸이라 OpenAI client 의존성을 두지 않는다.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """본문을 chunk_size 길이의 겹치는(overlap) 슬라이딩 청크로 분해한다.
    빈 문자열이면 빈 리스트, chunk_size보다 짧은 본문이면 청크 1개(원문 그대로)를 반환한다."""
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def _search_tavily(query: str, max_results: int) -> list[dict]:
    """Tavily Search로 보조 검색을 수행한다. ddgs 결과가 부족할 때만 부족한 만큼 호출된다.

    API 키가 없거나 호출이 실패하면 빈 리스트를 반환해 호출부(search_web)가 ddgs 결과만으로
    계속 진행하게 한다 — 2026-07-23에 Brave로 세웠던 것과 같은 계약이다. 다만 Brave와 달리
    이쪽은 실제로 키가 있어 동작한다.

    search_depth는 "basic"(1크레딧)을 쓴다. "advanced"는 2크레딧인데, 여기서 필요한 것은
    후보 URL 목록이지 정제된 본문이 아니다 — 본문은 추출 계층이 따로 가져온다."""
    api_key = _tavily_api_key()
    if not api_key:
        return []
    try:
        resp = requests.post(
            TAVILY_SEARCH_ENDPOINT,
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TAVILY_TIMEOUT,
        )
        if resp.status_code != 200:
            log.info(f"  [Tavily 검색 실패] '{query}' — HTTP {resp.status_code}, ddgs 결과만 사용")
            return []
        data = resp.json() or {}
        results = []
        for r in (data.get("results") or [])[:max_results]:
            url = r.get("url", "")
            if not url:
                continue
            snippet = r.get("content", "") or ""
            results.append(
                {
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": snippet,
                    "content": snippet,
                    "source_tier": classify_source_tier(url).value,
                }
            )
        return results
    except Exception as e:
        log.info(
            f"  [Tavily 검색 실패] '{query}' 검색 중 오류 발생({type(e).__name__}: {e}) — ddgs 결과만 사용"
        )
        return []


def search_web(query: str, max_results: int = 5, fetch_full_text: bool = False) -> list[dict]:
    """
    query로 웹검색을 수행하고, 각 결과에 tier를 매겨 반환한다.
    반환 형식: [{"title", "url", "snippet", "source_tier", "content"}]

    fetch_full_text=True면 각 결과의 실제 페이지 본문을 추가로 가져와 "content" 필드에 채운다
    (실패 시 스니펫으로 폴백). 요청 수가 늘어나 느려지므로 필요한 경우에만 켤 것.

    ddgs 라이브러리는 검색 결과가 진짜 하나도 없을 때(예: 너무 구체적인 재구성 질의)
    빈 리스트를 반환하는 대신 DDGSException("No results found.")을 던지는 경우가 있음
    (실제로 query rewriting 재시도 질의에서 발생해 파이프라인 전체가 죽는 크래시로 이어진
    사례 확인됨 — 파이프라인 문서 17절). fetch_page_text()가 네트워크 오류를 이미
    "실패 시 None 반환"으로 흡수하는 것과 같은 원칙으로, 여기서도 검색 자체의 실패를
    빈 리스트로 흡수해 호출부(재시도 로직, 정상 흐름)가 계속 진행되게 한다.

    다중 검색 백엔드(파이프라인 문서 32절): ddgs 결과가 max_results에 못 미치면
    (빈 리스트 포함) Tavily Search로 부족한 만큼만 보완한다. ddgs가 아예 실패해도
    (예외 발생) 빈 결과로 간주하고 Tavily 보완을 계속 시도한다 — 한쪽 백엔드가 죽어도
    다른 쪽으로 recall을 최대한 지키려는 목적.

    2026-07-28 — 보조 백엔드를 Brave에서 Tavily로 바꿨다. Brave는 키를 넣은 적이 없어
    한 번도 실행되지 않았고(즉 폴백이 사실상 없었다), 2026년 2월부로 무료 티어도
    없어졌다. TAVILY_API_KEY가 없으면 `_search_tavily()`가 빈 리스트를 반환하므로
    기존 ddgs-only 동작과 동일하게 유지되는 계약은 그대로다.
    """
    results: list[dict] = []
    seen_urls: set[str] = set()

    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                url = r.get("href") or r.get("url") or ""
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                snippet = r.get("body", "")
                content = snippet
                if fetch_full_text:
                    page_text = fetch_page_text(url)
                    if page_text:
                        content = page_text
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": url,
                        "snippet": snippet,
                        "content": content,
                        "source_tier": classify_source_tier(url).value,
                    }
                )
                log.info(
                    f"  [검색결과] {r.get('title', '')[:60]}",
                    extra={
                        "kind": "search_result",
                        "url": url,
                        "tier": classify_source_tier(url).value,
                        "title": r.get("title", ""),
                    },
                )
    except Exception as e:
        log.info(f"  [ddgs 검색 실패] '{query}' 검색 중 오류 발생({type(e).__name__}: {e}) — Tavily 백엔드로 계속 진행합니다.")

    if len(results) < max_results:
        remaining = max_results - len(results)
        tavily_results = _search_tavily(query, remaining)
        for r in tavily_results:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            if fetch_full_text:
                page_text = fetch_page_text(r["url"])
                if page_text:
                    r = {**r, "content": page_text}
            results.append(r)
            log.info(
                f"  [검색결과] {r.get('title', '')[:60]}",
                extra={
                    "kind": "search_result",
                    "url": r["url"],
                    "tier": r.get("source_tier", ""),
                    "title": r.get("title", ""),
                },
            )
        if tavily_results:
            log.info(f"  [Tavily 보완] ddgs {max_results - remaining}건 + Tavily {len(tavily_results)}건")

    return results


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    q = sys.argv[1] if len(sys.argv) > 1 else "웨어러블 헬스케어 기기 시장 규모"
    for r in search_web(q, max_results=5):
        log.info(f"[{r['source_tier']}] {r['title']}")
        log.info(f"  {r['url']}")
        log.info(f"  {r['snippet'][:120]}...\n")
