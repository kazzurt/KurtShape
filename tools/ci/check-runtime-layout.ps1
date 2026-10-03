param([string]$RuntimeRoot)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $RuntimeRoot) { $RuntimeRoot = Join-Path $root 'runtime' }
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$runtimeHome = Join-Path $RuntimeRoot 'freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311'
foreach ($name in @('python.exe','freecadcmd.exe','freecad.exe','FreeCAD.pyd','opengl32sw.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeHome ('bin\' + $name)) -PathType Leaf)) {
        throw ('Pinned runtime file missing: ' + $name)
    }
}
. (Join-Path $root 'tools\validation-session.ps1')
$variables = @('KURTSHAPE_ROOT','KURTSHAPE_SESSION_DIR','KURTSHAPE_EVIDENCE_DIR','KURTSHAPE_WRITE_EVIDENCE','FREECAD_USER_HOME','TEMP','TMP','APPDATA','LOCALAPPDATA','KURTSHAPE_TEST_TMP','PYTHONDONTWRITEBYTECODE')
$previous = @{}
foreach ($name in $variables) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $session = Join-Path $root ('runtime\ci-local\layout-' + [Guid]::NewGuid().ToString('N'))
    Initialize-KurtShapeValidationEnvironment -Root $root -Session $session
    $report = Join-Path $session 'evidence\runtime-layout.json'
    Invoke-KurtShapeValidationPython -Executable (Join-Path $runtimeHome 'bin\python.exe') -Arguments @('-B',(Join-Path $PSScriptRoot 'check_runtime_layout.py'),'--home',$runtimeHome,'--report',$report) -Name 'runtime-layout' -TimeoutSeconds 120
    $result = Get-Content -LiteralPath $report -Raw | ConvertFrom-Json
    if ($result.passed -isnot [bool] -or -not $result.passed) { throw 'Runtime layout probe did not pass.' }
    Write-Output ("['1','1','4'] 7.8.1 " + $result.home)
} finally {
    foreach ($name in $variables) {
        if ($null -eq $previous[$name]) { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    }
}
