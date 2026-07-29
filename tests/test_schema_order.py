"""2×2 요인 실험(`eval/schema_order.py`)의 회귀 테스트.

## 이 테스트가 지키려는 것

이 실험은 **운영 코드의 상수를 일시 교체해** 조건을 만든다. 교체가 실제로 반영되지
않으면 네 조건이 모두 같아지고, 그러면 "차이가 없다"는 결론이 나온다 — **틀린 결론이
아니라 무의미한 결론**이다. 그래서 배선을 계약으로 박아 둔다.

변조실험에서 이 검사 자체의 구멍이 드러난 이력이 있다. `grade_fact()` 를 우회해
직접 호출하도록 고쳐도 "스키마가 맞다"는 검사는 통과했다. **"스키마가 맞다"와
"운영 경로를 거쳤다"는 다른 주장이다.**
"""

from __future__ import annotations

import json

import pytest

import agents.verification as V
from eval.schema_order import (  # noqa: I001
    ANCHOR_5, CONDITIONS, RecordingClient, cites_source,
    ANCHOR_R1, GRADE_4_VARIANTS, RULE0_TEXT, TARGET_MARKETS, apply_rule0,
    grade_with, rubric_with_4_variant, rubric_with_rule0, rubric_without_4,
    rubric_without_rule0, schema_reasoning_first, schema_score_first,
    target_market_for,
)


# ── 스키마 변형 ────────────────────────────────────────────────────────────
def test_실험조건이_운영상태에_의존하지_않는다():
    """처음에는 조건 A를 '운영 스키마 그대로'로 정의했다.

    결함 M을 수정하자 운영이 조건 D가 되어 A를 만들 수 없게 됐고, 테스트 8개가
    깨졌다. **실험 조건을 운영 상태에 상대적으로 정의하면 운영이 바뀌는 순간 과거
    측정과 비교할 수 없게 된다.** 두 방향을 모두 명시적으로 구성해야 한다.
    """
    assert list(schema_score_first()["json_schema"]["schema"]["properties"]) == ["score", "reasoning"]
    assert list(schema_reasoning_first()["json_schema"]["schema"]["properties"]) == ["reasoning", "score"]


def test_운영스키마는_reasoning이_먼저다():
    """결함 M 수정 상태. `tests/test_rubric_completeness.py` 와 이중으로 지킨다."""
    assert list(V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]) == ["reasoning", "score"]


def test_변형스키마는_reasoning이_먼저다():
    s = schema_reasoning_first()
    sch = s["json_schema"]["schema"]
    assert list(sch["properties"]) == ["reasoning", "score"]
    assert sch["required"] == ["reasoning", "score"], \
        "required 순서도 생성 순서에 영향을 준다 (Router에서 확인)"


def test_변형이_운영스키마를_건드리지_않는다():
    before = json.dumps(V.GRADE_SCHEMA, ensure_ascii=False, sort_keys=True)
    schema_reasoning_first()
    assert json.dumps(V.GRADE_SCHEMA, ensure_ascii=False, sort_keys=True) == before


def test_변형이_description을_바꾸지_않는다():
    """순서 효과만 분리하려면 문구는 같아야 한다."""
    a = V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]
    b = schema_reasoning_first()["json_schema"]["schema"]["properties"]
    for k in ("score", "reasoning"):
        assert a[k] == b[k], k


# ── 루브릭 변형 ────────────────────────────────────────────────────────────
def test_수정전_루브릭을_재현할_수_있다():
    """수정 효과를 다시 검증하려면 수정 전 상태를 언제든 만들 수 있어야 한다."""
    p = rubric_without_4(V.PERSPECTIVE_PROMPTS["groundedness"])
    assert "- 4점:" not in p
    for n in ("1점:", "2점:", "3점:", "5점:"):
        assert n in p, f"{n} 정의까지 지워졌다"


