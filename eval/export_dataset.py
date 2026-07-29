"""fact_store DB에서 평가용 데이터셋 JSON을 뽑는다.

## 왜 스크립트로 만드는가

기존 데이터셋 4개는 **즉석 추출**로 만들었다. 그래서 다음 두 가지가 생겼다.

  · 같은 형식으로 다시 만들려면 그때 쓴 코드를 찾아야 하는데 남아 있지 않다.
  · 필드가 하나 빠져도(예: `region`) 눈치채지 못한다 — 대조할 기준이 없다.

이 프로젝트가 반복해서 배운 것과 같다 — **재현 경로가 없으면 그 숫자는 검증되지 않은
것이다**(검증 총정리 12-2절). 데이터셋도 예외가 아니다.

## 형식

기존 4개와 동일하다. 2026-07-29에 추가된 `region`·`source_excerpt`는 있으면 싣고
없으면 `null`로 둔다 — 옛 fact와 새 fact를 같은 스키마로 다룰 수 있어야 비교가 된다.

## 주의 — `source_excerpt`는 기본적으로 제외한다

fact당 최대 3,000자라 데이터셋이 수십 배로 커진다. 근거지지도 라벨링처럼 원문이
필요한 작업에서만 `--with-excerpt`로 포함시킨다. 대신 **채워졌는지 여부**는
`source_excerpt_present`로 항상 기록해, 빠뜨린 것과 없는 것을 구분한다.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

# topic → (파일명, 목표시장). 기존 4개와 이름 규칙을 맞춘다.
KNOWN = {
    "시니어 가정간편식(HMR)":   ("한국_HMR",      "한국 시니어 케어푸드 시장"),
    "친환경 포장재":            ("유럽_포장재",    "유럽 B2B 유통 시장"),
    "웨어러블 헬스케어 기기":     ("북미_웨어러블",  "북미 시니어 건강관리 시장"),
    "스마트 반려동물 건강관리 기기": ("북미_반려동물",  "북미 반려동물 오너 시장"),
}

FACT_FIELDS = [
    "text", "topic", "region",
    "verification_score", "verification_status", "verification_reasoning",
    "source_tier", "source_url", "needs_source_check", "citation_verified",
]


def load_facts(db: Path) -> list[dict]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = [json.loads(r["data_json"]) for r in conn.execute("SELECT data_json FROM facts")]
    conn.close()
    return rows


def build(topic: str, facts: list[dict], *, source: str, note: str,
          with_excerpt: bool, suffix: str = "") -> dict:
    """`dataset` 이름에 접미사를 포함시킨다.

    처음에는 파일명에만 접미사를 붙이고 `dataset` 필드는 그대로 뒀다. 그러자
    `sensitivity.py` 출력에서 구·신이 **같은 이름 두 줄**로 나와 구분되지 않았다.
    파일은 달라도 보고서에서 섞이면 소용이 없다 — 이름은 데이터를 식별하는 값이므로
    파일명과 같이 움직여야 한다."""
    name, market = KNOWN.get(topic, (topic.replace(" ", "_"), ""))
    name = f"{name}{suffix}"
    out = []
    for f in facts:
        item = {k: f.get(k) for k in FACT_FIELDS}
        item["source_excerpt_present"] = bool(f.get("source_excerpt"))
        if with_excerpt:
            item["source_excerpt"] = f.get("source_excerpt")
        out.append(item)
    return {
        "dataset": name,
        "topic": topic,
        "target_market": market,
        "source": source,
        "extracted_at": date.today().isoformat(),
        "note": note,
        "facts": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", type=Path, help="fact_store DB 경로")
    ap.add_argument("--topic", action="append", default=None,
                    help="추출할 topic. 반복 지정 가능. 생략하면 DB의 모든 topic")
    ap.add_argument("--outdir", type=Path, default=Path("eval/datasets"))
    ap.add_argument("--suffix", default="",
                    help="파일명 뒤에 붙일 접미사 (예: _v2). 기존 파일 덮어쓰기 방지")
    ap.add_argument("--source", default="", help="출처 메모 (어느 DB의 스냅샷인가)")
    ap.add_argument("--note", default="", help="채점 조건 메모 — 나중에 비교할 때 필요하다")
    ap.add_argument("--with-excerpt", action="store_true",
                    help="source_excerpt 본문까지 포함(용량 커짐). 근거지지도 라벨용")
    ap.add_argument("--dry-run", action="store_true", help="쓰지 않고 요약만")
    ap.add_argument("--force", action="store_true",
                    help="이미 있는 파일도 덮어쓴다. 기본은 덮어쓰지 않는다 — "
                         "기존 데이터셋이 대조군이라 실수로 지우면 비교가 불가능해진다")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB가 없습니다: {args.db}")
        return 1

    rows = load_facts(args.db)
    by_topic: dict[str, list[dict]] = {}
    for r in rows:
        by_topic.setdefault(r.get("topic") or "(없음)", []).append(r)

    targets = args.topic or sorted(by_topic)
    print(f"DB: {args.db}  ·  fact {len(rows)}건  ·  topic {len(by_topic)}개\n")

    args.outdir.mkdir(parents=True, exist_ok=True)
    for topic in targets:
        facts = by_topic.get(topic)
        if not facts:
            print(f"  ★ '{topic}' — DB에 없음. 건너뜀")
            continue
        data = build(topic, facts, source=args.source, note=args.note,
                     with_excerpt=args.with_excerpt, suffix=args.suffix)
        n = len(facts)
        st = Counter(f.get("verification_status") for f in facts)
        reg = sum(1 for f in facts if f.get("region"))
        exc = sum(1 for f in facts if f.get("source_excerpt"))
        path = args.outdir / f"{data['dataset']}.json"
        print(f"  {data['dataset']:<16} n={n:>4}  "
              f"채택 {st.get('채택',0):>3} / 애매 {st.get('애매',0):>3} / 기각 {st.get('기각',0):>3}  "
              f"region {reg}/{n}  excerpt {exc}/{n}")
        if args.dry_run:
            continue
        if path.exists() and not args.force:
            print(f"      ★ 이미 있습니다: {path} — 덮어쓰지 않습니다. "
                  f"--suffix 로 이름을 바꾸거나 --force 를 쓰십시오")
            continue
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"      저장: {path}  ({path.stat().st_size/1024:.0f} KB)")

    if args.dry_run:
        print("\n(--dry-run: 아무것도 쓰지 않았습니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
