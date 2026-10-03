$ErrorActionPreference = 'Stop'
$assemblyProject = Split-Path -Parent $PSScriptRoot
$assemblySession = Join-Path $assemblyProject ('runtime\assembly-step-gui-validation-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss'))
foreach ($folder in @('user-data','temporary','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $assemblySession $folder) | Out-Null
}
$env:KURTSHAPE_ROOT = $assemblyProject
$env:KURTSHAPE_SESSION_DIR = $assemblySession
$env:FREECAD_USER_HOME = Join-Path $assemblySession 'user-data'
$env:TEMP = Join-Path $assemblySession 'temporary'
$env:TMP = $env:TEMP
$env:APPDATA = Join-Path $assemblySession 'appdata'
$env:LOCALAPPDATA = Join-Path $assemblySession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE = '1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:KURTSHAPE_DEMO -ErrorAction SilentlyContinue
$assemblyBin = Join-Path $assemblyProject 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
$assemblyArgs = @('-u', ('"' + (Join-Path $assemblySession 'user-data\user.cfg') + '"'),
                  '-s', ('"' + (Join-Path $assemblySession 'user-data\system.cfg') + '"'),
                  '--log-file', ('"' + (Join-Path $assemblySession 'freecad.log') + '"'),
                  ('"' + (Join-Path $PSScriptRoot 'assembly-step-validation.FCMacro') + '"'))
$assemblyProcess = Start-Process -FilePath (Join-Path $assemblyBin 'freecad.exe') -ArgumentList $assemblyArgs -WorkingDirectory $assemblyProject -WindowStyle Hidden -PassThru
Write-Output ('Hidden Assembly STEP validation PID: ' + $assemblyProcess.Id)
Write-Output ('Report: ' + (Join-Path $assemblyProject 'validation\assembly-step-import\gui-result.json'))
