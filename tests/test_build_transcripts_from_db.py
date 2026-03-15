import importlib.util
import sqlite3
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_transcripts_from_db.py"
SPEC = importlib.util.spec_from_file_location("youtube_scraping_build_transcripts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

main = MODULE.main
sanitize_title = MODULE.sanitize_title


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("CREATE TABLE videos (id TEXT PRIMARY KEY, title TEXT)")
    cur.execute(
        "CREATE TABLE transcripts (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, language TEXT, word_count INTEGER, quality_score REAL, raw_text TEXT)"
    )
    cur.execute("INSERT INTO videos (id, title) VALUES (?, ?)", ("abc123", "A Title"))
    cur.execute(
        "INSERT INTO transcripts (video_id, language, word_count, quality_score, raw_text) VALUES (?, ?, ?, ?, ?)",
        ("abc123", "en", 12, 0.9, "hello world"),
    )
    con.commit()
    con.close()


def test_sanitize_title_falls_back_to_video_id() -> None:
    assert sanitize_title("!!!", "abc123") == "video_abc123"


def test_main_builds_index_and_video_files(tmp_path: Path) -> None:
    _init_db(tmp_path / "db" / "pipeline.db")
    main(tmp_path)
    transcript = tmp_path / "transcripts" / "by_video" / "ab" / "A Title__abc123.md"
    assert transcript.exists()
    assert (tmp_path / "transcripts" / "INDEX.md").exists()
    assert (tmp_path / "README_TRANSCRIPTS.md").exists()


def test_main_keeps_previous_tree_if_generation_fails(tmp_path: Path, monkeypatch) -> None:
    _init_db(tmp_path / "db" / "pipeline.db")
    existing = tmp_path / "transcripts" / "by_video" / "zz"
    existing.mkdir(parents=True, exist_ok=True)
    old_file = existing / "old.md"
    old_file.write_text("keep me", encoding="utf-8")

    original_write_text = Path.write_text

    def failing_write_text(self: Path, data: str, *args, **kwargs):
        if self.name.endswith("__abc123.md"):
            raise RuntimeError("boom")
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    try:
        main(tmp_path)
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")

    assert old_file.exists()
    assert old_file.read_text(encoding="utf-8") == "keep me"
