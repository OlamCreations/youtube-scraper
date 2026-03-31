import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


THEME_KEYWORDS = {
    "stoicism": ["stoic", "stoicism", "marcus aurelius", "seneca", "epictetus"],
    "buddhism": ["buddhism", "buddhist", "dharma", "zen", "thich nhat hanh", "mindful"],
    "meditation_mindfulness": ["meditation", "mindfulness", "breath", "presence", "awareness"],
    "psychology": ["psychology", "trauma", "depression", "anxiety", "inner child", "therapy"],
    "philosophy": ["philosophy", "philosophical", "meaning", "ethics", "existential", "virtue"],
    "productivity": ["productivity", "discipline", "focus", "procrastination", "habit", "deep work"],
    "science": ["science", "physics", "math", "biology", "chemistry", "universe", "space"],
    "economics": ["economics", "inflation", "market", "capitalism", "recession", "trade"],
    "geopolitics": ["war", "geopolitics", "nation", "empire", "state", "foreign policy"],
    "spirituality": ["soul", "sacred", "spiritual", "god", "faith", "prayer", "mystic"],
    "self_improvement": ["self improvement", "improve your life", "character", "growth", "resilience"],
    "culture_society": ["culture", "society", "civilization", "modern life", "social", "community"],
    "technology_ai": ["technology", "ai", "artificial intelligence", "machine learning", "software"],
    "business_entrepreneurship": ["business", "startup", "entrepreneur", "founder", "sales", "company"],
}


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or fallback


def sanitize_title(title: str, video_id: str) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip())
    text = re.sub(r"[^A-Za-z0-9 _\-\.,\(\)\[\]]+", "", text)
    text = text.strip(" .")
    if not text:
        text = f"video_{video_id}"
    return text[:100].rstrip(" .")


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", (text or "").lower())


