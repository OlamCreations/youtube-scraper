[CmdletBinding()]
param(
    [string]$HostName,
    [string]$RemoteRoot,
    [string]$LocalRoot,
    [string]$LogDir,
    [string]$Python,
    [switch]$SkipRebuild
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
if (-not $LogDir) { $LogDir = if ($env:LOG_DIR) { $env:LOG_DIR } else { Join-Path $repoRoot 'logs' } }
if (-not $Python) { $Python = if ($env:PYTHON) { $env:PYTHON } else { 'python' } }

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

function Invoke-Ssh {
    param(
        [Parameter(Mandatory)]
        [string]$Command
    )

    Assert-SafeValue -Value $HostName -Name 'HostName'
    Assert-SafeValue -Value $RemoteRoot -Name 'RemoteRoot'
    Assert-SafeValue -Value $Command -Name 'Command'

    & ssh $HostName "bash -lc '$Command'"
    if ($LASTEXITCODE -ne 0) {
        throw "SSH command failed with exit code $LASTEXITCODE."
    }
}

function New-LogPath {
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    Join-Path $LogDir "sync-$timestamp.log"
}

New-Item -ItemType Directory -Force -Path $LocalRoot | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$logPath = New-LogPath
$buildTranscriptsScript = Join-Path $PSScriptRoot 'build_transcripts.py'
$buildLibraryScript = Join-Path $PSScriptRoot 'build_library.py'

Assert-SafeValue -Value $HostName -Name 'HostName'
Assert-SafeValue -Value $RemoteRoot -Name 'RemoteRoot'

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$remoteBundle = "$RemoteRoot/tmp/sync_bundle-$timestamp.tgz"
$localBundle = Join-Path $env:TEMP "sync_bundle-$timestamp.tgz"

"[$(Get-Date -Format s)] creating remote archive $remoteBundle" | Tee-Object -FilePath $logPath -Append
Invoke-Ssh -Command "mkdir -p '$RemoteRoot/tmp' && cd '$RemoteRoot' && tar -czf '$remoteBundle' db transcripts library metadata logs --ignore-failed-read"

"[$(Get-Date -Format s)] downloading archive to $localBundle" | Tee-Object -FilePath $logPath -Append
& scp "${HostName}:$remoteBundle" $localBundle
if ($LASTEXITCODE -ne 0) {
    throw "scp failed with exit code $LASTEXITCODE."
}

"[$(Get-Date -Format s)] extracting archive into $LocalRoot" | Tee-Object -FilePath $logPath -Append
tar -xzf $localBundle -C $LocalRoot
if ($LASTEXITCODE -ne 0) {
    throw "tar extraction failed with exit code $LASTEXITCODE."
}

if (-not $SkipRebuild) {
    "[$(Get-Date -Format s)] rebuilding local transcript outputs" | Tee-Object -FilePath $logPath -Append
    & $Python $buildTranscriptsScript $LocalRoot 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "build_transcripts.py failed with exit code $LASTEXITCODE."
    }

    & $Python $buildLibraryScript $LocalRoot 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "build_library.py failed with exit code $LASTEXITCODE."
    }
}

"[$(Get-Date -Format s)] cleaning up remote archive" | Tee-Object -FilePath $logPath -Append
Invoke-Ssh -Command "rm -f '$remoteBundle'"

if (Test-Path -LiteralPath $localBundle) {
    Remove-Item -LiteralPath $localBundle -Force
}

"[$(Get-Date -Format s)] sync complete" | Tee-Object -FilePath $logPath -Append
