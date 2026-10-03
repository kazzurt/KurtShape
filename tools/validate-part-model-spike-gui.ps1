param([switch]$WriteEvidence)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$carrierProject = Split-Path -Parent $PSScriptRoot
$carrierSession = Join-Path $carrierProject 'runtime/u2-part-model-spike-gui-validation'
Initialize-KurtShapeValidationEnvironment -Root $carrierProject -Session $carrierSession -WriteEvidence:$WriteEvidence
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$carrierBin = Join-Path $carrierProject 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin'
$carrierArguments = @('-u', ('"' + (Join-Path $carrierSession 'user-data/user.cfg') + '"'),
                      '-s', ('"' + (Join-Path $carrierSession 'user-data/system.cfg') + '"'),
                      '--log-file', ('"' + (Join-Path $carrierSession 'freecad.log') + '"'),
                      ('"' + (Join-Path $PSScriptRoot 'part-model-spike-gui-validation.FCMacro') + '"'))
$carrierProcess = Start-Process -FilePath (Join-Path $carrierBin 'freecad.exe') -ArgumentList $carrierArguments -WorkingDirectory $carrierProject -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $carrierProcess -Executable (Join-Path $carrierBin 'freecad.exe') -Arguments $carrierArguments
Write-Output ('Hidden carrier validation PID: ' + $carrierProcess.Id)
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'u2-part-model-spike') 'gui-carrier-result.json'))
