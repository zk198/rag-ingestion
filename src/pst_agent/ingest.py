from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

from .config import Settings
from .extractors import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    SUPPORTED_EMAIL_EXTENSIONS,
    extract_text_from_file,
    guess_mime_type,
    parse_eml_file,
    parse_mbox_file,
    parse_msg_file,
    run_readpst,
)
from .storage import Store
from .utils import chunk_text, ensure_dir, iter_files, new_id, safe_filename, sha256_bytes, sha256_file


@dataclass
class IngestSummary:
    source_name: str
    files_seen: int = 0
    pst_files: int = 0
    messages: int = 0
    attachments: int = 0
    documents: int = 0
    chunks: int = 0

    def as_dict(self) -> dict:
        return {
            "source_name": self.source_name,
            "files_seen": self.files_seen,
            "pst_files": self.pst_files,
            "messages": self.messages,
            "attachments": self.attachments,
            "documents": self.documents,
            "chunks": self.chunks,
        }


class IngestService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = Store(settings)
        ensure_dir(settings.attachments_dir)
        ensure_dir(settings.temp_dir)

    def ingest_paths(self, paths: Iterable[str], source_name: str = "default", rebuild: bool = False) -> dict:
        summary = IngestSummary(source_name=source_name)
        if rebuild:
            self.store.clear_source(source_name)

        resolved = [Path(path).expanduser().resolve() for path in paths]
        for path in resolved:
            if not path.exists():
                raise FileNotFoundError(f"Path does not exist: {path}")

        for path in iter_files(resolved):
            summary.files_seen += 1
            suffix = path.suffix.lower()
            if suffix == ".pst":
                self._ingest_pst(path, source_name, summary)
            elif suffix == ".eml":
                self._ingest_message_record(parse_eml_file(path), source_name, path, summary)
            elif suffix == ".msg":
                self._ingest_message_record(parse_msg_file(path), source_name, path, summary)
            elif suffix == ".mbox":
                for item in parse_mbox_file(path):
                    self._ingest_message_record(item, source_name, path, summary)
            elif suffix in SUPPORTED_DOCUMENT_EXTENSIONS:
                self._ingest_document(path, source_name, summary)

        return summary.as_dict()

    def _ingest_pst(self, pst_path: Path, source_name: str, summary: IngestSummary) -> None:
        summary.pst_files += 1
        with TemporaryDirectory(dir=self.settings.temp_dir) as temp_name:
            extraction_root = Path(temp_name) / safe_filename(pst_path.stem)
            run_readpst(pst_path, extraction_root)
            for file_path in iter_files([extraction_root]):
                suffix = file_path.suffix.lower()
                if suffix == ".eml":
                    summary.files_seen += 1
                    self._ingest_message_record(parse_eml_file(file_path), source_name, pst_path, summary)
                elif suffix == ".msg":
                    summary.files_seen += 1
                    self._ingest_message_record(parse_msg_file(file_path), source_name, pst_path, summary)
                elif suffix in SUPPORTED_DOCUMENT_EXTENSIONS:
                    summary.files_seen += 1
                    self._ingest_document(file_path, source_name, summary, logical_source=str(pst_path))

    def _ingest_message_record(self, raw: dict, source_name: str, source_path: Path, summary: IngestSummary) -> None:
        message_id = new_id("msg")
        source_path_str = str(source_path)
        message = {
            "id": message_id,
            "source_name": source_name,
            "source_path": source_path_str,
            "item_type": "email",
            "folder": raw.get("folder") or "",
            "subject": raw.get("subject") or "",
            "sender": raw.get("sender") or "",
            "recipients": raw.get("recipients") or "",
            "cc": raw.get("cc") or "",
            "bcc": raw.get("bcc") or "",
            "sent_at": raw.get("sent_at") or "",
            "body_text": raw.get("body_text") or "",
            "body_html": raw.get("body_html") or "",
            "raw_path": raw.get("raw_path") or source_path_str,
            "sha256": sha256_file(Path(raw["raw_path"])) if raw.get("raw_path") and Path(raw["raw_path"]).exists() else None,
        }
        self.store.insert_message(message)
        summary.messages += 1

        body_chunks = []
        for chunk in chunk_text(message["body_text"]):
            chunk["id"] = new_id("chunk")
            body_chunks.append(chunk)
        self.store.replace_chunks(source_name, "message", message_id, body_chunks)
        summary.chunks += len(body_chunks)

        attachment_root = self.settings.attachments_dir / message_id
        ensure_dir(attachment_root)

        for item in raw.get("attachments", []):
            self._ingest_attachment(
                message_id=message_id,
                attachment=item,
                source_name=source_name,
                source_path=source_path_str,
                attachment_root=attachment_root,
                summary=summary,
            )

    def _ingest_attachment(
        self,
        *,
        message_id: str,
        attachment: dict,
        source_name: str,
        source_path: str,
        attachment_root: Path,
        summary: IngestSummary,
    ) -> None:
        attachment_id = new_id("att")
        filename = safe_filename(attachment.get("filename"), fallback=attachment_id)
        payload = attachment.get("data", b"") or b""
        if not isinstance(payload, (bytes, bytearray)):
            payload = bytes(payload)
        saved_path = attachment_root / f"{attachment_id}_{filename}"
        saved_path.write_bytes(payload)

        extracted_text = ""
        try:
            extracted_text = extract_text_from_file(saved_path)
        except Exception:
            extracted_text = ""

        media_type = attachment.get("content_type") or guess_mime_type(saved_path)
        sha = sha256_bytes(bytes(payload))

        self.store.insert_attachment(
            {
                "id": attachment_id,
                "message_id": message_id,
                "source_name": source_name,
                "original_name": filename,
                "saved_path": str(saved_path),
                "media_type": media_type,
                "size_bytes": len(payload),
                "sha256": sha,
                "extracted_text": extracted_text,
            }
        )
        summary.attachments += 1

        document_id = new_id("doc")
        self.store.insert_document(
            {
                "id": document_id,
                "source_name": source_name,
                "source_path": source_path,
                "title": filename,
                "media_type": media_type,
                "sha256": sha,
                "extracted_text": extracted_text,
                "raw_path": str(saved_path),
                "parent_message_id": message_id,
                "parent_attachment_id": attachment_id,
            }
        )
        summary.documents += 1

        chunks = []
        for chunk in chunk_text(extracted_text):
            chunk["id"] = new_id("chunk")
            chunks.append(chunk)
        self.store.replace_chunks(source_name, "document", document_id, chunks)
        summary.chunks += len(chunks)

    def _ingest_document(
        self,
        path: Path,
        source_name: str,
        summary: IngestSummary,
        logical_source: str | None = None,
    ) -> None:
        extracted_text = extract_text_from_file(path)
        document_id = new_id("doc")
        media_type = guess_mime_type(path)
        raw_copy_dir = self.settings.attachments_dir / "standalone"
        ensure_dir(raw_copy_dir)
        copied_path = raw_copy_dir / f"{document_id}_{safe_filename(path.name)}"
        if path.resolve() != copied_path.resolve():
            shutil.copy2(path, copied_path)
        sha = sha256_file(path)
        self.store.insert_document(
            {
                "id": document_id,
                "source_name": source_name,
                "source_path": logical_source or str(path),
                "title": path.name,
                "media_type": media_type,
                "sha256": sha,
                "extracted_text": extracted_text,
                "raw_path": str(copied_path),
                "parent_message_id": None,
                "parent_attachment_id": None,
            }
        )
        summary.documents += 1

        chunks = []
        for chunk in chunk_text(extracted_text):
            chunk["id"] = new_id("chunk")
            chunks.append(chunk)
        self.store.replace_chunks(source_name, "document", document_id, chunks)
        summary.chunks += len(chunks)


__all__ = ["IngestService"]
