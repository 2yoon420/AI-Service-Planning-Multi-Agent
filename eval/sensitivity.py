"""판정 파라미터 민감도 분석.

## 왜 필요한가

`agents/verification.py`의 판정 구조에는 근거가 없는 값이 세 개 있다.

    threshold = clamp(mean(scores) - 0.5 * stdev(scores), 3.0, 4.0)
    combined  = min(relevance, groundedness)
    채택: combined >= threshold / 기각: combined <= threshold - 2 / 그 사이: 애매

공식 자체(평균 − k·표준편차)는 MAIN-RAG 원문(arXiv:2501.00332)에서 확인했으나,
**계수 0.5, clamp 범위 3.0~4.0, 기각 경계 −2, min 결합은 전부 자체 설계**다.
외부 검토에서 "우리 프로젝트의 핵심인데 근거 자료가 하나도 없다"는 지적을 받았다.

논문을 들이댈 수 없는 값에 근거를 만드는 표준 방법이 민감도 분석이다 —
"근거는 없지만, 값을 바꿔봤더니 결과가 이만큼 변했고 우리가 고른 구간은 이런 성질을
가진다"를 보이는 것. 심사에서 "왜 0.5입니까"에 대해 "0.3~0.7 구간에서 판정이 이렇게
변하며 우리 데이터에서는 이 구간이 평평했습니다"라고 답할 수 있게 된다.

## 데이터

실제 운영 실행에서 나온 fact를 쓴다. `verification_reasoning` 필드가
"[관련성 N점: ...] [근거지지도 M점: ...]" 형식이므로 **두 축 점수를 복원할 수 있다.**
combined(min) 점수만으로는 결합 방식을 바꿔볼 수 없기 때문에 이 복원이 전제다.

## 채점 조건과 교란(confounding)

**채점 조건은 네 데이터셋이 모두 같다** — solar-mini + 결함 A~D 수정 이전 루브릭.
한국 데이터를 로컬(수정된 코드)이 아니라 배포 서버(ebbe658)에서 돌린 덕이다.
따라서 판정 파라미터 민감도에 관해서는 데이터셋 간 비교가 정당하다.

다만 **fact 수집 조건은 다르다.** 북미 두 실행(2026-07-27)은 Brave 검색을 썼고,
유럽·한국(2026-07-28)은 Tavily를 썼다. 이것은 "어떤 fact가 모였는가"에 영향을 주므로
점수 분포 자체의 차이로 나타난다. 채점 방식의 차이가 아니라 표본의 차이다.

그래서 이 분석은 절대값 비교보다 **"같은 결론이 네 도메인에서 재현되는가"** 에 무게를
둔다. 표본이 다른데도 같은 결론이 나오면 그 결론은 도메인·검색백엔드에 의존하지 않는다.

남은 한계: 원문(source_content)을 저장하지 않으므로, 수정 후 루브릭으로 재채점해
"수정이 판정 분포를 어떻게 바꿨는가"를 같은 표본에서 비교할 수는 없다.

## 사용법

    python eval/sensitivity.py                       # eval/datasets/*.json 전부
    python eval/sensitivity.py eval/datasets/유럽_포장재.json
    python eval/sensitivity.py --batch-size 10       # 배치 크기를 바꿔 재계산
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# 현재 운영 중인 값. 이 값들이 비교의 기준선이다.
CUR_COEF = 0.5
CUR_CLAMP = (3.0, 4.0)
CUR_REJECT_GAP = 2
SCORE_MIN, SCORE_MAX = 1, 5

REASON_PAT = re.compile(r"\[관련성 (\d+)점.*?\[근거지지도 (\d+)점", re.S)


@dataclass
class Pair:
    """한 fact의 두 축 점수. 민감도 분석의 최소 단위."""

    rel: int
    grd: int
    text: str

    def combine(self, rule: str) -> float:
        if rule == "min":
            return min(self.rel, self.grd)
        if rule == "mean":
            return (self.rel + self.grd) / 2
        if rule == "w73":  # 근거지지도 0.7 / 관련성 0.3 — 환각 억제를 더 중시
            return 0.3 * self.rel + 0.7 * self.grd
        if rule == "geo":  # 기하평균 — min과 평균의 중간 성격
            return (self.rel * self.grd) ** 0.5
        raise ValueError(rule)


@dataclass
class Dataset:
    name: str
    topic: str
    market: str
    pairs: list[Pair]
    note: str = ""

    def __len__(self) -> int:
        return len(self.pairs)


def load(path: str | Path) -> Dataset:
    """JSON 데이터셋에서 두 축 점수를 복원한다.

    복원 실패한 fact는 조용히 버리지 않고 개수를 보고한다 — 표본이 얼마나 줄었는지
    모르면 결론의 신뢰 구간을 말할 수 없다."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs, missed = [], 0
    for f in d["facts"]:
        m = REASON_PAT.search(f.get("verification_reasoning") or "")
        if not m:
            missed += 1
            continue
        rel, grd = int(m.group(1)), int(m.group(2))
        if not (SCORE_MIN <= rel <= SCORE_MAX and SCORE_MIN <= grd <= SCORE_MAX):
            # 결함 D에서 다룬 범위 밖 점수. 운영 데이터에는 없었지만 방어한다.
            missed += 1
            continue
        pairs.append(Pair(rel, grd, (f.get("text") or "")[:60]))
    ds = Dataset(d["dataset"], d.get("topic", ""), d.get("target_market", ""),
                 pairs, d.get("note", ""))
    ds.missed = missed  # type: ignore[attr-defined]
    return ds


