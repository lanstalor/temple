"""ChromaDB vector store - dual mode (embedded for dev, HTTP for Docker)."""

from __future__ import annotations

import logging
from typing import Any

import chromadb

logger = logging.getLogger(__name__)


class VectorStore:
    """ChromaDB-backed vector store with dual-mode support."""

    def __init__(
        self,
        mode: str = "embedded",
        host: str = "localhost",
        port: int = 8000,
        persist_dir: str = "./data/chromadb",
    ) -> None:
        if mode == "http":
            logger.info(f"Connecting to ChromaDB at {host}:{port}")
            self._client = chromadb.HttpClient(host=host, port=port)
        else:
            logger.info(f"Using embedded ChromaDB at {persist_dir}")
            self._client = chromadb.PersistentClient(path=persist_dir)

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        """Get or create a ChromaDB collection."""
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def add(
        self,
        collection_name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add documents with embeddings to a collection."""
        col = self.get_or_create_collection(collection_name)
        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(
        self,
        collection_name: str,
        query_embedding: list[float],
        n_results: int = 10,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query a collection by embedding similarity."""
        col = self.get_or_create_collection(collection_name)
        kwargs: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, col.count()) if col.count() > 0 else n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        if col.count() == 0:
            return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
        return col.query(**kwargs)

    def get(
        self,
        collection_name: str,
        ids: list[str],
    ) -> dict[str, Any]:
        """Get documents by ID."""
        col = self.get_or_create_collection(collection_name)
        return col.get(ids=ids, include=["documents", "metadatas"])

    def get_all(
        self,
        collection_name: str,
        limit: int = 100,
        offset: int = 0,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get documents in a collection with pagination."""
        col = self.get_or_create_collection(collection_name)
        kwargs: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "include": ["documents", "metadatas"],
        }
        if where:
            kwargs["where"] = where
        return col.get(**kwargs)

    def delete(
        self,
        collection_name: str,
        ids: list[str],
    ) -> None:
        """Delete documents by ID."""
        col = self.get_or_create_collection(collection_name)
        col.delete(ids=ids)

    def count(self, collection_name: str) -> int:
        """Count documents in a collection."""
        col = self.get_or_create_collection(collection_name)
        return col.count()

    def list_collections(self) -> list[str]:
        """List all collection names."""
        return [c.name for c in self._client.list_collections()]

    def delete_collection(self, name: str) -> None:
        """Delete an entire collection."""
        try:
            self._client.delete_collection(name)
        except Exception:
            pass  # Collection may not exist

    def heartbeat(self) -> bool:
        """Check if ChromaDB is responsive."""
        try:
            self._client.heartbeat()
            return True
        except Exception:
            return False
