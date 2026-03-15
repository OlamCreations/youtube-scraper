[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('status', 'health', 'runs', 'trigger-run', 'restart', 'logs', 'service-logs', 'disk', 'sync', 'cleanup', 'backfill', 'produce')]
    [string]$Action = 'status',

    [Parameter(Position = 1)]
    [string]$Arg1,

    [string]$HostName,
    [string]$RemoteRoot,
    [string]$LocalRoot,
    [string]$ServiceName,
    [string]$ApiEndpoint,
    [string]$ApiToken,
    [int]$Tail = 200
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Import-DotEnv {
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) {
            continue
        }

        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) {
            continue
        }

        $name = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        [Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoEnvPath = Join-Path $PSScriptRoot '..\.env'
if (Test-Path $repoEnvPath) {
    Import-DotEnv -Path $repoEnvPath
}

if (-not $HostName) { $HostName = $env:VPS_HOST }
if (-not $RemoteRoot) { $RemoteRoot = $env:REMOTE_ROOT }
if (-not $LocalRoot) { $LocalRoot = if ($env:LOCAL_ROOT) { $env:LOCAL_ROOT } else { Join-Path $repoRoot 'data' } }
if (-not $ServiceName) { $ServiceName = if ($env:PIPELINE_SERVICE_NAME) { $env:PIPELINE_SERVICE_NAME } else { 'youtube-pipeline' } }
if (-not $ApiEndpoint) { $ApiEndpoint = if ($env:YOUTUBE_PIPELINE_API) { $env:YOUTUBE_PIPELINE_API } else { 'http://127.0.0.1:8000' } }
if (-not $ApiToken) { $ApiToken = $env:YOUTUBE_PIPELINE_TOKEN }

function Assert-SafeValue {
    param(
        [Parameter(Mandatory)]
        [string]$Value,
        [Parameter(Mandatory)]
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Name is required."
    }

    if ($Value -match '[\r\n`";|&<>]') {
        throw "$Name contains unsafe characters."
    }
}

function Resolve-RequiredConfig {
    Assert-SafeValue -Value $HostName -Name 'HostName'
    Assert-SafeValue -Value $RemoteRoot -Name 'RemoteRoot'
    Assert-SafeValue -Value $ServiceName -Name 'ServiceName'
}

function Invoke-RemoteCommand {
    param(
        [Parameter(Mandatory)]
        [string]$Command,
        [switch]$AllocateTty
    )

    Resolve-RequiredConfig
    Assert-SafeValue -Value $Command -Name 'Command'

    $sshArgs = @()
    if ($AllocateTty) {
        $sshArgs += '-t'
    }
    $sshArgs += $HostName
    $sshArgs += "bash -lc '$Command'"

    & ssh @sshArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Remote command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-YoutubeApiCommand {
    param(
        [Parameter(Mandatory)]
        [ValidateSet('GET', 'POST')]
        [string]$Method,
        [Parameter(Mandatory)]
        [string]$Path,
        [string]$Body
    )

    Resolve-RequiredConfig

    $curlParts = @(
        'curl -fsSL',
        "-X $Method",
        "-H 'Accept: application/json'"
    )
    if ($ApiToken) {
        $curlParts += "-H 'Authorization: Bearer $ApiToken'"
    }
    if ($Body) {
        $escapedBody = $Body.Replace("'", "'\''")
        $curlParts += "-H 'Content-Type: application/json'"
        $curlParts += "--data '$escapedBody'"
    }
    $curlParts += "'$ApiEndpoint$Path'"

    Invoke-RemoteCommand -Command ($curlParts -join ' ')
}

function Get-RemoteLogFile {
    $candidates = @(
        "$RemoteRoot/logs/pipeline.log",
        "$RemoteRoot/logs/service.log",
        "$RemoteRoot/pipeline.log"
    )
    $checks = $candidates | ForEach-Object { "if [ -f '$_' ]; then printf '%s' '$_'; exit 0; fi" }
    $command = ($checks -join '; ') + "; printf '%s' '$($candidates[0])'"
    Resolve-RequiredConfig
    Assert-SafeValue -Value $command -Name 'Log probe command'
    (& ssh $HostName "bash -lc '$command'").Trim()
}

switch ($Action) {
    'status' {
        Invoke-RemoteCommand -Command "cd '$RemoteRoot' && pwd && echo && systemctl status '$ServiceName' --no-pager --full || docker compose ps || ps -ef | grep -i '[y]outube'"
        break
    }

    'health' {
        try {
            Invoke-YoutubeApiCommand -Method 'GET' -Path '/health'
        }
        catch {
            Invoke-RemoteCommand -Command "cd '$RemoteRoot' && test -f db/pipeline.db && sqlite3 db/pipeline.db 'select count(*) as transcripts from transcripts;' || true"
        }
        break
    }

    'runs' {
        try {
            Invoke-YoutubeApiCommand -Method 'GET' -Path '/runs'
        }
        catch {
            Invoke-RemoteCommand -Command "cd '$RemoteRoot' && if command -v sqlite3 >/dev/null 2>&1; then sqlite3 -header -column db/pipeline.db `"select id, status, started_at, finished_at from runs order by coalesce(started_at, created_at) desc limit 25;`"; else ls -lah runs; fi"
        }
        break
    }

    'trigger-run' {
        $body = if ($Arg1) { "{`"input`":`"$Arg1`"}" } else { '{}' }
        try {
            Invoke-YoutubeApiCommand -Method 'POST' -Path '/runs' -Body $body
        }
        catch {
            Invoke-RemoteCommand -Command "cd '$RemoteRoot' && if [ -x scripts/run.sh ]; then ./scripts/run.sh; elif [ -f package.json ]; then bun run start; else echo 'No run entrypoint found.' >&2; exit 1; fi" -AllocateTty
        }
        break
    }

    'restart' {
        Invoke-RemoteCommand -Command "systemctl restart '$ServiceName' || (cd '$RemoteRoot' && docker compose restart) || pkill -f youtube-pipeline"
        break
    }

    'logs' {
        $logFile = Get-RemoteLogFile
        Invoke-RemoteCommand -Command "tail -n $Tail '$logFile'"
        break
    }

    'service-logs' {
        Invoke-RemoteCommand -Command "journalctl -u '$ServiceName' -n $Tail --no-pager"
        break
    }

    'disk' {
        Invoke-RemoteCommand -Command "df -h && echo && du -sh '$RemoteRoot' '$RemoteRoot/db' '$RemoteRoot/transcripts' 2>/dev/null || true"
        break
    }

    'sync' {
        $syncScript = Join-Path $PSScriptRoot 'sync.ps1'
        if (-not (Test-Path -LiteralPath $syncScript)) {
            throw "Missing sync script: $syncScript"
        }
        & $syncScript -HostName $HostName -RemoteRoot $RemoteRoot -LocalRoot $LocalRoot
        if ($LASTEXITCODE -ne 0) {
            throw "sync.ps1 failed with exit code $LASTEXITCODE."
        }
        break
    }

    'cleanup' {
        Invoke-RemoteCommand -Command "cd '$RemoteRoot' && find tmp -mindepth 1 -maxdepth 1 -mtime +3 -exec rm -rf {} + 2>/dev/null || true && find logs -type f -name '*.log' -mtime +14 -delete 2>/dev/null || true"
        break
    }

    'backfill' {
        Invoke-RemoteCommand -Command "cd '$RemoteRoot' && bun run scripts/backfill-transcripts.ts" -AllocateTty
        break
    }

    'produce' {
        Invoke-RemoteCommand -Command "cd '$RemoteRoot' && if [ -f db/pipeline.db ]; then python3 scripts/build_transcripts.py . && python3 scripts/build_library.py .; else echo 'Missing db/pipeline.db' >&2; exit 1; fi" -AllocateTty
        break
    }
}
