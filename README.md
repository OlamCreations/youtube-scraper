# YouTube Scraper

**Build a searchable transcript library from YouTube channels**

Scrape YouTube channels, extract auto-generated captions, and build a browsable markdown library organized by channel with human-readable filenames. No AI model needed — uses YouTube's own auto-captions.

## Quick Start

```bash
git clone https://github.com/OlamCreations/youtube-scraper.git
cd youtube-scraper

# Add channels
python scripts/scrape.py ./data --seed channels.example.json

# Scrape transcripts
python scripts/scrape.py ./data

# Build the library
python scripts/build_library.py build ./data

# Browse
ls data/library/by_channel/
```

That's it. No VPS, no API keys, no setup. Just Python and yt-dlp.

## What it does

1. **Scrape:** Fetches video lists and auto-generated captions from YouTube channels using `yt-dlp`
2. **Store:** Cleans VTT captions and stores them in a local SQLite database
3. **Build:** Generates a browsable markdown library organized by channel, theme, and video

## Library Structure

The primary browsing interface is `by_channel/` — one markdown file per video, named by title.

```text
data/library/
├── by_channel/             # Browse by channel, human-readable filenames
│   ├── alex-hormozi/
│   │   ├── 13 Years Of Brutally Honest Business Advice in 90 Mins.md
│   │   ├── 16 Sales Closes In 60 Seconds.md
│   │   └── How to Change Your Life.md
│   └── naval/
│       └── How to Get Rich.md
├── videos/                 # Programmatic access by video ID
├── channels/               # Channel metadata and indices
├── themes/                 # Cross-channel thematic collections
├── bundles/                # Pre-packaged LLM-ready context
└── metadata/               # Full catalog (catalog.jsonl)
```

See [docs/LIBRARY.md](docs/LIBRARY.md) for details.

## Commands

### Scraping

```bash
# Seed channels from a JSON file
python scripts/scrape.py ./data --seed channels.example.json

# Scrape all enabled channels (default: 50 most recent videos per channel)
python scripts/scrape.py ./data

# Scrape more videos per channel
python scripts/scrape.py ./data --limit 200

# Scrape a single channel
python scripts/scrape.py ./data --channel UCUyDOdBWhC1MCxEjC46d-zw

# List all channels with video counts
python scripts/scrape.py ./data --list
```

### Building the Library

```bash
# Build the full library
python scripts/build_library.py build ./data

# Search transcripts
python scripts/build_library.py search ./data "sales closing"

# Generate an LLM-ready bundle
python scripts/build_library.py bundle ./data "negotiation"
```

### VPS Mode (optional, for 24/7 scraping)

For continuous scraping, deploy the pipeline on a VPS. See [docs/VPS_SETUP.md](docs/VPS_SETUP.md).

```powershell
# Remote control from your machine
scripts/manage.ps1 health
scripts/manage.ps1 trigger-run
scripts/manage.ps1 sync
```

## Adding Channels

Option 1 — seed from JSON:
```bash
python scripts/scrape.py ./data --seed channels.example.json
```

Option 2 — insert directly into SQLite:
```sql
INSERT INTO channels (id, name, handle, category, language, enabled)
VALUES ('UCUyDOdBWhC1MCxEjC46d-zw', 'Alex Hormozi', '@AlexHormozi', 'sales', 'en', 1);
```

## Requirements

1. Python 3.10+
2. [yt-dlp](https://github.com/yt-dlp/yt-dlp) (`pip install yt-dlp`)

Optional for VPS mode: PowerShell, SSH access.

## License

MIT — See [LICENSE](LICENSE).
