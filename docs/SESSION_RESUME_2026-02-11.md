# Temple Resume Handoff (2026-02-11)

## Current Runtime Snapshot

- Host disk before expansion: `/` at `99%` (`98G` total, `1.4G` free).
- Running services:
  - `docker-temple-memory-1` healthy on `:8100`
  - `docker-temple-chromadb-1` running
- Live data snapshot (latest check):
  - `entity_count: 51`
  - `relation_count: 20`
  - `total_memories: 3`
  - active context: `project:lance-taylor` + `global`

## Why Last Deploy Failed

- Rebuild of `temple-memory` failed with `No space left on device` while installing heavy Python deps (`torch` / `nvidia-cudnn-cu12`).
- Running container remained healthy; ingest was not interrupted.

## Changes Prepared Locally

- `src/temple/rest_server.py`
  - Atlas now persists `Base URL` and `API key` to browser `localStorage`.
  - Atlas auto-restores these values on reload.
  - Atlas auto-loads graph when a saved API key exists.
- `.env` (local, untracked)
  - `TEMPLE_SESSION_TTL=0` (disable session auto-expiry).
- `.env.example`
  - `TEMPLE_SESSION_TTL=0` (new default for fresh environments).

## Post-Reboot Resume Checklist

1. Verify expanded disk:
```bash
df -h
```

2. Start from repo root:
```bash
cd /home/lans/temple
```

3. Build and restart Temple service with pending Atlas changes:
```bash
cd docker
docker compose up -d --build temple-memory
```

4. Verify health:
```bash
docker compose ps
docker compose logs --tail=80 temple-memory
```

5. Quick API sanity check (inside container, auth-safe):
```bash
docker compose exec -T temple-memory python -c "import os,urllib.request;key=os.environ.get('TEMPLE_API_KEY','');req=urllib.request.Request('http://127.0.0.1:8100/api/v1/admin/stats',headers={'Authorization':'Bearer '+key});print(urllib.request.urlopen(req).read().decode())"
```

6. Atlas check:
- Open `/atlas`.
- Confirm API key/base URL persist across refresh.
- Confirm graph loads without re-entering creds.

## Notes

- Session TTL is now set to disabled (`0`) in local env, so future `session:*` data will not auto-expire.
- Existing graph is still `legacy` schema; migration can be run later with backup once desired.
