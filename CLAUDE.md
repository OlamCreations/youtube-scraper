# CLAUDE.md — YouTube Scraper

## What This Is

YouTube transcript scraper + library builder. Scrapes channels via yt-dlp, stores in SQLite, builds a browsable markdown library.

## Skill: /scrape-yt

This project is a Claude Code skill. Invoke with `/scrape-yt`.

## Config

All config in `.env` at project root (copy `.env.example`). Never hardcode paths.

## Commands

### Local scraping

```bash
python scripts/scrape.py .                          # scrape all channels
python scripts/scrape.py . --limit 200              # more depth
python scripts/scrape.py . --channel UCxxx          # single channel
python scripts/scrape.py . --list                   # list channels
python scripts/scrape.py . --seed channels.json     # seed from JSON
```

### Build library

```bash
python scripts/build_library_from_db.py build .     # full library
python scripts/build_library_from_db.py search . "sales closing"
python scripts/build_library_from_db.py bundle . "negotiation"
```

### VPS management

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 health
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 sync
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 trigger-run
```

### Adding a channel

```bash
# Local
sqlite3 db/pipeline.db "INSERT INTO channels (id, name, handle, category, language, enabled) VALUES ('UCxxx', 'Name', '@Handle', 'cat', 'en', 1);"

# VPS
ssh root@46.225.98.179 "sqlite3 /opt/metatron/data/youtube-scraper/db/pipeline.db \"INSERT INTO channels (id, name, handle, category, language, enabled) VALUES ('UCxxx', 'Name', '@Handle', 'cat', 'en', 1);\""
```

## Data Locations

| What | Path |
|------|------|
| SQLite DB | `db/pipeline.db` |
| Library | `library/` |
| Browse by channel | `library/by_channel/` |
| Video transcripts | `library/videos/{id}/transcript.md` |
| LLM bundles | `library/bundles/` |
| Catalog | `library/metadata/catalog.jsonl` |

## VPS

Host: `46.225.98.179` (metatron)
Data: `/opt/metatron/data/youtube-scraper/`
Structure: mirrors local (flat `db/`, `library/`)

## Blueprint

`youtube_scraper.vgb.json` — workflow graph with flows: full_pipeline, update, search_bundle.

## Scripts

| Script | Purpose |
|--------|---------|
| `scrape.py` | Scrape channels via yt-dlp |
| `build_library_from_db.py` | Build/search/bundle the markdown library |
| `build_library.py` | Alternative library builder |
| `build_transcripts.py` | Build transcript outputs |
| `build_transcripts_from_db.py` | Build transcripts from DB |
| `manage.ps1` | VPS management (status, health, sync, trigger-run) |
| `sync.ps1` | VPS → local data sync (called by manage.ps1) |
