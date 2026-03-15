import importlib.util
import json
import sqlite3
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_library_from_db.py"
SPEC = importlib.util.spec_from_file_location("youtube_scraping_build_library", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

build_library = MODULE.build_library
search_library = MODULE.search_library
write_query_bundle = MODULE.write_query_bundle


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE channels (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            handle TEXT,
            category TEXT DEFAULT 'general',
            language TEXT DEFAULT 'en',
            priority INTEGER DEFAULT 5,
            enabled INTEGER DEFAULT 1,
            last_scraped_at TEXT,
            total_videos INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE videos (
            id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            published_at TEXT,
            duration_seconds INTEGER,
            view_count INTEGER,
            like_count INTEGER,
            has_transcript INTEGER DEFAULT 0,
            transcript_source TEXT,
            scraped_at TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            word_count INTEGER NOT NULL,
            language TEXT DEFAULT 'en',
            quality_score REAL,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            insight_type TEXT NOT NULL,
            content TEXT NOT NULL,
            model_used TEXT,
            created_at TEXT
        )
        """
    )

    cur.execute(
        "INSERT INTO channels (id, name, handle, category, language) VALUES (?, ?, ?, ?, ?)",
        ("chan-1", "Daily Stoic", "@DailyStoic", "stoicism", "en"),
    )
    cur.execute(
        "INSERT INTO channels (id, name, handle, category, language) VALUES (?, ?, ?, ?, ?)",
        ("chan-2", "Plum Village", "@PlumVillageApp", "buddhism", "en"),
    )
    cur.execute(
        "INSERT INTO videos (id, channel_id, title, description, published_at, has_transcript, transcript_source) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("vid-stoic", "chan-1", "How Stoicism Builds Discipline", "A guide to resilience and focus.", "2026-03-01", 1, "auto-sub"),
    )
    cur.execute(
        "INSERT INTO videos (id, channel_id, title, description, published_at, has_transcript, transcript_source) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("vid-zen", "chan-2", "Meditation for Inner Peace", "Mindfulness and breathing practice.", "2026-03-02", 1, "auto-sub"),
    )
    cur.execute(
        "INSERT INTO transcripts (video_id, raw_text, word_count, language, quality_score) VALUES (?, ?, ?, ?, ?)",
        ("vid-stoic", "Stoicism teaches focus, virtue, resilience, and character over comfort.", 10, "en", 0.95),
    )
    cur.execute(
        "INSERT INTO transcripts (video_id, raw_text, word_count, language, quality_score) VALUES (?, ?, ?, ?, ?)",
        ("vid-zen", "Meditation, mindful breathing, compassion, and awareness reduce anxiety.", 9, "en", 0.97),
    )
    cur.execute(
        "INSERT INTO insights (video_id, insight_type, content, model_used) VALUES (?, ?, ?, ?)",
        (
            "vid-stoic",
            "full_analysis",
            json.dumps(
                {
                    "themes": ["Stoicism", "discipline"],
                    "notable_quotes": ["Character matters more than comfort."],
                    "summary": "A stoic overview of discipline, focus, and resilient character.",
                    "thematic_threads": ["virtue", "self-mastery"],
                }
            ),
            "test-model",
        ),
    )
    cur.execute(
        "INSERT INTO insights (video_id, insight_type, content, model_used) VALUES (?, ?, ?, ?)",
        (
            "vid-zen",
            "full_analysis",
            json.dumps(
                {
                    "themes": ["Mindfulness", "meditation"],
                    "notable_quotes": ["Return to your breath."],
                    "summary": "A mindfulness-oriented transcript about meditation and inner peace.",
                    "thematic_threads": ["awareness", "calm"],
                }
            ),
            "test-model",
        ),
    )
    con.commit()
    con.close()


def test_build_library_creates_channel_video_theme_views(tmp_path: Path) -> None:
    _init_db(tmp_path / "db" / "pipeline.db")

    library_dir = build_library(tmp_path)

    assert (library_dir / "channels" / "daily-stoic" / "README.md").exists()
    assert (library_dir / "videos" / "vid-stoic" / "context.md").exists()
    assert (library_dir / "themes" / "stoicism" / "README.md").exists()
    assert (library_dir / "metadata" / "catalog.jsonl").exists()
    assert (library_dir / "metadata" / "embeddings.jsonl").exists()
    assert (library_dir / "bundles" / "channel__daily-stoic.md").exists()
    assert (library_dir / "bundles" / "theme__meditation_mindfulness.md").exists()


def test_search_library_uses_local_embeddings_for_retrieval(tmp_path: Path) -> None:
    _init_db(tmp_path / "db" / "pipeline.db")
    library_dir = build_library(tmp_path)

    results = search_library(library_dir, query="stoic discipline virtue", limit=2)

    assert results
    assert results[0]["video_id"] == "vid-stoic"


def test_write_query_bundle_emits_llm_ready_markdown(tmp_path: Path) -> None:
    _init_db(tmp_path / "db" / "pipeline.db")
    library_dir = build_library(tmp_path)

    bundle_path = write_query_bundle(library_dir, query="mindfulness breathing calm", limit=2)

    content = bundle_path.read_text(encoding="utf-8")
    assert "LLM Query Bundle" in content
    assert "Meditation for Inner Peace" in content
    assert "videos/vid-zen/context.md" in content
    assert "themes:" in content
