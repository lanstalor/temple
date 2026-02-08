FROM python:3.12-slim

WORKDIR /app

# Install system deps for ONNX runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies (no venv needed in container)
RUN uv pip install --system --no-cache ".[dev]"

# Pre-download the embedding model during build
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5', backend='onnx')"

# Create data directories (NOT kuzu - Kuzu manages its own directory)
RUN mkdir -p /app/data/{chromadb,audit,models}

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

CMD ["python", "-m", "temple"]
