"""Central memory broker - orchestrates all subsystems."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from temple.config import Settings
from temple.memory.audit_log import AuditLog
from temple.memory.context import ContextManager
from temple.memory.embedder import embed_text, embed_batch
from temple.memory.graph_store import GraphStore
from temple.memory.hashing import content_hash
from temple.memory.vector_store import VectorStore
from temple.models.context import ContextScope, ContextTier
from temple.models.memory import MemoryEntry, MemorySearchResult

logger = logging.getLogger(__name__)


class MemoryBroker:
    """Central orchestrator coordinating vector store, graph store, and context."""

    def __init__(self, settings: Settings) -> None:
        settings.ensure_dirs()
        self._settings = settings

        self._vector_store = VectorStore(
            mode=settings.chroma_mode,
            host=settings.chroma_host,
            port=settings.chroma_port,
            persist_dir=str(settings.data_dir / "chromadb"),
        )
        self._graph_store = GraphStore(settings.kuzu_dir)
        self._audit = AuditLog(settings.audit_dir)
        self._context = ContextManager()

    @property
    def context(self) -> ContextManager:
        return self._context

    @property
    def graph(self) -> GraphStore:
        return self._graph_store

    @property
    def vector(self) -> VectorStore:
        return self._vector_store

    # ── Memory Operations ────────────────────────────────────────────

    def store_memory(
        self,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        scope: str | None = None,
    ) -> MemoryEntry:
        """Store a memory with embedding in the appropriate scope."""
        c_hash = content_hash(content)
        store_scope = self._context.get_store_scope(scope)
        collection = store_scope.collection_name

        # Check for duplicate
        existing = self._check_duplicate(collection, c_hash)
        if existing:
            logger.info(f"Duplicate memory detected: {c_hash[:12]}")
            self._audit.log("store_duplicate", store_scope.scope_key, {"hash": c_hash[:12]})
            return existing

        # Generate embedding
        embedding = embed_text(content, self._settings.embedding_model)

        now = datetime.now(timezone.utc).isoformat()
        entry = MemoryEntry(
            id=c_hash,
            content=content,
            content_hash=c_hash,
            tags=tags or [],
            metadata=metadata or {},
            scope=store_scope.scope_key,
            created_at=now,
            updated_at=now,
        )

        # Store in vector DB
        meta = {
            "content_hash": c_hash,
            "scope": store_scope.scope_key,
            "created_at": now,
            "tags": json.dumps(entry.tags),
        }
        self._vector_store.add(
            collection_name=collection,
            ids=[c_hash],
            embeddings=[embedding],
            documents=[content],
            metadatas=[meta],
        )

        self._audit.log("store", store_scope.scope_key, {
            "hash": c_hash[:12],
            "tags": entry.tags,
            "content_preview": content[:100],
        })

        logger.info(f"Stored memory {c_hash[:12]} in {collection}")
        return entry

    def retrieve_memory(
        self,
        query: str,
        n_results: int = 5,
        scope: str | None = None,
    ) -> list[MemorySearchResult]:
        """Retrieve memories by semantic similarity across active scopes."""
        query_embedding = embed_text(query, self._settings.embedding_model)

        if scope:
            scopes = [self._context._parse_scope(scope)]
        else:
            scopes = self._context.get_retrieval_scopes()

        all_results: list[MemorySearchResult] = []

        for ctx_scope in scopes:
            collection = ctx_scope.collection_name
            try:
                results = self._vector_store.query(
                    collection_name=collection,
                    query_embedding=query_embedding,
                    n_results=n_results,
                )
            except Exception as e:
                logger.debug(f"Query failed for {collection}: {e}")
                continue

            ids = results.get("ids", [[]])[0]
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for i, doc_id in enumerate(ids):
                # ChromaDB returns distances (lower = more similar for cosine)
                # Convert to similarity score (1 - distance)
                score = 1.0 - distances[i] if distances[i] is not None else 0.0
                meta = metas[i] if metas else {}
                tags = json.loads(meta.get("tags", "[]")) if meta.get("tags") else []

                entry = MemoryEntry(
                    id=doc_id,
                    content=docs[i],
                    content_hash=meta.get("content_hash", doc_id),
                    tags=tags,
                    scope=meta.get("scope", ctx_scope.scope_key),
                    created_at=meta.get("created_at", ""),
                )

                all_results.append(MemorySearchResult(
                    memory=entry,
                    score=score,
                    tier=ctx_scope.tier.value,
                ))

        # Sort by tier precedence (session > project > global), then by score
        all_results.sort(
            key=lambda r: (
                self._context.scope_precedence(
                    self._context._parse_scope(r.memory.scope)
                ),
                r.score,
            ),
            reverse=True,
        )

        self._audit.log("retrieve", "global", {
            "query_preview": query[:100],
            "results_count": len(all_results),
        })

        return all_results[:n_results]

    def delete_memory(self, memory_id: str, scope: str | None = None) -> bool:
        """Delete a memory by ID from the specified or current scope."""
        if scope:
            scopes = [self._context._parse_scope(scope)]
        else:
            scopes = self._context.get_retrieval_scopes()

        deleted = False
        for ctx_scope in scopes:
            collection = ctx_scope.collection_name
            try:
                self._vector_store.delete(collection_name=collection, ids=[memory_id])
                deleted = True
                self._audit.log("delete", ctx_scope.scope_key, {"id": memory_id[:12]})
            except Exception as e:
                logger.debug(f"Delete failed for {collection}: {e}")

        return deleted

    def search_memories(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        n_results: int = 10,
    ) -> list[MemorySearchResult]:
        """Search memories by text query and/or tags."""
        if query:
            results = self.retrieve_memory(query, n_results=n_results, scope=scope)
            if tags:
                results = [
                    r for r in results
                    if any(t in r.memory.tags for t in tags)
                ]
            return results
        return []

    # ── Entity Operations (Graph) ────────────────────────────────────

    def create_entities(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create multiple entities in the knowledge graph."""
        results = []
        scope = self._context.get_store_scope().scope_key
        for e in entities:
            created = self._graph_store.create_entity(
                name=e["name"],
                entity_type=e.get("entity_type", "unknown"),
                observations=e.get("observations", []),
                scope=scope,
            )
            results.append({"name": e["name"], "created": created})
            if created:
                self._audit.log("create_entity", scope, {"name": e["name"]})
        return results

    def get_entity(self, name: str) -> dict[str, Any] | None:
        """Get an entity by name."""
        return self._graph_store.get_entity(name)

    def update_entity(self, name: str, **updates: Any) -> bool:
        """Update an entity."""
        result = self._graph_store.update_entity(name, **updates)
        if result:
            self._audit.log("update_entity", "global", {"name": name})
        return result

    def delete_entities(self, names: list[str]) -> list[dict[str, Any]]:
        """Delete multiple entities."""
        results = []
        for name in names:
            deleted = self._graph_store.delete_entity(name)
            results.append({"name": name, "deleted": deleted})
            if deleted:
                self._audit.log("delete_entity", "global", {"name": name})
        return results

    def search_entities(
        self,
        entity_type: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search entities by type/scope."""
        return self._graph_store.search_entities(
            entity_type=entity_type,
            scope=scope,
            limit=limit,
        )

    # ── Relation Operations (Graph) ──────────────────────────────────

    def create_relations(self, relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create multiple relations."""
        results = []
        scope = self._context.get_store_scope().scope_key
        for r in relations:
            created = self._graph_store.create_relation(
                source=r["source"],
                target=r["target"],
                relation_type=r["relation_type"],
                scope=scope,
            )
            results.append({
                "source": r["source"],
                "target": r["target"],
                "relation_type": r["relation_type"],
                "created": created,
            })
            if created:
                self._audit.log("create_relation", scope, {
                    "source": r["source"],
                    "target": r["target"],
                    "type": r["relation_type"],
                })
        return results

    def delete_relations(self, relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Delete multiple relations."""
        results = []
        for r in relations:
            deleted = self._graph_store.delete_relation(
                source=r["source"],
                target=r["target"],
                relation_type=r["relation_type"],
            )
            results.append({**r, "deleted": deleted})
        return results

    def get_relations(self, entity_name: str, direction: str = "both") -> list[dict[str, Any]]:
        """Get relations for an entity."""
        return self._graph_store.get_relations(entity_name, direction)

    def find_path(self, source: str, target: str, max_hops: int = 5) -> Any:
        """Find shortest path between entities."""
        return self._graph_store.find_path(source, target, max_hops)

    # ── Observation Operations ───────────────────────────────────────

    def add_observations(self, entity_name: str, observations: list[str]) -> bool:
        """Add observations to an entity."""
        result = self._graph_store.add_observations(entity_name, observations)
        if result:
            self._audit.log("add_observations", "global", {
                "entity": entity_name,
                "count": len(observations),
            })
        return result

    def remove_observations(self, entity_name: str, observations: list[str]) -> bool:
        """Remove observations from an entity."""
        result = self._graph_store.remove_observations(entity_name, observations)
        if result:
            self._audit.log("remove_observations", "global", {
                "entity": entity_name,
                "count": len(observations),
            })
        return result

    # ── Context Operations ───────────────────────────────────────────

    def set_context(
        self,
        project: str | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        """Set the active context."""
        if project is not None:
            self._context.set_project(project if project else None)
        if session is not None:
            self._context.set_session(session if session else None)

        return {
            "project": self._context.context.project,
            "session": self._context.context.session,
            "active_scopes": [s.scope_key for s in self._context.get_active_scopes()],
        }

    def get_context(self) -> dict[str, Any]:
        """Get current context info."""
        return {
            "project": self._context.context.project,
            "session": self._context.context.session,
            "active_scopes": [s.scope_key for s in self._context.get_active_scopes()],
        }

    def list_projects(self) -> list[str]:
        """List all project collections."""
        collections = self._vector_store.list_collections()
        return [
            c.replace("temple_project_", "")
            for c in collections
            if c.startswith("temple_project_")
        ]

    def list_sessions(self) -> list[str]:
        """List all session collections."""
        collections = self._vector_store.list_collections()
        return [
            c.replace("temple_session_", "")
            for c in collections
            if c.startswith("temple_session_")
        ]

    # ── Admin Operations ─────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get system statistics."""
        collections = self._vector_store.list_collections()
        memory_counts = {}
        for c in collections:
            memory_counts[c] = self._vector_store.count(c)

        return {
            "collections": collections,
            "memory_counts": memory_counts,
            "total_memories": sum(memory_counts.values()),
            "entity_count": self._graph_store.entity_count(),
            "relation_count": self._graph_store.relation_count(),
            "active_context": self.get_context(),
        }

    def health_check(self) -> dict[str, Any]:
        """Check system health."""
        return {
            "status": "healthy",
            "vector_store": self._vector_store.heartbeat(),
            "graph_store": self._graph_store.entity_count() >= 0,
        }

    # ── Private Helpers ──────────────────────────────────────────────

    def _check_duplicate(self, collection: str, c_hash: str) -> MemoryEntry | None:
        """Check if a memory with this hash already exists."""
        try:
            result = self._vector_store.get(collection, ids=[c_hash])
            if result.get("ids") and result["ids"]:
                docs = result.get("documents", [])
                metas = result.get("metadatas", [])
                if docs:
                    meta = metas[0] if metas else {}
                    tags = json.loads(meta.get("tags", "[]")) if meta.get("tags") else []
                    return MemoryEntry(
                        id=c_hash,
                        content=docs[0],
                        content_hash=c_hash,
                        tags=tags,
                        scope=meta.get("scope", "global"),
                        created_at=meta.get("created_at", ""),
                    )
        except Exception:
            pass
        return None
