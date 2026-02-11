"""Tests for combined MCP + REST runtime."""

from typing import Any

import httpx
import pytest

from temple.combined_server import create_app
from temple.config import Settings
from temple.models.memory import MemoryEntry, MemorySearchResult


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

    def compact_audit_log(self, scope: str = "global", keep: int = 1000) -> int:
        return 0


@pytest.mark.asyncio
async def test_combined_server_exposes_mcp_and_rest_routes():
    """Combined app serves both MCP and REST paths."""
    app = create_app(broker=_FakeBroker(), config=Settings(api_key=""))
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in paths
    assert "/api/v1/memory/store" in paths
    assert "/openapi.json" in paths

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        assert health.status_code == 200

        stored = await client.post("/api/v1/memory/store", json={"content": "combined mode"})
        assert stored.status_code == 200


@pytest.mark.asyncio
async def test_combined_server_rest_auth_guard():
    """REST auth still works in combined mode when API key is set."""
    app = create_app(broker=_FakeBroker(), config=Settings(api_key="abc123"))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthorized = await client.post("/api/v1/memory/store", json={"content": "blocked"})
        assert unauthorized.status_code == 401

        authorized = await client.post(
            "/api/v1/memory/store",
            headers={"Authorization": "Bearer abc123"},
            json={"content": "allowed"},
        )
        assert authorized.status_code == 200


@pytest.mark.asyncio
async def test_combined_server_oauth_protected_resource_compatibility_routes():
    """Expose compatibility metadata endpoints for MCP OAuth discovery clients."""
    app = create_app(
        broker=_FakeBroker(),
        config=Settings(
            api_key="abc123",
            base_url="https://temple.tython.ca",
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        expected = {
            "resource": "https://temple.tython.ca/mcp",
            "authorization_servers": ["https://temple.tython.ca/"],
            "scopes_supported": ["temple"],
            "bearer_methods_supported": ["header"],
        }

        root = await client.get("/.well-known/oauth-protected-resource")
        assert root.status_code == 200
        assert root.json() == expected
        assert root.headers["cache-control"] == "no-store"

        alias = await client.get("/mcp/.well-known/oauth-protected-resource")
        assert alias.status_code == 200
        assert alias.json() == expected

        with_abs_resource = await client.get(
            "/.well-known/oauth-protected-resource",
            params={"resource": "https://temple.tython.ca/mcp"},
        )
        assert with_abs_resource.status_code == 200

        with_rel_resource = await client.get(
            "/.well-known/oauth-protected-resource",
            params={"resource": "/mcp"},
        )
        assert with_rel_resource.status_code == 200

        mismatched_resource = await client.get(
            "/.well-known/oauth-protected-resource",
            params={"resource": "https://example.com/not-mcp"},
        )
        assert mismatched_resource.status_code == 404


@pytest.mark.asyncio
async def test_combined_server_oauth_protected_resource_hidden_when_auth_disabled():
    """Do not advertise OAuth protected-resource metadata when auth is off."""
    app = create_app(broker=_FakeBroker(), config=Settings(api_key=""))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root = await client.get("/.well-known/oauth-protected-resource")
        assert root.status_code == 404

        alias = await client.get("/mcp/.well-known/oauth-protected-resource")
        assert alias.status_code == 404
