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
    runtime_mode: Literal["mcp", "rest", "combined"] = "combined"
    mcp_transport: Literal["streamable-http", "stdio"] = "streamable-http"

    # Authentication (empty = no auth, for local dev)
    api_key: str = ""

    # Base URL for OAuth metadata endpoints (e.g. https://temple.tython.ca)
    base_url: str = ""

    # OAuth 2.1 pre-registered client (empty = dynamic registration allowed)
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    # Comma-separated OAuth redirect URIs for pre-registered client mode
    oauth_redirect_uris: str = ""

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

    # LLM-assisted extraction (empty key = heuristics only)
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.0

    # Atlas UI authentication (empty = no auth)
    atlas_user: str = ""
    atlas_pass: str = ""

    # Session TTL (seconds)
    session_ttl: int = 86400

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Kuzu manages its own directory - only ensure parent exists
        self.kuzu_dir.parent.mkdir(parents=True, exist_ok=True)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    @property
    def oauth_redirect_uri_list(self) -> list[str]:
        """Parsed list of pre-registered OAuth redirect URIs."""
        return [uri.strip() for uri in self.oauth_redirect_uris.split(",") if uri.strip()]


# Singleton
settings = Settings()
