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

    def export_knowledge_graph(
        self,
        scope: str | None = None,
        limit: int = 10000,
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
        return {
            "entities": entities[:limit],
            "relations": relations,
            "entity_count": min(len(entities), limit),
            "relation_count": len(relations),
            "scope": scope or "all",
        }

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

        bad_limit = await client.get("/api/v1/admin/graph/export", params={"limit": "not-a-number"})
        assert bad_limit.status_code == 422
