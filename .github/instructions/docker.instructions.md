---
description: "Use when modifying Dockerfile, docker-compose.yml, or container configuration. Covers image build, runtime layout, and environment variables."
applyTo: "Dockerfile, docker-compose.yml"
---

# Docker Conventions

- Base image: `python:3.12-slim`
- Single-stage build — keep it simple
- System deps installed via `apt-get` in one `RUN` layer (build-essential, pst-utils, tesseract-ocr)
- Python deps installed from `requirements.txt`, then `pip install -e .`
- Entrypoint: `scripts/run-container.sh` with mode as first arg (`api`, `mcp`, `cli`, `bash`)
- Container paths:
  - `/app/state/` — persistent data, SQLite DB, uploads
  - `/data/inbox/` — mounted read-only source files
- All config via `PST_AGENT_*` environment variables (see `config.py`)
- `EXPOSE 8000` for the REST API
- Do not add test dependencies to the production image
