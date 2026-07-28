"""시장규모 단위 환산 회귀 테스트 (2026-07-28 추가).

배경: 유럽 친환경 포장재 기획서 실행에서 "116.13억 달러"라는 근거 문장이
기획서에 "TAM 116 USD"로 찍히는 사고가 났다. 원인은 배율 환산(억 -> 1e8)을
LLM에게 맡겨두고 코드에 검산이 전혀 없었던 것이다.

이 테스트는 그 사고를 고정한다 — 환산이 코드로 넘어왔는지, 그리고 환산이
틀렸을 때 조용히 넘어가지 않고 경고가 남는지를 확인한다.
"""

from unittest.mock import patch

import pytest

from agents.market_research import (
    _TAM_SANITY_MIN_USD,
    calculate_market_sizing,
    scale_to_multiplier,
)
from agents.writer import _fmt_num, _fmt_readable_scale


# --- 배율 환산 자체 ---------------------------------------------------------

@pytest.mark.parametrize(
    "scale,expected",
    [
        ("없음", 1.0),
        ("천", 1e3),
        ("만", 1e4),
        ("억", 1e8),
        ("조", 1e12),
        ("thousand", 1e3),
        ("million", 1e6),
        ("billion", 1e9),
        ("trillion", 1e12),
    ],
)
def test_배율_단어가_곱할_수로_환산된다(scale, expected):
    assert scale_to_multiplier(scale) == expected


@pytest.mark.parametrize("unknown", [None, "", "lakh", "crore", "제곱미터"])
def test_모르는_배율은_1로_처리해_파이프라인을_멈추지_않는다(unknown):
    """한계를 명시적으로 고정한다: enum에 없는 표현은 배율 없음으로 처리된다.
    틀릴 수는 있지만 예외로 전체 실행이 죽는 것보다 낫고, 상식 가드가 뒤를 받는다."""
    assert scale_to_multiplier(unknown) == 1.0


# --- calculate_market_sizing 통합 -------------------------------------------

def _fake_topdown(**overrides) -> dict:
    base = {
        "tam_found": True,
        "tam_value": 116.13,
        "tam_scale": "억",
        "tam_year": "2025 (예측치)",
        "tam_source_snippet": "유럽 친환경 포장재 시장 규모는 116.13억 달러였습니다.",
        "sam_ratio": 0.25,
        "sam_ratio_reasoning": "테스트",
        "som_ratio": 0.03,
        "som_ratio_reasoning": "테스트",
    }
    base.update(overrides)
    return base


def _run(topdown: dict):
    with patch("agents.market_research._estimate_topdown", return_value=topdown), \
         patch("agents.market_research.save_market_sizing"):
        return calculate_market_sizing(
            client=None, topic="친환경 포장재",
            target_market="유럽 B2B 유통 시장", facts=[],
        )


def test_사고사례_116억달러가_제대로_환산된다():
    """2026-07-28 실제 사고 재현. 이전 코드에서는 116.13이 그대로 남았다."""
    sizing = _run(_fake_topdown())
    assert sizing.tam_topdown == pytest.approx(11_613_000_000.0)
    assert sizing.sam_topdown == pytest.approx(11_613_000_000.0 * 0.25)
    assert sizing.som_topdown == pytest.approx(11_613_000_000.0 * 0.25 * 0.03)


def test_영어_배율도_환산된다():
    sizing = _run(_fake_topdown(tam_value=505, tam_scale="billion"))
    assert sizing.tam_topdown == pytest.approx(505e9)


def test_배율이_없는_원문은_그대로_쓴다():
    sizing = _run(_fake_topdown(tam_value=5_000_000_000, tam_scale="없음"))
    assert sizing.tam_topdown == pytest.approx(5e9)


def test_환산이_틀리면_검산_경고가_남는다():
    """LLM이 배율을 '없음'으로 잘못 답한 경우 — 값은 남기되 경고를 반드시 붙인다."""
    sizing = _run(_fake_topdown(tam_value=116.13, tam_scale="없음"))
    assert sizing.tam_topdown == pytest.approx(116.13)
    warnings = [a for a in sizing.assumptions if "검산 경고" in a]
    assert len(warnings) == 1, "비정상적으로 작은 TAM에는 경고가 붙어야 한다"
    assert f"{_TAM_SANITY_MIN_USD:,.0f}" in warnings[0]


def test_정상_규모에는_경고가_붙지_않는다():
    sizing = _run(_fake_topdown())
    assert not [a for a in sizing.assumptions if "검산 경고" in a]


def test_TAM을_못_찾으면_None이고_경고도_없다():
    sizing = _run(_fake_topdown(tam_found=False))
    assert sizing.tam_topdown is None
    assert not [a for a in sizing.assumptions if "검산 경고" in a]


# --- writer 표기 ------------------------------------------------------------

def test_큰_수는_읽기_쉬운_배율이_함께_표기된다():
    """개요 작성 LLM에게 넘어가는 문자열이 모호하지 않아야 한다."""
    out = _fmt_num(11_613_000_000.0, "USD")
    assert "11,613,000,000 USD" in out
    assert "약 116.1억" in out


def test_작은_수는_보조표기를_붙이지_않는다():
    assert _fmt_readable_scale(116.13) is None
    assert _fmt_num(116.13, "USD") == "116 USD"


def test_계산_불가는_그대로_표기된다():
    assert _fmt_num(None, "USD") == "계산 불가"
