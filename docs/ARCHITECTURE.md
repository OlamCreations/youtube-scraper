# Architecture Overview

`youtube-scraper` is a local-first project.

Its purpose is simple:
- fetch video metadata from YouTube channels
- download auto-generated captions when available
- clean and store transcripts in SQLite
- generate a readable markdown library from the stored data

## Main Components

### 1. Scraper

[`scripts/scrape.py`](C:/dev/projects/open-source/youtube-scraper/scripts/scrape.py) handles:
- channel seeding
- channel listing
- recent video discovery
- transcript download through `yt-dlp`
- storage in SQLite

The scraper writes into:
- `data/db/youtube.db`
- `data/tmp/`

### 2. Storage

SQLite is the source of truth for the local workflow.

Main tables:
- `channels`
- `videos`
- `transcripts`

This keeps the project easy to inspect, portable, and scriptable.

### 3. Library Builder

[`scripts/build_library.py`](C:/dev/projects/open-source/youtube-scraper/scripts/build_library.py) reads the SQLite data and produces a friendlier markdown export under `data/library/`.

The generated library is organized for:
- browsing by channel
- searching by topic
- building bundles of transcripts for downstream use

## Optional Helpers

The repository also includes optional helper scripts for users who want to automate runs or move data across machines, but they are not required for the core local workflow.
