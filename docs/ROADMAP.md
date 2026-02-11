# Temple Roadmap

Last updated: `2026-02-11`

This roadmap is prioritized for reliability, interoperability, and safe production growth across MCP and REST ecosystems.

## Priority 0: Stabilize Production Interop

1. OAuth policy hardening
- Define and enforce pre-registered OAuth client mode (`TEMPLE_OAUTH_CLIENT_*` + `TEMPLE_OAUTH_REDIRECT_URIS`).
- Keep compatibility discovery endpoints while client behavior is mixed.
- Add explicit runbook for safe temporary dynamic registration.

2. ~~Public endpoint confidence checks~~ **DONE 2026-02-11**
- `docker/scripts/smoke-test.sh` — 17 checks covering health, OAuth metadata, MCP, REST auth enforcement, graph export, and memory round-trip.
- Works against both LAN and public tunnel endpoints.

3. Client playbooks
- Ship tested connection recipes for Claude Code (Bearer mode).
- Ship tested connection recipes for Claude.ai remote MCP (OAuth mode).
- Ship tested connection recipes for Copilot Studio and M365.
- Ship tested connection recipes for ChatGPT Actions via OpenAPI.

## Priority 1: Data and Graph Integrity

1. ~~Graph schema migration completion~~ **DONE 2026-02-11**
- Migrated legacy → v2: 55 entities, 24 relations, 0 skipped.
- JSON backup: `data/graph/kuzu_legacy_backup_20260211_152531.json`
- Filesystem backup: `data/backups/kuzu_pre_migration_20260211_152411`

2. Session lifecycle controls
- Validate TTL cleanup behavior with realistic multi-session load.
- Add monitoring for expired-scope cleanup events.

3. Backup and restore drills — **PARTIALLY DONE 2026-02-11**
- Fixed `docker/scripts/backup.sh` (Kuzu is a file, not a dir; now copies entire graph/ dir).
- Added `docker/scripts/restore.sh` with safety checks (container-running guard, confirmation prompt, content verification).
- TODO: periodic recovery test cadence / cron automation.

## Priority 1.5: Ingest and Extraction Generalization — **DONE 2026-02-11**

1. ~~Generalized ingest API~~ **DONE**
- Universal `POST /api/v1/ingest/submit` accepting any content type (email, document, chat, meeting note, ticket, survey, note).
- Backward-compatible: legacy `/api/v1/surveys/*` routes remain as wrappers.
- State file migration: `survey_state.json` → `ingest_state.json` with automatic fallback.

2. ~~LLM-assisted extraction~~ **DONE**
- Claude-powered entity/relation extraction via Anthropic API when `TEMPLE_LLM_API_KEY` is configured.
- Structured taxonomy: 6 entity types, 13+ relation types.
- Heuristic fallback when no LLM key is set or API call fails.
- Extraction method tracked per job for observability.

## Priority 2: Ecosystem Expansion

1. First-party REST SDK adapters
- Add examples/templates for LangChain, LlamaIndex, Semantic Kernel, and generic Python/TypeScript clients.

2. MCP capability profiles
- Document capability subsets for tools with strict policy environments (enterprise copilots, shared tenants).

3. Multi-environment deployment profiles
- Add explicit `dev`, `staging`, `prod` compose/env patterns.
- Include auth and tunnel guidance per environment.

## Priority 3: Product Depth

1. Retrieval quality upgrades
- Hybrid retrieval path (semantic + graph + lexical signal).
- Better ranking diagnostics and explainability fields.

2. Multi-user namespace isolation
- Introduce tenant/user namespace boundary model for shared deployments.
- Add auth-scope mapping for per-tenant data separation.

3. UX and observability
- Web dashboard for memory/graph visibility.
- Structured metrics and alerting around query latency, error rates, and auth failures.

## Deferred / Exploratory

1. Unraid migration package
- Compose profile and volume mapping template for `/mnt/cache/appdata/temple`.

2. Optional embedding service split
- Evaluate external embedding service only if throughput warrants separation.

3. Policy-based tool exposure
- Per-client capability filtering (read-only vs mutating tools).
