#!/usr/bin/env python3
"""Build transcript markdown files from the pipeline database."""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TranscriptRow:
    video_id: str
    title: str
    channel_name: str
    channel_slug: str
    url: str
    published_at: str
    transcript_text: str
    transcript_source: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Pipeline root directory containing db/pipeline.db",
    )
    return parser.parse_args()


def slugify(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def sanitize_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:140] or fallback


def connect_database(root: Path) -> sqlite3.Connection:
    db_path = root / "db" / "pipeline.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Missing database: {db_path}")
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def list_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def fetch_transcripts(connection: sqlite3.Connection) -> Iterable[TranscriptRow]:
    tables = list_tables(connection)
    if "videos" not in tables:
        raise RuntimeError("Expected a videos table in pipeline.db.")

    transcript_expression = None
    for candidate in (
        "COALESCE(v.transcript, v.transcript_text, t.text, t.transcript_text)",
        "COALESCE(v.transcript_text, t.text, t.transcript_text)",
        "COALESCE(v.transcript, t.text)",
        "t.text",
    ):
        try:
            connection.execute(
                f"""
                SELECT {candidate}
                FROM videos v
                LEFT JOIN transcripts t ON t.video_id = v.video_id
                LIMIT 1
                """
            ).fetchone()
            transcript_expression = candidate
            break
        except sqlite3.OperationalError:
            continue

    if transcript_expression is None:
        raise RuntimeError("Could not determine transcript columns.")

    query = f"""
        SELECT
            COALESCE(v.video_id, v.id) AS video_id,
            COALESCE(v.title, v.video_title, 'Untitled video') AS title,
            COALESCE(v.channel_name, v.channel_title, v.uploader, 'Unknown channel') AS channel_name,
            COALESCE(v.channel_slug, v.channel_id, '') AS channel_key,
            COALESCE(v.url, 'https://www.youtube.com/watch?v=' || COALESCE(v.video_id, v.id)) AS url,
            COALESCE(v.published_at, v.upload_date, '') AS published_at,
            {transcript_expression} AS transcript_text,
            COALESCE(t.source, v.transcript_source, 'database') AS transcript_source
        FROM videos v
        LEFT JOIN transcripts t ON t.video_id = COALESCE(v.video_id, v.id)
        WHERE COALESCE({transcript_expression}, '') <> ''
        ORDER BY COALESCE(v.channel_name, v.channel_title, v.uploader, ''), COALESCE(v.published_at, v.upload_date, ''), COALESCE(v.title, v.video_title, '')
    """

    for row in connection.execute(query):
        channel_name = str(row["channel_name"] or "Unknown channel")
        channel_key = str(row["channel_key"] or "")
        yield TranscriptRow(
            video_id=str(row["video_id"]),
            title=str(row["title"] or "Untitled video"),
            channel_name=channel_name,
            channel_slug=slugify(channel_key or channel_name, str(row["video_id"])),
            url=str(row["url"] or ""),
            published_at=str(row["published_at"] or ""),
            transcript_text=str(row["transcript_text"] or "").strip(),
            transcript_source=str(row["transcript_source"] or "database"),
        )


def render_markdown(row: TranscriptRow) -> str:
    header = [
        f"# {row.title}",
        "",
        f"- Video ID: `{row.video_id}`",
        f"- Channel: {row.channel_name}",
        f"- Published: {row.published_at or 'Unknown'}",
        f"- URL: {row.url}",
        f"- Transcript Source: {row.transcript_source}",
        "",
        "## Transcript",
        "",
        row.transcript_text,
        "",
    ]
    return "\n".join(header)


def build_transcripts(root: Path) -> int:
    output_root = root / "transcripts" / "by_video"
    output_root.mkdir(parents=True, exist_ok=True)

    written = 0
    with connect_database(root) as connection:
        for row in fetch_transcripts(connection):
            transcript_dir = output_root / row.video_id
            transcript_dir.mkdir(parents=True, exist_ok=True)
            transcript_path = transcript_dir / "transcript.md"
            transcript_path.write_text(render_markdown(row), encoding="utf-8")

            title_path = transcript_dir / f"{sanitize_filename(row.title, row.video_id)}.md"
            if not title_path.exists():
                title_path.write_text(render_markdown(row), encoding="utf-8")
            written += 1

    return written


def main() -> None:
    args = parse_args()
    root = Path(args.root).expanduser().resolve()
    count = build_transcripts(root)
    print(f"built {count} transcript files under {root / 'transcripts' / 'by_video'}")


if __name__ == "__main__":
    main()
