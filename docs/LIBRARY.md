# Library Structure

The generated output of the YouTube Scraper is a static directory structure designed for both human readability and programmatic access (e.g., for LLM ingestion).

## Directory Layout

When you run `build_library.py`, it generates the following structure within your output directory (typically `./data/library/`):

1. **`by_channel/{channel-slug}/{Title}.md`**
   This is the **main browsing interface**. Files are grouped by channel slug, and each video gets a single Markdown file named after its human-readable title. Open a folder and read through a creator's content.

2. **`videos/{video_id}/`**
   This provides **programmatic access**. Each video has its own folder named by its unique YouTube ID. Inside:
   - `transcript.md`: The full transcript text with metadata header.
   - `metadata.json`: The same record as JSON (title, channel, URL, date, description, themes, transcript).

3. **`channels/{slug}/`**
   A generated `README.md` that lists every video of that channel.

4. **`themes/{theme}/`**
   Cross-channel thematic views. The builder assigns themes by keyword (`ai`, `business`, `software`, `design`, `media`, `productivity`, or `general` when none match) and lists the matching videos. For example, the `business` theme can hold videos from several channels.

5. **`bundles/`**
   Pre-packaged context for Large Language Models. `all-transcripts.md` combines every transcript in one file. The `bundle` command adds one file per query.

6. **`metadata/`**
   `catalog.jsonl` is a complete catalog of the library in JSON Lines format, one JSON object per video, for tooling, search engines, or custom scripts. `search.sqlite` holds the full-text search index and `summary.json` the video, channel and theme counts.

## Interacting with the Library

The `build_library.py` script provides subcommands for interacting with the data:

### Searching

Perform keyword searches across the entire transcript database:

```bash
python scripts/build_library.py search ./data "sales closing"
```

### Generating LLM Bundles

Generate custom bundles on the fly based on search queries:

```bash
python scripts/build_library.py bundle ./data "negotiation"
```

This creates a consolidated markdown file containing the transcripts of all matching videos, ready to paste into your AI tool.

### Note on Search Quality

Search ranks videos by keyword with BM25, through SQLite's FTS5 full-text index, with stemming ("closing" also finds "close"). Only videos that contain a word of the query come back. It matches words, not meaning. For semantic search, export `metadata/catalog.jsonl` to your preferred embedding pipeline.
