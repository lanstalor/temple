"""Configuration via environment variables with Pydantic Settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Temple configuration loaded from environment variables."""

    model_config = {"env_prefix": "TEMPLE_"}

    # Server
    host: str = "0.0.0.0"
    port: int = 8100
    log_level: str = "info"

    # Authentication (empty = no auth, for local dev)
    api_key: str = ""

    # ChromaDB
    chroma_mode: Literal["embedded", "http"] = "embedded"
    chroma_host: str = "temple-chromadb"
    chroma_port: int = 8000

    # Embedding
    embedding_model: str = "BAAI/bge-base-en-v1.5"

    # Data directories
    data_dir: Path = Path("./data")
    kuzu_dir: Path = Path("./data/kuzu")
    audit_dir: Path = Path("./data/audit")

    # Session TTL (seconds)
    session_ttl: int = 86400

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Kuzu manages its own directory - only ensure parent exists
        self.kuzu_dir.parent.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)


# Singleton
settings = Settings()