def threshold(scores: Iterable[float], coef: float, lo: float, hi: float) -> float:
    """적응형 임계값. 운영 코드(compute_adaptive_threshold)와 같은 식이다."""
    xs = list(scores)
    if not xs:
        return hi
    mean = statistics.mean(xs)
    stdev = statistics.pstdev(xs) if len(xs) > 1 else 0.0
    return max(lo, min(hi, mean - coef * stdev))


def judge(score: float, t: float, gap: float) -> str:
    if score >= t:
        return "채택"
    if score <= t - gap:
        return "기각"
    return "애매"


def run(
    ds: Dataset,
    *,
    coef: float = CUR_COEF,
    clamp: tuple[float, float] = CUR_CLAMP,
    gap: float = CUR_REJECT_GAP,
    rule: str = "min",
    batch_size: int | None = None,
) -> dict[str, int]:
    """한 설정으로 데이터셋 전체를 판정하고 채택/애매/기각 수를 센다.

    batch_size를 주면 그 크기로 나눠 배치별 임계값을 따로 계산한다. 운영 코드는
    '검색 한 회차'를 배치로 묶지만 데이터셋에는 회차 정보가 없다. 배치 경계를 모르는
    것이 이 분석의 한계이므로, 크기를 바꿔가며 결론이 흔들리는지 확인하는 데 쓴다."""
    combined = [p.combine(rule) for p in ds.pairs]
    n = len(combined)
    counts = {"채택": 0, "애매": 0, "기각": 0}
    size = batch_size or n
    for start in range(0, n, size):
        chunk = combined[start:start + size]
        t = threshold(chunk, coef, *clamp)
        for s in chunk:
            counts[judge(s, t, gap)] += 1
    return counts


def _fmt(c: dict[str, int], n: int) -> str:
    return (f"채택 {c['채택']:3d} ({c['채택']/n*100:4.1f}%) · "
            f"애매 {c['애매']:3d} ({c['애매']/n*100:4.1f}%) · "
            f"기각 {c['기각']:3d} ({c['기각']/n*100:4.1f}%)")


# ══════════════════════════════════════════════════════════════════════
#  실험 1 — 배치 크기
#
#  운영 코드는 "검색 한 회차에서 새로 저장한 fact"를 한 배치로 묶어 임계값을 계산한다.
#  즉 fact 하나의 판정이 같은 배치에 있는 다른 fact의 점수에 의존한다. 그런데 저장된
#  데이터에는 회차 정보가 없어서 배치 경계를 알 수 없다.
#
#  이 실험은 그 무지를 정면으로 다룬다. 배치 크기를 바꿔가며 판정 분포가 얼마나 움직이는지
#  재고, 실제 운영 결과를 재현하는 크기를 역으로 찾는다.
# ══════════════════════════════════════════════════════════════════════

