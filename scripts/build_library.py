#!/usr/bin/env python3
"""Build a local transcript library and retrieval index from the pipeline database."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_SEARCH_LIMIT = 8
# Full-text index of the library, an SQLite FTS5 table ranked with BM25.
SEARCH_INDEX = "search.sqlite"
# Porter stemming makes "closing" match "close" and "sales" match "sale".
# remove_diacritics makes "cafe" match "café".
SEARCH_TOKENIZER = "porter unicode61 remove_diacritics 2"
THEME_KEYWORDS = {
    "ai": ["llm", "gpt", "agent", "prompt", "machine learning", "artificial intelligence", "neural"],
    "business": ["startup", "sales", "marketing", "pricing", "saas", "revenue", "founder"],
    "software": ["python", "typescript", "javascript", "docker", "kubernetes", "api", "database", "devops"],
    "design": ["design", "ux", "ui", "typography", "brand", "figma"],
    "media": ["youtube", "podcast", "editing", "camera", "storytelling", "creator"],
    "productivity": ["workflow", "automation", "notes", "calendar", "email", "meeting"],
}


@dataclass(frozen=True)
class VideoItem:
    video_id: str
    title: str
    channel_id: str
    channel_name: str
    channel_slug: str
    url: str
    published_at: str
    description: str
    transcript_text: str
    transcript_source: str
    duration_seconds: int | None = None
    themes: tuple[str, ...] = field(default_factory=tuple)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build", help="Build the library outputs.")
    build_parser.add_argument("root", nargs="?", default=".", help="Pipeline root directory")

    search_parser = subparsers.add_parser("search", help="Search the local library index.")
    search_parser.add_argument("root", help="Pipeline root directory")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT, help="Maximum results")

    bundle_parser = subparsers.add_parser("bundle", help="Create an LLM bundle from the local library.")
    bundle_parser.add_argument("root", help="Pipeline root directory")
    bundle_parser.add_argument("query", help="Search query used to gather bundle items")
    bundle_parser.add_argument("--limit", type=int, default=DEFAULT_SEARCH_LIMIT, help="Maximum items")
    bundle_parser.add_argument("--name", help="Optional bundle name")

    return parser.parse_args()


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def sanitize_title(title: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', " ", title).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:140] or fallback


def connect_database(root: Path) -> sqlite3.Connection:
    db_path = root / "db" / "pipeline.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Missing database: {db_path}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def detect_themes(title: str, description: str, transcript_text: str) -> tuple[str, ...]:
    blob = " ".join(part for part in (title, description, transcript_text[:8000]) if part).lower()
    matches = [theme for theme, keywords in THEME_KEYWORDS.items() if any(keyword in blob for keyword in keywords)]
    return tuple(sorted(matches)) or ("general",)


def write_search_index(path: Path, items: Sequence[VideoItem]) -> None:
    """Index the title, description and transcript of every video for BM25 search."""
    connection = sqlite3.connect(path)
    try:
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE videos USING fts5("
                f"video_id UNINDEXED, title, description, transcript, tokenize = '{SEARCH_TOKENIZER}')"
            )
        except sqlite3.OperationalError as error:
            raise RuntimeError(
                f"The search index needs SQLite's FTS5 extension, which this Python's sqlite3 lacks: {error}"
            ) from error
        with connection:
            connection.executemany(
                "INSERT INTO videos (video_id, title, description, transcript) VALUES (?, ?, ?, ?)",
                [(item.video_id, item.title, item.description, item.transcript_text) for item in items],
            )
    finally:
        connection.close()


def match_any_word(query: str) -> str:
    """An FTS5 query that matches documents holding any word of the free-text query.

    Each word is quoted, so FTS5 operators typed by the user (AND, NOT, *, quotes)
    are searched as plain words.
    """
    return " OR ".join(f'"{word}"' for word in re.findall(r"\w+", query))


# Reads the schema that scripts/scrape.py creates (init_db): channels, videos, transcripts.
# A channel whose `flag` column is set is left out of the library.
VIDEO_QUERY = """
    SELECT
        v.id AS video_id,
        COALESCE(NULLIF(v.title, ''), 'Untitled video') AS title,
        v.channel_id AS channel_id,
        COALESCE(NULLIF(c.name, ''), v.channel_id, 'Unknown channel') AS channel_name,
        'https://www.youtube.com/watch?v=' || v.id AS url,
        COALESCE(v.published_at, '') AS published_at,
        COALESCE(v.description, '') AS description,
        t.raw_text AS transcript_text,
        COALESCE(v.transcript_source, 'auto-sub') AS transcript_source,
        v.duration_seconds AS duration_seconds
    FROM videos v
    JOIN transcripts t ON t.video_id = v.id
    LEFT JOIN channels c ON c.id = v.channel_id
    WHERE c.flag IS NULL
      AND COALESCE(t.raw_text, '') <> ''
    ORDER BY channel_name, published_at, title
