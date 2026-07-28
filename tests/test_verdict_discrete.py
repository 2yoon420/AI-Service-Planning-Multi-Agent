"""판정 경계 이산 규칙 회귀 테스트 (2026-07-29 clamp 전환).

## 이 파일이 왜 필요했는가 — 216개가 통과한 것이 경고였다

판정 규칙을 배치 기반 적응형 임계값에서 이산 규칙으로 **근본적으로 바꿨는데
기존 테스트 216개가 전부 통과했다.** 깨진 것이 하나도 없었다.

이는 좋은 신호가 아니다. 운영 경로의 판정 경계를 검사하는 테스트가 애초에 없었다는
뜻이다. `compute_adaptive_threshold()`를 직접 부르는 테스트는 있었지만, 그 함수가
실제 판정에 쓰이는지는 아무도 검사하지 않았다.

이 프로젝트가 같은 유형의 실수를 겪은 것이 이번이 네 번째다.

    1·2·3회차 (검증 총정리 5절 변조실험)
        "함수를 고쳤는지만 확인하고, 그 함수가 실제로 호출되는지는 검사하지 않았다"
        — 결함 F(decode_html), 결함 G(region 저장)에서 두 번, 그리고 그 진단 자체에서.
    4회차 (이 파일)
        판정 함수를 통째로 교체했는데 테스트가 침묵했다.

그래서 이 파일은 두 층으로 짠다.

    ① 계약 테스트 — classify_score()가 규칙대로 판정하는가
    ② 배선 테스트 — verify_fact()가 정말로 그 규칙을 타는가 (①만으로는 부족하다)

## 판정 규칙과 근거

    채택 ≥ 4 / 애매 = 3 / 기각 ≤ 2

근거는 agents/verification.py의 classify_score() 위 주석에 전부 적혀 있다. 요약하면
① 루브릭 정합성(3점="부분적으로만 관련"에 통과 도장은 자기모순) ② 사람 라벨 실측
(검증기 3점 30건이 사람 기준 채택 15 / 기각 13으로 갈림) ③ 민감도 실측(clamp 하한이
6.1~24.6%p로 최위험) ④ Chow(1970) reject option — 단 ④는 구조만 지지하며 경계값
4/2 자체는 지지하지 않는다.
"""

import inspect

import pytest

from agents.verification import (
    ACCEPT_MIN_SCORE,
    REJECT_MAX_SCORE,
    SCORE_MAX,
    SCORE_MIN,
    classify_score,
    compute_adaptive_threshold,
    verify_fact,
)
from fact_store.schema import VerificationStatus


# ------------------------------------------------------------------ ① 계약
@pytest.mark.parametrize("score,expected", [
    (5, VerificationStatus.ACCEPTED),
    (4, VerificationStatus.ACCEPTED),
    (3, VerificationStatus.AMBIGUOUS),
    (2, VerificationStatus.REJECTED),
    (1, VerificationStatus.REJECTED),
])
def test_이산_규칙이_점수를_판정으로_옮긴다(score, expected):
    assert classify_score(score) == expected


def test_3점은_채택도_기각도_아니다():
    """이 프로젝트의 핵심 결론을 박제한다.

    사람 라벨 70건 중 검증기가 3점을 준 30건은 채택 15 / 기각 13으로 갈렸다.
    자동 채택하면 43%가 잘못 실리고 자동 기각하면 50%를 잃는다. 어느 쪽으로도
    자동 처리할 수 없다는 것이 `애매`가 존재하는 이유다.
    """
    assert classify_score(3) is VerificationStatus.AMBIGUOUS
    assert classify_score(3) is not VerificationStatus.ACCEPTED, (
        "3점을 채택하면 사람 라벨 기준 43%가 잘못 실린다"
    )
    assert classify_score(3) is not VerificationStatus.REJECTED, (
        "3점을 기각하면 사람 라벨 기준 50%를 잃는다"
    )


def test_경계값_상수가_루브릭과_어긋나지_않는다():
    """경계를 흔들면 루브릭 정의와의 연결이 끊긴다.

    4점="직접 관련", 3점="부분적으로만 관련", 2점="무관/규칙 위반"이라는 루브릭 정의에서
    경계가 도출됐다. 상수만 조용히 바꾸면 그 연역이 깨지므로 값 자체를 박제한다.
    """
    assert ACCEPT_MIN_SCORE == 4
    assert REJECT_MAX_SCORE == 2
    assert REJECT_MAX_SCORE + 1 < ACCEPT_MIN_SCORE, (
        "애매 구간이 비면 3단계 판정이 2단계로 퇴화한다"
    )
    assert SCORE_MIN <= REJECT_MAX_SCORE < ACCEPT_MIN_SCORE <= SCORE_MAX


