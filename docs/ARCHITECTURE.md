# Temple: Context-Aware Memory Broker for AI Agents

## Context

The goal is to deploy a self-hosted, CPU-friendly memory broker that provides persistent memory to AI agents via MCP (Model Context Protocol). The system runs embedding generation, vector search, and knowledge graph operations locally, while cloud LLMs connect to it for intelligence. This follows the architecture described in the research artifact on context-aware memory broker systems.

**Environment:**
- **Host (tatooine):** Ubuntu 24.04.3 VM at 192.168.3.233, 1 vCPU (i7-14700K), 11GB RAM, 66GB free disk. Git installed, Tailscale active.
- **Unraid host:** 192.168.3.99 - available for future migration if more CPU/resources needed.
- **Strategy:** Develop AND deploy on tatooine. Install Docker here, run everything locally. No SSH-wrapping complexity. Containerized design means migration to Unraid (or anywhere) is a trivial `docker compose up` later.
- **Git remote:** github.com/lanstalor/temple

---

## Architecture

```
tatooine (192.168.3.233) — all-in-one dev + deploy
Tailscale: 100.79.174.122

┌─────────────────────────────────────────────┐
│  Docker Compose                             │
│                                             │
│  [temple-memory :8100/mcp]                  │
│    MCP server + ONNX embedder + Kuzu graph  │
│         │                                   │
│         └──► [temple-chromadb :8000]         │
│              vector DB (internal network)    │
└─────────────────────────────────────────────┘
         ▲
         │  Streamable HTTP
         │
[Claude Code / Claude Desktop / any MCP client]
  via LAN (192.168.3.233:8100)
  via Tailscale (100.79.174.122:8100)
  via Cloudflare Tunnel (https://temple.tython.ca/mcp)
```

**3 key design choices:**
1. **Embedding inside MCP server** (not separate TEI container) - ONNX-quantized bge-base-en-v1.5, ~20-40ms/embedding on CPU. Simpler, fewer containers, adequate for personal use.
2. **ChromaDB as separate container** - manages its own HNSW index, WAL, compaction. Independent restarts/upgrades.
3. **Kuzu embedded in MCP server** (not separate container) - zero network overhead, in-process graph queries.
4. **Everything on tatooine** - no SSH wrapping, direct Docker access, simpler debugging. Migration to Unraid host is trivial later (just `docker compose up` on new machine).

---

## Project Structure

```
/home/lans/temple/
├── pyproject.toml                    # Python project (uv)
├── .env.example / .env               # Configuration
├── docs/
│   └── ARCHITECTURE.md               # This file
├── docker/
│   ├── Dockerfile                    # MCP server image
│   ├── docker-compose.yml            # Production stack
│   ├── docker-compose.dev.yml        # Dev overrides (port exposure, debug logging)
│   └── scripts/
│       └── backup.sh                 # ChromaDB + Kuzu + JSONL backup
├── src/temple/
│   ├── server.py                     # FastMCP entry point (Streamable HTTP)
│   ├── config.py                     # Pydantic settings from env vars
│   ├── tools/
│   │   ├── memory_tools.py           # store_memory, retrieve_memory, delete_memory, recall, search
│   │   ├── entity_tools.py           # create/update/delete/get/search entities
│   │   ├── relation_tools.py         # create/delete relations, find_path
│   │   ├── observation_tools.py      # add/remove observations on entities
│   │   ├── context_tools.py          # set/get context, list projects/sessions
│   │   └── admin_tools.py            # stats, reindex, export, compact
│   ├── memory/
│   │   ├── broker.py                 # Central orchestrator (coordinates all subsystems)
│   │   ├── embedder.py               # ONNX sentence-transformers (bge-base-en-v1.5)
│   │   ├── vector_store.py           # ChromaDB client (embedded for dev, HTTP for prod)
│   │   ├── graph_store.py            # Kuzu embedded graph DB
│   │   ├── audit_log.py              # JSONL append-only audit trail
│   │   ├── context.py                # Three-tier context hierarchy logic
│   │   └── hashing.py                # SHA-256 content dedup
│   └── models/
│       ├── entity.py                 # Entity, Observation pydantic models
│       ├── relation.py               # Relation model
│       ├── memory.py                 # MemoryEntry, MemorySearchResult
│       └── context.py                # ContextTier, ContextScope, ActiveContext
├── tests/                            # pytest suite (unit + integration)
└── data/                             # Runtime data (gitignored)
    ├── chromadb/
    ├── graph/kuzu/
    └── audit/
```

