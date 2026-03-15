param(
  [ValidateSet("status", "health", "runs", "trigger-run", "restart", "logs", "service-logs", "disk", "sync", "cleanup", "backfill", "produce")]
  [string]$Action = "status",
  [string]$HostName = "root@46.225.98.179",
  [string]$RemoteRoot = "/root/youtube-pipeline",
  [string]$LocalRoot = "C:\\dev\\projects\\youtube_scraping\\openclaw_live",
  [int]$Tail = 120,
  [string]$LogDate = "",
  [int]$RemoteTempRetentionDays = 3,
  [switch]$SkipRemoteCleanup
)

$ErrorActionPreference = "Stop"

function Assert-SafeValue {
  param(
    [string]$Value,
    [string]$Name,
    [string]$Pattern
  )

  if ([string]::IsNullOrWhiteSpace($Value)) {
    throw "$Name cannot be empty"
  }
  if ($Value -notmatch $Pattern) {
    throw "$Name contains unsupported characters"
  }
}

function Get-CurrentLogDate {
  if ($LogDate) {
    return $LogDate
  }
  return (Get-Date -Format "yyyy-MM-dd")
}

function Invoke-RemoteCommand {
  param([string]$Command)
  ssh -o BatchMode=yes $HostName $Command
}

function Invoke-YoutubeApiCommand {
  param(
    [string]$Method,
    [string]$Path
  )

  $apiCmd = @"
set -euo pipefail
cd '$RemoteRoot'
set -a
. ./config/pipeline.env
set +a
curl -fsS -X $Method -H "Authorization: Bearer \$AUTH_TOKEN" http://127.0.0.1:3847$Path
"@

  Invoke-RemoteCommand -Command $apiCmd
}

function Invoke-RemoteCleanup {
  $cleanupCmd = @"
set -euo pipefail
cd '$RemoteRoot'

if [ -d workspace/transcripts ]; then
  find workspace/transcripts -mindepth 1 -maxdepth 1 -type f -delete
fi

if [ -d workspace/scrape ]; then
  find workspace/scrape -mindepth 1 -maxdepth 1 -type d -mtime +$RemoteTempRetentionDays -exec rm -rf {} +
fi

if [ -d workspace/produce ]; then
  find workspace/produce -mindepth 1 -maxdepth 1 -type d -mtime +$RemoteTempRetentionDays -exec rm -rf {} +
fi

du -sh db workspace/transcripts workspace/scrape workspace/produce logs 2>/dev/null || true
"@

  Invoke-RemoteCommand -Command $cleanupCmd
}

Assert-SafeValue -Value $HostName -Name "HostName" -Pattern "^[A-Za-z0-9._@:-]+$"
Assert-SafeValue -Value $RemoteRoot -Name "RemoteRoot" -Pattern "^[A-Za-z0-9_./-]+$"
Assert-SafeValue -Value $LocalRoot -Name "LocalRoot" -Pattern "^[A-Za-z0-9_:\\/ .-]+$"

if ($Tail -lt 1 -or $Tail -gt 5000) {
  throw "Tail must be between 1 and 5000"
}

if ($RemoteTempRetentionDays -lt 0 -or $RemoteTempRetentionDays -gt 365) {
  throw "RemoteTempRetentionDays must be between 0 and 365"
}

if ($LogDate -and $LogDate -notmatch "^\d{4}-\d{2}-\d{2}$") {
  throw "LogDate must use YYYY-MM-DD"
}

switch ($Action) {
  "status" {
    $cmd = @"
set -euo pipefail
systemctl is-active youtube-pipeline
systemctl status youtube-pipeline --no-pager --lines 40
"@
    Invoke-RemoteCommand -Command $cmd
  }

  "health" {
    Invoke-RemoteCommand -Command "curl -fsS http://127.0.0.1:3847/api/health"
  }

  "runs" {
    Invoke-RemoteCommand -Command "curl -fsS http://127.0.0.1:3847/api/runs"
  }

  "trigger-run" {
    Invoke-YoutubeApiCommand -Method "POST" -Path "/api/trigger/run"
  }

  "restart" {
    $cmd = @"
set -euo pipefail
systemctl restart youtube-pipeline
systemctl is-active youtube-pipeline
systemctl status youtube-pipeline --no-pager --lines 25
"@
    Invoke-RemoteCommand -Command $cmd
  }

  "logs" {
    $currentLogDate = Get-CurrentLogDate
    $cmd = @"
set -euo pipefail
cd '$RemoteRoot'
tail -n $Tail logs/pipeline-$currentLogDate.log
"@
    Invoke-RemoteCommand -Command $cmd
  }

  "service-logs" {
    Invoke-RemoteCommand -Command "journalctl -u youtube-pipeline --no-pager -n $Tail"
  }

  "disk" {
    $cmd = @"
set -euo pipefail
df -h /
cd '$RemoteRoot'
du -sh db logs workspace workspace/transcripts workspace/scrape workspace/produce 2>/dev/null || true
"@
    Invoke-RemoteCommand -Command $cmd
  }

  "sync" {
    $syncScript = Join-Path $PSScriptRoot "sync_openclaw_transcripts.ps1"
    & $syncScript -HostName $HostName -RemoteRoot $RemoteRoot -LocalRoot $LocalRoot -RemoteTempRetentionDays $RemoteTempRetentionDays -SkipRemoteCleanup:$SkipRemoteCleanup
  }

  "cleanup" {
    Invoke-RemoteCleanup
  }

  "backfill" {
    $cmd = @"
set -euo pipefail
cd '$RemoteRoot'
/root/.bun/bin/bun run scripts/backfill-transcripts.ts
"@
    Invoke-RemoteCommand -Command $cmd
  }

  "produce" {
    $cmd = @"
set -euo pipefail
cd '$RemoteRoot'
./scripts/produce.sh
"@
    Invoke-RemoteCommand -Command $cmd
  }
}
