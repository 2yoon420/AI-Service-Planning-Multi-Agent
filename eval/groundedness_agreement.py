"""근거지지도 축의 사람 라벨 대비 검증기 정렬도.

실행:
    python eval/groundedness_agreement.py                       # 기본 경로
    python eval/groundedness_agreement.py --labels ~/Downloads/groundedness_labels.json
    python eval/groundedness_agreement.py --selftest            # 라벨 없이 계산기 검증

## 무엇을 재는가

`검증기 점수`와 `사람 라벨`의 일치도다. 관련성 축은 `eval/agreement.py`가 이미
재고 있었고(κ 0.153 → 0.551), **근거지지도 축은 사람 라벨이 없어 비어 있었다.**
결함 H 수정으로 채점 원문이 저장되기 시작해 사람이 라벨할 수 있게 됐다.

## 세 층으로 본다

1. **판정 일치** — 채택/보류/기각 3분류의 Cohen's κ. 운영에서 실제로 갈리는 단위다.
2. **점수 일치** — 1~5점의 정확 일치·±1 이내. 척도가 얼마나 어긋나는지 본다.
3. **기각 성능** — 정밀도·재현율. "기각해야 할 것을 기각했는가"를 본다.

점수 κ를 주 지표로 쓰지 않는 이유가 있다. 1~5점은 순서형인데 κ는 순서를 모른다 —
5점을 4점으로 본 것과 5점을 1점으로 본 것을 같은 불일치로 센다. 판정 3분류가
운영 의미에 더 가깝다.

## 사람이 애매하다고 표시한 항목

라벨링 화면에서 `애매함`으로 표시한 항목을 따로 집계한다. 관련성 라벨(51절)에서
이 표시가 내 자기 착오 3건을 찾아내는 단서가 됐다. **사람도 흔들린 자리에서
기계가 흔들린 것은 다르게 읽어야 한다.**
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.groundedness_scale import (  # noqa: E402
    ACCEPT_MIN_SCORE, REJECT_MAX_SCORE, combine, status_of,
)

STATUSES = ["채택", "보류", "기각"]


# ── 통계 ───────────────────────────────────────────────────────────────────
def cohen_kappa(a: list, b: list, labels: Optional[list] = None) -> float:
    """Cohen's κ. 두 채점자의 일치도에서 우연 일치를 뺀 값."""
    assert len(a) == len(b) and a
    labels = labels or sorted(set(a) | set(b), key=str)
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[l] / n) * (cb[l] / n) for l in labels)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def landis_koch(k: float) -> str:
    for t, s in ((0.81, "거의 완전(almost perfect)"), (0.61, "상당(substantial)"),
                 (0.41, "보통(moderate)"), (0.21, "미약(fair)"), (0.0, "약간(slight)")):
        if k >= t:
            return s
    return "우연 이하(poor)"


def prf(human: list, machine: list, positive: str) -> tuple[float, float, int, int, int]:
    """positive 를 '검출 대상'으로 보는 정밀도·재현율."""
    tp = sum(1 for h, m in zip(human, machine) if m == positive and h == positive)
    fp = sum(1 for h, m in zip(human, machine) if m == positive and h != positive)
    fn = sum(1 for h, m in zip(human, machine) if m != positive and h == positive)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, tp, fp, fn


# ── 데이터 ─────────────────────────────────────────────────────────────────
def load_machine(sample_path: Path) -> dict[str, dict]:
    """표본 파일에 보관된 기계 점수를 읽는다 (라벨링 화면에는 넣지 않은 값)."""
    d = json.loads(sample_path.read_text(encoding="utf-8"))
    return {it["id"]: it for it in d["items"]}


def load_labels(p: Path) -> list[dict]:
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("axis") != "groundedness":
        raise SystemExit(f"근거지지도 라벨이 아니다: axis={d.get('axis')!r}")
    return d["labels"]


