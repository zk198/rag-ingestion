# PST Agent

A single Dockerized backend that reads PST archives and related files from disk, extracts text from emails and attachments, indexes the content locally, and exposes it to agents in two ways:

- **REST API** for ingestion and retrieval
- **MCP server** over stdio for agent/tool integrations

It is designed for the exact workflow you described: mount one or more files or folders into the container, ingest them, and let an agent search and fetch the normalized content.

## What this repository does

- Reads **`.pst`** files with `readpst`
- Reads **`.eml`**, **`.msg`**, and **`.mbox`** email files
- Extracts text from common attachment and loose file types:
  - PDF
  - DOCX
  - XLSX / XLSM
  - CSV / TXT / MD / JSON / XML / HTML
  - PNG / JPG / TIFF / BMP via OCR
  - ZIP archives recursively
- Stores normalized records in **SQLite**
- Builds a local **SQLite FTS5 BM25** search index for RAG-style retrieval
- Exposes searchable tools over **REST** and **MCP**

## Why this design

This repo intentionally keeps the moving parts simple:

- **No external database required**
- **No cloud dependency required**
- **No custom PST parser**; it relies on existing mature tooling
- **No embeddings required** to get useful retrieval; SQLite FTS5 is enough for many mailbox review and discovery tasks

That makes it easier to run in a single container and easier to wire into an agent.

## Architecture

```text
mounted files/folders
        |
        v
  IngestService
    |- PST -> readpst -> .eml files
    |- .eml/.msg/.mbox parser
    |- attachment extraction
    |- document text extraction
    |- OCR for images
        |
        v
   SQLite storage
    |- messages
    |- attachments
    |- documents
    |- chunks
    |- chunks_fts (FTS5)
        |
        +--> REST API
        |
        +--> MCP tools (stdio)
```

## Repo layout

```text
.
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── scripts/
│   └── run-container.sh
├── src/pst_agent/
│   ├── api.py
│   ├── cli.py
│   ├── config.py
│   ├── extractors.py
│   ├── ingest.py
│   ├── mcp_server.py
│   ├── service.py
│   ├── storage.py
│   └── utils.py
├── examples/
│   ├── http_client.py
│   └── mcp-server-config.json
└── tests/
    └── test_utils.py
```

## Build

```bash
docker build -t pst-agent .
```

## Run as REST API

Mount your source files into `/data/inbox` and persist index state in `/app/state`.

```bash
docker run --rm \
  -p 8000:8000 \
  -v /absolute/path/to/mail:/data/inbox:ro \
  -v pst-agent-state:/app/state \
  pst-agent
```

The default command is `api`, so the container starts the REST API on port `8000`.

### Health check

```bash
curl http://localhost:8000/healthz
```

### Ingest files

```bash
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "paths": ["/data/inbox"],
    "source_name": "case_a",
    "rebuild": true
  }'
```

### Search

```bash
curl -X POST http://localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "master service agreement amendment",
    "limit": 5,
    "source_name": "case_a"
  }'
```

### Fetch a message

```bash
curl http://localhost:8000/messages/msg_123
```

### Fetch a document or attachment text record

```bash
curl http://localhost:8000/documents/doc_123
```

## Run as a CLI inside the same container

This is handy for batch ingestion or cron jobs.

```bash
docker run --rm \
  -v /absolute/path/to/mail:/data/inbox:ro \
  -v pst-agent-state:/app/state \
  pst-agent cli ingest /data/inbox --source-name case_a --rebuild
```

Search with the CLI:

```bash
docker run --rm \
  -v pst-agent-state:/app/state \
  pst-agent cli search "invoice approval" --source-name case_a --limit 10
```

## Run as an MCP server

The MCP mode uses **stdio**, which is a common way for agents to launch a tool server locally.

```bash
docker run --rm -i \
  -v /absolute/path/to/mail:/data/inbox:ro \
  -v pst-agent-state:/app/state \
  pst-agent mcp
```

Available MCP tools:

- `ingest_paths(paths, source_name="default", rebuild=False)`
- `search(query, limit=10, source_name=None)`
- `get_message(message_id)`
- `get_document(document_id)`
- `list_sources()`
- `stats()`

Example config snippet is included in `examples/mcp-server-config.json`.

## REST API surface

### `POST /ingest`

Request:

```json
{
  "paths": ["/data/inbox"],
  "source_name": "case_a",
  "rebuild": true
}
```

### `POST /search`

Request:

```json
{
  "query": "board approval budget",
  "limit": 10,
  "source_name": "case_a"
}
```

### `GET /messages/{message_id}`

Returns the normalized message, linked attachments, and linked document records.

### `GET /documents/{document_id}`

Returns the normalized document record and extracted text.

### `GET /sources`

Lists indexed sources with counts.

### `GET /stats`

Returns global index counts.

## Data model

### Message

A message record stores:

- subject
- sender / recipients / cc / bcc
- sent date string
- normalized text body
- HTML body if available
- source path
- linked attachments

### Attachment

Each attachment stores:

- original name
- saved blob path
- media type
- hash
- extracted text, if available

### Document

A document record is used for:

- standalone loose files
- extracted attachment text records

### Chunk

Every message body and extracted document text is chunked into overlapping text segments and indexed in SQLite FTS5 for retrieval.

## Supported input patterns

You can point ingestion at:

- a single PST file
- a directory containing multiple PST files
- a folder of loose emails
- a mixed directory of PST + PDF + DOCX + XLSX + images

Examples:

```bash
/data/inbox/archive.pst
/data/inbox/legal_mail/
/data/inbox/
```

## Operational notes

- PST files are converted with `readpst` into `.eml` files during ingestion.
- OCR runs only for image-like inputs.
- Extracted attachment files are saved under `/app/state/attachments`.
- Search uses SQLite FTS5 prefix queries and BM25 ranking.
- Rebuilding a source removes previous indexed rows for that source and re-ingests from scratch.

## Limitations

- Password-protected attachments are not decrypted.
- Scanned PDFs are only partially supported unless they contain extractable text or are converted to images externally.
- Very unusual proprietary file formats may produce empty extracted text.
- This repo focuses on retrieval and normalization, not legal hold workflows or chain-of-custody features.

## Good next extensions

If you want to take this further, the easiest upgrades are:

- add optional embeddings and vector search
- add OCR for scanned PDFs page-by-page
- add entity extraction and redaction pipeline
- add auth around the REST API
- add OpenAPI-generated tool wrappers for agents that prefer HTTP over MCP
- stream ingestion progress for very large mailboxes

## Suggested agent workflows

### RAG-style workflow

1. Call `/ingest` once for a source.
2. Use `/search` to retrieve top chunks.
3. Use `/messages/{id}` or `/documents/{id}` for full context.
4. Summarize, answer, or cite based on those records.

### MCP-style workflow

1. Call `ingest_paths(...)` once.
2. Call `search(...)` with task-specific queries.
3. Call `get_message(...)` or `get_document(...)` to ground the final answer.

## Development

Run locally without Docker if you want:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
python -m pst_agent.api
```

CLI example:

```bash
pst-agent ingest /absolute/path/to/mail --source-name demo --rebuild
pst-agent search "termination clause" --source-name demo
```

## License

MIT
