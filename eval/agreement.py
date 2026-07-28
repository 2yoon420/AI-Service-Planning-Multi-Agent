"""3자 정렬도 분석 — 운영 검증기 / 상위 모델 기준선 / 사람 라벨.

## 왜 3자인가

라벨셋의 목적은 검증기와 독립된 기준을 얻는 것이다. 그런데 라벨러가 한 명이면
"검증기가 이 사람의 판단과 얼마나 일치하는가"만 알 수 있고, 그 사람이 틀렸을
가능성은 검증할 수 없다. 상위 모델(Claude)을 세 번째 채점자로 두면 다음을 구분할 수 있다.

  · 사람 = Claude ≠ solar-mini  → 검증기 문제일 가능성이 높다
  · 사람 = solar-mini ≠ Claude  → 기준선 모델 문제
  · 셋이 모두 다르다             → 그 케이스가 진짜 애매하다

세 번째가 이 프로젝트에서 특히 중요하다. "사람도 확신하지 못하는 것을 기계가
자동으로 '검증됨' 도장을 찍으면 안 된다"는 3단계 판정(채택/애매/기각)의 근거가 된다.

## 한계 (반드시 함께 보고할 것)

  · 사람 라벨러가 1명이다. 정렬도는 원래 2명 이상으로 재는 것이 표준이며,
    라벨러 간 일치도(inter-annotator agreement)를 모르면 사람 라벨의 신뢰 구간을
    말할 수 없다.
  · Claude 라벨은 사람 라벨이 아니다. solar-mini와 같은 LLM 계열이므로 공통 편향이
    있을 수 있고, 기준 모델도 틀린다.
  · solar-mini 점수는 결함 A~D 수정 **이전** 코드로 채점된 것이다. 수정 후 점수와
    비교하는 것이 아니므로, 이 결과는 "수정 전 검증기"의 상태를 나타낸다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ACCEPT_MIN = 4          # 채택 경계. 루브릭상 3점은 "부분적으로만 관련"이다.


def load() -> dict[str, dict]:
    base = Path("eval/label")
    sample = json.loads(Path("eval/label_sample.json").read_text(encoding="utf-8"))
    human = json.loads((base / "relevance_labels.json").read_text(encoding="utf-8"))
    claude = json.loads((base / "claude_reference_labels.json").read_text(encoding="utf-8"))

    rows: dict[str, dict] = {}
    for it in sample["items"]:
        rows[it["id"]] = {
            "id": it["id"], "dataset": it["dataset"], "stratum": it["stratum"],
            "text": it["text"], "topic": it["topic"], "market": it["target_market"],
            "judge": it["judge_relevance"],
            "judge_reason": it["judge_relevance_reason"],
        }
    for l in human["labels"]:
        rows[l["id"]].update(human=l["human_relevance"],
                             h_topic=l.get("topic_scope"), h_market=l.get("market_scope"))
    for l in claude["labels"]:
        rows[l["id"]].update(claude=l["claude_relevance"],
                             c_topic=l.get("topic_scope"), c_market=l.get("market_scope"),
                             c_reason=l.get("reason"))
    return rows


def kappa(a: list[bool], b: list[bool]) -> float:
    """Cohen's kappa (이진). 우연 일치를 보정한 값 — 단순 일치율보다 정직하다."""
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 0.0 if pe == 1 else (po - pe) / (1 - pe)


def kappa_label(k: float) -> str:
    # Landis & Koch(1977) 관례적 구간. 절대 기준이 아니라 해석 편의를 위한 관례다.
    if k < 0.0: return "우연보다 못함"
    if k < 0.20: return "미약(slight)"
    if k < 0.40: return "낮음(fair)"
    if k < 0.60: return "보통(moderate)"
    if k < 0.80: return "상당(substantial)"
    return "거의 완전(almost perfect)"


# ---------------------------------------------------------------------------
# 보고 계층 (2026-07-29 추가)
#
# 왜 뒤늦게 붙였는가: 이 파일에는 계산 함수만 있고 진입점이 없었다. 그런데
# 검증_총정리 12절이 재현 명령으로 `python eval/agreement.py`를 제시했다. 즉
# "재현 가능하다"는 주장만 있고 실제로는 실행해도 아무것도 출력되지 않았다.
# 문서가 보고한 수치(κ=0.153 등)는 재검산 결과 전부 옳았으나, 그것을 확인하려면
# 함수를 직접 import해야 했다. 재현 경로가 끊겨 있던 것이므로 출력 계층을 붙인다.
# ---------------------------------------------------------------------------

