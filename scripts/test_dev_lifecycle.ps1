$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-True {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-CheckedScript {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    & $FilePath
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1}" -f $LASTEXITCODE, $FilePath)
    }
}

function Wait-Until {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Condition,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) {
            return
        }
        Start-Sleep -Seconds 1
    }

    throw ("Timed out waiting for {0}." -f $Label)
}

function Test-UrlHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec 5
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Test-PortClosed {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    return @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    ).Count -eq 0
}

function Read-RequiredText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Assert-True -Condition (Test-Path $Path) -Message ("Missing expected file: {0}" -f $Path)
    return (Get-Content -Path $Path -Raw).Trim()
}

function Get-PortFromUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url
    )

    return ([System.Uri]$Url).Port
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$mainScript = Join-Path $repoRoot "scripts\dev.ps1"
$startWrapper = Join-Path $repoRoot "start-dev.cmd"
$stopWrapper = Join-Path $repoRoot "stop-dev.cmd"
$restartWrapper = Join-Path $repoRoot "restart-dev.cmd"
$runDir = Join-Path $repoRoot ".codex-run"
$backendPidFile = Join-Path $runDir "backend.pid"
$frontendPidFile = Join-Path $runDir "frontend.pid"
$backendUrlFile = Join-Path $runDir "backend.url"
$frontendUrlFile = Join-Path $runDir "frontend.url"

Assert-True -Condition (Test-Path $mainScript) -Message "Missing lifecycle script: scripts/dev.ps1"
Assert-True -Condition (Test-Path $startWrapper) -Message "Missing wrapper: start-dev.cmd"
Assert-True -Condition (Test-Path $stopWrapper) -Message "Missing wrapper: stop-dev.cmd"
Assert-True -Condition (Test-Path $restartWrapper) -Message "Missing wrapper: restart-dev.cmd"

try {
    Invoke-CheckedScript -FilePath $stopWrapper
    Wait-Until -Label "ports 8000/5173 to be closed" -Condition {
        (Test-PortClosed -Port 8000) -and (Test-PortClosed -Port 5173)
    } -TimeoutSeconds 20

    Invoke-CheckedScript -FilePath $startWrapper
    $backendUrl = Read-RequiredText -Path $backendUrlFile
    $frontendUrl = Read-RequiredText -Path $frontendUrlFile
    Wait-Until -Label "backend health" -Condition { Test-UrlHealthy -Url "$backendUrl/api/v1/chapters" } -TimeoutSeconds 90
    Wait-Until -Label "frontend home" -Condition { Test-UrlHealthy -Url $frontendUrl } -TimeoutSeconds 60
    Assert-True -Condition (Test-Path $backendPidFile) -Message "Missing backend PID file after start."
    Assert-True -Condition (Test-Path $frontendPidFile) -Message "Missing frontend PID file after start."

    Invoke-CheckedScript -FilePath $restartWrapper
    $backendUrl = Read-RequiredText -Path $backendUrlFile
    $frontendUrl = Read-RequiredText -Path $frontendUrlFile
    Wait-Until -Label "backend after restart" -Condition { Test-UrlHealthy -Url "$backendUrl/api/v1/chapters" } -TimeoutSeconds 90
    Wait-Until -Label "frontend after restart" -Condition { Test-UrlHealthy -Url $frontendUrl } -TimeoutSeconds 60
    Assert-True -Condition (Test-Path $backendPidFile) -Message "Missing backend PID file after restart."
    Assert-True -Condition (Test-Path $frontendPidFile) -Message "Missing frontend PID file after restart."

    $backendPort = Get-PortFromUrl -Url $backendUrl
    $frontendPort = Get-PortFromUrl -Url $frontendUrl
    Invoke-CheckedScript -FilePath $stopWrapper
    Wait-Until -Label "dev service ports to close after stop" -Condition {
        (Test-PortClosed -Port $backendPort) -and (Test-PortClosed -Port $frontendPort)
    } -TimeoutSeconds 30
    Assert-True -Condition (-not (Test-Path $backendPidFile)) -Message "Backend PID file still exists after stop."
    Assert-True -Condition (-not (Test-Path $frontendPidFile)) -Message "Frontend PID file still exists after stop."
}
finally {
    if (Test-Path $stopWrapper) {
        try {
            & $stopWrapper | Out-Host
        }
        catch {
        }
    }
}

Write-Host "Lifecycle smoke test passed." -ForegroundColor Green
