"""결함 L·M 수정의 계약 — 루브릭 5단계 완전성과 스키마 필드 순서.

## 결함 L — 루브릭에 등급이 빠져 있었다

채점 루브릭이 열거한 점수가 관련성 `5·3·1`, 근거지지도 `5·3·2·1` 이었다.
**두 축 모두 4점이 없었다.** 무엇인지 알려주지 않은 등급은 모델이 쓸 수 없다.

그런데 `ACCEPT_MIN_SCORE = 4` 다 — **채택 경계가 정의되지 않은 등급에 놓여 있었다.**
모집단 331건에서 채택 162건 중 5점이 156건(96%)이었다. 명목상 경계는 4지만
실질적으로 "5점만 채택"이었다.

그리고 **사람 라벨 척도(`eval/label_scale.py`, `eval/groundedness_scale.py`)에는
4점이 정의돼 있었다.** κ는 그 척도를 기준으로 재는데, 기계는 그 척도의 한 등급을
모르는 상태로 채점했다. 같은 프로젝트 안에서 사람용 척도와 기계용 루브릭이 달랐다.

측정 근거 (`eval/schema_order.py`, 30건 × 3회 × 3실행):
  1·4점 사용률   A 1.5% → C 30.4%   (루브릭 주효과 +23.3%p, 순서 주효과 −1.5%p)
  채택률         A 31.5% → D 59.3%  (사람 56.7%)

## 결함 M — 점수가 근거보다 앞에 있었다

`GRADE_SCHEMA` 가 `score → reasoning` 순서였다. Router의 결함 J·K와 같은 구조다.
확인된 효과는 **채택률(+13.7%p)과 재현성(실행 간 흔들림 11.1%p → 3.3%p)** 이며,
κ·정밀도·재현율은 실행 간 흔들림이 조건 간 차이보다 커서 판정하지 못했다.

## 남은 불일치 (미해결, 문서에 등재)

사람 척도의 `①예 × ②일부 = 4점` 은 근거지지도 규칙 1(*"원문에 없는 수치가 있으면
반드시 2점 이하"*)과 충돌한다. 라벨 30건에서 이 조합 3건은 모두 문자열 누락 0건이라
실측 피해는 없었으나, 정의상 충돌은 남아 있다. 그래서 **운영 4점 정의는 수치 누락이
아니라 조건 누락**으로 썼다 — 규칙 1과 겹치지 않게.
"""

from __future__ import annotations

import re

import pytest

import agents.verification as V
from eval.groundedness_scale import COMBINE as G_COMBINE
from eval.label_scale import COMBINE as R_COMBINE

AXES = ("relevance", "groundedness")


# ── 결함 L ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("axis", AXES)
def test_루브릭이_다섯_등급을_모두_정의한다(axis):
    p = V.PERSPECTIVE_PROMPTS[axis]
    missing = [n for n in "12345" if f"{n}점:" not in p]
    assert not missing, f"{axis} 루브릭에 정의 없는 등급: {missing}점"


@pytest.mark.parametrize("axis", AXES)
def test_채택경계_등급이_정의되어_있다(axis):
    """`ACCEPT_MIN_SCORE` 가 가리키는 등급이 루브릭에 없으면 경계가 작동하지 않는다."""
    assert f"{V.ACCEPT_MIN_SCORE}점:" in V.PERSPECTIVE_PROMPTS[axis]


@pytest.mark.parametrize("axis", AXES)
def test_기각경계_등급이_정의되어_있다(axis):
    assert f"{V.REJECT_MAX_SCORE}점:" in V.PERSPECTIVE_PROMPTS[axis]


@pytest.mark.parametrize("axis", AXES)
def test_등급이_내림차순으로_열거된다(axis):
    """5→4→3→2→1 순서가 아니면 모델이 척도를 잘못 읽을 수 있다."""
    p = V.PERSPECTIVE_PROMPTS[axis]
    pos = [p.find(f"- {n}점:") for n in "54321"]
    assert all(x >= 0 for x in pos), f"목록 형태(- N점:)가 아닌 등급이 있다: {pos}"
    assert pos == sorted(pos), f"{axis} 등급 열거 순서가 내림차순이 아니다"


