#!/usr/bin/env python3
"""Build a local transcript library and retrieval index from the pipeline database."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


EMBEDDING_DIMENSION = 96
DEFAULT_SEARCH_LIMIT = 8
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
    subparsers = parser.add_subparsers(dest="command")

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

    parser.add_argument("root", nargs="?", help=argparse.SUPPRESS)
    return parser.parse_args()


def resolve_command(args: argparse.Namespace) -> tuple[str, Path]:
    if args.command:
        return args.command, Path(args.root).expanduser().resolve()
    root = Path(args.root or ".").expanduser().resolve()
    return "build", root


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


def detect_transcript_expression(connection: sqlite3.Connection) -> str:
    candidates = (
        "COALESCE(v.transcript, v.transcript_text, t.text, t.transcript_text)",
        "COALESCE(v.transcript_text, t.text, t.transcript_text)",
        "COALESCE(v.transcript, t.text)",
        "t.text",
    )
    for candidate in candidates:
        try:
            connection.execute(
                f"""
                SELECT {candidate}
                FROM videos v
                LEFT JOIN transcripts t ON t.video_id = COALESCE(v.video_id, v.id)
                LIMIT 1
                """
            ).fetchone()
            return candidate
        except sqlite3.OperationalError:
            continue
    raise RuntimeError("Could not determine transcript columns in pipeline.db.")


def detect_optional_expression(connection: sqlite3.Connection, candidates: Sequence[str], fallback: str) -> str:
    for candidate in candidates:
        try:
            connection.execute(f"SELECT {candidate} FROM videos v LIMIT 1").fetchone()
            return candidate
        except sqlite3.OperationalError:
            continue
    return fallback


def detect_themes(title: str, description: str, transcript_text: str) -> tuple[str, ...]:
    blob = " ".join(part for part in (title, description, transcript_text[:8000]) if part).lower()
    matches = [theme for theme, keywords in THEME_KEYWORDS.items() if any(keyword in blob for keyword in keywords)]
    return tuple(sorted(matches)) or ("general",)


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", text.lower())


def embed_text(text: str, *, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    vector = [0.0] * dimension
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + (digest[5] / 255.0)
        vector[index] += sign * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [round(value / norm, 8) for value in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def fetch_video_items(connection: sqlite3.Connection) -> list[VideoItem]:
    transcript_expression = detect_transcript_expression(connection)
    channel_id_expr = detect_optional_expression(connection, ("COALESCE(v.channel_id, '')", "v.uploader_id"), "''")
    duration_expr = detect_optional_expression(connection, ("v.duration_seconds", "v.length_seconds", "v.duration"), "NULL")
    description_expr = detect_optional_expression(connection, ("COALESCE(v.description, '')", "COALESCE(v.summary, '')"), "''")

    query = f"""
        SELECT
            COALESCE(v.video_id, v.id) AS video_id,
            COALESCE(v.title, v.video_title, 'Untitled video') AS title,
            {channel_id_expr} AS channel_id,
            COALESCE(v.channel_name, v.channel_title, v.uploader, 'Unknown channel') AS channel_name,
            COALESCE(v.url, 'https://www.youtube.com/watch?v=' || COALESCE(v.video_id, v.id)) AS url,
            COALESCE(v.published_at, v.upload_date, '') AS published_at,
            {description_expr} AS description,
            {transcript_expression} AS transcript_text,
            COALESCE(t.source, v.transcript_source, 'database') AS transcript_source,
            {duration_expr} AS duration_seconds
        FROM videos v
        LEFT JOIN transcripts t ON t.video_id = COALESCE(v.video_id, v.id)
        WHERE COALESCE({transcript_expression}, '') <> ''
        ORDER BY COALESCE(v.channel_name, v.channel_title, v.uploader, ''), COALESCE(v.published_at, v.upload_date, ''), COALESCE(v.title, v.video_title, '')
    """

    items: list[VideoItem] = []
    for row in connection.execute(query):
        channel_name = str(row["channel_name"] or "Unknown channel")
        channel_id = str(row["channel_id"] or "")
        channel_slug = slugify(channel_id or channel_name, str(row["video_id"]))
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
    embedding_rows: list[dict[str, object]] = []
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

        embedding_rows.append(
            {
                "video_id": item.video_id,
                "title": item.title,
                "channel_slug": item.channel_slug,
                "themes": list(item.themes),
                "embedding": embed_text(" ".join((item.title, item.description, item.transcript_text[:10000]))),
            }
        )

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
    write_jsonl(metadata_dir / "embeddings.jsonl", embedding_rows)

    # -- by_channel: human-readable transcript files named by title --
    by_channel_dir = temp_root / 'by_channel'
    for channel_slug, items in sorted(by_channel.items()):
        ch_dir = by_channel_dir / channel_slug
        ch_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
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
    metadata_dir = root / "library" / "metadata"
    catalog = {row["video_id"]: row for row in load_jsonl(metadata_dir / "catalog.jsonl")}
    embeddings = load_jsonl(metadata_dir / "embeddings.jsonl")
    if not catalog or not embeddings:
        raise RuntimeError("Library index not found. Run build_library.py build <root> first.")

    query_embedding = embed_text(query)
    scored: list[tuple[float, dict[str, object]]] = []
    for row in embeddings:
        embedding = row.get("embedding")
        if not isinstance(embedding, list):
            continue
        score = cosine_similarity(query_embedding, [float(value) for value in embedding])
        video_id = str(row["video_id"])
        entry = dict(catalog.get(video_id, {}))
        entry["score"] = round(score, 6)
        scored.append((score, entry))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored[:limit]]


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
    command, root = resolve_command(args)

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
