from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    temp_dir: Path
    attachments_dir: Path
    db_path: Path
    host: str
    port: int
    postgres_dsn: str
    tenant_id: str
    user_id: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("PST_AGENT_DATA_DIR", "/app/state")).resolve()
        temp_dir = Path(os.getenv("PST_AGENT_TEMP_DIR", str(data_dir / "tmp"))).resolve()
        attachments_dir = Path(os.getenv("PST_AGENT_ATTACHMENTS_DIR", str(data_dir / "attachments"))).resolve()
        db_path = Path(os.getenv("PST_AGENT_DB_PATH", str(data_dir / "index.sqlite3"))).resolve()
        return cls(
            data_dir=data_dir,
            temp_dir=temp_dir,
            attachments_dir=attachments_dir,
            db_path=db_path,
            host=os.getenv("PST_AGENT_HOST", "0.0.0.0"),
            port=int(os.getenv("PST_AGENT_PORT", "8000")),
            postgres_dsn=os.getenv("PST_AGENT_POSTGRES_DSN", ""),
            tenant_id=os.getenv("RAG_TENANT_ID", ""),
            user_id=os.getenv("RAG_USER_ID") or None,
        )
