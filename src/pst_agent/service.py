from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .ingest import IngestService
from .storage import Store


class AgentService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.store = Store(self.settings)
        self.ingest_service = IngestService(self.settings)

    def ingest_paths(
        self,
        paths: list[str],
        source_name: str = "default",
        rebuild: bool = False,
        account_email: str | None = None,
        account_type: str = "other",
        display_name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        self.store.upsert_source(
            source_name,
            account_email=account_email,
            account_type=account_type,
            display_name=display_name,
            description=description,
        )
        return self.ingest_service.ingest_paths(paths=paths, source_name=source_name, rebuild=rebuild)

    def search(self, query: str, limit: int = 10, source_name: str | None = None) -> list[dict[str, Any]]:
        rows = self.store.search_chunks(query=query, limit=limit, source_name=source_name)
        results: list[dict[str, Any]] = []
        for row in rows:
            parent_kind = row["parent_kind"]
            parent_id = row["parent_id"]
            parent = self.store.get_message(parent_id) if parent_kind == "message" else self.store.get_document(parent_id)
            results.append(
                {
                    "chunk_id": row["id"],
                    "source_name": row["source_name"],
                    "parent_kind": parent_kind,
                    "parent_id": parent_id,
                    "score": row["score"],
                    "ordinal": row["ordinal"],
                    "text": row["text"],
                    "parent": parent,
                }
            )
        return results

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        return self.store.get_message(message_id)

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return self.store.get_document(document_id)

    def get_source(self, source_name: str) -> dict[str, Any] | None:
        return self.store.get_source(source_name)

    def list_sources(self) -> list[dict[str, Any]]:
        return self.store.list_sources()

    def stats(self) -> dict[str, Any]:
        return self.store.stats()
