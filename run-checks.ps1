$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $env:FREECAD_USER_HOME = Join-Path $PSScriptRoot 'runtime\test-user-data'
    $env:TEMP = Join-Path $PSScriptRoot 'runtime\temporary'
    $env:TMP = $env:TEMP
    $env:PYTHONDONTWRITEBYTECODE = '1'
    New-Item -ItemType Directory -Force -Path $env:FREECAD_USER_HOME,$env:TEMP | Out-Null
    $pythonPath = Join-Path $PSScriptRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
    & $pythonPath -B tools\inventory_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Source inventory failed.' }
    & $pythonPath -B tools\validate_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Original STEP validation failed.' }
    & $pythonPath -B tools\validate_offline.py
    if ($LASTEXITCODE -ne 0) { throw 'Offline core checks failed.' }
    & $pythonPath -B -m unittest discover -s tests -p test_bridge.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Loopback timeout checks failed.' }
    & $pythonPath -B -m unittest discover -s tests -p test_shortcuts.py -v
    if ($LASTEXITCODE -ne 0) { throw 'Keyboard routing checks failed.' }
} finally { Pop-Location }
