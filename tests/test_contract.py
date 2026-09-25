from __future__ import annotations

import inspect

from pst_agent.ingest import IngestService
from pst_agent.mcp_server import mcp, service


def test_mcp_tool_names_preserved() -> None:
    names = {tool.name for tool in mcp._tool_manager.list_tools()}
    assert {"ingest_paths", "search", "get_message", "get_document", "list_sources", "stats"} <= names


def test_service_store_contract_preserved() -> None:
    expected = {"upsert_source", "get_source", "clear_source", "insert_message", "insert_attachment", "insert_document", "replace_chunks", "search_chunks", "get_message", "get_document", "list_sources", "stats"}
    assert expected <= set(dir(service.store))


def test_ingest_public_signature_unchanged() -> None:
    assert list(inspect.signature(IngestService.ingest_paths).parameters) == ["self", "paths", "source_name", "rebuild"]