def test_4점_제거가_다른_등급을_건드리지_않는다():
    orig = V.PERSPECTIVE_PROMPTS["groundedness"]
    stripped = rubric_without_4(orig)
    assert len(stripped) < len(orig)
    # 5점 정의와 3점 정의가 붙어야 한다 (사이에 있던 4점만 빠짐)
    i5 = stripped.find("- 5점:")
    seg = stripped[i5:stripped.find("- 3점:")]
    assert "4점" not in seg, seg


def test_이미_4점이_없으면_실패한다():
    with pytest.raises(SystemExit):
        rubric_without_4(rubric_without_4(V.PERSPECTIVE_PROMPTS["groundedness"]))


def test_운영루브릭의_4점이_5점과_3점_사이에_있다():
    p = V.PERSPECTIVE_PROMPTS["groundedness"]
    i5, i4, i3 = p.find(ANCHOR_5), p.find("- 4점:"), p.find("- 3점:")
    assert i5 < i4 < i3, "척도 순서가 5→4→3 이어야 한다"


def test_문구를_다른_변형으로_교체할_수_있다():
    """과거 실험 문구(v1·v2)와 비교할 수 있어야 한다 — 3회 실험은 v2로 돌렸다."""
    orig = V.PERSPECTIVE_PROMPTS["groundedness"]
    for v in ("v1", "v2"):
        p = rubric_with_4_variant(orig, v)
        assert "- 4점:" in p
        assert p != orig
        assert p.count("- 4점:") == 1, "교체가 아니라 추가가 됐다"


# ── 배선 ───────────────────────────────────────────────────────────────────
ITEM = {"text": "시장은 2조 원 규모다", "source_excerpt": "시장은 2조 원 규모다",
        "topic": "테스트", "region": "한국"}


@pytest.mark.parametrize("cond", list(CONDITIONS))
def test_조건별_스키마가_실제로_전달된다(cond):
    """프롬프트 쪽 확인은 `test_조건별_규칙0_상태가_실제로_전달된다`가 함께 본다."""
    _, reorder, add4, add_r0 = CONDITIONS[cond]
    r0 = apply_rule0(add_r0)
    cl = RecordingClient()
    grade_with(cl, schema_reasoning_first() if reorder else schema_score_first(),
               r0 if add4 else (lambda p: r0(rubric_without_4(p))), ITEM, "테스트 시장")
    sch = cl.seen[-1]["response_format"]["json_schema"]["schema"]
    want = ["reasoning", "score"] if reorder else ["score", "reasoning"]
    assert list(sch["properties"]) == want
    assert sch["required"] == want


def test_호출후_운영상수가_복구된다():
    cl = RecordingClient()
    r0 = apply_rule0(True)
    grade_with(cl, schema_score_first(), lambda p: r0(rubric_without_4(p)), ITEM, "테스트 시장")
    assert list(V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]) == ["reasoning", "score"]
    assert "- 4점:" in V.PERSPECTIVE_PROMPTS["groundedness"]
    assert "■ 규칙 0" not in V.PERSPECTIVE_PROMPTS["groundedness"], "규칙 0이 운영에 새면 안 된다"


def test_예외가_나도_운영상수가_복구된다():
    class Boom(RecordingClient):
        def create(self, **kw):
            raise RuntimeError("의도된 실패")
    with pytest.raises(RuntimeError):
        grade_with(Boom(), schema_score_first(), rubric_without_4, ITEM, "테스트 시장")
    assert list(V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]) == ["reasoning", "score"]
    assert "- 4점:" in V.PERSPECTIVE_PROMPTS["groundedness"]


def test_운영_프롬프트조립을_거친다():
    """스키마만 확인하면 `grade_fact()` 우회를 못 잡는다 — 변조실험에서 드러난 구멍."""
    cl = RecordingClient()
    grade_with(cl, schema_reasoning_first(), None, ITEM, "테스트 시장")
    want = V.build_grading_prompt(ITEM["text"], ITEM["source_excerpt"], ITEM["topic"],
                                  "테스트 시장", "groundedness", ITEM["region"])
    assert cl.seen[-1]["prompt"] == want


