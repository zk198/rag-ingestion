# PST Agent — Project Guidelines

## Overview

Single-container Python backend that ingests PST archives, email files, and documents, indexes content in SQLite FTS5, and exposes it via REST API and MCP stdio server.

## Architecture

- **Source layout**: all application code lives under `src/pst_agent/`
- **Entry points**: REST API (`api.py`), CLI (`cli.py`), MCP server (`mcp_server.py`)
- **Storage**: SQLite with WAL mode, FTS5 for search — no external database
- **Config**: environment variables prefixed `PST_AGENT_` parsed in `config.py`
- **Ingest pipeline**: `ingest.py` → `extractors.py` → `storage.py`
- **Docker**: single-stage `python:3.12-slim` image, entry via `scripts/run-container.sh`

## Code Style

- Python 3.11+, use `from __future__ import annotations`
- Type hints on all function signatures
- Pydantic v2 models for API request/response validation
- Keep modules focused — one concern per file
- No classes where a plain function suffices

## Build and Test

```bash
# Build
docker build -t pst-agent .

# Run tests (mount tests dir into the container)
docker run --rm -v ./tests:/app/tests pst-agent bash -c "pip install pytest -q && python -m pytest /app/tests/ -v"

# Start API
docker run --rm -p 8000:8000 -v ./example-data:/data/inbox:ro pst-agent api

# Health check
curl http://localhost:8000/healthz
```

## Conventions

- Source grouping uses `source_name` with account metadata (`account_email`, `account_type`, `display_name`, `description`) in the `sources` table
- All IDs use the format `{prefix}_{uuid_hex}` (e.g., `msg_abc123`, `doc_def456`, `chunk_789ghi`)
- Text extraction goes through `clean_text()` before storage
- Chunking uses 1400-char windows with 200-char overlap
- File uploads land in `/app/state/uploads/{source_name}/`
- Never import from tests in production code
