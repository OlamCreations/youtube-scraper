# LLM Library

This repo now contains a local transcript library layer built from `openclaw_live/db/pipeline.db`.

## Goal

Turn raw YouTube transcripts into a corpus that is usable by:

- humans browsing by channel, video, or theme
- local tooling
- Codex, Claude Code, and Gemini through focused context bundles

## Build

```powershell
python .\scripts\build_library_from_db.py build .\openclaw_live
```

Default output:

- `openclaw_live/library/`

## Generated Structure

- `library/channels/<channel-slug>/README.md`
- `library/channels/<channel-slug>/channel.json`
- `library/videos/<video-id>/metadata.json`
- `library/videos/<video-id>/transcript.md`
- `library/videos/<video-id>/context.md`
- `library/themes/<theme-slug>/README.md`
- `library/themes/<theme-slug>/theme.json`
- `library/index/README.md`
- `library/index/channels.json`
- `library/index/themes.json`
- `library/index/search_index.json`
- `library/metadata/catalog.jsonl`
- `library/metadata/embeddings.jsonl`
- `library/bundles/channel__*.md`
- `library/bundles/theme__*.md`
- `library/bundles/query__*.md`

## Metadata Model

Each video record is normalized into:

- channel identity
- title
- published date
- transcript language/source
- word count
- quality score
- summary
- notable quotes
- tags
- themes
- relative paths to transcript/context/channel views

## Initial Theme Layer

Theme classification is local and heuristic for now.

Current taxonomy includes:

- `stoicism`
- `buddhism`
- `meditation_mindfulness`
- `psychology`
- `philosophy`
- `productivity`
- `science`
- `economics`
- `geopolitics`
- `spirituality`
- `self_improvement`
- `culture_society`
- `technology_ai`
- `business_entrepreneurship`

This layer is intentionally simple and replaceable.

## Retrieval Layer

The repo now includes a lightweight local embedding index:

- `library/metadata/embeddings.jsonl`

These embeddings are deterministic hashed token vectors, not model-grade semantic embeddings.
They exist to give the repo:

- targeted retrieval today
- no external dependency
- a stable interface to replace later with Axon or another embedding backend

Search:

```powershell
python .\scripts\build_library_from_db.py search .\openclaw_live --query "stoic discipline focus"
```

## LLM Bundles

Generate a query bundle:

```powershell
python .\scripts\build_library_from_db.py bundle .\openclaw_live --query "mindfulness and breathing"
```

This writes:

- `library/bundles/query__mindfulness-and-breathing.md`

Use bundles when you want to hand a chosen slice of the corpus to an LLM without dumping the full library.

## Recommended Usage Pattern

1. `manage_youtube_pipeline.ps1 -Action sync`
2. `build_library_from_db.py build .\openclaw_live`
3. `build_library_from_db.py search .\openclaw_live --query "..."`
4. `build_library_from_db.py bundle .\openclaw_live --query "..."`
5. Pass the resulting bundle or specific `context.md` files to the LLM

## Future Replacement Path

When you are ready for a stronger retrieval layer:

- keep `catalog.jsonl` as the structured source of truth
- replace `embeddings.jsonl` generation with Axon or another vector backend
- keep the same channel/video/theme bundle outputs so agent workflows do not need to change
