"""Router 6-way 분류 골든셋 — 실행과 집계.

## 무엇을 재는가

세 가지를 함께 본다. **정확도만 재면 신뢰성을 과대평가한다** — 모델 비교(검증 총정리
6절)에서 이미 겪었다. 1회 측정에서는 solar-mini가 1위였는데 3회 반복하자 순위가 뒤집혔다.

| 지표 | 왜 필요한가 |
|---|---|
| **정확도** | 기본 분류 능력 |
| **혼동 행렬** | 어느 action이 어느 action으로 새는가 — 프롬프트 수정의 재료 |
| **판정 뒤집힘** (pass^k) | 같은 발화가 실행마다 다르게 분류되는가. τ-bench의 pass^k 개념 |

정확도가 같아도 **뒤집힘이 있으면 운영에서 재현되지 않는다.** 같은 말을 두 번 했는데
한 번은 경쟁사가 돌고 한 번은 PESTEL이 도는 것은 정확도 숫자에 안 나타난다.

## 층별로 따로 보는 이유

전체 정확도 하나로 뭉치면 **어떤 종류의 판단이 약한지** 알 수 없다.

  · 명확(clear)     — 여기서 틀리면 기본 분류가 안 되는 것이다. 가장 심각.
  · 경계(boundary)  — 코드가 선언한 규칙을 지키는가. 여기서 틀리면 문서와 동작이 어긋난다.
  · 모호(ambiguous) — 넘겨짚지 않고 되묻는가. 여기서 틀리면 **명시적 지시 위반**이다.

특히 모호 층의 오답은 성격이 다르다. 프롬프트가 *"대충 짐작해서 다른 action을 고르지
마세요"* 라고 못 박았으므로, 취향 차이가 아니라 계약 위반이다.

## revision_count 누출

프롬프트에 `revision_count`가 들어가지만 판단 규칙 1~6에는 쓰이지 않는다(상한 도달 시
종료는 `router_node`가 LLM 호출 **전에** 처리한다). 같은 발화를 0과 4로 넣어 답이
달라지면 누출이며, `LEAK_PAIRS`로 짝지어 비교한다.

## 한계 (반드시 함께 보고할 것)

  · **개발자가 쓴 발화는 실사용자 발화 분포가 아니다.** 골든셋 100%여도 실사용 정확도는
    별개다 — 검증 총정리 2절의 *"pytest 통과 ≠ 판단 정확"* 과 같은 구조다.
  · **경계 케이스의 정답을 코드 주석에서 도출했다.** 주석이 곧 사양이라는 전제다.
    모델이 일관되게 다른 답을 고르고 그게 더 자연스럽다면, **고칠 대상은 모델이 아니라
    주석일 수도 있다.**
  · 케이스 42개는 작다. 층별로 나누면 모호 7개·경계 12개뿐이다.
  · `target_query`·`reasoning`·`user_facing_reply` 내용의 품질은 재지 않는다.
    action 하나만 본다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.router import HEAVY_MODEL, decide_next_action  # noqa: E402
from eval.cases_router import (  # noqa: E402
    ACTIONS,
    CASES,
    LEAK_PAIRS,
    Case,
    summary,
    verdict,
)
from eval.judge_self_test import client_for  # noqa: E402

OUT_DIR = Path("eval/label")
OUT = OUT_DIR / "router_goldenset.json"          # 최신 결과 (--reuse 대상)


def archive_path(created_at: str, model: str, repeat: int) -> Path:
    """실행마다 별도 파일로도 남긴다.

    ## 왜 뒤늦게 붙였는가

    이 스크립트는 처음에 고정 경로 하나만 썼다. 그래서 **두 번째 실행이 첫 번째 원본을
    덮었다.** 두 실행의 정확도가 99.5% vs 99.0%로 달랐는데, 첫 실행의 fact별 원본이
    사라져 차이를 케이스 단위로 추적할 수 없었다.

    **오늘 오전에 `relevance_guard.py`에서 똑같은 문제를 고쳤다**(두 조건이 같은 파일에
    저장돼 비교 대상을 덮음). 그 교훈을 이 스크립트에 적용하지 않았다 — 같은 실수를
    같은 날 두 번 했다.

    실행 간 변동을 재려면 **여러 실행의 원본이 함께 남아 있어야** 한다. 5회 반복은
    케이스 내 흔들림만 잡고 실행 간 흔들림은 잡지 못한다.
    """
    stamp = created_at.replace(":", "").replace("-", "").replace("+0000", "Z")
    return OUT_DIR / f"router_goldenset_{stamp}_{model}_r{repeat}.json"
SHORT = {"approve": "appr", "revise_market_research": "mres", "revise_pestel": "pest",
         "revise_competitor": "comp", "capability_question": "capq", "unclear": "uncl"}


def run_case(case: Case, client, model: str, repeat: int,
             sleep: float) -> tuple[list[str], list[bool | None]]:
    """(action 목록, needs_new_search 목록)을 함께 돌려준다.

    2026-07-29에 스키마를 바꿔 `needs_new_search`를 첫 필드로 넣었다(premature
    serialization 대응). 이 값을 함께 기록하면 **효과를 분리**할 수 있다.

      needs_new_search=true 인데 action=revise_pestel → 판단은 맞고 action이 안 따라옴
      needs_new_search=false                        → 판단부터 틀림

    둘은 처방이 다르다. 앞은 코드 안전망으로 교정 가능하고, 뒤는 프롬프트 문제다.
    """
    acts: list[str] = []
    flags: list[bool | None] = []
    for _ in range(repeat):
        try:
            d = decide_next_action(case.message, case.revision_count, client=client)
            acts.append(d.get("action", "(응답없음)"))
            flags.append(d.get("needs_new_search"))
        except Exception as e:
            acts.append(f"(오류:{type(e).__name__})")
            flags.append(None)
        if sleep:
            time.sleep(sleep)
    return acts, flags


def section(t: str) -> None:
    print("\n" + "=" * 78); print(t); print("=" * 78)


def report(results: dict[str, list[str]], repeat: int,
           flags: dict[str, list] | None = None) -> None:
    by_id = {c.id: c for c in CASES}

    section("1. 층별 정확도 — 뭉치면 어디가 약한지 알 수 없다")
    print(f"  {'층':<12}{'케이스':>6}{'채점':>7}{'정답':>7}{'정확도':>9}   성격")
    print("  " + "-" * 72)
    NOTE = {"clear": "기본 분류. 틀리면 가장 심각",
            "boundary": "코드가 선언한 규칙을 지키는가",
            "ambiguous": "넘겨짚지 않는가 — 오답은 명시적 지시 위반"}
    for layer in ("clear", "boundary", "ambiguous"):
        cs = [c for c in CASES if c.layer == layer]
        tot = ok = 0
        for c in cs:
            for a in results.get(c.id, []):
                tot += 1
                ok += verdict(c, a)
        acc = ok / tot * 100 if tot else 0
        print(f"  {layer:<12}{len(cs):>6}{tot:>7}{ok:>7}{acc:>8.1f}%   {NOTE[layer]}")
    tot = sum(len(v) for v in results.values())
    ok = sum(verdict(by_id[i], a) for i, v in results.items() for a in v)
    print("  " + "-" * 72)
    print(f"  {'전체':<12}{len(CASES):>6}{tot:>7}{ok:>7}{ok/tot*100:>8.1f}%")

    section("2. 판정 뒤집힘 — 같은 발화가 실행마다 다르게 분류되는가")
    flips = [(i, v) for i, v in results.items() if len(set(v)) > 1]
    print(f"  반복 {repeat}회 기준 · 뒤집힌 케이스 {len(flips)}/{len(CASES)}개\n")
    if not flips:
        print("  없음 — 모든 케이스가 반복에서 같은 action을 냈다(재현 가능)")
    else:
        for i, v in sorted(flips):
            c = by_id[i]
            dist = " / ".join(f"{SHORT.get(a, a)}×{n}" for a, n in Counter(v).most_common())
            hit = sum(verdict(c, a) for a in v)
            print(f"  [{i}] {c.message[:38]}")
            print(f"       정답 {SHORT[c.expect]} · 관측 {dist} · 맞은 횟수 {hit}/{len(v)}")
        print("\n  → 정확도가 같아도 뒤집힘이 있으면 운영에서 재현되지 않는다.")
        print("     같은 말을 두 번 했는데 한 번은 경쟁사가, 한 번은 PESTEL이 돈다.")

    section("3. 혼동 행렬 — 어느 action이 어느 action으로 새는가")
    mat: dict[tuple[str, str], int] = defaultdict(int)
    for i, v in results.items():
        for a in v:
            mat[(by_id[i].expect, a)] += 1
    헤더 = "정답\\관측"
    print(f"    {헤더:<12}" + "".join(f"{SHORT[a]:>7}" for a in ACTIONS) + f"{'계':>6}")
    print("    " + "-" * 62)
    for exp in ACTIONS:
        row = [mat.get((exp, obs), 0) for obs in ACTIONS]
        if not sum(row):
            continue
        cells = "".join(f"{v if v else '·':>7}" for v in row)
        print(f"    {SHORT[exp]:<12}{cells}{sum(row):>6}")
    off = [(e, o, n) for (e, o), n in mat.items() if e != o and n]
    if off:
        print("\n  주요 오분류 (프롬프트 수정의 재료)")
        for e, o, n in sorted(off, key=lambda x: -x[2])[:8]:
            print(f"    {SHORT[e]} → {SHORT[o]}  {n}회")

    section("4. revision_count 누출 — 상한 근접이 판단을 바꾸는가")
    print("  프롬프트에 값이 들어가지만 판단 규칙에는 쓰이지 않는다.")
    print("  같은 발화를 0과 4로 넣어 답이 달라지면 누출이다.\n")
    leaked = 0
    for leak_id, base_id in LEAK_PAIRS:
        lv, bv = results.get(leak_id, []), results.get(base_id, [])
        if not lv or not bv:
            print(f"  [{leak_id}] 결과 없음"); continue
        lm = Counter(lv).most_common(1)[0][0]
        bm = Counter(bv).most_common(1)[0][0]
        same = lm == bm
        leaked += (not same)
        print(f"  {by_id[base_id].message[:34]:<36} "
              f"count=0 → {SHORT.get(bm, bm):<5} count=4 → {SHORT.get(lm, lm):<5} "
              f"{'일치' if same else '★누출'}")
    print(f"\n  누출 {leaked}/{len(LEAK_PAIRS)}건")

    if flags:
        section("4-2. needs_new_search — 판단과 action이 어긋나는가 (효과 분리)")
        print("  스키마 첫 필드로 '새 검색이 필요한가'를 먼저 확정하게 했다.")
        print("  이 값과 action을 대조하면 오답의 성격이 갈린다.\n")
        mism = agree_t = agree_f = none_n = 0
        rows = []
        for i, fs in flags.items():
            c = by_id.get(i)
            if c is None:
                continue
            acts = results.get(i, [])
            for f, a in zip(fs, acts):
                if f is None:
                    none_n += 1
                elif f and a == "revise_pestel":
                    mism += 1
                    rows.append((i, c.message, a))
                elif f:
                    agree_t += 1
                else:
                    agree_f += 1
        print(f"    needs_new_search=true  이면서 action=revise_pestel : {mism:>3}건  ★어긋남")
        print(f"    needs_new_search=true  이면서 그 외 action         : {agree_t:>3}건")
        print(f"    needs_new_search=false                            : {agree_f:>3}건")
        if none_n:
            print(f"    값 없음(구버전 결과·오류)                          : {none_n:>3}건")
        if mism:
            print("\n  → 판단은 맞았고 action이 따라오지 않았다. **코드 안전망으로 교정 가능하다**:")
            print("       if action == 'revise_pestel' and needs_new_search: action = 'revise_market_research'")
            seen = set()
            for i, msg, a in rows:
                if i in seen:
                    continue
                seen.add(i)
                print(f"       [{i}] {msg[:44]}")
        else:
            print("\n  → 어긋남 없음. needs_new_search와 action이 일관된다.")

    section("5. 오답 전수 — 무엇을 왜 틀렸는가")
    wrong = [(i, a) for i, v in results.items() for a in v if not verdict(by_id[i], a)]
    if not wrong:
        print("  없음")
    else:
        seen = set()
        for i, a in wrong:
            if (i, a) in seen:
                continue
            seen.add((i, a))
            c = by_id[i]
            n = sum(1 for j, b in wrong if j == i and b == a)
            allow = f" (관용: {', '.join(SHORT[x] for x in c.also_acceptable)})" if c.also_acceptable else ""
            print(f"\n  [{i}·{c.layer}] {c.message}")
            print(f"    정답 {SHORT[c.expect]}{allow} · 관측 {SHORT.get(a, a)} ({n}/{len(results[i])}회)")
            print(f"    정답 근거: {c.why}")

    section("한계 — 반드시 함께 보고할 것")
    for line in (
        "개발자가 쓴 발화는 실사용자 발화 분포가 아니다. 골든셋 100%여도 실사용 정확도는",
        "  별개다 — 검증 총정리 2절의 'pytest 통과 ≠ 판단 정확'과 같은 구조다.",
        "경계 케이스의 정답을 코드 주석에서 도출했다. 주석이 곧 사양이라는 전제다.",
        "  모델이 일관되게 다른 답을 고르고 그게 더 자연스럽다면, 고칠 대상은 모델이",
        "  아니라 주석일 수도 있다.",
        "케이스 42개는 작다. 층별로 나누면 모호 7개·경계 12개뿐이다.",
        "action 하나만 본다. target_query·reasoning 품질은 재지 않았다.",
        "--repeat는 케이스 내 흔들림만 잡는다. 실행 간 변동은 별개다 — 같은 설정으로",
        "  두 번 돌려 99.5%와 99.0%가 나왔다(경계 100% vs 98.3%). 점 추정으로 보고하지",
        "  말고 여러 실행의 범위를 함께 볼 것. 모델 비교(검증 총정리 6절)에서 '단발 측정은",
        "  동전 던지기'라고 경고했던 것이 반복 실행 단위에서도 성립한다.",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=HEAVY_MODEL,
                    help=f"판단 모델 (기본 {HEAVY_MODEL} — router가 쓰는 HEAVY_MODEL)")
    ap.add_argument("--repeat", type=int, default=5,
                    help="같은 케이스를 몇 번 돌릴지 (기본 5). 1이면 뒤집힘을 못 본다")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true", help="케이스 목록만 확인(LLM 호출 없음)")
    ap.add_argument("--reuse", action="store_true", help="저장된 결과로 보고만 재출력")
    args = ap.parse_args()

    print(summary())
    if args.dry_run:
        for c in CASES:
            allow = f" | 관용 {','.join(SHORT[x] for x in c.also_acceptable)}" if c.also_acceptable else ""
            rc = f" | count={c.revision_count}" if c.revision_count else ""
            print(f"  [{c.id}·{c.layer[:4]}] {SHORT[c.expect]:<5}{allow}{rc}  {c.message}")
        return 0

    if args.reuse:
        if not OUT.exists():
            print(f"저장된 결과가 없습니다: {OUT}"); return 1
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        print(f"저장된 결과 재사용: {saved['created_at']} · 모델 {saved['model']} "
              f"· repeat {saved['repeat']}")
        report(saved["results"], saved["repeat"], saved.get("needs_new_search"))
        return 0

    client = client_for(args.model)
    print(f"모델 {args.model} · 반복 {args.repeat}회 · "
          f"예상 호출 {len(CASES) * args.repeat}회\n")
    results: dict[str, list[str]] = {}
    flags: dict[str, list] = {}
    for n, c in enumerate(CASES, 1):
        results[c.id], flags[c.id] = run_case(c, client, args.model, args.repeat, args.sleep)
        mark = "" if all(verdict(c, a) for a in results[c.id]) else "  ← 오답 포함"
        print(f"  [{n:>2}/{len(CASES)}] {c.id:<8} "
              f"{'/'.join(SHORT.get(a, a) for a in results[c.id])}{mark}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = json.dumps({
        "created_at": created,
        "model": args.model, "repeat": args.repeat,
        "note": "Router 6-way 분류 골든셋. 정답 근거는 eval/cases_router.py 참고.",
        "results": results, "needs_new_search": flags,
    }, ensure_ascii=False, indent=2)
    OUT.write_text(payload, encoding="utf-8")
    arch = archive_path(created, args.model, args.repeat)
    arch.write_text(payload, encoding="utf-8")
    print(f"\n저장: {OUT}")
    print(f"보관: {arch}   ← 실행 간 변동을 재려면 이 파일들이 함께 남아 있어야 한다")
    report(results, args.repeat, flags)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
