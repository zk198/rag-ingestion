from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path
from typing import Iterable, Iterator, List


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\x00", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_filename(name: str | None, fallback: str = "file") -> str:
    value = (name or fallback).strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value[:240] or fallback


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def chunk_text(text: str, size: int = 1400, overlap: int = 200) -> List[dict]:
    text = clean_text(text)
    if not text:
        return []
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks: List[dict] = []
    start = 0
    ordinal = 0
    while start < len(text):
        end = min(len(text), start + size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(
                {
                    "ordinal": ordinal,
                    "text": chunk,
                    "start_char": start,
                    "end_char": end,
                }
            )
            ordinal += 1
        if end == len(text):
            break
        start = max(0, end - overlap)
    return chunks




def to_fts_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", query.lower())
    if not tokens:
        return '""'
    return " ".join(f'{token}*' for token in tokens)

def iter_files(paths: Iterable[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    yield child
        elif path.is_file():
            yield path
