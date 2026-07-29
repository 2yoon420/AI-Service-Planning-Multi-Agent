"""두 축 채점의 실운영 동작 분석 — 관련성 축이 변별력을 갖는가.

## 왜 이 스크립트가 필요했는가

2026-07-29에 결함 A~H 수정본으로 3개 도메인을 재실행했다. 한국 HMR 결과를 보다가
**관련성 점수가 123/126(97.6%) 5점**인 것을 발견했다. `min(관련성, 근거지지도)`에서
한 축이 사실상 상수면 결합할 것이 없다 — **2축 설계가 1축으로 퇴화한다.**

이 관찰이 한 도메인만의 것인지 도메인 일반적인지 확인해야 하는데, 그때 쓴 것은
터미널에 붙여넣은 임시 코드였다. **대화창에만 있는 분석은 재현되지 않는다** —
오늘 하루에만 같은 문제를 세 번 겪었다(`agreement.py` 진입점 없음, 민감도 표에
배치 조건 없음, 데이터셋이 즉석 추출). 그래서 스크립트로 옮긴다.

## 무엇을 보는가

1. **판정 분포** — 수정 전 대비 채택/애매/기각이 어떻게 움직였나
2. **필드 채움률** — `region`·`source_excerpt`가 실제로 채워지는가(결함 G·H 배선 확인)
3. **두 축 교차표** — 관련성과 근거지지도가 각각 변별력을 갖는가
4. **병목 분석** — `min` 결합에서 어느 축이 판정을 결정하는가

## 한계

  · 신·구 데이터는 **같은 fact가 아니다.** 웹 검색 결과가 달라 fact 자체가 다르다.
    분포 비교이지 같은 표본 전후 비교가 아니다(그건 `rescore_relevance.py`가 한다).
  · 점수는 `verification_reasoning` 문자열에서 정규식으로 뽑는다. 형식이 바뀌면
    조용히 실패하므로, 추출 실패 건수를 항상 함께 출력한다.
  · 사전기각된 fact(결함 F 경로)는 두 축 점수가 없다. 실패 건수에 포함된다.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

SCORE_PAT = re.compile(r"\[관련성 (\d)점.*?\[근거지지도 (\d)점", re.S)

# 수정 전 실측 (구버전 데이터셋). (n, 채택, 애매, 기각)
BASELINE = {
    "시니어 가정간편식(HMR)": (140, 94, 37, 9),
    "친환경 포장재": (200, 128, 40, 15),
    "웨어러블 헬스케어 기기": (82, 63, 18, 1),
}


def load(db: Path) -> dict[str, list[dict]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = [json.loads(r["data_json"]) for r in conn.execute("SELECT data_json FROM facts")]
    conn.close()
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r.get("topic") or "(없음)", []).append(r)
    return by


def scores(facts: list[dict]) -> tuple[Counter, int]:
    """(관련성, 근거지지도) 쌍 카운터와 추출 실패 건수."""
    c, miss = Counter(), 0
    for f in facts:
        m = SCORE_PAT.search(f.get("verification_reasoning") or "")
        if not m:
            miss += 1
            continue
        c[(int(m.group(1)), int(m.group(2)))] += 1
    return c, miss


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path)
    ap.add_argument("--topic", action="append", default=None,
                    help="분석할 topic. 생략하면 BASELINE에 있는 3개")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB가 없습니다: {args.db}")
        return 1
    by = load(args.db)
    topics = args.topic or [t for t in BASELINE if t in by]
    if not topics:
        print("분석할 topic이 DB에 없습니다. 있는 것:", list(by))
        return 1

    section("1. 판정 분포 — 수정 전(solar-mini + clamp) 대비")
    print(f"  {'도메인':<22}{'n':>5}{'채택':>7}{'애매':>7}{'기각':>7}{'채택률':>9}{'수정 전':>10}{'변화':>8}")
    print("  " + "-" * 74)
    for t in topics:
        f = by[t]
        st = Counter(x.get("verification_status") for x in f)
        n = len(f)
        a, m, x = st.get("채택", 0), st.get("애매", 0), st.get("기각", 0)
        line = f"  {t:<22}{n:>5}{a:>7}{m:>7}{x:>7}{a/n*100:>8.1f}%"
        if t in BASELINE:
            on, oa, _, _ = BASELINE[t]
            line += f"{oa/on*100:>9.1f}%{a/n*100 - oa/on*100:>+7.1f}p"
        print(line)
    print("\n  주의: 신·구는 같은 fact가 아니다(검색 결과가 다르다). 분포 비교다.")

    section("2. 필드 채움률 — 결함 G·H가 수집 경로에 실제로 걸렸는가")
    for t in topics:
        f = by[t]
        n = len(f)
        reg = sum(1 for x in f if x.get("region"))
        exc = sum(1 for x in f if x.get("source_excerpt"))
        print(f"\n  {t}  (n={n})")
        print(f"    region         {reg:>4}/{n} ({reg/n*100:>5.1f}%)")
        print(f"    source_excerpt {exc:>4}/{n} ({exc/n*100:>5.1f}%)")
        print("    지역 분포: " + " · ".join(
            f"{k} {v}" for k, v in Counter(x.get("region") or "불명" for x in f).most_common()))

    section("3. 두 축 교차표 — 각 축이 변별력을 갖는가")
    for t in topics:
        c, miss = scores(by[t])
        tot = sum(c.values())
        if not tot:
            print(f"\n  {t}: 점수 추출 0건"); continue
        rels = Counter(k[0] for k in c.elements())
        grds = Counter(k[1] for k in c.elements())
        print(f"\n  {t}  (채점 {tot}건 · 사전기각 등 추출 실패 {miss}건)")
        헤더 = "관련성\\근거"
        print(f"    {헤더:>10}" + "".join(f"{s}점".rjust(6) for s in range(1, 6)) + f"{'계':>7}")
        print("    " + "-" * 48)
        for rel in range(5, 0, -1):
            row = [c.get((rel, g), 0) for g in range(1, 6)]
            if sum(row):
                print(f"    {rel}점{'':>7}" + "".join(f"{v if v else '·':>6}" for v in row)
                      + f"{sum(row):>7}")
        for name, dist in (("관련성", rels), ("근거지지도", grds)):
            top_s, top_n = dist.most_common(1)[0]
            사용된_점수 = sum(1 for s in range(1, 6) if dist.get(s))
            판정 = "★상수에 가까움 — 변별력 없음" if top_n / tot >= 0.9 else (
                   "쏠림 있음" if top_n / tot >= 0.6 else "분포함")
            print(f"    {name:<6}: " + " · ".join(f"{s}점 {dist.get(s,0):>3}" for s in range(1, 6))
                  + f"   최빈 {top_s}점 {top_n/tot*100:>4.0f}% · 쓰인 등급 {사용된_점수}/5  {판정}")

    section("4. 병목 분석 — min 결합에서 어느 축이 판정을 정하는가")
    print(f"  {'도메인':<22}{'근거지지도':>10}{'관련성':>9}{'동점':>7}{'근거 지배율':>12}")
    print("  " + "-" * 62)
    for t in topics:
        c, _ = scores(by[t])
        tot = sum(c.values()) or 1
        bg = sum(v for (rl, g), v in c.items() if g < rl)
        br = sum(v for (rl, g), v in c.items() if rl < g)
        tie = tot - bg - br
        결정 = bg + tie  # 동점이면 근거지지도가 곧 min이다
        print(f"  {t:<22}{bg:>10}{br:>9}{tie:>7}{결정/tot*100:>11.0f}%")
    print("\n  '근거 지배율' = 근거지지도가 min을 결정한 비율(동점 포함).")
    print("  이 값이 90%를 넘으면 관련성 축은 사실상 판정에 관여하지 않는다.")

    section("한계 — 반드시 함께 보고할 것")
    for line in (
        "신·구 데이터는 같은 fact가 아니다. 검색 결과가 달라 fact 자체가 다르므로",
        "  분포 비교이지 같은 표본 전후 비교가 아니다(그건 rescore_relevance.py가 한다).",
        "관련성 축이 상수에 가깝다는 것이 곧 '쓸모없다'는 뜻은 아니다. 검색이 주제를",
        "  벗어났을 때 잡는 안전망이라면, 검색이 잘 되는 동안 발동하지 않는 것이 정상이다.",
        "  다만 그렇다면 그 값어치를 '평소 통과율'이 아니라 '실패 시 잡는가'로 재야 하는데,",
        "  그 측정을 한 적이 없다.",
        "점수는 reasoning 문자열에서 정규식으로 뽑는다. 형식이 바뀌면 조용히 실패하므로",
        "  추출 실패 건수를 함께 본다. 사전기각분(결함 F)은 원래 점수가 없다.",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