def exp_batch_size(ds: Dataset, observed: dict[str, int] | None = None) -> None:
    n = len(ds)
    print("\n[실험 1] 배치 크기가 판정에 미치는 영향")
    print("  운영 코드는 검색 회차 단위로 배치를 묶는다. 데이터에 회차 정보가 없어")
    print("  경계를 모르므로, 크기를 바꿔가며 흔들림의 폭을 본다.\n")
    print(f"  {'배치크기':>8}  {'채택':>12} {'애매':>12} {'기각':>12}   임계값 예시")
    rows = []
    for size in (5, 8, 10, 15, 20, 30, 50, n):
        if size > n:
            continue
        c = run(ds, batch_size=size)
        t0 = threshold([p.combine("min") for p in ds.pairs[:size]], CUR_COEF, *CUR_CLAMP)
        label = f"{size}" + (" (전체)" if size == n else "")
        print(f"  {label:>8}  {c['채택']:5d} ({c['채택']/n*100:4.1f}%) "
              f"{c['애매']:5d} ({c['애매']/n*100:4.1f}%) "
              f"{c['기각']:5d} ({c['기각']/n*100:4.1f}%)   {t0:.3f}")
        rows.append((size, c))

    spread = max(c["채택"] for _, c in rows) - min(c["채택"] for _, c in rows)
    print(f"\n  → 배치 크기만 바꿔도 채택 수가 {spread}건({spread/n*100:.0f}%p) 움직인다.")
    if spread / n > 0.15:
        print("     파라미터 민감도를 논하기 전에, 배치 경계가 이미 최대 변수다.")

    if observed:
        print(f"\n  운영 실측: 채택 {observed['채택']} · 애매 {observed['애매']} · 기각 {observed['기각']}")
        best, err = None, None
        for size in range(2, n + 1):
            c = run(ds, batch_size=size)
            e = sum(abs(c[k] - observed[k]) for k in observed)
            if err is None or e < err:
                best, err = (size, c), e
        size, c = best  # type: ignore[misc]
        print(f"  가장 가까운 배치 크기: {size}  →  {_fmt(c, n)}  (오차 {err}건)")
        print("  이 값이 '실제 회차당 fact 수'의 추정치다. 회차 정보를 저장하면 추정이 불필요해진다.")


# ══════════════════════════════════════════════════════════════════════
#  실험 2 — 계수 k (평균 − k·표준편차)
#
#  MAIN-RAG 원문은 공식만 제시하고 계수는 정하지 않았다. 0.5는 우리가 고른 값이다.
# ══════════════════════════════════════════════════════════════════════

def exp_coefficient(ds: Dataset, batch_size: int) -> None:
    n = len(ds)
    print("\n[실험 2] 계수 k — 표준편차를 얼마나 빼는가")
    print("  공식(평균 − k·표준편차)은 MAIN-RAG 원문에서 확인. k=0.5는 자체 설계.\n")
    print(f"  {'k':>5}  {'채택':>12} {'애매':>12} {'기각':>12}   기준선 대비")
    base = run(ds, coef=CUR_COEF, batch_size=batch_size)
    for k in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
        c = run(ds, coef=k, batch_size=batch_size)
        d = c["채택"] - base["채택"]
        mark = " ← 현재" if k == CUR_COEF else (f" {d:+d}건" if d else " 동일")
        print(f"  {k:>5}  {c['채택']:5d} ({c['채택']/n*100:4.1f}%) "
              f"{c['애매']:5d} ({c['애매']/n*100:4.1f}%) "
              f"{c['기각']:5d} ({c['기각']/n*100:4.1f}%)  {mark}")
    lo = run(ds, coef=0.3, batch_size=batch_size)["채택"]
    hi = run(ds, coef=0.7, batch_size=batch_size)["채택"]
    print(f"\n  → k를 0.3~0.7로 흔들면 채택 수가 {abs(hi-lo)}건 변한다"
          f" ({abs(hi-lo)/n*100:.1f}%p).")
    if abs(hi - lo) / n < 0.05:
        print("     이 구간은 평평하다. 0.5를 고른 것이 결과를 좌우하지 않는다는 뜻이다.")


