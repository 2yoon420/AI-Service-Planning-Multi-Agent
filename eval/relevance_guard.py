"""관련성 축 안전망 검증 — 도메인 교차 변조실험.

## 왜 필요한가

2026-07-29 재실행에서 관련성 점수가 세 도메인 모두 5점에 몰렸다.

    한국 HMR    5점 98%   (쓰인 등급 2/5)
    유럽 포장재  5점 93%   (쓰인 등급 3/5)
    북미 웨어러블 5점 89%   (쓰인 등급 4/5)

그리고 `min(관련성, 근거지지도)`에서 **근거지지도가 96~98%의 판정을 혼자 결정**한다.
2축 설계가 사실상 1축으로 퇴화한 것이다.

**그런데 이것이 결함인지 정상인지 확정되지 않았다.** 해석이 둘로 갈린다.

  정상 — fact는 그 주제로 검색해 모은 것이다. 기저율이 원래 100%에 가깝다.
         관련성 축은 검색이 실패했을 때 잡는 안전망이고, 평소 안 울리는 게 맞다.
  고장 — 축이 변별력을 잃어 결합이 무의미해졌고 LLM 호출 절반을 낭비하고 있다.

**둘을 가르는 측정을 한 적이 없다.** 그래서 프롬프트를 고치면 무엇을 고치는지 모른 채
고치는 것이 된다.

## 방법 — 코드 변조실험의 데이터 판

이 프로젝트는 *"테스트가 통과한다"* 를 믿지 않고 코드를 일부러 망가뜨려 테스트가
잡는지 확인했다(변조실험 56종). 같은 논리를 데이터에 적용한다.

    한국 HMR 채점기에  ← 유럽 포장재 fact를 섞는다
    유럽 포장재 채점기에 ← 북미 웨어러블 fact를 섞는다
    북미 웨어러블 채점기에 ← 한국 HMR fact를 섞는다

명백히 무관한 fact다. 관련성 축이 이것들을 낮게 주면 안전망이 작동하는 것이고,
5점을 주면 축이 실제로 고장난 것이다.

## 판정 기준을 미리 고정한다

실험 후에 기준을 정하면 결과에 맞춰 해석하게 된다. 먼저 적어둔다.

    이물 fact의 관련성 중앙값이 2점 이하        → 안전망 작동 (유지)
    이물 fact의 채택률(>=4점)이 10% 미만         → 안전망 작동 (유지)
    위 둘 중 하나라도 어기면                     → 결함 I 후보 (조사 필요)
    이물 fact의 채택률이 50% 이상               → 결함 I 확정 (축이 무의미)

## 한계

  · **이물 fact는 "완전히 무관"이라 쉬운 문제다.** 실제 검색 실패는 "인접 주제"로
    새는 경우가 더 많다(예: 시니어 HMR을 찾다가 일반 HMR 자료를 가져오는 것).
    이 실험이 통과해도 **경계 사례를 잡는다는 보장은 없다.**
  · region을 원래 값 그대로 넘긴다. 유럽 fact를 한국 채점에 넣으면 region이
    '유럽'이므로 지역 규칙이 먼저 걸린다 — 즉 이 실험은 **주제 판단과 지역 판단을
    분리하지 못한다.** 그래서 `--strip-region` 으로 지역을 지운 조건도 함께 돌린다.
  · 1회 채점이다. 흔들림을 재지 않는다.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.verification import ACCEPT_MIN_SCORE, VERIFICATION_MODEL, grade_fact  # noqa: E402
from eval.judge_self_test import client_for  # noqa: E402

# (채점 조건 topic, target_market) ← 이물을 가져올 topic
PAIRS = [
    ("시니어 가정간편식(HMR)", "한국 시니어 케어푸드 시장", "친환경 포장재"),
    ("친환경 포장재", "유럽 B2B 유통 시장", "웨어러블 헬스케어 기기"),
    ("웨어러블 헬스케어 기기", "북미 시니어 건강관리 시장", "시니어 가정간편식(HMR)"),
]
SEED = 20260729


def out_path(strip_region: bool) -> Path:
    """조건별로 파일을 나눈다.

    처음에는 고정 경로 하나를 썼는데, 두 조건을 연달아 돌리자 **두 번째 실행이 첫
    번째 결과를 덮었다.** 요약 수치는 터미널에 남았지만 원본(fact별 점수와 이유)은
    사라졌다. 조건을 비교하려고 만든 스크립트가 비교 대상을 지운 것이다.
    이 프로젝트가 반복해 겪은 '재현 경로가 끊긴다'의 또 다른 형태다.
    """
    suffix = "_noregion" if strip_region else "_region"
    return Path(f"eval/label/relevance_guard{suffix}.json")


def load_by_topic(db: Path) -> dict[str, list[dict]]:
    import sqlite3
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = [json.loads(r["data_json"]) for r in conn.execute("SELECT data_json FROM facts")]
    conn.close()
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r.get("topic") or "", []).append(r)
    return by


def verdict(scores: list[int]) -> tuple[str, str]:
    """실험 전에 고정한 기준으로 판정한다."""
    med = statistics.median(scores)
    acc = sum(1 for s in scores if s >= ACCEPT_MIN_SCORE) / len(scores)
    if acc >= 0.50:
        return "결함 확정", f"이물 채택률 {acc*100:.0f}% — 관련성 축이 무관한 fact를 절반 이상 통과시킨다"
    if med <= 2 and acc < 0.10:
        return "안전망 작동", f"중앙값 {med:.0f}점 · 채택률 {acc*100:.0f}%"
    return "결함 후보", f"중앙값 {med:.0f}점 · 채택률 {acc*100:.0f}% — 기준(중앙값 ≤2, 채택률 <10%) 미달"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path, help="fact_store DB (신규 3도메인이 들어 있어야 한다)")
    ap.add_argument("--n", type=int, default=30, help="도메인당 이물 fact 수 (기본 30)")
    ap.add_argument("--model", default=VERIFICATION_MODEL)
    ap.add_argument("--strip-region", action="store_true",
                    help="이물 fact의 region을 지워 지역 규칙을 끄고 주제 판단만 본다")
    ap.add_argument("--reuse", action="store_true", help="저장된 결과로 보고만 재출력")
    args = ap.parse_args()

    if args.reuse:
        path = out_path(args.strip_region)
        if not path.exists():
            print(f"저장된 결과가 없습니다: {path}"); return 1
        saved = json.loads(path.read_text(encoding="utf-8"))
        print(f"저장된 결과 재사용: {saved['created_at']} · 모델 {saved['model']}"
              f" · strip_region={saved['strip_region']}")
        results = saved["results"]
    else:
        if not args.db.exists():
            print(f"DB가 없습니다: {args.db}"); return 1
        by = load_by_topic(args.db)
        missing = [t for _, _, t in PAIRS if t not in by] + [t for t, _, _ in PAIRS if t not in by]
        if missing:
            print("DB에 없는 topic:", sorted(set(missing)))
            print("있는 topic:", sorted(by))
            return 1

        client = client_for(args.model)
        rng = random.Random(SEED)
        results = []
        print(f"모델 {args.model} · 도메인당 {args.n}건 · "
              f"지역 {'제거' if args.strip_region else '유지'}\n")
        for topic, market, alien_topic in PAIRS:
            pool = by[alien_topic]
            sample = rng.sample(pool, min(args.n, len(pool)))
            print(f"  [{topic}] ← {alien_topic} {len(sample)}건 채점")
            rows = []
            for i, f in enumerate(sample, 1):
                region = None if args.strip_region else f.get("region")
                score, reason = grade_fact(client, f["text"], "", topic, market,
                                           "relevance", region)
                rows.append({"text": f["text"][:120], "region": region,
                             "score": score, "reason": reason[:200]})
                if i % 10 == 0 or i == len(sample):
                    print(f"    {i}/{len(sample)}", flush=True)
            results.append({"topic": topic, "market": market,
                            "alien_topic": alien_topic, "rows": rows})
        path = out_path(args.strip_region)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": args.model, "seed": SEED, "strip_region": args.strip_region,
            "results": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {path}")

    print("\n" + "=" * 78)
    print("관련성 축 안전망 검증 — 다른 도메인 fact를 섞으면 잡는가")
    print("=" * 78)
    print("  판정 기준(실험 전 고정): 중앙값 ≤2점 AND 채택률 <10% → 안전망 작동")
    print(f"                          채택률 ≥50% → 결함 확정 (채택 경계 {ACCEPT_MIN_SCORE}점)\n")
    print(f"  {'채점 조건':<22}{'이물 출처':<20}{'n':>4}{'중앙값':>7}{'채택률':>8}   판정")
    print("  " + "-" * 76)
    allscores = []
    for r in results:
        sc = [x["score"] for x in r["rows"]]
        allscores += sc
        v, why = verdict(sc)
        acc = sum(1 for s in sc if s >= ACCEPT_MIN_SCORE) / len(sc)
        print(f"  {r['topic']:<22}{r['alien_topic']:<20}{len(sc):>4}"
              f"{statistics.median(sc):>7.0f}{acc*100:>7.0f}%   {v}")

    print("\n  점수 분포 (전체 이물 fact)")
    d = Counter(allscores)
    for s in range(1, 6):
        n = d.get(s, 0)
        bar = "█" * int(n / max(1, len(allscores)) * 40)
        print(f"    {s}점 {n:>3}건 {bar}")
    acc_all = sum(1 for s in allscores if s >= ACCEPT_MIN_SCORE) / len(allscores)
    v, why = verdict(allscores)
    print(f"\n  종합: n={len(allscores)} · 중앙값 {statistics.median(allscores):.0f}점 · "
          f"채택률 {acc_all*100:.0f}%  →  **{v}**")
    print(f"        {why}")

    print("\n" + "=" * 78)
    print("한계 — 반드시 함께 보고할 것")
    print("=" * 78)
    for line in (
        "이물 fact는 '완전히 무관'이라 쉬운 문제다. 실제 검색 실패는 인접 주제로 새는",
        "  경우가 더 많다(시니어 HMR을 찾다가 일반 HMR 자료를 가져오는 것). 이 실험을",
        "  통과해도 경계 사례를 잡는다는 보장은 없다.",
        "지역 규칙과 주제 판단이 섞인다. 유럽 fact를 한국 채점에 넣으면 region이 '유럽'",
        "  이라 지역 규칙이 먼저 걸린다. --strip-region 으로 지역을 지운 조건도 돌려",
        "  두 효과를 분리해야 한다.",
        "1회 채점이다. 흔들림을 재지 않았다.",
        "이 실험은 '관련성 축이 무관한 것을 거르는가'만 답한다. '유용한 것을 살리는가'는",
        "  묻지 않는다 — 그건 사람 라벨과의 정렬도(9-6절)가 답할 영역이다.",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