# 지역어 목록. "fact 문장에 지역이 드러나는가"를 코드로 판정하기 위한 것이며,
# 결함 G(fact가 지역 정보를 잃는 문제)의 규모를 세는 데 쓴다.
#
# 한계: 이 목록 자체가 근거 없는 임의값이다. 네 도메인(유럽·북미·한국)에 맞춰
# 만든 것이므로 다른 지역 데이터에는 적중하지 않는다 — 하드코딩 목록 6종과 같은
# 성질의 지뢰를 안고 있다. 목록을 좁히면 37건, 넓히면 34건이 나오므로 이 숫자는
# ±3건의 폭을 가진 추정치로 읽어야 한다.
REGION_WORDS = [
    "유럽", "EU", "독일", "프랑스", "영국", "이탈리아", "스페인", "네덜란드",
    "폴란드", "벨기에", "스웨덴",
    "북미", "미국", "캐나다",
    "한국", "국내", "아시아", "중국", "일본",
    "글로벌", "세계", "전세계", "국제",
]
_REGION_PAT = re.compile("|".join(re.escape(w) for w in REGION_WORDS))


def has_region_word(text: str) -> bool:
    """fact 문장 자체에 지역어가 드러나는가."""
    return bool(_REGION_PAT.search(text))


def _accepted(rows: dict[str, dict], key: str) -> list[bool]:
    return [rows[i][key] >= ACCEPT_MIN for i in sorted(rows)]


