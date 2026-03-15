# youtube_scraping

Local control-plane repo for the YouTube scraping/transcript runtime on `46.225.98.179`, plus a structured transcript library built from exported artifacts.

## What This Repo Actually Contains

This is not the Bun runtime repo itself. It is the local operator repo used to:

- pilot the live `youtube-pipeline` service on the VPS
- inspect health, logs, runs, and disk state
- trigger workflow actions remotely
- export transcripts and SQLite state back to the workstation
- rebuild a browsable local transcript archive from SQLite
- build a reusable `library/` layer for humans and LLMs

The repository currently contains:

- `scripts/`: maintenance scripts used to sync data and rebuild transcript exports
- `openclaw_live/`: current local mirror of the live OpenClaw transcript workspace
- `youtube_scraps_openclaw_2026-02-26/`: historical export snapshot
- `logs/`: local sync logs

The bulk of the repository is generated data, not source code.

## Main Workflow

Source of truth is the OpenClaw Sentinel VPS at `46.225.98.179`, under `/root/youtube-pipeline`.

The normal operator workflow is:

1. Inspect the VPS runtime from this repo
2. Trigger or restart the pipeline if needed
3. Export `workspace/transcripts` and `db/pipeline.db` to local
4. Rebuild normalized Markdown transcript files from SQLite
5. Clean ephemeral VPS artifacts after export

## VPS Control Plane

The main entry point is now:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action status
```

Supported actions:

- `status`: `systemd` state plus recent service status
- `health`: live `GET /api/health`
- `runs`: live `GET /api/runs`
- `trigger-run`: authenticated `POST /api/trigger/run`
- `restart`: restart `youtube-pipeline.service`
- `logs`: tail daily pipeline JSONL log
- `service-logs`: tail `journalctl`
- `disk`: root filesystem and runtime directory sizes
- `sync`: export transcripts + DB to local mirror and rebuild Markdown
- `cleanup`: purge exported transcript files and rotate old workspace dirs on VPS
- `backfill`: run `scripts/backfill-transcripts.ts`
- `produce`: run `scripts/produce.sh`

Examples:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action health
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action runs
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action logs -Tail 200
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action trigger-run
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action sync
```

## Transcript Library

The second major entry point is:

```powershell
python .\scripts\build_library_from_db.py build .\openclaw_live
```

This generates a structured library under `openclaw_live/library/` with:

- `channels/` for channel-by-channel browsing
- `videos/` for one folder per video with transcript, metadata, and context bundle
- `themes/` for cross-channel topic views
- `metadata/catalog.jsonl` as the normalized source for tooling
- `metadata/embeddings.jsonl` as a first local retrieval layer
- `bundles/` with ready-to-paste LLM context bundles

Useful commands:

```powershell
python .\scripts\build_library_from_db.py build .\openclaw_live
python .\scripts\build_library_from_db.py search .\openclaw_live --query "stoic discipline focus"
python .\scripts\build_library_from_db.py bundle .\openclaw_live --query "mindfulness and breathing"
```

Detailed usage is documented in [docs/LLM_LIBRARY.md](C:\dev\projects\youtube_scraping\docs\LLM_LIBRARY.md).

## Actual Runtime On The VPS

The live scraper/transcript system is a separate Bun/TypeScript repo on the VPS, not this local mirror.

- Runtime root: `/root/youtube-pipeline`
- Service: `youtube-pipeline.service`
- Entry point: `src/index.ts`
- API port: `3847`
- Schedule: cron trigger every 30 minutes
- Main DAG: `scrape -> analyze -> generate -> produce -> upload`

This local repo only mirrors:

- `workspace/transcripts`
- `db/pipeline.db`

and rebuilds a friendlier export from those artifacts.

See [docs/VPS_CARTOGRAPHY.md](C:\dev\projects\youtube_scraping\docs\VPS_CARTOGRAPHY.md) for the detailed runtime map.
See [docs/VPS_SECURITY_AUDIT.md](C:\dev\projects\youtube_scraping\docs\VPS_SECURITY_AUDIT.md) for the current VPS security posture and OpenClaw inventory.

## VPS Split

As of March 9, 2026, the workloads are intentionally split:

- `46.225.98.179` (`openclaw-sentinel`): TorahCode, YouTube pipeline, OpenClaw, Parnassa hotpath
- `46.225.173.203` (`filon-zeroclaw-01`): Le Filon only

Le Filon was migrated off `46.225.98.179` and should not be redeployed there.
The Filon VPS now serves the scraper path from `46.225.173.203` directly.
Public DNS was aligned on March 9, 2026:

- `lefilon.ai` -> `46.225.173.203`
- `www.lefilon.ai` -> `46.225.173.203`
- `ai.lefilon.ai` -> `46.225.173.203`
- `sre.lefilon.ai` -> `46.225.173.203`
- `admin.lefilon.ai` removed

## Important Scripts

### Sync from OpenClaw VPS

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_openclaw_transcripts.ps1
```

Equivalent through the control-plane wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\manage_youtube_pipeline.ps1 -Action sync
```

Defaults:

- Host: `root@46.225.98.179`
- Remote root: `/root/youtube-pipeline`
- Local root: `C:\dev\projects\youtube_scraping\openclaw_live`
- Default behavior after a successful export:
  - clears exported files from `workspace/transcripts` on the VPS
  - deletes old `workspace/scrape/*` directories older than 3 days
  - deletes old `workspace/produce/*` directories older than 3 days

Optional override:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\sync_openclaw_transcripts.ps1 -SkipRemoteCleanup
```

### Rebuild transcript export from local SQLite DB

```powershell
python .\scripts\build_transcripts_from_db.py .\openclaw_live
```

Expected DB path under the target root:

- `db/pipeline.db`

Generated outputs:

- `transcripts/by_video/`
- `transcripts/INDEX.md`
- `README_TRANSCRIPTS.md`

## Operational Notes

- This repo should now be treated as the local operator console for `/root/youtube-pipeline`, not just as a passive mirror.
- `build_transcripts_from_db.py` now rebuilds into a temporary tree and swaps atomically, so a failed export should not wipe the previous `by_video` tree.
- `sync_openclaw_transcripts.ps1` now uses a unique remote temp bundle path, validates basic SSH path inputs, and logs both success and failure.
- `manage_youtube_pipeline.ps1` tunnels control through SSH and uses the remote `pipeline.env` for authenticated API actions, so you do not need to duplicate the YouTube pipeline bearer token locally in this repo.
- `build_library_from_db.py` turns `pipeline.db` into a local knowledge library with channel/video/theme views plus deterministic local embeddings for targeted retrieval.
- The repo currently has no normal application packaging, no top-level test runner config, and no conventional source/data split.
- On March 9, 2026, the VPS runtime was temporarily blocked at the `scrape` pre-hook by disk pressure; after cleanup the host returned above the `2GB` `disk-check` threshold.
- On March 9, 2026, the Filon Caddy config on `46.225.173.203` was simplified to remove stale ACME targets (`admin.lefilon.ai`, `hotpath.parnassa.work`), expose SRE admin through `/admin/*`, and then re-enabled hostname-based TLS for `lefilon.ai` and `www.lefilon.ai` after Cloudflare DNS was corrected.

## Maintenance Guidance

- Treat `openclaw_live/` as the current working mirror.
- Treat `scripts/manage_youtube_pipeline.ps1` as the default entry point for live ops on `46.225.98.179`.
- Treat `scripts/build_library_from_db.py` as the default entry point for building the local knowledge layer.
- Treat dated export folders like `youtube_scraps_openclaw_2026-02-26/` as immutable snapshots unless explicitly asked to regenerate them.
- Avoid mass-editing generated transcript files manually.
- Prefer rebuilding from `db/pipeline.db` instead of editing transcript Markdown in place.
- Prefer passing `library/bundles/*.md` or selected `videos/*/context.md` files to LLMs instead of dumping raw transcript folders.
- If transcript freshness matters, check the VPS disk state before trusting the mirror; the service can be `active` in systemd while every cron run still fails fast.
- The intended storage policy is now: export locally, then keep SQLite as the durable source of truth on the VPS while aggressively cleaning ephemeral workspace artifacts.

## Known Limits

- `git status` currently fails with `must be run in a work tree` from this path, so do not assume normal git review flows are available until repo state is clarified.
- This repo mirrors only the YouTube transcript path from `46.225.98.179`; Le Filon now belongs on the separate VPS `46.225.173.203`.