# ══════════════════════════════════════════════════════════════════════
#  실험 3 — clamp 범위
#
#  정수 점수에서 clamp 하한 3.0은 "3점 fact를 채택할 것인가"라는 이진 스위치로
#  작동한다(3.001과 3.999가 동일한 결과를 낸다). 하한이 곧 최대 변수다.
# ══════════════════════════════════════════════════════════════════════

def exp_clamp(ds: Dataset, batch_size: int) -> None:
    n = len(ds)
    print("\n[실험 3] clamp 범위 — 임계값의 상·하한")
    print("  정수 점수에서 3.001과 3.999는 같은 결과를 낸다. 즉 하한이 정확히 3.0인지가")
    print("  '3점 fact를 채택하는가'를 가르는 스위치다.\n")
    print(f"  {'범위':>14}  {'채택':>12} {'애매':>12} {'기각':>12}")
    for lo, hi, label in ((3.0, 4.0, "3.0~4.0 ← 현재"),
                          (3.1, 4.0, "3.1~4.0"),
                          (3.5, 4.0, "3.5~4.0"),
                          (2.0, 5.0, "2.0~5.0 (느슨)"),
                          (1.0, 5.0, "clamp 없음")):
        c = run(ds, clamp=(lo, hi), batch_size=batch_size)
        print(f"  {label:>14}  {c['채택']:5d} ({c['채택']/n*100:4.1f}%) "
              f"{c['애매']:5d} ({c['애매']/n*100:4.1f}%) "
              f"{c['기각']:5d} ({c['기각']/n*100:4.1f}%)")
    a = run(ds, clamp=(3.0, 4.0), batch_size=batch_size)["채택"]
    b = run(ds, clamp=(3.1, 4.0), batch_size=batch_size)["채택"]
    print(f"\n  → 하한을 3.0에서 3.1로 0.1만 올리면 채택이 {a}건 → {b}건"
          f" ({b-a:+d}건, {abs(b-a)/n*100:.1f}%p).")
    if abs(b - a) / n > 0.1:
        print("     계수보다 이 값이 훨씬 민감하다. 근거 없는 값 중 가장 위험한 것이다.")


# ══════════════════════════════════════════════════════════════════════
#  실험 4 — 기각 경계 (threshold − gap)
# ══════════════════════════════════════════════════════════════════════

def exp_reject_gap(ds: Dataset, batch_size: int) -> None:
    n = len(ds)
    print("\n[실험 4] 기각 경계 — threshold − gap")
    print(f"  {'gap':>5}  {'채택':>12} {'애매':>12} {'기각':>12}")
    for gap in (1, 2, 3):
        c = run(ds, gap=gap, batch_size=batch_size)
        mark = " ← 현재" if gap == CUR_REJECT_GAP else ""
        print(f"  {gap:>5}  {c['채택']:5d} ({c['채택']/n*100:4.1f}%) "
              f"{c['애매']:5d} ({c['애매']/n*100:4.1f}%) "
              f"{c['기각']:5d} ({c['기각']/n*100:4.1f}%){mark}")
    a = run(ds, gap=2, batch_size=batch_size)
    b = run(ds, gap=1, batch_size=batch_size)
    print(f"\n  → gap을 2에서 1로 바꿔도 기각이 {a['기각']}건 → {b['기각']}건.")
    if a["기각"] == b["기각"]:
        print("     아무 변화가 없다. 임계값이 4.0에 닿지 않는 한 기각은 '점수 1점'으로")
        print("     고정되므로, 이 매개변수는 사실상 상수 1과 같다. 죽은 파라미터다.")


