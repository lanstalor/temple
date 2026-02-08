"""Tests for content hashing."""

from temple.memory.hashing import content_hash


def test_content_hash_deterministic():
    """Same content produces same hash."""
    h1 = content_hash("hello world")
    h2 = content_hash("hello world")
    assert h1 == h2


def test_content_hash_different():
    """Different content produces different hash."""
    h1 = content_hash("hello")
    h2 = content_hash("world")
    assert h1 != h2


def test_content_hash_is_sha256():
    """Hash is a valid SHA-256 hex string."""
    h = content_hash("test")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