def report(labels: list[dict], machine: dict[str, dict]) -> None:
    rows = []
    missing = []
    for l in labels:
        m = machine.get(l["id"])
        if not m:
            missing.append(l["id"]); continue
        hs = l.get("human_groundedness")
        if hs is None:                       # 환산값이 없으면 다시 계산
            hs = combine(l["claim_scope"], l["numeric_scope"])
        rows.append({
            "id": l["id"],
            "human": int(hs),
            "machine": int(m["_machine_groundedness"]),
            "claim": l["claim_scope"], "numeric": l["numeric_scope"],
            "uncertain": bool(l.get("uncertain")),
            "note": l.get("note", ""),
            "text": m["text"], "topic": m["topic"],
        })
    if missing:
        print(f"  ! 표본에 없는 라벨 {len(missing)}건 무시: {missing[:3]}")
    if not rows:
        raise SystemExit("대조할 항목이 없다.")

    H = [r["human"] for r in rows]
    M = [r["machine"] for r in rows]
    HS = [status_of(x) for x in H]
    MS = [status_of(x) for x in M]
    n = len(rows)

    print("=" * 74)
    print(f"근거지지도 정렬도 — 사람 라벨 {n}건 대비 검증기")
    print("=" * 74)

    print(f"\n[1] 판정 일치 (채택 ≥{ACCEPT_MIN_SCORE} / 기각 ≤{REJECT_MAX_SCORE})")
    k = cohen_kappa(HS, MS, STATUSES)
    agree = sum(1 for h, m in zip(HS, MS) if h == m)
    print(f"    일치율   {agree}/{n} = {agree/n*100:.1f}%")
    print(f"    Cohen's κ = {k:.3f}  ({landis_koch(k)})")
    print(f"    참고: 관련성 축은 0.153 → 0.551 (미약 → 보통)")

    print(f"\n    혼동 행렬 (행=사람, 열=기계)")
    print("      " + "".join(f"{s:>8}" for s in STATUSES) + "     합")
    for hs in STATUSES:
        cells = [sum(1 for h, m in zip(HS, MS) if h == hs and m == ms) for ms in STATUSES]
        print(f"    {hs:>4}" + "".join(f"{c:>8}" for c in cells) + f"{sum(cells):>8}")
    print("     합 " + "".join(f"{sum(1 for m in MS if m==ms):>8}" for ms in STATUSES))

    print(f"\n[2] 점수 일치 (1~5점)")
    exact = sum(1 for h, m in zip(H, M) if h == m)
    within1 = sum(1 for h, m in zip(H, M) if abs(h - m) <= 1)
    bias = sum(m - h for h, m in zip(H, M)) / n
    print(f"    정확 일치  {exact}/{n} = {exact/n*100:.1f}%")
    print(f"    ±1 이내    {within1}/{n} = {within1/n*100:.1f}%")
    print(f"    평균 편향  {bias:+.2f}점  ({'기계가 후하다' if bias > 0.15 else '기계가 짜다' if bias < -0.15 else '치우침 작음'})")
    print(f"    사람 분포  {dict(sorted(Counter(H).items()))}")
    print(f"    기계 분포  {dict(sorted(Counter(M).items()))}")

    print(f"\n[3] 기각 성능 — '근거 없는 fact를 걸러내는가'")
    p, r, tp, fp, fn = prf(HS, MS, "기각")
    print(f"    정밀도 {p*100:.0f}%  (기계가 기각한 것 중 사람도 기각: {tp}/{tp+fp})")
    print(f"    재현율 {r*100:.0f}%  (사람이 기각한 것 중 기계도 기각: {tp}/{tp+fn})")
    if fn:
        print(f"    ★ 놓친 기각 {fn}건 — 사람은 근거 없다고 봤는데 기계는 통과시켰다")

    print(f"\n[4] 사람이 두 축을 어떻게 봤나")
    cn = Counter((r["claim"], r["numeric"]) for r in rows)
    for (c, nu), v in sorted(cn.items(), key=lambda x: -x[1]):
        print(f"    {c:>4} × {nu:<6} → {combine(c, nu)}점  {v:>3}건")
    danger = cn.get(("예", "없음"), 0) + cn.get(("부분", "없음"), 0)
    if danger:
        print(f"    ★ 주장은 있고 수치가 없는 유형: {danger}건 (가장 위험한 환각 형태)")

    unc = [r for r in rows if r["uncertain"]]
    print(f"\n[5] 사람이 애매하다고 표시한 항목: {len(unc)}건")
    if unc:
        ku = cohen_kappa([status_of(r["human"]) for r in unc],
                         [status_of(r["machine"]) for r in unc], STATUSES) if len(unc) > 1 else float("nan")
        rest = [r for r in rows if not r["uncertain"]]
        kr = cohen_kappa([status_of(r["human"]) for r in rest],
                         [status_of(r["machine"]) for r in rest], STATUSES) if len(rest) > 1 else float("nan")
        print(f"    애매 표시분 κ={ku:.3f} / 나머지 κ={kr:.3f}")
        print(f"    → 사람도 흔들린 자리에서 기계가 흔들린 것은 다르게 읽어야 한다")

    print(f"\n[6] 가장 크게 어긋난 항목")
    for r in sorted(rows, key=lambda x: -abs(x["human"] - x["machine"]))[:8]:
        d = r["machine"] - r["human"]
        if d == 0:
            break
        flag = " [애매]" if r["uncertain"] else ""
        print(f"    사람 {r['human']}({status_of(r['human'])}) / 기계 {r['machine']}({status_of(r['machine'])})"
              f"  {d:+d}{flag}")
        print(f"       {r['claim']}×{r['numeric']} · {r['text'][:62]}")
        if r["note"]:
            print(f"       메모: {r['note'][:70]}")

    print(f"\n[7] 한계")
    for line in (
        f"표본 {n}건이다. 층별로 나누면 각 층이 한 자리 수가 되어 층별 κ는 신뢰구간이 넓다.",
        "② 수치·고유명사 대조는 코드가 후보를 제시하고 사람이 확정한 반자동이다 — 순수 사람 라벨이 아니다.",
        "원문에서 찾은 후보를 화면에 강조 표시했다. ① 판단에 시선을 유도했을 수 있다.",
        "채점자가 한 명이다. 관련성 축은 3자였다 — 사람 라벨 자체의 흔들림을 여기서는 못 잰다.",
    ):
        print(f"    - {line}")


