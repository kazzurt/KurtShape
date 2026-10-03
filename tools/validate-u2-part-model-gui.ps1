$ErrorActionPreference = 'Stop'
$studioProject = Split-Path -Parent $PSScriptRoot
$studioSession = Join-Path $studioProject 'runtime/u2-part-model-gui-validation'
foreach ($studioFolder in @('user-data','temporary','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $studioSession $studioFolder) | Out-Null
}
$env:KURTSHAPE_ROOT = $studioProject
$env:KURTSHAPE_SESSION_DIR = $studioSession
$env:FREECAD_USER_HOME = Join-Path $studioSession 'user-data'
$env:TEMP = Join-Path $studioSession 'temporary'
$env:TMP = $env:TEMP
$env:APPDATA = Join-Path $studioSession 'appdata'
$env:LOCALAPPDATA = Join-Path $studioSession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE = '1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$studioBin = Join-Path $studioProject 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin'
$studioArguments = @('-u', ('"' + (Join-Path $studioSession 'user-data/user.cfg') + '"'),
                     '-s', ('"' + (Join-Path $studioSession 'user-data/system.cfg') + '"'),
                     '--log-file', ('"' + (Join-Path $studioSession 'freecad.log') + '"'),
                     ('"' + (Join-Path $PSScriptRoot 'u2-part-model-gui-validation.FCMacro') + '"'))
$studioProcess = Start-Process -FilePath (Join-Path $studioBin 'freecad.exe') -ArgumentList $studioArguments -WorkingDirectory $studioProject -WindowStyle Hidden -PassThru
Write-Output ('Hidden U2 GUI validation PID: ' + $studioProcess.Id)
Write-Output ('Report: ' + (Join-Path $studioProject 'validation/u2-part-model/gui-result.json'))
