import re
import sqlite3
import shutil
import tempfile
from pathlib import Path


def sanitize_title(title: str, video_id: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = re.sub(r"[^A-Za-z0-9 _\-\.,\(\)\[\]]+", "", t)
    t = t.strip(" .")
    if not t:
        t = f"video_{video_id}"
    if len(t) > 90:
        t = t[:90].rstrip(" .")
    return t


def _replace_tree_atomic(source: Path, target: Path) -> None:
    backup = target.with_name(f"{target.name}__bak")
    if backup.exists():
        shutil.rmtree(backup)
    if target.exists():
        target.replace(backup)
    source.replace(target)
    if backup.exists():
        shutil.rmtree(backup)


def main(root: Path) -> None:
    db = root / "db" / "pipeline.db"
    out_root = root / "transcripts"
    by_video = out_root / "by_video"
    out_root.mkdir(parents=True, exist_ok=True)

    if not db.exists():
        raise FileNotFoundError(f"database not found: {db}")

    with sqlite3.connect(db) as con:
        cur = con.cursor()
        cur.execute("SELECT id, title FROM videos")
        titles = {vid: (title or "").strip() for vid, title in cur.fetchall()}

        cur.execute(
            "SELECT video_id, language, word_count, quality_score, raw_text FROM transcripts ORDER BY id"
        )
        rows = cur.fetchall()

    entries = []
    temp_dir = Path(tempfile.mkdtemp(prefix="transcripts_build_", dir=out_root))
    temp_by_video = temp_dir / "by_video"
    temp_by_video.mkdir(parents=True, exist_ok=True)
    try:
        for video_id, lang, wc, qs, raw_text in rows:
            if not video_id:
                continue
            title = titles.get(video_id, "")
            stem = f"{sanitize_title(title, video_id)}__{video_id}"
            prefix = (video_id[:2] if len(video_id) >= 2 else "zz").lower()
            if not prefix.isalnum():
                prefix = "zz"
            d = temp_by_video / prefix
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{stem}.md"
            content = (
                f"# Transcript for video `{video_id}`\n\n"
                f"- title: {title if title else f'video_{video_id}'}\n"
                f"- language: `{lang}`\n"
                f"- word_count: `{wc}`\n"
                f"- quality_score: `{qs}`\n\n"
                f"{raw_text or ''}\n"
            )
            p.write_text(content, encoding="utf-8")
            entries.append((video_id, title if title else f"video_{video_id}", Path("by_video", prefix, p.name).as_posix()))

        entries.sort(key=lambda x: (x[1].lower(), x[0]))
        index = temp_dir / "INDEX.md"
        with index.open("w", encoding="utf-8") as f:
            f.write("# Transcripts Index\n\n")
            f.write(f"Total files: **{len(entries)}**\n\n")
            f.write("Format: `Title__videoId.md`\n\n")
            f.write("## Files\n\n")
            for vid, title, rel in entries:
                f.write(f"- `{rel}` - {title}\n")

        _replace_tree_atomic(temp_by_video, by_video)
        shutil.move(str(index), str(out_root / "INDEX.md"))
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    readme = root / "README_TRANSCRIPTS.md"
    readme.write_text(
        "# Transcript Exports\n\n"
        "- Source: `db/pipeline.db`\n"
        "- Main index: `transcripts/INDEX.md`\n"
        "- Per-video files: `transcripts/by_video/`\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    main(target)
