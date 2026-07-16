param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly,
    [switch]$IncludeLegacyVue
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"
$reactDir = Join-Path $repoRoot "frontend-react"

if (-not $FrontendOnly) {
    Invoke-NativeStep -Label "Backend pytest (not chroma_integration)" -WorkingDirectory $backendDir -FilePath "python" -ArgumentList @("-m", "pytest", "-q", "-m", "not chroma_integration")
}

if (-not $BackendOnly) {
    # Governance QA lane contract tests (scripts/tests) run from the repo root.
    # Node on Windows does not expand a directory argument into test files; pass the
    # maintained *.test.cjs files explicitly so this lane behaves like CI.
    $scriptTestFiles = @(
        Get-ChildItem -Path (Join-Path $repoRoot "scripts\tests") -Filter "*.test.cjs" -File |
            Sort-Object Name |
            ForEach-Object { $_.FullName }
    )
    if ($scriptTestFiles.Count -eq 0) {
        throw "No script contract tests found under scripts/tests."
    }
    Invoke-NativeStep -Label "Script contract tests (scripts/tests)" -WorkingDirectory $repoRoot -FilePath "node" -ArgumentList (@("--test") + $scriptTestFiles)

    # React mainline (frontend-react) is the default frontend gate: vitest unit tests + build.
    Invoke-NativeStep -Label "React frontend tests" -WorkingDirectory $reactDir -FilePath "npm.cmd" -ArgumentList @("test")
    Invoke-NativeStep -Label "React frontend build" -WorkingDirectory $reactDir -FilePath "npm.cmd" -ArgumentList @("run", "build")

    # Legacy Vue frontend is no longer a default gate (reversible); pass -IncludeLegacyVue to include it.
    if ($IncludeLegacyVue) {
        Invoke-NativeStep -Label "Legacy Vue frontend tests" -WorkingDirectory $frontendDir -FilePath "npm.cmd" -ArgumentList @("test")
        Invoke-NativeStep -Label "Legacy Vue frontend build" -WorkingDirectory $frontendDir -FilePath "npm.cmd" -ArgumentList @("run", "build")
    }
}
