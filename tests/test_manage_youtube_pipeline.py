from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "manage_youtube_pipeline.ps1"


def test_manage_script_exposes_vps_control_actions() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '[ValidateSet("status", "health", "runs", "trigger-run", "restart", "logs", "service-logs", "disk", "sync", "cleanup", "backfill", "produce")]' in content
    assert 'curl -fsS http://127.0.0.1:3847/api/health' in content
    assert 'curl -fsS http://127.0.0.1:3847/api/runs' in content
    assert 'curl -fsS -X $Method -H "Authorization: Bearer \\$AUTH_TOKEN" http://127.0.0.1:3847$Path' in content
    assert 'systemctl restart youtube-pipeline' in content
    assert 'journalctl -u youtube-pipeline --no-pager -n $Tail' in content
    assert '/root/.bun/bin/bun run scripts/backfill-transcripts.ts' in content
    assert './scripts/produce.sh' in content


def test_manage_script_reuses_sync_and_cleanup_paths() -> None:
    content = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'sync_openclaw_transcripts.ps1' in content
    assert 'find workspace/transcripts -mindepth 1 -maxdepth 1 -type f -delete' in content
    assert 'find workspace/scrape -mindepth 1 -maxdepth 1 -type d -mtime +$RemoteTempRetentionDays' in content
    assert 'find workspace/produce -mindepth 1 -maxdepth 1 -type d -mtime +$RemoteTempRetentionDays' in content
