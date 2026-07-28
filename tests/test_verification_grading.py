"""채점 루브릭·점수 계약 회귀 테스트 (2026-07-28 judge self-test 후속).

여기서 박제하는 결함 두 개:

결함 B — groundedness 3점 정의가 수치 조작을 서술하고 있었다.
  옛 루브릭: "3점: 원문에 비슷한 내용은 있으나, 원문에 없는 세부사항(구체적 수치,
  조건 등)이 추가되어 다소 확대해석됨"
  G-NG-4(원문의 "증가했다"에 "17.4%"를 붙인 케이스)가 이 정의에 정확히 해당해서
  solar-mini/pro2/pro3 세 모델 전부 3점을 줬다. 모델이 틀린 게 아니라 지시를 정확히
  따른 것이다. 3점은 adaptive threshold의 clamp 하한(3.0)에 걸려 통과할 수 있으므로,
  지어낸 수치가 기획서에 실리는 경로가 코드상 실재했다.

결함 D — GRADE_SCHEMA에 점수 범위 제약이 없었다.
  solar-pro3가 실제로 0점을 반환했다(R-NG-5, [0, 5, 5]). 범위 밖 점수는
  compute_adaptive_threshold()의 평균을 끌어내리고 표준편차를 키워 임계값을 두 방향에서
  낮춘다. 한 건의 계약 위반이 배치 전체를 관대하게 만든다.
"""

import pytest

from agents.verification import (
    GRADE_SCHEMA,
    PERSPECTIVE_PROMPTS,
    SCORE_MAX,
    SCORE_MIN,
    clamp_score,
    compute_adaptive_threshold,
    grade_fact,
)


# ---------------------------------------------------------------- 결함 B
GROUNDEDNESS = PERSPECTIVE_PROMPTS["groundedness"]


def _flat(text: str) -> str:
    """줄바꿈·연속공백을 접어, 여러 줄에 걸친 항목도 한 문자열로 검사할 수 있게 한다."""
    return " ".join(text.split())


FLAT_GROUNDEDNESS = _flat(GROUNDEDNESS)


def test_수치_조작은_2점_이하라는_규칙이_있다():
    assert "2점 이하" in GROUNDEDNESS


def test_두_가지_수치_위반_모두에_강제_표현이_붙어_있다():
    """처음 쓴 테스트는 '2점 이하'가 문서 어딘가에 있는지만 봤다. 그래서 핵심 항목
    (원문이 방향만 말했는데 수치를 붙인 경우 = G-NG-4 유형) 하나만 '감점하세요' 같은
    약한 표현으로 바꿔도 테스트가 통과했다. 변조실험에서 드러난 구멍이다.

    수치 위반은 두 종류다 — ① 없는 값을 만든 경우, ② 원문과 다른 값을 쓴 경우.
    둘 다 강제여야 한다."""
    assert FLAT_GROUNDEDNESS.count("반드시 2점 이하") == 2, (
        "수치 위반 두 종류 모두에 '반드시'가 붙어 있어야 한다"
    )
    # ① 없는 값을 만든 경우 — self-test G-NG-4가 바로 이 유형이다
    assert "구체적인 수치나 시점을 붙였다면, 그 값은 지어낸 것입니다 → 반드시 2점 이하." in FLAT_GROUNDEDNESS
    # ② 원문과 다른 값을 쓴 경우
    assert "원문에 있는 값과 다른 값을 쓴 경우도 → 반드시 2점 이하." in FLAT_GROUNDEDNESS


def test_3점_정의가_더는_수치_추가를_가리키지_않는다():
    """이 테스트가 깨지면 G-NG-4 유형(지어낸 수치)이 다시 3점을 받는다."""
    three = [ln for ln in GROUNDEDNESS.splitlines() if ln.strip().startswith("- 3점")]
    assert len(three) == 1
    assert "구체적 수치" not in three[0]
    assert "수치" not in three[0] or "일치" in three[0]


def test_2점_등급이_루브릭에_존재한다():
    """옛 루브릭은 5/3/1점만 있어 '수치 조작'을 앉힐 칸이 없었다."""
    assert any(ln.strip().startswith("- 2점") for ln in GROUNDEDNESS.splitlines())


