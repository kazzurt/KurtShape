param([switch]$Full, [switch]$WriteEvidence, [switch]$Lint, [switch]$KeepNativeTemp)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'tools\validation-session.ps1')
Push-Location $PSScriptRoot
try {
    $checksSession = Join-Path $PSScriptRoot ('runtime\test-tmp\checks-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss') + '-' + $PID)
    Initialize-KurtShapeValidationEnvironment -Root $PSScriptRoot -Session $checksSession -WriteEvidence:$WriteEvidence
    $env:KURTSHAPE_TEST_TMP = Join-Path $PSScriptRoot 'runtime\test-tmp'
    $pythonPath = Join-Path $PSScriptRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run install-runtime.ps1 first.' }
    $examples = if ($env:KURTSHAPE_ONSHAPE_EXAMPLES) { $env:KURTSHAPE_ONSHAPE_EXAMPLES }
                else { Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'Onshape examples' }
    $hasExamples = (Test-Path -LiteralPath $examples -PathType Container) -and @(Get-ChildItem -LiteralPath $examples -File).Count -gt 0
    if ($hasExamples) {
        Invoke-KurtShapeValidationPython -Executable $pythonPath -Arguments @('-B','tools\inventory_sources.py') -Name 'source-inventory' -TimeoutSeconds 120
        Invoke-KurtShapeValidationPython -Executable $pythonPath -Arguments @('-B','tools\validate_sources.py') -Name 'source-validation' -TimeoutSeconds 120
    } elseif ($Full) {
        throw ('Full validation requires a nonempty external examples folder: ' + $examples)
    } else {
        Write-Warning ('External examples are unavailable; the 3 real-part tests will be skipped: ' + $examples)
    }
    $reportFolder = Get-KurtShapeEvidenceDirectory 'checks'
    New-Item -ItemType Directory -Force -Path $reportFolder | Out-Null
    $nativeArgs = @('-B','tools\run_native_tests.py','--require-native','--report',(Join-Path $reportFolder 'native.json'),'--junit',(Join-Path $reportFolder 'junit.xml'))
    if ($Full) { $nativeArgs += '--require-external' }
    if ($KeepNativeTemp) { $nativeArgs += '--keep-temp' }
    Invoke-KurtShapeValidationPython -Executable $pythonPath -Arguments $nativeArgs -Name 'all-test-suites' -TimeoutSeconds 7500
    Write-Output ('Report: ' + (Join-Path $reportFolder 'native.json'))
    if ($Lint) {
        $ruff = Get-Command ruff -ErrorAction SilentlyContinue
        if ($ruff) {
            & $ruff.Source check .
            if ($LASTEXITCODE -ne 0) { throw 'Lint checks failed.' }
        } else { Write-Warning 'ruff is not on PATH; lint was not run.' }
    }
} finally { Pop-Location }
