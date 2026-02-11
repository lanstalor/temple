"""Tests for vector store."""

from temple.memory.vector_store import VectorStore


def test_add_and_query(tmp_path):
    """Add a document and query it back."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))

    store.add(
        collection_name="test",
        ids=["doc1"],
        embeddings=[[0.1] * 768],
        documents=["Hello world"],
        metadatas=[{"key": "value"}],
    )

    assert store.count("test") == 1

    results = store.query(
        collection_name="test",
        query_embedding=[0.1] * 768,
        n_results=1,
    )

    assert results["ids"][0][0] == "doc1"
    assert results["documents"][0][0] == "Hello world"


def test_delete(tmp_path):
    """Delete a document."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))

    store.add(
        collection_name="test",
        ids=["doc1"],
        embeddings=[[0.1] * 768],
        documents=["To be deleted"],
    )
    assert store.count("test") == 1

    store.delete("test", ids=["doc1"])
    assert store.count("test") == 0


def test_list_collections(tmp_path):
    """List collections."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))

    store.get_or_create_collection("col1")
    store.get_or_create_collection("col2")

    names = store.list_collections()
    assert "col1" in names
    assert "col2" in names


def test_heartbeat(tmp_path):
    """Heartbeat returns True for embedded mode."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))
    assert store.heartbeat() is True


def test_upsert(tmp_path):
    """Upserting same ID updates the document."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))

    store.add(
        collection_name="test",
        ids=["doc1"],
        embeddings=[[0.1] * 768],
        documents=["Original"],
    )
    store.add(
        collection_name="test",
        ids=["doc1"],
        embeddings=[[0.2] * 768],
        documents=["Updated"],
    )

    assert store.count("test") == 1
    result = store.get("test", ids=["doc1"])
    assert result["documents"][0] == "Updated"


def test_query_empty_collection(tmp_path):
    """Querying empty collection returns empty results."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))

    results = store.query(
        collection_name="empty",
        query_embedding=[0.1] * 768,
        n_results=5,
    )

    assert results["ids"] == [[]]


def test_get_all_with_pagination(tmp_path):
    """Read collection contents using paginated get_all."""
    store = VectorStore(mode="embedded", persist_dir=str(tmp_path / "chroma"))
    store.add(
        collection_name="test",
        ids=["a", "b", "c"],
        embeddings=[[0.1] * 768, [0.2] * 768, [0.3] * 768],
        documents=["doc-a", "doc-b", "doc-c"],
    )

    first_page = store.get_all("test", limit=2, offset=0)
    second_page = store.get_all("test", limit=2, offset=2)

    assert len(first_page["ids"]) == 2
    assert len(second_page["ids"]) == 1
