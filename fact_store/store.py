"""
Fact Store — SQLite 기반 저장소

schema.py의 Pydantic 모델(Fact, Competitor, MarketSizing)을 실제로
저장·조회하는 최소 구현. 각 레코드는 핵심 필드를 컬럼으로 두고,
나머지는 JSON으로 직렬화해 함께 저장한다 (스키마 변경에 유연하게 대응하기 위함).
"""

import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from fact_store.schema import Competitor, Fact, MarketSizing

DB_PATH = Path(__file__).parent / "fact_store.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """테이블이 없으면 생성. 여러 번 호출해도 안전(idempotent)."""
    conn = _connect()
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                source_tier TEXT NOT NULL,
                needs_source_check INTEGER NOT NULL DEFAULT 0,
                region TEXT,
                data_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS competitors (
                name TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_sizing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                data_json TEXT NOT NULL
            )
            """
        )
    conn.close()


def save_fact(fact: Fact) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO facts (id, source_tier, needs_source_check, region, data_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_tier=excluded.source_tier,
                needs_source_check=excluded.needs_source_check,
                region=excluded.region,
                data_json=excluded.data_json
            """,
            (
                fact.id,
                fact.source_tier.value,
                int(fact.needs_source_check),
                fact.region,
                fact.model_dump_json(),
            ),
        )
    conn.close()


def get_fact(fact_id: str) -> Optional[Fact]:
    conn = _connect()
    row = conn.execute("SELECT data_json FROM facts WHERE id = ?", (fact_id,)).fetchone()
    conn.close()
    return Fact.model_validate_json(row["data_json"]) if row else None


def list_facts(
    source_tier: Optional[str] = None,
    needs_source_check: Optional[bool] = None,
    region: Optional[str] = None,
) -> list[Fact]:
    """필터 조건에 맞는 Fact 목록 조회. 인자를 안 주면 전체 반환."""
    conn = _connect()
    query = "SELECT data_json FROM facts WHERE 1=1"
    params: list = []
    if source_tier is not None:
        query += " AND source_tier = ?"
        params.append(source_tier)
    if needs_source_check is not None:
        query += " AND needs_source_check = ?"
        params.append(int(needs_source_check))
    if region is not None:
        query += " AND region = ?"
        params.append(region)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [Fact.model_validate_json(r["data_json"]) for r in rows]


DUPLICATE_SIMILARITY_THRESHOLD = 0.85


def find_similar_fact(text: str, threshold: float = DUPLICATE_SIMILARITY_THRESHOLD) -> Optional[Fact]:
    """
    기존 fact 중 텍스트가 threshold 이상 유사한 것이 있으면 반환한다 (없으면 None).

    임베딩 기반 의미 유사도가 아니라 문자열 유사도(difflib.SequenceMatcher)를 쓴다.
    "84억 4천만 달러이다" vs "84억 4천만 달러입니다"처럼 표현만 다른 사실상 동일한
    fact를 잡아내는 게 목적이라, 이 정도 근사치로 충분하다고 판단함. 완전히 다른
    표현으로 같은 내용을 말하는 경우(의역)까지는 못 잡는다는 한계가 있다.
    """
    for existing in list_facts():
        ratio = SequenceMatcher(None, text, existing.text).ratio()
        if ratio >= threshold:
            return existing
    return None


def save_fact_if_new(fact: Fact, threshold: float = DUPLICATE_SIMILARITY_THRESHOLD) -> tuple[Fact, bool]:
    """
    기존에 비슷한 fact가 없을 때만 새로 저장한다.
    반환값: (실제로 저장/기존에 있던 Fact, 새로 저장했으면 True / 중복이라 건너뛰었으면 False)

    기존 fact가 중복으로 판정되면 새로 저장하지는 않되, 기존 fact에 topic 필드가
    비어 있고 이번에 들어온 fact에는 topic이 있으면 그 값을 채워 넣어 업데이트한다.
    (레거시 fact — topic 필드 도입 이전에 저장된 것 — 가 이후 실행에서도 계속 topic
    필터에 걸리지 않고 소외되는 문제를 점진적으로 완화하기 위함. 완전한 백필은 아니고,
    같은 내용의 fact가 topic이 지정된 채로 다시 발견될 때만 보정됨.)
    """
    duplicate = find_similar_fact(fact.text, threshold=threshold)
    if duplicate:
        if duplicate.topic is None and fact.topic is not None:
            duplicate.topic = fact.topic
            save_fact(duplicate)
        return duplicate, False
    save_fact(fact)
    return fact, True


def save_competitor(competitor: Competitor) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO competitors (name, type, data_json)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                type=excluded.type,
                data_json=excluded.data_json
            """,
            (competitor.name, competitor.type.value, competitor.model_dump_json()),
        )
    conn.close()


def list_competitors(competitor_type: Optional[str] = None) -> list[Competitor]:
    conn = _connect()
    if competitor_type:
        rows = conn.execute(
            "SELECT data_json FROM competitors WHERE type = ?", (competitor_type,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT data_json FROM competitors").fetchall()
    conn.close()
    return [Competitor.model_validate_json(r["data_json"]) for r in rows]


def save_market_sizing(sizing: MarketSizing) -> int:
    conn = _connect()
    with conn:
        cur = conn.execute(
            "INSERT INTO market_sizing (data_json) VALUES (?)",
            (sizing.model_dump_json(),),
        )
        row_id = cur.lastrowid
    conn.close()
    return row_id


def latest_market_sizing() -> Optional[MarketSizing]:
    conn = _connect()
    row = conn.execute(
        "SELECT data_json FROM market_sizing ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return MarketSizing.model_validate_json(row["data_json"]) if row else None


if __name__ == "__main__":
    # 간단한 자체 테스트
    from datetime import date

    init_db()
    sample = Fact(
        id="fact_test_0001",
        text="샘플 fact - store.py 동작 확인용",
        source_url="https://example.com",
        source_tier="2차",
        retrieved_date=date.today(),
    )
    save_fact(sample)
    fetched = get_fact("fact_test_0001")
    print("저장/조회 성공:", fetched.id if fetched else "실패")
    print("전체 fact 수:", len(list_facts()))
