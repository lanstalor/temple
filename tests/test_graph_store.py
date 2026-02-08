"""Tests for graph store."""

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
    gs.delete_entity("Python")
    assert gs.get_entity("Python") is None


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


def test_delete_relation(tmp_path):
    """Delete a relation."""
    gs = GraphStore(tmp_path / "kuzu")
    gs.create_entity("A", "node")
    gs.create_entity("B", "node")
    gs.create_relation("A", "B", "links_to")

    gs.delete_relation("A", "B", "links_to")
    rels = gs.get_relations("A", direction="out")
    assert len(rels) == 0


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