"""


def assign_channel_slugs(channels: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Map each channel id to a readable folder name, unique across channels."""
    slugs: dict[str, str] = {}
    taken: set[str] = set()
    for channel_id, channel_name in channels:
        if channel_id in slugs:
            continue
        slug = slugify(channel_name, slugify(channel_id, "channel"))
        if slug in taken:
            slug = f"{slug}-{slugify(channel_id, 'channel')}"
        slugs[channel_id] = slug
        taken.add(slug)
    return slugs


def fetch_video_items(connection: sqlite3.Connection) -> list[VideoItem]:
    rows = connection.execute(VIDEO_QUERY).fetchall()
    channel_slugs = assign_channel_slugs((str(row["channel_id"] or ""), str(row["channel_name"])) for row in rows)

    items: list[VideoItem] = []
    for row in rows:
        channel_name = str(row["channel_name"])
        channel_id = str(row["channel_id"] or "")
        channel_slug = channel_slugs[channel_id]
        transcript_text = str(row["transcript_text"] or "").strip()
        description = str(row["description"] or "").strip()
        themes = detect_themes(str(row["title"] or ""), description, transcript_text)
        duration_value = row["duration_seconds"]
        duration_seconds = int(duration_value) if duration_value is not None and str(duration_value).strip() else None

        items.append(
            VideoItem(
                video_id=str(row["video_id"]),
                title=str(row["title"] or "Untitled video"),
                channel_id=channel_id,
                channel_name=channel_name,
                channel_slug=channel_slug,
                url=str(row["url"] or ""),
                published_at=str(row["published_at"] or ""),
                description=description,
                transcript_text=transcript_text,
                transcript_source=str(row["transcript_source"] or "database"),
                duration_seconds=duration_seconds,
                themes=themes,
            )
        )
    return items