def test_그럴듯함은_근거가_아니라고_명시한다():
    """모델이 '업계 상식에 맞는 수치'라며 통과시키는 경로를 막는다."""
    assert "그럴듯하다" in GROUNDEDNESS
    assert "원문 안에 그 값이 있는지만" in GROUNDEDNESS


def test_단위_표기_변환은_감점하지_않는다고_명시한다():
    """NUMCoT가 지적한 단위 환산 문제. 규칙 1이 과잉 적용되면 정상 fact가 죽는다."""
    assert "단위" in GROUNDEDNESS
    assert "감점하지 않습니다" in GROUNDEDNESS


LENIENT = "3점 이상으로 채점하세요"


def test_관대함_지시는_규칙1_뒤에_한_번만_온다():
    """순서가 뒤집히면 '애매하면 관대하게'가 수치 규칙을 무력화한다.

    주의 — 처음 쓴 이 테스트는 결함이 있었다. GROUNDEDNESS.index("규칙 1")로 위치를
    찾았는데, 관대함 문장 자체가 "규칙 1 위반이 아니면서…"라는 말을 포함하고 있어서,
    관대함 문장을 규칙 1 앞으로 옮기는 변조를 넣어도 index가 그 안의 "규칙 1"을 잡아
    테스트가 통과해버렸다. 그래서 섹션 머리표(■)로 앵커를 잡고, 관대함 문장이 한 번만
    등장하는지까지 확인한다.
    """
    assert GROUNDEDNESS.count(LENIENT) == 1, "관대함 지시가 여러 곳에 있으면 순서 보장이 무의미하다"
    idx_rule1 = GROUNDEDNESS.index("■ 규칙 1")
    idx_rule2 = GROUNDEDNESS.index("■ 규칙 2")
    idx_lenient = GROUNDEDNESS.index(LENIENT)
    assert idx_rule1 < idx_rule2 < idx_lenient


# ---------------------------------------------------------------- 결함 D
def test_스키마에_점수_범위가_명시돼_있다():
    props = GRADE_SCHEMA["json_schema"]["schema"]["properties"]
    assert props["score"]["minimum"] == SCORE_MIN
    assert props["score"]["maximum"] == SCORE_MAX


@pytest.mark.parametrize(
    "raw, expected",
    [(0, 1), (-3, 1), (1, 1), (3, 3), (5, 5), (6, 5), (99, 5)],
)
def test_clamp_score가_범위로_강제한다(raw, expected):
    assert clamp_score(raw, "relevance") == expected


@pytest.mark.parametrize("raw", ["4", 4.0, None, True])
def test_clamp_score는_정수가_아니면_최저점으로_처리한다(raw):
    assert clamp_score(raw, "groundedness") == SCORE_MIN


def test_범위_밖_점수_한_건이_배치_임계값을_최저로_끌어내린다():
    """결함 D의 실제 피해를 수치로 박제한다."""
    healthy = [5, 5, 4, 4, 3, 3, 5, 4, 3, 4]
    polluted = healthy[:-1] + [0]
    clamped = healthy[:-1] + [clamp_score(0, "relevance")]

    base = compute_adaptive_threshold(healthy)
    bad = compute_adaptive_threshold(polluted)
    fixed = compute_adaptive_threshold(clamped)

    assert bad == 3.0, "0점 한 건이 임계값을 clamp 하한(가장 관대한 값)까지 끌어내린다"
    assert bad < fixed < base, "clamp가 오염을 완전히 없애진 못하지만 크게 줄인다"
    assert base - bad > 0.5, "피해 규모가 무시할 수 없다는 것을 명시적으로 남긴다"


def test_grade_fact가_범위_밖_응답을_보정한다():
    """스키마가 강제되지 않는 공급자를 만나도 파이프라인이 오염되지 않아야 한다."""

    class _FakeCompletions:
        def create(self, *, model, messages, response_format):
            class _Msg:
                content = '{"score": 0, "reasoning": "범위 밖"}'

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    class _FakeClient:
        chat = type("_Chat", (), {"completions": _FakeCompletions()})()

    score, reason = grade_fact(_FakeClient(), "f", "s", "t", "m", "relevance")
    assert score == SCORE_MIN
    assert reason == "범위 밖"


