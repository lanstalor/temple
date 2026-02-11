"""Central memory broker - orchestrates all subsystems."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from temple.config import Settings
from temple.memory.audit_log import AuditLog
from temple.memory.context import ContextManager
from temple.memory.embedder import embed_text
from temple.memory.graph_store import GraphStore
from temple.memory.hashing import content_hash
from temple.memory.vector_store import VectorStore
from temple.models.context import ContextScope
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
        self._last_session_cleanup: datetime | None = None

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
        self._maybe_cleanup_expired_sessions()
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
            "updated_at": now,
            "tags": json.dumps(entry.tags),
            "metadata": json.dumps(entry.metadata),
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
        self._maybe_cleanup_expired_sessions()
        query_embedding = embed_text(query, self._settings.embedding_model)

        scopes = self._resolve_scopes(scope)

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

                metadata = json.loads(meta.get("metadata", "{}")) if meta.get("metadata") else {}

                entry = MemoryEntry(
                    id=doc_id,
                    content=docs[i],
                    content_hash=meta.get("content_hash", doc_id),
                    tags=tags,
                    metadata=metadata,
                    scope=meta.get("scope", ctx_scope.scope_key),
                    created_at=meta.get("created_at", ""),
                    updated_at=meta.get("updated_at", meta.get("created_at", "")),
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
                    self._context.parse_scope(r.memory.scope)
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
        self._maybe_cleanup_expired_sessions()
        scopes = self._resolve_scopes(scope)

        deleted = False
        for ctx_scope in scopes:
            collection = ctx_scope.collection_name
            try:
                existing = self._vector_store.get(collection_name=collection, ids=[memory_id])
                if not existing.get("ids"):
                    continue
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
        self._maybe_cleanup_expired_sessions()
        normalized_tags = [t.strip() for t in (tags or []) if t.strip()]

        if query:
            # Overfetch before applying tag filters so we still return enough rows.
            semantic_limit = max(n_results * 5, n_results)
            results = self.retrieve_memory(query, n_results=semantic_limit, scope=scope)
            if normalized_tags:
                results = [
                    r for r in results
                    if all(tag in r.memory.tags for tag in normalized_tags)
                ]
            return results[:n_results]

        if not normalized_tags:
            return []

        scopes = self._resolve_scopes(scope)
        all_results: list[MemorySearchResult] = []
        for ctx_scope in scopes:
            offset = 0
            batch_size = 200
            while True:
                try:
                    batch = self._vector_store.get_all(
                        collection_name=ctx_scope.collection_name,
                        limit=batch_size,
                        offset=offset,
                    )
                except Exception as e:
                    logger.debug(f"Tag search failed for {ctx_scope.collection_name}: {e}")
                    break

                ids = batch.get("ids", [])
                if not ids:
                    break

                docs = batch.get("documents", [])
                metas = batch.get("metadatas", [])
                for i, doc_id in enumerate(ids):
                    meta = metas[i] if i < len(metas) else {}
                    tags_raw = json.loads(meta.get("tags", "[]")) if meta.get("tags") else []
                    if not all(tag in tags_raw for tag in normalized_tags):
                        continue

                    metadata = json.loads(meta.get("metadata", "{}")) if meta.get("metadata") else {}
                    all_results.append(
                        MemorySearchResult(
                            memory=MemoryEntry(
                                id=doc_id,
                                content=docs[i],
                                content_hash=meta.get("content_hash", doc_id),
                                tags=tags_raw,
                                metadata=metadata,
                                scope=meta.get("scope", ctx_scope.scope_key),
                                created_at=meta.get("created_at", ""),
                                updated_at=meta.get("updated_at", meta.get("created_at", "")),
                            ),
                            score=1.0,
                            tier=ctx_scope.tier.value,
                        )
                    )

                offset += len(ids)
                if len(ids) < batch_size:
                    break

        all_results.sort(
            key=lambda r: (
                self._context.scope_precedence(self._context.parse_scope(r.memory.scope)),
                r.memory.updated_at,
            ),
            reverse=True,
        )
        return all_results[:n_results]

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
        self._maybe_cleanup_expired_sessions()
        for scope_key in self._scope_keys_for_graph_reads():
            entity = self._graph_store.get_entity(name, scope=scope_key)
            if entity:
                return entity
        return None

    def update_entity(self, name: str, **updates: Any) -> bool:
        """Update an entity."""
        self._maybe_cleanup_expired_sessions()
        for scope_key in self._scope_keys_for_graph_reads():
            result = self._graph_store.update_entity(name, scope=scope_key, **updates)
            if result:
                self._audit.log("update_entity", scope_key, {"name": name})
                return True
        return False

    def delete_entities(self, names: list[str]) -> list[dict[str, Any]]:
        """Delete multiple entities."""
        results = []
        for name in names:
            deleted = False
            deleted_scope = "global"
            for scope_key in self._scope_keys_for_graph_reads():
                deleted = self._graph_store.delete_entity(name, scope=scope_key)
                if deleted:
                    deleted_scope = scope_key
                    break
            results.append({"name": name, "deleted": deleted})
            if deleted:
                self._audit.log("delete_entity", deleted_scope, {"name": name})
        return results

    def search_entities(
        self,
        entity_type: str | None = None,
        scope: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search entities by type/scope."""
        self._maybe_cleanup_expired_sessions()
        normalized_scope = self._context.parse_scope(scope).scope_key if scope else None
        return self._graph_store.search_entities(
            entity_type=entity_type,
            scope=normalized_scope,
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
            deleted = False
            for scope_key in self._scope_keys_for_graph_reads():
                deleted = self._graph_store.delete_relation(
                    source=r["source"],
                    target=r["target"],
                    relation_type=r["relation_type"],
                    scope=scope_key,
                )
                if deleted:
                    break
            results.append({**r, "deleted": deleted})
        return results

    def get_relations(self, entity_name: str, direction: str = "both") -> list[dict[str, Any]]:
        """Get relations for an entity."""
        seen: set[tuple[str, str, str, str, str]] = set()
        merged: list[dict[str, Any]] = []
        for scope_key in self._scope_keys_for_graph_reads():
            relations = self._graph_store.get_relations(entity_name, direction, scope=scope_key)
            for rel in relations:
                key = (
                    rel["source"],
                    rel["target"],
                    rel["relation_type"],
                    rel["scope"],
                    rel["direction"],
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(rel)
        return merged

    def find_path(self, source: str, target: str, max_hops: int = 5) -> Any:
        """Find shortest path between entities."""
        for scope_key in self._scope_keys_for_graph_reads():
            path = self._graph_store.find_path(source, target, max_hops, scope=scope_key)
            if path is not None:
                return path
        return None

    # ── Observation Operations ───────────────────────────────────────

    def add_observations(self, entity_name: str, observations: list[str]) -> bool:
        """Add observations to an entity."""
        for scope_key in self._scope_keys_for_graph_reads():
            result = self._graph_store.add_observations(entity_name, observations, scope=scope_key)
            if result:
                self._audit.log("add_observations", scope_key, {
                    "entity": entity_name,
                    "count": len(observations),
                })
                return True
        return False

    def remove_observations(self, entity_name: str, observations: list[str]) -> bool:
        """Remove observations from an entity."""
        for scope_key in self._scope_keys_for_graph_reads():
            result = self._graph_store.remove_observations(entity_name, observations, scope=scope_key)
            if result:
                self._audit.log("remove_observations", scope_key, {
                    "entity": entity_name,
                    "count": len(observations),
                })
                return True
        return False

    # ── Context Operations ───────────────────────────────────────────

    def set_context(
        self,
        project: str | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        """Set the active context."""
        self._maybe_cleanup_expired_sessions(force=True)
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
        self._maybe_cleanup_expired_sessions()
        return {
            "project": self._context.context.project,
            "session": self._context.context.session,
            "active_scopes": [s.scope_key for s in self._context.get_active_scopes()],
        }

    def list_projects(self) -> list[str]:
        """List all project collections."""
        self._maybe_cleanup_expired_sessions()
        collections = self._vector_store.list_collections()
        return [
            c.replace("temple_project_", "")
            for c in collections
            if c.startswith("temple_project_")
        ]

    def list_sessions(self) -> list[str]:
        """List all session collections."""
        self._maybe_cleanup_expired_sessions(force=True)
        collections = self._vector_store.list_collections()
        return [
            c.replace("temple_session_", "")
            for c in collections
            if c.startswith("temple_session_")
        ]

    # ── Admin Operations ─────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get system statistics."""
        self._maybe_cleanup_expired_sessions(force=True)
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
            "graph_schema": self._graph_store.schema_version,
            "active_context": self.get_context(),
        }

    def export_knowledge_graph(
        self,
        scope: str | None = None,
        limit: int = 10000,
        include_memories: bool = False,
        memory_limit: int = 5000,
    ) -> dict[str, Any]:
        """Export entities and outgoing relations for visualization/backup."""
        self._maybe_cleanup_expired_sessions(force=True)
        normalized_scope = self._context.parse_scope(scope).scope_key if scope else None
        entities = self._graph_store.search_entities(scope=normalized_scope, limit=limit)

        entity_scope_by_name: dict[str, set[str]] = {}
        for entity in entities:
            entity_scope_by_name.setdefault(entity["name"], set()).add(entity["scope"])

        seen_relations: set[tuple[str, str, str, str, str, str | None]] = set()
        all_relations: list[dict[str, Any]] = []
        for entity in entities:
            source_scope = entity["scope"]
            relations = self._graph_store.get_relations(
                entity["name"],
                direction="out",
                scope=source_scope,
            )
            for rel in relations:
                target_name = rel["target"]
                target_scope = self._resolve_export_target_scope(
                    target_name=target_name,
                    relation_scope=rel["scope"],
                    known_scopes=entity_scope_by_name,
                )
                key = (
                    rel["source"],
                    source_scope,
                    rel["target"],
                    target_scope or "",
                    rel["relation_type"],
                    rel["scope"],
                )
                if key in seen_relations:
                    continue
                seen_relations.add(key)
                all_relations.append(
                    {
                        "source": rel["source"],
                        "source_scope": source_scope,
                        "target": rel["target"],
                        "target_scope": target_scope,
                        "relation_type": rel["relation_type"],
                        "scope": rel["scope"],
                        "created_at": rel.get("created_at", ""),
                    }
                )

        payload = {
            "entities": entities,
            "relations": all_relations,
            "entity_count": len(entities),
            "relation_count": len(all_relations),
            "scope": normalized_scope or "all",
        }
        if include_memories:
            memories = self._export_memories(scope=normalized_scope, limit=memory_limit)
            payload["memories"] = memories
            payload["memory_count"] = len(memories)
        return payload

    def health_check(self) -> dict[str, Any]:
        """Check system health."""
        self._maybe_cleanup_expired_sessions()
        return {
            "status": "healthy",
            "vector_store": self._vector_store.heartbeat(),
            "graph_store": self._graph_store.entity_count() >= 0,
            "graph_schema": self._graph_store.schema_version,
        }

    def compact_audit_log(self, scope: str = "global", keep: int = 1000) -> int:
        """Compact audit logs for a scope, keeping the most recent entries."""
        return self._audit.compact(scope=scope, keep=keep)

    def get_graph_schema_status(self) -> dict[str, Any]:
        """Get graph schema status and migration readiness."""
        return {
            "schema_version": self._graph_store.schema_version,
            "legacy_schema_detected": self._graph_store.is_legacy_schema(),
            "entity_count": self._graph_store.entity_count(),
            "relation_count": self._graph_store.relation_count(),
        }

    def migrate_graph_schema(self, backup_path: str | None = None) -> dict[str, Any]:
        """Migrate legacy graph schema to v2."""
        result = self._graph_store.migrate_legacy_schema(backup_path=backup_path)
        if result.get("migrated"):
            self._audit.log("migrate_graph_schema", "global", {
                "schema_version": result.get("schema_version"),
                "entities_migrated": result.get("entities_migrated", 0),
                "relations_migrated": result.get("relations_migrated", 0),
                "relations_skipped": result.get("relations_skipped", 0),
                "backup_path": result.get("backup_path"),
            })
        return result

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
                    metadata = json.loads(meta.get("metadata", "{}")) if meta.get("metadata") else {}
                    return MemoryEntry(
                        id=c_hash,
                        content=docs[0],
                        content_hash=c_hash,
                        tags=tags,
                        metadata=metadata,
                        scope=meta.get("scope", "global"),
                        created_at=meta.get("created_at", ""),
                        updated_at=meta.get("updated_at", meta.get("created_at", "")),
                    )
        except Exception:
            pass
        return None

    def _export_memories(
        self,
        scope: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Export memory notes from vector collections for visualization."""
        target_limit = max(1, limit)
        if scope:
            collections = [self._context.parse_scope(scope).collection_name]
        else:
            collections = sorted(self._vector_store.list_collections())

        memories: list[dict[str, Any]] = []
        for collection_name in collections:
            if len(memories) >= target_limit:
                break

            offset = 0
            batch_size = 200
            while len(memories) < target_limit:
                try:
                    batch = self._vector_store.get_all(
                        collection_name=collection_name,
                        limit=min(batch_size, target_limit - len(memories)),
                        offset=offset,
                    )
                except Exception as e:
                    logger.debug(f"Memory export read failed for {collection_name}: {e}")
                    break

                ids = batch.get("ids", [])
                if not ids:
                    break

                docs = batch.get("documents", [])
                metas = batch.get("metadatas", [])
                for idx, memory_id in enumerate(ids):
                    if len(memories) >= target_limit:
                        break
                    meta = metas[idx] if idx < len(metas) else {}
                    tags = json.loads(meta.get("tags", "[]")) if meta.get("tags") else []
                    metadata = json.loads(meta.get("metadata", "{}")) if meta.get("metadata") else {}
                    memories.append(
                        {
                            "id": memory_id,
                            "content_hash": meta.get("content_hash", memory_id),
                            "content": docs[idx] if idx < len(docs) else "",
                            "scope": meta.get("scope", "global"),
                            "tags": tags,
                            "metadata": metadata,
                            "created_at": meta.get("created_at", ""),
                            "updated_at": meta.get("updated_at", meta.get("created_at", "")),
                            "collection": collection_name,
                        }
                    )

                offset += len(ids)
                if len(ids) < batch_size:
                    break

        memories.sort(
            key=lambda note: note.get("updated_at") or note.get("created_at") or "",
            reverse=True,
        )
        return memories

    def _resolve_scopes(self, scope: str | None = None) -> list[ContextScope]:
        """Resolve context scopes for retrieval/search operations."""
        if scope:
            return [self._context.parse_scope(scope)]
        return self._context.get_retrieval_scopes()

    def _scope_keys_for_graph_reads(self) -> list[str]:
        """Resolve graph scope keys in highest-precedence-first order."""
        return [scope.scope_key for scope in reversed(self._context.get_retrieval_scopes())]

    def _resolve_export_target_scope(
        self,
        target_name: str,
        relation_scope: str,
        known_scopes: dict[str, set[str]],
    ) -> str | None:
        """Pick a target scope for relation export when duplicate names exist."""
        scopes = known_scopes.get(target_name, set())
        if not scopes:
            return None
        if relation_scope in scopes:
            return relation_scope
        if len(scopes) == 1:
            return next(iter(scopes))
        return None

    def _session_expiration_cutoff(self) -> datetime | None:
        """Return the TTL cutoff timestamp, or None when expiration is disabled."""
        if self._settings.session_ttl <= 0:
            return None
        return datetime.now(timezone.utc) - timedelta(seconds=self._settings.session_ttl)

    def _parse_iso(self, value: str | None) -> datetime | None:
        """Parse an ISO timestamp into an aware datetime."""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def _maybe_cleanup_expired_sessions(self, force: bool = False) -> None:
        """Cleanup expired session-scoped memory collections and graph nodes."""
        cutoff = self._session_expiration_cutoff()
        if cutoff is None:
            return

        now = datetime.now(timezone.utc)
        if not force and self._last_session_cleanup and (now - self._last_session_cleanup) < timedelta(minutes=5):
            return

        self._last_session_cleanup = now
        collections = self._vector_store.list_collections()
        session_collections = [c for c in collections if c.startswith("temple_session_")]
        for collection in session_collections:
            session_id = collection.replace("temple_session_", "", 1)
            scope_key = f"session:{session_id}"
            latest_seen: datetime | None = None
            offset = 0
            batch_size = 200

            while True:
                try:
                    batch = self._vector_store.get_all(
                        collection_name=collection,
                        limit=batch_size,
                        offset=offset,
                    )
                except Exception as e:
                    logger.debug(f"Session cleanup read failed for {collection}: {e}")
                    break

                ids = batch.get("ids", [])
                if not ids:
                    break

                for meta in batch.get("metadatas", []):
                    if not meta:
                        continue
                    updated_at = self._parse_iso(meta.get("updated_at"))
                    created_at = self._parse_iso(meta.get("created_at"))
                    candidate = updated_at or created_at
                    if candidate and (latest_seen is None or candidate > latest_seen):
                        latest_seen = candidate

                offset += len(ids)
                if len(ids) < batch_size:
                    break

            should_expire = latest_seen is None or latest_seen < cutoff
            if not should_expire:
                continue

            self._vector_store.delete_collection(collection)
            deleted_scope = self._graph_store.delete_scope(scope_key)
            if self._context.context.session == session_id:
                self._context.set_session(None)

            self._audit.log("expire_session", scope_key, {
                "collection": collection,
                "last_seen_at": latest_seen.isoformat() if latest_seen else None,
                "ttl_seconds": self._settings.session_ttl,
                **deleted_scope,
            })
