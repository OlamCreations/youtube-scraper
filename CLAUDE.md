# CLAUDE.md — YouTube Scraper

## What This Is

A standalone YouTube transcript scraper. Scrapes channels via yt-dlp, stores in SQLite, builds a browsable markdown library.

## Commands

```bash
# Seed channels from JSON
python scripts/scrape.py ./data --seed channels.example.json

# Scrape all enabled channels (default 50 videos per channel)
python scripts/scrape.py ./data

# Scrape with more depth
python scripts/scrape.py ./data --limit 200

# Scrape a single channel by ID
python scripts/scrape.py ./data --channel UCUyDOdBWhC1MCxEjC46d-zw

# List all channels
python scripts/scrape.py ./data --list

# Build the browsable library
python scripts/build_library.py build ./data

# Search transcripts
python scripts/build_library.py search ./data "sales closing"

# Generate LLM bundle
python scripts/build_library.py bundle ./data "negotiation"
```

## Adding a Channel

To add a channel, insert into SQLite:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/db/pipeline.db')
conn.execute(\"INSERT INTO channels (id, name, handle, category, language, enabled) VALUES (?, ?, ?, ?, ?, 1)\",
    ('CHANNEL_ID', 'Channel Name', '@Handle', 'category', 'en'))
conn.commit()
conn.close()
"
```

Or seed from channels.example.json.

## Data Locations

| What | Where |
|------|-------|
| SQLite DB | `data/db/pipeline.db` |
| Library | `data/library/` |
| Browse by channel | `data/library/by_channel/` |
| Video transcripts | `data/library/videos/{id}/transcript.md` |
| LLM bundles | `data/library/bundles/` |
| Catalog | `data/library/metadata/catalog.jsonl` |

## Requirements

1. Python 3.10+
2. yt-dlp (`pip install yt-dlp`)

## Workflow

1. Add channels (seed or INSERT)
2. Scrape (`scripts/scrape.py`)
3. Build library (`scripts/build_library.py build`)
4. Browse `data/library/by_channel/`

Always scrape before building the library to get the latest videos.
