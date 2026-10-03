$ErrorActionPreference = 'Stop'
$messagesProject = Split-Path -Parent $PSScriptRoot
$messagesSession = Join-Path $messagesProject 'runtime\messages-behavior-validation'
foreach ($folder in @('user-data', 'temporary', 'appdata', 'localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $messagesSession $folder) | Out-Null
}
$env:KURTSHAPE_ROOT = $messagesProject
$env:KURTSHAPE_SESSION_DIR = $messagesSession
$env:FREECAD_USER_HOME = Join-Path $messagesSession 'user-data'
$env:TEMP = Join-Path $messagesSession 'temporary'
$env:TMP = $env:TEMP
$env:APPDATA = Join-Path $messagesSession 'appdata'
$env:LOCALAPPDATA = Join-Path $messagesSession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE = '1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$messagesBin = Join-Path $messagesProject 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
$messagesArgs = @('-u', ('"' + (Join-Path $messagesSession 'user-data\user.cfg') + '"'),
                  '-s', ('"' + (Join-Path $messagesSession 'user-data\system.cfg') + '"'),
                  '--log-file', ('"' + (Join-Path $messagesSession 'freecad.log') + '"'),
                  ('"' + (Join-Path $PSScriptRoot 'messages-validation.FCMacro') + '"'))
$messagesProcess = Start-Process -FilePath (Join-Path $messagesBin 'freecad.exe') -ArgumentList $messagesArgs -WorkingDirectory $messagesProject -WindowStyle Hidden -PassThru
Write-Output ('Hidden Messages validation PID: ' + $messagesProcess.Id)
Write-Output ('Report: ' + (Join-Path $messagesProject 'validation\messages-behavior\gui-result.json'))
