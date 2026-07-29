"""라벨 표본 관련성 재채점 — 한계 ⑨를 관련성 축에서 닫는다.

## 이 스크립트가 답하는 질문 하나

**"κ=0.153은 결함 A~D 수정 전 값인데, 고친 뒤에는 얼마인가?"**

검증 총정리 한계 ⑨와 3차 외부 검토의 지적(*"결함을 고쳤다면서 정렬도는 고치기 전
숫자 아닙니까"*)에 대한 답이다. 그 이상은 목적이 아니다.

## 왜 과거 데이터셋이어야 하는가

**같은 표본이어야 하기 때문이다.** 새로 수집한 fact로 재면 정렬도가 좋아져도
*"수정 덕분인지, fact가 달라서인지"* 구분할 수 없다. 사람 라벨 70건은 특정 fact
70개에 묶여 있으므로, 그 fact들을 그대로 다시 채점해야 비교가 성립한다.

## 무엇을 못 하는가 (먼저 밝힌다)

- **근거지지도는 재채점할 수 없다.** 원문(`source_content`)이 저장돼 있지 않다.
  2026-07-29에 `source_excerpt`를 추가했으나 **기존 fact에는 소급되지 않는다.**
  따라서 한계 ⑨는 **관련성 축에 한해 절반만** 닫힌다.
- **최종 판정이 좋아졌다고 말할 수 없다.** 판정은 `min(관련성, 근거지지도)`이므로
  관련성 κ가 올라가도 시스템 판정의 정렬도는 별개다.
- **순수 모델 효과가 아니다.** 모델(mini→pro2)·루브릭(결함 A~D)·지역 규칙(결함 G)이
  함께 바뀌었다. 모델만의 기여는 `judge_self_test.py --compare`가 이미 답했다
  (pro2 100% / mini 85%, 판정 뒤집힘 0건 vs 3건).

## region 2변형이 필요한 이유

데이터셋 4개 전부 `region`이 저장돼 있지 않다(0/489건). 그런데 현재 관련성 프롬프트는
`region='불명'`이면 3점을 넘지 못하게 한다(결함 G 수정). 그냥 돌리면 거의 전부 3점
이하가 나오는데, 그것은 *"pro2가 엄격해졌다"* 가 아니라 *"지역 정보가 없다"* 를 잰 것이다.
두 효과를 분리하기 위해 두 조건으로 돌린다.

  A(라벨) — 데이터셋 이름에서 region을 부여한다. **과대 부여 대조군.**
  B(추출) — 문장에서 지역어를 찾고 없으면 `불명`. **현실**: 결함 G가 겨냥한 상태.

두 값의 차이가 곧 "지역 정보를 어떻게 다루느냐가 판정에 미치는 영향"이다.

### ★ 2026-07-29 실측 후 정정 — 변형 A를 "상한"이라고 부른 것은 틀렸다

처음 이 파일을 쓸 때 A를 *"region이 완벽할 때의 상한"* 이라고 적었다. 실측 결과
**A는 상한이 아니라 과대 부여였다.**

    변형        채택   맞음  틀림  놓침   정밀도  재현율   κ
    수정 전      30    19    11    19     63%    50%   +0.153
    A(라벨)      54    34    20     4     63%    89%   +0.281
    B(추출)      28    25     3    13     89%    66%   +0.551

A는 5점을 51건(73%)이나 줬다. 재현율만 89%로 올라가고 **정밀도는 63%로 수정 전과
같다** — 정확해진 것이 아니라 그냥 관대해진 것이다. κ도 B보다 낮다.

원인은 가정 자체다. *"유럽 데이터셋의 fact니까 유럽 이야기다"* 라고 가정했는데,
**결함 G가 밝힌 것이 정확히 그 가정이 틀렸다는 것**이었다(70건 중 34건은 문장에
지역어가 없다). 결함 G의 교훈을 어긴 실험 설계였다.

그래도 A를 지운 게 아니라 남긴다. **"지역을 후하게 부여하면 어떻게 되는가"의 대조군**
으로서 값이 있다 — B가 좋은 이유를 A 없이는 설명할 수 없다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.verification import (  # noqa: E402
    ACCEPT_MIN_SCORE,
    VERIFICATION_MODEL,
    grade_fact,
)
from eval.agreement import ACCEPT_MIN, has_region_word, kappa, kappa_label, load  # noqa: E402
from eval.judge_self_test import client_for  # noqa: E402

# 데이터셋 이름 → 그 실행의 목표 지역. 변형 A에서만 쓴다.
DATASET_REGION = {
    "유럽_포장재": "유럽",
    "한국_HMR": "한국",
    "북미_웨어러블": "북미",
    "북미_반려동물": "북미",
}

OUT_PATH = Path("eval/label/rescored_relevance.json")


# 문장에서 찾은 지역어 → 정규화된 지역. 변형 B에서만 쓴다.
#
# `agreement.has_region_word()`가 쓰는 REGION_WORDS 전체를 여기서 빠짐없이 매핑해야
# 한다. 일부만 매핑하면 "지역어는 있는데 None이 되는" fact가 생겨, 결함 G 분석의
# 34건과 이 실험의 '불명' 건수가 어긋난다. 처음 작성 때 실제로 38건이 나와 어긋났다.
#
# '글로벌'류를 None으로 보내지 않는 이유: 세계 시장 수치를 언급한 fact는 지역이
# 불명한 것이 아니라 '전 세계'라고 말한 것이다. 목표시장보다 넓은 범위이므로
# 채점기가 부분 관련으로 판단할 수 있게 그대로 넘기고, 판단을 코드가 가로채지 않는다.
_TEXT_REGION = [
    ("유럽", "유럽"), ("EU", "유럽"), ("독일", "유럽"), ("프랑스", "유럽"),
    ("영국", "유럽"), ("이탈리아", "유럽"), ("스페인", "유럽"), ("네덜란드", "유럽"),
    ("폴란드", "유럽"), ("벨기에", "유럽"), ("스웨덴", "유럽"),
    ("북미", "북미"), ("미국", "북미"), ("캐나다", "북미"),
    ("한국", "한국"), ("국내", "한국"),
    ("아시아", "아시아"), ("중국", "중국"), ("일본", "일본"),
    ("전세계", "글로벌"), ("글로벌", "글로벌"), ("세계", "글로벌"), ("국제", "글로벌"),
]


def region_for(row: dict, variant: str) -> str | None:
    """변형별 region 값. 위 docstring의 A/B 정의를 그대로 구현한다."""
    if variant == "label":
        # 과대 부여 대조군. 이 fact가 정말 그 지역 이야기인지 확인하지 않고
        # 데이터셋 이름만 보고 부여한다 — 그것이 이 변형의 요점이다.
        return DATASET_REGION.get(row["dataset"])
    # variant == "text": 문장에 지역어가 드러날 때만 인정한다.
    if not has_region_word(row["text"]):
        return None
    for word, canon in _TEXT_REGION:
        if word in row["text"]:
            return canon
    # 여기 도달하면 REGION_WORDS와 _TEXT_REGION이 어긋난 것이다. 조용히 None을
    # 반환하면 '불명' 건수가 결함 G 분석과 달라지므로 즉시 드러나게 한다.
    raise AssertionError(
        f"REGION_WORDS에는 있으나 _TEXT_REGION에 없는 지역어: {row['text'][:60]!r}"
    )


def rescore(rows: dict[str, dict], variant: str, model: str, sleep: float) -> dict[str, int]:
    """관련성 축만 재채점한다. 원문은 넘기지 않는다 — 결함 A 수정이 그것이다."""
    client = client_for(model)
    out: dict[str, int] = {}
    ids = sorted(rows)
    for n, i in enumerate(ids, 1):
        r = rows[i]
        score, _reason = grade_fact(
            client, r["text"],
            "",                      # 관련성 채점에 원문은 쓰지 않는다(결함 A)
            r["topic"], r["market"], "relevance",
            region_for(r, variant),
        )
        out[i] = score
        if n % 10 == 0 or n == len(ids):
            print(f"    [{variant}] {n}/{len(ids)}", flush=True)
        if sleep:
            time.sleep(sleep)
    return out


def _acc(scores: dict[str, int], ids: list[str]) -> list[bool]:
    return [scores[i] >= ACCEPT_MIN for i in ids]


def report(rows: dict[str, dict], rescored: dict[str, dict[str, int]]) -> None:
    ids = sorted(rows)
    n = len(ids)
    human = [rows[i]["human"] >= ACCEPT_MIN for i in ids]
    old = [rows[i]["judge"] >= ACCEPT_MIN for i in ids]
    claude = [rows[i]["claude"] >= ACCEPT_MIN for i in ids]

    print("\n" + "=" * 76)
    print("관련성 재채점 — 한계 ⑨(수정 전후 같은 표본 비교)를 관련성 축에서 닫는다")
    print("=" * 76)
    print(f"  표본 {n}건 · 채택 경계 관련성 ≥ {ACCEPT_MIN}점\n")

    print("[결과 1] 사람 라벨과의 일치도 — 이 실험의 목적")
    print(f"  {'채점자':<34}{'일치':>12}{'Cohen κ':>10}   해석")
    print("  " + "-" * 74)
    base_k = kappa(old, human)
    print(f"  {'solar-mini + 구 루브릭 (수정 전)':<34}"
          f"{sum(a==b for a,b in zip(old,human)):>4}/{n} ({sum(a==b for a,b in zip(old,human))/n*100:>4.1f}%)"
          f"{base_k:>+10.3f}   {kappa_label(base_k)}")
    for variant, label in (("label", "region=라벨 부여 (과대 대조군)"),
                           ("text", "region=문장 추출 (현실)")):
        if variant not in rescored:
            continue
        new = _acc(rescored[variant], ids)
        k = kappa(new, human)
        agree = sum(a == b for a, b in zip(new, human))
        mark = "▲" if k > base_k else ("▼" if k < base_k else "=")
        print(f"  {'pro2 + 신 루브릭, ' + label:<34}"
              f"{agree:>4}/{n} ({agree/n*100:>4.1f}%){k:>+10.3f}   {kappa_label(k)}  {mark}{k-base_k:+.3f}")
    ck = kappa(claude, human)
    print(f"  {'(참고) Claude 기준선 ↔ 사람':<34}"
          f"{sum(a==b for a,b in zip(claude,human)):>4}/{n} "
          f"({sum(a==b for a,b in zip(claude,human))/n*100:>4.1f}%){ck:>+10.3f}   {kappa_label(ck)}")

    print("\n[결과 2] 점수가 어디로 움직였나 (수정 전 → 재채점)")
    for variant in ("label", "text"):
        if variant not in rescored:
            continue
        print(f"\n  변형 {variant}")
        print(f"    {'수정전':>6} │" + "".join(f"{s:>6}" for s in range(1, 6)) + f"{'계':>6}")
        print("    " + "-" * 46)
        mat = Counter((rows[i]["judge"], rescored[variant][i]) for i in ids)
        for a in range(1, 6):
            row = [mat.get((a, b), 0) for b in range(1, 6)]
            if not sum(row):
                continue
            print(f"    {a:>6} │" + "".join(f"{v:>6}" if v else f"{'·':>6}" for v in row)
                  + f"{sum(row):>6}")
        same = sum(v for (a, b), v in mat.items() if a == b)
        up = sum(v for (a, b), v in mat.items() if b > a)
        down = sum(v for (a, b), v in mat.items() if b < a)
        print(f"    유지 {same} · 상승 {up} · 하락 {down}")

    print("\n[결과 3] 검증기가 3점을 준 30건은 어떻게 됐나")
    three = [i for i in ids if rows[i]["judge"] == 3]
    print(f"  수정 전 3점: {len(three)}건 (사람 라벨: "
          f"채택 {sum(1 for i in three if rows[i]['human']>=4)} / "
          f"기각 {sum(1 for i in three if rows[i]['human']<=2)})")
    for variant in ("label", "text"):
        if variant not in rescored:
            continue
        d = Counter(rescored[variant][i] for i in three)
        print(f"    [{variant}] 재채점 분포: " + " · ".join(f"{s}점 {d.get(s,0)}건" for s in range(1, 6)))

    print("\n[결과 4] 정밀도·재현율 — κ 하나로는 방향을 알 수 없다")
    print(f"  {'채점자':<26}{'채택':>5}{'맞음':>5}{'틀림':>5}{'놓침':>5}{'정밀도':>8}{'재현율':>8}")
    print("  " + "-" * 62)
    for name, acc in [("수정 전 (mini+구 루브릭)", old)] + [
        (f"pro2, region={'라벨' if v=='label' else '추출'}", _acc(rescored[v], ids))
        for v in ("label", "text") if v in rescored
    ]:
        tp = sum(1 for a, b in zip(acc, human) if a and b)
        fp = sum(1 for a, b in zip(acc, human) if a and not b)
        fn = sum(1 for a, b in zip(acc, human) if not a and b)
        prec = tp / (tp + fp) * 100 if tp + fp else 0.0
        rec = tp / (tp + fn) * 100 if tp + fn else 0.0
        print(f"  {name:<26}{tp+fp:>5}{tp:>5}{fp:>5}{fn:>5}{prec:>7.0f}%{rec:>7.0f}%")

    print("\n[결과 5] 관련성 축이 지역 게이트로 좁아졌는가")
    print("  결함 A 수정(관련성에서 원문 제거)과 결함 G 수정(지역 불명이면 3점 초과 금지)이")
    print("  겹치면, 관련성 채점기에 남는 강한 신호가 지역뿐일 수 있다. 그것을 직접 본다.\n")
    if "text" in rescored:
        from eval.rescore_relevance import region_for as _rf
        tab = Counter((_rf(rows[i], "text") is not None, rescored["text"][i]) for i in ids)
        print(f"    {'region':<8}" + "".join(f"{s}점".rjust(7) for s in range(1, 6)) + f"{'계':>7}")
        print("    " + "-" * 50)
        for hasreg, label in ((True, "있음"), (False, "불명")):
            row = [tab.get((hasreg, sc), 0) for sc in range(1, 6)]
            print(f"    {label:<8}" + "".join(f"{v if v else '·':>7}" for v in row)
                  + f"{sum(row):>7}")
        불명_채택 = sum(v for (h, sc), v in tab.items() if not h and sc >= ACCEPT_MIN)
        있음_채택 = sum(v for (h, sc), v in tab.items() if h and sc >= ACCEPT_MIN)
        있음_계 = sum(v for (h, _), v in tab.items() if h)
        print(f"\n    region 불명 중 채택: {불명_채택}건")
        print(f"    region 있음 중 채택: {있음_채택}/{있음_계}건 ({있음_채택/있음_계*100:.0f}%)")
        if 불명_채택 == 0:
            print("    → 지역은 채택의 필요조건이다. 다만 있음 중에도 채택이 아닌 건이 있으므로")
            print("       충분조건은 아니다 — 주제 판단이 작동하기는 한다.")
            print("    ★ 그러나 채택 여부를 사실상 지역 유무가 결정한다. 관련성 축이 좁아졌다.")

    print("\n[결과 6] 채택 경계(ACCEPT_MIN_SCORE) 민감도")
    print("  4점이 실제로 쓰이는지 확인한다. 쓰이지 않으면 경계 4와 5가 같은 결과를 낸다.")
    for v in ("label", "text"):
        if v not in rescored:
            continue
        dist = Counter(rescored[v][i] for i in ids)
        print(f"\n    [{v}] 점수 분포: "
              + " · ".join(f"{sc}점 {dist.get(sc, 0)}건" for sc in range(1, 6)))
        for b in (4, 5):
            acc = [rescored[v][i] >= b for i in ids]
            print(f"      경계 {b}: 채택 {sum(acc):>2}건 · κ {kappa(acc, human):+.3f}")
        if dist.get(4, 0) == 0:
            print("      → 4점이 한 건도 없다. 경계를 4로 두든 5로 두든 결과가 같다.")
            print("         ACCEPT_MIN_SCORE는 근거 없는 값이지만 민감도가 0이다(안전한 임의값).")

    print("\n" + "=" * 76)
    print("한계 — 반드시 함께 보고할 것")
    print("=" * 76)
    for line in (
        "관련성 축만 재채점했다. 근거지지도는 원문이 저장돼 있지 않아 불가능하다.",
        "  따라서 한계 ⑨는 절반만 닫혔다. 나머지는 source_excerpt가 쌓인 뒤에야 가능하다.",
        "최종 판정은 min(관련성, 근거지지도)이므로, 관련성 κ가 올라가도 시스템 판정의",
        "  정렬도가 올라갔다고 말할 수 없다.",
        "모델·루브릭·지역 규칙이 함께 바뀌었다. 순수 모델 효과는 judge_self_test가 답한다.",
        "변형 A(라벨 부여)는 상한이 아니라 과대 부여 대조군이다. 실측에서 정밀도가 수정 전과",
        "  같은 63%였다 — 정확해진 것이 아니라 관대해진 것이다. 70건 중 34건은 문장에",
        "  지역어가 없으므로(결함 G) 데이터셋 이름으로 지역을 부여하는 가정 자체가 틀렸다.",
        "κ가 올랐다는 것을 '정확해졌다'로 읽으면 위험하다. 사람 라벨러도 도메인 지식이",
        "  부족해 지역 위주로 판단했을 가능성이 있다 — 두 채점자가 같은 얕은 규칙을 쓰면",
        "  κ는 오른다. 실제로 사람은 지역이 없는 fact를 '아니오' 23건으로 잘랐다.",
        "사람 라벨러가 1명이며 개발자 본인이다. 표본은 3점 구간을 43% 넣어 의도적으로 어렵다.",
        "LLM 채점은 실행마다 흔들린다. 이 스크립트는 1회만 채점하므로, 차이가 작으면",
        "  모델 교체 효과인지 우연인지 구분할 수 없다(--repeat 미구현).",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=VERIFICATION_MODEL,
                    help=f"채점 모델 (기본 {VERIFICATION_MODEL})")
    ap.add_argument("--variant", choices=["label", "text", "both"], default="both",
                    help="region 처리 방식. 기본 both(둘 다 돌려 지역 효과를 분리)")
    ap.add_argument("--sleep", type=float, default=0.0, help="호출 간 대기(초)")
    ap.add_argument("--reuse", action="store_true",
                    help="이전 실행 결과를 재사용해 보고만 다시 출력(LLM 호출 없음)")
    args = ap.parse_args()

    rows = load()
    variants = ["label", "text"] if args.variant == "both" else [args.variant]

    if args.reuse:
        if not OUT_PATH.exists():
            print(f"저장된 결과가 없습니다: {OUT_PATH}")
            return 1
        saved = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        rescored = {k: {i: int(v) for i, v in d.items()} for k, d in saved["scores"].items()}
        print(f"저장된 결과 재사용: {saved['created_at']} · 모델 {saved['model']}")
    else:
        calls = len(rows) * len(variants)
        print(f"모델 {args.model} · 표본 {len(rows)}건 · 변형 {variants}")
        print(f"예상 LLM 호출 {calls}회 (관련성 축만)\n")
        rescored = {}
        for v in variants:
            rescored[v] = rescore(rows, v, args.model, args.sleep)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps({
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": args.model,
            "axis": "relevance",
            "note": "관련성 축만 재채점. 근거지지도는 원문 미저장으로 불가.",
            "scores": rescored,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n저장: {OUT_PATH}")

    report(rows, rescored)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
