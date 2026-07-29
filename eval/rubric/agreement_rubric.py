"""산출물 루브릭 2자 채점 대조 — 점수와 일치도를 함께 본다.

## 왜 두 사람이 채점하는가

3차 외부 검토 8-5절은 산출물 측정을 제안하면서 편향 대응을 이렇게 포기했다.

> *"라벨러가 1명이며 개발자 본인이다. 자기 산출물을 평가하는 것이므로 관대 편향이
> 있다. 정렬도 실험과 달리 편향 방지 장치를 두기 어렵다(자기 문서라 블라인드가
> 불가능)."*

**이진 루브릭이면 그 포기가 필요 없다.** 항목이 *"TAM에 통화가 명시되어 있는가"* 처럼
확인 가능한 질문이면 채점자가 달라도 같은 답이 나와야 한다. 두 사람이 따로 채점하고
κ를 재면 **"루브릭이 정말 객관적인가"** 자체가 측정된다.

  · κ가 높다  → 항목이 잘 정의됐다. 점수를 신뢰할 근거가 생긴다.
  · κ가 낮다  → **루브릭이 문제다.** 점수보다 그 사실이 더 중요한 발견이다.

즉 이 스크립트는 산출물만 재는 것이 아니라 **자를 함께 잰다.**

## 독립성을 어떻게 지켰는가

Claude가 먼저 채점하지 않았다. 사용자가 채점을 마친 뒤, **Claude가 그 파일을 열지 않은
상태에서** 따로 채점했다. 정렬도 실험에서 라벨러에게 검증기 점수를 숨긴 것과 같은 통제다.

## 한계

  · **표본이 96칸(3문서 × 32항목)이다.** κ의 신뢰구간이 넓다.
  · **채점자 2명 중 1명이 LLM이다.** 사람 2명이 아니므로 표준적인 라벨러 간 일치도가
    아니다. Claude와 사람이 같은 문서를 읽고 같은 답을 냈다는 것까지만 말할 수 있다.
  · **'모름'은 κ에서 제외한다.** 제외 건수를 함께 봐야 한다 — 모름이 많으면 항목이
    모호하다는 뜻이고, 남은 것만으로 잰 κ는 실제보다 높게 나온다.
  · 점수를 국제 벤치마크와 직접 비교할 수 없다(과제도 루브릭도 다르다).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.rubric.hisrubric import DOCS, ITEMS, RUNGS, by_no  # noqa: E402

HUMAN = Path("eval/rubric/rubric_human.json")
CLAUDE = Path("eval/rubric/rubric_claude.json")


def kappa(a: list[bool], b: list[bool]) -> float:
    n = len(a)
    if not n:
        return 0.0
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 0.0 if pe == 1 else (po - pe) / (1 - pe)


def label(k: float) -> str:
    if k < 0.0: return "우연보다 못함"
    if k < 0.20: return "미약(slight)"
    if k < 0.40: return "낮음(fair)"
    if k < 0.60: return "보통(moderate)"
    if k < 0.80: return "상당(substantial)"
    return "거의 완전(almost perfect)"


def load(p: Path) -> dict:
    if not p.exists():
        print(f"파일이 없습니다: {p}")
        raise SystemExit(1)
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    H, C = load(HUMAN), load(CLAUDE)
    aliases = [a for a, _ in DOCS]
    nos = [i.no for i in ITEMS]

    def get(src, alias, no):
        return (src.get("scores", {}).get(alias, {}) or {}).get(str(no))

    print("=" * 78)
    print("산출물 루브릭 2자 채점 대조")
    print("=" * 78)
    print(f"  채점자 A: {H.get('labeler','?')}  ·  채점자 B: {C.get('labeler','?')}")
    print(f"  항목 {len(ITEMS)} × 문서 {len(aliases)} = {len(ITEMS)*len(aliases)}칸\n")

    # ── 1. 점수
    print("[1] 문서별 충족률 (예 / 채점된 칸)")
    print(f"  {'문서':<16}{'A(사람)':>12}{'B(Claude)':>12}{'차이':>8}")
    print("  " + "-" * 50)
    for a in aliases:
        hv = [get(H, a, n) for n in nos]
        cv = [get(C, a, n) for n in nos]
        hy = sum(1 for v in hv if v == "yes"); hn = sum(1 for v in hv if v in ("yes", "no"))
        cy = sum(1 for v in cv if v == "yes"); cn = sum(1 for v in cv if v in ("yes", "no"))
        hp = hy / hn * 100 if hn else 0
        cp = cy / cn * 100 if cn else 0
        print(f"  {a:<16}{f'{hy}/{hn} ({hp:.0f}%)':>12}{f'{cy}/{cn} ({cp:.0f}%)':>12}{cp-hp:>+7.0f}p")

    # ── 2. 층별
    print("\n[2] 4단 사다리별 충족률 (두 채점자 평균)")
    print(f"  {'단계':<16}{'항목수':>6}" + "".join(f"{a:>14}" for a in aliases))
    print("  " + "-" * 62)
    for r in RUNGS:
        rn = [i.no for i in ITEMS if i.rung == r]
        cells = []
        for a in aliases:
            tot = ok = 0
            for src in (H, C):
                for n in rn:
                    v = get(src, a, n)
                    if v in ("yes", "no"):
                        tot += 1
                        ok += (v == "yes")
            cells.append(f"{ok/tot*100:.0f}%" if tot else "—")
        print(f"  {r:<16}{len(rn):>6}" + "".join(f"{c:>14}" for c in cells))

    # ── 3. 일치도
    print("\n[3] 채점자 일치도")
    pa, pb, skipped = [], [], 0
    for a in aliases:
        for n in nos:
            x, y = get(H, a, n), get(C, a, n)
            if x in ("yes", "no") and y in ("yes", "no"):
                pa.append(x == "yes"); pb.append(y == "yes")
            else:
                skipped += 1
    agree = sum(x == y for x, y in zip(pa, pb))
    k = kappa(pa, pb)
    print(f"  비교 가능 {len(pa)}칸 (제외 {skipped}칸 — 모름·미채점)")
    print(f"  단순 일치 {agree}/{len(pa)} ({agree/len(pa)*100:.1f}%)")
    print(f"  Cohen κ  {k:+.3f}  {label(k)}")
    if skipped:
        print(f"  ※ 제외 {skipped}칸이 있다. 모름이 많으면 항목이 모호하다는 뜻이고,")
        print(f"     남은 것만으로 잰 κ는 실제보다 높게 나온다.")

    # ── 4. 갈린 항목
    print("\n[4] 두 채점이 갈린 항목")
    diffs = []
    for a in aliases:
        for n in nos:
            x, y = get(H, a, n), get(C, a, n)
            if x in ("yes", "no") and y in ("yes", "no") and x != y:
                diffs.append((a, n, x, y))
    if not diffs:
        print("  없음 — 모든 항목에서 일치했다")
    else:
        for a, n, x, y in diffs:
            it = by_no(n)
            print(f"\n  [{a}] {n}. {it.text}")
            print(f"    사람 {x} / Claude {y}" + ("   ★외부 확인 필요 항목" if it.needs_external else ""))
            why = (C.get("reasons", {}).get(a, {}) or {}).get(str(n), "")
            if why:
                print(f"    Claude 근거: {why}")

    # ── 5. 모두 아니오인 항목 (공통 약점)
    print("\n[5] 두 채점자 모두 '아니오'로 본 항목 — 확실한 약점")
    weak = []
    for a in aliases:
        for n in nos:
            if get(H, a, n) == "no" and get(C, a, n) == "no":
                weak.append((a, n))
    if not weak:
        print("  없음")
    else:
        for n, cnt in Counter(n for _, n in weak).most_common():
            docs_ = [a for a, m in weak if m == n]
            print(f"  {n}. {by_no(n).text}")
            print(f"     → {', '.join(docs_)} ({len(docs_)}/{len(aliases)}건)")

    print("\n" + "=" * 78)
    print("한계")
    print("=" * 78)
    for line in (
        "표본이 96칸이다. κ의 신뢰구간이 넓다.",
        "채점자 2명 중 1명이 LLM이다. 사람 2명이 아니므로 표준 라벨러 간 일치도가 아니다.",
        "'모름'은 κ에서 제외했다. 제외 건수를 함께 볼 것.",
        "국제 벤치마크와 직접 비교할 수 없다 — 과제도 루브릭도 다르다.",
        "  DeepResearch Bench II의 '최강 모델 50% 미만'과 나란히 놓지 말고,",
        "  '같은 방식으로 쟀다'까지만 말할 것.",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
