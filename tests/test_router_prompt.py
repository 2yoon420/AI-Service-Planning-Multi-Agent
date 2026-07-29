"""Router 프롬프트 계약 회귀 테스트 (2026-07-29 골든셋이 찾은 결함 2건).

## 무엇이 문제였는가 — 사양이 프롬프트에 없었다

Router 골든셋을 처음 돌려 **사양-프롬프트 불일치 2건**을 찾았다. 두 건 모두 사양이
코드 주석·docstring에만 있고 **모델이 읽는 프롬프트에는 없었다.**

| 결함 | 사양이 있던 곳 | 골든셋 관측 |
|---|---|---|
| 재검색 필요 시 `revise_market_research` 우선 | `graph.py` `pestel_revision_node` 주석 | **20/20 오답** |
| 복수 요청은 하나만 처리하고 나머지는 다음 턴 | `decide_next_action` docstring | **4/5 오답** |

**결함 B와 같은 구조다.** 결함 B는 근거지지도 3점 정의가 수치 조작을 서술해서 세 모델
전부 3점을 준 것이었다 — 모델이 틀린 게 아니라 **지시를 정확히 따른** 것이다.
*"PESTEL에 최신 규제 반영해줘"* 도 옛 규칙 3에 표면적으로 딱 맞았다.

## 왜 pytest로 잡을 수 있는가

**프롬프트는 문자열이므로 계약 검사가 가능하다.** LLM 호출 없이 *"이 규칙이 프롬프트에
들어 있는가"* 를 볼 수 있다. 골든셋(LLM 210회, 15분)은 *"실제로 그렇게 판단하는가"* 를
재고, 이 테스트는 *"그렇게 판단하라고 말했는가"* 를 지킨다.

둘 다 필요하다 — 말했는데 안 하는 것과, 말하지도 않은 것은 다른 문제다.
**이번 결함은 후자였고, 골든셋 없이는 어느 쪽인지 몰랐다.**

## 한계

프롬프트에 규칙이 있다는 것이 모델이 지킨다는 뜻은 아니다. 이 테스트가 통과해도
골든셋을 다시 돌려야 한다.
"""

import re

import pytest

from agents.router import ROUTER_DECISION_SCHEMA, _router_decision_prompt


def _prompt(msg: str = "테스트 발화", rc: int = 0) -> str:
    return _router_decision_prompt(msg, rc)


def _flat(s: str) -> str:
    """줄바꿈·연속공백을 접어 여러 줄에 걸친 규칙도 한 문자열로 검사한다."""
    return " ".join(s.split())


# ── 결함 ① 재검색 필요 시 research 우선
def test_규칙3에_재검색_예외가_있다():
    """`pestel_revision_node`가 선언한 사양이 프롬프트에 전달되는가.

    코드 주석: "재검색이 필요한 요청이면 Router가 revise_market_research로 먼저
    보내야 한다." 이 문장이 프롬프트에 없어서 골든셋 20/20이 틀렸다.
    """
    p = _flat(_prompt())
    assert "revise_market_research" in p
    assert "PESTEL 얘기라도" in p, "PESTEL이어도 research로 보내라는 예외가 없다"


def test_재검색_예외에_판단_단서가_있다():
    """규칙만 있고 단서가 없으면 모델이 적용 시점을 모른다.

    '새 검색이 필요한 요청'을 어떻게 알아보는지 예시로 준다.
    """
    p = _flat(_prompt())
    단서 = ["최신 자료를 찾아서", "새로 생긴 규정", "최근 동향"]
    누락 = [k for k in 단서 if k not in p]
    assert not 누락, f"재검색 판단 단서가 빠졌다: {누락}"


def test_재검색_예외가_규칙3_안에_붙어_있다():
    """변조실험이 뚫은 구멍 — 예외 표식만 바꿔도 테스트가 통과했다.

    처음에는 `"PESTEL 얘기라도"` 같은 개별 문구만 검사했다. 그런데 `★ 단,` 을
    `※ 삭제됨` 으로 바꾸는 변조가 통과했다 — 뒤 문장이 그대로 남아 키워드 검사를
    다 만족했기 때문이다. **문구는 있는데 예외로 읽히지 않는 상태**다.

    모델은 문장 구조를 보고 읽으므로, 규칙 3 블록 안에서 **예외임이 드러나야** 한다.
    규칙 3 시작부터 규칙 4 시작까지를 잘라내 그 안에 예외 표식과 대상 action이 함께
    있는지 본다.
    """
    p = _prompt()
    assert "3. PESTEL/환경분석" in p and "4. 경쟁사 정보를" in p
    규칙3 = p.split("3. PESTEL/환경분석")[1].split("4. 경쟁사 정보를")[0]
    flat = _flat(규칙3)
    assert "단," in flat, "규칙 3 안에 예외 표식('단,')이 없다 — 예외로 읽히지 않는다"
    assert "revise_market_research" in flat, "규칙 3 안에 대상 action이 없다"
    assert flat.index("단,") < flat.index("revise_market_research"), \
        "예외 표식이 대상 action보다 뒤에 있다 — 조건절 구조가 아니다"


