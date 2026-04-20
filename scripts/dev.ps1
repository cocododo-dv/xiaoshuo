param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("start", "stop", "restart")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    Write-Step -Message $Label
    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw ("Native command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($ArgumentList -join " "))
        }
    }
    finally {
        Pop-Location
    }
}

function Assert-CommandAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw ("Required command not found: {0}" -f $Name)
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

function Test-PortListening {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    return @(
        Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    ).Count -gt 0
}

function Get-RecordedRootProcessIds {
    $recorded = New-Object System.Collections.Generic.List[int]
    foreach ($pidFile in @($script:BackendPidFile, $script:FrontendPidFile)) {
        if (-not (Test-Path $pidFile)) {
            continue
        }

        foreach ($line in (Get-Content -Path $pidFile -ErrorAction SilentlyContinue)) {
            $value = 0
            if ([int]::TryParse(($line | Out-String).Trim(), [ref]$value)) {
                [void]$recorded.Add($value)
            }
        }
    }

    return @($recorded | Select-Object -Unique)
}

function Test-ProcessAlive {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    return $null -ne (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Get-LiveRecordedRootProcessIds {
    return @(
        Get-RecordedRootProcessIds | Where-Object { Test-ProcessAlive -ProcessId $_ }
    )
}

function Get-DescendantProcessIds {
    param(
        [Parameter(Mandatory = $true)]
        [int[]]$RootProcessIds
    )

    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    $allIds = New-Object System.Collections.Generic.HashSet[int]
    $queue = [System.Collections.Generic.Queue[int]]::new()

    foreach ($rootId in $RootProcessIds) {
        if ($allIds.Add($rootId)) {
            $queue.Enqueue($rootId)
        }
    }

    while ($queue.Count -gt 0) {
        $current = $queue.Dequeue()
        $children = @($processes | Where-Object { $_.ParentProcessId -eq $current })
        foreach ($child in $children) {
            $childId = [int]$child.ProcessId
            if ($allIds.Add($childId)) {
                $queue.Enqueue($childId)
            }
        }
    }

    return @($allIds)
}

function Remove-RunState {
    Remove-Item $script:BackendPidFile, $script:FrontendPidFile -ErrorAction SilentlyContinue
}

function Clear-PreviousLogs {
    Remove-Item $script:BackendOutLog, $script:BackendErrLog, $script:FrontendOutLog, $script:FrontendErrLog -ErrorAction SilentlyContinue
}

function Stop-TrackedServices {
    $recordedIds = @(Get-RecordedRootProcessIds)
    if ($recordedIds.Count -eq 0) {
        Write-Step -Message "No tracked dev services are running."
        Remove-RunState
        return
    }

    Write-Step -Message "Stopping tracked dev services"
    $allIds = @(Get-DescendantProcessIds -RootProcessIds $recordedIds)
    foreach ($processId in ($allIds | Sort-Object -Descending)) {
        try {
            Stop-Process -Id $processId -Force -ErrorAction Stop
        }
        catch {
        }
    }

    Start-Sleep -Seconds 2
    Remove-RunState
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    if (Test-PortListening -Port $Port) {
        throw ("{0} port {1} is already in use. Run .\\stop-dev.cmd or .\\restart-dev.cmd first." -f $Label, $Port)
    }
}

function Invoke-BackendBootstrap {
    $previousPythonPath = $env:PYTHONPATH
    $previousVectorBackend = $env:NOVEL_SYSTEM_VECTOR_BACKEND

    try {
        $env:PYTHONPATH = "src"
        $env:NOVEL_SYSTEM_VECTOR_BACKEND = "memory"
        Invoke-NativeStep -Label "Backend migration" -WorkingDirectory $script:BackendDir -FilePath "python" -ArgumentList @("-m", "alembic", "upgrade", "head")
        if (Test-DemoSeedSkipped) {
            Write-Step -Message "Demo seed skipped; clean reset marker is active."
        }
        else {
            Invoke-NativeStep -Label "Demo seed" -WorkingDirectory $script:BackendDir -FilePath "python" -ArgumentList @("-m", "novel_system.tools.seed_demo")
        }
    }
    finally {
        if ($null -eq $previousPythonPath) {
            Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
        }
        else {
            $env:PYTHONPATH = $previousPythonPath
        }

        if ($null -eq $previousVectorBackend) {
            Remove-Item Env:NOVEL_SYSTEM_VECTOR_BACKEND -ErrorAction SilentlyContinue
        }
        else {
            $env:NOVEL_SYSTEM_VECTOR_BACKEND = $previousVectorBackend
        }
    }
}

function Test-DemoSeedSkipped {
    if ($env:NOVEL_SYSTEM_SKIP_DEMO_SEED -eq "1") {
        return $true
    }
    return Test-Path -LiteralPath $script:SkipDemoSeedMarker
}

function Start-TrackedServices {
    Assert-CommandAvailable -Name "python"
    Assert-CommandAvailable -Name "npm.cmd"

    $liveTrackedIds = @(Get-LiveRecordedRootProcessIds)
    if ($liveTrackedIds.Count -gt 0) {
        throw "Tracked dev services already appear to be running. Use .\\restart-dev.cmd or .\\stop-dev.cmd first."
    }

    Remove-RunState
    Assert-PortAvailable -Port $script:BackendPort -Label "Backend"
    Assert-PortAvailable -Port $script:FrontendPort -Label "Frontend"

    New-Item -ItemType Directory -Path $script:RunDir -Force | Out-Null
    Clear-PreviousLogs
    Invoke-BackendBootstrap

    try {
        Write-Step -Message "Starting backend on $script:BackendUrl"
        $backendCommand = '$env:PYTHONPATH = ''src''; $env:NOVEL_SYSTEM_VECTOR_BACKEND = ''memory''; python -m uvicorn novel_system.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000 --app-dir src'
        $backendProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $backendCommand) -WorkingDirectory $script:BackendDir -RedirectStandardOutput $script:BackendOutLog -RedirectStandardError $script:BackendErrLog -PassThru
        Set-Content -Path $script:BackendPidFile -Value $backendProcess.Id

        Write-Step -Message "Starting frontend on $script:FrontendUrl"
        $frontendCommand = 'npm.cmd run dev -- --host 127.0.0.1 --port 5173'
        $frontendProcess = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand) -WorkingDirectory $script:FrontendDir -RedirectStandardOutput $script:FrontendOutLog -RedirectStandardError $script:FrontendErrLog -PassThru
        Set-Content -Path $script:FrontendPidFile -Value $frontendProcess.Id

        Wait-Until -Label "backend health" -Condition { Test-UrlHealthy -Url $script:BackendHealthUrl } -TimeoutSeconds 90
        Wait-Until -Label "frontend home" -Condition { Test-UrlHealthy -Url $script:FrontendUrl } -TimeoutSeconds 60
    }
    catch {
        Stop-TrackedServices
        throw
    }

    Write-Host ("Backend:  {0}" -f $script:BackendUrl) -ForegroundColor Green
    Write-Host ("Frontend: {0}" -f $script:FrontendUrl) -ForegroundColor Green
    Write-Host ("Logs:     {0}" -f $script:RunDir) -ForegroundColor Green
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$script:BackendDir = Join-Path $repoRoot "backend"
$script:FrontendDir = Join-Path $repoRoot "frontend"
$script:RunDir = Join-Path $repoRoot ".codex-run"
$script:BackendPidFile = Join-Path $script:RunDir "backend.pid"
$script:FrontendPidFile = Join-Path $script:RunDir "frontend.pid"
$script:SkipDemoSeedMarker = Join-Path $script:RunDir "skip-demo-seed"
$script:BackendOutLog = Join-Path $script:RunDir "backend.out.log"
$script:BackendErrLog = Join-Path $script:RunDir "backend.err.log"
$script:FrontendOutLog = Join-Path $script:RunDir "frontend.out.log"
$script:FrontendErrLog = Join-Path $script:RunDir "frontend.err.log"
$script:BackendPort = 8000
$script:FrontendPort = 5173
$script:BackendUrl = "http://127.0.0.1:8000"
$script:BackendHealthUrl = "$script:BackendUrl/api/v1/chapters"
$script:FrontendUrl = "http://127.0.0.1:5173"

switch ($Action) {
    "start" {
        Start-TrackedServices
    }
    "stop" {
        Stop-TrackedServices
    }
    "restart" {
        Stop-TrackedServices
        Start-TrackedServices
    }
}
