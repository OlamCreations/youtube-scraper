"""End-to-end check of the README Quick Start, fully offline.

The test runs the Quick Start commands against a temporary data directory,
each one as a real subprocess, the way the README gives them:

1. ``scrape.py <data> --seed channels.example.json``
2. ``scrape.py <data> --limit 5``
3. ``build_library.py build <data>``
4. ``build_library.py search <data> ...`` and ``bundle <data> ...``

For step 2, tests/fake_yt_dlp goes first on PYTHONPATH. scrape.py finds that
package instead of the real yt-dlp and runs it as ``python -m yt_dlp``, as it
does after ``pip install -r requirements.txt``. The fake lists the fixture
videos and writes YouTube-style rolling auto-captions, so the rows land in the
database created by the scraper's own ``init_db``. It never opens a network
connection, logs every call, and rejects any call it does not recognise.

The pip install steps are not replayed.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Iterator, Mapping

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
SEED_FILE = REPO / "channels.example.json"
FAKE_YT_DLP_PATH = REPO / "tests" / "fake_yt_dlp"
sys.path.insert(0, str(SCRIPTS))

import build_library  # noqa: E402
import scrape  # noqa: E402

# A deprecated call fails the tests instead of printing a warning: here through
# pytest, and in the scripts' subprocesses through ``-W`` (see _run).
pytestmark = pytest.mark.filterwarnings("error::DeprecationWarning")

# The timestamp format already stored in existing databases: naive UTC, ISO 8601.
STORED_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?")

# Two videos per seeded channel, in the order of channels.example.json.
# Each caption line is one cue of spoken text.
FIXTURE_VIDEOS = [
    [
        ("fixture-sci-1", "How black holes evaporate",
         ["black holes lose mass", "through hawking radiation", "over enormous timescales"]),
        ("fixture-sci-2", "The immune system, explained",
         ["white blood cells", "hunt down invaders", "every single day"]),
    ],
    [
        ("fixture-biz-1", "Pricing your offer",
         ["raise your price", "then add a guarantee", "to close more deals"]),
        ("fixture-biz-2", "The closing call",
         ["most sales are lost", "after the price is said", "closing means asking twice"]),
    ],
    [
        ("fixture-phi-1", "“Café notes”: reading slowly ☕",
         ["read what you love", "until you love to read"]),
        ("fixture-phi-2", "Specific knowledge",
         ["specific knowledge cannot be taught", "but it can be learned"]),
    ],
]


def _seeded_channels() -> list[dict]:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))["channels"]


def _expected_text(lines: list[str]) -> str:
    return " ".join(lines)


def _rolling_vtt(lines: list[str]) -> str:
    """Build a caption file in the rolling-context format YouTube uses.

    Each real cue repeats the previous line and adds a new one with inline
    timing tags. A 10 ms echo cue follows each real cue. The scraper must keep
    every spoken line exactly once.
    """
    out = ["WEBVTT", "Kind: captions", "Language: en", ""]
    previous = None
    start = 0
    for line in lines:
        first, *rest = line.split(" ")
        tagged = first + "".join(
            f"<00:00:{start:02d}.500><c> {word}</c>" for word in rest
        )
        out.append(f"00:00:{start:02d}.000 --> 00:00:{start + 2:02d}.000 align:start position:0%")
        if previous is not None:
            out.append(previous)
        out.append(tagged)
        out.append("")
        out.append(f"00:00:{start + 2:02d}.000 --> 00:00:{start + 2:02d}.010 align:start position:0%")
        out.append(line)
        out.append("")
        previous = line
        start += 2
    return "\n".join(out) + "\n"


def _channel_url(channel: dict) -> str:
    """The listing URL scrape.py builds for a seeded channel."""
    handle = channel.get("handle")
    return f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{channel['id']}"


def _listings() -> dict[str, list[tuple[str, str, list[str]]]]:
    channels = _seeded_channels()
    assert len(channels) <= len(FIXTURE_VIDEOS), "add fixture videos for the new seed channel"
    return {channel["id"]: FIXTURE_VIDEOS[index] for index, channel in enumerate(channels)}


class FakeYtDlp:
    """Fixture file and call log for the fake yt_dlp package in tests/fake_yt_dlp."""

    def __init__(self, workdir: Path, listings: dict[str, list[tuple[str, str, list[str]]]],
                 failing: Mapping[str, str] = MappingProxyType({})):
        """``failing`` maps a channel id to the way its listing fails: "404", "silent" or "cut short"."""
        self.fixture = workdir / "fake-yt-dlp.json"
        self.log = workdir / "fake-yt-dlp.log"
        channels = _seeded_channels()
        payload = {
            "listings": {
                _channel_url(channel): [[vid, title] for vid, title, _ in listings[channel["id"]]]
                for channel in channels
            },
            "failing": {_channel_url(channel): failing[channel["id"]] for channel in channels if channel["id"] in failing},
            "captions": {vid: _rolling_vtt(lines) for videos in listings.values() for vid, _, lines in videos},
            # The encoding yt-dlp used on a Windows pipe when nothing else was asked.
            "pipe_encoding": "cp1252",
        }
        self.fixture.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def env(self) -> dict[str, str]:
        return {
            "FAKE_YT_DLP_FIXTURE": str(self.fixture),
            "FAKE_YT_DLP_LOG": str(self.log),
            "PYTHONPATH": os.pathsep.join(filter(None, [str(FAKE_YT_DLP_PATH), os.environ.get("PYTHONPATH")])),
        }

    def calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


def _run(*args: object, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    # Run the scripts with Python's default I/O settings, as on a fresh machine,
    # even if the developer's shell forces UTF-8 mode.
    base = {key: value for key, value in os.environ.items() if key not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    return subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", *map(str, args)],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**base, **(env or {})},
    )


@contextmanager
def _db(data: Path) -> Iterator[sqlite3.Connection]:
    """Open the scraper database, commit on success, and always close it."""
    conn = sqlite3.connect(data / "db" / "pipeline.db")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _seed(data: Path) -> None:
    """Quick Start step 1."""
    seed = _run(SCRIPTS / "scrape.py", data, "--seed", SEED_FILE)
    assert seed.returncode == 0, seed.stdout + seed.stderr
    channels = _seeded_channels()
    assert f"Seeded {len(channels)} channels" in seed.stdout
    with _db(data) as conn:
        assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == len(channels)


@pytest.fixture()
def scraped_data(tmp_path: Path) -> Path:
    """Quick Start steps 1 and 2: seed the example channels, then scrape through the fake yt-dlp."""
    data = tmp_path / "data"
    _seed(data)
    channels = _seeded_channels()

    fake = FakeYtDlp(tmp_path, _listings())
    run = _run(SCRIPTS / "scrape.py", data, "--limit", "5", env=fake.env())
    assert run.returncode == 0, run.stdout + run.stderr

    calls = fake.calls()
    assert calls, "scrape.py never ran the fake yt-dlp"
    assert all(call["ok"] for call in calls), [call for call in calls if not call["ok"]]
    listing_calls = [call["argv"] for call in calls if "--flat-playlist" in call["argv"]]
    assert len(listing_calls) == len(channels)
    assert all(argv[argv.index("--playlist-end") + 1] == "5" for argv in listing_calls)

    expected_videos = sum(len(FIXTURE_VIDEOS[i]) for i in range(len(channels)))
    with _db(data) as conn:
        assert conn.execute("SELECT COUNT(*) FROM videos WHERE has_transcript = 1").fetchone()[0] == expected_videos
        titles = dict(conn.execute("SELECT id, title FROM videos").fetchall())
        stored = dict(conn.execute("SELECT video_id, raw_text FROM transcripts").fetchall())
        timestamps = [row[0] for row in conn.execute("SELECT scraped_at FROM videos")]
        timestamps += [row[0] for row in conn.execute("SELECT last_scraped_at FROM channels")]
    assert timestamps and all(STORED_TIMESTAMP.fullmatch(value) for value in timestamps), timestamps
    for index in range(len(channels)):
        for vid, title, lines in FIXTURE_VIDEOS[index]:
            assert titles[vid] == title, "the title changed between yt-dlp and the database"
            assert stored[vid] == _expected_text(lines), "rolling captions were not deduplicated"
    return data


def test_quickstart_seed_scrape_build_search_bundle(scraped_data: Path) -> None:
    data = scraped_data
    channels = _seeded_channels()
    expected_videos = sum(len(FIXTURE_VIDEOS[i]) for i in range(len(channels)))

    # Step 3: build the library.
    build = _run(SCRIPTS / "build_library.py", "build", data)
    assert build.returncode == 0, build.stdout + build.stderr
    summary = json.loads(build.stdout)
    assert summary["videos"] == expected_videos
    assert summary["channels"] == len(channels)

    library = data / "library"
    for index, channel in enumerate(channels):
        channel_dir = library / "by_channel" / build_library.slugify(channel["name"], channel["id"])
        assert channel_dir.is_dir(), f"missing browse folder for {channel['name']}"
        for vid, title, lines in FIXTURE_VIDEOS[index]:
            page = channel_dir / f"{build_library.sanitize_title(title, vid)}.md"
            assert page.is_file(), f"missing page {page}"
            content = page.read_text(encoding="utf-8")
            assert f"- Channel: {channel['name']}" in content
            assert _expected_text(lines) in content
            assert (library / "videos" / vid / "transcript.md").is_file()

    catalog = (library / "metadata" / "catalog.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(catalog) == expected_videos

    # Step 4: search and bundle.
    def search(query: str, *options: str) -> list[dict]:
        run = _run(SCRIPTS / "build_library.py", "search", data, query, *options)
        assert run.returncode == 0, run.stdout + run.stderr
        return json.loads(run.stdout)

    # The README's query. Only the videos that use its words come back, the sales
    # video that uses both first. Stemming lets "closing" match "close" in the
    # pricing video.
    ranked = search("sales closing")
    assert [result["video_id"] for result in ranked] == ["fixture-biz-2", "fixture-biz-1"]
    assert ranked[0]["score"] > ranked[1]["score"] > 0
    assert [result["video_id"] for result in search("sales closing", "--limit", "1")] == ["fixture-biz-2"]

    assert [result["video_id"] for result in search("hawking radiation")] == ["fixture-sci-1"]
    assert search("quantum chromodynamics") == []

    assert search("reading slowly")[0]["title"] == FIXTURE_VIDEOS[2][0][1]

    bundle = _run(SCRIPTS / "build_library.py", "bundle", data, "pricing guarantee")
    assert bundle.returncode == 0, bundle.stdout + bundle.stderr
    bundle_path = Path(bundle.stdout.strip())
    assert bundle_path.is_file()
    assert _expected_text(FIXTURE_VIDEOS[1][0][2]) in bundle_path.read_text(encoding="utf-8")


def test_flagged_channel_is_left_out_of_the_library(scraped_data: Path) -> None:
    data = scraped_data
    flagged = _seeded_channels()[0]
    with _db(data) as conn:
        conn.execute("UPDATE channels SET flag = 'excluded' WHERE id = ?", (flagged["id"],))

    build = _run(SCRIPTS / "build_library.py", "build", data)
    assert build.returncode == 0, build.stdout + build.stderr
    by_channel = data / "library" / "by_channel"
    assert not (by_channel / build_library.slugify(flagged["name"], flagged["id"])).exists()
    assert len(list(by_channel.iterdir())) == len(_seeded_channels()) - 1


def test_build_names_fts5_when_sqlite_lacks_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = sqlite3.connect

    class WithoutFts5:
        """A connection that fails like an SQLite compiled without FTS5."""

        def __init__(self, path: object) -> None:
            self._connection = real_connect(path)

        def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
            if "fts5" in sql:
                raise sqlite3.OperationalError("no such module: fts5")
            return self._connection.execute(sql, *args)

        def close(self) -> None:
            self._connection.close()

    monkeypatch.setattr(build_library.sqlite3, "connect", WithoutFts5)
    with pytest.raises(RuntimeError, match="needs SQLite's FTS5 extension"):
        build_library.write_search_index(tmp_path / "search.sqlite", [])


def test_yt_dlp_goes_through_this_python_when_the_module_is_installed_here() -> None:
    installed = scrape.yt_dlp_command(find_spec=lambda name: object() if name == "yt_dlp" else None)
    assert installed == [sys.executable, "-m", "yt_dlp"]
    assert scrape.yt_dlp_command(find_spec=lambda name: None) == ["yt-dlp"]


def test_scrape_exits_1_and_names_the_channel_it_could_not_list(tmp_path: Path) -> None:
    """Quick Start step 2 when one channel cannot be reached: the others are scraped, the exit code is 1."""
    data = tmp_path / "data"
    _seed(data)
    channels = _seeded_channels()
    broken = channels[0]

    fake = FakeYtDlp(tmp_path, _listings(), failing={broken["id"]: "404"})
    run = _run(SCRIPTS / "scrape.py", data, "--limit", "5", env=fake.env())

    assert run.returncode == 1, run.stdout + run.stderr
    assert f"Could not list {broken['name']} <{_channel_url(broken)}>" in run.stdout
    assert "HTTP Error 404" in run.stdout
    assert all(call["ok"] for call in fake.calls())
    with _db(data) as conn:
        stored = {row[0] for row in conn.execute("SELECT DISTINCT channel_id FROM videos")}
    assert stored == {channel["id"] for channel in channels} - {broken["id"]}


@pytest.mark.parametrize("content", [None, "{not json"], ids=["missing file", "invalid JSON"])
def test_seed_exits_1_when_the_file_cannot_be_read(tmp_path: Path, content: str | None) -> None:
    seed_file = tmp_path / "channels.json"
    if content is not None:
        seed_file.write_text(content, encoding="utf-8")
    data = tmp_path / "data"

    run = _run(SCRIPTS / "scrape.py", data, "--seed", seed_file)

    assert run.returncode == 1, run.stdout + run.stderr
    assert "Error seeding channels" in run.stdout
    with _db(data) as conn:
        assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == 0


def _as_printed(title: str) -> str:
    """A title as the ``--check`` table prints it: ASCII only, one ? per other character, 48 at most."""
    return title.encode("ascii", errors="replace").decode("ascii")[:48]


def _check_rows(stdout: str) -> dict[str, tuple[int, str]]:
    """The rows of the ``--check`` table: channel name -> (unseen videos, latest unseen title)."""
    rows = {}
    for channel in _seeded_channels():
        for line in stdout.splitlines():
            match = re.fullmatch(rf"{re.escape(channel['name'])}\s+(\d+)  (.*)", line)
            if match:
                rows[channel["name"]] = (int(match.group(1)), match.group(2))
    return rows


@pytest.mark.parametrize(
    "failure, detail",
    [
        ("404", "HTTP Error 404"),
        ("silent", "no output and no error"),
        ("cut short", "fake listing cut short"),
    ],
)
def test_check_names_the_channel_it_could_not_list_and_exits_1(tmp_path: Path, failure: str, detail: str) -> None:
    """``scrape.py --check`` when one channel cannot be listed: that channel is named, never counted as 0 new videos."""
    data = tmp_path / "data"
    _seed(data)
    channels = _seeded_channels()
    broken = channels[0]

    fake = FakeYtDlp(tmp_path, _listings(), failing={broken["id"]: failure})
    run = _run(SCRIPTS / "scrape.py", data, "--check", "--limit", "5", env=fake.env())

    assert run.returncode == 1, run.stdout + run.stderr
    assert f"Could not list {broken['name']} <{_channel_url(broken)}>: " in run.stdout
    assert detail in run.stdout
    # Nothing is scraped yet, so every listed video is unseen. The third channel's
    # latest title holds curly quotes, an accent and an emoji: a listing read in
    # the pipe's encoding instead of UTF-8 loses the emoji, and its "?" with it.
    assert _check_rows(run.stdout) == {
        channel["name"]: (len(FIXTURE_VIDEOS[index]), _as_printed(FIXTURE_VIDEOS[index][0][1]))
        for index, channel in enumerate(channels)
        if channel is not broken
    }

    calls = fake.calls()
    assert len(calls) == len(channels) and all(call["ok"] for call in calls), calls
    assert all(call["argv"][call["argv"].index("--playlist-end") + 1] == "5" for call in calls)
    with _db(data) as conn:
        assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0, "--check wrote to the database"


def test_check_exits_0_with_nothing_new_after_a_scrape(scraped_data: Path, tmp_path: Path) -> None:
    fake = FakeYtDlp(tmp_path, _listings())
    run = _run(SCRIPTS / "scrape.py", scraped_data, "--check", "--limit", "5", env=fake.env())

    assert run.returncode == 0, run.stdout + run.stderr
    assert "Could not list" not in run.stdout
    assert _check_rows(run.stdout) == {channel["name"]: (0, "") for channel in _seeded_channels()}
