from __future__ import annotations

import os

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .config import Settings
from .service import AgentService
from .storage import tenant_context


class IngestRequest(BaseModel):
    paths: list[str] = Field(..., min_length=1)
    source_name: str = "default"
    rebuild: bool = False
    account_email: str | None = None
    account_type: str = "other"
    display_name: str | None = None
    description: str | None = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=100)
    source_name: str | None = None


app = FastAPI(title="PST Agent API", version="0.1.0")
service = AgentService(Settings.from_env())


@app.middleware("http")
async def tenant_context_middleware(request: Request, call_next):
    # Header-derived tenant/user context is disabled by default. Enable it only
    # when this service is reachable exclusively through the authenticated gateway.
    if request.url.path == "/healthz" or os.getenv("RAG_TRUST_CONTEXT_HEADERS", "false").lower() != "true":
        return await call_next(request)

    tenant_id = request.headers.get("X-RAG-Tenant-ID")
    user_id = request.headers.get("X-RAG-User-ID")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant context is required")
    with tenant_context(tenant_id, user_id):
        return await call_next(request)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "stats": service.stats()}


@app.get("/stats")
def stats() -> dict:
    return service.stats()


@app.get("/sources")
def list_sources() -> list[dict]:
    return service.list_sources()


@app.get("/sources/{source_name}")
def get_source(source_name: str) -> dict:
    source = service.get_source(source_name)
    if not source:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@app.post("/ingest")
def ingest(request: IngestRequest) -> dict:
    try:
        return service.ingest_paths(
            paths=request.paths,
            source_name=request.source_name,
            rebuild=request.rebuild,
            account_email=request.account_email,
            account_type=request.account_type,
            display_name=request.display_name,
            description=request.description,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/upload")
async def upload(
    file: UploadFile,
    source_name: str = Form(default="default"),
    account_email: str | None = Form(default=None),
    account_type: str = Form(default="other"),
    display_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
) -> dict:
    """Upload an email or document file for ingestion."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")
    try:
        data = await file.read()
        return service.upload_file(
            filename=file.filename,
            data=data,
            source_name=source_name,
            account_email=account_email,
            account_type=account_type,
            display_name=display_name,
            description=description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/search")
def search(request: SearchRequest) -> list[dict]:
    try:
        return service.search(query=request.query, limit=request.limit, source_name=request.source_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/messages/{message_id}")
def get_message(message_id: str) -> dict:
    message = service.get_message(message_id)
    if not message:
        raise HTTPException(status_code=404, detail="message not found")
    return message


@app.get("/documents/{document_id}")
def get_document(document_id: str) -> dict:
    document = service.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="document not found")
    return document


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run("pst_agent.api:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
