# CODEX.md

## Scope

Operational context for `C:\dev\projects\youtube_scraping`.

## Repo Reality

- This repo is now the local control plane for the live YouTube pipeline VPS plus the downstream transcript mirror.
- The Bun/TypeScript runtime still lives remotely on `46.225.98.179` under `/root/youtube-pipeline`.
- There is no standard app structure, no package manifest, and no top-level docs besides transcript export readmes.
- The source of truth is remote OpenClaw data, not the Markdown files themselves.

## Current Important Paths

- Live local mirror: `openclaw_live/`
- Historical snapshot: `youtube_scraps_openclaw_2026-02-26/`
- Live SQLite DB mirror: `openclaw_live/db/pipeline.db`
- Live generated transcript tree: `openclaw_live/transcripts/by_video/`
- Live structured library: `openclaw_live/library/`
- Sync log: `logs/sync_openclaw.log`
- Main VPS control script: `scripts/manage_youtube_pipeline.ps1`
- Main library builder: `scripts/build_library_from_db.py`

## Main Commands

- Inspect service status from this repo:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action status
```

- Check API health:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action health
```

- Trigger a manual run:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action trigger-run
```

- Tail live pipeline logs:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action logs -Tail 200
```

- Check disk pressure on the VPS:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action disk
```

- Sync latest OpenClaw artifacts from VPS:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_openclaw_transcripts.ps1
```

- Rebuild transcript export from local DB:
```powershell
python .\scripts\build_transcripts_from_db.py .\openclaw_live
```

- Build the local LLM-ready library:
```powershell
python .\scripts\build_library_from_db.py build .\openclaw_live
```

- Search the local library:
```powershell
python .\scripts\build_library_from_db.py search .\openclaw_live --query "stoic discipline focus"
```

- Generate an LLM query bundle:
```powershell
python .\scripts\build_library_from_db.py bundle .\openclaw_live --query "mindfulness and breathing"
```

- Run local tests:
```powershell
pytest -q .\tests
```

## Verified VPS Context

- Default sync host: `root@46.225.98.179`
- Default remote root: `/root/youtube-pipeline`
- Sync currently pulls:
  - `workspace/transcripts`
  - `db/pipeline.db`
- The live runtime is a separate Bun/TypeScript service on the VPS, not this repo.
- Detailed runtime map: [`docs/VPS_CARTOGRAPHY.md`](C:\dev\projects\youtube_scraping\docs\VPS_CARTOGRAPHY.md)
- Security posture snapshot: [`docs/VPS_SECURITY_AUDIT.md`](C:\dev\projects\youtube_scraping\docs\VPS_SECURITY_AUDIT.md)
- VPS split as of March 9, 2026:
  - `46.225.98.179` = OpenClaw Sentinel host for TorahCode + YouTube pipeline + OpenClaw/Parnassa services
  - `46.225.173.203` = dedicated Le Filon host

## VPS Runtime Summary

- systemd unit: `youtube-pipeline.service`
- working directory: `/root/youtube-pipeline`
- process: `bun run src/index.ts`
- API port: `3847`
- scheduler: cron trigger every 30 minutes
- DAG: `scrape -> analyze -> generate -> produce -> upload`

Current observed state on March 9, 2026 after cleanup:

- service is `active`
- root filesystem recovered above the `2GB` `disk-check` threshold
- earlier in the day, cron runs were failing because only `277M` was free

Interpretation:

- `systemctl status` alone is not enough
- a green service can still be operationally stalled
- for transcript freshness, inspect both systemd and daily pipeline logs
- OpenClaw residue cleanup already performed:
  - removed `/root/openclaw-staging`
- Filon migration completed:
  - full Le Filon Docker stack moved to `46.225.173.203`
  - no `lefilon*` containers should remain on `46.225.98.179`
  - Filon `VPS_SCRAPER_URL` now targets `http://46.225.173.203/vps-scrape`
  - Filon Caddy now exposes SRE admin on `/admin/*` without depending on `admin.lefilon.ai`
  - Cloudflare authoritative DNS now points `lefilon.ai`, `www.lefilon.ai`, `ai.lefilon.ai`, `sre.lefilon.ai` to `46.225.173.203`
  - `admin.lefilon.ai` was removed
  - Caddy successfully obtained fresh Let's Encrypt certificates for `lefilon.ai` and `www.lefilon.ai`

## Behavior of Local Scripts

### `scripts/manage_youtube_pipeline.ps1`

