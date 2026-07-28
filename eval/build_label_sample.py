"""관련성 사람 라벨용 표본을 4개 도메인에서 층화 추출한다.

## 왜 관련성만 하는가

근거지지도를 사람이 라벨하려면 원문(source_content)이 필요한데 스키마가 저장하지 않는다.
관련성은 "이 fact가 연구대상·목표시장과 관련 있는가"만 보므로 fact 문장·주제·시장만
있으면 판단할 수 있다 — 오늘 결함 A 수정으로 검증기에서도 원문을 뺀 것과 같은 논리다.

## 왜 3점 경계에 집중하는가

지금 답해야 할 질문은 하나다: "combined 3점 fact를 채택해도 되는가."
민감도 분석 결과, 적응형 임계값이 정수 척도에서 실제로 하는 일은 이 결정 하나뿐이었다.
그래서 471건을 전부 라벨하지 않고 3점 주변만 본다.

## 왜 5점·1점도 넣는가

사람도 실수한다. 명백한 케이스에서 사람 라벨이 검증기와 일치하는지 먼저 확인해야
라벨셋 자체를 신뢰할 수 있다. 여기서 어긋나면 경계 케이스 결과도 못 믿는다.
(이 항목이 없으면 "사람이 옳고 기계가 틀렸다"는 전제를 검증 없이 깔게 된다.)

## 편향 방지

- 검증기 점수를 표본 파일에 넣지만, 라벨링 도구는 라벨 확정 전까지 보여주지 않는다.
- 도메인 편향을 막기 위해 4개 데이터셋에서 비례 추출한다.
- 표본 순서를 섞어, 라벨하는 사람이 "이 구간은 다 3점이구나"를 눈치채지 못하게 한다.
- 난수 시드를 고정해 재현 가능하게 한다.
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import re
from pathlib import Path

REASON_PAT = re.compile(r"\[관련성 (\d+)점: (.*?)\] \[근거지지도 (\d+)점", re.S)

# (설명, 조건, 목표 건수)
STRATA = [
    ("경계: 관련성 3점", lambda r, g: r == 3, 30),
    ("대조: 관련성 4점", lambda r, g: r == 4, 20),
    ("정답 확인: 관련성 5점", lambda r, g: r == 5, 10),
    ("정답 확인: 관련성 1~2점", lambda r, g: r <= 2, 10),
]


def load_all() -> list[dict]:
    items = []
    for p in sorted(glob.glob("eval/datasets/*.json")):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        for f in d["facts"]:
            m = REASON_PAT.search(f.get("verification_reasoning") or "")
            if not m:
                continue
            items.append({
                "dataset": d["dataset"],
                "topic": d["topic"],
                "target_market": d["target_market"],
                "text": f["text"],
                "source_url": f.get("source_url"),
                "source_tier": f.get("source_tier"),
                # 아래 세 개는 라벨 확정 후에만 보여준다
                "judge_relevance": int(m.group(1)),
                "judge_relevance_reason": m.group(2).strip(),
                "judge_groundedness": int(m.group(3)),
                "judge_status": f.get("verification_status"),
            })
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260728)
    ap.add_argument("--out", default="eval/label_sample.json")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pool = load_all()
    print(f"전체 후보 {len(pool)}건 (관련성 점수 복원 성공분)")

    picked, used = [], set()
    for label, cond, want in STRATA:
        cand = [i for i, x in enumerate(pool)
                if i not in used and cond(x["judge_relevance"], x["judge_groundedness"])]
        # 도메인이 한쪽으로 쏠리지 않게, 데이터셋별로 돌아가며 뽑는다
        by_ds: dict[str, list[int]] = {}
        for i in cand:
            by_ds.setdefault(pool[i]["dataset"], []).append(i)
        for v in by_ds.values():
            rng.shuffle(v)
        take: list[int] = []
        while len(take) < want and any(by_ds.values()):
            for ds in sorted(by_ds):
                if by_ds[ds] and len(take) < want:
                    take.append(by_ds[ds].pop())
        used.update(take)
        for i in take:
            item = dict(pool[i])
            item["stratum"] = label
            picked.append(item)
        got = len(take)
        dist = {}
        for i in take:
            dist[pool[i]["dataset"]] = dist.get(pool[i]["dataset"], 0) + 1
        flag = "" if got == want else f"  ← 후보 부족 (요청 {want})"
        print(f"  {label:<22} {got:2d}건  {dist}{flag}")

    rng.shuffle(picked)          # 라벨하는 사람이 구간을 눈치채지 못하게
    for n, item in enumerate(picked, 1):
        item["id"] = f"L{n:03d}"

    out = {
        "created_at": "2026-07-28",
        "seed": args.seed,
        "axis": "relevance",
        "instruction": (
            "각 fact가 연구대상·목표시장과 관련 있는지 1~5점으로 채점하십시오. "
            "5=정확히 부합, 3=부분적으로만 관련(인접 카테고리·인접 지역), 1=전혀 다름. "
            "원문에 근거가 있는지는 판단하지 마십시오 — 그것은 다른 축입니다."
        ),
        "n": len(picked),
        "items": picked,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{args.out}  총 {len(picked)}건")


if __name__ == "__main__":
    main()
