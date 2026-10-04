param([ValidateRange(1,900)][int]$TimeoutSeconds = 300)
$ErrorActionPreference = 'Stop'
$q03Root = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$q03Base = Join-Path $q03Root 'runtime\ci-gui\q03-status'
$q03Session = Join-Path $q03Base ('run-' + [Guid]::NewGuid().ToString('N'))
$q03Names = @('KURTSHAPE_ROOT','KURTSHAPE_SESSION_DIR','KURTSHAPE_EVIDENCE_DIR','KURTSHAPE_WRITE_EVIDENCE','FREECAD_USER_HOME','TEMP','TMP','APPDATA','LOCALAPPDATA','KURTSHAPE_TEST_TMP','PYTHONDONTWRITEBYTECODE','QT_QPA_PLATFORM','KURTSHAPE_DEMO','KURTSHAPE_NO_DEMO','KURTSHAPE_STARTUP_BASELINE')
$q03Previous = @{}
foreach ($name in $q03Names) { $q03Previous[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
$q03Process = $null
try {
    Initialize-KurtShapeValidationEnvironment -Root $q03Root -Session $q03Session -SessionBase $q03Base
    foreach ($name in @('QT_QPA_PLATFORM','KURTSHAPE_DEMO','KURTSHAPE_STARTUP_BASELINE')) { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
    $env:KURTSHAPE_NO_DEMO = '1'
    $q03Executable = Join-Path $q03Root 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
    $q03Macro = Join-Path $PSScriptRoot 'q03-status-validation.FCMacro'
    $q03Report = Join-Path $q03Session 'evidence\q03-status\gui-result.json'
    $q03Arguments = @('-u',('"' + (Join-Path $q03Session 'user-data\user.cfg') + '"'),'-s',('"' + (Join-Path $q03Session 'user-data\system.cfg') + '"'),'--log-file',('"' + (Join-Path $q03Session 'freecad.log') + '"'),('"' + $q03Macro + '"'))
    $q03Process = Start-Process -FilePath $q03Executable -ArgumentList $q03Arguments -WorkingDirectory $q03Root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $q03Session 'stdout.txt') -RedirectStandardError (Join-Path $q03Session 'stderr.txt')
    Register-KurtShapeValidationProcess -Process $q03Process -Executable $q03Executable -Arguments $q03Arguments
    if (-not $q03Process.WaitForExit($TimeoutSeconds * 1000)) { throw 'Q03 GUI timed out.' }
    $q03Process.Refresh()
    if ($q03Process.ExitCode -ne 0) { throw ('Q03 GUI exited ' + $q03Process.ExitCode) }
    $q03Result = Get-Content -LiteralPath $q03Report -Raw | ConvertFrom-Json
    if ($q03Result.passed -isnot [bool] -or -not $q03Result.passed -or $q03Result.check_count -ne 17 -or @($q03Result.checks).Count -ne 17 -or -not $q03Result.owned_documents_closed -or -not $q03Result.source_unchanged -or $q03Result.cleanup_errors) { throw ('Q03 GUI failed. Report: ' + $q03Report) }
    Write-Output ('Q03 GUI passed 17 checks. Report: ' + $q03Report)
} finally {
    if ($q03Process) {
        if (-not $q03Process.HasExited) { Stop-Process -Id $q03Process.Id -Force; $q03Process.WaitForExit() }
        $q03Process.Dispose()
    }
    foreach ($name in $q03Names) {
        if ($null -eq $q03Previous[$name]) { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name,$q03Previous[$name],'Process') }
    }
}