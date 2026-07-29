"""근거지지도 라벨 척도·표본·UI 생성의 회귀 테스트.

## 무엇을 지키려는 테스트인가

이 라벨셋은 사람이 한 시간을 들여 만든다. 척도나 표본이 조용히 어긋나면 그 한 시간이
버려진다. 그래서 "돌아가는가"가 아니라 **"어긋나면 깨지는가"** 를 검사한다.

특히 세 가지를 못 뚫리게 한다.
  ① 판정 경계가 운영 코드와 어긋남 (라벨 점수를 운영과 다른 규칙으로 환산)
  ② 기계 점수가 라벨링 화면에 새어 나감 (앵커링 → 정렬도 측정 무효)
  ③ 후보 추출기가 잘린 문자열·맥락 서술어를 후보로 올림 (사람 시간 낭비)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from eval.build_groundedness_sample import (
    GENERIC_TOKENS, check_tokens, extract_tokens, near_hits, norm,
)
from eval.build_groundedness_ui import prefill_numeric, strip_machine
from eval.groundedness_scale import (
    ACCEPT_MIN_SCORE, CLAIM_HELP, COMBINE, NUMERIC_HELP, REJECT_MAX_SCORE,
    combine, status_of,
)

CLAIMS = ["예", "부분", "아니오"]
NUMERICS = ["있음", "일부", "없음", "해당없음"]


# ── ① 척도 ────────────────────────────────────────────────────────────────
def test_combine_전조합_존재():
    for c in CLAIMS:
        for n in NUMERICS:
            assert (c, n) in COMBINE, f"{c}×{n} 누락"
    assert len(COMBINE) == 12


def test_combine_점수범위():
    assert all(1 <= v <= 5 for v in COMBINE.values())


def test_판정경계가_운영코드와_같다():
    """라벨 환산이 운영 판정과 다른 규칙을 쓰면 정렬도 비교가 무의미해진다."""
    from agents.verification import ACCEPT_MIN_SCORE as OPS_ACCEPT
    from agents.verification import REJECT_MAX_SCORE as OPS_REJECT
    assert ACCEPT_MIN_SCORE == OPS_ACCEPT
    assert REJECT_MAX_SCORE == OPS_REJECT


def test_수치조작은_기각이다():
    """`①예 ②없음` — 주장은 원문에 있고 수치만 조작된 유형.

    관측된 환각의 주 유형이다(G-NG-1·2·4). 이것이 보류(3점)로 새면 기획서에 들어간다.
    """
    assert combine("예", "없음") <= REJECT_MAX_SCORE
    assert status_of(combine("예", "없음")) == "기각"


def test_주장이_없으면_수치와_무관하게_최저점():
    for n in NUMERICS:
        assert combine("아니오", n) == 1


def test_수치없는_fact는_주장만으로_채택가능():
    """`해당없음`이 없으면 수치 없는 fact가 부당하게 기각된다."""
    assert status_of(combine("예", "해당없음")) == "채택"


def test_부분_일부는_보류():
    assert status_of(combine("부분", "일부")) == "보류"


def test_모르는_조합은_예외():
    with pytest.raises(ValueError):
        combine("아마도", "있음")  # type: ignore[arg-type]


def test_도움말이_모든_선택지를_덮는다():
    assert set(CLAIM_HELP) == set(CLAIMS)
    assert set(NUMERIC_HELP) == set(NUMERICS)


# ── ② 후보 추출 ────────────────────────────────────────────────────────────
def test_수치를_뽑는다():
    t = extract_tokens("2023년 매출은 1,200억 원으로 35.7% 증가했다")
    assert any("2023" in x for x in t)
    assert any("1,200" in x for x in t)
    assert any("35.7" in x for x in t)


def test_잘린_조직명을_뽑지_않는다():
    """`룩셈부르크` → `룩셈부` 버그. 1글자 접미사를 뺀 것이 이 테스트로 고정된다."""
    t = extract_tokens("아르다그 그룹 SA(룩셈부르크)는 유럽에서 활동한다")
    assert "룩셈부" not in t
    assert not any(x.endswith("부") and len(x) <= 4 for x in t), t


def test_일반약어를_뽑지_않는다():
    t = extract_tokens("Amcor plc는 B2B 시장에서 활동한다")
    low = {norm(x).lower() for x in t}
    assert "b2b" not in low
    assert "plc" not in low
    assert any("Amcor" in x for x in t), t


def test_맥락서술어를_뽑지_않는다():
    """주제·리서치 질문에 이미 있는 말은 출처가 주장한 내용이 아니다."""
    ctx = "시니어 케어푸드 한국 시니어 케어푸드 시장 규모는?"
    t = extract_tokens("현대그린푸드는 한국 시니어 케어푸드 시장에서 성장했다", ctx)
    assert "케어푸드" not in t, t


def test_월단독은_뽑지_않는다():
    t = extract_tokens("2025년 6월에 협약했다")
    assert not any(norm(x) == "6월" for x in t), t


def test_두자리_월도_뽑지_않는다():
    """`12월` → `12` 가 후보로 새던 문제.

    변조실험에서 `MONTH_ONLY` 검사를 지워도 테스트가 통과해 **죽은 코드**임이 드러났다.
    단위 목록에서 `월`을 빼는 방식으로 막으려 했는데, 그러면 `12월`이 `12`로 잡히고
    한 자리 숫자 필터를 통과한다. 방어를 두 겹 겹쳐 놓고 한 겹이 다른 겹을 무력화한 경우다.
    """
    t = extract_tokens("2024년 12월 출시했다")
    assert not any(norm(x) in ("12", "12월") for x in t), t
    assert any("2024" in x for x in t), t


def test_MONTH_ONLY가_실제로_발동한다():
    """죽은 코드 재발 방지 — 검사가 존재하는 것과 작동하는 것은 다르다."""
    from eval.build_groundedness_sample import MONTH_ONLY, NUM_PAT
    raw = [m.group(0) for m in NUM_PAT.finditer("2024년 12월 출시")]
    assert any(MONTH_ONLY.match(norm(x)) for x in raw), \
        f"MONTH_ONLY가 어떤 토큰에도 걸리지 않는다(죽은 코드): {raw}"


def test_일_단위는_유지된다():
    """`30일`은 기간·기한 서술로 대조 가치가 있다."""
    t = extract_tokens("2025년 6월 30일 기준")
    assert any("30일" in x for x in t), t


def test_단위없는_한자리숫자는_뽑지_않는다():
    """`Top 5`의 `5`처럼 단위 없는 한 자리 숫자는 대조 가치가 없다.

    ## 이 테스트를 다시 쓴 이유

    처음에는 이렇게 짰다.

        assert extract_tokens(...) == [] or all(... for ...)

    앞 절이 거짓이면 뒤 절이 **항상 참**이 되는 형태여서, 필터를 지워도 통과했다.
    변조실험이 잡았다. 44절에서 "통과하는 테스트가 아니라 깨질 때 깨지는 테스트"라고
    적어둔 것을 그 문서를 쓴 사람이 위반했다.
    """
    t = extract_tokens("Top 5 브랜드 비교")
    assert not any(norm(x) == "5" for x in t), t


def test_단위붙은_숫자는_뽑는다():
    """`5개`는 실제 주장이므로 남겨야 한다 — 필터가 과하면 환각을 놓친다."""
    t = extract_tokens("상위 5개 업체가 점유했다")
    assert any(norm(x) == "5개" for x in t), t


def test_중복후보를_한번만():
    t = extract_tokens("2023년과 2023년을 비교하면")
    assert len([x for x in t if "2023" in x]) == 1


def test_verbatim_대조가_표기차이를_흡수():
    """`2조 5,000억`과 `2조5000억`은 같은 것으로 본다."""
    r = check_tokens(["2조 5,000억"], "시장은 2조5000억 규모다")
    assert r[0]["verbatim"] is True


def test_verbatim_대조가_단위환산은_하지_않는다():
    """`2.5조` ↔ `2조 5,000억` 은 판단이므로 코드가 단정하지 않는다."""
    r = check_tokens(["2조 5,000억"], "시장은 2.5조 규모다")
    assert r[0]["verbatim"] is False


def test_없는후보에는_near가_붙는다():
    r = check_tokens(["2032년"], "예측 기간은 2023-2032 이다")
    assert r[0]["verbatim"] is False
    assert r[0]["near"], "비슷한 표기를 못 찾았다"


def test_near문맥은_원문에서_잘린다():
    """정규화 문자열에서 자르면 없던 인접 관계가 생겨 사람을 오도한다."""
    exc = "유니레버는 2025년 까지 재활용 소재를 100% 달성한다"
    hits = near_hits("2025년", exc)
    assert hits
    for h in hits:
        assert " " in h, f"공백이 사라진 문맥: {h!r}"
        # 원문에서 공백만 접은 형태여야 한다
        assert h.replace(" ", "") in exc.replace(" ", "")


def test_near가_없으면_빈목록():
    r = check_tokens(["9999억"], "관계없는 본문")
    assert r[0]["near"] == []


# ── ③ UI 데이터 ───────────────────────────────────────────────────────────
def test_기계점수를_제거한다():
    it = {"id": "x", "text": "t", "_machine_groundedness": 5, "_machine_status": "채택"}
    out = strip_machine(it)
    assert out == {"id": "x", "text": "t"}


@pytest.mark.parametrize("cands,want", [
    ([], "해당없음"),
    ([{"token": "a", "verbatim": True}], "있음"),
    ([{"token": "a", "verbatim": False}], "없음"),
    ([{"token": "a", "verbatim": True}, {"token": "b", "verbatim": False}], "일부"),
])
def test_prefill(cands, want):
    assert prefill_numeric(cands) == want


UI = Path("eval/label/groundedness_labeling.html")
SAMPLE = Path("eval/label/groundedness_sample.json")


@pytest.mark.skipif(not UI.exists(), reason="UI 미생성")
def test_UI에_기계점수가_없다():
    """가장 중요한 테스트. 새어 나가면 한 시간의 라벨링이 무효가 된다."""
    h = UI.read_text(encoding="utf-8")
    data = json.loads(re.search(r"const DATA = (\{.*?\});\nconst COMBINE", h, re.S).group(1))
    keys = {k for it in data["items"] for k in it}
    assert not any(k.startswith("_") for k in keys), keys
    assert not any(re.search(r"machine|verification_score|verification_status", k, re.I)
                   for k in keys), keys


@pytest.mark.skipif(not UI.exists(), reason="UI 미생성")
def test_UI의_결합표가_Python과_같다():
    """JS 쪽에 표를 손으로 복사하면 언젠가 어긋난다."""
    h = UI.read_text(encoding="utf-8")
    js = json.loads(re.search(r"const COMBINE = (\{.*?\});", h, re.S).group(1))
    assert len(js) == len(COMBINE)
    for (c, n), v in COMBINE.items():
        assert js[f"{c}|{n}"] == v, f"{c}|{n}: JS {js[f'{c}|{n}']} vs PY {v}"


@pytest.mark.skipif(not UI.exists(), reason="UI 미생성")
def test_UI에_자리표시자가_남지_않았다():
    h = UI.read_text(encoding="utf-8")
    for tok in ("__DATA__", "__COMBINE__", "__CLAIMS__", "__NUMERICS__",
                "__CLAIM_HELP__", "__NUMERIC_HELP__", "__ACCEPT__", "__REJECT__"):
        assert tok not in h, tok


@pytest.mark.skipif(not SAMPLE.exists(), reason="표본 미생성")
def test_표본이_경계층에_집중되어_있다():
    d = json.loads(SAMPLE.read_text(encoding="utf-8"))
    from collections import Counter
    dist = Counter(it["_machine_groundedness"] for it in d["items"])
    assert dist[3] > dist[5], f"3점 경계가 가장 두꺼워야 한다: {dict(dist)}"
    assert len(dist) >= 3, "명확 구간도 있어야 라벨셋 자체를 검증할 수 있다"


@pytest.mark.skipif(not SAMPLE.exists(), reason="표본 미생성")
def test_표본의_모든_항목이_원문을_가진다():
    d = json.loads(SAMPLE.read_text(encoding="utf-8"))
    for it in d["items"]:
        assert it["source_excerpt"], it["id"]


@pytest.mark.skipif(not SAMPLE.exists(), reason="표본 미생성")
def test_표본이_주제에_치우치지_않았다():
    d = json.loads(SAMPLE.read_text(encoding="utf-8"))
    from collections import Counter
    c = Counter(it["topic"] for it in d["items"])
    assert max(c.values()) <= len(d["items"]) * 0.5, dict(c)
