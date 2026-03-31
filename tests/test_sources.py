import os
import tempfile

from pst_agent.config import Settings
from pst_agent.storage import Store


def _tmp_settings(tmp_path: str) -> Settings:
    os.environ["PST_AGENT_DATA_DIR"] = tmp_path
    os.environ["PST_AGENT_DB_PATH"] = os.path.join(tmp_path, "index.sqlite3")
    os.environ["PST_AGENT_TEMP_DIR"] = os.path.join(tmp_path, "tmp")
    os.environ["PST_AGENT_ATTACHMENTS_DIR"] = os.path.join(tmp_path, "attachments")
    return Settings.from_env()


def test_upsert_source_creates_and_updates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(_tmp_settings(tmp))

        store.upsert_source(
            "work_inbox",
            account_email="alice@corp.com",
            account_type="work",
            display_name="Alice Work",
            description="Corporate mailbox",
        )
        source = store.get_source("work_inbox")
        assert source is not None
        assert source["account_email"] == "alice@corp.com"
        assert source["account_type"] == "work"
        assert source["display_name"] == "Alice Work"
        assert source["description"] == "Corporate mailbox"

        store.upsert_source(
            "work_inbox",
            account_type="work",
            description="Updated corporate mailbox",
        )
        source = store.get_source("work_inbox")
        assert source is not None
        assert source["account_email"] == "alice@corp.com"
        assert source["description"] == "Updated corporate mailbox"


def test_list_sources_includes_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(_tmp_settings(tmp))

        store.upsert_source("private", account_email="bob@gmail.com", account_type="private")
        store.upsert_source("work", account_email="bob@corp.com", account_type="work")

        sources = store.list_sources()
        names = [s["source_name"] for s in sources]
        assert "private" in names
        assert "work" in names

        private = next(s for s in sources if s["source_name"] == "private")
        assert private["account_email"] == "bob@gmail.com"
        assert private["account_type"] == "private"


def test_get_source_returns_none_for_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(_tmp_settings(tmp))
        assert store.get_source("nonexistent") is None