def test_재검색_예외에_피해가_적혀_있다():
    """왜 그래야 하는지를 함께 준다.

    이 프로젝트가 프롬프트를 쓸 때 지켜온 방식이다 — 규칙만 주지 않고 어기면 무엇이
    잘못되는지 알려준다(결함 B 수정에서 '2점은 수치 위반 전용'을 명시한 것과 같은 원리).
    """
    p = _flat(_prompt())
    assert "재작업 한도" in p, "규칙을 어기면 무엇이 잘못되는지가 없다"


# ── 결함 ② 복수 요청 처리
def test_규칙7_복수_요청_지침이_있다():
    """`decide_next_action` docstring의 사양이 프롬프트에 전달되는가.

    docstring: "여러 요청이 섞여 있으면 이번엔 하나만 처리하고, reasoning에 그 취지를
    남겨 다음 턴에 나머지를 처리하도록 유도한다." 이것이 프롬프트에 없어서
    "경쟁사랑 시장 규모 둘 다 다시 봐주세요"가 4/5회 unclear로 갔다.
    """
    p = _flat(_prompt())
    assert "여러 요청이 한 문장에 섞여" in p, "복수 요청 처리 지침이 없다"
    assert "다음 턴에" in p, "나머지를 다음 턴에 처리하라는 안내가 없다"


def test_복수_요청은_unclear가_아니라고_명시한다():
    """가장 중요한 문장이다.

    모델이 둘 중 하나를 못 고르면 unclear로 도망간다. 그것을 명시적으로 막아야 한다.
    사용자는 이미 구체적으로 말했으므로 되물으면 같은 말을 반복하게 만든다.
    """
    p = _flat(_prompt())
    assert "unclear로 되묻지 마세요" in p or "unclear로 되묻지" in p, \
        "복수 요청에서 unclear를 쓰지 말라는 금지가 없다"


def test_unclear의_적용_범위가_좁혀졌다():
    """unclear를 '무엇을 원하는지 알 수 없을 때'로 한정한다.

    범위를 좁히지 않으면 규칙 6(애매하면 unclear)과 규칙 7이 충돌해 모델이 규칙 6으로
    도망간다.
    """
    p = _flat(_prompt())
    assert "무엇을 원하는지 알 수 없을 때" in p, "unclear 적용 범위 한정이 없다"


# ── 기존 규칙이 깨지지 않았는지 (결함 B 수정의 부작용 전례)
@pytest.mark.parametrize("keyword", [
    "action=approve", "action=revise_market_research", "action=revise_pestel",
    "action=revise_competitor", "action=capability_question", "action=unclear",
])
def test_여섯_action이_모두_프롬프트에_남아_있다(keyword):
    """규칙을 추가하다 기존 것을 지우는 사고를 막는다.

    결함 B 수정이 부작용(2점 칸 남용)을 만든 전례가 있다 — 한 규칙을 고치면 다른
    규칙의 동작이 바뀔 수 있으므로, 최소한 존재는 지킨다.
    """
    assert keyword in _flat(_prompt())


def test_넘겨짚기_금지가_남아_있다():
    """모호 층 100%를 만든 문장이다. 규칙 7을 넣으면서 이것이 약해지면 안 된다."""
    p = _flat(_prompt())
    assert "대충 짐작해서 다른 action을 고르지 마세요" in p
    assert "되묻는 편이 훨씬 낫습니다" in p


def test_스키마_enum과_프롬프트_action이_일치한다():
    """스키마에 있는 action이 프롬프트에 설명돼 있어야 한다.

    한쪽만 고치면 모델이 고를 수 있는데 설명을 못 들은 action이 생긴다.
    """
    enum = ROUTER_DECISION_SCHEMA["json_schema"]["schema"]["properties"]["action"]["enum"]
    p = _flat(_prompt())
    누락 = [a for a in enum if f"action={a}" not in p]
    assert not 누락, f"스키마에 있으나 프롬프트에 설명이 없는 action: {누락}"


def test_revision_count가_판단_규칙에_쓰이지_않는다():
    """규칙 C — 상한 처리는 router_node가 LLM 호출 전에 한다.

    프롬프트에 값이 표시되지만 판단 규칙 1~7에서 그 값을 조건으로 쓰면 누출이다.
    골든셋 실측에서 누출 0/4건이었고, 그 상태를 지킨다.
    """
    p = _prompt("아무 말", rc=4)
    assert "재작업 횟수: 4회" in p, "값은 표시된다(사용자 안내 목적)"
    규칙부 = p.split("판단 규칙(반드시 지킬 것):")[1]
    assert "재작업 횟수" not in 규칙부, "판단 규칙이 revision_count를 조건으로 쓴다"
    assert "4회" not in 규칙부.replace("상한 5회", ""), "판단 규칙에 회차 조건이 있다"