---

## Three-Tier Context Hierarchy

| Tier | Loaded when | Precedence | Storage | TTL |
|------|-------------|------------|---------|-----|
| **Global** | Always | Lowest | `temple_global` collection | None |
| **Project** | When project active | Medium | `temple_project_<name>` collection | None |
| **Session** | When session active | Highest | `temple_session_<id>` collection | 24h default |

Retrieval searches all active tiers, results ranked: session > project > global, then by cosine similarity.

---

## MCP Tools Summary (24 total)

**Memory** (5 tools): `store_memory`, `retrieve_memory`, `recall_memory`, `search_memories`, `delete_memory`
**Entities** (5 tools): `create_entities`, `update_entity`, `delete_entities`, `get_entity`, `search_entities`
**Relations** (4 tools): `create_relations`, `delete_relations`, `get_relations`, `find_path`
**Observations** (2 tools): `add_observations`, `remove_observations`
**Context** (4 tools): `set_context`, `get_context`, `list_projects`, `list_sessions`
**Admin** (4 tools): `get_stats`, `reindex`, `export_knowledge_graph`, `compact_audit_log`

---

## Phased Implementation

### Phase 1: Foundation (MVP) ✅

1. Install Docker on tatooine, configure git (user.name/email), init repo, push to github.com/lanstalor/temple
2. Set up `pyproject.toml` with uv, install all deps
3. Build configuration system (`config.py` with Pydantic settings, env var overrides)
4. Build embedder module (ONNX bge-base-en-v1.5, async wrapper)
5. Build vector store module (ChromaDB, dual-mode: embedded for dev / HTTP for Docker)
6. Build content hasher (SHA-256 dedup)
7. Build audit log (JSONL append writer with scoped files)
8. Build memory broker (orchestrator: store, retrieve, delete - global context only)
9. Build MCP server with `store_memory`, `retrieve_memory`, `delete_memory` tools
10. Write unit tests for each module
11. Build Dockerfile + docker-compose.yml, `docker compose up`, verify end-to-end locally

**Deliverable:** Working MCP server on tatooine - store and retrieve memories via any MCP client.

### Phase 2: Knowledge Graph + Context ✅

1. Build graph store (Kuzu: entity/relation CRUD, path finding, neighborhood queries)
2. Build context hierarchy (ContextScope, ActiveContext, tier resolution, precedence)
3. Add entity, relation, observation, and context tools
4. Update broker for multi-scope retrieval with precedence ordering
5. Integration tests for graph + vector + context interplay
6. Update Docker volumes for Kuzu persistence

**Deliverable:** Full knowledge graph with context switching across tiers.

### Phase 3: Production Hardening

1. Add admin tools (stats, reindex, export, compact) ✅
2. Add `recall_memory` (natural language) and `search_memories` (text/tag) ✅
3. Memory lifecycle (AUDN cycle: auto-detect add vs update vs delete vs no-op)
4. Session TTL auto-expiry
5. Backup script (ChromaDB + Kuzu + JSONL, local + optional offsite)
6. Health monitoring, structured logging

### Phase 4: Future Enhancements

- Migration to Unraid host for more CPU/resources if needed
- Web dashboard for memory visualization
- TEI container migration if throughput needed
- Hybrid retrieval (BM25 + semantic + graph fusion)
- Multi-user namespace isolation

---

## Docker Compose

Two containers on tatooine:

| Container | Image | Resources | Ports | Volumes |
|-----------|-------|-----------|-------|---------|
| `temple-memory` | Custom (Python 3.12-slim) | 3GB RAM, 1 CPU | 8100 (MCP) | data/graph/, data/audit/ |
| `temple-chromadb` | chromadb/chroma:latest | 1GB RAM, 0.5 CPU | 8000 (internal only) | data/chromadb/ |

