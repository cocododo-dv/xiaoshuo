param(
    [string]$DatabasePath,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
if (-not $DatabasePath) {
    $DatabasePath = Join-Path $backendDir "novel_system.db"
}
$env:PYTHONPATH = (Join-Path $backendDir "src") + [IO.Path]::PathSeparator + $env:PYTHONPATH

function Invoke-BackupTool {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & $Python -m novel_system.tools.db_backup @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "db_backup failed with exit code $LASTEXITCODE"
    }
}

$resolvedSource = (& $Python -c "import os,sys; from novel_system.tools.db_backup import resolve_sqlite_path as r; print(os.path.abspath(r(sys.argv[1])))" $DatabasePath | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $resolvedSource -PathType Leaf)) {
    throw "Source database does not exist: $resolvedSource"
}

$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$workDir = [IO.Path]::GetFullPath((Join-Path $tempRoot ("novel-backup-drill-" + [guid]::NewGuid().ToString("N"))))
if (-not $workDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary drill directory escaped the system temp root: $workDir"
}
[IO.Directory]::CreateDirectory($workDir) | Out-Null

$productionCopy = Join-Path $workDir "production-copy.db"
$backup = Join-Path $workDir "backup.db"
try {
    Write-Host "[drill] 1/5 Create an isolated production copy"
    Invoke-BackupTool --backup $resolvedSource $productionCopy | Out-Null

    Write-Host "[drill] 2/5 Create a consistent backup of the copy"
    Invoke-BackupTool --backup $productionCopy $backup | Out-Null

    Write-Host "[drill] 3/5 Verify manifest, checksum, integrity, and foreign keys"
    Invoke-BackupTool --verify $backup

    Write-Host "[drill] 4/5 Corrupt the temporary production copy"
    [IO.File]::WriteAllBytes($productionCopy, [byte[]]::new(128))

    Write-Host "[drill] 5/5 Restore the temporary copy and verify again"
    Invoke-BackupTool --restore $backup $productionCopy | Out-Null
    Invoke-BackupTool --verify $productionCopy
    Write-Host "[drill] Restore drill passed; the source database was not modified." -ForegroundColor Green
}
finally {
    $resolvedWorkDir = [IO.Path]::GetFullPath($workDir)
    if ($resolvedWorkDir.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedWorkDir)) {
        Remove-Item -LiteralPath $resolvedWorkDir -Recurse -Force
    }
}