# ══════════════════════════════════════════════════════════════════════
#  실험 5 — 결합 방식 (min vs 평균 vs 가중합 vs 기하평균)
#
#  가장 중요한 실험. min은 비보상적(non-compensatory) 결합이고, 평균은 보상적이다.
#  "관련성은 높지만 근거가 없는 fact"(= 환각의 전형)를 어떻게 처리하는지가 갈린다.
# ══════════════════════════════════════════════════════════════════════

def _verdicts(ds: Dataset, rule: str, batch_size: int) -> list[str]:
    """각 fact의 판정을 배치 단위로 계산해 순서대로 돌려준다.
    실험 5는 개별 fact의 운명 변화를 봐야 하므로 집계만으로는 부족하다."""
    combined = [p.combine(rule) for p in ds.pairs]
    out: list[str] = []
    size = batch_size or len(combined)
    for start in range(0, len(combined), size):
        chunk = combined[start:start + size]
        t = threshold(chunk, CUR_COEF, *CUR_CLAMP)
        out.extend(judge(s, t, CUR_REJECT_GAP) for s in chunk)
    return out


def exp_combine(ds: Dataset, batch_size: int) -> None:
    """결합 방식 비교.

    주의 — 이 함수는 처음에 결론 문구를 하드코딩해뒀다가 실측에 반박당했다.
    "평균 계열은 환각을 통과시킨다"고 미리 써뒀는데, 유럽 데이터에서는 네 방식 모두
    위험 유형을 0/5로 막았다. 미리 정한 결론을 출력하는 코드는 분석이 아니라 주장이다.
    지금은 판정 변화를 실제로 세어서 그 결과만 말한다."""
    n = len(ds)
    print("\n[실험 5] 결합 방식 — min을 쓸 근거가 있는가")
    print("  min은 비보상적 결합(한 축이 낮으면 다른 축이 못 메운다),")
    print("  평균은 보상적 결합(높은 축이 낮은 축을 메운다).\n")
    print(f"  {'결합':>10}  {'채택':>12} {'애매':>12} {'기각':>12}")
    rules = (("min", "min ← 현재"), ("geo", "기하평균"),
             ("mean", "산술평균"), ("w73", "0.3R+0.7G"))
    for rule, label in rules:
        c = run(ds, rule=rule, batch_size=batch_size)
        print(f"  {label:>10}  {c['채택']:5d} ({c['채택']/n*100:4.1f}%) "
              f"{c['애매']:5d} ({c['애매']/n*100:4.1f}%) "
              f"{c['기각']:5d} ({c['기각']/n*100:4.1f}%)")

    base = _verdicts(ds, "min", batch_size)

    # ① 위험 유형: 주제에는 맞지만 원문에 근거가 없다 = 환각의 전형
    risky = [i for i, p in enumerate(ds.pairs) if p.rel >= 4 and p.grd <= 2]
    print(f"\n  ① 위험 유형 — 관련성 ≥4 · 근거지지도 ≤2: {len(risky)}건")
    print("     (주제에는 딱 맞지만 원문에 근거가 없다 = 환각의 전형적 형태)")
    if risky:
        for rule, label in rules:
            v = _verdicts(ds, rule, batch_size)
            cnt = {k: sum(1 for i in risky if v[i] == k) for k in ("채택", "애매", "기각")}
            print(f"     {label:>10}: 채택 {cnt['채택']} · 애매 {cnt['애매']} · 기각 {cnt['기각']}")
        print("     → 채택이 0이라면 어느 결합을 써도 환각이 '검증됨' 도장을 받지는 않는다.")
        print("       그래도 기각과 애매의 차이는 남는다 — 애매는 사람이 다시 봐야 한다.")
        print("\n     예시:")
        for i in risky[:3]:
            pp = ds.pairs[i]
            print(f"       [관련성 {pp.rel} · 근거 {pp.grd}] {pp.text}")
    else:
        print("     이 데이터셋에는 해당 유형이 없다.")

    # ② min에서 다른 결합으로 바꿀 때 실제로 운명이 바뀌는 fact
    print("\n  ② min → 다른 결합으로 바꿀 때 판정이 바뀌는 fact")
    for rule, label in rules[1:]:
        v = _verdicts(ds, rule, batch_size)
        promoted = [i for i in range(n) if base[i] != "채택" and v[i] == "채택"]
        demoted = [i for i in range(n) if base[i] == "채택" and v[i] != "채택"]
        relaxed = [i for i in range(n) if base[i] == "기각" and v[i] != "기각"]
        print(f"     {label:>10}: 채택으로 승격 {len(promoted):3d}건 · "
              f"채택에서 하락 {len(demoted):3d}건 · 기각에서 완화 {len(relaxed):3d}건")
        if promoted:
            grd_low = sum(1 for i in promoted if ds.pairs[i].grd <= 3)
            print(f"     {'':10}  승격된 {len(promoted)}건 중 근거지지도 ≤3점이 "
                  f"{grd_low}건 ({grd_low/len(promoted)*100:.0f}%)")
            worst = min(promoted, key=lambda i: ds.pairs[i].grd)
            pw = ds.pairs[worst]
            print(f"     {'':10}  최저 근거 승격 예: [관련성 {pw.rel} · 근거 {pw.grd}] {pw.text[:44]}")

    print("\n     → 승격된 fact의 근거지지도가 낮을수록, 그 결합은 '관련성으로 근거를")
    print("       메워주는' 성질이 강하다. min을 쓰는 이유는 그 보상을 막는 것이다.")
    print("       다만 이것은 min이 최적이라는 증명이 아니라, min이 무엇을 막는지에 대한")
    print("       설명이다. 최적 결합은 사람 라벨과의 정렬도를 재야 알 수 있다.")


