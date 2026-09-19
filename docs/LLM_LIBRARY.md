# LLM Library

How to hand part of the transcript corpus to an LLM without pasting all of it. Everything below is produced by `scripts/build_library.py` from `data/db/pipeline.db`. The full directory layout is in [LIBRARY.md](LIBRARY.md).

## Build

```bash
python scripts/build_library.py build ./data
```

It prints a one-line summary: `{"videos": <n>, "channels": <n>, "themes": <n>}`.

## What an LLM Can Read

1. `data/library/videos/<video-id>/transcript.md`: one video, with a header (channel, date, URL, themes) and the full transcript.
2. `data/library/bundles/all-transcripts.md`: every transcript in one file.
3. `data/library/bundles/<query>.md`: the transcripts that best match a query (see Bundles).
4. `data/library/metadata/catalog.jsonl`: one JSON object per video with its id, title, channel, themes, date, URL, path and a short summary.

## Themes

Each video gets its themes by keyword matching on the title, the description and the first 8,000 characters of the transcript: `ai`, `business`, `software`, `design`, `media`, `productivity`. A video that matches none gets `general`. The keyword lists are `THEME_KEYWORDS` at the top of `build_library.py`.

## Search

```bash
python scripts/build_library.py search ./data "stoic discipline focus"
```

It returns the closest videos as JSON, 8 by default (`--limit` changes it). Each video is indexed as a 96-dimension hashed bag of words, stored in `data/library/metadata/embeddings.jsonl`. The search matches shared words, not meaning, and needs no model and no network. For semantic search, feed `catalog.jsonl` to the embedding model of your choice.

## Bundles

```bash
python scripts/build_library.py bundle ./data "mindfulness and breathing"
```

This writes `data/library/bundles/mindfulness-and-breathing.md` with the matching transcripts and prints its path. `--name` sets the file name and `--limit` the number of videos. The next `build` replaces the whole library, query bundles included.

## Typical Use

1. `python scripts/scrape.py ./data` to fetch new videos.
2. `python scripts/build_library.py build ./data`.
3. `python scripts/build_library.py search ./data "..."` to see what matches.
4. `python scripts/build_library.py bundle ./data "..."`, then give the bundle, or a few `transcript.md` files, to the LLM.
