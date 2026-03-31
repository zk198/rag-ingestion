from __future__ import annotations

from fastmcp import FastMCP

from .config import Settings
from .service import AgentService


service = AgentService(Settings.from_env())
mcp = FastMCP("PST Agent MCP")


@mcp.tool
def ingest_paths(
    paths: list[str],
    source_name: str = "default",
    rebuild: bool = False,
    account_email: str | None = None,
    account_type: str = "other",
    display_name: str | None = None,
    description: str | None = None,
) -> dict:
    """Ingest one or more files or directories from local disk into the search index."""
    return service.ingest_paths(
        paths=paths,
        source_name=source_name,
        rebuild=rebuild,
        account_email=account_email,
        account_type=account_type,
        display_name=display_name,
        description=description,
    )


@mcp.tool
def search(query: str, limit: int = 10, source_name: str | None = None) -> list[dict]:
    """Search across indexed message bodies and extracted attachment/document text."""
    return service.search(query=query, limit=limit, source_name=source_name)


@mcp.tool
def get_message(message_id: str) -> dict:
    """Fetch a full message record including attachments and linked document records."""
    message = service.get_message(message_id)
    if not message:
        raise ValueError(f"message not found: {message_id}")
    return message


@mcp.tool
def get_document(document_id: str) -> dict:
    """Fetch a full document record, including extracted text."""
    document = service.get_document(document_id)
    if not document:
        raise ValueError(f"document not found: {document_id}")
    return document


@mcp.tool
def list_sources() -> list[dict]:
    """List indexed sources and their counts."""
    return service.list_sources()


@mcp.tool
def stats() -> dict:
    """Return top-level index statistics."""
    return service.stats()


if __name__ == "__main__":
    mcp.run()
