"""SQLite-хранилище: пользователи, события, заявки, вопросы и база знаний RAG."""

from __future__ import annotations

import json
import sqlite3
import threading
from array import array
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY,
    username        TEXT,
    first_name      TEXT,
    last_name       TEXT,
    language_code   TEXT,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    kind        TEXT NOT NULL,
    payload     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_user_kind ON events (user_id, kind, created_at);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events (kind, created_at);

CREATE TABLE IF NOT EXISTS query_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT,
    sources     TEXT,
    top_score   REAL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_log_user ON query_log (user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log (created_at);

CREATE TABLE IF NOT EXISTS leads (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'express_audit',
    name        TEXT,
    company     TEXT,
    site        TEXT,
    contact     TEXT,
    comment     TEXT,
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status, created_at);
CREATE INDEX IF NOT EXISTS idx_leads_user ON leads (user_id, created_at);

CREATE TABLE IF NOT EXISTS documents (
    url           TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    chars         INTEGER NOT NULL,
    chunks        INTEGER NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    url              TEXT NOT NULL,
    title            TEXT NOT NULL,
    ordinal          INTEGER NOT NULL,
    text             TEXT NOT NULL,
    embedding        BLOB,
    embedding_model  TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_url ON chunks (url);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(slots=True)
class TelegramUser:
    """Снимок пользователя Telegram (не зависит от aiogram)."""

    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None

    @classmethod
    def from_aiogram(cls, user: Any) -> "TelegramUser":
        return cls(
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
        )

    @property
    def full_name(self) -> str:
        parts = [self.first_name or "", self.last_name or ""]
        return " ".join(part for part in parts if part).strip() or "без имени"

    @property
    def handle(self) -> str:
        return f"@{self.username}" if self.username else "—"


@dataclass(slots=True)
class NewChunk:
    text: str
    embedding: list[float] | None = None


@dataclass(slots=True)
class KnowledgeRow:
    id: int
    url: str
    title: str
    text: str
    embedding: list[float] | None = None


def _encode_vector(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def _decode_vector(blob: bytes | None) -> list[float] | None:
    if not blob:
        return None
    arr = array("f")
    arr.frombytes(blob)
    return list(arr)


class Database:
    """Тонкая синхронная обёртка над SQLite. Трафик бота небольшой,
    поэтому отдельный пул соединений здесь избыточен."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ users

    def upsert_user(self, user: TelegramUser) -> bool:
        """Создаёт/обновляет пользователя. Возвращает True, если он новый."""
        now = iso_now()
        with self._lock, self._conn:
            row = self._conn.execute("SELECT id FROM users WHERE id = ?", (user.id,)).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE users SET username = ?, first_name = ?, last_name = ?, "
                    "language_code = ?, last_seen_at = ? WHERE id = ?",
                    (user.username, user.first_name, user.last_name, user.language_code, now, user.id),
                )
                return False
            self._conn.execute(
                "INSERT INTO users (id, username, first_name, last_name, language_code, "
                "created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user.id, user.username, user.first_name, user.last_name, user.language_code, now, now),
            )
            return True

    def get_user(self, user_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    # ----------------------------------------------------------------- events

    def log_event(self, user_id: int | None, kind: str, payload: dict[str, Any] | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO events (user_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (user_id, kind, json.dumps(payload, ensure_ascii=False) if payload else None, iso_now()),
            )

    def last_event_at(self, user_id: int, kind: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT created_at FROM events WHERE user_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1",
                (user_id, kind),
            ).fetchone()
        return parse_iso(row["created_at"]) if row else None

    def event_count(self, user_id: int, kind: str, since: datetime | None = None) -> int:
        sql = "SELECT COUNT(*) FROM events WHERE user_id = ? AND kind = ?"
        params: list[Any] = [user_id, kind]
        if since:
            sql += " AND created_at >= ?"
            params.append(since.isoformat(timespec="seconds"))
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()[0])

    # ---------------------------------------------------------------- queries

    def log_question(
        self,
        user_id: int,
        question: str,
        answer: str | None = None,
        sources: Sequence[str] = (),
        top_score: float | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO query_log (user_id, question, answer, sources, top_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    question,
                    answer,
                    json.dumps(list(sources), ensure_ascii=False),
                    top_score,
                    iso_now(),
                ),
            )

    def recent_questions(self, user_id: int, limit: int = 5) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT question FROM query_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [row["question"] for row in rows]

    def questions_count(self, user_id: int, since: datetime | None = None) -> int:
        sql = "SELECT COUNT(*) FROM query_log WHERE user_id = ?"
        params: list[Any] = [user_id]
        if since:
            sql += " AND created_at >= ?"
            params.append(since.isoformat(timespec="seconds"))
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()[0])

    def question_history(self, user_id: int, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
        """Последние вопросы пользователя (для карточки у менеджеров)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT question, created_at, top_score FROM query_log "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_id, limit, max(0, offset)),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_user_by_username(self, username: str) -> int | None:
        value = username.strip().lstrip("@")
        if not value:
            return None
        with self._lock:
            row = self._conn.execute("SELECT id FROM users WHERE lower(username) = lower(?)", (value,)).fetchone()
        return int(row["id"]) if row else None

    # ------------------------------------------------------------------ leads

    def create_lead(
        self,
        user_id: int,
        *,
        kind: str = "express_audit",
        name: str | None = None,
        company: str | None = None,
        site: str | None = None,
        contact: str | None = None,
        comment: str | None = None,
    ) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO leads (user_id, kind, name, company, site, contact, comment, "
                "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                (user_id, kind, name, company, site, contact, comment, iso_now()),
            )
            return int(cursor.lastrowid)

    def list_leads(
        self,
        limit: int = 10,
        status: str | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM leads"
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def leads_count(self, user_id: int | None = None, status: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM leads"
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()[0])

    def set_lead_status(self, lead_id: int, status: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
            return cursor.rowcount > 0

    # -------------------------------------------------------------- knowledge

    def reset_knowledge(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks")
            self._conn.execute("DELETE FROM documents")

    def document_hash(self, url: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT content_hash FROM documents WHERE url = ?", (url,)).fetchone()
        return row["content_hash"] if row else None

    def document_has_vectors(self, url: str, embedding_model: str) -> bool:
        """Есть ли у страницы векторы актуальной модели (для дозагрузки эмбеддингов)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM chunks WHERE url = ? AND embedding IS NOT NULL AND embedding_model = ? LIMIT 1",
                (url, embedding_model),
            ).fetchone()
        return row is not None

    def replace_document(
        self,
        url: str,
        title: str,
        content_hash: str,
        chars: int,
        chunks: Sequence[NewChunk],
        embedding_model: str | None = None,
    ) -> int:
        """Атомарно заменяет чанки страницы. Возвращает количество чанков."""
        now = iso_now()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM chunks WHERE url = ?", (url,))
            self._conn.executemany(
                "INSERT INTO chunks (url, title, ordinal, text, embedding, embedding_model, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        url,
                        title,
                        index,
                        chunk.text,
                        _encode_vector(chunk.embedding) if chunk.embedding else None,
                        embedding_model if chunk.embedding else None,
                        now,
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )
            self._conn.execute(
                "INSERT INTO documents (url, title, content_hash, chars, chunks, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET title = excluded.title, "
                "content_hash = excluded.content_hash, chars = excluded.chars, "
                "chunks = excluded.chunks, updated_at = excluded.updated_at",
                (url, title, content_hash, chars, len(chunks), now),
            )
        return len(chunks)

    def fetch_chunks(self, embedding_model: str) -> list[KnowledgeRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, url, title, text, embedding, embedding_model FROM chunks ORDER BY id"
            ).fetchall()
        result: list[KnowledgeRow] = []
        for row in rows:
            vector = None
            if row["embedding_model"] and row["embedding_model"] == embedding_model:
                vector = _decode_vector(row["embedding"])
            result.append(
                KnowledgeRow(
                    id=int(row["id"]),
                    url=row["url"],
                    title=row["title"],
                    text=row["text"],
                    embedding=vector,
                )
            )
        return result

    def knowledge_docs(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT url, title, chars, chunks, updated_at FROM documents ORDER BY url"
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ stats

    def stats(self) -> dict[str, int]:
        today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
        queries = {
            "users": "SELECT COUNT(*) FROM users",
            "users_today": "SELECT COUNT(*) FROM users WHERE created_at >= ?",
            "active_today": "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= ?",
            "questions": "SELECT COUNT(*) FROM query_log",
            "questions_today": "SELECT COUNT(*) FROM query_log WHERE created_at >= ?",
            "leads": "SELECT COUNT(*) FROM leads",
            "leads_new": "SELECT COUNT(*) FROM leads WHERE status = 'new'",
            "documents": "SELECT COUNT(*) FROM documents",
            "chunks": "SELECT COUNT(*) FROM chunks",
        }
        result: dict[str, int] = {}
        with self._lock:
            for key, sql in queries.items():
                params: tuple[Any, ...] = (today,) if "?" in sql else ()
                result[key] = int(self._conn.execute(sql, params).fetchone()[0])
        return result
