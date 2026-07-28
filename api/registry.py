"""프로젝트 메타 저장소 (설계도 6-2절).

checkpoints.db(LangGraph 소유)나 fact_store.db(도메인 데이터)와 섞지 않고
독립 SQLite 파일을 쓴다. 담는 것은 "이 project_id가 무슨 주제이고 지금 무슨
상태인가"뿐이다 — 그래프 상태 자체는 여전히 checkpointer가 소유한다."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from paths import data_path
from typing import Optional

DB_PATH = data_path("sessions.db", Path(__file__).resolve().parent / "sessions.db")

STATUS_RUNNING = "running"
STATUS_AWAITING = "awaiting_review"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

# 이 상태에서는 새 메시지를 받을 수 없다(409 Conflict).
BUSY_STATUSES = {STATUS_RUNNING}
CLOSED_STATUSES = {STATUS_COMPLETED}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id     TEXT PRIMARY KEY,
                topic          TEXT NOT NULL,
                target_market  TEXT NOT NULL,
                status         TEXT NOT NULL,
                docx_path      TEXT,
                error          TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """
        )


def create_project(project_id: str, topic: str, target_market: str) -> dict:
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO projects (project_id, topic, target_market, status,"
            " docx_path, error, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
            (project_id, topic, target_market, STATUS_RUNNING, now, now),
        )
    return get_project(project_id)  # type: ignore[return-value]


def get_project(project_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
    return dict(row) if row else None


def list_projects() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_project(
    project_id: str,
    *,
    status: Optional[str] = None,
    docx_path: Optional[str] = None,
    error: Optional[str] = None,
    clear_error: bool = False,
) -> None:
    """지정한 필드만 갱신한다. error를 지우려면 clear_error=True를 쓴다
    (None을 넘기는 것과 '지운다'를 구분하기 위함)."""
    sets: list[str] = ["updated_at = ?"]
    params: list = [_now()]
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if docx_path is not None:
        sets.append("docx_path = ?")
        params.append(docx_path)
    if clear_error:
        sets.append("error = NULL")
    elif error is not None:
        sets.append("error = ?")
        params.append(error)
    params.append(project_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE project_id = ?", params
        )


def delete_project(project_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))


def running_project_ids() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT project_id FROM projects WHERE status = ?", (STATUS_RUNNING,)
        ).fetchall()
    return [r["project_id"] for r in rows]
