from __future__ import annotations

import os
from pathlib import Path

import pytest

from pst_agent.config import Settings
from pst_agent.storage import Store, tenant_context


def _settings(tmp_path: Path, dsn: str, tenant: str = "tenant-a", user: str = "user-a") -> Settings:
    return Settings(tmp_path, tmp_path / "tmp", tmp_path / "attachments", tmp_path / "unused.sqlite3", "127.0.0.1", 8000, dsn, tenant, user)


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.getenv("TEST_POSTGRES_DSN") or os.getenv("PST_AGENT_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set TEST_POSTGRES_DSN to run PostgreSQL integration tests")
    return dsn


@pytest.fixture
def store(tmp_path: Path, postgres_dsn: str) -> Store:
    store = Store(_settings(tmp_path, postgres_dsn))
    with store.connection() as conn:
        conn.execute("TRUNCATE rag_outbox, chunks, documents, attachments, messages, sources RESTART IDENTITY CASCADE")
    return store


def test_source_upsert_and_tenant_isolation(store: Store) -> None:
    store.upsert_source("work", account_email="a@example.com", account_type="work")
    assert store.get_source("work")["account_email"] == "a@example.com"
    with tenant_context("tenant-b", "user-b"):
        assert store.get_source("work") is None
        store.upsert_source("work", account_email="b@example.com", account_type="work")
        assert store.get_source("work")["account_email"] == "b@example.com"
    assert store.get_source("work")["account_email"] == "a@example.com"


def test_message_attachment_document_and_outbox(store: Store) -> None:
    store.upsert_source("inbox")
    store.insert_message({"id": "msg-1", "source_name": "inbox", "item_type": "email", "subject": "Subject"})
    store.insert_attachment({"id": "att-1", "message_id": "msg-1", "source_name": "inbox", "size_bytes": 3})
    store.insert_document({"id": "doc-1", "source_name": "inbox", "title": "Attachment", "parent_message_id": "msg-1", "parent_attachment_id": "att-1"})
    message = store.get_message("msg-1")
    assert message and message["subject"] == "Subject"
    assert [a["id"] for a in message["attachments"]] == ["att-1"]
    assert [d["id"] for d in message["documents"]] == ["doc-1"]
    with store.connection() as conn:
        events = conn.execute("SELECT event_type, aggregate_id FROM rag_outbox WHERE tenant_id=%s ORDER BY id", ("tenant-a",)).fetchall()
    assert [e["event_type"] for e in events] == ["source_upserted", "message_upserted", "attachment_upserted", "document_upserted"]


def test_chunks_replace_search_and_outbox(store: Store) -> None:
    store.upsert_source("docs")
    store.replace_chunks("docs", "document", "doc-1", [
        {"id": "c1", "ordinal": 0, "start_char": 0, "end_char": 16, "text": "contract renewal"},
        {"id": "c2", "ordinal": 1, "start_char": 16, "end_char": 30, "text": "unrelated text"},
    ])
    assert [r["id"] for r in store.search_chunks("contract renewal")] == ["c1"]
    store.replace_chunks("docs", "document", "doc-1", [{"id": "c3", "ordinal": 0, "start_char": 0, "end_char": 12, "text": "new content"}])
    assert store.search_chunks("contract renewal") == []
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM rag_outbox WHERE event_type='chunks_replaced'").fetchone()["n"] == 2


def test_clear_source_removes_data_and_emits_rebuild_event(store: Store) -> None:
    store.upsert_source("docs")
    store.insert_document({"id": "doc-1", "source_name": "docs", "title": "A"})
    store.replace_chunks("docs", "document", "doc-1", [{"id": "c1", "ordinal": 0, "start_char": 0, "end_char": 5, "text": "hello"}])
    store.clear_source("docs")
    assert store.get_source("docs") is None
    assert store.get_document("doc-1") is None
    with store.connection() as conn:
        row = conn.execute("SELECT event_type FROM rag_outbox WHERE event_type='source_cleared'").fetchone()
    assert row is not None


def test_transaction_rolls_back_domain_and_outbox_on_failure(store: Store) -> None:
    store.upsert_source("docs")
    with pytest.raises(Exception):
        with store.connection() as conn:
            conn.execute("INSERT INTO messages (tenant_id,id,source_name,item_type) VALUES (%s,%s,%s,%s)", ("tenant-a", "bad", "docs", "email"))
            conn.execute("INSERT INTO messages (tenant_id,id,source_name,item_type) VALUES (%s,%s,%s,%s)", ("tenant-a", "bad", "docs", "email"))
    assert store.get_message("bad") is None
    with store.connection() as conn:
        assert conn.execute("SELECT count(*) AS n FROM rag_outbox WHERE aggregate_id='bad'").fetchone()["n"] == 0


def test_message_tenant_isolation(store: Store) -> None:
    store.upsert_source("docs")
    store.insert_message({"id": "msg-a", "source_name": "docs", "item_type": "email"})
    with tenant_context("tenant-b", "user-b"):
        store.upsert_source("docs")
        store.insert_message({"id": "msg-b", "source_name": "docs", "item_type": "email"})
        assert store.get_message("msg-a") is None
        assert store.get_message("msg-b") is not None
    assert store.get_message("msg-a") is not None
    assert store.get_message("msg-b") is None


def test_stats_are_tenant_scoped(store: Store) -> None:
    store.upsert_source("docs")
    store.insert_document({"id": "doc-a", "source_name": "docs", "title": "A"})
    assert store.stats()["documents"] == 1
    with tenant_context("tenant-b", "user-b"):
        store.upsert_source("docs")
        store.insert_document({"id": "doc-b", "source_name": "docs", "title": "B"})
        assert store.stats()["documents"] == 1
    assert store.stats()["documents"] == 1
