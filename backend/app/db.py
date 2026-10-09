"""Small SQLite persistence layer for the 人机恋 API.

The project intentionally uses the stdlib sqlite3 module instead of an ORM. It
keeps the demo easy to run (a single file database and no migration service)
while still giving the API a clear persistence boundary that can be swapped
for Postgres later.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | None = None) -> None:
        default = Path(__file__).resolve().parents[1] / "data" / "companion.sqlite3"
        configured = path or os.getenv("DATABASE_URL", str(default))
        # Accept sqlite:///foo.db as a convenience for deployment.
        if configured.startswith("sqlite:///"):
            configured = configured[len("sqlite:///") :]
        self.path = Path(configured)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.init_schema()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS personas (
          id TEXT PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          tagline TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '',
          avatar TEXT NOT NULL DEFAULT '',
          accent TEXT NOT NULL DEFAULT '#9e7b67',
          system_prompt TEXT NOT NULL DEFAULT '',
          traits_json TEXT NOT NULL DEFAULT '[]',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
          title TEXT NOT NULL DEFAULT '新的对话',
          status TEXT NOT NULL DEFAULT 'active',
          context_summary TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
        CREATE TABLE IF NOT EXISTS messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK(role IN ('system', 'user', 'assistant')),
          content TEXT NOT NULL,
          metadata_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
        CREATE TABLE IF NOT EXISTS memories (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          category TEXT NOT NULL DEFAULT 'profile',
          content TEXT NOT NULL,
          importance REAL NOT NULL DEFAULT 0.5,
          source_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS companion_states (
          session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
          mood TEXT NOT NULL DEFAULT 'curious',
          energy INTEGER NOT NULL DEFAULT 72 CHECK(energy BETWEEN 0 AND 100),
          trust INTEGER NOT NULL DEFAULT 50 CHECK(trust BETWEEN 0 AND 100),
          intimacy INTEGER NOT NULL DEFAULT 18 CHECK(intimacy BETWEEN 0 AND 100),
          tension INTEGER NOT NULL DEFAULT 0 CHECK(tension BETWEEN 0 AND 100),
          affection INTEGER NOT NULL DEFAULT 50 CHECK(affection BETWEEN 0 AND 100),
          jealousy INTEGER NOT NULL DEFAULT 0 CHECK(jealousy BETWEEN 0 AND 100),
          state_json TEXT NOT NULL DEFAULT '{}',
          last_interaction_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS promises (
          id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
          content TEXT NOT NULL,
          promised_by TEXT NOT NULL DEFAULT 'companion',
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'kept', 'broken', 'cancelled')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_promises_session ON promises(session_id, updated_at DESC);
        """
        with self._lock, self.connection() as conn:
            conn.executescript(schema)

    @staticmethod
    def decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in ("traits_json", "metadata_json"):
            if key in data:
                try:
                    decoded = json.loads(data.pop(key) or ("[]" if key == "traits_json" else "{}"))
                except json.JSONDecodeError:
                    decoded = [] if key == "traits_json" else {}
                data["traits" if key == "traits_json" else "metadata"] = decoded
        return data

    def seed_personas(self, personas: list[dict[str, Any]]) -> None:
        now = utc_now()
        with self._lock, self.connection() as conn:
            for p in personas:
                conn.execute(
                    """INSERT OR IGNORE INTO personas
                       (id, slug, name, tagline, description, avatar, accent,
                        system_prompt, traits_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        p.get("id") or str(uuid.uuid4()),
                        p["slug"],
                        p["name"],
                        p.get("tagline", ""),
                        p.get("description", ""),
                        p.get("avatar", ""),
                        p.get("accent", "#9e7b67"),
                        p.get("system_prompt", ""),
                        json.dumps(p.get("traits", []), ensure_ascii=False),
                        now,
                    ),
                )

    def list_personas(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute("SELECT * FROM personas ORDER BY created_at ASC").fetchall()
        return [self.decode(row) for row in rows if row is not None]

    def get_persona(self, persona_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM personas WHERE id = ? OR slug = ?", (persona_id, persona_id)).fetchone()
        return self.decode(row)

    def create_session(self, persona_id: str, title: str = "新的对话") -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                "INSERT INTO sessions (id, persona_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, persona_id, title.strip() or "新的对话", now, now),
            )
            conn.execute("INSERT INTO companion_states (session_id, last_interaction_at) VALUES (?, ?)", (session_id, now))
            row = conn.execute(
                "SELECT s.*, p.name AS persona_name, p.slug AS persona_slug, p.avatar AS persona_avatar, p.accent AS persona_accent "
                "FROM sessions s JOIN personas p ON p.id = s.persona_id WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        return self.decode(row) or {}

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT s.*, p.name AS persona_name, p.slug AS persona_slug, p.avatar AS persona_avatar, p.accent AS persona_accent "
                "FROM sessions s JOIN personas p ON p.id = s.persona_id ORDER BY s.updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self.decode(row) for row in rows if row is not None]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT s.*, p.name AS persona_name, p.slug AS persona_slug, p.avatar AS persona_avatar, p.accent AS persona_accent, "
                "p.system_prompt, p.traits_json FROM sessions s JOIN personas p ON p.id = s.persona_id WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        return self.decode(row)

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self.connection() as conn:
            result = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return result.rowcount > 0

    def touch_session(self, session_id: str) -> None:
        with self._lock, self.connection() as conn:
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (utc_now(), session_id))

    def get_state(self, session_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM companion_states WHERE session_id = ?", (session_id,)).fetchone()
        return self.decode(row)

    def update_state(self, session_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"mood", "energy", "trust", "intimacy", "tension", "affection", "jealousy", "state_json"}
        updates = {key: value for key, value in changes.items() if key in allowed}
        if not updates:
            return self.get_state(session_id)
        updates["last_interaction_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._lock, self.connection() as conn:
            conn.execute(f"UPDATE companion_states SET {assignments} WHERE session_id = ?", (*updates.values(), session_id))
            row = conn.execute("SELECT * FROM companion_states WHERE session_id = ?", (session_id,)).fetchone()
        return self.decode(row)

    def add_message(self, session_id: str, role: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        with self._lock, self.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (session_id, role, content, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, role, content, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
            conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            conn.execute("UPDATE companion_states SET last_interaction_at = ? WHERE session_id = ?", (now, session_id))
        return self.decode(row) or {}

    def list_messages(self, session_id: str, limit: int = 100, before_id: int | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 200))
        with self.connection() as conn:
            if before_id is None:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?", (session_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
                    (session_id, before_id, limit),
                ).fetchall()
        return [self.decode(row) for row in reversed(rows) if row is not None]

    def add_memory(
        self,
        session_id: str,
        content: str,
        category: str = "profile",
        importance: float = 0.5,
        source_message_id: int | None = None,
    ) -> dict[str, Any]:
        memory_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                "INSERT INTO memories (id, session_id, category, content, importance, source_message_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (memory_id, session_id, category.strip() or "profile", content.strip(), max(0, min(float(importance), 1)), source_message_id, now, now),
            )
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self.decode(row) or {}

    def list_memories(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE session_id = ? ORDER BY importance DESC, updated_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [self.decode(row) for row in rows if row is not None]

    def delete_memory(self, session_id: str, memory_id: str) -> bool:
        with self._lock, self.connection() as conn:
            result = conn.execute("DELETE FROM memories WHERE id = ? AND session_id = ?", (memory_id, session_id))
        return result.rowcount > 0

    def add_promise(self, session_id: str, content: str, promised_by: str = "companion") -> dict[str, Any]:
        promise_id = str(uuid.uuid4())
        now = utc_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                "INSERT INTO promises (id, session_id, content, promised_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (promise_id, session_id, content.strip(), promised_by, now, now),
            )
            row = conn.execute("SELECT * FROM promises WHERE id = ?", (promise_id,)).fetchone()
        return self.decode(row) or {}

    def list_promises(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM promises WHERE session_id = ? AND status = 'pending' ORDER BY updated_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [self.decode(row) for row in rows if row is not None]

    def update_promise(self, session_id: str, promise_id: str, status: str) -> dict[str, Any] | None:
        if status not in {"pending", "kept", "broken", "cancelled"}:
            return None
        with self._lock, self.connection() as conn:
            conn.execute("UPDATE promises SET status = ?, updated_at = ? WHERE id = ? AND session_id = ?", (status, utc_now(), promise_id, session_id))
            row = conn.execute("SELECT * FROM promises WHERE id = ? AND session_id = ?", (promise_id, session_id)).fetchone()
        return self.decode(row)
