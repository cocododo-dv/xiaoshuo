param(
    [string]$Distro = "Ubuntu-24.04"
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

$repoRoot = Split-Path -Parent $PSScriptRoot
$windowsScript = Join-Path $repoRoot "scripts\verify_windows.ps1"
$repoRootForWslPath = $repoRoot -replace "\\", "/"

Invoke-NativeCommand -Label "Windows verification lane" -FilePath "powershell" -ArgumentList @("-ExecutionPolicy", "Bypass", "-File", $windowsScript)

$repoRootWsl = (& wsl.exe -d $Distro wslpath -a "$repoRootForWslPath" | Out-String).Trim()
if (-not $repoRootWsl) {
    throw "Could not resolve the repository path inside WSL."
}

$bashCommand = "cd '$repoRootWsl' && bash scripts/verify_wsl_strict.sh"

Invoke-NativeCommand -Label "WSL strict Chroma verification lane" -FilePath "wsl.exe" -ArgumentList @("-d", $Distro, "bash", "-lc", $bashCommand)
