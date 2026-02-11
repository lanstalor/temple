# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Temple

Temple is a self-hosted memory platform for AI agents. It exposes persistent memory (vector + knowledge graph) through two surfaces on one process: **MCP** (`/mcp`) for Claude/Copilot/MCP-native clients, and **REST** (`/api/v1`) for ChatGPT Actions, LangChain, and custom apps. Both share the same `MemoryBroker` and data plane.

## Commands

```bash
# Install dependencies
uv sync --dev

# Run server locally (defaults to combined MCP+REST mode on :8100)
uv run python -m temple

# Run tests (92 tests, pytest-asyncio with asyncio_mode=auto)
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_broker.py -v

# Run a single test by name
uv run pytest tests/test_broker.py -k "test_store_memory" -v

# Docker build and run
docker compose -f docker/docker-compose.yml up -d --build

# Health check
curl http://localhost:8100/health
```

## Architecture

### Entry point and runtime dispatch

`src/temple/__main__.py` dispatches based on `TEMPLE_RUNTIME_MODE`:
- `combined` (default) → `combined_server.py`: merges MCP (Starlette from FastMCP) and REST (Starlette) route tables into one ASGI app served by uvicorn
- `mcp` → `server.py`: MCP-only via FastMCP (supports streamable-http or stdio transport)
- `rest` → `rest_server.py`: REST-only Starlette app

### Core components

**`MemoryBroker`** (`memory/broker.py`) is the central orchestrator. It owns all subsystems and is the only thing tools and REST handlers call. One broker instance is shared across MCP and REST in combined mode.

**Storage backends** (all under `memory/`):
- `VectorStore` → ChromaDB (embedded or HTTP client mode)
- `GraphStore` → Kuzu embedded graph database
- `AuditLog` → append-only JSONL files
- `ContextManager` → in-memory scope state (global/project/session)
- `embedder.py` → sentence-transformers with ONNX backend

**MCP tools** (`tools/`): Each file exports a `register_*_tools(mcp, broker)` function that decorates functions with `@mcp.tool()`. Tool groups: memory (5), entity (5), relation (4), observation (2), context (4), admin (6).

**REST server** (`rest_server.py`): Starlette routes with Pydantic request models. Also serves `/openapi.json`, `/docs` (Swagger UI), and `/atlas` (D3.js graph explorer with inline HTML/JS/CSS).

### Context hierarchy

Three scopes with strict ranking: **session > project > global**. On retrieval, all active scopes are searched and results merged by precedence then similarity score. On storage, content goes to the most specific active scope. Collections are named `temple_global`, `temple_project_<name>`, `temple_session_<id>`.

### Authentication

Dual auth when `TEMPLE_API_KEY` is set: static Bearer token checked first, then OAuth 2.1 tokens via `TempleAuthProvider` (extends FastMCP's `InMemoryOAuthProvider`). `/health` bypasses auth. When `TEMPLE_API_KEY` is empty, auth is disabled.

**Atlas Basic Auth**: The `/atlas` UI is gated by HTTP Basic Auth when `TEMPLE_ATLAS_USER` and `TEMPLE_ATLAS_PASS` are set. Valid Atlas Basic Auth credentials also bypass the Bearer token requirement on API routes, so the browser's automatic credential forwarding lets Atlas fetch graph data without a separate API key. When both vars are empty, Atlas is open (local dev).

### Ingest and enrichment pipeline

Background thread (`_ingest_worker_loop`) processes ingested content of any type (email, document, chat, meeting note, ticket, survey, note). Extraction uses LLM (Anthropic Claude) when `TEMPLE_LLM_API_KEY` is configured, falling back to regex/keyword heuristics. Confidence policy: auto-creates high-confidence (≥0.80) relations, queues medium-confidence (≥0.60) for human review. State is persisted to `data/audit/ingest_state.json` and resumed on restart. Legacy `survey_state.json` is auto-migrated on first load.

**LLM extractor** (`memory/llm_extractor.py`): Separate module following `embedder.py` lazy-load pattern. Provides `extract(text, actor_id, settings)` → `ExtractionResult` with entities, relations, extraction_method, and optional LLM usage/error data. Heuristic helpers (`_extract_entity_candidates`, `_infer_relation_candidates`, `_normalize_entity_name`, `_infer_entity_type`) live here.

**Survey routes** (`/api/v1/surveys/*`): Backward-compatible wrappers that delegate to the generalized ingest methods. New routes at `/api/v1/ingest/*` are the canonical API.

## Configuration

All config via `TEMPLE_`-prefixed env vars, loaded by Pydantic Settings into `temple.config.Settings`. See `.env.example` for the full list.

## Testing

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. Shared fixtures in `tests/conftest.py` provide `tmp_data_dir` and `test_settings` that point to temp directories with embedded ChromaDB (no Docker needed for tests).

## Key technical gotchas

- **Kuzu**: Database path must NOT pre-exist as a directory. Kuzu creates its own dir. Only ensure the parent exists.
- **FastMCP v2.14**: Uses `instructions=` (not `description=`) in constructor. Auth via `auth=` parameter.
- **ChromaDB in Docker**: Data stored at `/data` inside container, volume mount is `../data/chromadb:/data`.
- **Docker compose env**: `env_file` loads vars into container; `environment:` with `${VAR}` resolves from host shell. Don't use both for the same variable.
- **ONNX embeddings**: Requires both `onnxruntime` and `optimum[onnxruntime]` packages.
