# PST Agent

Ninido's PST/document ingestion service with PostgreSQL as the authoritative store and a transactional outbox for downstream indexing.

## Architecture

`ingest -> PostgreSQL + outbox -> rag-indexer -> embeddings/sparse+dense index -> rag-retrieval`

Qdrant is intentionally not written by this service. PostgreSQL is the source of truth and the search index is rebuildable.

## Local development

Requires Docker and Docker Compose.

```bash
docker compose up --build
```

Set `RAG_TENANT_ID` for the deployment's tenant scope. In the shared deployment, the authenticated gateway should be the only component allowed to set request tenant/user context; direct context headers are disabled by default.

## Tests

```bash
uv sync --extra test
TEST_POSTGRES_DSN=postgresql://rag:rag@localhost:5432/rag PST_AGENT_POSTGRES_DSN=postgresql://rag:rag@localhost:5432/rag uv run pytest
```

The suite covers PostgreSQL persistence, transactional outbox creation, tenant isolation, the upstream storage contract, MCP tool names, and configuration.
