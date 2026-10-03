$ErrorActionPreference = 'Stop'
$carrierProject = Split-Path -Parent $PSScriptRoot
$carrierSession = Join-Path $carrierProject 'runtime/u2-part-model-spike-gui-validation'
foreach ($carrierFolder in @('user-data','temporary','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $carrierSession $carrierFolder) | Out-Null
}
$env:KURTSHAPE_ROOT = $carrierProject
$env:KURTSHAPE_SESSION_DIR = $carrierSession
$env:FREECAD_USER_HOME = Join-Path $carrierSession 'user-data'
$env:TEMP = Join-Path $carrierSession 'temporary'
$env:TMP = $env:TEMP
$env:APPDATA = Join-Path $carrierSession 'appdata'
$env:LOCALAPPDATA = Join-Path $carrierSession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE = '1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$carrierBin = Join-Path $carrierProject 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin'
$carrierArguments = @('-u', ('"' + (Join-Path $carrierSession 'user-data/user.cfg') + '"'),
                      '-s', ('"' + (Join-Path $carrierSession 'user-data/system.cfg') + '"'),
                      '--log-file', ('"' + (Join-Path $carrierSession 'freecad.log') + '"'),
                      ('"' + (Join-Path $PSScriptRoot 'part-model-spike-gui-validation.FCMacro') + '"'))
$carrierProcess = Start-Process -FilePath (Join-Path $carrierBin 'freecad.exe') -ArgumentList $carrierArguments -WorkingDirectory $carrierProject -WindowStyle Hidden -PassThru
Write-Output ('Hidden carrier validation PID: ' + $carrierProcess.Id)
Write-Output ('Report: ' + (Join-Path $carrierProject 'validation/u2-part-model-spike/gui-carrier-result.json'))