# ── 스키마 필드 순서 (2026-07-29, premature serialization 대응)
SCHEMA = ROUTER_DECISION_SCHEMA["json_schema"]["schema"]


def test_reasoning이_action보다_앞에_있다():
    """구조화 출력은 스키마 순서대로 토큰을 생성한다.

    `action`이 먼저 오면 모델은 **근거를 한 글자도 쓰기 전에 답을 확정**한다.
    연구가 premature serialization이라 부르는 현상이며(arXiv:2606.09410),
    *"reasoning이 답보다 앞서면 chain-of-thought가 작동하고, 답이 먼저 오면
    zero-shot이 된다"* 고 정리돼 있다.

    골든셋 실측이 이것을 확증했다 — 예외 규칙을 프롬프트에 넣어도 B-A 케이스가
    20/20 오답이었고, 규칙을 강화하자 흔들림만 생겼다(pest×4/mres×1).
    **규칙이 읽히기는 하지만 이기지 못하는 상태**였다.
    """
    props = list(SCHEMA["properties"])
    assert props.index("reasoning") < props.index("action"), (
        f"reasoning이 action보다 뒤에 있다: {props}. "
        "이 순서면 모델이 근거 없이 답을 먼저 확정한다."
    )


def test_needs_new_search가_맨_앞에_있다():
    """판단을 두 단계로 쪼갠다.

    모델이 '검색이 필요한가'를 먼저 확정해 써놓으면, 그다음 revise_pestel을 고르기가
    어려워진다 — 자기가 방금 쓴 것과 모순되기 때문이다.
    """
    props = list(SCHEMA["properties"])
    assert props[0] == "needs_new_search", f"첫 필드가 아니다: {props}"


def test_required_순서가_properties와_같다():
    """required 순서도 생성 순서에 영향을 준다. 둘이 어긋나면 의도한 순서가 깨진다."""
    assert list(SCHEMA["properties"]) == SCHEMA["required"], (
        f"properties {list(SCHEMA['properties'])} != required {SCHEMA['required']}"
    )


def test_needs_new_search가_required에_있다():
    """required에 없으면 모델이 생략할 수 있고, 그러면 순서 효과가 사라진다."""
    assert "needs_new_search" in SCHEMA["required"]
    assert SCHEMA["properties"]["needs_new_search"]["type"] == "boolean"


def test_needs_new_search_설명에_판단_단서와_이유가_있다():
    """규칙만 주면 적용 시점을 모른다. 단서와 어기면 무엇이 잘못되는지를 함께 준다."""
    d = SCHEMA["properties"]["needs_new_search"]["description"]
    단서 = ["찾아서", "조사해서", "최신", "새로 생긴"]
    누락 = [k for k in 단서 if k not in d]
    assert not 누락, f"판단 단서가 빠졌다: {누락}"
    assert "revise_pestel" in d, "이 값이 어느 action과 충돌하는지가 없다"
    assert "action을 정하기 전에" in d, "순서 지시가 없다"
    # 변조실험이 두 번 뚫은 구멍이다.
    #
    #   1차 시도 — 단순 포함 검사(`"revise_pestel" in d`)는 연결어를 지워도 통과했다.
    #   2차 시도 — 문장 단위로 쪼개 검사했더니 **여전히 통과**했다. 같은 문장에
    #             "PESTEL 재실행(revise_pestel)은…"이 앞서 나와 revise_pestel이
    #             이미 포함돼 있었기 때문이다.
    #
    # 필요한 것은 **조건 → 대상**의 인접 구조다. `true` 다음에 조건 연결어가 오고
    # 그 직후에 `revise_pestel`이 와야 모델이 "true면 이걸 고르지 마라"로 읽는다.
    조건구조 = re.search(
        r"true\s*(?:인데|이면|일 때|라면)[^.]{0,15}revise_pestel", d)
    assert 조건구조, (
        "'true'와 'revise_pestel'이 조건절로 붙어 있지 않다. "
        "둘 다 문장에 있어도 조건 구조가 아니면 규칙으로 읽히지 않는다.\n"
        f"description: {d!r}"
    )


def test_reasoning_설명이_action보다_먼저_정리하라고_지시한다():
    """필드 순서만 바꿔도 모델이 습관적으로 답을 먼저 정할 수 있다.

    description으로 순서를 한 번 더 못 박는다 — capability_qa 버그에서 배운
    '스키마 description만 믿지 말고 중복 기재한다'의 역방향 적용이다.
    """
    d = SCHEMA["properties"]["reasoning"]["description"]
    assert "action을 정하기 전에" in d, "reasoning을 먼저 쓰라는 지시가 없다"
    assert "needs_new_search" in d, "앞 필드를 근거로 쓰라는 연결이 없다"
