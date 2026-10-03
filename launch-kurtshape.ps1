param([switch]$Validation, [switch]$WriteEvidence)
$ErrorActionPreference = 'Stop'
$kurtshapeRoot = $PSScriptRoot
$runtimePath = Join-Path $kurtshapeRoot 'runtime'
if ($Validation) { $runtimePath = Join-Path $runtimePath 'interface-validation' }
if ($Validation) {
    . (Join-Path $PSScriptRoot 'tools\validation-session.ps1')
    Initialize-KurtShapeValidationEnvironment -Root $kurtshapeRoot -Session $runtimePath -WriteEvidence:$WriteEvidence
} else {
    foreach ($folder in @('temporary','user-data','appdata','localappdata')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $runtimePath $folder) | Out-Null
    }
    $env:KURTSHAPE_ROOT = $kurtshapeRoot
    $env:KURTSHAPE_SESSION_DIR = $runtimePath
    Remove-Item Env:KURTSHAPE_NO_DEMO -ErrorAction SilentlyContinue
    $env:FREECAD_USER_HOME = Join-Path $runtimePath 'user-data'
    $env:TEMP = Join-Path $runtimePath 'temporary'
    $env:TMP = $env:TEMP
    $env:APPDATA = Join-Path $runtimePath 'appdata'
    $env:LOCALAPPDATA = Join-Path $runtimePath 'localappdata'
    $env:PYTHONDONTWRITEBYTECODE = '1'
}
if ($Validation) { $env:KURTSHAPE_NO_DEMO = '1' }
$exePath = Join-Path $kurtshapeRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
if (-not (Test-Path -LiteralPath $exePath)) { throw 'Run install-runtime.ps1 first.' }
$macroPath = Join-Path $kurtshapeRoot $(if ($Validation) {'tools\gui-validation.FCMacro'} else {'KurtShape.FCMacro'})
$userConfigPath = Join-Path $runtimePath 'user-data\user.cfg'
$systemConfigPath = Join-Path $runtimePath 'user-data\system.cfg'
$launchArguments = @('-u', ('"'+$userConfigPath+'"'), '-s', ('"'+$systemConfigPath+'"'), '--log-file', ('"'+(Join-Path $runtimePath 'freecad-launch.log')+'"'))
$launchArguments += ('"'+$macroPath+'"')
$launchWindowStyle = if ($Validation) { 'Hidden' } else { 'Normal' }
$launchProcess = Start-Process -FilePath $exePath -ArgumentList $launchArguments -WorkingDirectory $kurtshapeRoot -WindowStyle $launchWindowStyle -PassThru
if ($Validation) {
    Register-KurtShapeValidationProcess -Process $launchProcess -Executable $exePath -Arguments $launchArguments
    Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'interface-pass') 'gui-test-result.json'))
}
$launchProcess | Select-Object Id
