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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_due "
                "ON reminders(delivered, due_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_notes_owner ON notes(owner_id, id DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_owner_status ON tasks(owner_id, status, id DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS missions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    goal TEXT NOT NULL,
                    report TEXT NOT NULL,
                    agents TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_missions_owner ON missions(owner_id, id DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id INTEGER NOT NULL,
                    draft_id INTEGER NOT NULL,
                    channel_id TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_posts_due ON scheduled_posts(status, scheduled_at)"
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

    def mark_published(self, draft_id: int, *, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE drafts SET status = 'published' WHERE id = ? AND owner_id = ? AND status = 'draft'",
                (int(draft_id), int(owner_id)),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    "UPDATE scheduled_posts SET status = 'cancelled' WHERE draft_id = ? AND owner_id = ? AND status = 'pending'",
                    (int(draft_id), int(owner_id)),
                )
        return cursor.rowcount == 1

    def add_reminder(self, *, owner_id: int, text: str, due_at: str) -> int:
        text = text.strip()
        if not text or not due_at:
            raise ValueError("reminder text and due time must not be empty")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO reminders (owner_id, text, due_at) VALUES (?, ?, ?)",
                (int(owner_id), text, due_at),
            )
            return int(cursor.lastrowid)

    def due_reminders(self, *, now: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, owner_id, text, due_at FROM reminders WHERE delivered = 0 AND due_at <= ? ORDER BY due_at LIMIT 100",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_reminder_delivered(self, reminder_id: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE reminders SET delivered = 1 WHERE id = ? AND delivered = 0",
                (int(reminder_id),),
            )

    def list_reminders(self, *, owner_id: int, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, text, due_at FROM reminders WHERE owner_id = ? AND delivered = 0 ORDER BY due_at LIMIT ?",
                (int(owner_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_reminder(self, reminder_id: int, *, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM reminders WHERE id = ? AND owner_id = ? AND delivered = 0",
                (int(reminder_id), int(owner_id)),
            )
        return cursor.rowcount == 1

    def count_notes(self, *, owner_id: int) -> int:
        with self._connection() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM notes WHERE owner_id = ?", (int(owner_id),)).fetchone()
        return int(row["total"])

    def count_open_tasks(self, *, owner_id: int) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM tasks WHERE owner_id = ? AND status = 'open'",
                (int(owner_id),),
            ).fetchone()
        return int(row["total"])

    def count_pending_reminders(self, *, owner_id: int) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM reminders WHERE owner_id = ? AND delivered = 0",
                (int(owner_id),),
            ).fetchone()
        return int(row["total"])

    def add_note(self, *, owner_id: int, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("note must not be empty")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO notes (owner_id, text) VALUES (?, ?)",
                (int(owner_id), text),
            )
            return int(cursor.lastrowid)

    def list_notes(self, *, owner_id: int, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, text, created_at FROM notes WHERE owner_id = ? ORDER BY id DESC LIMIT ?",
                (int(owner_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_note(self, note_id: int, *, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM notes WHERE id = ? AND owner_id = ?",
                (int(note_id), int(owner_id)),
            )
        return cursor.rowcount == 1

    def add_task(self, *, owner_id: int, text: str) -> int:
        text = text.strip()
        if not text:
            raise ValueError("task must not be empty")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks (owner_id, text) VALUES (?, ?)",
                (int(owner_id), text),
            )
            return int(cursor.lastrowid)

    def list_tasks(self, *, owner_id: int, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, text, status, created_at FROM tasks WHERE owner_id = ? ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC LIMIT ?",
                (int(owner_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def schedule_post(
        self, *, owner_id: int, draft_id: int, channel_id: str, scheduled_at: str
    ) -> int:
        with self._connection() as connection:
            draft = connection.execute(
                "SELECT status FROM drafts WHERE id = ? AND owner_id = ?",
                (int(draft_id), int(owner_id)),
            ).fetchone()
            if draft is None or draft["status"] != "draft":
                raise ValueError("draft is missing or no longer publishable")
            existing = connection.execute(
                "SELECT id FROM scheduled_posts WHERE draft_id = ? AND owner_id = ? AND status = 'pending'",
                (int(draft_id), int(owner_id)),
            ).fetchone()
            if existing:
                raise ValueError("draft already has a pending schedule")
            cursor = connection.execute(
                "INSERT INTO scheduled_posts (owner_id, draft_id, channel_id, scheduled_at) VALUES (?, ?, ?, ?)",
                (int(owner_id), int(draft_id), channel_id, scheduled_at),
            )
            return int(cursor.lastrowid)

    def due_scheduled_posts(self, *, now: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.id, s.owner_id, s.draft_id, s.channel_id, d.content
                   FROM scheduled_posts s JOIN drafts d ON d.id = s.draft_id
                   WHERE s.status = 'pending' AND s.scheduled_at <= ?
                   ORDER BY s.scheduled_at LIMIT 50""",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_scheduled_post_published(self, schedule_id: int, draft_id: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE scheduled_posts SET status = 'published' WHERE id = ? AND status = 'pending'",
                (int(schedule_id),),
            )
            connection.execute(
                "UPDATE drafts SET status = 'published' WHERE id = ? AND status = 'draft'",
                (int(draft_id),),
            )

    def list_scheduled_posts(self, *, owner_id: int, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.id, s.draft_id, s.scheduled_at, d.topic
                   FROM scheduled_posts s JOIN drafts d ON d.id = s.draft_id
                   WHERE s.owner_id = ? AND s.status = 'pending'
                   ORDER BY s.scheduled_at LIMIT ?""",
                (int(owner_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_scheduled_post(self, schedule_id: int, *, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE scheduled_posts SET status = 'cancelled' WHERE id = ? AND owner_id = ? AND status = 'pending'",
                (int(schedule_id), int(owner_id)),
            )
        return cursor.rowcount == 1

    def count_pending_scheduled_posts(self, *, owner_id: int) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM scheduled_posts WHERE owner_id = ? AND status = 'pending'",
                (int(owner_id),),
            ).fetchone()
        return int(row["total"])

    def count_missions(self, *, owner_id: int) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM missions WHERE owner_id = ?",
                (int(owner_id),),
            ).fetchone()
        return int(row["total"])

    def save_mission(self, *, owner_id: int, goal: str, report: str, agents: str) -> int:
        goal, report, agents = goal.strip(), report.strip(), agents.strip()
        if not goal or not report or not agents:
            raise ValueError("mission fields must not be empty")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO missions (owner_id, goal, report, agents) VALUES (?, ?, ?, ?)",
                (int(owner_id), goal, report, agents),
            )
            return int(cursor.lastrowid)

    def list_missions(self, *, owner_id: int, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, goal, agents, created_at FROM missions WHERE owner_id = ? ORDER BY id DESC LIMIT ?",
                (int(owner_id), limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_mission(self, mission_id: int, *, owner_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, owner_id, goal, report, agents, created_at FROM missions WHERE id = ? AND owner_id = ?",
                (int(mission_id), int(owner_id)),
            ).fetchone()
        return dict(row) if row is not None else None

    def complete_task(self, task_id: int, *, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'done', completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ? AND owner_id = ? AND status = 'open'",
                (int(task_id), int(owner_id)),
            )
        return cursor.rowcount == 1

    def delete_task(self, task_id: int, *, owner_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM tasks WHERE id = ? AND owner_id = ?",
                (int(task_id), int(owner_id)),
            )
        return cursor.rowcount == 1
