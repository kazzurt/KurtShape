param(
    [ValidateSet('plate','studio')][string]$Fixture = 'plate',
    [int]$Holes = 60,
    [int]$Repeat = 3
)
$ErrorActionPreference = 'Stop'
$reviewRoot = Split-Path -Parent $PSCommandPath
$appRoot = Split-Path -Parent (Split-Path -Parent $reviewRoot)
. (Join-Path $appRoot 'tools\validation-session.ps1')
$session = Join-Path $appRoot ('runtime\engine-responsiveness-review-working\' + $Fixture + '-' + [Guid]::NewGuid().ToString('N'))
Initialize-KurtShapeValidationEnvironment -Root $appRoot -Session $session
$sourcePaths = @(
    Get-ChildItem -LiteralPath (Join-Path $appRoot 'src\kurtshape') -File -Filter '*.py'
    Get-Item -LiteralPath (Join-Path $appRoot 'tools\perf\bench_core.py')
    Get-Item -LiteralPath (Join-Path $appRoot 'tools\perf\report.py')
    Get-Item -LiteralPath (Join-Path $appRoot 'tools\perf\budgets.json')
)
$fingerprints = @($sourcePaths | ForEach-Object {
    [ordered]@{path=$_.FullName.Substring($appRoot.Length+1);sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}
})
[ordered]@{
    captured_utc=[DateTimeOffset]::UtcNow.ToString('o')
    note='Current working tree, including uncommitted interaction changes; headless controller benchmark, not input-to-paint latency.'
    files=$fingerprints
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $session 'evidence\source-manifest.json') -Encoding utf8
$python = Join-Path $appRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
Invoke-KurtShapeValidationPython -Executable $python -Arguments @(
    '-B', (Join-Path $appRoot 'tools\perf\bench_core.py'),
    '--fixture', $Fixture, '--holes', [string]$Holes, '--repeat', [string]$Repeat,
    '--measure', 'false', '--scratch', (Join-Path $session 'native-fixtures'),
    '--out', (Join-Path $session 'evidence\benchmark.json')
) -Name ('responsiveness-review-' + $Fixture) -TimeoutSeconds 1200
$verification = @($fingerprints | ForEach-Object {
    $actual = (Get-FileHash -LiteralPath (Join-Path $appRoot $_.path) -Algorithm SHA256).Hash
    [ordered]@{path=$_.path;expected_sha256=$_.sha256;actual_sha256=$actual;unchanged=($actual -eq $_.sha256)}
})
$sourceUnchanged = @($verification | Where-Object { -not $_.unchanged }).Count -eq 0
[ordered]@{
    verified_utc=[DateTimeOffset]::UtcNow.ToString('o')
    passed=$sourceUnchanged
    checked_files=$verification.Count
    files=$verification
} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $session 'evidence\source-verification.json') -Encoding utf8
if (-not $sourceUnchanged) { throw 'Application or benchmark source changed during the review run; inspect source-verification.json.' }
Write-Output ('Review evidence: ' + (Join-Path $session 'evidence'))