def render_transcript(item: VideoItem) -> str:
    lines = [
        f"# {item.title}",
        "",
        f"- Video ID: `{item.video_id}`",
        f"- Channel: {item.channel_name}",
        f"- Channel Slug: `{item.channel_slug}`",
        f"- Published: {item.published_at or 'Unknown'}",
        f"- URL: {item.url}",
        f"- Themes: {', '.join(item.themes)}",
        f"- Transcript Source: {item.transcript_source}",
    ]
    if item.duration_seconds is not None:
        lines.append(f"- Duration Seconds: {item.duration_seconds}")
    lines.extend(["", "## Description", "", item.description or "_No description available._", "", "## Transcript", "", item.transcript_text, ""])
    return "\n".join(lines)


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_library(root: Path) -> dict[str, int]:
    library_root = root / "library"
    temp_root = root / ".library-build"
    ensure_clean_dir(temp_root)

    with connect_database(root) as connection:
        items = fetch_video_items(connection)

    videos_dir = temp_root / "videos"
    channels_dir = temp_root / "channels"
    themes_dir = temp_root / "themes"
    bundles_dir = temp_root / "bundles"
    metadata_dir = temp_root / "metadata"

    for directory in (videos_dir, channels_dir, themes_dir, bundles_dir, metadata_dir):
        directory.mkdir(parents=True, exist_ok=True)

    catalog_rows: list[dict[str, object]] = []
    by_channel: dict[str, list[VideoItem]] = defaultdict(list)
    by_theme: dict[str, list[VideoItem]] = defaultdict(list)
    by_channel_name: dict[str, str] = {}

    for item in items:
        by_channel[item.channel_slug].append(item)
        by_channel_name[item.channel_slug] = item.channel_name
        for theme in item.themes:
            by_theme[theme].append(item)

        video_dir = videos_dir / item.video_id
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / "transcript.md").write_text(render_transcript(item), encoding="utf-8")
        write_json(video_dir / "metadata.json", asdict(item))

        document = {
            "video_id": item.video_id,
            "title": item.title,
            "channel_slug": item.channel_slug,
            "channel_name": item.channel_name,
            "themes": list(item.themes),
            "published_at": item.published_at,
            "url": item.url,
            "path": str((Path("videos") / item.video_id / "transcript.md").as_posix()),
            "summary": (item.description or item.transcript_text[:280]).strip(),
        }
        catalog_rows.append(document)

    for channel_slug, channel_items in sorted(by_channel.items()):
        channel_dir = channels_dir / channel_slug
        channel_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {by_channel_name[channel_slug]}",
            "",
            f"- Channel Slug: `{channel_slug}`",
            f"- Videos: {len(channel_items)}",
            "",
            "## Videos",
            "",
        ]
        for item in sorted(channel_items, key=lambda current: ((current.published_at or ""), current.title.lower())):
            transcript_rel = Path("..") / "videos" / item.video_id / "transcript.md"
            lines.append(f"- [{item.title}]({transcript_rel.as_posix()})")
        lines.append("")
        (channel_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    for theme, theme_items in sorted(by_theme.items()):
        theme_dir = themes_dir / theme
        theme_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# Theme: {theme}",
            "",
            f"- Videos: {len(theme_items)}",
            "",
            "## Matches",
            "",
        ]
        for item in sorted(theme_items, key=lambda current: (current.channel_slug, current.title.lower())):
            transcript_rel = Path("..") / "videos" / item.video_id / "transcript.md"
            lines.append(f"- [{item.title}]({transcript_rel.as_posix()}) ({item.channel_name})")
        lines.append("")
        (theme_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")

    latest_bundle_path = bundles_dir / "all-transcripts.md"
    bundle_lines = [
        "# Bundle: all-transcripts",
        "",
        f"- Videos: {len(items)}",
        "",
    ]
    for item in items:
        bundle_lines.extend(
            [
                f"## {item.title} ({item.video_id})",
                "",
                f"Channel: {item.channel_name}",
                f"URL: {item.url}",
                f"Themes: {', '.join(item.themes)}",
                "",
                item.transcript_text,
                "",
            ]
        )
    latest_bundle_path.write_text("\n".join(bundle_lines), encoding="utf-8")

    write_json(
        metadata_dir / "summary.json",
        {
            "videos": len(items),
            "channels": len(by_channel),
            "themes": len(by_theme),
            "generated_dir": str(library_root),
        },
    )
    write_jsonl(metadata_dir / "catalog.jsonl", catalog_rows)
    write_search_index(metadata_dir / SEARCH_INDEX, items)

    # -- by_channel: human-readable transcript files named by title --
    by_channel_dir = temp_root / 'by_channel'
    for channel_slug, channel_items in sorted(by_channel.items()):
        ch_dir = by_channel_dir / channel_slug
        ch_dir.mkdir(parents=True, exist_ok=True)
        for item in channel_items:
            safe_name = sanitize_title(item.title, item.video_id)
            dst = ch_dir / f'{safe_name}.md'
            if dst.exists():
                dst = ch_dir / f'{safe_name} [{item.video_id[:6]}].md'
            src = videos_dir / item.video_id / 'transcript.md'
            if src.exists():
                shutil.copy2(src, dst)

    if library_root.exists():
        shutil.rmtree(library_root)
    shutil.move(str(temp_root), str(library_root))

    return {
        "videos": len(items),
        "channels": len(by_channel),
        "themes": len(by_theme),
    }


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def search_library(root: Path, query: str, limit: int) -> list[dict[str, object]]:
    """Rank the videos that contain words of the query with BM25, best first.

    Videos that share no word with the query are not returned. Each result is its
    catalog entry plus a positive ``score``: the higher, the better the match.
    """
    metadata_dir = root / "library" / "metadata"
    catalog = {row["video_id"]: row for row in load_jsonl(metadata_dir / "catalog.jsonl")}
    index_path = metadata_dir / SEARCH_INDEX
    if not catalog or not index_path.is_file():
        raise RuntimeError("Library index not found. Run build_library.py build <root> first.")

    match = match_any_word(query)
    if not match:
        return []
    connection = sqlite3.connect(index_path)
    try:
        rows = connection.execute(
            "SELECT video_id, bm25(videos) FROM videos WHERE videos MATCH ? ORDER BY bm25(videos) LIMIT ?",
            (match, limit),
        ).fetchall()
    finally:
        connection.close()

    results: list[dict[str, object]] = []
    for video_id, rank in rows:
        entry = dict(catalog.get(video_id, {}))
        # FTS5's bm25() is negative for every match, and more negative is better.
        entry["score"] = float(f"{-rank:.4g}")
        results.append(entry)
    return results


def build_search_bundle(root: Path, query: str, limit: int, name: str | None) -> Path:
    results = search_library(root, query, limit)
    if not results:
        raise RuntimeError("Search returned no results.")

    bundle_name = slugify(name or query, "bundle")
    bundle_path = root / "library" / "bundles" / f"{bundle_name}.md"
    lines = [
        f"# Bundle: {bundle_name}",
        "",
        f"- Query: {query}",
        f"- Results: {len(results)}",
        "",
    ]
    for result in results:
        transcript_path = root / "library" / str(result["path"])
        transcript_text = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
        lines.extend(
            [
                f"## {result['title']} ({result['video_id']})",
                "",
                f"Channel: {result['channel_name']}",
                f"URL: {result['url']}",
                f"Score: {result['score']}",
                "",
                transcript_text,
                "",
            ]
        )
    bundle_path.write_text("\n".join(lines), encoding="utf-8")
    return bundle_path


def main() -> None:
    args = parse_args()
    command = args.command
    root = Path(args.root).expanduser().resolve()
    # Titles are printed as UTF-8 JSON. Without this, a piped stdout on Windows
    # falls back to the ANSI code page and crashes on the first emoji in a title.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if command == "build":
        summary = build_library(root)
        print(json.dumps(summary, ensure_ascii=False))
        return

    if command == "search":
        results = search_library(root, args.query, args.limit)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if command == "bundle":
        bundle_path = build_search_bundle(root, args.query, args.limit, args.name)
        print(bundle_path)
        return

    raise RuntimeError(f"Unsupported command: {command}")


if __name__ == "__main__":
    main()
