# CLAUDE.md — YouTube Scraper (Private)

## What This Is

YouTube transcript scraper + library builder. Scrapes channels via yt-dlp, stores in SQLite, builds a browsable markdown library. VPS pipeline on OpenClaw Sentinel (46.225.98.179) + local scraping.

## Skill: /scrape-yt

This project is a Claude Code skill. Invoke with `/scrape-yt`.

## Commands

### Local scraping

```bash
python scripts/scrape.py openclaw_live                          # scrape all channels
python scripts/scrape.py openclaw_live --limit 200              # more depth
python scripts/scrape.py openclaw_live --channel UCxxx          # single channel
python scripts/scrape.py openclaw_live --list                   # list channels
```

### Build library

```bash
python scripts/build_library_from_db.py build openclaw_live     # full library
python scripts/build_library_from_db.py search openclaw_live "sales closing"
python scripts/build_library_from_db.py bundle openclaw_live "negotiation"
```

### VPS pipeline (24/7 mode)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage_youtube_pipeline.ps1 -Action health
powershell -ExecutionPolicy Bypass -File scripts/manage_youtube_pipeline.ps1 -Action trigger-run
powershell -ExecutionPolicy Bypass -File scripts/manage_youtube_pipeline.ps1 -Action sync
```

### Adding a channel

```bash
ssh root@46.225.98.179 "sqlite3 /root/youtube-pipeline/db/pipeline.db \
  \"INSERT INTO channels (id, name, handle, category, language, enabled) \
  VALUES ('UCxxx', 'Name', '@Handle', 'cat', 'en', 1);\""
```

For local-only: same INSERT but on `openclaw_live/db/pipeline.db`.

## Data Locations

| What | Where |
|------|-------|
| SQLite DB | `openclaw_live/db/pipeline.db` |
| Library | `openclaw_live/library/` |
| Browse by channel | `openclaw_live/library/by_channel/` |
| Video transcripts | `openclaw_live/library/videos/{id}/transcript.md` |
| LLM bundles | `openclaw_live/library/bundles/` |
| Catalog | `openclaw_live/library/metadata/catalog.jsonl` |

## VPS

Host: `46.225.98.179` (openclaw-sentinel)
Pipeline: `/root/youtube-pipeline/`
Service: `youtube-pipeline.service`
Cron: every 30 min (scrape + analyze only, manual trigger for full pipeline)

## Blueprint

`youtube_scraper.vgb.json` — workflow graph with flows: full_pipeline, update, search_bundle.
