# VPS Cartography

Operational map of the live YouTube transcript pipeline running on the OpenClaw VPS.

## Identity

- VPS: `46.225.98.179`
- Hostname: `openclaw-sentinel`
- Runtime root: `/root/youtube-pipeline`
- Service: `youtube-pipeline.service`
- Process: `/root/.bun/bin/bun run src/index.ts`
- Service state seen on March 9, 2026: `active (running)` since February 26, 2026

Important distinction:

- `C:\dev\projects\youtube_scraping` is only a local mirror plus rebuild tooling.
- The actual scraper/runtime lives on the VPS in its own Bun/TypeScript repo.
- Le Filon no longer belongs on this host; its dedicated VPS is `46.225.173.203` (`filon-zeroclaw-01`).

## Topology

Top-level runtime directories:

- `config/`
- `db/`
- `docs/`
- `logs/`
- `memory/`
- `scripts/`
- `src/`
- `workspace/`

Observed sizes on March 9, 2026 before cleanup:

- `config`: `20K`
- `db`: `83M`
- `logs`: `1.1M`
- `memory`: `4.0K`
- `workspace`: `81M`

Observed after cleanup and export on March 9, 2026:

- `workspace/transcripts`: reduced from `58M` to `20K`
- `workspace/produce`: reduced from `20M` to `4K`
- `workspace/scrape`: reduced from `3.5M` to `384K`
- root filesystem recovered from `277M` free to roughly `2.8G` free

## Runtime Model

The service is a DAG workflow engine, not a single scraper script.

Defined DAG in `config/pipeline.json`:

1. `scrape`
2. `analyze`
3. `generate`
4. `produce`
5. `upload`

Edges and gates:

- `scrape -> analyze` via `transcript-quality`
- `analyze -> generate` via `manual-only`
- `generate -> produce` via `script-quality`
- `produce -> upload` via `video-integrity`

Triggers:

- cron trigger `pipeline-cycle` every 30 minutes: `*/30 * * * *`
- manual trigger

## Main Source Files

Core boot/runtime:

- `/root/youtube-pipeline/src/index.ts`
- `/root/youtube-pipeline/src/config.ts`
- `/root/youtube-pipeline/src/engine/executor.ts`
- `/root/youtube-pipeline/src/engine/scheduler.ts`
- `/root/youtube-pipeline/src/http/server.ts`
- `/root/youtube-pipeline/src/http/routes.ts`

Database layer:

- `/root/youtube-pipeline/src/db/schema.ts`
- `/root/youtube-pipeline/src/db/repository.ts`

Node handlers:

- `/root/youtube-pipeline/src/nodes/scrape.ts`
- `/root/youtube-pipeline/src/nodes/analyze.ts`
- `/root/youtube-pipeline/src/nodes/generate.ts`
- `/root/youtube-pipeline/src/nodes/produce.ts`
- `/root/youtube-pipeline/src/nodes/upload.ts`

Hooks and observability:

- `/root/youtube-pipeline/src/hooks/resource-checks.ts`
- `/root/youtube-pipeline/src/hooks/registry.ts`
- `/root/youtube-pipeline/src/observability/health.ts`
- `/root/youtube-pipeline/src/observability/logger.ts`

Ops scripts:

- `/root/youtube-pipeline/scripts/scrape.sh`
- `/root/youtube-pipeline/scripts/produce.sh`
- `/root/youtube-pipeline/scripts/backfill-transcripts.ts`
- `/root/youtube-pipeline/scripts/init-db.sh`

## Data Flow

### 1. Scrape

`src/nodes/scrape.ts`:

- reads enabled channels from SQLite
- lists videos with `yt-dlp`
- downloads auto subtitles
- parses VTT to cleaned text
- inserts `videos` and `transcripts`
- writes transcript markdown into `workspace/transcripts/<videoId>.md`

Legacy shell path also exists in `scripts/scrape.sh`:

- seeds channels from `config/channels.json`
- runs `yt-dlp` against channel feeds
- writes metadata and transcripts into SQLite
- removes per-channel temp workspace after processing

### 2. Analyze

`src/nodes/analyze.ts`:

- selects transcripts not yet analyzed
- calls NVIDIA NIM chat completions
- stores structured JSON into `insights`
- attempts embeddings for RAG

### 3. Generate

`src/nodes/generate.ts`:

- retrieves relevant insights through RAG
- writes a long-form prophetic narration script
- stores rows in `scripts`

### 4. Produce

`src/nodes/produce.ts`:

- sanitizes bracketed stage directions for TTS
- runs `edge-tts`
- creates a static background with `ffmpeg`
- composes an `.mp4`
- stores rows in `episodes`

### 5. Upload

`src/nodes/upload.ts`:

- refreshes Google OAuth token
- uploads via YouTube Data API resumable upload
- falls back to `dry_run` if credentials are absent

## HTTP API

Port:

- `3847`

Bind model as of March 9, 2026 evening hardening pass:

- `127.0.0.1:3847` only
- no longer intended for direct public access on the VPS IP

Auth model:

- mutation methods require `Authorization: Bearer <AUTH_TOKEN>`
- GET routes are readable without the bearer token

Useful routes from `src/http/routes.ts`:

- `GET /api/health`
- `POST /api/trigger/run`
- `POST /api/produce`
- `GET /api/runs`
- `GET /api/runs/:id`
- `POST /api/runs/:id/cancel`
- `GET /api/dlq`
- `POST /api/dlq/:id/replay`
- `GET /api/metrics`
- `GET /api/transcripts/:videoId`

