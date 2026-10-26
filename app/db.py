"""SQLite storage for the single connected TikTok account (row id = 1)."""

import sqlite3
import time

from app.config import settings


def _conn() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                open_id TEXT NOT NULL,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
            """
        )


def save_token(data: dict) -> None:
    """Save a TikTok /oauth/token/ response."""
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO token (id, open_id, access_token, refresh_token, expires_at)
            VALUES (1, ?, ?, ?, ?)
            """,
            (
                data["open_id"],
                data["access_token"],
                data["refresh_token"],
                int(time.time()) + int(data["expires_in"]),
            ),
        )


def get_token() -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM token WHERE id = 1").fetchone()
    return dict(row) if row else None
