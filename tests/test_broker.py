"""Tests for memory broker (integration test - requires embedding model)."""

from datetime import datetime, timedelta, timezone

import pytest

from temple.config import Settings
from temple.memory.broker import MemoryBroker


@pytest.fixture
def broker(tmp_data_dir):
    """Create a broker with temp directories."""
    settings = Settings(
        chroma_mode="embedded",
        data_dir=tmp_data_dir,
        kuzu_dir=tmp_data_dir / "kuzu",
        audit_dir=tmp_data_dir / "audit",
    )
    return MemoryBroker(settings)


def test_store_and_retrieve(broker):
    """Store a memory and retrieve it."""
    entry = broker.store_memory(
        "Python is a great programming language",
        tags=["programming"],
        metadata={"source": "unit-test"},
    )
    assert entry.content == "Python is a great programming language"
    assert entry.tags == ["programming"]
    assert entry.metadata == {"source": "unit-test"}

    results = broker.retrieve_memory("programming language")
    assert len(results) > 0
    assert results[0].memory.content == "Python is a great programming language"
    assert results[0].memory.metadata == {"source": "unit-test"}


def test_dedup(broker):
    """Storing duplicate content returns existing entry."""
    entry1 = broker.store_memory("Duplicate test content")
    entry2 = broker.store_memory("Duplicate test content")
    assert entry1.id == entry2.id


def test_delete_memory(broker):
    """Delete a memory."""
    entry = broker.store_memory("To be deleted")
    deleted = broker.delete_memory(entry.id)
    assert deleted is True
    assert broker.delete_memory(entry.id) is False


def test_context_scoping(broker):
    """Memories respect context scoping."""
    # Store in global
    broker.store_memory("Global fact", scope="global")

    # Switch to project
    broker.set_context(project="proj1")
    broker.store_memory("Project fact")

    # Retrieve from project context (should get both)
    results = broker.retrieve_memory("fact", n_results=10)
    assert len(results) >= 1

    # Global context should not see project memories
    broker.set_context(project="")
    results_global = broker.retrieve_memory("Project fact", scope="global")
    contents = [r.memory.content for r in results_global]
    assert "Project fact" not in contents


def test_entity_crud(broker):
    """Create, read, update, delete entities."""
    broker.create_entities([
        {"name": "TestEntity", "entity_type": "test", "observations": ["obs1"]},
    ])

    entity = broker.get_entity("TestEntity")
    assert entity is not None
    assert entity["entity_type"] == "test"

    broker.update_entity("TestEntity", entity_type="updated_test")
    entity = broker.get_entity("TestEntity")
    assert entity["entity_type"] == "updated_test"

    broker.delete_entities(["TestEntity"])
    assert broker.get_entity("TestEntity") is None


def test_relations(broker):
    """Create and query relations."""
    broker.create_entities([
        {"name": "A", "entity_type": "node"},
        {"name": "B", "entity_type": "node"},
    ])

    broker.create_relations([
        {"source": "A", "target": "B", "relation_type": "connects_to"},
    ])

    rels = broker.get_relations("A", direction="out")
    assert len(rels) == 1
    assert rels[0]["target"] == "B"


def test_observations(broker):
    """Add and remove observations."""
    broker.create_entities([
        {"name": "TestNode", "entity_type": "test"},
    ])

    broker.add_observations("TestNode", ["obs1", "obs2"])
    entity = broker.get_entity("TestNode")
    assert "obs1" in entity["observations"]

    broker.remove_observations("TestNode", ["obs1"])
    entity = broker.get_entity("TestNode")
    assert "obs1" not in entity["observations"]
    assert "obs2" in entity["observations"]


def test_stats(broker):
    """Get system stats."""
    stats = broker.get_stats()
    assert "total_memories" in stats
    assert "entity_count" in stats
    assert stats["graph_schema"] == "v2"
    assert "active_context" in stats


def test_health_check(broker):
    """Health check returns healthy."""
    health = broker.health_check()
    assert health["status"] == "healthy"
    assert health["graph_schema"] == "v2"


def test_search_memories_by_tags_only(broker):
    """Tag-only search works without semantic query."""
    broker.store_memory("Tagged alpha", tags=["alpha", "common"])
    broker.store_memory("Tagged beta", tags=["beta", "common"])

    results = broker.search_memories(tags=["alpha"])
    assert len(results) == 1
    assert results[0].memory.content == "Tagged alpha"


def test_search_memories_requires_all_tags(broker):
    """Tag filters match all requested tags."""
    broker.store_memory("Only one tag", tags=["alpha"])
    broker.store_memory("Two tags", tags=["alpha", "beta"])

    results = broker.search_memories(tags=["alpha", "beta"])
    assert len(results) == 1
    assert results[0].memory.content == "Two tags"


def test_session_ttl_expiry(tmp_data_dir):
    """Expired session collections are cleaned up from vector and graph stores."""
    settings = Settings(
        chroma_mode="embedded",
        data_dir=tmp_data_dir,
        kuzu_dir=tmp_data_dir / "kuzu",
        audit_dir=tmp_data_dir / "audit",
        session_ttl=1,
    )
    broker = MemoryBroker(settings)

    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    broker.vector.add(
        collection_name="temple_session_expired",
        ids=["old-memory"],
        embeddings=[[0.01] * 768],
        documents=["old session memory"],
        metadatas=[{
            "content_hash": "old-memory",
            "scope": "session:expired",
            "created_at": expired_at,
            "updated_at": expired_at,
            "tags": "[]",
            "metadata": "{}",
        }],
    )
    broker.graph.create_entity("OldSessionEntity", "test", scope="session:expired")

    assert "temple_session_expired" in broker.vector.list_collections()
    _ = broker.list_sessions()
    assert "temple_session_expired" not in broker.vector.list_collections()
    assert broker.graph.entity_count(scope="session:expired") == 0


def test_graph_schema_status_and_migration_noop(broker):
    """Current schema reports v2 and migration is a no-op."""
    status = broker.get_graph_schema_status()
    assert status["schema_version"] == "v2"
    assert status["legacy_schema_detected"] is False

    migration = broker.migrate_graph_schema()
    assert migration["migrated"] is False
    assert migration["reason"] == "already_v2"
