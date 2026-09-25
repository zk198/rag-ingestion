from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from .config import Settings
from .utils import ensure_dir, to_fts_query


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_path TEXT,
    item_type TEXT NOT NULL,
    folder TEXT,
    subject TEXT,
    sender TEXT,
    recipients TEXT,
    cc TEXT,
    bcc TEXT,
    sent_at TEXT,
    body_text TEXT,
    body_html TEXT,
    raw_path TEXT,
    sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    original_name TEXT,
    saved_path TEXT,
    media_type TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT,
    extracted_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    source_path TEXT,
    title TEXT,
    media_type TEXT,
    sha256 TEXT,
    extracted_text TEXT,
    raw_path TEXT,
    parent_message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
    parent_attachment_id TEXT REFERENCES attachments(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    source_name TEXT NOT NULL,
    parent_kind TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    id UNINDEXED,
    source_name UNINDEXED,
    parent_kind UNINDEXED,
    parent_id UNINDEXED,
    text,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    account_email TEXT,
    account_type TEXT NOT NULL DEFAULT 'other',
    display_name TEXT,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_messages_source_name ON messages(source_name);
CREATE INDEX IF NOT EXISTS idx_attachments_message_id ON attachments(message_id);
CREATE INDEX IF NOT EXISTS idx_documents_parent_message ON documents(parent_message_id);
CREATE INDEX IF NOT EXISTS idx_documents_parent_attachment ON documents(parent_attachment_id);
CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(parent_kind, parent_id);
"""


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        ensure_dir(settings.data_dir)
        ensure_dir(settings.temp_dir)
        ensure_dir(settings.attachments_dir)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def connection(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        ensure_dir(Path(self.settings.db_path).parent)
        with self.connection() as conn:
            conn.executescript(SCHEMA_SQL)

    def upsert_source(
        self,
        name: str,
        *,
        account_email: str | None = None,
        account_type: str = "other",
        display_name: str | None = None,
        description: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO sources (name, account_email, account_type, display_name, description)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    account_email = COALESCE(excluded.account_email, sources.account_email),
                    account_type = excluded.account_type,
                    display_name = COALESCE(excluded.display_name, sources.display_name),
                    description = COALESCE(excluded.description, sources.description),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (name, account_email, account_type, display_name, description),
            )

    def get_source(self, name: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sources WHERE name = ?", (name,)).fetchone()
            return dict(row) if row else None

    def clear_source(self, source_name: str) -> None:
        with self.connection() as conn:
            message_ids = [row[0] for row in conn.execute("SELECT id FROM messages WHERE source_name = ?", (source_name,))]
            document_ids = [row[0] for row in conn.execute("SELECT id FROM documents WHERE source_name = ?", (source_name,))]

            for row_id in message_ids:
                conn.execute("DELETE FROM chunks_fts WHERE parent_kind = 'message' AND parent_id = ?", (row_id,))
                conn.execute("DELETE FROM chunks WHERE parent_kind = 'message' AND parent_id = ?", (row_id,))

            for row_id in document_ids:
                conn.execute("DELETE FROM chunks_fts WHERE parent_kind = 'document' AND parent_id = ?", (row_id,))
                conn.execute("DELETE FROM chunks WHERE parent_kind = 'document' AND parent_id = ?", (row_id,))

            conn.execute("DELETE FROM documents WHERE source_name = ?", (source_name,))
            conn.execute("DELETE FROM attachments WHERE source_name = ?", (source_name,))
            conn.execute("DELETE FROM messages WHERE source_name = ?", (source_name,))

    def insert_message(self, data: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO messages (
                    id, source_name, source_path, item_type, folder, subject, sender, recipients,
                    cc, bcc, sent_at, body_text, body_html, raw_path, sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data["source_name"],
                    data.get("source_path"),
                    data.get("item_type", "email"),
                    data.get("folder"),
                    data.get("subject"),
                    data.get("sender"),
                    data.get("recipients"),
                    data.get("cc"),
                    data.get("bcc"),
                    data.get("sent_at"),
                    data.get("body_text"),
                    data.get("body_html"),
                    data.get("raw_path"),
                    data.get("sha256"),
                ),
            )

    def insert_attachment(self, data: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO attachments (
                    id, message_id, source_name, original_name, saved_path, media_type,
                    size_bytes, sha256, extracted_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data["message_id"],
                    data["source_name"],
                    data.get("original_name"),
                    data.get("saved_path"),
                    data.get("media_type"),
                    int(data.get("size_bytes", 0)),
                    data.get("sha256"),
                    data.get("extracted_text"),
                ),
            )

    def insert_document(self, data: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO documents (
                    id, source_name, source_path, title, media_type, sha256,
                    extracted_text, raw_path, parent_message_id, parent_attachment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data["source_name"],
                    data.get("source_path"),
                    data.get("title"),
                    data.get("media_type"),
                    data.get("sha256"),
                    data.get("extracted_text"),
                    data.get("raw_path"),
                    data.get("parent_message_id"),
                    data.get("parent_attachment_id"),
                ),
            )

    def replace_chunks(self, source_name: str, parent_kind: str, parent_id: str, chunks: Iterable[dict[str, Any]]) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM chunks_fts WHERE parent_kind = ? AND parent_id = ?", (parent_kind, parent_id))
            conn.execute("DELETE FROM chunks WHERE parent_kind = ? AND parent_id = ?", (parent_kind, parent_id))
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO chunks (id, source_name, parent_kind, parent_id, ordinal, start_char, end_char, text)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["id"],
                        source_name,
                        parent_kind,
                        parent_id,
                        chunk["ordinal"],
                        chunk["start_char"],
                        chunk["end_char"],
                        chunk["text"],
                    ),
                )
                conn.execute(
                    "INSERT INTO chunks_fts (id, source_name, parent_kind, parent_id, text) VALUES (?, ?, ?, ?, ?)",
                    (chunk["id"], source_name, parent_kind, parent_id, chunk["text"]),
                )

    def search_chunks(self, query: str, limit: int = 10, source_name: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT c.*, bm25(chunks_fts) AS score "
            "FROM chunks_fts JOIN chunks c USING(id) "
            "WHERE chunks_fts MATCH ?"
        )
        params: list[Any] = [to_fts_query(query)]
        if source_name:
            sql += " AND c.source_name = ?"
            params.append(source_name)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
            if not row:
                return None
            message = dict(row)
            attachments = conn.execute(
                "SELECT * FROM attachments WHERE message_id = ? ORDER BY created_at, id", (message_id,)
            ).fetchall()
            message["attachments"] = [dict(item) for item in attachments]
            documents = conn.execute(
                "SELECT * FROM documents WHERE parent_message_id = ? ORDER BY created_at, id", (message_id,)
            ).fetchall()
            message["documents"] = [dict(item) for item in documents]
            return message

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
            return dict(row) if row else None

    def list_sources(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """
                WITH source_names AS (
                    SELECT source_name FROM messages
                    UNION
                    SELECT source_name FROM attachments
                    UNION
                    SELECT source_name FROM documents
                    UNION
                    SELECT source_name FROM chunks
                    UNION
                    SELECT name AS source_name FROM sources
                )
                SELECT s.source_name,
                       src.account_email,
                       src.account_type,
                       src.display_name,
                       src.description,
                       (SELECT COUNT(*) FROM messages m WHERE m.source_name = s.source_name) AS message_count,
                       (SELECT COUNT(*) FROM documents d WHERE d.source_name = s.source_name) AS document_count,
                       (SELECT COUNT(*) FROM attachments a WHERE a.source_name = s.source_name) AS attachment_count,
                       (SELECT COUNT(*) FROM chunks c WHERE c.source_name = s.source_name) AS chunk_count
                FROM source_names s
                LEFT JOIN sources src ON src.name = s.source_name
                ORDER BY s.source_name
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            result = {
                "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                "attachments": conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0],
                "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
                "chunks": conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                "sources": conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT source_name FROM messages
                        UNION SELECT source_name FROM attachments
                        UNION SELECT source_name FROM documents
                        UNION SELECT source_name FROM chunks
                    )
                    """
                ).fetchone()[0],
            }
            return result
