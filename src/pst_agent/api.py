from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import Settings
from .service import AgentService


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
