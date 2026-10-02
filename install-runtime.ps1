$ErrorActionPreference = 'Stop'
$runtimePath = Join-Path $PSScriptRoot 'runtime'
$downloadPath = Join-Path $runtimePath 'downloads'
$temporaryPath = Join-Path $runtimePath 'temporary'
New-Item -ItemType Directory -Force -Path $downloadPath,$temporaryPath | Out-Null
$env:TEMP = $temporaryPath
$env:TMP = $temporaryPath
$archivePath = Join-Path $downloadPath 'FreeCAD_1.1.4-Windows-x86_64-py311.7z'
$expectedHash = '4828741fc91ee37fafcdb97a1abacb18b04ba451ac4372d9ff7a7349b36f4d6d'
if (-not (Test-Path -LiteralPath $archivePath)) {
    Invoke-WebRequest -Uri 'https://github.com/FreeCAD/FreeCAD/releases/download/1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311.7z' -OutFile $archivePath
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Official archive SHA256 mismatch.' }
$sevenZipPath = 'C:\Program Files\7-Zip\7z.exe'
if (-not (Test-Path -LiteralPath $sevenZipPath)) { throw '7-Zip is required; this script does not install a global dependency.' }
$extractPath = Join-Path $runtimePath 'freecad-1.1.4'
& $sevenZipPath x $archivePath ('-o'+$extractPath) -y -bso0 -bsp0
if ($LASTEXITCODE -ne 0) { throw 'Portable extraction failed.' }
Write-Output 'Pinned portable FreeCAD runtime ready under Codex. Run launch-kurtshape.ps1.'
