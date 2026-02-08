"""Tests for pydantic models."""

from temple.models.context import ActiveContext, ContextScope, ContextTier
from temple.models.memory import MemoryEntry, MemorySearchResult
from temple.models.entity import Entity, Observation
from temple.models.relation import Relation


def test_memory_entry():
    """MemoryEntry creates with defaults."""
    entry = MemoryEntry(
        id="abc",
        content="test",
        content_hash="abc",
    )
    assert entry.tags == []
    assert entry.scope == "global"
    assert entry.created_at is not None


def test_memory_search_result():
    """MemorySearchResult wraps entry with score."""
    entry = MemoryEntry(id="x", content="test", content_hash="x")
    result = MemorySearchResult(memory=entry, score=0.95)
    assert result.score == 0.95
    assert result.tier == "global"


def test_context_scope_collection_names():
    """ContextScope generates correct collection names."""
    assert ContextScope(tier=ContextTier.GLOBAL).collection_name == "temple_global"
    assert ContextScope(tier=ContextTier.PROJECT, name="foo").collection_name == "temple_project_foo"
    assert ContextScope(tier=ContextTier.SESSION, name="s1").collection_name == "temple_session_s1"


def test_active_context_scopes():
    """ActiveContext builds correct scope list."""
    ctx = ActiveContext(project="proj", session="s1")
    scopes = ctx.active_scopes
    assert len(scopes) == 3
    assert scopes[0].tier == ContextTier.GLOBAL
    assert scopes[1].tier == ContextTier.PROJECT
    assert scopes[2].tier == ContextTier.SESSION


def test_entity_model():
    """Entity model with observations."""
    entity = Entity(
        name="Python",
        entity_type="language",
        observations=[Observation(content="High-level")],
    )
    assert entity.name == "Python"
    assert len(entity.observations) == 1


def test_relation_model():
    """Relation model."""
    rel = Relation(source="A", target="B", relation_type="uses")
    assert rel.source == "A"
    assert rel.scope == "global"