def test_운영_clamp를_거친다():
    score, _ = grade_with(RecordingClient(score=9), schema_reasoning_first(), None, ITEM, "테스트 시장")
    assert score == V.SCORE_MAX
    score, _ = grade_with(RecordingClient(score=0), schema_reasoning_first(), None, ITEM, "테스트 시장")
    assert score == V.SCORE_MIN


# ── 지표 ───────────────────────────────────────────────────────────────────
def test_인용판정_원문수치를_인용하면_참():
    assert cites_source("원문에 2조 원이라고 나온다", "시장은 2조 원 규모다") is True


def test_인용판정_수치를_인용하지_않으면_거짓():
    assert cites_source("대체로 맞는 것 같다", "시장은 2조 원 규모다") is False


def test_인용판정_원문에_수치가_없으면_해당없음():
    """'해당 없음'을 '인용 안 함'으로 세면 조건 간 비교가 왜곡된다."""
    assert cites_source("근거가 있다", "시장이 성장하고 있다") is None


def test_인용판정_단위없는_한자리는_세지_않는다():
    """`그림 3 참고` 의 3은 인용 대상이 아니다. 단위가 붙은 `3개`는 대상이다."""
    assert cites_source("근거 없음", "그림 3 참고") is None
    assert cites_source("근거 없음", "3개 업체가 있다") is False


def test_인용판정_금액표기를_놓치지_않는다():
    """맨숫자만 뽑으면 `2조 원`이 `2`가 되어 필터에 걸린다 — 정작 중요한 값이다."""
    assert cites_source("원문은 2조 원이라고 한다", "시장은 2조 원 규모다") is True
    assert cites_source("규모가 크다", "시장은 2조 원 규모다") is False


def test_목표시장은_기존_맵을_그대로_쓴다():
    """복사하지 않고 참조해야 한다 — 복사하면 한쪽만 고쳐져 어긋난다."""
    from eval.export_dataset import KNOWN
    assert TARGET_MARKETS == {t: m for t, (_, m) in KNOWN.items()}
    assert TARGET_MARKETS["친환경 포장재"] == "유럽 B2B 유통 시장"
    assert TARGET_MARKETS["웨어러블 헬스케어 기기"] == "북미 시니어 건강관리 시장"


def test_구버전_접미사가_붙어도_찾는다():
    assert target_market_for("친환경 포장재 [구버전 2026-07-28]") == "유럽 B2B 유통 시장"


def test_모르는_주제는_조용히_넘기지_않는다():
    """대체값을 쓰면 원 실행과 다른 값으로 채점한 것을 아무도 모른다."""
    with pytest.raises(SystemExit):
        target_market_for("듣도 보도 못한 주제")


def test_4점_문구_두_변형():
    assert set(GRADE_4_VARIANTS) == {"v1", "v2"}
    v1, v2 = GRADE_4_VARIANTS["v1"], GRADE_4_VARIANTS["v2"]
    assert "두 대목" in v1, "v1은 원문 두 대목 합침을 감점한다"
    assert "두 대목" not in v2, "v2는 그 항목을 뺐다 — 프롬프트 전제와 충돌하므로"
    assert "계산해 얻은 값" in v2, "v2는 파생값 구간을 넣었다"
    for v in (v1, v2):
        assert v.lstrip().startswith("- 4점:")


def test_두_변형이_서로_다른_결과를_만든다():
    g = V.PERSPECTIVE_PROMPTS["groundedness"]
    p1 = rubric_with_4_variant(g, "v1")
    p2 = rubric_with_4_variant(g, "v2")
    assert p1 != p2 and p1 != g and p2 != g
    assert all("- 4점:" in x for x in (p1, p2))

