from __future__ import annotations

import os
from pathlib import Path

import pytest

from pst_agent.config import Settings
from pst_agent.storage import Store, tenant_context


def _settings(tmp_path: Path, dsn: str) -> Settings:
    return Settings(tmp_path, tmp_path / "tmp", tmp_path / "attachments", tmp_path / "unused.sqlite3", "127.0.0.1", 8000, dsn, "tenant-a", "user-a")


@pytest.fixture
def postgres_dsn() -> str:
    dsn = os.getenv("TEST_POSTGRES_DSN") or os.getenv("PST_AGENT_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set TEST_POSTGRES_DSN to run PostgreSQL integration tests")
    return dsn


@pytest.fixture
def store(tmp_path: Path, postgres_dsn: str) -> Store:
    store = Store(_settings(tmp_path, postgres_dsn))
    return store


def test_source_upsert_and_tenant_isolation(store: Store) -> None:
    store.upsert_source("work", account_email="a@example.com", account_type="work")
    assert store.get_source("work")["account_email"] == "a@example.com"
    with tenant_context("tenant-b", "user-b"):
        assert store.get_source("work") is None
        store.upsert_source("work", account_email="b@example.com", account_type="work")
        assert store.get_source("work")["account_email"] == "b@example.com"
    assert store.get_source("work")["account_email"] == "a@example.com"


def test_message_and_outbox_are_atomic(store: Store) -> None:
    store.upsert_source("inbox")
    store.insert_message({"id": "msg-1", "source_name": "inbox", "item_type": "email", "subject": "Subject", "body_text": "Body"})
    message = store.get_message("msg-1")
    assert message and message["subject"] == "Subject"
    with store.connection() as conn:
        rows = conn.execute("SELECT event_type, aggregate_id FROM rag_outbox WHERE tenant_id = %s", ("tenant-a",)).fetchall()
    assert any(r["event_type"] == "message_upserted" and r["aggregate_id"] == "msg-1" for r in rows)


def test_chunks_replace_and_search(store: Store) -> None:
    store.upsert_source("docs")
    store.replace_chunks("docs", "document", "doc-1", [
        {"id": "c1", "ordinal": 0, "start_char": 0, "end_char": 16, "text": "contract renewal"},
        {"id": "c2", "ordinal": 1, "start_char": 16, "end_char": 30, "text": "unrelated text"},
    ])
    assert [r["id"] for r in store.search_chunks("contract renewal")] == ["c1"]
    store.replace_chunks("docs", "document", "doc-1", [{"id": "c3", "ordinal": 0, "start_char": 0, "end_char": 12, "text": "new content"}])
    assert store.search_chunks("contract renewal") == []


def test_stats_are_tenant_scoped(store: Store) -> None:
    store.upsert_source("docs")
    store.insert_document({"id": "doc-a", "source_name": "docs", "title": "A"})
    assert store.stats()["documents"] == 1
    with tenant_context("tenant-b", "user-b"):
        store.upsert_source("docs")
        store.insert_document({"id": "doc-b", "source_name": "docs", "title": "B"})
        assert store.stats()["documents"] == 1
    assert store.stats()["documents"] == 1