def report(rows: dict[str, dict]) -> None:
    n = len(rows)
    ids = sorted(rows)
    j, h, c = _accepted(rows, "judge"), _accepted(rows, "human"), _accepted(rows, "claude")

    print("=" * 72)
    print("3자 정렬도 — 운영 검증기 / Claude 기준선 / 사람 라벨")
    print("=" * 72)
    print(f"  표본 {n}건 · 채택 경계 관련성 ≥ {ACCEPT_MIN}점")
    print("  주의: 검증기 점수는 결함 A~D 수정 **이전** 코드로 채점된 것이다.\n")

    print("[결과 1] 일치도")
    print(f"  {'쌍':<22}{'일치':>12}{'Cohen κ':>10}   해석")
    print("  " + "-" * 62)
    for name, a, b in (("Claude ↔ 사람", c, h),
                       ("검증기 ↔ Claude", j, c),
                       ("검증기 ↔ 사람", j, h)):
        agree = sum(x == y for x, y in zip(a, b))
        k = kappa(a, b)
        print(f"  {name:<22}{agree:>4}/{n} ({agree/n*100:>4.1f}%){k:>+10.3f}   {kappa_label(k)}")
    print("\n  κ는 우연 일치를 보정한 값이다. 단순 일치율만 보면 57%가 나쁘지 않아 보이지만,")
    print("  두 채점자의 채택 비율이 비슷하면 우연히도 그 정도는 맞는다.\n")

    print("  채택 비율")
    for name, v in (("검증기", j), ("사람", h), ("Claude", c)):
        print(f"    {name:<8} 채택 {sum(v):>2}/{n} ({sum(v)/n*100:>4.1f}%)")

    print("\n[결과 2] 채택 판정 조합 (O=채택, X=기각)")
    combos = Counter((rows[i]["judge"] >= ACCEPT_MIN,
                      rows[i]["claude"] >= ACCEPT_MIN,
                      rows[i]["human"] >= ACCEPT_MIN) for i in ids)
    notes = {
        (True, True, True): "명백히 관련 있음",
        (False, True, True): "검증기만 기각 — 과하게 엄격",
        (False, False, False): "명백히 무관",
        (False, True, False): "기준선(Claude)이 관대",
        (True, True, False): "사람이 엄격",
        (False, False, True): "사람만 채택",
        (True, False, False): "검증기만 채택 — 과하게 관대(위험)",
        (True, False, True): "—",
    }
    print(f"  {'검증기':<8}{'Claude':<9}{'사람':<7}{'건수':>5}   해석")
    print("  " + "-" * 62)
    for combo, cnt in combos.most_common():
        s = ["O" if x else "X" for x in combo]
        print(f"  {s[0]:<8}{s[1]:<9}{s[2]:<7}{cnt:>5}   {notes.get(combo, '')}")
    strict = combos.get((False, True, True), 0)
    loose = combos.get((True, False, False), 0)
    if loose:
        print(f"\n  → 검증기 오류가 엄격한 방향({strict}건)에 관대한 방향({loose}건)의 "
              f"{strict/loose:.1f}배 편중됐다.")
        print("     즉 수정 전 검증기는 정상 근거를 버리는 쪽으로 틀렸다.")

    print("\n[결과 3] 핵심 질문 — 검증기의 3점을 사람은 어떻게 봤는가")
    three = [rows[i]["human"] for i in ids if rows[i]["judge"] == 3]
    hi = sum(1 for x in three if x >= 4)
    mid = sum(1 for x in three if x == 3)
    lo = sum(1 for x in three if x <= 2)
    print(f"  검증기가 관련성 3점을 준 {len(three)}건의 사람 라벨 분포")
    print(f"    ≥4점 (채택 상당)  {hi:>2}건 ({hi/len(three)*100:>3.0f}%)")
    print(f"     3점              {mid:>2}건 ({mid/len(three)*100:>3.0f}%)")
    print(f"    ≤2점 (기각 상당)  {lo:>2}건 ({lo/len(three)*100:>3.0f}%)")
    print(f"\n  → 3점을 자동 채택하면 {lo/len(three)*100:.0f}%가 잘못 실리고,")
    print(f"     자동 기각하면 {hi/len(three)*100:.0f}%를 잃는다. 어느 쪽으로도 자동 처리할 수 없다.")
    print("     이것이 `채택 ≥4 / 애매 =3 / 기각 ≤2` 이산 규칙의 실측 근거다.")

    print("\n[결과 4] 두 축을 따로 보면 — 어디서 갈렸는가")
    print(f"  {'채점자':<10}{'주제: 예/부분/아니오':<24}{'지역·대상: 예/부분/아니오'}")
    print("  " + "-" * 62)
    for name, tk, mk in (("사람", "h_topic", "h_market"), ("Claude", "c_topic", "c_market")):
        t = Counter(rows[i].get(tk) for i in ids)
        m = Counter(rows[i].get(mk) for i in ids)
        tf = f"{t.get('예',0)} / {t.get('부분',0)} / {t.get('아니오',0)}"
        mf = f"{m.get('예',0)} / {m.get('부분',0)} / {m.get('아니오',0)}"
        print(f"  {name:<10}{tf:<24}{mf}")
    print("\n  → 주제 판정은 거의 같다. 갈린 것은 지역·대상이다.")

    noreg = [i for i in ids if not has_region_word(rows[i]["text"])]
    h_no = sum(1 for i in noreg if rows[i].get("h_market") == "아니오")
    c_part = sum(1 for i in noreg if rows[i].get("c_market") == "부분")
    print(f"\n  fact 문장에 지역어가 없는 건: {len(noreg)}/{n} ({len(noreg)/n*100:.0f}%)")
    print(f"    이 중 사람이 '아니오'로 본 것    {h_no}건")
    print(f"    이 중 Claude가 '부분'으로 본 것  {c_part}건")
    print("  → 지역이 안 적힌 fact를 '유럽 이야기일 수도 있으니 부분'으로 본 것은 관대한")
    print("     판단이다. 이 지점이 결함 G(fact가 지역 정보를 잃는 문제)의 발견 경로다.")

    print("\n" + "=" * 72)
    print("한계 — 반드시 함께 보고할 것")
    print("=" * 72)
    for line in (
        "라벨러가 1명이며 개발자 본인이다. 정렬도의 표준은 2명 이상이고, 라벨러 간",
        "  일치도를 모르면 사람 라벨 자체의 신뢰 구간을 말할 수 없다.",
        "표본은 의도적으로 어렵다 — 70건 중 30건(43%)이 가장 안 갈리는 3점 구간이다.",
        "  따라서 이 κ는 실제 운영 분포에서의 일치도보다 낮게 나오도록 설계된 값이다.",
        "검증기 점수는 결함 A~D 수정 이전이다. 원문을 저장하지 않으므로 같은 표본을",
        "  수정 후 루브릭으로 재채점할 수 없다.",
        "Claude 라벨은 사람 라벨이 아니다. 같은 LLM 계열이라 공통 편향이 있을 수 있다.",
        "관련성 축만 측정했다. 근거지지도 정렬도는 원문 저장(스키마 변경)이 선행돼야 한다.",
        "REGION_WORDS 목록 자체가 임의값이다. 좁히면 37건, 넓히면 34건이 나온다.",
    ):
        print(f"  · {line}" if not line.startswith("  ") else f"  {line}")


def main() -> None:
    report(load())


if __name__ == "__main__":
    main()
