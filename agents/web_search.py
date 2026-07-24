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

# 2026-07-23 추가: 다중 검색 백엔드(파이프라인 문서 32절 참고). ddgs 하나만 쓰다 보니
# ddgs가 결과를 적게/못 주는 질의에서 recall이 그대로 죽는 문제가 있었음. Brave Search
# API(무료 티어 월 2,000건)를 보조 백엔드로 추가해, ddgs 결과가 부족할 때만 부족한 만큼
# 채워 넣는다. BRAVE_API_KEY가 .env에 없으면 이 백엔드는 조용히 건너뛴다(선택적 기능 —
# 키 없이도 기존처럼 ddgs만으로 동작).
BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
BRAVE_FETCH_TIMEOUT = 8

# 검색 스니펫(1~2문장)만으로는 fact 추출이 부족한 경우가 많아(파이프라인 문서 9절 recall 이슈),
# 상위 결과의 실제 페이지 본문을 가져와 함께 활용한다. HTML을 정교하게 파싱(readability 등)하지
# 않고 태그를 정규식으로 제거하는 간이 추출이라, 네비게이션·광고 텍스트가 섞여 들어올 수 있는
# 한계가 있음 — 빠른 MVP 구현을 위한 트레이드오프로 문서에 기록해둠.
PAGE_FETCH_TIMEOUT = 8
PAGE_FETCH_MAX_CHARS = 4000

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


def fetch_page_text(url: str, max_chars: int = PAGE_FETCH_MAX_CHARS) -> Optional[str]:
    """스니펫 대신 쓸 수 있도록 페이지 실제 본문 텍스트를 가져온다. 실패하면 None을 반환해
    호출부가 스니펫으로 폴백할 수 있게 한다(네트워크 오류·404·PDF 등 어떤 이유로든 실패를
    전체 파이프라인이 멈추는 원인으로 만들지 않기 위함)."""
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
            return None
        html = resp.text
        html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception:
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


def _search_brave(query: str, max_results: int) -> list[dict]:
    """Brave Search API로 보조 검색을 수행한다. API 키가 없거나 호출이 실패하면 빈 리스트를
    반환해 호출부(search_web)가 ddgs 결과만으로 계속 진행할 수 있게 한다(fetch_page_text()/
    search_web()의 ddgs 호출과 같은 "실패를 흡수한다" 원칙)."""
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        return []
    try:
        resp = requests.get(
            BRAVE_SEARCH_ENDPOINT,
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key,
            },
            timeout=BRAVE_FETCH_TIMEOUT,
        )
        if resp.status_code != 200:
            print(f"  [Brave 검색 실패] '{query}' — HTTP {resp.status_code}, ddgs 결과만 사용")
            return []
        data = resp.json()
        web_results = (data.get("web") or {}).get("results") or []
        results = []
        for r in web_results[:max_results]:
            url = r.get("url", "")
            snippet = r.get("description", "")
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
        print(f"  [Brave 검색 실패] '{query}' 검색 중 오류 발생({type(e).__name__}: {e}) — ddgs 결과만 사용")
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

    2026-07-23 추가(다중 검색 백엔드, 파이프라인 문서 32절): ddgs 결과가 max_results에
    못 미치면(빈 리스트 포함) Brave Search API로 부족한 만큼만 보완한다. ddgs가 아예
    실패해도(예외 발생) 빈 결과로 간주하고 Brave 보완을 계속 시도한다 — 한쪽 백엔드가
    죽어도 다른 쪽으로 recall을 최대한 지키려는 목적. BRAVE_API_KEY가 없으면
    `_search_brave()`가 빈 리스트를 반환하므로 기존 ddgs-only 동작과 동일하게 유지된다.
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
    except Exception as e:
        print(f"  [ddgs 검색 실패] '{query}' 검색 중 오류 발생({type(e).__name__}: {e}) — Brave 백엔드로 계속 진행합니다.")

    if len(results) < max_results:
        remaining = max_results - len(results)
        brave_results = _search_brave(query, remaining)
        for r in brave_results:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            if fetch_full_text:
                page_text = fetch_page_text(r["url"])
                if page_text:
                    r = {**r, "content": page_text}
            results.append(r)
        if brave_results:
            print(f"  [Brave 보완] ddgs {max_results - remaining}건 + Brave {len(brave_results)}건")

    return results


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "웨어러블 헬스케어 기기 시장 규모"
    for r in search_web(q, max_results=5):
        print(f"[{r['source_tier']}] {r['title']}")
        print(f"  {r['url']}")
        print(f"  {r['snippet'][:120]}...\n")
