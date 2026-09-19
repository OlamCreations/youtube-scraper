"""End-to-end check of the README Quick Start, fully offline.

The test walks the Quick Start against a temporary data directory:

1. ``scrape.py --seed channels.example.json`` runs as a real subprocess.
2. ``scrape.scrape()`` runs in process. yt-dlp is replaced by a fixture that
   returns a video listing and writes YouTube-style rolling auto-captions, so
   the rows land in the database created by the scraper's own ``init_db``.
3. ``build_library.py build`` runs as a real subprocess.
4. ``build_library.py search`` and ``bundle`` run as real subprocesses.

Nothing reaches the network: every yt-dlp call goes through the fixture, and
the fixture fails the test on any call it does not recognise.
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
from typing import Iterator

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
SEED_FILE = REPO / "channels.example.json"
sys.path.insert(0, str(SCRIPTS))

import build_library  # noqa: E402
import scrape  # noqa: E402

# A deprecated call in the scripts fails the tests instead of printing a warning.
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
        ("fixture-biz-2", "Hiring your first salesperson",
         ["hire for grit", "train the script", "measure every call"]),
    ],
    [
        ("fixture-phi-1", "Café notes: reading slowly ☕",
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


class FakeYtDlp:
    """Stand-in for subprocess.run(["yt-dlp", ...]) inside scrape.py."""

    def __init__(self, listings: dict[str, list[tuple[str, str, list[str]]]], failing: frozenset[str] = frozenset()):
        self.listings = listings
        self.failing = failing
        self.url_to_channel = {_channel_url(channel): channel["id"] for channel in _seeded_channels()}
        self.captions = {vid: lines for videos in listings.values() for vid, _, lines in videos}
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        prefix = scrape.YT_DLP
        assert list(cmd[: len(prefix)]) == prefix, f"unexpected subprocess: {cmd}"
        cmd = list(cmd[len(prefix):])  # the yt-dlp arguments alone
        self.calls.append(cmd)
        url = cmd[-1]
        text_mode = kwargs.get("text", False)
        if "--flat-playlist" in cmd:
            assert url in self.url_to_channel, f"listing for unknown channel: {url}"
            channel_id = self.url_to_channel[url]
            if channel_id in self.failing:
                return subprocess.CompletedProcess(cmd, 1, "", "ERROR: HTTP Error 404: Not Found")
            limit = int(cmd[cmd.index("--playlist-end") + 1])
            rows = []
            for vid, title, _ in self.listings[channel_id][:limit]:
                rows.extend([vid, title])
            return subprocess.CompletedProcess(cmd, 0, "\n".join(rows) + "\n", "")
        if "--write-auto-sub" in cmd:
            vid = url.split("watch?v=")[-1]
            template = cmd[cmd.index("-o") + 1]
            Path(template.replace("%(id)s", vid) + ".en.vtt").write_text(
                _rolling_vtt(self.captions[vid]), encoding="utf-8"
            )
            empty = "" if text_mode else b""
            return subprocess.CompletedProcess(cmd, 0, empty, empty)
        raise AssertionError(f"unrecognised yt-dlp call: {cmd}")


def _run(*args: object) -> subprocess.CompletedProcess:
    # Run the scripts with Python's default I/O settings, as on a fresh machine,
    # even if the developer's shell forces UTF-8 mode.
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    return subprocess.run(
        [sys.executable, *map(str, args)],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _listings() -> dict[str, list[tuple[str, str, list[str]]]]:
    channels = _seeded_channels()
    assert len(channels) <= len(FIXTURE_VIDEOS), "add fixture videos for the new seed channel"
    return {channel["id"]: FIXTURE_VIDEOS[index] for index, channel in enumerate(channels)}


@contextmanager
def _db(data: Path) -> Iterator[sqlite3.Connection]:
    """Open the scraper database, commit on success, and always close it."""
    conn = sqlite3.connect(data / "db" / "pipeline.db")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


@pytest.fixture()
def scraped_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Quick Start steps 1 and 2: seed the example channels, then scrape offline."""
    data = tmp_path / "data"

    seed = _run(SCRIPTS / "scrape.py", data, "--seed", SEED_FILE)
    assert seed.returncode == 0, seed.stdout + seed.stderr
    channels = _seeded_channels()
    assert f"Seeded {len(channels)} channels" in seed.stdout
    with _db(data) as conn:
        assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == len(channels)

    fake = FakeYtDlp(_listings())
    conn = scrape.init_db(data / "db" / "pipeline.db")
    try:
        with monkeypatch.context() as patch:
            patch.setattr(scrape.subprocess, "run", fake)
            failed = scrape.scrape(conn, data, limit=5)
    finally:
        conn.close()

    assert failed == 0
    assert fake.calls, "the scraper never called yt-dlp"
    expected_videos = sum(len(FIXTURE_VIDEOS[i]) for i in range(len(channels)))
    with _db(data) as conn:
        assert conn.execute("SELECT COUNT(*) FROM videos WHERE has_transcript = 1").fetchone()[0] == expected_videos
        stored = dict(conn.execute("SELECT video_id, raw_text FROM transcripts").fetchall())
        timestamps = [row[0] for row in conn.execute("SELECT scraped_at FROM videos")]
        timestamps += [row[0] for row in conn.execute("SELECT last_scraped_at FROM channels")]
    assert timestamps and all(STORED_TIMESTAMP.fullmatch(value) for value in timestamps), timestamps
    for index in range(len(channels)):
        for vid, _, lines in FIXTURE_VIDEOS[index]:
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
    search = _run(SCRIPTS / "build_library.py", "search", data, "hawking radiation")
    assert search.returncode == 0, search.stdout + search.stderr
    results = json.loads(search.stdout)
    assert results[0]["video_id"] == "fixture-sci-1"

    accented = _run(SCRIPTS / "build_library.py", "search", data, "reading slowly")
    assert accented.returncode == 0, accented.stdout + accented.stderr
    assert json.loads(accented.stdout)[0]["title"] == "Café notes: reading slowly ☕"

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


def test_yt_dlp_goes_through_this_python_when_the_module_is_installed_here() -> None:
    installed = scrape.yt_dlp_command(find_spec=lambda name: object() if name == "yt_dlp" else None)
    assert installed == [sys.executable, "-m", "yt_dlp"]
    assert scrape.yt_dlp_command(find_spec=lambda name: None) == ["yt-dlp"]


def test_scrape_reports_a_channel_it_could_not_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    (data / "db").mkdir(parents=True)
    conn = scrape.init_db(data / "db" / "pipeline.db")
    try:
        scrape.seed_channels(conn, SEED_FILE)
        listings = _listings()
        broken = next(iter(listings))
        fake = FakeYtDlp(listings, failing=frozenset({broken}))
        monkeypatch.setattr(scrape.subprocess, "run", fake)
        failed = scrape.scrape(conn, data, limit=5)
        stored = {row[0] for row in conn.execute("SELECT DISTINCT channel_id FROM videos")}
    finally:
        conn.close()

    assert failed == 1
    assert broken not in stored
    assert stored == set(listings) - {broken}
