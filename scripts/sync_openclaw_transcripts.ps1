param(
  [string]$HostName = "root@46.225.98.179",
  [string]$RemoteRoot = "/root/youtube-pipeline",
  [string]$LocalRoot = "C:\\dev\\projects\\youtube_scraping\\openclaw_live",
  [switch]$SkipRemoteCleanup,
  [int]$RemoteTempRetentionDays = 3
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

Assert-SafeValue -Value $HostName -Name "HostName" -Pattern "^[A-Za-z0-9._@:-]+$"
Assert-SafeValue -Value $RemoteRoot -Name "RemoteRoot" -Pattern "^[A-Za-z0-9_./-]+$"
if ($RemoteTempRetentionDays -lt 0 -or $RemoteTempRetentionDays -gt 365) {
  throw "RemoteTempRetentionDays must be between 0 and 365"
}

function Invoke-RemoteCleanup {
  param(
    [string]$HostName,
    [string]$RemoteRoot,
    [int]$RetentionDays
  )

  $cleanupCmd = @"
set -euo pipefail
cd '$RemoteRoot'

if [ -d workspace/transcripts ]; then
  find workspace/transcripts -mindepth 1 -maxdepth 1 -type f -delete
fi

if [ -d workspace/scrape ]; then
  find workspace/scrape -mindepth 1 -maxdepth 1 -type d -mtime +$RetentionDays -exec rm -rf {} +
fi

if [ -d workspace/produce ]; then
  find workspace/produce -mindepth 1 -maxdepth 1 -type d -mtime +$RetentionDays -exec rm -rf {} +
fi

du -sh workspace/transcripts workspace/scrape workspace/produce 2>/dev/null || true
"@

  ssh -o BatchMode=yes $HostName $cleanupCmd
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$tmp = Join-Path $env:TEMP "openclaw_sync_$timestamp"
$bundle = Join-Path $tmp "bundle.tar.gz"
$remoteBundle = "/tmp/openclaw_sync_bundle_${timestamp}_$PID.tar.gz"
$log = Join-Path "C:\\dev\\projects\\youtube_scraping\\logs" "sync_openclaw.log"

New-Item -ItemType Directory -Force -Path $tmp | Out-Null
New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

try {
  ssh -o BatchMode=yes $HostName "tar -C $RemoteRoot -czf $remoteBundle workspace/transcripts db/pipeline.db"
  scp "$HostName`:$remoteBundle" $bundle | Out-Null
  ssh -o BatchMode=yes $HostName "rm -f $remoteBundle"
  if (!(Test-Path $bundle)) { throw "bundle not downloaded" }

  tar -xzf $bundle -C $LocalRoot

  python "C:\\dev\\projects\\youtube_scraping\\scripts\\build_transcripts_from_db.py" $LocalRoot

  $count = (Get-ChildItem -Path (Join-Path $LocalRoot "transcripts\\by_video") -Recurse -File -Filter *.md | Measure-Object).Count
  if (-not $SkipRemoteCleanup) {
    $cleanupSummary = Invoke-RemoteCleanup -HostName $HostName -RemoteRoot $RemoteRoot -RetentionDays $RemoteTempRetentionDays
  } else {
    $cleanupSummary = "remote_cleanup=skipped"
  }
  "[$(Get-Date -Format s)] sync_ok files=$count retention_days=$RemoteTempRetentionDays cleanup=$cleanupSummary" | Out-File -Append -FilePath $log -Encoding utf8
  Write-Output "sync_ok files=$count"
}
catch {
  "[$(Get-Date -Format s)] sync_error message=$($_.Exception.Message)" | Out-File -Append -FilePath $log -Encoding utf8
  throw
}
finally {
  try {
    ssh -o BatchMode=yes $HostName "rm -f $remoteBundle" 2>$null | Out-Null
  } catch {
  }
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
}
