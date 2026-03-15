from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_openclaw_transcripts.ps1"


def test_sync_script_enables_remote_cleanup_by_default():
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "[switch]$SkipRemoteCleanup" in content
    assert "function Invoke-RemoteCleanup" in content
    assert "find workspace/transcripts -mindepth 1 -maxdepth 1 -type f -delete" in content
    assert "find workspace/scrape -mindepth 1 -maxdepth 1 -type d -mtime +" in content
    assert "find workspace/produce -mindepth 1 -maxdepth 1 -type d -mtime +" in content
    assert "if (-not $SkipRemoteCleanup)" in content
