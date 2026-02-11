"""Tests for REST compatibility server."""

from typing import Any

import httpx
import pytest

from temple.config import Settings
from temple.models.memory import MemoryEntry, MemorySearchResult
from temple.rest_server import create_app


class _FakeBroker:
    def __init__(self) -> None:
        self._entries: list[MemoryEntry] = []
        self._survey_jobs: dict[str, dict[str, Any]] = {}
        self._survey_reviews: dict[str, dict[str, Any]] = {
            "rev-1": {
                "review_id": "rev-1",
                "status": "pending",
                "candidate": {
                    "source": "Lance",
                    "target": "Temple",
                    "relation_type": "uses",
                    "scope": "project:survey",
                    "confidence": 0.73,
                    "provenance": {"survey_id": "s-1"},
                },
            }
        }

    def health_check(self) -> dict[str, Any]:
        return {"status": "healthy", "graph_schema": "v2"}

    def store_memory(
        self,
        content: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        scope: str | None = None,
    ) -> MemoryEntry:
        entry = MemoryEntry(
            id=f"id-{len(self._entries)+1}",
            content=content,
            content_hash=f"hash-{len(self._entries)+1}",
            tags=tags or [],
            metadata=metadata or {},
            scope=scope or "global",
        )
        self._entries.append(entry)
        return entry

    def retrieve_memory(
        self,
        query: str,
        n_results: int = 5,
        scope: str | None = None,
    ) -> list[MemorySearchResult]:
        results = [
            MemorySearchResult(memory=entry, score=0.99, tier="global")
            for entry in self._entries
            if query.lower() in entry.content.lower()
        ]
        return results[:n_results]

    def search_memories(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        scope: str | None = None,
        n_results: int = 10,
    ) -> list[MemorySearchResult]:
        matched = self._entries
        if query:
            matched = [e for e in matched if query.lower() in e.content.lower()]
        if tags:
            matched = [e for e in matched if all(tag in e.tags for tag in tags)]
        return [MemorySearchResult(memory=e, score=0.99, tier="global") for e in matched[:n_results]]

    def delete_memory(self, memory_id: str, scope: str | None = None) -> bool:
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != memory_id]
        return len(self._entries) != before

    def get_context(self) -> dict[str, Any]:
        return {"project": None, "session": None, "active_scopes": ["global"]}

    def set_context(self, project: str | None = None, session: str | None = None) -> dict[str, Any]:
        return {"project": project, "session": session, "active_scopes": ["global"]}

    def list_projects(self) -> list[str]:
        return []

    def list_sessions(self) -> list[str]:
        return []

    def get_stats(self) -> dict[str, Any]:
        return {"total_memories": len(self._entries), "graph_schema": "v2"}

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
        job_id = f"job-{len(self._survey_jobs) + 1}"
        self._survey_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "survey_id": survey_id,
            "respondent_id": respondent_id,
            "scope": scope,
            "memory_id": f"memory-{job_id}",
        }
        return {"status": "queued", "job_id": job_id, "memory_id": f"memory-{job_id}", "scope": scope, "queued": True}

    def get_survey_job(self, job_id: str) -> dict[str, Any] | None:
        return self._survey_jobs.get(job_id)

    def list_survey_reviews(self, status: str = "pending", limit: int = 100) -> list[dict[str, Any]]:
        records = list(self._survey_reviews.values())
        if status != "all":
            records = [r for r in records if r["status"] == status]
        return records[:limit]

    def review_survey_relation(
        self,
        review_id: str,
        decision: str,
        reviewer: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any] | None:
        record = self._survey_reviews.get(review_id)
        if not record:
            return None
        if decision == "approve":
            record["status"] = "approved"
            record["applied"] = True
        elif decision == "reject":
            record["status"] = "rejected"
            record["applied"] = False
        else:
            raise ValueError("decision must be one of: approve, reject")
        record["reviewer"] = reviewer or ""
        record["notes"] = notes or ""
        return record

    def get_relationship_map(
        self,
        entity: str,
        depth: int = 2,
        scope: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return {
            "entity": entity,
            "depth": depth,
            "scope": scope or "active",
            "nodes": [{"name": entity, "entity_type": "person", "scope": "global", "observations": []}],
            "relations": [],
            "node_count": 1,
            "relation_count": 0,
        }

    def export_knowledge_graph(
        self,
        scope: str | None = None,
        limit: int = 10000,
        include_memories: bool = False,
        memory_limit: int = 5000,
    ) -> dict[str, Any]:
        entities = [
            {"name": "Temple", "entity_type": "project", "observations": ["self-hosted memory"], "scope": "project:temple"},
            {"name": "Claude", "entity_type": "agent", "observations": ["uses MCP"], "scope": "global"},
        ]
        relations = [
            {
                "source": "Claude",
                "source_scope": "global",
                "target": "Temple",
                "target_scope": "project:temple",
                "relation_type": "uses",
                "scope": "global",
                "created_at": "",
            }
        ]
        payload = {
            "entities": entities[:limit],
            "relations": relations,
            "entity_count": min(len(entities), limit),
            "relation_count": len(relations),
            "scope": scope or "all",
        }
        if include_memories:
            payload["memories"] = [
                {
                    "id": "note-1",
                    "content_hash": "note-1",
                    "content": "Temple stores durable memory",
                    "scope": "global",
                    "tags": ["memory"],
                    "metadata": {},
                    "created_at": "",
                    "updated_at": "",
                    "collection": "temple_global",
                }
            ][:memory_limit]
            payload["memory_count"] = len(payload["memories"])
        return payload

    def get_graph_schema_status(self) -> dict[str, Any]:
        return {"schema_version": "v2", "legacy_schema_detected": False}

    def migrate_graph_schema(self, backup_path: str | None = None) -> dict[str, Any]:
        return {"migrated": False, "reason": "already_v2"}

    def create_entities(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"name": e["name"], "created": True} for e in entities]

    def delete_entities(self, names: list[str]) -> list[dict[str, Any]]:
        return [{"name": n, "deleted": True} for n in names]

    def get_entity(self, name: str) -> dict[str, Any] | None:
        return {"name": name, "entity_type": "test", "observations": [], "scope": "global"}

    def update_entity(self, name: str, **updates: Any) -> bool:
        return True

    def create_relations(self, relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "created": True} for r in relations]

    def delete_relations(self, relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "deleted": True} for r in relations]

    def get_relations(self, entity_name: str, direction: str = "both") -> list[dict[str, Any]]:
        return []

    def find_path(self, source: str, target: str, max_hops: int = 5) -> dict[str, Any] | None:
        return None

    def add_observations(self, entity_name: str, observations: list[str]) -> bool:
        return True

    def remove_observations(self, entity_name: str, observations: list[str]) -> bool:
        return True


