"""Tests for context hierarchy."""

import pytest

from temple.memory.context import ContextManager
from temple.models.context import ContextTier


def test_default_context():
    """Default context has only global scope."""
    ctx = ContextManager()
    scopes = ctx.get_active_scopes()
    assert len(scopes) == 1
    assert scopes[0].tier == ContextTier.GLOBAL


def test_set_project():
    """Setting project adds project scope."""
    ctx = ContextManager()
    ctx.set_project("myproject")

    scopes = ctx.get_active_scopes()
    assert len(scopes) == 2
    assert scopes[1].tier == ContextTier.PROJECT
    assert scopes[1].name == "myproject"


def test_set_session():
    """Setting session adds session scope."""
    ctx = ContextManager()
    ctx.set_session("abc123")

    scopes = ctx.get_active_scopes()
    assert len(scopes) == 2
    assert scopes[1].tier == ContextTier.SESSION


def test_full_hierarchy():
    """Setting both project and session gives three tiers."""
    ctx = ContextManager()
    ctx.set_project("myproject")
    ctx.set_session("session1")

    scopes = ctx.get_active_scopes()
    assert len(scopes) == 3
    assert scopes[0].tier == ContextTier.GLOBAL
    assert scopes[1].tier == ContextTier.PROJECT
    assert scopes[2].tier == ContextTier.SESSION


def test_collection_names():
    """Scopes produce correct collection names."""
    ctx = ContextManager()
    ctx.set_project("temple")
    ctx.set_session("s1")

    scopes = ctx.get_active_scopes()
    assert scopes[0].collection_name == "temple_global"
    assert scopes[1].collection_name == "temple_project_temple"
    assert scopes[2].collection_name == "temple_session_s1"


def test_clear_project():
    """Clearing project removes project scope."""
    ctx = ContextManager()
    ctx.set_project("myproject")
    ctx.set_project(None)

    scopes = ctx.get_active_scopes()
    assert len(scopes) == 1


def test_store_scope_default():
    """Default store scope is the highest active."""
    ctx = ContextManager()
    ctx.set_project("proj")

    scope = ctx.get_store_scope()
    assert scope.tier == ContextTier.PROJECT


def test_store_scope_explicit():
    """Explicit scope overrides default."""
    ctx = ContextManager()
    scope = ctx.get_store_scope("session:test")
    assert scope.tier == ContextTier.SESSION
    assert scope.name == "test"


def test_parse_scope_invalid_raises():
    """Invalid scope strings are rejected."""
    ctx = ContextManager()
    with pytest.raises(ValueError):
        ctx.parse_scope("invalid-scope")
    with pytest.raises(ValueError):
        ctx.parse_scope("project:")
    with pytest.raises(ValueError):
        ctx.parse_scope("session:")
