param([switch]$WriteEvidence)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$studioProject = Split-Path -Parent $PSScriptRoot
$studioSession = Join-Path $studioProject 'runtime/u2-part-model-gui-validation'
Initialize-KurtShapeValidationEnvironment -Root $studioProject -Session $studioSession -WriteEvidence:$WriteEvidence
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$studioBin = Join-Path $studioProject 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin'
$studioArguments = @('-u', ('"' + (Join-Path $studioSession 'user-data/user.cfg') + '"'),
                     '-s', ('"' + (Join-Path $studioSession 'user-data/system.cfg') + '"'),
                     '--log-file', ('"' + (Join-Path $studioSession 'freecad.log') + '"'),
                     ('"' + (Join-Path $PSScriptRoot 'u2-part-model-gui-validation.FCMacro') + '"'))
$studioProcess = Start-Process -FilePath (Join-Path $studioBin 'freecad.exe') -ArgumentList $studioArguments -WorkingDirectory $studioProject -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $studioProcess -Executable (Join-Path $studioBin 'freecad.exe') -Arguments $studioArguments
Write-Output ('Hidden U2 GUI validation PID: ' + $studioProcess.Id)
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'u2-part-model') 'gui-result.json'))
