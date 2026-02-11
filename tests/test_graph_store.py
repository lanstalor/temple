"""Tests for graph store."""

import json

import kuzu

from temple.memory.graph_store import GraphStore


def test_create_and_get_entity(tmp_path):
    """Create an entity and get it back."""
    gs = GraphStore(tmp_path / "kuzu")

    created = gs.create_entity("Python", "language", ["High-level language"])
    assert created is True

    entity = gs.get_entity("Python")
    assert entity is not None
    assert entity["name"] == "Python"
    assert entity["entity_type"] == "language"
    assert "High-level language" in entity["observations"]


def test_create_duplicate_entity(tmp_path):
    """Creating duplicate entity returns False."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language")
    result = gs.create_entity("Python", "language")
    assert result is False


def test_delete_entity(tmp_path):
    """Delete an entity."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language")
    assert gs.delete_entity("Python") is True
    assert gs.get_entity("Python") is None
    assert gs.delete_entity("Python") is False


def test_update_entity(tmp_path):
    """Update entity fields."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language")
    gs.update_entity("Python", entity_type="programming_language")

    entity = gs.get_entity("Python")
    assert entity["entity_type"] == "programming_language"


def test_create_and_get_relation(tmp_path):
    """Create a relation between two entities."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language")
    gs.create_entity("FastAPI", "framework")

    created = gs.create_relation("Python", "FastAPI", "powers")
    assert created is True

    rels = gs.get_relations("Python", direction="out")
    assert len(rels) == 1
    assert rels[0]["target"] == "FastAPI"
    assert rels[0]["relation_type"] == "powers"
    assert gs.create_relation("Python", "FastAPI", "powers") is False


def test_delete_relation(tmp_path):
    """Delete a relation."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("A", "node")
    gs.create_entity("B", "node")
    gs.create_relation("A", "B", "links_to")

    assert gs.delete_relation("A", "B", "links_to") is True
    rels = gs.get_relations("A", direction="out")
    assert len(rels) == 0
    assert gs.delete_relation("A", "B", "links_to") is False


def test_search_entities(tmp_path):
    """Search entities by type."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language")
    gs.create_entity("JavaScript", "language")
    gs.create_entity("FastAPI", "framework")

    results = gs.search_entities(entity_type="language")
    assert len(results) == 2
    names = [r["name"] for r in results]
    assert "Python" in names
    assert "JavaScript" in names


def test_add_observations(tmp_path):
    """Add observations to an entity."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language", ["Created by Guido"])
    gs.add_observations("Python", ["Version 3.12", "Popular for AI"])

    entity = gs.get_entity("Python")
    assert len(entity["observations"]) == 3
    assert "Version 3.12" in entity["observations"]


def test_remove_observations(tmp_path):
    """Remove specific observations."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("Python", "language", ["Fact 1", "Fact 2", "Fact 3"])
    gs.remove_observations("Python", ["Fact 2"])

    entity = gs.get_entity("Python")
    assert len(entity["observations"]) == 2
    assert "Fact 2" not in entity["observations"]


def test_entity_count(tmp_path):
    """Count entities."""
    gs = GraphStore(tmp_path / "kuzu")
    assert gs.entity_count() == 0

    gs.create_entity("A", "node")
    gs.create_entity("B", "node")
    assert gs.entity_count() == 2


def test_relation_count(tmp_path):
    """Count relations."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("A", "node")
    gs.create_entity("B", "node")
    assert gs.relation_count() == 0

    gs.create_relation("A", "B", "links_to")
    assert gs.relation_count() == 1


def test_create_relation_requires_existing_entities(tmp_path):
    """Relation creation fails when source or target is missing."""
    gs = GraphStore(tmp_path / "kuzu")
    assert gs.create_relation("MissingA", "MissingB", "links_to") is False


def test_scoped_duplicate_entity_names_supported(tmp_path):
    """Same entity name can exist in different scopes."""
    gs = GraphStore(tmp_path / "kuzu")
    assert gs.create_entity("Python", "language", scope="global") is True
    assert gs.create_entity("Python", "language", scope="project:temple") is True

    global_entity = gs.get_entity("Python", scope="global")
    project_entity = gs.get_entity("Python", scope="project:temple")
    assert global_entity is not None
    assert project_entity is not None
    assert global_entity["scope"] == "global"
    assert project_entity["scope"] == "project:temple"


def test_migrate_legacy_schema(tmp_path):
    """Legacy graph schema migrates to v2 and preserves data."""
    db_path = tmp_path / "kuzu"
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    conn.execute(
        "CREATE NODE TABLE IF NOT EXISTS Entity("
        "name STRING, entity_type STRING, observations STRING, scope STRING, "
        "created_at STRING, updated_at STRING, PRIMARY KEY(name))"
    )
    conn.execute(
        "CREATE REL TABLE IF NOT EXISTS Relation("
        "FROM Entity TO Entity, relation_type STRING, scope STRING, created_at STRING)"
    )
    now = "2026-02-11T00:00:00+00:00"
    conn.execute(
        "CREATE (e:Entity {name: $name, entity_type: $type, observations: $obs, scope: $scope, created_at: $now, updated_at: $now})",
        {"name": "A", "type": "node", "obs": "", "scope": "global", "now": now},
    )
    conn.execute(
        "CREATE (e:Entity {name: $name, entity_type: $type, observations: $obs, scope: $scope, created_at: $now, updated_at: $now})",
        {"name": "B", "type": "node", "obs": "", "scope": "global", "now": now},
    )
    conn.execute(
        "MATCH (a:Entity), (b:Entity) WHERE a.name = $src AND b.name = $tgt "
        "CREATE (a)-[:Relation {relation_type: $rtype, scope: $scope, created_at: $now}]->(b)",
        {"src": "A", "tgt": "B", "rtype": "links_to", "scope": "global", "now": now},
    )
    del conn
    del db

    gs = GraphStore(db_path)
    assert gs.is_legacy_schema() is True

    backup_path = tmp_path / "legacy_snapshot.json"
    result = gs.migrate_legacy_schema(backup_path=backup_path)
    assert result["migrated"] is True
    assert result["schema_version"] == "v2"
    assert result["entities_migrated"] == 2
    assert result["relations_migrated"] == 1
    assert backup_path.exists()

    snapshot = json.loads(backup_path.read_text())
    assert snapshot["schema"] == "legacy"
    assert snapshot["entity_count"] == 2
    assert snapshot["relation_count"] == 1

    assert gs.schema_version == "v2"
    assert gs.entity_count() == 2
    assert gs.relation_count() == 1
    assert gs.create_entity("A", "node", scope="project:proj1") is True