def test_판정은_배치_구성에_의존하지_않는다():
    """이산 규칙 전환의 핵심 이득 — 재현성.

    이전 규칙에서는 같은 점수 3점이 배치 분포에 따라 채택되기도 하고 애매가 되기도 했다.
    같은 fact가 어느 검색 회차에 걸렸는지에 따라 판정이 달라졌다는 뜻이다.
    """
    관대한_배치 = [1, 1, 1, 3]      # 평균이 낮아 이전 규칙이라면 임계값이 하한으로 내려감
    엄격한_배치 = [5, 5, 5, 3]      # 평균이 높아 임계값이 올라감
    assert compute_adaptive_threshold(관대한_배치) != compute_adaptive_threshold(엄격한_배치), (
        "이전 규칙에서는 두 배치의 임계값이 실제로 달랐다 — 이 전제가 성립해야 시험이 의미가 있다"
    )
    # 그런데 이산 규칙에서는 3점의 판정이 배치와 무관하게 같다.
    assert classify_score(3) == classify_score(3)
    for batch in (관대한_배치, 엄격한_배치):
        판정들 = [classify_score(s) for s in batch]
        assert 판정들[-1] is VerificationStatus.AMBIGUOUS


def test_범위_밖_점수는_배치를_오염시키지_못한다():
    """결함 D의 전파 경로가 원리적으로 사라졌음을 박제한다.

    결함 D는 "범위 밖 점수 한 건이 배치 평균을 끌어내려 나머지 전체를 관대하게 만든다"는
    문제였다. 판정이 배치 분포를 보지 않으므로 그 통로가 없다. clamp_score()는 여전히
    필요하지만(그 fact 하나의 판정은 여전히 망가진다), 전파는 불가능하다.
    """
    정상 = [5, 5, 4, 4, 3]
    오염 = [0, 5, 5, 4, 4, 3]           # 0점 한 건이 섞였다
    # 이전 규칙이라면 임계값이 달라졌다 (이 전제가 결함 D의 실체였다)
    assert compute_adaptive_threshold(정상) != compute_adaptive_threshold(오염)
    # 이산 규칙에서는 정상 점수들의 판정이 0점 유입과 무관하게 동일하다
    assert [classify_score(s) for s in 정상] == [classify_score(s) for s in 오염[1:]]


# ------------------------------------------------------------------ ② 배선
def test_verify_fact이_threshold_인자를_받지_않는다():
    """조용히 무시되는 인자를 남기지 않았음을 확인한다.

    이산 규칙 전환으로 threshold가 쓰이지 않게 됐는데, 인자를 남겨두고 무시하면
    호출부는 자기가 넘긴 값이 반영된다고 믿는다. 제거해서 옛 호출부가 TypeError로
    즉시 드러나게 했다. 이 시험은 그 결정이 되돌려지지 않았는지 지킨다.
    """
    params = list(inspect.signature(verify_fact).parameters)
    assert "threshold" not in params, (
        "threshold 인자가 되살아났다 — 무시되는 인자는 배선 버그의 씨앗이다"
    )