All persistent data lives in `/home/lans/temple/data/` (gitignored). For future Unraid migration, just remap volumes to `/mnt/cache/appdata/temple/`.

---

## Key Dependencies

```
fastmcp>=2.0          # MCP server framework (Streamable HTTP)
chromadb>=0.5         # Vector database
sentence-transformers>=3.0  # Embedding generation
onnxruntime>=1.18     # ONNX inference (CPU)
optimum[onnxruntime]>=1.19  # ONNX model export/loading
kuzu>=0.7             # Embedded graph database
pydantic>=2.0         # Data models
pydantic-settings>=2.0  # Config from env vars
```

---

## Key Technical Notes

- **Kuzu v0.11+**: Database path must NOT pre-exist as a directory. Kuzu creates its own dir. Mount the parent volume instead (e.g., `data/graph:/app/data/graph` with `TEMPLE_KUZU_DIR=/app/data/graph/kuzu`).
- **FastMCP v2.14**: Uses `instructions=` not `description=` in constructor. Run method uses `transport="streamable-http"`.
- **ChromaDB chroma:latest**: Data stored at `/data` inside container (not `/chroma/chroma`). Volume mount: `../data/chromadb:/data`.

---

## Connectivity

| Method | URL | Use case |
|--------|-----|----------|
| LAN | `http://192.168.3.233:8100/mcp` | Claude Code on local network |
| Tailscale | `http://100.79.174.122:8100/mcp` | Remote access via Tailscale |
| Cloudflare | `https://temple.tython.ca/mcp` | Public access (any MCP client) |

**Cloudflare Tunnel:** ID `2bc0c79a-a0a4-46de-a56e-42dca3d60425`, runs as systemd service `cloudflared-temple.service`.

### Authentication

Temple supports **dual authentication** when `TEMPLE_API_KEY` is set. The `/health` endpoint remains unauthenticated (used by Docker healthcheck).

- **Auth disabled** (default): No `TEMPLE_API_KEY` set — open access, suitable for local dev.
- **Auth enabled**: Set `TEMPLE_API_KEY` to a strong random string. Two auth methods work simultaneously:

#### 1. Static Bearer Token
MCP clients send `Authorization: Bearer <key>` with the static API key. Works with Claude Code, Copilot Studio, curl, and any MCP client.

**Claude Code client config** (`~/.claude/mcp.json`):
```json
{
  "mcpServers": {
    "temple": {
      "type": "streamable-http",
      "url": "https://temple.tython.ca/mcp",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}
```

#### 2. OAuth 2.1 (Authorization Code + PKCE)
Claude.ai's remote MCP connector requires OAuth 2.1. Temple advertises OAuth metadata at `/.well-known/oauth-protected-resource` and supports:

- **Pre-registered client** — set `TEMPLE_OAUTH_CLIENT_ID` + `TEMPLE_OAUTH_CLIENT_SECRET` to lock down access (recommended for public endpoints). Dynamic registration is disabled when a client is pre-registered.
- **Dynamic client registration** — if no client is pre-registered, any client can auto-register (suitable for trusted networks only).
- **Authorization code flow with PKCE** — auto-approved (single-user server, no consent screen)
- **Token exchange** — issues in-memory access/refresh tokens (lost on restart; clients re-register automatically)

Set `TEMPLE_BASE_URL` to the public-facing URL (e.g. `https://temple.tython.ca`) so OAuth metadata endpoints advertise correct URLs.

**Claude.ai remote MCP config**: Enter the MCP URL and the pre-registered client credentials:
- URL: `https://temple.tython.ca/mcp`
- Client ID: value of `TEMPLE_OAUTH_CLIENT_ID`
- Client Secret: value of `TEMPLE_OAUTH_CLIENT_SECRET`

Claude.ai handles the authorization code + PKCE flow automatically.

---

## Verification

1. **Unit tests:** `uv run pytest tests/ -v` — 47 tests covering all modules
2. **Health check:** `curl http://localhost:8100/health`
3. **MCP client test:** Connect to `http://192.168.3.233:8100/mcp`, verify 24 tools discovered
4. **Persistence test:** `docker compose down && docker compose up -d`, verify memories survive
5. **Tunnel test:** `curl https://temple.tython.ca/health`
