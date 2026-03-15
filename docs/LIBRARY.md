# Library Structure

The generated output of the YouTube Scraper is a static directory structure designed for both human readability and programmatic access (e.g., for LLM ingestion).

## Directory Layout

When you run `build_library.py`, it generates the following structure within your output directory (typically `./data/library/`):

1. **`by_channel/{channel-slug}/{Title}.md`**
   This is the **main browsing interface**. Files are grouped by channel slug, and each video gets a single Markdown file named after its human-readable title. Open a folder and read through a creator's content.

2. **`videos/{video_id}/`**
   This provides **programmatic access**. Each video has its own folder named by its unique YouTube ID. Inside:
   - `transcript.md`: The full transcript text with metadata header.
   - `metadata.json`: Full metadata (title, channel, themes, tags, word count).

3. **`channels/{slug}/`**
   Contains channel-level metadata (`channel.json`) and a generated README index of all videos scraped for that channel.

4. **`themes/{theme}/`**
   Cross-channel thematic views. The builder auto-detects themes based on keywords (sales, philosophy, science, etc.) and groups relevant videos. For example, a `business_entrepreneurship` theme might contain videos from multiple channels.

5. **`bundles/`**
   Pre-packaged context ready for Large Language Models. Consolidated markdown files combining multiple transcripts (e.g., an entire channel bundle or a specific theme bundle).

6. **`metadata/catalog.jsonl`**
   A complete catalog of the entire library in JSON Lines format. One JSON object per line, per video. For tooling, search engines, or custom scripts.

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

Search uses lightweight hash-based keyword matching, not semantic embeddings. It works well for finding specific topics but is not a full vector search. For semantic search, export `metadata/catalog.jsonl` to your preferred embedding pipeline.
