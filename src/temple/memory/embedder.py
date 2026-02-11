"""Embedding generation using sentence-transformers with ONNX backend."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lazy-loaded models keyed by model name.
_models: dict[str, object] = {}


def _get_model(model_name: str = "BAAI/bge-base-en-v1.5"):
    """Lazy-load the sentence-transformers model with ONNX backend."""
    model = _models.get(model_name)
    if model is None:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Loading embedding model: {model_name}")
        model = SentenceTransformer(model_name, backend="onnx")
        _models[model_name] = model
        logger.info("Embedding model loaded successfully")
    return model


def embed_text(text: str, model_name: str = "BAAI/bge-base-en-v1.5") -> list[float]:
    """Generate an embedding vector for a single text string."""
    model = _get_model(model_name)
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_batch(texts: list[str], model_name: str = "BAAI/bge-base-en-v1.5") -> list[list[float]]:
    """Generate embedding vectors for a batch of texts."""
    if not texts:
        return []
    model = _get_model(model_name)
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()


def embedding_dimension(model_name: str = "BAAI/bge-base-en-v1.5") -> int:
    """Return the embedding dimension for the loaded model."""
    model = _get_model(model_name)
    return model.get_sentence_embedding_dimension()
