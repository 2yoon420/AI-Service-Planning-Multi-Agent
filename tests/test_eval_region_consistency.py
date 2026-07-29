"""평가 도구 간 지역어 목록 일치 회귀 테스트 (2026-07-29).

## 왜 필요한가

지역어 판정이 **두 곳에** 있다.

  · `eval/agreement.REGION_WORDS` — "이 fact 문장에 지역이 드러나는가" (결함 G 규모 집계)
  · `eval/rescore_relevance._TEXT_REGION` — 그 지역어를 정규화된 지역명으로 매핑

두 목록이 어긋나면 **한쪽에는 있고 다른 쪽에는 없는 지역어**가 생긴다. 그러면
재채점 실험의 '불명' 건수가 결함 G 분석의 34건과 달라지고, 두 숫자를 나란히 놓은
보고가 조용히 틀린다.

**실제로 처음 작성 때 어긋났다.** `_TEXT_REGION`이 7개만 매핑해서 '불명'이 38건으로
나왔다(정답 34건). 4건 차이라 눈으로는 이상해 보이지 않았고, 결함 G 분석과 대조해서야
드러났다. 숫자가 그럴듯하게 틀리는 종류의 오류다.

이 프로젝트가 반복해서 겪은 유형과 같다 — **같은 값이 두 곳에 있으면 반드시 어긋난다**
(설계값 레지스터 vs 임의값 전수목록, 프롬프트 절단 길이 vs 저장 절단 길이).
"""

import pytest

from eval.agreement import REGION_WORDS, has_region_word
from eval.rescore_relevance import _TEXT_REGION, region_for


def test_모든_지역어가_정규화_매핑에_있다():
    """REGION_WORDS의 각 단어가 _TEXT_REGION으로 지역명을 얻어야 한다."""
    mapped = {w for w, _ in _TEXT_REGION}
    빠진것 = [w for w in REGION_WORDS if w not in mapped]
    assert not 빠진것, (
        f"REGION_WORDS에는 있으나 _TEXT_REGION에 없는 지역어: {빠진것}\n"
        "이대로 두면 재채점 실험의 '불명' 건수가 결함 G 분석과 어긋난다."
    )


def test_매핑에만_있는_지역어는_없다():
    """반대 방향도 막는다. _TEXT_REGION에만 있으면 has_region_word가 못 잡는다."""
    words = set(REGION_WORDS)
    남는것 = [w for w, _ in _TEXT_REGION if w not in words]
    assert not 남는것, (
        f"_TEXT_REGION에만 있는 지역어: {남는것}\n"
        "has_region_word()가 이 단어를 지역어로 보지 않으므로 매핑에 도달하지 못한다."
    )


@pytest.mark.parametrize("word", REGION_WORDS)
def test_각_지역어가_담긴_문장은_불명이_아니다(word):
    """단어 하나만 넣은 문장으로 실제 경로를 태운다.

    목록 대조만으로는 부족하다 — region_for()의 루프가 실제로 그 단어를 집는지,
    그리고 has_region_word()를 먼저 통과하는지를 함께 확인해야 한다.
    """
    row = {"dataset": "유럽_포장재", "text": f"{word} 시장 규모는 2024년 기준이다."}
    assert has_region_word(row["text"]), f"'{word}'를 지역어로 인식하지 못한다"
    assert region_for(row, "text") is not None, f"'{word}'가 정규화되지 않아 불명이 된다"


def test_지역어가_없는_문장은_불명이다():
    row = {"dataset": "유럽_포장재", "text": "시장 규모는 전년 대비 12% 성장했다."}
    assert not has_region_word(row["text"])
    assert region_for(row, "text") is None


def test_라벨_변형은_데이터셋마다_지역을_준다():
    """변형 A는 데이터셋 이름에서 지역을 부여하므로 불명이 없어야 한다."""
    from eval.rescore_relevance import DATASET_REGION
    for ds in DATASET_REGION:
        row = {"dataset": ds, "text": "지역어가 전혀 없는 문장이다."}
        assert region_for(row, "label") is not None, f"{ds}에 지역이 부여되지 않는다"
