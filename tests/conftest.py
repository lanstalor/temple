"""Shared test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest

from temple.config import Settings


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Create a temporary data directory."""
    (tmp_path / "chromadb").mkdir()
    # Don't create kuzu dir - Kuzu manages it
    (tmp_path / "audit").mkdir()
    return tmp_path


@pytest.fixture
def test_settings(tmp_data_dir):
    """Create settings pointing to temp directories."""
    return Settings(
        chroma_mode="embedded",
        data_dir=tmp_data_dir,
        kuzu_dir=tmp_data_dir / "kuzu",
        audit_dir=tmp_data_dir / "audit",
        embedding_model="BAAI/bge-base-en-v1.5",
    )
