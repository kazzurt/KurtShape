param([ValidateSet('copy','lifecycle','recovery','interaction','startup','baseline','step')][string]$Scenario='copy')
$ErrorActionPreference='Stop'
$reviewRoot=$PSScriptRoot
$reviewSession=Join-Path $reviewRoot "runtime\review-$Scenario-validation"
foreach ($folder in @('temporary','user-data','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $reviewSession $folder) | Out-Null
}
$env:KURTSHAPE_ROOT=$reviewRoot
$env:KURTSHAPE_SESSION_DIR=$reviewSession
$env:FREECAD_USER_HOME=Join-Path $reviewSession 'user-data'
$env:TEMP=Join-Path $reviewSession 'temporary'
$env:TMP=$env:TEMP
$env:APPDATA=Join-Path $reviewSession 'appdata'
$env:LOCALAPPDATA=Join-Path $reviewSession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE='1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
if ($Scenario -eq 'baseline') { $env:KURTSHAPE_STARTUP_BASELINE='1'; $env:KURTSHAPE_NO_DEMO='1' }
else { Remove-Item Env:KURTSHAPE_STARTUP_BASELINE -ErrorAction SilentlyContinue }
$reviewMacro=@{copy='general-actions-validation.FCMacro';lifecycle='sketch-lifecycle-validation.FCMacro';recovery='review-recovery-crash.FCMacro';interaction='gui-review-validation.FCMacro';startup='gui-startup-diagnostics.FCMacro';baseline='gui-startup-diagnostics.FCMacro';step='step-import-gui-validation.FCMacro'}[$Scenario]
$reviewExe=Join-Path $reviewRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
$reviewArgs=@('-u',('"'+(Join-Path $reviewSession 'user-data\user.cfg')+'"'),'-s',('"'+(Join-Path $reviewSession 'user-data\system.cfg')+'"'),('--log-file'),('"'+(Join-Path $reviewSession 'freecad.log')+'"'),('"'+(Join-Path $reviewRoot "tools\$reviewMacro")+'"'))
Start-Process -FilePath $reviewExe -ArgumentList $reviewArgs -WorkingDirectory $reviewRoot -WindowStyle Hidden -PassThru | Select-Object Id