@pytest.mark.parametrize("rel,grd,expected", [
    (5, 5, VerificationStatus.ACCEPTED),    # 둘 다 높음
    (5, 3, VerificationStatus.AMBIGUOUS),   # min=3 → 애매 (관련성이 근거를 메워주지 못한다)
    (3, 5, VerificationStatus.AMBIGUOUS),   # 대칭 확인
    (5, 2, VerificationStatus.REJECTED),    # min=2 → 기각
    (4, 4, VerificationStatus.ACCEPTED),    # 경계 바로 위
])
def test_실제_판정_경로가_이산_규칙을_탄다(monkeypatch, rel, grd, expected):
    """배선 테스트 — verify_fact()가 정말로 classify_score()를 거치는가.

    ①의 계약 테스트만으로는 부족하다. classify_score()가 완벽해도 verify_fact()가
    그것을 부르지 않으면 운영에서는 아무 효과가 없다. 이 프로젝트는 정확히 그 실수를
    세 번 겪었으므로(결함 F·G), 실제 함수를 호출해 결과를 본다.

    min 결합도 함께 검사한다 — 비보상적 결합(한 축의 미달을 다른 축이 메우지 못함)이
    유지되는지가 판정 의미의 절반이다.
    """
    import agents.verification as M

    class _Fact:
        def __init__(self):
            self.text = "유럽 친환경 포장재 시장은 2024년 116억 USD 규모였다"
            self.region = "유럽"
            self.verification_score = None
            self.verification_status = None
            self.verification_reasoning = None
            self.citation_verified = None
            self.needs_source_check = None

    calls = {"n": 0}

    def _fake_grade(client, text, source_content, topic, target_market, perspective, region=None):
        calls["n"] += 1
        return (rel if perspective == "relevance" else grd), f"{perspective} 채점"

    monkeypatch.setattr(M, "grade_fact", _fake_grade)
    monkeypatch.setattr(M, "prescreen_fact", lambda text, src: None)

    fact = M.verify_fact(
        client=None, fact=_Fact(),
        source_content="유럽 친환경 포장재 시장은 2024년 116억 USD 규모였다",
        topic="친환경 포장재", target_market="유럽 B2B 유통 시장",
    )

    assert calls["n"] == 2, "두 관점을 각각 채점해야 한다"
    assert fact.verification_score == min(rel, grd), "결합은 min이어야 한다(비보상적)"
    assert fact.verification_status == expected
    assert fact.citation_verified is (expected is VerificationStatus.ACCEPTED)
    assert fact.needs_source_check is (expected is not VerificationStatus.ACCEPTED)


def test_배치_경로도_같은_규칙을_탄다(monkeypatch):
    """verify_facts_batch()의 판정이 verify_fact()와 일치하는지 확인한다.

    이전 구현은 두 함수에 같은 비교식이 중복돼 있었다. 한쪽만 고치면 경로에 따라
    판정이 달라지는데, 그런 불일치는 로그를 봐도 드러나지 않는다.
    """
    import agents.verification as M

    class _Fact:
        def __init__(self, text):
            self.id = text
            self.text = text
            self.region = "유럽"
            self.verification_score = None
            self.verification_status = None
            self.verification_reasoning = None
            self.citation_verified = None
            self.needs_source_check = None

    점수표 = {"a": (5, 5), "b": (5, 3), "c": (1, 5)}   # min = 5, 3, 1 → 채택/애매/기각

    def _fake_grade(client, text, source_content, topic, target_market, perspective, region=None):
        rel, grd = 점수표[text]
        return (rel if perspective == "relevance" else grd), "채점"

    saved = []
    monkeypatch.setattr(M, "grade_fact", _fake_grade)
    monkeypatch.setattr(M, "prescreen_fact", lambda text, src: None)
    monkeypatch.setattr(M, "save_fact", lambda f: saved.append(f))

    counts = M.verify_facts_batch(
        client=None,
        facts_with_content=[(_Fact(k), "원문") for k in 점수표],
        topic="친환경 포장재", target_market="유럽 B2B 유통 시장",
    )

    assert counts == {"accepted": 1, "ambiguous": 1, "rejected": 1}, (
        "배치 경로의 판정이 이산 규칙과 어긋난다"
    )
    상태 = {f.text: f.verification_status for f in saved}
    assert 상태["a"] is VerificationStatus.ACCEPTED
    assert 상태["b"] is VerificationStatus.AMBIGUOUS
    assert 상태["c"] is VerificationStatus.REJECTED


def test_배치_판정이_단건_판정과_일치한다(monkeypatch):
    """같은 점수 조합을 두 경로에 넣어 결과가 같은지 대조한다."""
    import agents.verification as M
    for combined in (1, 2, 3, 4, 5):
        assert M.classify_score(combined) is M.classify_score(combined)
    # 두 경로가 같은 함수를 참조하는지 소스 수준에서도 확인한다
    src_single = inspect.getsource(M.verify_fact)
    src_batch = inspect.getsource(M.verify_facts_batch)
    assert "classify_score(" in src_single, "단건 경로가 classify_score를 부르지 않는다"
    assert "classify_score(" in src_batch, "배치 경로가 classify_score를 부르지 않는다"
    for stale in (">= threshold", "<= threshold - 2", "compute_adaptive_threshold("):
        assert stale not in src_single, f"단건 경로에 옛 판정식이 남아 있다: {stale}"
        assert stale not in src_batch, f"배치 경로에 옛 판정식이 남아 있다: {stale}"
