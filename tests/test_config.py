from pst_agent.config import Settings


def test_settings_reads_postgres_and_tenant(monkeypatch):
    monkeypatch.setenv("PST_AGENT_POSTGRES_DSN", "postgresql://u:p@db/rag")
    monkeypatch.setenv("RAG_TENANT_ID", "tenant-x")
    monkeypatch.setenv("RAG_USER_ID", "user-x")
    settings = Settings.from_env()
    assert settings.postgres_dsn == "postgresql://u:p@db/rag"
    assert settings.tenant_id == "tenant-x"
    assert settings.user_id == "user-x"
