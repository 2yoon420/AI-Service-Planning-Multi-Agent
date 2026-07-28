"""판정 규칙 전환의 영향 측정 — 이전(적응형+clamp) vs 이후(이산 규칙).

## 왜 별도 스크립트인가

2026-07-29에 판정 경계를 이산 규칙(채택 ≥4 / 애매 =3 / 기각 ≤2)으로 바꿨다.
"고쳤다"고만 쓰면 심사에서 *"그래서 산출물이 어떻게 달라졌습니까"* 에 답할 수 없다.
이 스크립트가 그 답을 숫자로 만든다.

## 설계에서 중요한 것 두 가지

**① 이후 규칙은 재구현하지 않는다.** `agents.verification.classify_score()`를 직접
   호출한다. 평가 스크립트가 운영 규칙을 베껴 쓰면, 운영 코드를 고쳐도 평가는 옛 규칙을
   재고 있으면서 "일치한다"고 보고한다. 이 프로젝트가 네 번 겪은 배선 실수의 변종이다.

**② 이전 규칙은 여기 명시적으로 남긴다.** `compute_adaptive_threshold()`는 운영에서
   폐기됐지만 기준선으로는 필요하다. 지우면 전후 비교를 재현할 수 없다.

## 한계

  · 데이터는 결함 A~G 수정 **이전** 코드(solar-mini)로 채점된 점수다. 즉 이 표는
    "같은 점수에 다른 판정 규칙을 적용하면 어떻게 되는가"만 보여준다. 수정 후 모델
    (solar-pro2 + 새 루브릭)이 매길 점수 분포는 이것과 다르다.
  · 배치 크기 5를 쓴다(이전 규칙 계산에만 영향). 유럽 운영 실측을 오차 0건으로
    재현하는 값이지만, 한국은 12가 최적이었다 — 도메인마다 다르다.
  · 채택이 줄었다는 것이 "정확해졌다"를 뜻하지는 않는다. 사람 라벨 70건에서 3점이
    채택 15 / 기각 13으로 갈렸으므로, 애매로 보낸 것 중 절반가량은 실제로 쓸 수
    있었던 fact다. 이 전환은 "정확도 개선"이 아니라 **자동 판정의 범위를 좁히고
    사람에게 넘기는 양을 늘린 것**이다.
"""

from __future__ import annotations

import glob
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.verification import (  # noqa: E402
    ACCEPT_MIN_SCORE,
    REJECT_MAX_SCORE,
    classify_score,
    compute_adaptive_threshold,
)
from eval.sensitivity import Dataset, load  # noqa: E402
from fact_store.schema import VerificationStatus  # noqa: E402

_KEY = {
    VerificationStatus.ACCEPTED: "채택",
    VerificationStatus.AMBIGUOUS: "애매",
    VerificationStatus.REJECTED: "기각",
}
BATCH_SIZE = 5


def previous_rule(ds: Dataset, batch_size: int = BATCH_SIZE) -> dict[str, int]:
    """2026-07-29 이전 규칙 — 배치 분포로 임계값을 정하고 clamp(3.0, 4.0)."""
    out = {"채택": 0, "애매": 0, "기각": 0}
    pairs = ds.pairs
    for i in range(0, len(pairs), batch_size):
        scores = [min(p.rel, p.grd) for p in pairs[i:i + batch_size]]
        th = compute_adaptive_threshold(scores)
        for s in scores:
            if s >= th:
                out["채택"] += 1
            elif s <= th - 2:
                out["기각"] += 1
            else:
                out["애매"] += 1
    return out


def current_rule(ds: Dataset) -> dict[str, int]:
    """현재 규칙 — 운영 코드의 classify_score()를 그대로 호출한다."""
    out = {"채택": 0, "애매": 0, "기각": 0}
    for p in ds.pairs:
        out[_KEY[classify_score(min(p.rel, p.grd))]] += 1
    return out


