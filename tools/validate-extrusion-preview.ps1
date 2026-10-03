$ErrorActionPreference = 'Stop'
$previewProject = Split-Path -Parent $PSScriptRoot
$previewRuntime = Join-Path $previewProject 'runtime\ui-refinement-preview'
foreach ($folder in @('user-data','temporary','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $previewRuntime $folder) | Out-Null
}
$env:KURTSHAPE_ROOT = $previewProject
$env:KURTSHAPE_SESSION_DIR = $previewRuntime
$env:FREECAD_USER_HOME = Join-Path $previewRuntime 'user-data'
$env:TEMP = Join-Path $previewRuntime 'temporary'
$env:TMP = $env:TEMP
$env:APPDATA = Join-Path $previewRuntime 'appdata'
$env:LOCALAPPDATA = Join-Path $previewRuntime 'localappdata'
$env:PYTHONDONTWRITEBYTECODE = '1'
$previewBin = Join-Path $previewProject 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
& (Join-Path $previewBin 'python.exe') -B -m unittest discover -s (Join-Path $previewProject 'tests') -p test_extrusion_preview.py -v
if ($LASTEXITCODE -ne 0) { throw 'Native extrusion preview checks failed.' }
$previewArgs = @('-u', ('"' + (Join-Path $previewRuntime 'user-data\user.cfg') + '"'),
                 '-s', ('"' + (Join-Path $previewRuntime 'user-data\system.cfg') + '"'),
                 '--log-file', ('"' + (Join-Path $previewRuntime 'freecad.log') + '"'),
                 ('"' + (Join-Path $PSScriptRoot 'extrusion-preview-validation.FCMacro') + '"'))
$previewProcess = Start-Process -FilePath (Join-Path $previewBin 'freecad.exe') -ArgumentList $previewArgs -WorkingDirectory $previewProject -WindowStyle Hidden -PassThru
Write-Output ('Hidden preview validation PID: ' + $previewProcess.Id)
Write-Output ('Report: ' + (Join-Path $previewProject 'validation\ui-refinement-preview\gui-result.json'))
