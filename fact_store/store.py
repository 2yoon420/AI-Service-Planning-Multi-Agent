"""
Fact Store — SQLite 기반 저장소

schema.py의 Pydantic 모델(Fact, Competitor, MarketSizing)을 실제로
저장·조회하는 최소 구현. 각 레코드는 핵심 필드를 컬럼으로 두고,
나머지는 JSON으로 직렬화해 함께 저장한다 (스키마 변경에 유연하게 대응하기 위함).

2026-07-24 변경(topic 스코핑): Router가 같은 프로젝트를 여러 차례 재방문하는 구조로
확장되면서, Competitor/MarketSizing에 topic 구분이 없으면 서로 다른 주제의 데이터가
섞이는 문제가 생긴다(예: 동명의 경쟁사가 있으면 다른 topic 것끼리 덮어씀, 가장 최근
market_sizing이 topic 무관하게 반환됨). Fact는 이미 topic 필드가 있었으나 Competitor/
MarketSizing엔 없어서 이번에 추가하고, competitors 테이블은 기본키를 name 단독에서
(topic, name) 복합키로 바꾼다. 기존 데이터는 facts 테이블에 실제로 남아있는 topic 값을
근거로 마이그레이션한다(코드에 특정 프로젝트명을 직접 적어넣지 않음 — _infer_legacy_topic
참고).
"""

import json
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

from paths import data_path
from typing import Optional

from fact_store.schema import Competitor, Fact, MarketSizing

# 배포 시 DATA_DIR로 소스 트리 밖(영구 디스크)으로 뺀다 — 이 파일은 git에 추적되고
# 있어서, 그대로 두면 서버에서 git pull 할 때마다 수집한 fact가 덮인다(paths.py 참고).
DB_PATH = data_path("fact_store.db", Path(__file__).parent / "fact_store.db")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _infer_legacy_topic(conn: sqlite3.Connection) -> str:
    """competitors/market_sizing에 topic 컬럼이 없던 시절 저장된 레거시 행을 옮길 때 쓸
    topic 값을 facts 테이블에서 실제로 조회해 정한다. 특정 프로젝트 이름을 코드에 직접
    적어두는 대신, 지금 이 DB에 실제로 있는 데이터를 보고 판단한다.

    facts에 topic이 정확히 1종류만 있으면 그 값을 그대로 쓰고, 0개거나 2개 이상 섞여
    있으면(어느 프로젝트 것인지 특정할 수 없으므로) 잘못 추측하지 않고 "_unknown_legacy_"로만
    표시해둔다."""
    rows = conn.execute("SELECT data_json FROM facts").fetchall()
    topics: set[str] = set()
    for r in rows:
        try:
            t = json.loads(r["data_json"]).get("topic")
        except (json.JSONDecodeError, AttributeError):
            t = None
        if t:
            topics.add(t)
    if len(topics) == 1:
        return topics.pop()
    return "_unknown_legacy_"


def _migrate_competitors_table(conn: sqlite3.Connection) -> None:
    """competitors 테이블 기본키를 name 단독에서 (topic, name) 복합키로 바꾼다.
    이미 마이그레이션됐으면(=topic 컬럼이 이미 있으면) 아무것도 하지 않는다(idempotent)."""
    if _column_exists(conn, "competitors", "topic"):
        return

    existing = conn.execute("SELECT name, type, data_json FROM competitors").fetchall()
    legacy_topic = _infer_legacy_topic(conn) if existing else "_unknown_legacy_"

    conn.execute("ALTER TABLE competitors RENAME TO competitors_old")
    conn.execute(
        """
        CREATE TABLE competitors (
            topic TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (topic, name)
        )
        """
    )
    for row in existing:
        try:
            data = json.loads(row["data_json"])
        except json.JSONDecodeError:
            data = {}
        topic = data.get("topic") or legacy_topic
        data["topic"] = topic  # Competitor 모델(topic 필드 신규 추가)과 맞춰 data_json도 보정
        conn.execute(
            "INSERT INTO competitors (topic, name, type, data_json) VALUES (?, ?, ?, ?)",
            (topic, row["name"], row["type"], json.dumps(data, ensure_ascii=False)),
        )
        print(f"  [마이그레이션] 경쟁사 '{row['name']}' → topic='{topic}'로 배정")
    conn.execute("DROP TABLE competitors_old")


def _migrate_market_sizing_table(conn: sqlite3.Connection) -> None:
    """market_sizing 테이블에 topic 컬럼을 추가한다. 이미 있으면 건너뛴다(idempotent)."""
    if _column_exists(conn, "market_sizing", "topic"):
        return
    conn.execute("ALTER TABLE market_sizing ADD COLUMN topic TEXT")

    rows = conn.execute("SELECT id, data_json FROM market_sizing WHERE topic IS NULL").fetchall()
    if not rows:
        return
    legacy_topic = _infer_legacy_topic(conn)
    for row in rows:
        try:
            data = json.loads(row["data_json"])
        except json.JSONDecodeError:
            data = {}
        topic = data.get("topic") or legacy_topic
        data["topic"] = topic
        conn.execute(
            "UPDATE market_sizing SET topic = ?, data_json = ? WHERE id = ?",
            (topic, json.dumps(data, ensure_ascii=False), row["id"]),
        )
        print(f"  [마이그레이션] market_sizing #{row['id']} → topic='{topic}'로 배정")


