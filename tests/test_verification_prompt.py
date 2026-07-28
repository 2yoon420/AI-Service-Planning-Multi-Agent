"""검증기 채점 프롬프트의 관점 분리 회귀 테스트.

2026-07-28 judge self-test에서 발견한 결함을 박제한다.

결함: grade_fact()가 perspective와 무관하게 하나의 템플릿을 써서, 관련성을
채점할 때도 원본 본문을 함께 넣었다. 그 결과 모델이 관련성 대신 근거지지도를
채점했고("원문에 언급이 없어 부분적 관련성만"), min 결합이 근거지지도를
두 번 감점하는 이중 처벌이 됐다. solar-mini/pro2/pro3 세 모델 전부에서
relevance 채택기대 항목이 무너진 원인이다.

여기서 지키는 불변식: 각 관점은 자기 판단에 필요한 입력만 본다.
이 불변식이 깨지면 min 결합의 전제(두 축의 독립)가 깨진다.
"""

import pytest

from agents.verification import (
    PERSPECTIVE_INPUT_KEYS,
    build_grading_prompt,
    grade_fact,
)

FACT = "미국 고령층의 스마트워치 보급률이 최근 상승하고 있다."
SOURCE = (
    "가민의 웨어러블 부문 매출은 전년 대비 증가했다. "
    "피트니스 추적 기능과 배터리 수명이 강점으로 꼽힌다."
)
TOPIC = "웨어러블 헬스케어 기기"
MARKET = "북미 시니어 건강관리 시장"


def _prompt(perspective, source_content=SOURCE):
    return build_grading_prompt(FACT, source_content, TOPIC, MARKET, perspective)


def test_관련성_프롬프트에_원문이_들어가지_않는다():
    """이 테스트가 깨지면 min 결합이 다시 이중 처벌이 된다."""
    p = _prompt("relevance")
    assert "원본 본문" not in p
    assert "피트니스 추적 기능" not in p  # 원문 내용 자체가 새지 않는지
    assert "가민" not in p


def test_관련성_프롬프트에_연구대상과_목표시장은_들어간다():
    p = _prompt("relevance")
    assert TOPIC in p
    assert MARKET in p


def test_근거지지도_프롬프트에_원문이_들어간다():
    p = _prompt("groundedness")
    assert "원본 본문" in p
    assert "피트니스 추적 기능" in p


def test_근거지지도_프롬프트에_연구대상과_목표시장이_들어가지_않는다():
    """대칭. 근거지지도는 주제를 알 필요가 없다 — 알면 주제 적합성이 새어든다."""
    p = _prompt("groundedness")
    assert TOPIC not in p
    assert MARKET not in p


def test_두_관점의_입력집합은_겹치지_않는다():
    rel = set(PERSPECTIVE_INPUT_KEYS["relevance"])
    grd = set(PERSPECTIVE_INPUT_KEYS["groundedness"])
    assert rel and grd
    assert rel.isdisjoint(grd), "두 축이 같은 입력을 보면 독립 가정이 깨진다"


def test_모든_관점에_채점대상_fact와_지시문이_들어간다():
    for perspective in PERSPECTIVE_INPUT_KEYS:
        p = _prompt(perspective)
        assert FACT in p
        assert "채점 대상 fact" in p
        assert "1~5점" in p


def test_원문이_비어도_근거지지도_프롬프트가_깨지지_않는다():
    p = _prompt("groundedness", source_content="")
    assert "(원본 본문 없음)" in p


def test_원문은_3000자로_자른다():
    long_source = "가" * 5000
    p = _prompt("groundedness", source_content=long_source)
    assert "가" * 3000 in p
    assert "가" * 3001 not in p


def test_grade_fact가_관점별_프롬프트를_실제로_사용한다():
    """빌더만 고치고 grade_fact가 옛 템플릿을 계속 쓰면 소용없다.
    LLM은 부르지 않고, 넘어간 프롬프트만 가로채 확인한다."""
    captured = {}

    class _FakeCompletions:
        def create(self, *, model, messages, response_format):
            captured["prompt"] = messages[0]["content"]

            class _Msg:
                content = '{"score": 5, "reasoning": "x"}'

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    class _FakeClient:
        chat = type("_Chat", (), {"completions": _FakeCompletions()})()

    for perspective, forbidden in (
        ("relevance", "가민"),
        ("groundedness", TOPIC),
    ):
        captured.clear()
        score, _ = grade_fact(_FakeClient(), FACT, SOURCE, TOPIC, MARKET, perspective)
        assert score == 5
        assert forbidden not in captured["prompt"], (
            f"{perspective} 프롬프트에 {forbidden!r} 가 새어들었다"
        )
