param([ValidateSet('interface','preview','modeling')][string]$Scenario='interface')
$ErrorActionPreference='Stop'
$refinementRoot=$PSScriptRoot
$refinementBin=Join-Path $refinementRoot 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin'
if ($Scenario -eq 'modeling') {
    & (Join-Path $refinementBin 'python.exe') -B (Join-Path $refinementRoot 'tools/validate_modeling_workflows.py')
    exit $LASTEXITCODE
}
$refinementSession=Join-Path $refinementRoot "runtime/ui-refinement-$Scenario-validation"
foreach ($folder in @('temporary','user-data','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $refinementSession $folder) | Out-Null
}
$env:KURTSHAPE_ROOT=$refinementRoot
$env:KURTSHAPE_SESSION_DIR=$refinementSession
$env:FREECAD_USER_HOME=Join-Path $refinementSession 'user-data'
$env:TEMP=Join-Path $refinementSession 'temporary'
$env:TMP=$env:TEMP
$env:APPDATA=Join-Path $refinementSession 'appdata'
$env:LOCALAPPDATA=Join-Path $refinementSession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE='1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$refinementMacro=@{interface='ui-refinement-validation.FCMacro';preview='extrusion-preview-validation.FCMacro'}[$Scenario]
$refinementArguments=@('-u',('"'+(Join-Path $refinementSession 'user-data/user.cfg')+'"'),'-s',('"'+(Join-Path $refinementSession 'user-data/system.cfg')+'"'),'--log-file',('"'+(Join-Path $refinementSession 'freecad.log')+'"'),('"'+(Join-Path $refinementRoot "tools/$refinementMacro")+'"'))
Start-Process -FilePath (Join-Path $refinementBin 'freecad.exe') -ArgumentList $refinementArguments -WorkingDirectory $refinementRoot -WindowStyle Hidden -PassThru | Select-Object Id
