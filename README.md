# YouTube Scraper

**Build a searchable transcript library from YouTube channels**

Scrape YouTube channels, extract auto-generated captions, and build a browsable markdown library organized by channel with human-readable filenames. No AI model is required: the project relies on YouTube auto-captions and local processing.

## Quick Start

```bash
git clone https://github.com/OlamCreations/youtube-scraper.git
cd youtube-scraper

# Install yt-dlp, the only dependency
python -m pip install -r requirements.txt

# Add the example channels
python scripts/scrape.py ./data --seed channels.example.json

# Scrape the 5 latest uploads of each channel tab (Videos, Shorts, Live)
python scripts/scrape.py ./data --limit 5

# Build the library
python scripts/build_library.py build ./data

# Browse the generated output
ls data/library/by_channel/

# Search it
python scripts/build_library.py search ./data "sales closing"

# Run the tests (offline, no YouTube access needed)
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

That is the whole workflow. It needs no API key.

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

# Look further back (the limit applies to each channel tab)
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
2. [yt-dlp](https://github.com/yt-dlp/yt-dlp), installed by `requirements.txt`
3. pytest for the tests, installed by `requirements-dev.txt`

## How this was built

I did not write this code by hand. I directed AI coding agents. `CLAUDE.md` is the context file the agent reads. `youtube_scraper.vgb.json` describes the pipeline as a graph an agent can follow step by step.

My part is the spec, the review and the checks. `tests/test_quickstart_e2e.py` runs the Quick Start commands, from seeding the example channels to search. A stand-in for yt-dlp answers the scrape, so the tests never reach YouTube. A GitHub Action runs the tests on every push.

## License

MIT — See [LICENSE](LICENSE).
