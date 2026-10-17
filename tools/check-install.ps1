param([string]$RuntimeRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime'))
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path ([IO.Path]::GetFullPath($RuntimeRoot)) 'freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 to install the pinned runtime.' }
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$names = @('KURTSHAPE_ROOT','KURTSHAPE_SESSION_DIR','KURTSHAPE_EVIDENCE_DIR','KURTSHAPE_WRITE_EVIDENCE','FREECAD_USER_HOME','TEMP','TMP','APPDATA','LOCALAPPDATA','KURTSHAPE_TEST_TMP','PYTHONDONTWRITEBYTECODE')
$previous = @{}
foreach ($name in $names) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $session = Join-Path $root ('runtime\installation-check\' + [Guid]::NewGuid().ToString('N'))
    Initialize-KurtShapeValidationEnvironment -Root $root -Session $session
    $report = Join-Path $session 'evidence\installation.json'
    Invoke-KurtShapeValidationPython -Executable $pythonPath -Arguments @('-B',(Join-Path $PSScriptRoot 'installation_smoke.py'),'--report',$report) -Name 'installation-smoke' -TimeoutSeconds 180
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($result.passed -isnot [bool] -or -not $result.passed) { throw ('Installation check failed: ' + $report) }
    Write-Output ('Installation report: ' + $report)
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
