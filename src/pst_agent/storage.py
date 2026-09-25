from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from .config import Settings
from .utils import ensure_dir, to_fts_query

TENANT_ID: ContextVar[str | None] = ContextVar("rag_tenant_id", default=None)
USER_ID: ContextVar[str | None] = ContextVar("rag_user_id", default=None)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sources (
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    account_email TEXT,
    account_type TEXT NOT NULL DEFAULT 'other',
    display_name TEXT,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, name)
);
CREATE TABLE IF NOT EXISTS messages (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    user_id TEXT,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, source_name) REFERENCES sources(tenant_id, name) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS attachments (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    user_id TEXT,
    message_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    original_name TEXT,
    saved_path TEXT,
    media_type TEXT,
    size_bytes BIGINT NOT NULL,
    sha256 TEXT,
    extracted_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, message_id) REFERENCES messages(tenant_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS documents (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    user_id TEXT,
    source_name TEXT NOT NULL,
    source_path TEXT,
    title TEXT,
    media_type TEXT,
    sha256 TEXT,
    extracted_text TEXT,
    raw_path TEXT,
    parent_message_id TEXT,
    parent_attachment_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, source_name) REFERENCES sources(tenant_id, name) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, parent_message_id) REFERENCES messages(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, parent_attachment_id) REFERENCES attachments(tenant_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS chunks (
    tenant_id TEXT NOT NULL,
    id TEXT NOT NULL,
    user_id TEXT,
    source_name TEXT NOT NULL,
    parent_kind TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, source_name) REFERENCES sources(tenant_id, name) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_parent ON chunks(tenant_id, parent_kind, parent_id);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(tenant_id, source_name);
CREATE TABLE IF NOT EXISTS rag_outbox (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT,
    source_name TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempts INTEGER NOT NULL DEFAULT 0,
    locked_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending ON rag_outbox(available_at, id)
WHERE processed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_outbox_tenant ON rag_outbox(tenant_id, id);
"""

class Store:
    """PostgreSQL authority and transactional-outbox boundary for Ninido."""

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.postgres_dsn:
            raise ValueError("PST_AGENT_POSTGRES_DSN is required")
        ensure_dir(settings.data_dir)
        ensure_dir(settings.temp_dir)
        ensure_dir(settings.attachments_dir)
        self._init_db()

    @property
    def tenant_id(self) -> str:
        value = TENANT_ID.get() or self.settings.tenant_id
        if not value:
            raise ValueError("RAG tenant context is required")
        return value

    @property
    def user_id(self) -> str | None:
        return USER_ID.get() or self.settings.user_id

    @contextmanager
    def connection(self):
        with psycopg.connect(self.settings.postgres_dsn, row_factory=dict_row) as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_db(self) -> None:
        with self.connection() as conn:
            conn.execute(SCHEMA_SQL)

    def _outbox(self, conn, event_type: str, aggregate_type: str,
                aggregate_id: str | None = None, source_name: str | None = None,
                payload: dict[str, Any] | None = None) -> None:
        conn.execute(
            """INSERT INTO rag_outbox
               (tenant_id,user_id,event_type,aggregate_type,aggregate_id,source_name,payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""",
            (self.tenant_id, self.user_id, event_type, aggregate_type,
             aggregate_id, source_name, json.dumps(payload or {}, default=str)),
        )

    def upsert_source(self, name: str, *, account_email: str | None = None,
                      account_type: str = "other", display_name: str | None = None,
                      description: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute("""INSERT INTO sources
                (tenant_id,name,account_email,account_type,display_name,description)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,name) DO UPDATE SET
                  account_email=COALESCE(EXCLUDED.account_email,sources.account_email),
                  account_type=EXCLUDED.account_type,
                  display_name=COALESCE(EXCLUDED.display_name,sources.display_name),
                  description=COALESCE(EXCLUDED.description,sources.description),
                  updated_at=now()""",
                (self.tenant_id, name, account_email, account_type, display_name, description))
            self._outbox(conn, "source_upserted", "source", name, name)

    def get_source(self, name: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM sources WHERE tenant_id=%s AND name=%s",
                               (self.tenant_id, name)).fetchone()
            return dict(row) if row else None

    def clear_source(self, source_name: str) -> None:
        with self.connection() as conn:
            conn.execute("DELETE FROM sources WHERE tenant_id=%s AND name=%s",
                         (self.tenant_id, source_name))
            self._outbox(conn, "source_cleared", "source", source_name, source_name)

    def insert_message(self, data: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute("""INSERT INTO messages
                (tenant_id,id,user_id,source_name,source_path,item_type,folder,subject,sender,
                 recipients,cc,bcc,sent_at,body_text,body_html,raw_path,sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,id) DO UPDATE SET
                 user_id=EXCLUDED.user_id,source_name=EXCLUDED.source_name,
                 source_path=EXCLUDED.source_path,item_type=EXCLUDED.item_type,
                 folder=EXCLUDED.folder,subject=EXCLUDED.subject,sender=EXCLUDED.sender,
                 recipients=EXCLUDED.recipients,cc=EXCLUDED.cc,bcc=EXCLUDED.bcc,
                 sent_at=EXCLUDED.sent_at,body_text=EXCLUDED.body_text,
                 body_html=EXCLUDED.body_html,raw_path=EXCLUDED.raw_path,sha256=EXCLUDED.sha256""",
                (self.tenant_id,data["id"],self.user_id,data["source_name"],data.get("source_path"),
                 data.get("item_type","email"),data.get("folder"),data.get("subject"),
                 data.get("sender"),data.get("recipients"),data.get("cc"),data.get("bcc"),
                 data.get("sent_at"),data.get("body_text"),data.get("body_html"),
                 data.get("raw_path"),data.get("sha256")))
            self._outbox(conn, "message_upserted", "message", data["id"], data["source_name"])

    def insert_attachment(self, data: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute("""INSERT INTO attachments
                (tenant_id,id,user_id,message_id,source_name,original_name,saved_path,media_type,
                 size_bytes,sha256,extracted_text)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,id) DO UPDATE SET
                 user_id=EXCLUDED.user_id,message_id=EXCLUDED.message_id,
                 source_name=EXCLUDED.source_name,original_name=EXCLUDED.original_name,
                 saved_path=EXCLUDED.saved_path,media_type=EXCLUDED.media_type,
                 size_bytes=EXCLUDED.size_bytes,sha256=EXCLUDED.sha256,
                 extracted_text=EXCLUDED.extracted_text""",
                (self.tenant_id,data["id"],self.user_id,data["message_id"],data["source_name"],
                 data.get("original_name"),data.get("saved_path"),data.get("media_type"),
                 int(data.get("size_bytes",0)),data.get("sha256"),data.get("extracted_text")))
            self._outbox(conn, "attachment_upserted", "attachment", data["id"],
                         data["source_name"], {"message_id": data["message_id"]})

    def insert_document(self, data: dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute("""INSERT INTO documents
                (tenant_id,id,user_id,source_name,source_path,title,media_type,sha256,
                 extracted_text,raw_path,parent_message_id,parent_attachment_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,id) DO UPDATE SET
                 user_id=EXCLUDED.user_id,source_name=EXCLUDED.source_name,
                 source_path=EXCLUDED.source_path,title=EXCLUDED.title,
                 media_type=EXCLUDED.media_type,sha256=EXCLUDED.sha256,
                 extracted_text=EXCLUDED.extracted_text,raw_path=EXCLUDED.raw_path,
                 parent_message_id=EXCLUDED.parent_message_id,
                 parent_attachment_id=EXCLUDED.parent_attachment_id""",
                (self.tenant_id,data["id"],self.user_id,data["source_name"],data.get("source_path"),
                 data.get("title"),data.get("media_type"),data.get("sha256"),
                 data.get("extracted_text"),data.get("raw_path"),
                 data.get("parent_message_id"),data.get("parent_attachment_id")))
            self._outbox(conn, "document_upserted", "document", data["id"], data["source_name"])

    def replace_chunks(self, source_name: str, parent_kind: str, parent_id: str,
                       chunks: Iterable[dict[str, Any]]) -> None:
        materialized = list(chunks)
        with self.connection() as conn:
            conn.execute("DELETE FROM chunks WHERE tenant_id=%s AND parent_kind=%s AND parent_id=%s",
                         (self.tenant_id,parent_kind,parent_id))
            for chunk in materialized:
                conn.execute("""INSERT INTO chunks
                    (tenant_id,id,user_id,source_name,parent_kind,parent_id,ordinal,start_char,end_char,text)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self.tenant_id,chunk["id"],self.user_id,source_name,parent_kind,parent_id,
                     chunk["ordinal"],chunk["start_char"],chunk["end_char"],chunk["text"]))
            self._outbox(conn, "chunks_replaced", parent_kind, parent_id, source_name,
                         {"parent_kind":parent_kind,"parent_id":parent_id})

    def search_chunks(self, query: str, limit: int = 10,
                      source_name: str | None = None) -> list[dict[str, Any]]:
        sql = """SELECT c.*, ts_rank_cd(to_tsvector('simple',coalesce(c.text,'')),
                 plainto_tsquery('simple',%s)) AS score
                 FROM chunks c
                 WHERE c.tenant_id=%s
                   AND to_tsvector('simple',coalesce(c.text,'')) @@ plainto_tsquery('simple',%s)"""
        params: list[Any] = [query, self.tenant_id, query]
        if source_name:
            sql += " AND c.source_name=%s"
            params.append(source_name)
        sql += " ORDER BY score DESC LIMIT %s"
        params.append(limit)
        with self.connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row=conn.execute("SELECT * FROM messages WHERE tenant_id=%s AND id=%s",
                              (self.tenant_id,message_id)).fetchone()
            if not row: return None
            result=dict(row)
            result["attachments"]=[dict(r) for r in conn.execute(
                "SELECT * FROM attachments WHERE tenant_id=%s AND message_id=%s ORDER BY created_at,id",
                (self.tenant_id,message_id)).fetchall()]
            result["documents"]=[dict(r) for r in conn.execute(
                "SELECT * FROM documents WHERE tenant_id=%s AND parent_message_id=%s ORDER BY created_at,id",
                (self.tenant_id,message_id)).fetchall()]
            return result

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row=conn.execute("SELECT * FROM documents WHERE tenant_id=%s AND id=%s",
                              (self.tenant_id,document_id)).fetchone()
            return dict(row) if row else None

    def list_sources(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows=conn.execute("""SELECT s.name AS source_name,s.account_email,s.account_type,
                s.display_name,s.description,
                (SELECT count(*) FROM messages m WHERE m.tenant_id=s.tenant_id AND m.source_name=s.name) message_count,
                (SELECT count(*) FROM documents d WHERE d.tenant_id=s.tenant_id AND d.source_name=s.name) document_count,
                (SELECT count(*) FROM attachments a WHERE a.tenant_id=s.tenant_id AND a.source_name=s.name) attachment_count,
                (SELECT count(*) FROM chunks c WHERE c.tenant_id=s.tenant_id AND c.source_name=s.name) chunk_count
                FROM sources s WHERE s.tenant_id=%s ORDER BY s.name""",(self.tenant_id,)).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self.connection() as conn:
            def count(table): return conn.execute(
                f"SELECT count(*) AS n FROM {table} WHERE tenant_id=%s",(self.tenant_id,)).fetchone()["n"]
            return {"messages":count("messages"),"attachments":count("attachments"),
                    "documents":count("documents"),"chunks":count("chunks"),
                    "sources":count("sources"),
                    "outbox_pending":conn.execute(
                        "SELECT count(*) AS n FROM rag_outbox WHERE tenant_id=%s AND processed_at IS NULL",
                        (self.tenant_id,)).fetchone()["n"]}

@contextmanager
def tenant_context(tenant_id: str, user_id: str | None = None):
    t=TENANT_ID.set(tenant_id)
    u=USER_ID.set(user_id)
    try:
        yield
    finally:
        USER_ID.reset(u)
        TENANT_ID.reset(t)
