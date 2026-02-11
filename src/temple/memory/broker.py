"""Central memory broker - orchestrates all subsystems."""

from __future__ import annotations

import json
import logging
import queue
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from temple.config import Settings
from temple.memory.audit_log import AuditLog
from temple.memory.context import ContextManager
from temple.memory.embedder import embed_text
from temple.memory.graph_store import GraphStore
from temple.memory.hashing import content_hash
from temple.memory.llm_extractor import (
    ExtractionResult,
    _infer_entity_type,
    _normalize_entity_name,
    extract as llm_extract,
)
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
        self._ingest_lock = threading.Lock()
        self._ingest_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._ingest_jobs: dict[str, dict[str, Any]] = {}
        self._ingest_reviews: dict[str, dict[str, Any]] = {}
        self._ingest_payloads: dict[str, dict[str, Any]] = {}
        self._ingest_state_path = settings.audit_dir / "ingest_state.json"
        self._load_ingest_state()
        self._ingest_worker = threading.Thread(
            target=self._ingest_worker_loop,
            name="temple-ingest-worker",
            daemon=True,
        )
        self._ingest_worker.start()
        self._resume_pending_ingest_jobs()

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

        with self._ingest_lock:
            ingest_jobs = len(self._ingest_jobs)
            ingest_pending_reviews = len([r for r in self._ingest_reviews.values() if r["status"] == "pending"])

        return {
            "collections": collections,
            "memory_counts": memory_counts,
            "total_memories": sum(memory_counts.values()),
            "entity_count": self._graph_store.entity_count(),
            "relation_count": self._graph_store.relation_count(),
            "graph_schema": self._graph_store.schema_version,
            "active_context": self.get_context(),
            # New canonical keys
            "ingest_jobs": ingest_jobs,
            "ingest_pending_reviews": ingest_pending_reviews,
            # Backward-compat aliases
            "survey_jobs": ingest_jobs,
            "survey_pending_reviews": ingest_pending_reviews,
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

    # ── General Ingest Operations ────────────────────────────────────

    def submit_ingest_item(
        self,
        item_type: str,
        actor_id: str,
        source: str,
        content: str,
        source_id: str | None = None,
        timestamp: str | None = None,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        scope: str = "global",
    ) -> dict[str, Any]:
        """Store a text payload and enqueue asynchronous enrichment.

        This is the universal ingest entrypoint for any content type
        (email, document, chat, meeting note, ticket, survey, note).
        """
        self._maybe_cleanup_expired_sessions()
        normalized_scope = self._context.parse_scope(scope).scope_key
        key = idempotency_key.strip() if idempotency_key else None
        key_tag = f"ingest-idem:{key}" if key else None

        if key_tag:
            existing = self.search_memories(
                tags=["ingest-item", key_tag],
                scope=normalized_scope,
                n_results=1,
            )
            if existing:
                memory = existing[0].memory
                return {
                    "status": "duplicate",
                    "job_id": memory.metadata.get("ingest_job_id"),
                    "memory_id": memory.id,
                    "scope": memory.scope,
                    "queued": False,
                }

        job_id = uuid4().hex
        now = timestamp or datetime.now(timezone.utc).isoformat()
        tags = [
            "ingest-item",
            f"item_type:{item_type}",
            f"source:{source}",
            f"actor:{actor_id}",
        ]
        if key_tag:
            tags.append(key_tag)
        if source_id:
            tags.append(f"source_id:{source_id}")

        merged_meta = dict(metadata or {})
        merged_meta.update({
            "item_type": item_type,
            "actor_id": actor_id,
            "source": source,
            "source_id": source_id or "",
            "ingest_job_id": job_id,
            "submitted_at": now,
        })

        entry = self.store_memory(
            content,
            tags=tags,
            metadata=merged_meta,
            scope=normalized_scope,
        )

        job_state = {
            "job_id": job_id,
            "status": "queued",
            "item_type": item_type,
            "actor_id": actor_id,
            "source": source,
            "source_id": source_id or "",
            "scope": normalized_scope,
            "memory_id": entry.id,
            "submitted_at": now,
            "started_at": None,
            "finished_at": None,
            "extraction_method": None,
            "relations_created": 0,
            "reviews_created": 0,
            "entities_touched": 0,
            "errors": [],
        }
        with self._ingest_lock:
            self._ingest_jobs[job_id] = job_state
            self._ingest_payloads[job_id] = {
                "job_id": job_id,
                "item_type": item_type,
                "actor_id": actor_id,
                "source": source,
                "source_id": source_id or "",
                "scope": normalized_scope,
                "memory_id": entry.id,
                "content": content,
            }
        self._persist_ingest_state()

        self._audit.log("ingest_submit", normalized_scope, {
            "job_id": job_id,
            "item_type": item_type,
            "actor_id": actor_id,
            "source": source,
            "memory_id": entry.id,
            "idempotency_key_present": bool(key_tag),
        })

        self._ingest_queue.put(self._ingest_payloads[job_id])
        return {
            "status": "queued",
            "job_id": job_id,
            "memory_id": entry.id,
            "scope": normalized_scope,
            "queued": True,
        }

    def get_ingest_job(self, job_id: str) -> dict[str, Any] | None:
        """Return current ingest job status."""
        with self._ingest_lock:
            job = self._ingest_jobs.get(job_id)
            if not job:
                return None
            return dict(job)

    def list_ingest_reviews(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        """List relation candidates awaiting review (or all statuses)."""
        target = status.strip().lower()
        with self._ingest_lock:
            reviews = list(self._ingest_reviews.values())

        if target != "all":
            reviews = [r for r in reviews if r.get("status") == target]
        reviews.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return reviews[:max(1, min(limit, 1000))]

    def review_ingest_relation(
        self,
        review_id: str,
        decision: str,
        reviewer: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Approve or reject a queued inferred relation."""
        normalized = decision.strip().lower()
        if normalized not in {"approve", "reject"}:
            raise ValueError("decision must be one of: approve, reject")

        with self._ingest_lock:
            record = self._ingest_reviews.get(review_id)
            if not record:
                return None
            if record["status"] != "pending":
                return dict(record)

        applied = False
        if normalized == "approve":
            rel = record["candidate"]
            applied = self._create_relation_in_scope(
                source=rel["source"],
                target=rel["target"],
                relation_type=rel["relation_type"],
                scope=rel["scope"],
                confidence=rel.get("confidence", 0.0),
                provenance=rel.get("provenance", {}),
            )

        now = datetime.now(timezone.utc).isoformat()
        with self._ingest_lock:
            record = self._ingest_reviews[review_id]
            record["status"] = "approved" if normalized == "approve" else "rejected"
            record["reviewed_at"] = now
            record["reviewer"] = reviewer or ""
            record["notes"] = notes or ""
            record["applied"] = applied
            updated = dict(record)
        self._persist_ingest_state()

        self._audit.log("ingest_review", updated["candidate"]["scope"], {
            "review_id": review_id,
            "decision": normalized,
            "applied": applied,
            "reviewer": reviewer or "",
        })
        return updated

    # ── Survey Enrichment Operations (backward-compat wrappers) ──────

    def submit_survey_response(
        self,
        survey_id: str,
        respondent_id: str,
        response: str,
        source: str = "survey",
        version: str = "1",
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        scope: str = "project:survey",
    ) -> dict[str, Any]:
        """Store a survey response and enqueue asynchronous enrichment.

        Thin wrapper around submit_ingest_item() for backward compatibility.
        """
        merged_meta = dict(metadata or {})
        merged_meta.update({
            "survey_id": survey_id,
            "respondent_id": respondent_id,
            "version": version,
        })
        return self.submit_ingest_item(
            item_type="survey",
            actor_id=respondent_id,
            source=source,
            content=response,
            source_id=survey_id,
            idempotency_key=idempotency_key,
            metadata=merged_meta,
            scope=scope,
        )

    def get_survey_job(self, job_id: str) -> dict[str, Any] | None:
        """Return current survey job status (delegates to get_ingest_job)."""
        return self.get_ingest_job(job_id)

    def list_survey_reviews(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        """List relation candidates awaiting review (delegates to list_ingest_reviews)."""
        return self.list_ingest_reviews(status=status, limit=limit)

    def review_survey_relation(
        self,
        review_id: str,
        decision: str,
        reviewer: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        """Approve or reject a queued inferred relation (delegates to review_ingest_relation)."""
        return self.review_ingest_relation(
            review_id=review_id,
            decision=decision,
            reviewer=reviewer,
            notes=notes,
        )

    def get_relationship_map(
        self,
        entity: str,
        depth: int = 2,
        scope: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return an explainable graph slice around an entity."""
        max_depth = max(1, min(int(depth), 4))
        max_nodes = max(1, min(int(limit), 1000))
        normalized_scope = self._context.parse_scope(scope).scope_key if scope else None

        visited: set[str] = {entity}
        queue_nodes = deque([(entity, 0)])
        nodes: list[dict[str, Any]] = []
        relations: list[dict[str, Any]] = []
        relation_seen: set[tuple[str, str, str, str]] = set()

        while queue_nodes and len(visited) <= max_nodes:
            current, level = queue_nodes.popleft()
            node = self._graph_store.get_entity(current, scope=normalized_scope) if normalized_scope else self.get_entity(current)
            if node:
                node_payload = {
                    "name": node["name"],
                    "entity_type": node.get("entity_type", "unknown"),
                    "scope": node.get("scope", normalized_scope or "global"),
                    "observations": node.get("observations", []),
                }
                if not any(n["name"] == node_payload["name"] and n["scope"] == node_payload["scope"] for n in nodes):
                    nodes.append(node_payload)

            if level >= max_depth:
                continue

            rels = self._graph_store.get_relations(current, direction="both", scope=normalized_scope)
            for rel in rels:
                key = (rel["source"], rel["target"], rel["relation_type"], rel["scope"])
                if key not in relation_seen:
                    relation_seen.add(key)
                    relations.append({
                        "source": rel["source"],
                        "target": rel["target"],
                        "relation_type": rel["relation_type"],
                        "scope": rel["scope"],
                        "direction": rel["direction"],
                    })

                neighbor = rel["target"] if rel["source"] == current else rel["source"]
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue_nodes.append((neighbor, level + 1))
                if len(visited) >= max_nodes:
                    break

        return {
            "entity": entity,
            "depth": max_depth,
            "scope": normalized_scope or "active",
            "nodes": nodes,
            "relations": relations,
            "node_count": len(nodes),
            "relation_count": len(relations),
        }

    # ── Private Helpers ──────────────────────────────────────────────

    def _ingest_worker_loop(self) -> None:
        """Background worker for ingest enrichment jobs."""
        while True:
            payload = self._ingest_queue.get()
            job_id = payload.get("job_id", "")
            now = datetime.now(timezone.utc).isoformat()
            with self._ingest_lock:
                if job_id in self._ingest_jobs:
                    self._ingest_jobs[job_id]["status"] = "processing"
                    self._ingest_jobs[job_id]["started_at"] = now
            self._persist_ingest_state()

            try:
                result = self._process_ingest_payload(payload)
                finished = datetime.now(timezone.utc).isoformat()
                with self._ingest_lock:
                    if job_id in self._ingest_jobs:
                        self._ingest_jobs[job_id]["status"] = "completed"
                        self._ingest_jobs[job_id]["finished_at"] = finished
                        self._ingest_jobs[job_id]["extraction_method"] = result.get("extraction_method")
                        self._ingest_jobs[job_id]["relations_created"] = result["relations_created"]
                        self._ingest_jobs[job_id]["reviews_created"] = result["reviews_created"]
                        self._ingest_jobs[job_id]["entities_touched"] = result["entities_touched"]
                        self._ingest_payloads.pop(job_id, None)
                self._persist_ingest_state()
            except Exception as e:
                logger.exception("Ingest enrichment failed for job %s", job_id)
                failed = datetime.now(timezone.utc).isoformat()
                with self._ingest_lock:
                    if job_id in self._ingest_jobs:
                        self._ingest_jobs[job_id]["status"] = "failed"
                        self._ingest_jobs[job_id]["finished_at"] = failed
                        self._ingest_jobs[job_id]["errors"].append(str(e))
                        self._ingest_payloads.pop(job_id, None)
                self._persist_ingest_state()
            finally:
                self._ingest_queue.task_done()

    def _process_ingest_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract entities/relations from an ingest payload and apply confidence policy."""
        scope = payload["scope"]
        content = payload["content"]
        actor_id = payload.get("actor_id", "")
        source = payload.get("source", "unknown")
        job_id = payload.get("job_id", "")
        memory_id = payload.get("memory_id", "")

        extraction: ExtractionResult = llm_extract(content, actor_id, self._settings)

        touched = 0
        for entity in extraction.entities:
            entity_type = entity.get("type", "concept")
            created = self._graph_store.create_entity(entity["name"], entity_type, scope=scope)
            if created:
                touched += 1
                self._audit.log("create_entity", scope, {
                    "name": entity["name"],
                    "source": f"ingest-enrichment-{extraction.extraction_method}",
                })

        similar = self.retrieve_memory(content, n_results=3, scope=scope)
        signal_boost = 0.05 if any(
            r.memory.id != memory_id and r.score >= 0.88 for r in similar
        ) else 0.0

        created_relations = 0
        review_relations = 0
        for rel in extraction.relations:
            confidence = min(0.99, rel["confidence"] + signal_boost)
            provenance = {
                "job_id": job_id,
                "memory_id": memory_id,
                "source": source,
                "extraction_method": extraction.extraction_method,
                "signal_boost": round(signal_boost, 3),
            }
            if extraction.llm_usage:
                provenance["llm_usage"] = extraction.llm_usage

            relation_type = rel["type"]
            if confidence >= 0.80:
                created = self._create_relation_in_scope(
                    source=rel["source"],
                    target=rel["target"],
                    relation_type=relation_type,
                    scope=scope,
                    confidence=confidence,
                    provenance=provenance,
                )
                if created:
                    created_relations += 1
            elif confidence >= 0.60:
                self._enqueue_review_candidate(
                    candidate={
                        "source": rel["source"],
                        "target": rel["target"],
                        "relation_type": relation_type,
                        "scope": scope,
                        "confidence": round(confidence, 3),
                        "provenance": provenance,
                    },
                    ingest_job_id=job_id,
                    memory_id=memory_id,
                )
                review_relations += 1

        self._audit.log("ingest_enriched", scope, {
            "job_id": job_id,
            "extraction_method": extraction.extraction_method,
            "entities_touched": touched,
            "relations_created": created_relations,
            "reviews_created": review_relations,
            "llm_error": extraction.llm_error,
        })
        return {
            "entities_touched": touched,
            "relations_created": created_relations,
            "reviews_created": review_relations,
            "extraction_method": extraction.extraction_method,
        }

    def _enqueue_review_candidate(
        self,
        candidate: dict[str, Any],
        ingest_job_id: str,
        memory_id: str,
    ) -> None:
        """Queue a medium-confidence inferred relation for human review."""
        review_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "review_id": review_id,
            "status": "pending",
            "created_at": now,
            "reviewed_at": None,
            "reviewer": "",
            "notes": "",
            "applied": False,
            "ingest_job_id": ingest_job_id,
            # Keep backward-compat key
            "survey_job_id": ingest_job_id,
            "memory_id": memory_id,
            "candidate": candidate,
        }
        with self._ingest_lock:
            self._ingest_reviews[review_id] = record
        self._persist_ingest_state()
        self._audit.log("ingest_review_queued", candidate["scope"], {
            "review_id": review_id,
            "source": candidate["source"],
            "target": candidate["target"],
            "relation_type": candidate["relation_type"],
            "confidence": candidate["confidence"],
        })

    def _create_relation_in_scope(
        self,
        source: str,
        target: str,
        relation_type: str,
        scope: str,
        confidence: float,
        provenance: dict[str, Any],
    ) -> bool:
        """Create a relation in a specific scope and audit provenance."""
        if source == target:
            return False

        source_exists = self._graph_store.get_entity(source, scope=scope)
        if not source_exists:
            self._graph_store.create_entity(source, _infer_entity_type(source), scope=scope)
        target_exists = self._graph_store.get_entity(target, scope=scope)
        if not target_exists:
            self._graph_store.create_entity(target, _infer_entity_type(target), scope=scope)

        created = self._graph_store.create_relation(
            source=source,
            target=target,
            relation_type=relation_type,
            scope=scope,
        )
        if created:
            self._audit.log("create_relation_inferred", scope, {
                "source": source,
                "target": target,
                "relation_type": relation_type,
                "confidence": round(confidence, 3),
                "provenance": provenance,
            })
        return created

    def _ingest_state_snapshot(self) -> dict[str, Any]:
        """Build a serializable snapshot of ingest job/review state."""
        with self._ingest_lock:
            jobs = {k: dict(v) for k, v in self._ingest_jobs.items()}
            reviews = {k: dict(v) for k, v in self._ingest_reviews.items()}
            payloads = {k: dict(v) for k, v in self._ingest_payloads.items()}
        return {
            "version": 2,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "jobs": jobs,
            "reviews": reviews,
            "payloads": payloads,
        }

    def _persist_ingest_state(self) -> None:
        """Persist ingest job/review state to disk for restart durability."""
        snapshot = self._ingest_state_snapshot()
        try:
            self._ingest_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._ingest_state_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(snapshot, ensure_ascii=True))
            tmp_path.replace(self._ingest_state_path)
        except Exception as e:
            logger.warning("Failed to persist ingest state: %s", e)

    def _load_ingest_state(self) -> None:
        """Load persisted ingest job/review state from disk.

        Falls back to reading legacy survey_state.json for migration.
        """
        state_path = self._ingest_state_path
        if not state_path.exists():
            # Try legacy filename for migration
            legacy_path = self._ingest_state_path.parent / "survey_state.json"
            if legacy_path.exists():
                state_path = legacy_path
                logger.info("Migrating state from survey_state.json → ingest_state.json")
            else:
                return

        try:
            payload = json.loads(state_path.read_text())
        except Exception as e:
            logger.warning("Failed to read ingest state file %s: %s", state_path, e)
            return

        jobs_raw = payload.get("jobs", {})
        reviews_raw = payload.get("reviews", {})
        payloads_raw = payload.get("payloads", {})
        if not isinstance(jobs_raw, dict) or not isinstance(reviews_raw, dict) or not isinstance(payloads_raw, dict):
            logger.warning("Ingest state file has invalid shape; ignoring")
            return

        with self._ingest_lock:
            self._ingest_jobs = {k: dict(v) for k, v in jobs_raw.items() if isinstance(v, dict)}
            self._ingest_reviews = {k: dict(v) for k, v in reviews_raw.items() if isinstance(v, dict)}
            self._ingest_payloads = {k: dict(v) for k, v in payloads_raw.items() if isinstance(v, dict)}

            for job_id, job in self._ingest_jobs.items():
                status = str(job.get("status", "queued"))
                if status in {"queued", "processing"} and job_id not in self._ingest_payloads:
                    job["status"] = "failed"
                    job.setdefault("errors", [])
                    job["errors"].append("missing persisted payload for queued/processing job")
                    job["finished_at"] = datetime.now(timezone.utc).isoformat()
                elif status == "processing":
                    # Job was in-flight during restart; resume from queued.
                    job["status"] = "queued"
                    job["started_at"] = None

                # Ensure new fields exist on migrated jobs
                job.setdefault("item_type", job.get("survey_id", "survey") and "survey")
                job.setdefault("actor_id", job.get("respondent_id", ""))
                job.setdefault("extraction_method", None)

            # Ensure review records have new key alongside legacy
            for review in self._ingest_reviews.values():
                review.setdefault("ingest_job_id", review.get("survey_job_id", ""))

    def _resume_pending_ingest_jobs(self) -> None:
        """Re-enqueue queued ingest jobs loaded from persisted state."""
        to_resume: list[dict[str, Any]] = []
        with self._ingest_lock:
            for job_id, job in self._ingest_jobs.items():
                if job.get("status") != "queued":
                    continue
                payload = self._ingest_payloads.get(job_id)
                if not payload:
                    continue
                # Ensure payload has generalized keys
                payload.setdefault("content", payload.get("response", ""))
                payload.setdefault("actor_id", payload.get("respondent_id", ""))
                payload.setdefault("item_type", "survey")
                to_resume.append(dict(payload))

        for payload in to_resume:
            self._ingest_queue.put(payload)
        if to_resume:
            logger.info("Resumed %d ingest jobs from persisted state", len(to_resume))
            self._persist_ingest_state()

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