- Primary local entry point for operating `/root/youtube-pipeline`
- Uses SSH to execute `systemctl`, `journalctl`, remote `curl`, and pipeline scripts
- Reads the remote `config/pipeline.env` only on the VPS when an authenticated API call is needed
- Exposes actions:
  - `status`
  - `health`
  - `runs`
  - `trigger-run`
  - `restart`
  - `logs`
  - `service-logs`
  - `disk`
  - `sync`
  - `cleanup`
  - `backfill`
  - `produce`
- Should be the default operator interface for this repo
- Keeps bearer-token handling remote instead of duplicating secrets locally
### `scripts/sync_openclaw_transcripts.ps1`

- Pulls a tar bundle from the VPS
- Extracts it under the chosen local root
- Rebuilds transcript Markdown from SQLite
- By default, cleans exported transcript files from the VPS afterwards
- Rotates old `workspace/scrape/*` and `workspace/produce/*` directories on the VPS
- Appends `sync_ok` / `sync_error` events to `logs/sync_openclaw.log`

### `scripts/build_transcripts_from_db.py`

- Reads `db/pipeline.db`
- Joins `videos` and `transcripts`
- Writes one Markdown file per video under `transcripts/by_video/<prefix>/`
- Rebuilds `transcripts/INDEX.md`
- Writes `README_TRANSCRIPTS.md`
- Uses a temp tree + atomic replace so a failed run should not destroy the prior export

### `scripts/build_library_from_db.py`

- Builds `openclaw_live/library/` from `pipeline.db`
- Normalizes one record per transcript-backed video
- Generates views by:
  - channel
  - video
  - theme
- Produces:
  - `metadata/catalog.jsonl`
  - `metadata/embeddings.jsonl`
  - `bundles/channel__*.md`
  - `bundles/theme__*.md`
  - `bundles/query__*.md`
- Includes a lightweight local retrieval layer based on deterministic hashed embeddings
- Gives future agents a stable surface that can later be swapped to Axon or a stronger vector backend

## Review Findings Already Addressed

- Sync script no longer uses a shared fixed `/tmp` bundle name on the VPS.
- Sync script now validates SSH input shape and logs failures.
- Transcript rebuild no longer deletes the existing `by_video` tree before a successful full rebuild.
- Regression tests exist in `tests/test_build_transcripts_from_db.py`.

## Rules For Future Agents

- Do not manually refactor transcript Markdown content unless explicitly requested.
- Default to `manage_youtube_pipeline.ps1` for live ops before reaching for ad hoc SSH commands.
- Default to `build_library_from_db.py` when the user wants structured knowledge access, retrieval, or LLM context packaging.
- Prefer rebuilding from `pipeline.db` over editing generated outputs.
- Treat `youtube_scraps_openclaw_2026-02-26/` as a snapshot.
- Be careful with broad search/edit commands because the repo contains a very large number of generated files.
- Keep the distinction explicit between:
  - local mirror/export repo
  - live VPS runtime repo
- Keep the host split explicit between:
  - `openclaw-sentinel` for TorahCode / YouTube / OpenClaw
  - `filon-zeroclaw-01` for Le Filon only
- If DNS ever drifts again, verify Cloudflare zone `lefilon.ai` directly; Vercel project state is no longer authoritative for the apex.
- Default disk policy for the YouTube pipeline:
  - local machine keeps the mirror/export
  - VPS keeps `db/pipeline.db` as durable state
  - VPS should not keep already-exported transcript markdown indefinitely
  - temporary `workspace/scrape` and `workspace/produce` dirs should be rotated
- If asked for a review, focus first on:
  - VPS sync safety
  - data loss risks during export rebuild
  - artifact sprawl / repo hygiene
  - lack of packaging / lack of ignores / lack of source-data separation

## Testing

Current local tests cover:

- title sanitization
- transcript/index generation
- preserving previous export tree on generation failure
- presence of the VPS control-plane actions in `manage_youtube_pipeline.ps1`
- library build outputs, retrieval ordering, and query bundle generation

Command:

```powershell
pytest -q .\tests
```

## Open Questions

- Whether this directory is intended to be a real git worktree is currently unclear; `git -C C:\dev\projects\youtube_scraping status` failed with `must be run in a work tree`.
- There is still no `.gitignore`, no root `README` history, and no explicit retention policy for large generated artifacts.
- The current embedding layer is intentionally simple and local; if stronger semantic retrieval is needed later, replace `embeddings.jsonl` generation without breaking the bundle format.
