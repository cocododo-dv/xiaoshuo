param(
    [string]$Distro = "Ubuntu-24.04",
    [switch]$IncludeLegacyVue
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    Write-Host "==> $Label" -ForegroundColor Cyan
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw ("Native command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($ArgumentList -join " "))
    }
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

    Write-Host "==> $Label" -ForegroundColor Cyan
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

$repoRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $repoRoot "frontend"
$backendVenvPython = Join-Path $repoRoot "backend\.venv\bin\python"
$windowsScript = Join-Path $repoRoot "scripts\verify_windows.ps1"
$repoRootForWslPath = $repoRoot -replace "\\", "/"
$sharedWslPython = ""

$windowsArgs = @("-ExecutionPolicy", "Bypass", "-File", $windowsScript)
if ($IncludeLegacyVue) { $windowsArgs += "-IncludeLegacyVue" }
Invoke-NativeCommand -Label "Windows verification lane" -FilePath "powershell" -ArgumentList $windowsArgs

# React mainline contract E2E (run-smokes.mjs) is the default release gate for the
# production frontend: verify_react_e2e.ps1 spins up an isolated seeded backend on :8009
# + the React app on :5174, runs the smoke suites (reseeding between each), then tears
# everything down. Needs Playwright installed in frontend/ (cd frontend; npm ci).
$reactE2eScript = Join-Path $repoRoot "scripts\verify_react_e2e.ps1"
Invoke-NativeCommand -Label "React mainline contract E2E (run-smokes)" -FilePath "powershell" -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $reactE2eScript)

# Legacy Vue seeded Playwright E2E is no longer a default release gate (reversible).
# Pass -IncludeLegacyVue to include it.
if ($IncludeLegacyVue) {
    Invoke-NativeStep -Label "Seeded runtime-ops E2E lane (legacy Vue)" -WorkingDirectory $frontendDir -FilePath "npm.cmd" -ArgumentList @("run", "test:e2e")
}

$repoRootWsl = (& wsl.exe -d $Distro wslpath -a "$repoRootForWslPath" | Out-String).Trim()
if (-not $repoRootWsl) {
    throw "Could not resolve the repository path inside WSL."
}

if (-not (Test-Path $backendVenvPython)) {
    $worktreeRoots = (& git -C $repoRoot worktree list --porcelain | Select-String "^worktree " | ForEach-Object {
        $_.Line.Substring("worktree ".Length)
    })
    foreach ($worktreeRoot in $worktreeRoots) {
        if ($worktreeRoot -eq $repoRoot) {
            continue
        }
        $candidatePython = Join-Path $worktreeRoot "backend\.venv\bin\python"
        if (Test-Path $candidatePython) {
            $candidatePythonForWslPath = $candidatePython -replace "\\", "/"
            $sharedWslPython = (& wsl.exe -d $Distro wslpath -a "$candidatePythonForWslPath" | Out-String).Trim()
            if ($sharedWslPython) {
                break
            }
        }
    }
}

$bashCommand = "cd '$repoRootWsl' && "
if ($sharedWslPython) {
    $bashCommand += "PYTHON_BIN='$sharedWslPython' "
}
$bashCommand += "bash scripts/verify_wsl_strict.sh"

Invoke-NativeCommand -Label "WSL strict Chroma verification lane" -FilePath "wsl.exe" -ArgumentList @("-d", $Distro, "bash", "-lc", $bashCommand)