@pytest.mark.parametrize("axis,combine", [("relevance", R_COMBINE),
                                          ("groundedness", G_COMBINE)])
def test_사람척도가_쓰는_모든_점수가_루브릭에_있다(axis, combine):
    """κ는 사람 척도를 기준으로 잰다. 기계가 모르는 등급이 있으면 정렬도가 구조적으로 깎인다."""
    used = sorted(set(combine.values()))
    p = V.PERSPECTIVE_PROMPTS[axis]
    for s in used:
        assert f"{s}점:" in p, f"사람 척도는 {s}점을 쓰는데 {axis} 루브릭에 정의가 없다"


def test_근거지지도_4점이_규칙1과_겹치지_않는다():
    """규칙 1은 '원문에 없는 수치 → 2점 이하'다.

    4점 정의를 '수치 일부 누락'으로 쓰면 같은 경우를 4점과 2점으로 동시에 지시한다.
    그래서 4점은 **수치는 모두 일치하되 조건을 빠뜨린 경우**로 한정한다.
    """
    p = V.PERSPECTIVE_PROMPTS["groundedness"]
    m = re.search(r"- 4점:(.*?)(?=\n- 3점:)", p, re.S)
    assert m, "4점 정의를 찾지 못했다"
    body = m.group(1)
    assert "모두 원문과 일치" in body, "수치가 전부 일치하는 경우로 한정해야 한다"
    assert "빠뜨" in body, "조건 누락이 4점의 요건이어야 한다"


def test_근거지지도_3점과_4점이_반대방향이다():
    """덧붙이면 3점, 빠뜨리면 4점 — 직교하는 구분이어야 한다."""
    p = V.PERSPECTIVE_PROMPTS["groundedness"]
    four = re.search(r"- 4점:(.*?)(?=\n- 3점:)", p, re.S).group(1)
    three = re.search(r"- 3점:(.*?)(?=\n- 2점:)", p, re.S).group(1)
    assert "덧붙이지도" in four or "빠뜨" in four
    assert "덧붙" in three


def test_관련성_4점이_사람척도_조합과_맞는다():
    """사람 척도의 4점 = (예,부분) / (부분,예) — 한쪽만 정확한 경우다."""
    assert {k for k, v in R_COMBINE.items() if v == 4} == {("예", "부분"), ("부분", "예")}
    four = re.search(r"- 4점:(.*?)(?=\n- 3점:)",
                     V.PERSPECTIVE_PROMPTS["relevance"], re.S).group(1)
    assert "한쪽" in four and "인접" in four


# ── 결함 M ────────────────────────────────────────────────────────────────
def test_스키마는_reasoning이_먼저다():
    sch = V.GRADE_SCHEMA["json_schema"]["schema"]
    assert list(sch["properties"]) == ["reasoning", "score"], \
        "score 가 앞에 오면 모델이 근거를 쓰기 전에 점수를 내놓아야 한다 (결함 M)"


def test_required_순서도_같다():
    """Router에서 required 순서가 생성 순서에 영향을 주는 것이 확인됐다."""
    sch = V.GRADE_SCHEMA["json_schema"]["schema"]
    assert sch["required"] == list(sch["properties"])


def test_점수_설명이_근거를_먼저_보라고_지시한다():
    d = V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]["score"]["description"]
    assert "reasoning" in d, "순서만 바꾸고 지시를 안 넣으면 규칙이 프롬프트에 없는 셈이다"


def test_점수_범위가_스키마에_명시되어_있다():
    """결함 D 회귀 방지 — 범위 밖 점수 한 건이 배치 전체를 흔든 이력이 있다."""
    sc = V.GRADE_SCHEMA["json_schema"]["schema"]["properties"]["score"]
    assert sc["minimum"] == V.SCORE_MIN and sc["maximum"] == V.SCORE_MAX