def _make_app(tmp_data_dir, api_key: str = ""):
    settings = Settings(
        api_key=api_key,
    )
    broker = _FakeBroker()
    return create_app(broker=broker, config=settings)


@pytest.mark.asyncio
async def test_rest_health_and_openapi(tmp_data_dir):
    """Health and OpenAPI endpoints are available."""
    app = _make_app(tmp_data_dir)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        openapi = await client.get("/openapi.json")
        assert openapi.status_code == 200
        body = openapi.json()
        assert body["openapi"] == "3.1.0"
        assert "/api/v1/memory/store" in body["paths"]
        assert "/api/v1/admin/graph/export" in body["paths"]

        atlas = await client.get("/atlas")
        assert atlas.status_code == 200
        assert "Temple Atlas" in atlas.text
        assert "temple.atlas.api_key" in atlas.text


@pytest.mark.asyncio
async def test_rest_memory_roundtrip(tmp_data_dir):
    """Store and retrieve memory through REST endpoints."""
    app = _make_app(tmp_data_dir)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        stored = await client.post(
            "/api/v1/memory/store",
            json={
                "content": "Temple supports REST compatibility mode",
                "tags": ["integration", "rest"],
                "metadata": {"source": "rest-test"},
            },
        )
        assert stored.status_code == 200
        assert stored.json()["content"] == "Temple supports REST compatibility mode"

        retrieved = await client.post(
            "/api/v1/memory/retrieve",
            json={"query": "REST compatibility", "n_results": 3},
        )
        assert retrieved.status_code == 200
        results = retrieved.json()
        assert len(results) >= 1
        assert results[0]["memory"]["metadata"]["source"] == "rest-test"


