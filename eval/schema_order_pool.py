"""여러 실행을 합쳐 신호와 잡음을 분리한다.

실행:
    python eval/schema_order_pool.py                    # 보관된 모든 실행
    python eval/schema_order_pool.py --variant 운영     # 문구별로

## 왜 별도 스크립트인가

`schema_order.py` 는 **한 실행**을 돌리고 그 실행만 집계한다. 그런데 이 프로젝트에서
반복 확인된 것은 **실행 간 변동이 조건 간 차이만큼 크다**는 것이다.

    κ    조건 간 평균 폭 0.054   vs   실행 간 최대 폭 0.348   (5회 실측)

한 실행의 표를 보고 "B가 최고"라고 말하면 다음 실행에서 뒤집힌다. 실제로 5회 중
κ 1위가 B → C → D → B → C 로 매번 달라졌다. 그래서 **여러 실행을 합쳐 신호 대 잡음을
먼저 보고, 잡음이 우세한 지표는 판정하지 않는다.**

## 판정 규칙

각 지표마다 두 값을 비교한다.

    신호 = 조건별 평균의 최대 - 최소
    잡음 = 한 조건이 실행 간에 흔들린 폭의 최대

신호 > 잡음 일 때만 "이 지표로 조건을 비교할 수 있다"고 말한다. 그렇지 않으면
표본을 늘리거나 반복을 늘려야 하며, **숫자를 보고할 때 순위를 매기지 않는다.**
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.groundedness_agreement import cohen_kappa, landis_koch, prf  # noqa: E402
from eval.groundedness_scale import (  # noqa: E402
    ACCEPT_MIN_SCORE, combine, status_of,
)
from eval.schema_order import CONDITIONS  # noqa: E402

STATUSES = ["채택", "보류", "기각"]
LABELS = Path("eval/label/groundedness_labels.json")
ARCHIVE = "eval/label/schema_order_2*.json"


def human_scores() -> dict[str, int]:
    d = json.loads(LABELS.read_text(encoding="utf-8"))
    out = {}
    for l in d["labels"]:
        out[l["id"]] = int(l.get("human_groundedness")
                           or combine(l["claim_scope"], l["numeric_scope"]))
    return out


def load_runs(variant: str | None) -> list[tuple[str, str, dict]]:
    runs = []
    for f in sorted(glob.glob(ARCHIVE)):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        v = d.get("grade_4_variant", "v2")
        if variant and v != variant:
            continue
        runs.append((os.path.basename(f)[13:28], v, d["results"]))
    return runs


def per_run(res: dict, c: str, H: dict[str, int]) -> dict:
    ids = [i for i in res[c] if i in H and res[c][i]]
    sc = [r["score"] for i in ids for r in res[c][i]]
    if not sc:
        return {}
    pr = [(status_of(H[i]), status_of(Counter(r["score"] for r in res[c][i]).most_common(1)[0][0]))
          for i in ids]
    Hs = [a for a, _ in pr]; Ms = [b for _, b in pr]
    p, r, *_ = prf(Hs, Ms, "기각")
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return dict(n=len(ids),
                n14=(sc.count(1) + sc.count(4)) / len(sc) * 100,
                acc=sum(1 for s in sc if s >= ACCEPT_MIN_SCORE) / len(sc) * 100,
                k=cohen_kappa(Hs, Ms, STATUSES), p=p * 100, r=r * 100, f1=f1)


METRICS = [("n14", "1·4점 사용률", 1, "%"), ("acc", "채택률", 1, "%"),
           ("k", "κ", 3, ""), ("p", "정밀도", 0, "%"),
           ("r", "재현율", 0, "%"), ("f1", "F1", 3, "")]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", help="4점 문구로 걸러내기 (운영 / v1 / v2)")
    ap.add_argument("--n", type=int,
                    help="대조 항목 수가 이 값인 실행만. 라벨을 늘린 뒤에는 "
                         "대상이 다른 실행을 섞으면 안 된다")
    a = ap.parse_args()

    H = human_scores()
    runs = load_runs(a.variant)
    if a.n:
        runs = [(t, v, r) for t, v, r in runs if per_run(r, "A", H).get("n") == a.n]
    if not runs:
        raise SystemExit(f"보관 파일이 없다: {ARCHIVE}")

    print("=" * 84)
    print(f"실행 {len(runs)}개 합산 · 사람 라벨 {len(H)}건"
          + (f" · 4점 문구 {a.variant}" if a.variant else ""))
    print("=" * 84)
    for t, v, res in runs:
        n = per_run(res, "A", H).get("n", 0)
        print(f"  {t}  문구={v:<4} 대조 가능 {n}건")

    covered = per_run(runs[0][2], "A", H).get("n", 0)
    if covered < len(H):
        print(f"\n  ! 라벨 {len(H)}건 중 {covered}건만 실행에 포함돼 있다."
              f" 라벨을 늘렸다면 실험을 다시 돌려야 새 항목이 들어간다.")

    hu = list(H.values())
    hacc = sum(1 for x in hu if x >= ACCEPT_MIN_SCORE) / len(hu) * 100
    h14 = sum(1 for x in hu if x in (1, 4)) / len(hu) * 100

    print(f"\n{'─'*84}\n조건별 평균 (범위)\n{'─'*84}")
    hdr = f"  {'조건':<4}" + "".join(f"{n:>20}" for _, n, _, _ in METRICS[:3])
    print(hdr)
    vals = {}
    for c in CONDITIONS:
        vals[c] = {k: [per_run(res, c, H)[k] for _, _, res in runs] for k, *_ in METRICS}
        row = f"  {c}   "
        for k, _, p, u in METRICS[:3]:
            v = vals[c][k]
            row += f"{st.mean(v):.{p}f} ({min(v):.{p}f}~{max(v):.{p}f})".rjust(20)
        print(row)
    print(f"  사람  {h14:>19.1f}{hacc:>20.1f}")

    print(f"\n{'─'*84}\n신호 대 잡음 — 어떤 지표로 조건을 비교할 수 있는가\n{'─'*84}")
    usable = []
    for k, name, p, u in METRICS:
        means = {c: st.mean(vals[c][k]) for c in CONDITIONS}
        signal = max(means.values()) - min(means.values())
        noise = max(max(vals[c][k]) - min(vals[c][k]) for c in CONDITIONS)
        ok = signal > noise
        usable.append((k, name, ok))
        print(f"  {name:<12} 신호 {signal:>7.{p}f}{u}   잡음 {noise:>7.{p}f}{u}   "
              f"{'✅ 비교 가능' if ok else '★ 판정 불가 — 순위를 매기지 않는다'}")

    print(f"\n{'─'*84}\n비교 가능한 지표에서 사람과의 거리\n{'─'*84}")
    ref = {"n14": h14, "acc": hacc}
    for k, name, ok in usable:
        if not ok or k not in ref:
            continue
        print(f"\n  [{name}]  사람 {ref[k]:.1f}%")
        for c in sorted(CONDITIONS, key=lambda c: abs(st.mean(vals[c][k]) - ref[k])):
            m = st.mean(vals[c][k])
            print(f"    {c} {CONDITIONS[c][0]:<30} {m:>6.1f}%   차이 {m-ref[k]:+6.1f}%p")

    print(f"\n{'─'*84}\n전 실행 합산 (반복·실행을 모두 모아 항목별 최빈값)\n{'─'*84}")
    print(f"  {'조건':<4}{'1·4점':>9}{'채택률':>9}{'κ':>8}{'정밀도':>8}{'재현율':>8}{'F1':>8}   κ 해석")
    for c in CONDITIONS:
        byid: dict[str, list[int]] = {}
        sc: list[int] = []
        for _, _, res in runs:
            for i, v in res[c].items():
                if i not in H:
                    continue
                byid.setdefault(i, []).extend(r["score"] for r in v)
                sc.extend(r["score"] for r in v)
        pr = [(status_of(H[i]), status_of(Counter(ss).most_common(1)[0][0]))
              for i, ss in byid.items()]
        Hs = [x for x, _ in pr]; Ms = [y for _, y in pr]
        p, r, *_ = prf(Hs, Ms, "기각")
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        k = cohen_kappa(Hs, Ms, STATUSES)
        print(f"  {c}  {(sc.count(1)+sc.count(4))/len(sc)*100:>8.1f}%"
              f"{sum(1 for s in sc if s>=ACCEPT_MIN_SCORE)/len(sc)*100:>8.1f}%"
              f"{k:>8.3f}{p*100:>7.0f}%{r*100:>7.0f}%{f1:>8.3f}   {landis_koch(k)}")
    print(f"  사람  {h14:>8.1f}%{hacc:>8.1f}%")

    print(f"\n{'─'*84}\n요인 주효과 (평균 기준)\n{'─'*84}")
    for k, name, p, u in METRICS:
        A, B, C, D = (st.mean(vals[x][k]) for x in "ABCD")
        print(f"  {name:<12} 루브릭 {((C+D)-(A+B))/2:+8.{p}f}{u}   "
              f"순서 {((B+D)-(A+C))/2:+8.{p}f}{u}   교차 {D-B-C+A:+8.{p}f}{u}")


if __name__ == "__main__":
    main()
