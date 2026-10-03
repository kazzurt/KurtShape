param([switch]$SkipNativeTests, [int]$Holes = 20, [int]$Repeat = 3, [string[]]$KurtOwnedPath = @())
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if ($Holes -lt 1 -or $Repeat -lt 1) { throw 'Holes and repeats must be positive.' }
. (Join-Path $root 'tools\validation-session.ps1')
$variables = @('KURTSHAPE_ROOT','KURTSHAPE_SESSION_DIR','KURTSHAPE_EVIDENCE_DIR','KURTSHAPE_WRITE_EVIDENCE','FREECAD_USER_HOME','TEMP','TMP','APPDATA','LOCALAPPDATA','KURTSHAPE_TEST_TMP','KURTSHAPE_TEST_OUTSIDE','PYTHONDONTWRITEBYTECODE')
$previous = @{}
foreach ($name in $variables) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
$session = Join-Path $root ('runtime\ci-local\run-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N'))
Initialize-KurtShapeValidationEnvironment -Root $root -Session $session
# Tests create and remove their own short-lived scratch under this ungranted parent.
# runtime/ is already within the default Codex grant and cannot test rejection.
$env:KURTSHAPE_TEST_OUTSIDE = Split-Path -Parent (Split-Path -Parent $root)
$snapshot = Join-Path $session 'tree-before.json'
& (Join-Path $root 'tools\check-local-tree.ps1') -Mode Capture -SnapshotPath $snapshot -KurtOwnedPath $KurtOwnedPath
& (Join-Path $PSScriptRoot 'check-runtime-layout.ps1')
$python = Join-Path $root 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
$checks = @([ordered]@{name='runtime layout';passed=$true})
if (-not $SkipNativeTests) {
    $nativeReport = Join-Path $session 'evidence\native-tests.json'
    Invoke-KurtShapeValidationPython -Executable $python -Arguments @('-B',(Join-Path $root 'tools\run_native_tests.py'),'--require-native','--report',$nativeReport,'--junit',(Join-Path $session 'evidence\junit.xml')) -Name 'ci-native-tests' -TimeoutSeconds 7500
    $checks += [ordered]@{name='native suites';passed=$true;report=$nativeReport}
}
$benchmark = Join-Path $session ('evidence\perf\bench-' + $Holes + '.json')
Invoke-KurtShapeValidationPython -Executable $python -Arguments @('-B',(Join-Path $root 'tools\perf\bench_core.py'),'--fixture','plate','--holes',[string]$Holes,'--repeat',[string]$Repeat,'--scratch',(Join-Path $session 'bench'),'--out',$benchmark) -Name 'ci-benchmark' -TimeoutSeconds 7200
$benchResult = Get-Content -LiteralPath $benchmark -Raw | ConvertFrom-Json
if ($benchResult.passed -isnot [bool] -or -not $benchResult.passed) { throw ('Local benchmark has unavailable or failed required sections: ' + $benchmark) }
$checks += [ordered]@{name='plate benchmark';passed=$true;report=$benchmark}
& (Join-Path $root 'tools\check-local-tree.ps1') -Mode Compare -SnapshotPath $snapshot -KurtOwnedPath $KurtOwnedPath
$checks += [ordered]@{name='exact local tree comparison';passed=$true}
$report = Join-Path $session 'evidence\ci-local.json'
[ordered]@{passed=$true;method='tools/ci/run-local.ps1';checks=$checks;native_tests_skipped=[bool]$SkipNativeTests;session=$session;limits='Hosted CI and lint not exercised by this local gate.'} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $report -Encoding utf8
Write-Output ('Local CI passed. Report: ' + $report)
} finally {
    foreach ($name in $variables) {
        if ($null -eq $previous[$name]) { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
        else { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    }
}
