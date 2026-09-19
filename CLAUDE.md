# CLAUDE.md: YouTube Scraper

Context for an AI coding agent working in this repository.

## What This Is

A YouTube transcript scraper and library builder, in two scripts:

1. `scripts/scrape.py` lists the latest videos of each channel with yt-dlp, downloads the auto-captions, removes the repeated lines of rolling captions, and stores the text in SQLite.
2. `scripts/build_library.py` turns that database into a browsable markdown library, a local search index, and bundles of transcripts for LLMs.

Both scripts use only the Python standard library. The search index needs the FTS5 extension of Python's `sqlite3`; without it, `build` stops with an error that says so. `scrape.py` runs yt-dlp: through the current Python when the `yt_dlp` module is installed there (`pip install -r requirements.txt` does that), otherwise the `yt-dlp` executable on PATH.

## Commands

Every command takes the data directory as its first argument (`./data` below).

### Scrape

```bash
python scripts/scrape.py ./data --seed channels.example.json   # add channels from a JSON file
python scripts/scrape.py ./data                                # scrape all enabled channels (latest 50 of each channel tab)
python scripts/scrape.py ./data --limit 200                    # look further back
python scripts/scrape.py ./data --channel UCxxx                # one channel
python scripts/scrape.py ./data --list                         # list channels
python scripts/scrape.py ./data --check                        # count unseen videos per channel, download nothing
python scripts/scrape.py ./data --retry-failed                 # retry videos stored without a transcript
python scripts/scrape.py ./data --rescrape-transcripts         # re-download and re-clean every transcript
python scripts/scrape.py ./data --reclean-text                 # re-clean the stored text, no download
```

A scrape, or a `--check`, exits 1 when a channel cannot be listed (for example an id or handle that no longer exists) and names that channel. `--check` never shows such a channel as 0 new videos. `--seed` exits 1 when its JSON file cannot be read.

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

The tests run offline. `tests/test_quickstart_e2e.py` runs the README Quick Start commands as subprocesses, from `--seed` through `--limit 5`, `build` and `search` to `bundle`. The pip install steps are not replayed. For the scrape, `tests/fake_yt_dlp` goes first on `PYTHONPATH`: scrape.py runs that stand-in as `python -m yt_dlp`, it answers from a fixture and never touches the network. The tests check the exit code of the scrape and of `--check`: 0 when every channel is listed, 1 when one is not, with that channel named in the output. `.github/workflows/tests.yml` runs the tests on every push and pull request.

## Data Locations

| What | Path |
|------|------|
| SQLite database | `data/db/pipeline.db` |
| Library | `data/library/` |
| Browse by channel | `data/library/by_channel/<channel>/<title>.md` |
| One transcript per video | `data/library/videos/<video-id>/transcript.md` |
| LLM bundles | `data/library/bundles/` |
| Catalog | `data/library/metadata/catalog.jsonl` |
| Search index (SQLite FTS5, ranked with BM25) | `data/library/metadata/search.sqlite` |
| Caption downloads (temporary) | `data/tmp/` |

## Schema

`scrape.init_db` creates three tables: `channels`, `videos` and `transcripts` (text in `transcripts.raw_text`). `build_library.py` reads exactly this schema. A channel whose `flag` column is set is left out of the library.

Change the two scripts together. The end-to-end test builds its database by running `scrape.py`, then reads it with `build_library.py`, so it fails if they drift apart.

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
