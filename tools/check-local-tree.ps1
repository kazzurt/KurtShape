param(
    [ValidateSet('Capture','Compare')][string]$Mode = 'Compare',
    [string]$SnapshotPath,
    [string[]]$KurtOwnedPath = @()
)
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if (-not $SnapshotPath) { $SnapshotPath = Join-Path $repositoryRoot 'runtime\longrun\tree-before.json' }
if (-not [IO.Path]::IsPathRooted($SnapshotPath)) { $SnapshotPath = Join-Path $repositoryRoot $SnapshotPath }
$SnapshotPath = [IO.Path]::GetFullPath($SnapshotPath)
$runtimeRoot = Join-Path $repositoryRoot 'runtime'
if (-not $SnapshotPath.StartsWith($runtimeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Store the local tree snapshot under runtime.'
}
$statusDocument = Get-Content -LiteralPath (Join-Path $repositoryRoot 'docs\long-run\STATUS.md') -Raw
$exclusions = @('docs/long-run/')
foreach ($path in $KurtOwnedPath) {
    $normalized = $path.Replace('\','/')
    if ($normalized.StartsWith('./', [StringComparison]::Ordinal)) { $normalized = $normalized.Substring(2) }
    if (-not $normalized -or $normalized.Contains('..') -or [IO.Path]::IsPathRooted($path)) {
        throw ('Kurt-owned exclusions must be explicit repository paths: ' + $path)
    }
    if (-not $statusDocument.Replace('\','/').Contains($normalized)) {
        throw ('Document this Kurt-owned path in STATUS before excluding it: ' + $normalized)
    }
    $exclusions += $normalized
}
Push-Location $repositoryRoot
try {
    $status = @(& git -c core.quotepath=false status --porcelain --ignored=matching --untracked-files=normal)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read git status.' }
    $status = @($status | Where-Object {
        $path = $_.Substring(3).Trim('"').Replace('\','/')
        $excluded = $false
        foreach ($entry in $exclusions) {
            if ($path -eq $entry -or ($entry.EndsWith('/') -and $path.StartsWith($entry, [StringComparison]::Ordinal))) { $excluded = $true }
        }
        -not $excluded
    })
    $pathspecs = @('.') + @($exclusions | ForEach-Object { ':(exclude)' + $_ })
    $snapshotFolder = Split-Path -Parent $SnapshotPath
    New-Item -ItemType Directory -Force -Path $snapshotFolder | Out-Null
    $diffPath = Join-Path $snapshotFolder ('local-tree-diff-' + [Guid]::NewGuid().ToString('N') + '.patch')
    try {
        & git -c core.quotepath=false diff --binary HEAD --output $diffPath -- @pathspecs
        if ($LASTEXITCODE -ne 0) { throw 'Cannot read git diff HEAD.' }
        $hash = (Get-FileHash -LiteralPath $diffPath -Algorithm SHA256).Hash.ToLowerInvariant()
    } finally {
        if (Test-Path -LiteralPath $diffPath) { Remove-Item -LiteralPath $diffPath }
    }
    $snapshot = [ordered]@{schema_version=1; exclusions=$exclusions; status=$status; diff_sha256=$hash}
    if ($Mode -eq 'Capture') {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SnapshotPath) | Out-Null
        $snapshot | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $SnapshotPath -Encoding utf8
        Write-Output ('Captured local tree: ' + $SnapshotPath)
    } else {
        $before = Get-Content -LiteralPath $SnapshotPath -Raw | ConvertFrom-Json
        if (($before.exclusions -join "`n") -ne ($exclusions -join "`n")) { throw 'Use the same documented exclusions as the captured tree.' }
        $changes = @(Compare-Object -ReferenceObject @($before.status) -DifferenceObject @($status))
        if ($changes.Count -or $before.diff_sha256 -ne $hash) {
            if ($changes.Count) { $changes | Format-Table -AutoSize | Out-String | Write-Host }
            throw ('Local tree changed during checks. Before diff SHA256: ' + $before.diff_sha256 + '; after: ' + $hash + '. No files were restored or removed.')
        }
        Write-Output ('Local tree unchanged; diff SHA256 ' + $hash)
    }
} finally { Pop-Location }