@pytest.mark.asyncio
async def test_rest_auth_guard(tmp_data_dir):
    """REST endpoints require bearer token when API key is configured."""
    app = _make_app(tmp_data_dir, api_key="secret-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthorized = await client.post(
            "/api/v1/memory/store",
            json={"content": "blocked"},
        )
        assert unauthorized.status_code == 401

        authorized = await client.post(
            "/api/v1/memory/store",
            headers={"Authorization": "Bearer secret-token"},
            json={"content": "allowed"},
        )
        assert authorized.status_code == 200

        denied_export = await client.get("/api/v1/admin/graph/export")
        assert denied_export.status_code == 401

        allowed_export = await client.get(
            "/api/v1/admin/graph/export",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert allowed_export.status_code == 200
        exported = allowed_export.json()
        assert exported["entity_count"] == 2
        assert exported["relation_count"] == 1


@pytest.mark.asyncio
async def test_rest_export_graph_limit_and_scope_validation(tmp_data_dir):
    """Graph export supports query params and validates bad limits."""
    app = _make_app(tmp_data_dir)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        exported = await client.get(
            "/api/v1/admin/graph/export",
            params={"scope": "project:temple", "limit": "1"},
        )
        assert exported.status_code == 200
        body = exported.json()
        assert body["scope"] == "project:temple"
        assert body["entity_count"] == 1

        with_memories = await client.get(
            "/api/v1/admin/graph/export",
            params={"include_memories": "1", "memory_limit": "1"},
        )
        assert with_memories.status_code == 200
        memory_body = with_memories.json()
        assert memory_body["memory_count"] == 1

        bad_limit = await client.get("/api/v1/admin/graph/export", params={"limit": "not-a-number"})
        assert bad_limit.status_code == 422

        bad_memory_limit = await client.get("/api/v1/admin/graph/export", params={"memory_limit": "NaN"})
        assert bad_memory_limit.status_code == 422


@pytest.mark.asyncio
async def test_rest_survey_and_relationship_endpoints(tmp_data_dir):
    """Survey submission/review/map routes are available and wired."""
    app = _make_app(tmp_data_dir)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        queued = await client.post(
            "/api/v1/surveys/submit",
            json={
                "survey_id": "pulse-1",
                "respondent_id": "lance",
                "response": "I work with Temple and use Azure for delivery.",
            },
        )
        assert queued.status_code == 200
        job = queued.json()
        assert job["status"] == "queued"
        assert job["job_id"]

        job_status = await client.get(f"/api/v1/surveys/jobs/{job['job_id']}")
        assert job_status.status_code == 200
        assert job_status.json()["job_id"] == job["job_id"]

        reviews = await client.get("/api/v1/surveys/reviews")
        assert reviews.status_code == 200
        assert len(reviews.json()) >= 1

        review = await client.post(
            "/api/v1/surveys/reviews/rev-1",
            json={"decision": "approve", "reviewer": "tester"},
        )
        assert review.status_code == 200
        assert review.json()["status"] == "approved"

        relation_map = await client.get(
            "/api/v1/relationship-map",
            params={"entity": "Lance", "depth": "2"},
        )
        assert relation_map.status_code == 200
        assert relation_map.json()["entity"] == "Lance"