# ------------------------------------------------- 결함 C: 평가셋과 코드 필터의 경계
# self-test 케이스가 실제로 검증기까지 도달하는지 확인한다. 도달하지 못하는 케이스로
# 검증기를 평가하면, 그 점수는 검증기의 능력과 무관한 숫자가 된다.
#
# 2026-07-28에 실제로 이 일이 있었다. R-NG-5가 "제공된 본문에는 해당 정보가 포함되어
# 있지 않습니다."였는데, 이 문장은 NO_INFO_PATTERNS에 걸려 추출 직후 제거된다.
# 세 모델 전부 이 케이스에서 판정이 흔들렸지만(mini [1,1,5], pro3 [0,5,5]) 그 흔들림은
# 운영에 아무 영향이 없었다. 반대로 말하면, 그 흔들림을 근거로 모델을 판단했다면
# 틀린 결정을 했을 것이다.
from agents.market_research import _is_no_info_statement
from eval.cases_judge import ALL_CASES


def test_평가셋의_모든_fact가_정규식_필터를_통과한다():
    """필터에 걸리는 fact는 검증기를 시험할 수 없으므로 평가셋에 있으면 안 된다."""
    blocked = [
        (c["id"], c["fact"])
        for _, c in ALL_CASES
        if _is_no_info_statement(c["fact"])
    ]
    assert not blocked, (
        "다음 케이스는 추출 단계에서 이미 제거되므로 검증기에 도달하지 못한다: "
        f"{blocked}"
    )


def test_옛_R_NG_5_문장은_정규식으로_걸러진다():
    """교체 이유를 박제한다. 이 필터가 약해지면 메타발언이 fact로 실린다."""
    assert _is_no_info_statement("제공된 본문에는 해당 정보가 포함되어 있지 않습니다.")


def test_새_R_NG_5는_정규식으로_안_걸리므로_LLM이_판단해야_한다():
    new_fact = next(c["fact"] for _, c in ALL_CASES if c["id"] == "R-NG-5")
    assert not _is_no_info_statement(new_fact)
    assert "투자 판단의 근거로 사용될 수 없다" in new_fact


# ------------------------------------------ 2점 등급 남용 방지 (2026-07-28 재측정 후속)
# 결함 B 수정으로 2점 칸을 새로 만들자 solar-mini가 그 칸을 남용했다.
# G-OK-1("EU는 2030년까지 … 의무화한다" — 원문 첫 문장을 거의 그대로 옮긴 fact)에
# 2점을 주면서 근거를 "원본 본문에 나오지 않는 단정적인 표현"이라고 댔다.
# 루브릭상 단정 문제는 3점이고 2점은 수치 위반 전용인데, 약한 모델이 등급을 구분하지
# 못한 것이다. 새 등급을 만들면 그 범위를 좁게 못 박아야 한다는 교훈.
def test_2점은_수치_위반_전용이라고_못박는다():
    assert "2점은 규칙 1 위반" in FLAT_GROUNDEDNESS
    assert "에만 쓰는 등급" in FLAT_GROUNDEDNESS


def test_단정적_표현으로는_2점을_주지_말라고_명시한다():
    """mini가 실제로 낸 오류 유형을 문구로 차단한다."""
    assert "단정적이다" in FLAT_GROUNDEDNESS
    assert "그런 경우는 3점입니다" in FLAT_GROUNDEDNESS


def test_2점_판단_전에_수치_존재를_먼저_확인하라고_지시한다():
    """판단 순서를 지정해, 2점을 기본 후보에서 빼는 효과를 노린다."""
    assert "없다면 2점은 후보에서 제외" in FLAT_GROUNDEDNESS


# --------------------------------- 검증 전용 모델 분리 (2026-07-28 재측정 결론)
# self-test 실측(20케이스 × 3회 × 3모델): solar-pro2 100%/판정뒤집힘 0건,
# solar-mini 85%/3건, solar-pro3 85%/2건. 검증 단계만 pro2로 올리기로 했다.
# 그런데 verification.py가 router.py와 LIGHT_MODEL을 공유하고 있어, 그대로는
# "검증기만 정확한 모델" 이라는 선택이 불가능했다. 전용 변수로 분리한 것을 박제한다.
import importlib


