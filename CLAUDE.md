# CLAUDE.md — YouTube Scraper

## What This Is

YouTube transcript scraper + library builder. Scrapes channels via yt-dlp, stores in SQLite, builds a browsable markdown library.

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
python scripts/scrape.py . --rescrape-transcripts   # re-clean all transcripts (dedup VTT)
```

### Build library

```bash
python scripts/build_library_from_db.py build .     # full library
python scripts/build_library_from_db.py search . --query "sales closing"
python scripts/build_library_from_db.py bundle . --query "negotiation"
```

### Remote management

```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 health
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 sync
```

### Adding a channel

```bash
sqlite3 db/pipeline.db "INSERT INTO channels (id, name, handle, category, language, enabled) VALUES ('UCxxx', 'Name', '@Handle', 'cat', 'en', 1);"
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

## Remote

Configure via `.env` (`VPS_HOST`, `REMOTE_ROOT`). Used by `manage.ps1` and `sync.ps1`.

## Blueprint

`youtube_scraper.vgb.json` — workflow graph with flows: full_pipeline, update, search_bundle.

## Scripts

| Script | Purpose |
|--------|---------|
| `scrape.py` | Scrape channels via yt-dlp, dedup VTT auto-subs |
| `build_library_from_db.py` | Build/search/bundle the markdown library |
| `build_library.py` | Alternative library builder |
| `build_transcripts.py` | Build transcript outputs |
| `build_transcripts_from_db.py` | Build transcripts from DB |
| `manage.ps1` | Remote management (status, health, sync, trigger-run) |
| `sync.ps1` | Remote → local data sync (called by manage.ps1) |
