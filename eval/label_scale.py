"""관련성 라벨의 분해 척도와 결합 규칙.

## 왜 분해하는가

처음에는 "이 fact가 연구대상·목표시장과 관련 있나"를 한 번에 1~5점으로 물었다.
라벨하는 사람이 "도메인을 모르니 애매한 것이 많았다"고 했고, 타당한 지적이었다 —
그 질문은 지식을 요구한다. `일동후디스 하이뮨`이 케어푸드 회사인지 알아야 답할 수 있다.

두 개로 쪼개면 지식이 아니라 **범위 대조**가 된다.
  ① 이 fact의 주제가 연구대상 범위 안인가?
  ② 이 fact의 지역·대상이 목표시장 범위 안인가?

이것은 오늘 결함 A를 고칠 때 쓴 논리와 같다 — 한 판단에 두 축을 섞으면 흔들린다.
검증기에서 그걸 고쳐놓고 사람 라벨에서 같은 실수를 했다.

## 왜 결합을 코드로 고정하는가

사람 라벨과 상위 모델(Claude) 라벨을 나란히 비교하려면 **같은 규칙으로 환산**해야 한다.
각자 머릿속에서 1~5점을 매기면 척도가 어긋나 비교가 무의미해진다.
"""

from __future__ import annotations

from typing import Literal

Scope = Literal["예", "부분", "아니오"]

# (주제 범위, 지역·대상 범위) → 관련성 점수
#
# 설계 근거는 기존 검증기 루브릭에 맞췄다:
#   5점 = 연구대상·목표시장에 정확히 부합
#   3점 = 부분적으로만 관련(인접 카테고리, 인접 지역)
#   1점 = 전혀 다른 주제/지역/카테고리
#
# "주제는 맞지만 지역이 완전히 다르다"를 2점으로 둔 이유: 그 fact는 다른 시장에 대한
# 서술이므로 이 기획서의 근거가 될 수 없다. 다만 주제까지 다른 1점보다는 낫다
# (같은 산업의 다른 지역 사례는 참고 가치가 조금이라도 있다).
COMBINE: dict[tuple[Scope, Scope], int] = {
    ("예",   "예"):     5,
    ("예",   "부분"):   4,
    ("부분", "예"):     4,
    ("부분", "부분"):   3,
    ("예",   "아니오"): 2,
    ("부분", "아니오"): 2,
    ("아니오", "예"):    2,
    ("아니오", "부분"):  1,
    ("아니오", "아니오"): 1,
}

SCOPE_HELP = {
    "예":    "범위 안에 확실히 들어온다",
    "부분":  "인접하지만 정확히 일치하지는 않는다",
    "아니오": "범위 밖이다",
}


def combine(topic_scope: Scope, market_scope: Scope) -> int:
    """두 범위 판정을 관련성 1~5점으로 환산한다."""
    try:
        return COMBINE[(topic_scope, market_scope)]
    except KeyError as e:
        raise ValueError(f"알 수 없는 범위 조합: {e}") from e


def describe(topic_scope: Scope, market_scope: Scope) -> str:
    return (f"주제 {topic_scope}({SCOPE_HELP[topic_scope]}) · "
            f"지역·대상 {market_scope}({SCOPE_HELP[market_scope]}) → "
            f"관련성 {combine(topic_scope, market_scope)}점")