def main() -> None:
    paths = sys.argv[1:] or sorted(glob.glob("eval/datasets/*.json"))
    if not paths:
        print("데이터셋이 없습니다. eval/datasets/*.json 을 확인하세요.")
        return
    dss = [load(p) for p in paths]

    print("=" * 78)
    print("판정 규칙 전환 영향 — 이전(적응형+clamp) vs 이후(이산 규칙)")
    print("=" * 78)
    print(f"  이전: threshold = 평균 − 0.5×표준편차, clamp(3.0, 4.0), 기각 ≤ threshold−2")
    print(f"  이후: 채택 ≥ {ACCEPT_MIN_SCORE} / 애매 = 3 / 기각 ≤ {REJECT_MAX_SCORE}  (배치 무관)")
    print(f"  이전 규칙 계산에 쓴 배치 크기: {BATCH_SIZE}\n")

    print(f"  {'도메인':<14}{'n':>5}   {'이전 채택/애매/기각':<24}"
          f"{'이후 채택/애매/기각':<24}{'채택 변화':>12}")
    print("  " + "-" * 74)
    tot = {"prev": [0, 0, 0], "cur": [0, 0, 0]}
    for ds in dss:
        a, b, n = previous_rule(ds), current_rule(ds), len(ds)
        for i, k in enumerate(("채택", "애매", "기각")):
            tot["prev"][i] += a[k]
            tot["cur"][i] += b[k]
        fa = f"{a['채택']:>3} / {a['애매']:>3} / {a['기각']:>3}"
        fb = f"{b['채택']:>3} / {b['애매']:>3} / {b['기각']:>3}"
        d = b["채택"] - a["채택"]
        print(f"  {ds.name:<14}{n:>5}   {fa:<24}{fb:<24}"
              f"{d:>+5}건 ({d / n * 100:>+5.1f}%p)")

    N = sum(len(d) for d in dss)
    p, c = tot["prev"], tot["cur"]
    print("  " + "-" * 74)
    fa = f"{p[0]:>3} / {p[1]:>3} / {p[2]:>3}"
    fb = f"{c[0]:>3} / {c[1]:>3} / {c[2]:>3}"
    print(f"  {'합계':<14}{N:>5}   {fa:<24}{fb:<24}"
          f"{c[0] - p[0]:>+5}건 ({(c[0] - p[0]) / N * 100:>+5.1f}%p)")

    print(f"\n  채택률   {p[0] / N * 100:.1f}%  →  {c[0] / N * 100:.1f}%"
          f"   (상대 {(c[0] / p[0] - 1) * 100:+.1f}%)")
    print(f"  애매     {p[1]}건  →  {c[1]}건   ({c[1] - p[1]:+d}건, "
          f"{(c[1] / p[1] - 1) * 100:+.0f}% — 사람이 확인할 양)")
    print(f"  기각     {p[2]}건  →  {c[2]}건   ({c[2] - p[2]:+d}건)")

    print("\n  얻은 것: 근거 없는 값 4개 → 1개")
    print("    (계수 0.5 · clamp 하한 3.0 · clamp 상한 4.0 · 기각 경계 −2) → (경계 4/3/2)")
    print("    남은 1개는 루브릭 정의에 묶여 있어 임의로 흔들 수 없다.")
    print("  얻은 것: 결함 D의 전파 경로 소멸 — 판정이 배치 분포를 보지 않는다.")
    print("  얻은 것: 재현성 — 같은 fact가 어느 회차에 검색됐는지에 따라 판정이 달라지지 않는다.")
    print("\n  대가: 애매가 65% 늘어난다. 기획서에 [출처확인필요] 태그가 그만큼 많아지고,")
    print("        사용자가 손으로 확인할 항목이 늘어난다. 의도한 대가다.")

    print("\n" + "=" * 78)
    print("한계 — 반드시 함께 보고할 것")
    print("=" * 78)
    for line in (
        "이 데이터는 결함 A~G 수정 이전 코드(solar-mini)로 채점된 점수다. 같은 점수에",
        "  다른 규칙을 적용한 결과이며, 수정 후 모델이 매길 분포는 이것과 다르다.",
        "채택이 줄었다는 것이 정확해졌다는 뜻은 아니다. 사람 라벨에서 3점은 채택 15 /",
        "  기각 13으로 갈렸으므로, 애매로 보낸 것 중 절반가량은 실제로 쓸 수 있었다.",
        "  이 전환은 정확도 개선이 아니라 자동 판정 범위를 좁힌 것이다.",
        "경계 4/2 자체는 여전히 근거 없는 값이다. 루브릭 정의에 묶였을 뿐이다.",
        "배치 크기 5는 유럽 실측 재현값이지만 한국은 12가 최적이었다(도메인 의존).",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")


if __name__ == "__main__":
    main()