# ── 규칙 0 (결함 N 후보) ───────────────────────────────────────────────────
def test_규칙0은_규칙1보다_앞에_온다():
    """지금 기계가 목표시장 서술을 **규칙 1로** 처리해 기각하고 있다.

    예외를 규칙 1보다 뒤에 두면 이미 적용된 규칙을 되돌려야 하는데, Router 결함 J에서
    그 방식이 실패했다(규칙 안에 예외를 삽입해도 90.0%에서 멈췄다).
    """
    p = rubric_with_rule0(V.PERSPECTIVE_PROMPTS["groundedness"])
    assert p.find("■ 규칙 0") < p.find(ANCHOR_R1)


def test_규칙0_왕복이_원문을_복원한다():
    """조건을 절대적으로 정의하려면 넣고 빼는 것이 정확히 역연산이어야 한다."""
    orig = V.PERSPECTIVE_PROMPTS["groundedness"]
    assert rubric_without_rule0(rubric_with_rule0(orig)) == orig


def test_규칙0_중복삽입은_실패한다():
    p = rubric_with_rule0(V.PERSPECTIVE_PROMPTS["groundedness"])
    with pytest.raises(SystemExit):
        rubric_with_rule0(p)


def test_규칙0_없는데_제거하면_실패한다():
    with pytest.raises(SystemExit):
        rubric_without_rule0(V.PERSPECTIVE_PROMPTS["groundedness"])


def test_규칙0이_지역조작_예외를_담는다():
    """`주입된 맥락`과 `fact가 주장하는 지역`의 경계가 애매하다.

    원문이 유럽 얘기인데 fact가 "북미 시장에서"라고 쓴 경우는 **잡아야 한다.**
    예외를 빼면 규칙 0이 지역 조작까지 면제해버린다.
    """
    assert "다른 지역을 말하는데" in RULE0_TEXT
    assert "원문에 없는 **수치**가 붙은 경우" in RULE0_TEXT


def test_규칙0이_감점대상을_명시한다():
    """무엇이 면제되는지만 말하고 무엇이 여전히 필요한지 안 말하면 과잉 면제가 된다."""
    assert "주장하는 내용" in RULE0_TEXT
    for k in ("금액", "연도", "고유명사"):
        assert k in RULE0_TEXT, k


def test_apply_rule0은_운영상태와_무관하게_맞춘다():
    """이미 있으면 넣지 않고, 없으면 넣는다 — 운영에 반영된 뒤에도 조건이 성립해야 한다."""
    orig = V.PERSPECTIVE_PROMPTS["groundedness"]
    on, off = apply_rule0(True), apply_rule0(False)
    assert "■ 규칙 0" in on(orig)
    assert "■ 규칙 0" not in off(orig)
    assert on(on(orig)) == on(orig), "이미 있는데 또 넣으면 안 된다"
    assert off(off(orig)) == off(orig), "없는데 또 빼려 하면 안 된다"


@pytest.mark.parametrize("cond", list(CONDITIONS))
def test_조건별_규칙0_상태가_실제로_전달된다(cond):
    _, reorder, add4, add_r0 = CONDITIONS[cond]
    r0 = apply_rule0(add_r0)
    cl = RecordingClient()
    grade_with(cl, schema_reasoning_first() if reorder else schema_score_first(),
               r0 if add4 else (lambda p: r0(rubric_without_4(p))), ITEM, "테스트 시장")
    assert ("■ 규칙 0" in cl.seen[-1]["prompt"]) is add_r0
    assert ("- 4점:" in cl.seen[-1]["prompt"]) is add4


def test_조건이_여섯개다():
    """D가 현 운영, E가 규칙 0 추가. A~C는 수정 전 상태 재현용."""
    assert set(CONDITIONS) == set("ABCDEF")
    assert CONDITIONS["D"][1:] == (True, True, False), "D는 현 운영이어야 한다"
    assert CONDITIONS["E"][1:] == (True, True, True), "E는 D + 규칙 0"
