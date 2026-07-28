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


# ══════════════════════════════════════════════════════════════════════
#  통화 환산 (2026-07-28 추가) — 한국 시장 실행에서 드러난 결함
#
#  사고: 배포 서버에서 "시니어 가정간편식(HMR) / 한국 시니어 케어푸드 시장"을 돌렸더니
#  기획서 초안에 이렇게 실렸다.
#
#      TAM=2,500,000,000,000 USD [원문 2.5e+04억 x 100,000,000]
#      근거: "국내 케어푸드 시장규모는 2021년 기준 약 2조 5000억원으로 추산"
#
#  원문은 "2조 5000억 원"이고 배율 계산도 맞다. 틀린 것은 통화다 — 2.5조 원은 약
#  18억 달러인데 2.5조 달러(세계 GDP의 2% 이상)로 찍혔다. 1,380배 과대.
#
#  원인 두 가지:
#   ① 스키마가 배율(tam_scale)은 물어보면서 통화는 묻지 않았고 unit="USD"가 하드코딩됨
#   ② 상식 검산이 하한(100만 USD)만 봤다. 과대 방향은 아무도 막지 않았다
#
#  왜 이제야 드러났나: 유럽·북미 실행은 출처가 전부 달러였다. 한국어 1차 자료를
#  쓰는 순간 즉시 나타났다. 도메인을 넓히지 않으면 못 찾는 종류의 결함이다.
#  (NUMCoT 논문이 지적한 한자문화권 수 체계 문제와 같은 계열이다.)
# ══════════════════════════════════════════════════════════════════════

from agents.market_research import (  # noqa: E402
    _FX_TO_USD,
    _TAM_SANITY_MAX_USD,
    _TAM_SANITY_MIN_USD,
    currency_to_usd,
    scale_to_multiplier,
)


def test_한국_HMR_사고를_재현하고_고쳐진_것을_확인한다():
    """실제 사고 값으로 회귀를 막는다."""
    scaled = 2.5e4 * scale_to_multiplier("억")      # "2조 5000억" = 25,000억
    assert scaled == 2.5e12                          # 원화로는 정확하다

    usd, note = currency_to_usd(scaled, "KRW")
    assert 1.5e9 < usd < 2.5e9, f"2.5조 원은 약 18억 달러여야 한다 (실제 {usd:,.0f})"
    assert "KRW → USD" in note
    assert usd < _TAM_SANITY_MAX_USD                 # 이제 상한 검산을 통과한다


def test_통화를_틀리면_상한_검산에_걸린다():
    """수정 전 동작. 이 값이 상한을 넘지 않으면 검산이 무의미해진다."""
    wrong, _ = currency_to_usd(2.5e12, "USD")
    assert wrong > _TAM_SANITY_MAX_USD


def test_통화_불명이면_USD로_가정하지_않고_경고한다():
    """'불명'을 USD로 처리하는 것이 바로 이 결함의 원인이었다."""
    usd, note = currency_to_usd(1000.0, "불명")
    assert usd == 1000.0, "환산하지 않고 원문 숫자를 그대로 넘긴다"
    assert "⚠️" in note and "USD로 가정하지 않고" in note


def test_USD는_환산하지_않고_군더더기_문구도_붙이지_않는다():
    usd, note = currency_to_usd(1234.0, "USD")
    assert usd == 1234.0
    assert note == ""


@pytest.mark.parametrize("currency", ["KRW", "EUR", "JPY", "CNY", "GBP"])
def test_지원_통화는_모두_환산율이_있다(currency):
    usd, note = currency_to_usd(100.0, currency)
    assert usd != 100.0 or currency == "USD"
    assert note, "환산했으면 무엇을 어떻게 바꿨는지 초안에 남아야 한다"


def test_모르는_통화는_조용히_넘기지_않고_경고한다():
    usd, note = currency_to_usd(500.0, "INR")     # 환율 표에 없다
    assert usd == 500.0
    assert "⚠️" in note and "INR" in note


def test_환율표에_USD가_1로_들어있다():
    """USD 자기환산이 1이 아니면 달러 출처가 전부 망가진다."""
    assert _FX_TO_USD["USD"] == 1.0


def test_원화_환율_방향이_뒤집히지_않았다():
    """1/1380 대신 1380을 넣는 실수를 막는다. 방향이 뒤집히면 2.5조 원이
    3,450조 달러가 된다."""
    assert _FX_TO_USD["KRW"] < 1, "1원은 1달러보다 싸다"
    assert 0.0005 < _FX_TO_USD["KRW"] < 0.002


def test_상한과_하한이_모순되지_않는다():
    assert _TAM_SANITY_MIN_USD < _TAM_SANITY_MAX_USD


def test_상한이_세계_GDP_규모_아래에_있다():
    """상한이 너무 크면 아무것도 못 잡는다. 세계 GDP는 약 100조 USD다."""
    assert _TAM_SANITY_MAX_USD <= 1e13