# ── 자체 검증 ──────────────────────────────────────────────────────────────
def selftest() -> None:
    """라벨 파일 없이 계산기가 맞는지 확인한다."""
    print("계산기 자체 검증")
    ok = 0
    def chk(cond, msg):
        nonlocal ok
        print(f"  {'OK ' if cond else '★  '} {msg}")
        ok += bool(cond)
    chk(abs(cohen_kappa(["a","b","a","b"], ["a","b","a","b"]) - 1.0) < 1e-9, "완전 일치 → κ=1")
    chk(abs(cohen_kappa(["a","a","b","b"], ["a","a","b","b"], ["a","b"]) - 1.0) < 1e-9, "라벨 지정 완전 일치")
    chk(abs(cohen_kappa(["a","b","a","b"], ["b","a","b","a"]) + 1.0) < 1e-9, "완전 불일치 → κ=-1")
    chk(cohen_kappa(["a"]*4, ["a"]*4) == 1.0, "한 범주뿐이고 일치 → 1.0 (0으로 나누지 않음)")
    chk(cohen_kappa(["a"]*4, ["b"]*4) == 0.0, "한 범주뿐이고 불일치 → 0.0")
    # 우연 일치가 큰 경우: 일치율은 높은데 κ는 0이어야 한다.
    #
    # 처음에는 18/2 대 19/1 로 짜고 "κ < 0.6" 을 기대했다. 실제로는 0.643이 나왔고,
    # 손으로 계산해보니 그것이 맞았다(po=0.95, pe=0.86 → 0.643). **계산기가 아니라
    # 내가 어림한 기대값이 틀렸다.** 검증하려던 성질을 정확히 보여주는 사례로 바꾼다.
    #
    # 기계가 전부 채택으로만 답하면 일치율 95%인데 판별력은 0이다. κ는 이것을 잡는다.
    h = ["채택"]*19 + ["기각"]*1
    m = ["채택"]*20
    k = cohen_kappa(h, m, STATUSES)
    chk(abs(k) < 1e-9, f"전부 한쪽으로 답하면 일치율 95%라도 κ=0 (관측 {k:.3f})")
    # 그리고 앞서 틀렸던 계산을 값으로 박아둔다 — 계산기가 바뀌면 깨지게
    k2 = cohen_kappa(["채택"]*18 + ["기각"]*2, ["채택"]*19 + ["기각"]*1, STATUSES)
    chk(abs(k2 - 0.6429) < 5e-4, f"수기 검산값 0.6429 (관측 {k2:.4f})")
    p, r, tp, fp, fn = prf(["기각","기각","채택"], ["기각","채택","채택"], "기각")
    chk(p == 1.0 and abs(r - 0.5) < 1e-9, f"정밀도 1.0 / 재현율 0.5 (관측 {p:.2f}/{r:.2f})")
    chk(landis_koch(0.551) == "보통(moderate)", "Landis & Koch 구간 (0.551 → 보통)")
    chk(landis_koch(0.153) == "약간(slight)", "0.153 → 약간")
    chk(status_of(combine("예","없음")) == "기각", "예×없음 → 기각")
    print(f"\n  {ok}/11 통과")
    if ok != 11:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="eval/label/groundedness_labels.json")
    ap.add_argument("--sample", default="eval/label/groundedness_sample.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    lp = Path(a.labels)
    if not lp.exists():
        raise SystemExit(
            f"라벨 파일이 없다: {lp}\n"
            "  라벨링 화면에서 [JSON 내보내기]를 누르면 groundedness_labels.json 이 내려온다.\n"
            "  그 파일을 eval/label/ 로 옮기거나 --labels 로 경로를 지정할 것.")
    report(load_labels(lp), load_machine(Path(a.sample)))


if __name__ == "__main__":
    main()