def clip_text(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def parse_json_payload(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def hash_embedding(text: str, dims: int = 64) -> list[float]:
    buckets = [0.0] * dims
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % dims
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        buckets[index] += sign
    norm = math.sqrt(sum(value * value for value in buckets))
    if norm == 0:
        return buckets
    return [round(value / norm, 6) for value in buckets]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    return sum(l * r for l, r in zip(left, right))


def replace_tree_atomic(source: Path, target: Path) -> None:
    backup = target.with_name(f"{target.name}__bak")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.replace(backup)
    source.replace(target)
    if backup.exists():
        shutil.rmtree(backup)


@dataclass
class VideoRecord:
    video_id: str
    channel_id: str
    channel_name: str
    channel_handle: str
    channel_category: str
    channel_language: str
    title: str
    description: str
    published_at: str
    transcript_source: str
    transcript_language: str
    word_count: int
    quality_score: float | None
    transcript_text: str
    summary: str
    notable_quotes: list[str]
    insights_model: str
    tags: list[str]
    themes: list[str]
    embedding: list[float]
    search_text: str


def derive_themes(
    *,
    category: str,
    title: str,
    description: str,
    transcript_text: str,
    insight_payload: dict[str, Any],
) -> list[str]:
    haystack = " ".join(
        [
            category or "",
            title or "",
            description or "",
            clip_text(transcript_text, 2400),
            " ".join(str(item) for item in insight_payload.get("themes", []) if item),
            " ".join(str(item) for item in insight_payload.get("thematic_threads", []) if item),
            str(insight_payload.get("summary", "") or ""),
        ]
    ).lower()

    themes: list[str] = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            themes.append(theme)

    category_slug = slugify(category, "general")
    if category_slug and category_slug not in themes:
        themes.append(category_slug)
    if not themes:
        themes.append("general")
    return sorted(dict.fromkeys(themes))


def derive_tags(
    *,
    channel_name: str,
    channel_handle: str,
    category: str,
    language: str,
    transcript_source: str,
    insight_payload: dict[str, Any],
    themes: list[str],
) -> list[str]:
    tags = [
        slugify(channel_name, "channel"),
        slugify(channel_handle.replace("@", ""), "handle") if channel_handle else "",
        slugify(category, "general"),
        slugify(language, "en"),
        slugify(transcript_source, "transcript"),
    ]
    for item in insight_payload.get("themes", []):
        if isinstance(item, str):
            tags.append(slugify(item, "theme"))
    for item in insight_payload.get("thematic_threads", []):
        if isinstance(item, str):
            tags.append(slugify(item, "thread"))
    tags.extend(themes)
    return sorted(tag for tag in dict.fromkeys(tags) if tag)


def load_video_records(root: Path) -> list[VideoRecord]:
    db_path = root / "db" / "pipeline.db"
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    query = """
    SELECT
      v.id,
      v.channel_id,
      c.name,
      c.handle,
      c.category,
      c.language,
      v.title,
      COALESCE(v.description, ''),
      COALESCE(v.published_at, ''),
      COALESCE(v.transcript_source, ''),
      COALESCE(t.language, c.language, 'en'),
      COALESCE(t.word_count, 0),
      t.quality_score,
      COALESCE(t.raw_text, ''),
      COALESCE(i.content, ''),
      COALESCE(i.model_used, '')
    FROM videos v
    JOIN channels c ON c.id = v.channel_id
    LEFT JOIN transcripts t ON t.video_id = v.id
    LEFT JOIN (
      SELECT i1.video_id, i1.content, i1.model_used
      FROM insights i1
      JOIN (
        SELECT video_id, MAX(id) AS max_id
        FROM insights
        GROUP BY video_id
      ) latest ON latest.video_id = i1.video_id AND latest.max_id = i1.id
    ) i ON i.video_id = v.id
    WHERE t.video_id IS NOT NULL
    ORDER BY c.name, v.published_at, v.id
    """

    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(query)
        rows = cur.fetchall()

    records: list[VideoRecord] = []
    for row in rows:
        (
            video_id,
            channel_id,
            channel_name,
            channel_handle,
            channel_category,
            channel_language,
            title,
            description,
            published_at,
            transcript_source,
            transcript_language,
            word_count,
            quality_score,
            transcript_text,
            insight_content,
            insights_model,
        ) = row
        payload = parse_json_payload(insight_content)
        summary = str(payload.get("summary", "") or "")
        quotes = [str(item) for item in payload.get("notable_quotes", []) if isinstance(item, str)]
        themes = derive_themes(
            category=channel_category,
            title=title,
            description=description,
            transcript_text=transcript_text,
            insight_payload=payload,
        )
        tags = derive_tags(
            channel_name=channel_name,
            channel_handle=channel_handle or "",
            category=channel_category,
            language=transcript_language or channel_language or "en",
            transcript_source=transcript_source,
            insight_payload=payload,
            themes=themes,
        )
        search_text = " ".join(
            [
                channel_name or "",
                channel_handle or "",
                channel_category or "",
                title or "",
                description or "",
                summary,
                " ".join(themes),
                " ".join(tags),
                clip_text(transcript_text, 1800),
            ]
        )
        records.append(
            VideoRecord(
                video_id=video_id,
                channel_id=channel_id,
                channel_name=channel_name,
                channel_handle=channel_handle or "",
                channel_category=channel_category or "general",
                channel_language=channel_language or "en",
                title=title,
                description=description,
                published_at=published_at,
                transcript_source=transcript_source,
                transcript_language=transcript_language or channel_language or "en",
                word_count=int(word_count or 0),
                quality_score=quality_score,
                transcript_text=transcript_text,
                summary=summary,
                notable_quotes=quotes[:3],
                insights_model=insights_model,
                tags=tags,
                themes=themes,
                embedding=hash_embedding(search_text),
                search_text=search_text,
            )
        )
    return records


def build_library(root: Path, library_dir: Path | None = None) -> Path:
    records = load_video_records(root)
    if not records:
        raise RuntimeError("no transcript-backed videos found in pipeline.db")

    target = library_dir or (root / "library")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="library_build_", dir=target.parent))

    channels_dir = temp_root / "channels"
    videos_dir = temp_root / "videos"
    themes_dir = temp_root / "themes"
    metadata_dir = temp_root / "metadata"
    index_dir = temp_root / "index"
    bundles_dir = temp_root / "bundles"
    for path in (channels_dir, videos_dir, themes_dir, metadata_dir, index_dir, bundles_dir):
        path.mkdir(parents=True, exist_ok=True)

    by_channel: dict[str, list[VideoRecord]] = defaultdict(list)
    by_theme: dict[str, list[VideoRecord]] = defaultdict(list)
    catalog_entries: list[dict[str, Any]] = []

    for record in records:
        channel_slug = slugify(record.channel_name, record.channel_id.lower())
        safe_title = sanitize_title(record.title, record.video_id)
        video_dir = videos_dir / record.video_id
        video_dir.mkdir(parents=True, exist_ok=True)

        transcript_path = Path("videos", record.video_id, "transcript.md").as_posix()
        context_path = Path("videos", record.video_id, "context.md").as_posix()
        metadata_path = Path("videos", record.video_id, "metadata.json").as_posix()

        video_metadata = {
            "video_id": record.video_id,
            "title": record.title,
            "channel": {
                "id": record.channel_id,
                "name": record.channel_name,
                "handle": record.channel_handle,
                "slug": channel_slug,
                "category": record.channel_category,
                "language": record.channel_language,
            },
            "published_at": record.published_at,
            "transcript": {
                "language": record.transcript_language,
                "source": record.transcript_source,
                "word_count": record.word_count,
                "quality_score": record.quality_score,
            },
            "summary": record.summary,
            "quotes": record.notable_quotes,
            "themes": record.themes,
            "tags": record.tags,
            "paths": {
                "transcript": transcript_path,
                "context": context_path,
                "channel": Path("channels", channel_slug, "README.md").as_posix(),
            },
        }
        (video_dir / "metadata.json").write_text(json.dumps(video_metadata, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        (video_dir / "transcript.md").write_text(
            f"# {record.title}\n\n"
            f"- video_id: `{record.video_id}`\n"
            f"- channel: `{record.channel_name}`\n"
            f"- handle: `{record.channel_handle}`\n"
            f"- published_at: `{record.published_at or 'unknown'}`\n"
            f"- transcript_language: `{record.transcript_language}`\n"
            f"- transcript_source: `{record.transcript_source or 'unknown'}`\n"
            f"- word_count: `{record.word_count}`\n"
            f"- quality_score: `{record.quality_score}`\n\n"
            f"{record.transcript_text}\n",
            encoding="utf-8",
        )
        (video_dir / "context.md").write_text(
            f"# Context Bundle: {record.title}\n\n"
            f"## Summary\n\n{record.summary or 'No summary available.'}\n\n"
            f"## Themes\n\n- " + "\n- ".join(record.themes) + "\n\n"
            f"## Tags\n\n- " + "\n- ".join(record.tags) + "\n\n"
            f"## Notable Quotes\n\n" + (
                "\n".join(f"> {quote}" for quote in record.notable_quotes) if record.notable_quotes else "_No quotes extracted._"
            ) + "\n\n"
            f"## Retrieval Snippet\n\n{clip_text(record.transcript_text, 1400)}\n",
            encoding="utf-8",
        )

        catalog_entry = {
            "video_id": record.video_id,
            "title": record.title,
            "safe_title": safe_title,
            "channel_id": record.channel_id,
            "channel_name": record.channel_name,
            "channel_handle": record.channel_handle,
            "channel_slug": channel_slug,
            "channel_category": record.channel_category,
            "published_at": record.published_at,
            "language": record.transcript_language,
            "word_count": record.word_count,
            "quality_score": record.quality_score,
            "summary": record.summary,
            "themes": record.themes,
            "tags": record.tags,
            "transcript_path": transcript_path,
            "context_path": context_path,
            "metadata_path": metadata_path,
        }
        catalog_entries.append(catalog_entry)
        by_channel[channel_slug].append(record)
        for theme in record.themes:
            by_theme[theme].append(record)

    for channel_slug, items in sorted(by_channel.items()):
        channel_dir = channels_dir / channel_slug
        channel_dir.mkdir(parents=True, exist_ok=True)
        first = items[0]
        overview = {
            "channel_id": first.channel_id,
            "channel_name": first.channel_name,
            "channel_handle": first.channel_handle,
            "channel_category": first.channel_category,
            "video_count": len(items),
            "themes": sorted({theme for item in items for theme in item.themes}),
        }
        (channel_dir / "channel.json").write_text(json.dumps(overview, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        lines = [
            f"# Channel Library: {first.channel_name}",
            "",
            f"- channel_id: `{first.channel_id}`",
            f"- handle: `{first.channel_handle}`",
            f"- category: `{first.channel_category}`",
            f"- videos: `{len(items)}`",
            "",
            "## Videos",
            "",
        ]
        for item in items:
            lines.append(
                f"- [{item.title}](../../videos/{item.video_id}/context.md) "
                f"`{item.video_id}` themes={','.join(item.themes[:4])} words={item.word_count}"
            )
        (channel_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (bundles_dir / f"channel__{channel_slug}.md").write_text(
            "\n".join(
                [
                    f"# LLM Bundle: channel/{first.channel_name}",
                    "",
                    f"Use this when you want context scoped to `{first.channel_name}`.",
                    "",
                    "## Priority Videos",
                    "",
                ]
                + [
                    f"### {item.title}\n- video_id: `{item.video_id}`\n- themes: {', '.join(item.themes)}\n- words: {item.word_count}\n\n{clip_text(item.transcript_text, 2000)}\n"
                    for item in sorted(items, key=lambda current: current.word_count, reverse=True)[:12]
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    for theme_slug, items in sorted(by_theme.items()):
        theme_dir = themes_dir / theme_slug
        theme_dir.mkdir(parents=True, exist_ok=True)
        overview = {
            "theme": theme_slug,
            "video_count": len(items),
            "channels": sorted({item.channel_name for item in items}),
        }
        (theme_dir / "theme.json").write_text(json.dumps(overview, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        lines = [
            f"# Theme Library: {theme_slug}",
            "",
            f"- videos: `{len(items)}`",
            f"- channels: `{len(overview['channels'])}`",
            "",
            "## Videos",
            "",
        ]
        for item in sorted(items, key=lambda current: (current.channel_name.lower(), current.title.lower())):
            lines.append(
                f"- [{item.title}](../../videos/{item.video_id}/context.md) "
                f"channel=`{item.channel_name}` published=`{item.published_at or 'unknown'}`"
            )
        (theme_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (bundles_dir / f"theme__{theme_slug}.md").write_text(
            "\n".join(
                [
                    f"# LLM Bundle: theme/{theme_slug}",
                    "",
                    "Use this when you want cross-channel context on one theme.",
                    "",
                ]
                + [
                    f"## {item.title}\n- channel: `{item.channel_name}`\n- video_id: `{item.video_id}`\n- words: {item.word_count}\n\n{clip_text(item.transcript_text, 2000)}\n"
                    for item in sorted(items, key=lambda current: current.word_count, reverse=True)[:15]
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    search_records = [
        {
            "video_id": record.video_id,
            "title": record.title,
            "channel_name": record.channel_name,
            "themes": record.themes,
            "tags": record.tags,
            "summary": record.summary,
            "embedding": record.embedding,
            "context_path": Path("videos", record.video_id, "context.md").as_posix(),
        }
        for record in records
    ]
    embeddings_path = metadata_dir / "embeddings.jsonl"
    catalog_path = metadata_dir / "catalog.jsonl"
    with catalog_path.open("w", encoding="utf-8") as handle:
        for item in catalog_entries:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    with embeddings_path.open("w", encoding="utf-8") as handle:
        for item in search_records:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")

    channel_index = [
        {
            "slug": slug,
            "channel_name": items[0].channel_name,
            "video_count": len(items),
            "path": Path("channels", slug, "README.md").as_posix(),
        }
        for slug, items in sorted(by_channel.items())
    ]
    theme_index = [
        {
            "slug": slug,
            "video_count": len(items),
            "path": Path("themes", slug, "README.md").as_posix(),
        }
        for slug, items in sorted(by_theme.items())
    ]
    (index_dir / "channels.json").write_text(json.dumps(channel_index, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (index_dir / "themes.json").write_text(json.dumps(theme_index, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (index_dir / "search_index.json").write_text(
        json.dumps(
            {
                "video_count": len(records),
                "channel_count": len(by_channel),
                "theme_count": len(by_theme),
                "embedding_dimensions": 64,
                "catalog_path": "metadata/catalog.jsonl",
                "embeddings_path": "metadata/embeddings.jsonl",
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (index_dir / "README.md").write_text(
        "\n".join(
            [
                "# Library Index",
                "",
                f"- videos: `{len(records)}`",
                f"- channels: `{len(by_channel)}`",
                f"- themes: `{len(by_theme)}`",
                "",
                "## Primary Views",
                "",
                "- `channels/` channel-by-channel library",
                "- `videos/` one folder per video with transcript, metadata, and context bundle",
                "- `themes/` cross-channel thematic library",
                "- `bundles/` ready-to-paste context bundles for LLM workflows",
                "- `metadata/catalog.jsonl` structured catalog for tooling",
                "- `metadata/embeddings.jsonl` local hashed embeddings for targeted retrieval",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # ── by_channel: human-readable transcript files named by title ──
    by_channel_dir = temp_root / "by_channel"
    for channel_slug, items in sorted(by_channel.items()):
        ch_dir = by_channel_dir / channel_slug
        ch_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            safe_name = sanitize_title(item.title, item.video_id)
            dst = ch_dir / f"{safe_name}.md"
            if dst.exists():
                dst = ch_dir / f"{safe_name} [{item.video_id[:6]}].md"
            src = videos_dir / item.video_id / "transcript.md"
            if src.exists():
                shutil.copy2(src, dst)

    if target.exists():
        replace_tree_atomic(temp_root, target)
    else:
        temp_root.replace(target)
    return target


def load_embeddings(library_dir: Path) -> list[dict[str, Any]]:
    path = library_dir / "metadata" / "embeddings.jsonl"
    results = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            results.append(json.loads(line))
    return results


def search_library(library_dir: Path, query: str, limit: int = 8) -> list[dict[str, Any]]:
    query_embedding = hash_embedding(query)
    matches = []
    for item in load_embeddings(library_dir):
        score = cosine_similarity(query_embedding, item["embedding"])
        match = dict(item)
        match["score"] = round(score, 6)
        matches.append(match)
    matches.sort(key=lambda current: current["score"], reverse=True)
    return matches[:limit]


def write_query_bundle(library_dir: Path, query: str, limit: int = 8, output_path: Path | None = None) -> Path:
    results = search_library(library_dir, query=query, limit=limit)
    bundle_path = output_path or (library_dir / "bundles" / f"query__{slugify(query, 'query')}.md")
    lines = [
        f"# LLM Query Bundle: {query}",
        "",
        f"- results: `{len(results)}`",
        "",
    ]
    for item in results:
        transcript_excerpt = ""
        transcript_path = library_dir / "videos" / item["video_id"] / "transcript.md"
        if transcript_path.exists():
            raw = transcript_path.read_text(encoding="utf-8", errors="replace")
            transcript_excerpt = clip_text(raw, 2000)
        lines.extend(
            [
                f"## {item['title']}",
                f"- score: `{item['score']}`",
                f"- channel: `{item['channel_name']}`",
                f"- themes: `{', '.join(item['themes'])}`",
                f"- context: `{item['context_path']}`",
                "",
                transcript_excerpt or "No transcript available.",
                "",
            ]
        )
    bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and query a local transcript library from pipeline.db")
    subparsers = parser.add_subparsers(dest="command", required=False)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("root", nargs="?", default=".")
    build_parser.add_argument("--library-dir", default=None)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("root", nargs="?", default=".")
    search_parser.add_argument("--library-dir", default=None)
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--limit", type=int, default=8)

    bundle_parser = subparsers.add_parser("bundle")
    bundle_parser.add_argument("root", nargs="?", default=".")
    bundle_parser.add_argument("--library-dir", default=None)
    bundle_parser.add_argument("--query", required=True)
    bundle_parser.add_argument("--limit", type=int, default=8)
    bundle_parser.add_argument("--output", default=None)

    parser.set_defaults(command="build")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).resolve()
    library_dir = Path(args.library_dir).resolve() if args.library_dir else (root / "library")

    if args.command == "build":
        path = build_library(root=root, library_dir=library_dir)
        print(f"library_built path={path}")
    elif args.command == "search":
        results = search_library(library_dir=library_dir, query=args.query, limit=args.limit)
        print(json.dumps(results, indent=2, ensure_ascii=True))
    elif args.command == "bundle":
        output_path = Path(args.output).resolve() if args.output else None
        path = write_query_bundle(library_dir=library_dir, query=args.query, limit=args.limit, output_path=output_path)
        print(f"bundle_written path={path}")


if __name__ == "__main__":
    main()
