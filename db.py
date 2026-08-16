import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("pendientes.db")
MIGRATION = Path("migrations/001_init.sql")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(MIGRATION.read_text())


def create_pending(chat_id: int, created_by: int, title: str) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO pendings (chat_id, created_by, title, created_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, created_by, title, now),
        )
        return cur.lastrowid


def list_open(chat_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM pendings WHERE chat_id = ? AND state = 'OPEN' "
            "ORDER BY created_at",
            (chat_id,),
        ).fetchall()
