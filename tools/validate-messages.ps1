param([switch]$WriteEvidence)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$messagesProject = Split-Path -Parent $PSScriptRoot
$messagesSession = Join-Path $messagesProject 'runtime\messages-behavior-validation'
Initialize-KurtShapeValidationEnvironment -Root $messagesProject -Session $messagesSession -WriteEvidence:$WriteEvidence
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$messagesBin = Join-Path $messagesProject 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
$messagesArgs = @('-u', ('"' + (Join-Path $messagesSession 'user-data\user.cfg') + '"'),
                  '-s', ('"' + (Join-Path $messagesSession 'user-data\system.cfg') + '"'),
                  '--log-file', ('"' + (Join-Path $messagesSession 'freecad.log') + '"'),
                  ('"' + (Join-Path $PSScriptRoot 'messages-validation.FCMacro') + '"'))
$messagesProcess = Start-Process -FilePath (Join-Path $messagesBin 'freecad.exe') -ArgumentList $messagesArgs -WorkingDirectory $messagesProject -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $messagesProcess -Executable (Join-Path $messagesBin 'freecad.exe') -Arguments $messagesArgs
Write-Output ('Hidden Messages validation PID: ' + $messagesProcess.Id)
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'messages-behavior') 'gui-result.json'))
