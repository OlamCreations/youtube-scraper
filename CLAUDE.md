# CLAUDE.md: YouTube Scraper

Context for an AI coding agent working in this repository.

## What This Is

A YouTube transcript scraper and library builder, in two scripts:

1. `scripts/scrape.py` lists the latest videos of each channel with yt-dlp, downloads the auto-captions, removes the repeated lines of rolling captions, and stores the text in SQLite.
2. `scripts/build_library.py` turns that database into a browsable markdown library, a local search index, and bundles of transcripts for LLMs.

Both scripts use only the Python standard library. `scrape.py` calls the `yt-dlp` command-line tool.

## Commands

Every command takes the data directory as its first argument (`./data` below).

### Scrape

```bash
python scripts/scrape.py ./data --seed channels.example.json   # add channels from a JSON file
python scripts/scrape.py ./data                                # scrape all enabled channels (latest 50 videos each)
python scripts/scrape.py ./data --limit 200                    # look further back
python scripts/scrape.py ./data --channel UCxxx                # one channel
python scripts/scrape.py ./data --list                         # list channels
python scripts/scrape.py ./data --check                        # count unseen videos per channel, download nothing
python scripts/scrape.py ./data --retry-failed                 # retry videos stored without a transcript
python scripts/scrape.py ./data --rescrape-transcripts         # re-download and re-clean every transcript
python scripts/scrape.py ./data --reclean-text                 # re-clean the stored text, no download
```

A scrape exits 1 when a channel cannot be listed (for example an id or handle that no longer exists) and names that channel.

### Build, search, bundle

```bash
python scripts/build_library.py build ./data
python scripts/build_library.py search ./data "sales closing"
python scripts/build_library.py bundle ./data "negotiation"
```

### Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

The tests run offline. `tests/test_quickstart_e2e.py` replays the README Quick Start with a stand-in for yt-dlp. `.github/workflows/tests.yml` runs them on every push and pull request.

## Data Locations

| What | Path |
|------|------|
| SQLite database | `data/db/pipeline.db` |
| Library | `data/library/` |
| Browse by channel | `data/library/by_channel/<channel>/<title>.md` |
| One transcript per video | `data/library/videos/<video-id>/transcript.md` |
| LLM bundles | `data/library/bundles/` |
| Catalog | `data/library/metadata/catalog.jsonl` |
| Caption downloads (temporary) | `data/tmp/` |

## Schema

`scrape.init_db` creates three tables: `channels`, `videos` and `transcripts` (text in `transcripts.raw_text`). `build_library.py` reads exactly this schema. A channel whose `flag` column is set is left out of the library.

Change the two scripts together. The end-to-end test builds its database with `init_db`, so it fails if they drift apart.

## Adding a Channel

Add it to a JSON file and run `--seed`, or insert it directly:

```bash
sqlite3 data/db/pipeline.db "INSERT INTO channels (id, name, handle, category, language, enabled) VALUES ('UCxxx', 'Name', '@Handle', 'cat', 'en', 1);"
```

When `handle` is set, the scraper lists `https://www.youtube.com/<handle>`; otherwise it uses the channel id.

## Blueprint

`youtube_scraper.vgb.json` describes the pipeline as a graph of commands. Nodes: `seed_channels`, `scrape`, `scrape_single`, `build_library`, `search`, `bundle`, `list_channels`. Flows: `full_pipeline`, `update`, `search_and_bundle`.

## Rules

1. Rebuild from `pipeline.db` instead of editing files under `data/library/`. A build replaces the whole library.
2. Keep `data/` out of version control. `.gitignore` already does.
3. Run the tests before committing.
