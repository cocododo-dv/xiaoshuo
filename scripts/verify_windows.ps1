param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
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

if (-not $FrontendOnly) {
    Invoke-NativeStep -Label "Backend pytest (not chroma_integration)" -WorkingDirectory $backendDir -FilePath "python" -ArgumentList @("-m", "pytest", "-q", "-m", "not chroma_integration")
}

if (-not $BackendOnly) {
    Invoke-NativeStep -Label "Frontend tests" -WorkingDirectory $frontendDir -FilePath "npm.cmd" -ArgumentList @("test")
    Invoke-NativeStep -Label "Frontend build" -WorkingDirectory $frontendDir -FilePath "npm.cmd" -ArgumentList @("run", "build")
}
