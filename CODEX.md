# CODEX.md

## Scope

Operational context for `C:\dev\projects\youtube-scraper`.

## Architecture

Local Python scraper + SQLite DB + markdown library builder. No remote runtime, no service, no API.

## Important Paths

| What | Path |
|------|------|
| SQLite DB | `db/pipeline.db` |
| Transcript library | `library/` |
| Browse by channel | `library/by_channel/` |
| Video transcripts | `library/videos/{id}/transcript.md` |
| LLM bundles | `library/bundles/` |
| Catalog | `library/metadata/catalog.jsonl` |
| Config | `.env` (from `.env.example`) |
| Blueprint | `youtube_scraper.vgb.json` |

## VPS Data Mirror

VPS host: `root@46.225.98.179` (metatron)
VPS data: `/opt/metatron/data/youtube-scraper/` (flat: `db/`, `library/`)
Structure mirrors local. No services or crons on VPS.

## Main Commands

### Scraping
```bash
python scripts/scrape.py .                        # scrape all channels
python scripts/scrape.py . --limit 200            # more depth
python scripts/scrape.py . --channel UCxxx        # single channel
python scripts/scrape.py . --list                 # list channels
python scripts/scrape.py . --seed channels.json   # seed from JSON
```

### Library
```bash
python scripts/build_library_from_db.py build .
python scripts/build_library_from_db.py search . "query"
python scripts/build_library_from_db.py bundle . "query"
```

### VPS management
```powershell
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 status
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 health
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 sync
powershell -ExecutionPolicy Bypass -File scripts/manage.ps1 trigger-run
```

### Tests
```bash
pytest -q tests/
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scrape.py` | Scrape channels via yt-dlp, store in SQLite |
| `build_library_from_db.py` | Build/search/bundle markdown library from DB |
| `build_library.py` | Alternative library builder |
| `build_transcripts.py` | Build transcript outputs |
| `build_transcripts_from_db.py` | Build transcripts from DB |
| `manage.ps1` | VPS management (status, health, sync, trigger-run) |
| `sync.ps1` | VPS -> local data sync (called by manage.ps1) |

## Rules For Future Agents

1. Default to `manage.ps1` for VPS ops before ad hoc SSH commands.
2. Default to `build_library_from_db.py` for structured knowledge access.
3. Prefer rebuilding from `pipeline.db` over editing generated outputs.
4. Be careful with broad search/edit — large number of generated files.
5. The `data_dir` argument to Python scripts is `.` (current directory).
6. Config lives in `.env` — never hardcode host, paths, or tokens.
