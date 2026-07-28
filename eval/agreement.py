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
from collections import Counter
from itertools import combinations
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
