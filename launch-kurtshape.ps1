param([switch]$Validation)
$ErrorActionPreference = 'Stop'
$kurtshapeRoot = $PSScriptRoot
$runtimePath = Join-Path $kurtshapeRoot 'runtime'
if ($Validation) { $runtimePath = Join-Path $runtimePath 'interface-validation' }
foreach ($folder in @('temporary','user-data','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimePath $folder) | Out-Null
}
$env:KURTSHAPE_ROOT = $kurtshapeRoot
$env:KURTSHAPE_SESSION_DIR = $runtimePath
if ($Validation) { $env:KURTSHAPE_NO_DEMO = '1' } else { Remove-Item Env:KURTSHAPE_NO_DEMO -ErrorAction SilentlyContinue }
$env:FREECAD_USER_HOME = Join-Path $runtimePath 'user-data'
$env:TEMP = Join-Path $runtimePath 'temporary'
$env:TMP = $env:TEMP
$env:APPDATA = Join-Path $runtimePath 'appdata'
$env:LOCALAPPDATA = Join-Path $runtimePath 'localappdata'
$env:PYTHONDONTWRITEBYTECODE = '1'
$exePath = Join-Path $kurtshapeRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
if (-not (Test-Path -LiteralPath $exePath)) { throw 'Run install-runtime.ps1 first.' }
$macroPath = Join-Path $kurtshapeRoot $(if ($Validation) {'tools\gui-validation.FCMacro'} else {'KurtShape.FCMacro'})
$userConfigPath = Join-Path $runtimePath 'user-data\user.cfg'
$systemConfigPath = Join-Path $runtimePath 'user-data\system.cfg'
$launchArguments = @('-u', ('"'+$userConfigPath+'"'), '-s', ('"'+$systemConfigPath+'"'), '--log-file', ('"'+(Join-Path $runtimePath 'freecad-launch.log')+'"'))
$launchArguments += ('"'+$macroPath+'"')
$launchWindowStyle = if ($Validation) { 'Hidden' } else { 'Normal' }
Start-Process -FilePath $exePath -ArgumentList $launchArguments -WorkingDirectory $kurtshapeRoot -WindowStyle $launchWindowStyle -PassThru | Select-Object Id
