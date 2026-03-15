# YouTube Scraper

**Build a searchable transcript library from YouTube channels**

Scrape YouTube channels, extract auto-generated captions, and build a browsable markdown library organized by channel with human-readable filenames. No AI model is required: the project relies on YouTube auto-captions and local processing.

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

# Browse the generated output
ls data/library/by_channel/
```

That is the core workflow. No API keys, no hidden control plane, and no private runtime assumptions.

## What It Does

1. Scrape video lists and auto-generated captions from YouTube channels with `yt-dlp`.
2. Clean and store transcript text in a local SQLite database.
3. Generate a markdown library for browsing, searching, and downstream reuse.

## Library Structure

```text
data/library/
├── by_channel/             # Human-readable browsing by channel
├── videos/                 # Programmatic access by video ID
├── channels/               # Channel metadata and indices
├── themes/                 # Cross-channel thematic collections
├── bundles/                # Pre-packaged context bundles
└── metadata/               # Catalog and supporting metadata
```

See [docs/LIBRARY.md](docs/LIBRARY.md) for details.

## Commands

### Scraping

```bash
# Seed channels from JSON
python scripts/scrape.py ./data --seed channels.example.json

# Scrape all enabled channels
python scripts/scrape.py ./data

# Scrape more videos per channel
python scripts/scrape.py ./data --limit 200

# Scrape one specific channel
python scripts/scrape.py ./data --channel UCUyDOdBWhC1MCxEjC46d-zw

# List configured channels
python scripts/scrape.py ./data --list
```

### Build the Library

```bash
# Build the full library
python scripts/build_library.py build ./data

# Search transcripts
python scripts/build_library.py search ./data "sales closing"

# Generate a bundle
python scripts/build_library.py bundle ./data "negotiation"
```

## Adding Channels

Option 1:

```bash
python scripts/scrape.py ./data --seed channels.example.json
```

Option 2:

```sql
INSERT INTO channels (id, name, handle, category, language, enabled)
VALUES ('UCUyDOdBWhC1MCxEjC46d-zw', 'Alex Hormozi', '@AlexHormozi', 'sales', 'en', 1);
```

## Requirements

1. Python 3.10+
2. [yt-dlp](https://github.com/yt-dlp/yt-dlp)

Optional:
- PowerShell if you want to use the included helper scripts on Windows

## Notes

- The public repository is intended to stay generic and safe to publish.
- Do not add private infrastructure details, operator playbooks, hostnames, or internal runtime notes to this README.
- If you self-host scheduled runs, keep machine-specific configuration outside version control.

## License

MIT — See [LICENSE](LICENSE).
