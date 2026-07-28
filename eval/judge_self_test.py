"""검증기 self-test — 정답을 아는 극단 케이스로 grade_fact()를 시험한다.

실행:
    python eval/judge_self_test.py                      # 기본 모델(VERIFICATION_MODEL)
    python eval/judge_self_test.py --repeat 3           # 판정 안정성까지
    python eval/judge_self_test.py --model solar-pro2   # 다른 모델로
    python eval/judge_self_test.py --compare            # 두 모델 나란히 비교
    python eval/judge_self_test.py --dry-run            # LLM 없이 케이스 점검

## 무엇을 재는가

"검증기가 **명백한 것**이라도 가려내는가"만 잰다. 애매한 경계는 일부러 넣지 않았다.
극단에서 실패하면 임계값·결합방식 같은 미세 조정은 의미가 없기 때문이다.

## 무엇을 재지 않는가

- 실제 fact에 대한 정확도 — 그건 사람 라벨셋(judge 정렬도)이 필요하다
- 파이프라인 전체 품질 — 여기는 `grade_fact()` 한 함수만 본다

## 순환 논리가 없는 이유

원문과 fact를 **둘 다 우리가 지어냈다.** 검증기의 채점을 근거로 검증기를 평가하는
구조가 아니다(2026-07-28 사후 집계의 약점이 그것이었다).
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from collections import defaultdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.cases_judge import ALL_CASES


# ── 모델 → 공급자 라우팅 ────────────────────────────────────────────────
#
# 프로덕션의 get_client()는 Upstage 주소가 고정돼 있다. 여기서만 모델 이름을 보고
# 클라이언트를 갈아끼운다 — 평가를 위해 프로덕션 코드에 분기를 넣지 않기 위함이다.
#
# 셋 다 OpenAI 호환 인터페이스를 제공하므로 base_url과 키만 바꾸면 같은 코드가 돈다.
PROVIDERS = [
    # (모델명 접두사, 표시명, 환경변수, base_url)
    ("solar",  "Upstage", "UPSTAGE_API_KEY", "https://api.upstage.ai/v1"),
    ("gpt",    "OpenAI",  "OPENAI_API_KEY",  None),   # None이면 OpenAI 기본 주소
    ("o1",     "OpenAI",  "OPENAI_API_KEY",  None),
    ("o3",     "OpenAI",  "OPENAI_API_KEY",  None),
    ("gemini", "Google",  "GOOGLE_API_KEY",
     "https://generativelanguage.googleapis.com/v1beta/openai/"),
]


def resolve_provider(model: str):
    for prefix, label, env, base in PROVIDERS:
        if model.lower().startswith(prefix):
            return label, env, base
    # 모르는 접두사는 Upstage로 보낸다 — 이 프로젝트의 기본 공급자다.
    return "Upstage(추정)", "UPSTAGE_API_KEY", "https://api.upstage.ai/v1"


def client_for(model: str):
    """모델에 맞는 OpenAI 호환 클라이언트. 키가 없으면 RuntimeError."""
    from openai import OpenAI

    label, env, base = resolve_provider(model)
    key = os.getenv(env)
    if not key or not key.strip():
        raise RuntimeError(
            f"{model} 은(는) {label} 모델인데 {env} 가 .env 에 없습니다.\n"
            f"       .env 에 {env}=... 를 추가하고 다시 실행하세요."
        )
    return OpenAI(api_key=key.strip(), **({"base_url": base} if base else {}))


def preflight(model: str, client) -> Optional[str]:
    """본 실행 전에 1회만 호출해 본다.

    20건을 다 돌린 뒤 전부 같은 이유로 실패하는 것보다, 처음에 한 번 찔러보고
    끝내는 쪽이 낫다. 특히 구조화 출력(json_schema) 지원은 공급자마다 다르다."""
    from agents.verification import grade_fact
    try:
        grade_fact_with_model(grade_fact, model, client,
                              {"fact": "테스트", "src": "테스트 원문",
                               "topic": "t", "market": "m"}, "relevance")
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def verdict(case: dict, score: int) -> bool:
    if "expect_min" in case:
        return score >= case["expect_min"]
    return score <= case["expect_max"]


def expectation(case: dict) -> str:
    return f">={case['expect_min']}점" if "expect_min" in case else f"<={case['expect_max']}점"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1,
                    help="같은 케이스를 몇 번 채점할지. 2 이상이면 판정 안정성도 본다")
    ap.add_argument("--model", default=None,
                    help="채점에 쓸 모델. 미지정 시 VERIFICATION_MODEL(기본 solar-pro2)")
    ap.add_argument("--compare", nargs="*", metavar="MODEL",
                    help="여러 모델을 같은 케이스로 돌려 비교. 값을 안 주면 "
                         "LIGHT_MODEL과 HEAVY_MODEL을 쓴다")
    ap.add_argument("--dry-run", action="store_true", help="LLM 호출 없이 케이스만 점검")
    args = ap.parse_args()

    if args.dry_run:
        for persp, c in ALL_CASES:
            print(f"  {c['id']:8s} {persp:12s} 기대 {expectation(c):6s}  {c['note']}")
        print("\n(dry-run — LLM을 호출하지 않았습니다)")
        return 0

    if args.compare is not None:
        models = args.compare or [
            os.getenv("VERIFICATION_MODEL", "solar-pro2"),
            os.getenv("HEAVY_MODEL", "solar-pro2"),
        ]
        return compare_models(models, args.repeat)

    model = args.model or os.getenv("VERIFICATION_MODEL", "solar-pro2")
    try:
        rate, buckets, _, _ = run_suite(model, args.repeat)
    except RuntimeError as e:
        print(f"  !! {e}")
        return 2
    if rate is None:
        return 2
    return report(model, rate, buckets)


def run_suite(model: str, repeat: int, verbose: bool = False):
    """한 모델로 전체 케이스를 채점하고 (정답률, 버킷, 실패목록, 근거) 를 돌려준다."""
    from agents.verification import grade_fact

    label, env, _ = resolve_provider(model)
    print(f"모델 {model} ({label}) · 케이스 {len(ALL_CASES)}개 · 반복 {repeat}회 "
          f"→ 총 {len(ALL_CASES) * repeat}회 채점\n")

    client = client_for(model)
    err = preflight(model, client)
    if err:
        print(f"  !! 사전 점검 실패 — 이 모델은 건너뜁니다.\n     {err}\n")
        return None, {}, [], {}
    results = defaultdict(list)   # id -> [score, ...]
    reasons = {}

    for i, (persp, c) in enumerate(ALL_CASES, 1):
        for _ in range(repeat):
            try:
                score, reason = grade_fact_with_model(
                    grade_fact, model, client, c, persp
                )
            except Exception as e:                      # 한 건 실패로 전체를 죽이지 않는다
                print(f"  !! {c['id']} 채점 실패: {type(e).__name__}: {e}")
                continue
            results[c["id"]].append(score)
            reasons.setdefault(c["id"], reason)
        got = results.get(c["id"], [])
        mark = "." if got and all(verdict(c, s) for s in got) else "X"
        print(f"  [{i:2d}/{len(ALL_CASES)}] {c['id']:8s} {mark} {got}")

    # ── 집계 ──
    print("\n" + "=" * 64)
    buckets = defaultdict(lambda: [0, 0])     # (관점, 방향) -> [정답, 전체]
    failures = []
    unstable = []

    for persp, c in ALL_CASES:
        got = results.get(c["id"])
        if not got:
            continue
        direction = "채택기대" if "expect_min" in c else "기각기대"
        key = (persp, direction)
        passed = all(verdict(c, s) for s in got)
        buckets[key][1] += 1
        if passed:
            buckets[key][0] += 1
        else:
            failures.append((persp, c, got))
        if len(set(got)) > 1:
            # 점수가 흔들린 것과 '판정'이 뒤집힌 것은 다르다.
            # 예) 기각기대 케이스가 [2, 1, 1] 이면 점수는 흔들렸지만 세 번 다 기각이므로
            #     운영에 아무 영향이 없다(무해). 반면 [2, 5, 5]는 기각↔채택이 뒤집힌
            #     것이므로 같은 fact가 실행마다 다르게 처리된다(유해).
            # 이 구분을 안 하면 "흔들림 3건"과 "흔들림 3건"이 전혀 다른 상태인데도
            # 같아 보인다. 2026-07-28 pro2(무해 3건)와 mini(유해 3건)가 그 예다.
            flipped = len(set(verdict(c, sc) for sc in got)) > 1
            unstable.append((c["id"], got, flipped))

    print("항목별 정답률")
    for (persp, direction), (ok, tot) in sorted(buckets.items()):
        print(f"  {persp:12s} {direction}  {ok:2d}/{tot:2d}  ({ok/tot*100:5.1f}%)")

    tot_ok = sum(v[0] for v in buckets.values())
    tot_all = sum(v[1] for v in buckets.values())
    rate = tot_ok / tot_all * 100 if tot_all else 0
    print(f"\n  종합  {tot_ok}/{tot_all}  ({rate:.1f}%)")

    if failures:
        print("\n틀린 케이스")
        for persp, c, got in failures:
            print(f"\n  [{c['id']}] {persp} — 기대 {expectation(c)}, 실제 {got}")
            print(f"    fact : {c['fact'][:70]}")
            print(f"    의도 : {c['note']}")
            print(f"    채점 근거: {(reasons.get(c['id']) or '')[:130]}")

    if repeat > 1 and unstable:
        harmful = [(cid, got) for cid, got, f in unstable if f]
        benign = [(cid, got) for cid, got, f in unstable if not f]
        print(f"\n점수가 흔들린 케이스 {len(unstable)}건 (같은 입력, 다른 점수)")
        if harmful:
            print(f"  · 판정까지 뒤집힘 {len(harmful)}건 — 같은 fact가 실행마다 다르게 처리된다")
            for cid, got in harmful:
                print(f"      {cid}: {got}")
        if benign:
            print(f"  · 등급 안에서만 흔들림 {len(benign)}건 — 판정은 매번 같아 운영 영향 없음")
            for cid, got in benign:
                print(f"      {cid}: {got}")

    return rate, dict(buckets), failures, reasons


# ── 판정 임계 ──
#
# 종합 정답률 하나로 판정하면 안 된다. 두 방향의 비용이 다르기 때문이다.
#
#   조작을 놓침(기각기대 실패)  → 기획서에 거짓이 실린다
#   정상을 기각(채택기대 실패)  → 근거가 사라진다 (recall 손실, 13-8절 사고)
#
# 실제로 이 스크립트를 만들며 가짜 채점기로 시험했더니, 13-8절과 똑같은 오기각이
# 2건 났는데 종합 90%라 "통과"로 나왔다. 그래서 항목별 하한을 따로 건다.
OVERALL_MIN, BUCKET_MIN = 90.0, 80.0


def report(model: str, rate: float, buckets: dict) -> int:
    weak = [(k, ok, tot) for k, (ok, tot) in buckets.items()
            if tot and ok / tot * 100 < BUCKET_MIN]

    print("\n" + "=" * 64)
    if rate >= OVERALL_MIN and not weak:
        print(f"판정: 통과 ({model} · 종합 {rate:.1f}%, 모든 항목 {BUCKET_MIN:.0f}% 이상)")
        print("      검증기가 명백한 케이스는 가려낸다.")
        print("      → 이제 사람 라벨셋(judge 정렬도)으로 경계 케이스를 볼 단계다.")
    elif weak:
        print(f"판정: 미달 — 종합은 {rate:.1f}%지만 특정 항목이 무너졌다.")
        for (persp, direction), ok, tot in weak:
            cost = ("기획서에 거짓이 실린다" if direction == "기각기대"
                    else "정상 근거가 사라진다 (13-8절 유형)")
            print(f"      · {persp} {direction} {ok}/{tot} → {cost}")
        print("      → 종합 점수에 속지 말 것. 위 항목의 채점 근거부터 읽어야 한다.")
    else:
        print(f"판정: 미달 (종합 {rate:.1f}%). 극단 케이스도 못 가린다.")
        print("      → 임계값·결합방식 조정은 무의미하다. 프롬프트나 모델을 먼저 볼 것.")

    print("\n한계: 이 테스트는 극단만 본다. 통과했다고 실제 fact 판정이 정확하다는 뜻이")
    print("      아니다. 그건 사람 라벨과의 정렬도를 재야 알 수 있다.")
    print(f"      임계 {OVERALL_MIN:.0f}%/{BUCKET_MIN:.0f}%도 근거 없는 값이다(임의값_전수목록 참고).")
    return 0 if (rate >= OVERALL_MIN and not weak) else 1


def compare_models(models: list[str], repeat: int) -> int:
    """같은 케이스를 여러 모델로 돌려 비교한다.

    모델 선택의 근거를 만들기 위한 것이다. 지금까지 "판정은 단순 분류에 가까우니
    싼 모델로 충분하다"는 판단만 있었고 실측 비교는 없었다(1차 외부검토 ②).
    같은 20문항이므로 비교 조건이 고정된다."""
    table, skipped = {}, []
    for m in models:
        print("\n" + "#" * 64)
        try:
            rate, buckets, failures, _ = run_suite(m, repeat)
        except RuntimeError as e:
            print(f"  !! {e}\n")
            skipped.append((m, "키 없음"))
            continue
        if rate is None:                      # preflight 실패
            skipped.append((m, "호출 실패"))
            continue
        table[m] = (rate, buckets, failures)
        report(m, rate, buckets)

    if not table:
        print("\n비교할 모델이 없습니다. 위 사유를 확인하세요.")
        return 2

    print("\n" + "=" * 64)
    print("모델 비교")
    print(f"\n  {'모델':22s} {'종합':>7s}  {'근거·기각':>9s} {'근거·채택':>9s} {'관련·기각':>9s} {'관련·채택':>9s}")
    for m, (rate, buckets, _) in table.items():
        def cell(p, d):
            ok, tot = buckets.get((p, d), (0, 0))
            return f"{ok}/{tot}" if tot else "-"
        print(f"  {m:22s} {rate:6.1f}%  "
              f"{cell('groundedness','기각기대'):>9s} {cell('groundedness','채택기대'):>9s} "
              f"{cell('relevance','기각기대'):>9s} {cell('relevance','채택기대'):>9s}")

    if skipped:
        print("\n  제외된 모델:")
        for m, why in skipped:
            print(f"    {m} — {why}")

    if len(table) == 1:
        print("\n  (비교 대상이 1개뿐이라 격차를 낼 수 없습니다)")
        return 0

    best = max(table, key=lambda m: table[m][0])
    worst = min(table, key=lambda m: table[m][0])
    gap = table[best][0] - table[worst][0]
    print(f"\n  최고 {best} ({table[best][0]:.1f}%) · 최저 {worst} ({table[worst][0]:.1f}%) · 격차 {gap:.1f}%p")

    # 격차 "크기"만 보면 안 된다. 어느 쪽이 이겼는지가 결론을 뒤집는다.
    # 현재 운영 모델(VERIFICATION_MODEL)이 이겼다면 "바꿀 이유 없음"이고,
    # 졌다면 "바꿀지 검토"다. 2026-07-28 첫 실행에서 이 구분이 없어
    # "비싼 모델을 쓸지 재검토하라"는 엉뚱한 안내가 나왔다.
    current = os.getenv("VERIFICATION_MODEL", "solar-pro2")
    n_cases = len(ALL_CASES) * repeat
    diff_cases = round(gap / 100 * n_cases)

    if current in table and best == current:
        print(f"  → 현재 운영 모델({current})이 가장 높다. 바꿀 이유가 없다.")
    elif current in table:
        print(f"  → 현재 운영 모델({current}, {table[current][0]:.1f}%)보다 "
              f"{best}가 높다. 교체를 검토할 것.")
    else:
        print(f"  → 현재 운영 모델({current})은 이번 비교에 없다.")

    print(f"\n  단, 격차 {gap:.1f}%p는 {n_cases}문항 중 약 {diff_cases}문항 차이다.")
    if diff_cases <= 3:
        print("     이 정도는 우연으로도 나온다. 결론을 내리기 전에 --repeat 로 반복할 것.")

    # 종합 점수가 가리는 항목별 붕괴를 따로 짚는다
    collapsed = []
    for m, (_, buckets, _) in table.items():
        for (persp, direction), (ok, tot) in buckets.items():
            if tot and ok / tot * 100 < BUCKET_MIN:
                cost = ("조작을 통과시킴" if direction == "기각기대"
                        else "정상 근거를 기각함")
                collapsed.append((m, persp, direction, ok, tot, cost))
    if collapsed:
        print("\n  종합 점수에 가려진 항목별 붕괴:")
        for m, persp, direction, ok, tot, cost in collapsed:
            print(f"    {m:14s} {persp} {direction} {ok}/{tot} → {cost}")
    print(f"\n  주의: 케이스 {len(ALL_CASES)}개는 방향 확인용이다. 이 격차로 통계적")
    print("        결론을 내릴 수는 없다. 반복 실행(--repeat)으로 안정성도 함께 볼 것.")
    print("        공급자가 다르면 구조화 출력·안전필터 동작도 달라, 순수한 모델 성능")
    print("        비교가 아니라 '이 파이프라인에서의 실효 성능' 비교임을 유의할 것.")
    return 0


def grade_fact_with_model(grade_fact, model, client, case, persp):
    """verification 모듈의 모델 상수를 일시적으로 바꿔 채점한다.

    grade_fact()가 모듈 전역 VERIFICATION_MODEL을 보므로, 인자로 모델을 넘길 방법이
    없다. 프로덕션 코드에 평가 전용 파라미터를 추가하지 않기 위해 여기서 감싼다."""
    import agents.verification as V
    original = V.VERIFICATION_MODEL
    V.VERIFICATION_MODEL = model
    try:
        return grade_fact(client, case["fact"], case["src"],
                          case["topic"], case["market"], persp)
    finally:
        V.VERIFICATION_MODEL = original


if __name__ == "__main__":
    raise SystemExit(main())