def _reload_verification(monkeypatch, **env):
    import agents.verification as V
    for k in ("VERIFICATION_MODEL", "LIGHT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(V)


def test_아무것도_설정하지_않으면_pro2로_돈다(monkeypatch):
    """기본값이 mini면, 변수를 모르는 서버가 조용히 나쁜 쪽으로 돈다."""
    V = _reload_verification(monkeypatch)
    assert V.VERIFICATION_MODEL == "solar-pro2"


def test_LIGHT_MODEL은_검증_모델에_영향을_주지_않는다(monkeypatch):
    """분리의 핵심. 이게 깨지면 router와 다시 묶여 단계별 선택이 불가능해진다."""
    V = _reload_verification(monkeypatch, LIGHT_MODEL="solar-mini")
    assert V.VERIFICATION_MODEL == "solar-pro2"


def test_VERIFICATION_MODEL로_명시_지정할_수_있다(monkeypatch):
    V = _reload_verification(monkeypatch, VERIFICATION_MODEL="solar-mini",
                             LIGHT_MODEL="solar-pro3")
    assert V.VERIFICATION_MODEL == "solar-mini"


# ------------------------------------------------ 토큰 사용량 계측 (비용 근거 확보용)
# 모델 교체의 비용 영향을 물었을 때 프롬프트 글자 수로 추정할 수밖에 없었다.
# 한국어 토크나이저의 글자당 토큰 수를 모르므로 그 추정은 근거가 약하다.
# API 응답의 usage 필드를 누적하면 추정이 불필요해진다.
class _UsageStub:
    def __init__(self, p, comp):
        self.prompt_tokens, self.completion_tokens = p, comp


def _client_with_usage(usage):
    class _Completions:
        def create(self, *, model, messages, response_format):
            class _Msg:
                content = '{"score": 5, "reasoning": "ok"}'

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            r = _Resp()
            if usage is not None:
                r.usage = usage
            return r

    class _Client:
        chat = type("_C", (), {"completions": _Completions()})()

    return _Client()


@pytest.fixture(autouse=True)
def _clear_usage():
    from agents.verification import TOKEN_USAGE
    TOKEN_USAGE.clear()
    yield
    TOKEN_USAGE.clear()


def test_토큰_사용량이_호출마다_누적된다():
    from agents.verification import TOKEN_USAGE, VERIFICATION_MODEL, grade_fact
    cl = _client_with_usage(_UsageStub(1200, 40))
    for _ in range(3):
        grade_fact(cl, "f", "s", "t", "m", "relevance")
    u = TOKEN_USAGE[VERIFICATION_MODEL]
    assert (u["calls"], u["prompt"], u["completion"]) == (3, 3600, 120)


def test_usage가_없어도_채점은_정상_동작한다():
    """계측은 부가 기능이다. 없다고 파이프라인이 죽으면 안 된다."""
    from agents.verification import TOKEN_USAGE, grade_fact
    score, _ = grade_fact(_client_with_usage(None), "f", "s", "t", "m", "relevance")
    assert score == 5
    assert TOKEN_USAGE == {}


def test_usage_필드가_깨져도_채점은_정상_동작한다():
    from agents.verification import grade_fact

    class _Broken:
        @property
        def prompt_tokens(self):
            raise RuntimeError("공급자가 이상한 값을 줬다")

    score, _ = grade_fact(_client_with_usage(_Broken()), "f", "s", "t", "m", "relevance")
    assert score == 5


def test_보고서_문자열에_호출수와_토큰이_모두_담긴다():
    from agents.verification import VERIFICATION_MODEL, grade_fact, token_usage_report
    grade_fact(_client_with_usage(_UsageStub(1000, 50)), "f", "s", "t", "m", "groundedness")
    r = token_usage_report()
    assert VERIFICATION_MODEL in r and "1회" in r and "1,000" in r and "50" in r


def test_기록이_없으면_보고서가_그_사실을_알린다():
    from agents.verification import token_usage_report
    assert "기록 없음" in token_usage_report()
