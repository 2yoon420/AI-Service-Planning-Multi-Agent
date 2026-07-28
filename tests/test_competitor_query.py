"""경쟁사 심층조사 질의 생성 회귀 테스트 (2026-07-28 추가).

배경: 목표시장이 "유럽 B2B 유통 시장"이던 실행에서 경쟁사 9곳 전부 가격이
"(정보 없음)"으로 비었다. 원인은 _ENGLISH_REVIEW_MARKET_KEYWORDS에 유럽이
빠져 있어 한국어 가격 질의가 나간 것이었다 — 유럽 B2B 포장재 기업을 한국어로
검색하면 가격 정보가 나올 리 없다.

이 테스트는 지역별 질의 언어 선택을 고정한다. 목록에 지역을 추가할 때
기존 동작이 깨지지 않는지도 함께 확인한다.
"""

import pytest

from agents.competitor import _deep_dive_queries, _use_english_price_query


# --- 영어 질의를 써야 하는 시장 -------------------------------------------

@pytest.mark.parametrize(
    "market",
    [
        "유럽 B2B 유통 시장",          # 2026-07-28 실제 사고 사례
        "유럽 시니어 건강관리 시장",
        "EU 친환경 포장재 시장",
        "European B2B distribution",
        "북미 시니어 건강관리 시장",    # 기존 동작 — 깨지면 안 된다
        "미국 웨어러블 시장",
        "United States healthcare",
        "독일 자동차 부품 시장",
        "글로벌 SaaS 시장",
    ],
)
def test_영어권_유럽_글로벌_시장은_영어로_질의한다(market):
    assert _use_english_price_query(market) is True
    queries = _deep_dive_queries("Tetra Pak", market)
    assert queries[0] == "Tetra Pak price review comparison 2026"


# --- 한국어 질의를 써야 하는 시장 -----------------------------------------

@pytest.mark.parametrize(
    "market",
    [
        "국내 반려동물 시장",
        "한국 시니어 건강관리 시장",
        "부산 지역 소상공인 시장",
    ],
)
def test_국내_시장은_한국어로_질의한다(market):
    assert _use_english_price_query(market) is False
    queries = _deep_dive_queries("테트라팍", market)
    assert queries[0] == "테트라팍 가격 비교 리뷰 추천 2026"


def test_목표시장이_비어도_예외없이_한국어로_폴백한다():
    """목표시장 정보가 없을 때 파이프라인이 죽지 않아야 한다."""
    assert _use_english_price_query("") is False
    queries = _deep_dive_queries("테트라팍", "")
    assert queries[0] == "테트라팍 가격 비교 리뷰 추천 2026"


def test_대소문자를_구분하지_않는다():
    assert _use_english_price_query("Europe B2B") is True
    assert _use_english_price_query("EUROPE B2B") is True
    assert _use_english_price_query("europe b2b") is True


def test_가격_외_두_질의는_지역과_무관하게_유지된다():
    """이번 변경이 투자·매출/판매채널 질의까지 건드리지 않았는지 확인한다."""
    for market in ["유럽 B2B 유통 시장", "국내 반려동물 시장"]:
        queries = _deep_dive_queries("테트라팍", market)
        assert len(queries) == 3
        assert queries[1] == "테트라팍 투자 유치 매출 실적 규모"
        assert queries[2] == "테트라팍 판매 채널 유통 파트너십"
