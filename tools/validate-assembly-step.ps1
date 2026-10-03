param([switch]$WriteEvidence)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$assemblyProject = Split-Path -Parent $PSScriptRoot
$assemblySession = Join-Path $assemblyProject ('runtime\assembly-step-gui-validation-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss'))
Initialize-KurtShapeValidationEnvironment -Root $assemblyProject -Session $assemblySession -WriteEvidence:$WriteEvidence
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:KURTSHAPE_DEMO -ErrorAction SilentlyContinue
$assemblyBin = Join-Path $assemblyProject 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
$assemblyArgs = @('-u', ('"' + (Join-Path $assemblySession 'user-data\user.cfg') + '"'),
                  '-s', ('"' + (Join-Path $assemblySession 'user-data\system.cfg') + '"'),
                  '--log-file', ('"' + (Join-Path $assemblySession 'freecad.log') + '"'),
                  ('"' + (Join-Path $PSScriptRoot 'assembly-step-validation.FCMacro') + '"'))
$assemblyProcess = Start-Process -FilePath (Join-Path $assemblyBin 'freecad.exe') -ArgumentList $assemblyArgs -WorkingDirectory $assemblyProject -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $assemblyProcess -Executable (Join-Path $assemblyBin 'freecad.exe') -Arguments $assemblyArgs
Write-Output ('Hidden Assembly STEP validation PID: ' + $assemblyProcess.Id)
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'assembly-step-import') 'gui-result.json'))
