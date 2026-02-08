"""SHA-256 content hashing for deduplication."""

from __future__ import annotations

import hashlib


def content_hash(text: str) -> str:
    """Generate a SHA-256 hash of the given text for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