## Configuration And Secrets

Environment is loaded from:

- `/root/youtube-pipeline/config/pipeline.env`

Important config keys in `src/config.ts`:

- `WORKFLOW_PORT`
- `WORKFLOW_HOST`
- `AUTH_TOKEN`
- `DB_PATH`
- `PIPELINE_DIR`
- `LOG_DIR`
- `WORKSPACE_DIR`
- `NVIDIA_API_KEY`
- `NVIDIA_MODEL`
- `PEXELS_API_KEY`
- `SCRAPE_BOOTSTRAP_LIMIT`
- `SCRAPE_INCREMENTAL_LIMIT`
- `SCRAPE_SLEEP_INTERVAL`
- `TARGET_WORD_COUNT`
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`

Other config files:

- `/root/youtube-pipeline/config/pipeline.json`: DAG definition
- `/root/youtube-pipeline/config/channels.json`: seed list of channels
- `/root/youtube-pipeline/config/cookies.txt`: cookies used by `yt-dlp`

Observed seeded channels include:

- Kurzgesagt
- 3Blue1Brown
- Veritasium
- CGP Grey
- TED-Ed
- Philosophy Tube
- Wendover Productions
- Computerphile
- Economics Explained
- TEDx Talks

## Persistence Model

The workflow engine extends the existing SQLite DB with workflow tables.

Workflow tables seen in `src/db/schema.ts`:

- `schema_version`
- `workflow_runs`
- `work_items`
- `transitions`
- `hook_logs`
- `gate_logs`
- `dead_letter`
- `circuit_breakers`
- `metrics`

Domain tables referenced by nodes:

- `channels`
- `videos`
- `transcripts`
- `insights`
- `scripts`
- `episodes`

## Workspace Layout

Observed under `/root/youtube-pipeline/workspace`:

- `workspace/transcripts/`
- `workspace/scrape/<runId>/`
- `workspace/produce/<runId>/`

Notable observation:

- `workspace/transcripts` currently contains `506` transcript markdown files at the top level.
- `workspace/scrape` contains hundreds of numbered run directories and appears to be the main source of churn.

## Logging And Monitoring

Logs are JSONL with daily rotation:

- `/root/youtube-pipeline/logs/pipeline-YYYY-MM-DD.log`

Health endpoint reports:

- DB connectivity
- disk usage
- memory usage
- active run count
- uptime

Systemd:

- unit file: `/etc/systemd/system/youtube-pipeline.service`
- restart policy: `Restart=on-failure`

## Current Operational State

As of Monday, March 9, 2026:

- service is running under systemd
- earlier in the day, recent `workflow_runs` were failing repeatedly
- failure occurred before `scrape` executed
- reason from logs: pre-hook `disk-check`

Observed disk state before cleanup:

- filesystem `/dev/sda1`
- size `38G`
- used `36G`
- available `277M`
- usage `100%`

The resource hook in `src/hooks/resource-checks.ts` aborts when available disk is below `2GB`, which is why the earlier state guaranteed cron failure.

Log pattern seen repeatedly in `pipeline-2026-03-09.log`:

- cron trigger matches every 30 minutes
- `Pre-hook failed, aborting work item`
- failed hook: `disk-check`

This means:

- systemd `active` does not imply productive scraping
- the local mirror may be stale even when the service looks healthy at first glance

Current follow-up state after cleanup:

- transcript and workspace churn was exported and purged
- Docker/journal cleanup restored the box above the `2GB` threshold
- `youtube-pipeline` should no longer be blocked specifically by the `disk-check` pre-hook
- `youtube-pipeline` was rebound from `*:3847` to `127.0.0.1:3847`

## Operational Commands

Status:

```powershell
ssh root@46.225.98.179 "systemctl status youtube-pipeline --no-pager"
```

Tail logs:

```powershell
ssh root@46.225.98.179 "tail -n 120 /root/youtube-pipeline/logs/pipeline-2026-03-09.log"
```

Health:

```powershell
ssh root@46.225.98.179 "curl -s http://localhost:3847/api/health"
```

Manual production trigger:

```powershell
ssh root@46.225.98.179 "cd /root/youtube-pipeline && ./scripts/produce.sh"
```

Backfill missing transcripts:

```powershell
ssh root@46.225.98.179 "cd /root/youtube-pipeline && /root/.bun/bin/bun run scripts/backfill-transcripts.ts"
```

## Practical Reprise Notes

- Treat `/root/youtube-pipeline` as the source of truth.
- Treat `C:\dev\projects\youtube_scraping` as a downstream mirror for inspection/export only.
- When resuming work, inspect disk pressure first; current failures are operational, not algorithmic.
- When checking co-hosted workloads, remember that Le Filon has been migrated away and should not be recreated on this host.
- If freshness matters, verify `logs/pipeline-YYYY-MM-DD.log` before trusting `openclaw_live`.
- If cleanup work is planned, inspect `workspace/scrape/` first because it is the most obvious accumulation zone.
- New intended policy:
  - export `workspace/transcripts` and `db/pipeline.db` to local
  - rebuild locally from SQLite
  - then clear exported transcript files from the VPS
  - keep only short-lived `workspace/scrape/*` and `workspace/produce/*` directories on the VPS