def init_db() -> None:
    """테이블이 없으면 생성하고, topic 스코핑 도입 이전의 옛 스키마가 남아있으면
    새 스키마로 마이그레이션한다. 여러 번 호출해도 안전(idempotent)."""
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
                topic TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                PRIMARY KEY (topic, name)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS market_sizing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                topic TEXT,
                data_json TEXT NOT NULL
            )
            """
        )
        # 위 CREATE TABLE IF NOT EXISTS는 옛 스키마로 이미 만들어져 있던 DB에는 효과가 없으므로
        # (테이블이 이미 존재), 실제로 옛 스키마인지 확인해 필요할 때만 마이그레이션한다.
        _migrate_competitors_table(conn)
        _migrate_market_sizing_table(conn)
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
    topic: Optional[str] = None,
) -> list[Fact]:
    """필터 조건에 맞는 Fact 목록 조회. 인자를 안 주면 전체 반환.

    topic 필터(2026-07-24 추가)는 DB 컬럼이 아니라 Python 쪽에서 적용한다 — Fact.topic
    필드가 있으면 정확히 일치하는 것만, 없는 레거시 fact는 topic_relevance(검색 질문 문구)
    부분 문자열 매칭으로 보조 판정한다. 이 로직은 원래 agents/competitor.py와
    agents/pestel.py에 각각 중복으로 들어있던 것을 여기 한 곳으로 모은 것이다."""
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
    facts = [Fact.model_validate_json(r["data_json"]) for r in rows]

    if topic is not None:
        facts = [
            f for f in facts
            if (f.topic == topic if f.topic is not None else topic in (f.topic_relevance or ""))
        ]
    return facts


DUPLICATE_SIMILARITY_THRESHOLD = 0.85


def find_similar_fact(
    text: str,
    threshold: float = DUPLICATE_SIMILARITY_THRESHOLD,
    topic: Optional[str] = None,
) -> Optional[Fact]:
    """
    기존 fact 중 텍스트가 threshold 이상 유사한 것이 있으면 반환한다 (없으면 None).

    임베딩 기반 의미 유사도가 아니라 문자열 유사도(difflib.SequenceMatcher)를 쓴다.
    "84억 4천만 달러이다" vs "84억 4천만 달러입니다"처럼 표현만 다른 사실상 동일한
    fact를 잡아내는 게 목적이라, 이 정도 근사치로 충분하다고 판단함. 완전히 다른
    표현으로 같은 내용을 말하는 경우(의역)까지는 못 잡는다는 한계가 있다.

    2026-07-28 수정 — topic 스코핑 (프로젝트 간 근거 유실 버그):
    이 함수는 원래 list_facts()를 필터 없이 호출해 **전체 프로젝트**를 훑었다. 그래서
    서로 다른 주제의 두 프로젝트가 우연히 같은 문장을 만나면, 나중 프로젝트가 "중복"으로
    판정되어 저장을 건너뛰었다. 그 fact는 앞 프로젝트의 topic을 달고 있으므로
    list_facts(topic=나중프로젝트)로는 조회되지 않는다 — 즉 **저장도 조회도 안 되어
    기획서에서 근거가 통째로 사라졌다.** 재현 결과:

        프로젝트A 저장: is_new=True,  topic='웨어러블 헬스케어 기기'
        프로젝트B 저장: is_new=False, topic='웨어러블 헬스케어 기기'   ← B의 topic이 아님
        → 프로젝트B로 조회한 fact 수: 0건

    topic을 넘기면 그 topic의 fact와 **레거시 fact(topic이 비어 있는 것)** 만 후보로 본다.
    레거시를 포함시키는 이유는 save_fact_if_new()의 점진적 백필이 바로 그 대상을 노리기
    때문이다 — 여기서 제외하면 백필이 영영 동작하지 않는다.

    topic=None이면 종전대로 전체를 훑는다(호출부 하위 호환).
    """
    if topic is None:
        candidates = list_facts()
    else:
        candidates = list_facts(topic=topic)
        seen = {f.id for f in candidates}
        # 레거시 fact — topic 필드 도입 이전 저장분. list_facts(topic=...)의
        # topic_relevance 부분 문자열 폴백에 안 걸린 것들을 여기서 보충한다.
        candidates += [
            f for f in list_facts() if f.topic is None and f.id not in seen
        ]

    for existing in candidates:
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
    # topic을 넘겨 같은 프로젝트(+레거시) 안에서만 중복을 찾는다.
    # 넘기지 않으면 다른 프로젝트의 fact를 중복으로 오판해 근거가 유실된다
    # (find_similar_fact의 2026-07-28 주석 참고).
    duplicate = find_similar_fact(fact.text, threshold=threshold, topic=fact.topic)
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
            INSERT INTO competitors (topic, name, type, data_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(topic, name) DO UPDATE SET
                type=excluded.type,
                data_json=excluded.data_json
            """,
            (competitor.topic or "", competitor.name, competitor.type.value, competitor.model_dump_json()),
        )
    conn.close()


def list_competitors(competitor_type: Optional[str] = None, topic: Optional[str] = None) -> list[Competitor]:
    conn = _connect()
    query = "SELECT data_json FROM competitors WHERE 1=1"
    params: list = []
    if competitor_type:
        query += " AND type = ?"
        params.append(competitor_type)
    if topic is not None:
        query += " AND topic = ?"
        params.append(topic)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [Competitor.model_validate_json(r["data_json"]) for r in rows]


def save_market_sizing(sizing: MarketSizing) -> int:
    conn = _connect()
    with conn:
        cur = conn.execute(
            "INSERT INTO market_sizing (topic, data_json) VALUES (?, ?)",
            (sizing.topic, sizing.model_dump_json()),
        )
        row_id = cur.lastrowid
    conn.close()
    return row_id


def latest_market_sizing(topic: Optional[str] = None) -> Optional[MarketSizing]:
    conn = _connect()
    if topic is not None:
        row = conn.execute(
            "SELECT data_json FROM market_sizing WHERE topic = ? ORDER BY id DESC LIMIT 1",
            (topic,),
        ).fetchone()
    else:
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