# ══════════════════════════════════════════════════════════════════════
#  실험 6 — 교차 데이터셋 재현성
#
#  이 분석의 핵심 방어선. 데이터셋마다 채점 모델과 루브릭이 달라(교란) 절대값은 비교할
#  수 없지만, "같은 결론이 여러 도메인에서 반복되는가"는 물을 수 있다. 조건이 다른데도
#  같은 결론이 나온다면 그 결론은 도메인·모델에 의존하지 않는다는 뜻이다.
# ══════════════════════════════════════════════════════════════════════

def exp_cross(datasets: list[Dataset], batch_size: int) -> None:
    print("\n" + "=" * 72)
    print("[실험 6] 교차 데이터셋 재현성 — 결론이 도메인에 의존하는가")
    print("=" * 72)
    print("  채점 조건(solar-mini + 수정 전 루브릭)은 네 데이터셋이 동일하다.")
    print("  다만 검색 백엔드가 다르므로(북미=Brave, 유럽·한국=Tavily) 모인 fact의")
    print("  분포 자체가 다르다. 절대값보다 '민감도 크기가 재현되는가'를 볼 것.\n")

    print(f"  {'데이터셋':<16} {'n':>4}  {'계수 0.3→0.7':>14} {'하한 3.0→3.1':>14} "
          f"{'gap 2→1':>10} {'min→평균':>12}")
    print("  " + "-" * 76)
    verdict = {"coef": [], "clamp": [], "gap": [], "rule": []}
    for ds in datasets:
        n = len(ds)
        bs = min(batch_size, n)
        d_coef = abs(run(ds, coef=0.7, batch_size=bs)["채택"]
                     - run(ds, coef=0.3, batch_size=bs)["채택"]) / n * 100
        d_clamp = abs(run(ds, clamp=(3.1, 4.0), batch_size=bs)["채택"]
                      - run(ds, clamp=(3.0, 4.0), batch_size=bs)["채택"]) / n * 100
        d_gap = abs(run(ds, gap=1, batch_size=bs)["기각"]
                    - run(ds, gap=2, batch_size=bs)["기각"]) / n * 100
        d_rule = abs(run(ds, rule="mean", batch_size=bs)["채택"]
                     - run(ds, rule="min", batch_size=bs)["채택"]) / n * 100
        verdict["coef"].append(d_coef)
        verdict["clamp"].append(d_clamp)
        verdict["gap"].append(d_gap)
        verdict["rule"].append(d_rule)
        print(f"  {ds.name:<16} {n:>4}  {d_coef:>13.1f}%p {d_clamp:>13.1f}%p "
              f"{d_gap:>9.1f}%p {d_rule:>11.1f}%p")

    print("\n  결론 재현성")
    labels = {"coef": "계수 k (0.3~0.7)", "clamp": "clamp 하한 (3.0→3.1)",
              "gap": "기각 경계 (2→1)", "rule": "결합 방식 (min→평균)"}
    for key, label in labels.items():
        vals = verdict[key]
        lo, hi = min(vals), max(vals)
        if hi < 3:
            note = "모든 도메인에서 영향 미미 — 값 선택이 결과를 좌우하지 않는다"
        elif lo > 10:
            note = "모든 도메인에서 영향 큼 — 근거가 반드시 필요한 값"
        else:
            note = "도메인에 따라 다름 — 단일 도메인 결론을 일반화할 수 없다"
        print(f"    {label:<22} {lo:4.1f}~{hi:4.1f}%p   {note}")

    print("\n  데이터셋 조건(교란 요인)")
    for ds in datasets:
        print(f"    {ds.name:<16} {ds.topic} / {ds.market}")
        if ds.note:
            print(f"    {'':16} {ds.note}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="데이터셋 JSON. 생략하면 eval/datasets/*.json")
    ap.add_argument("--batch-size", type=int, default=10,
                    help="배치 크기 (기본 10). 실험 1이 실측 재현값을 추정해준다")
    ap.add_argument("--observed", type=str, default=None,
                    help="운영 실측 판정 수 '채택,애매,기각' — 배치 크기 역추정에 사용")
    args = ap.parse_args()

    paths = args.paths or sorted(glob.glob("eval/datasets/*.json"))
    if not paths:
        print("데이터셋이 없습니다. eval/datasets/*.json 을 확인하세요.")
        return

    datasets = [load(p) for p in paths]
    observed = None
    if args.observed:
        a, m, r = (int(x) for x in args.observed.split(","))
        observed = {"채택": a, "애매": m, "기각": r}

    for ds in datasets:
        print("\n" + "#" * 72)
        print(f"# {ds.name} — {ds.topic} / {ds.market}")
        print(f"# fact {len(ds)}쌍 (두 축 복원 실패 {getattr(ds, 'missed', 0)}건 제외)")
        print("#" * 72)
        exp_batch_size(ds, observed if len(datasets) == 1 else None)
        bs = min(args.batch_size, len(ds))
        exp_coefficient(ds, bs)
        exp_clamp(ds, bs)
        exp_reject_gap(ds, bs)
        exp_combine(ds, bs)

    if len(datasets) > 1:
        exp_cross(datasets, args.batch_size)

    print("\n" + "=" * 72)
    print("한계")
    print("=" * 72)
    print("  · 배치 경계를 모른다. 운영 코드는 검색 회차로 묶지만 데이터에 회차 정보가")
    print("    없다. 실험 1이 보여주듯 이것이 가장 큰 변수이므로, 회차 ID를 저장하도록")
    print("    스키마를 고치는 것이 이 분석의 정확도를 올리는 가장 빠른 길이다.")
    print("  · 원문(source_content)을 저장하지 않으므로, 결함 수정 후 루브릭으로 같은")
    print("    표본을 재채점해 '수정 전후 판정 분포'를 비교할 수 없다.")
    print("  · 검색 백엔드가 데이터셋마다 다르다(북미=Brave, 유럽·한국=Tavily).")
    print("    채점 방식의 차이는 아니지만 모인 fact의 분포에는 영향을 준다.")
    print("  · 민감도가 낮다는 것은 '그 값이 안전하다'는 뜻이지 '그 값이 최적'이라는")
    print("    뜻이 아니다. 최적값은 사람 라벨과의 정렬도를 재야 알 수 있다.")


if __name__ == "__main__":
    main()
