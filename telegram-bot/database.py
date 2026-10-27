"""SQLite persistence for Telegram content drafts."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterator
from contextlib import contextmanager


class DraftStore:
    """Small, thread-safe-by-connection SQLite store for generated drafts."""

    def __init__(self, database_path: str | Path):
        raw_path = str(database_path)
        self.database_path = (
            raw_path if raw_path == ":memory:" else str(Path(raw_path).expanduser())
        )

    def _prepare_path(self) -> None:
        if self.database_path != ":memory:":
            Path(self.database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._prepare_path()
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the schema if this is a fresh database."""
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    topic TEXT NOT NULL,
                    angle TEXT NOT NULL,
                    content TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_drafts_owner_created "
                "ON drafts(owner_id, created_at DESC)"
            )

    def save_draft(
        self,
        *,
        owner_id: int,
        topic: str,
        angle: str,
        content: str,
        model: str,
    ) -> dict[str, Any]:
        topic = topic.strip()
        angle = angle.strip()
        content = content.strip()
        if not topic or not angle or not content:
            raise ValueError("topic, angle, and content must not be empty")

        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO drafts (owner_id, topic, angle, content, model)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(owner_id), topic, angle, content, model.strip()),
            )
            draft_id = cursor.lastrowid

        draft = self.get_draft(int(draft_id), owner_id=int(owner_id))
        if draft is None:  # Defensive: the row was just inserted in this transaction.
            raise RuntimeError("saved draft could not be read back")
        return draft

    def count_drafts(self, *, owner_id: int) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM drafts WHERE owner_id = ?",
                (int(owner_id),),
            ).fetchone()
        return int(row["total"])

    def list_drafts(self, *, owner_id: int, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, owner_id, topic, angle, content, model, status, created_at
                FROM drafts
                WHERE owner_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(owner_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_draft(self, draft_id: int, *, owner_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT id, owner_id, topic, angle, content, model, status, created_at
                FROM drafts
                WHERE id = ? AND owner_id = ?
                """,
                (int(draft_id), int(owner_id)),
            ).fetchone()
        return dict(row) if row is not None else None
