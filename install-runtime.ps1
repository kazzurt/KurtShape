param([string]$RuntimeRoot = (Join-Path $PSScriptRoot 'runtime'))
$ErrorActionPreference = 'Stop'
$previousEnvironment = @{}
foreach ($name in @('TEMP','TMP')) {
    $previousEnvironment[$name] = @{present=(Test-Path -LiteralPath ('Env:' + $name));value=[Environment]::GetEnvironmentVariable($name, 'Process')}
}
$previousProgressPreference = $ProgressPreference
try {
$runtimePath = [IO.Path]::GetFullPath($RuntimeRoot)
$downloadPath = Join-Path $runtimePath 'downloads'
$temporaryPath = Join-Path $runtimePath 'temporary'
New-Item -ItemType Directory -Force -Path $downloadPath,$temporaryPath | Out-Null
$env:TEMP = $temporaryPath
$env:TMP = $temporaryPath
$archivePath = Join-Path $downloadPath 'FreeCAD_1.1.4-Windows-x86_64-py311.7z'
$expectedHash = '4828741fc91ee37fafcdb97a1abacb18b04ba451ac4372d9ff7a7349b36f4d6d'
if (-not (Test-Path -LiteralPath $archivePath)) {
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri 'https://github.com/FreeCAD/FreeCAD/releases/download/1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311.7z' -OutFile $archivePath
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Official archive SHA256 mismatch.' }
$sevenZipPath = $env:KURTSHAPE_7Z
if (-not $sevenZipPath) { $sevenZipPath = (Get-Command 7z.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
if (-not $sevenZipPath) { $sevenZipPath = 'C:\Program Files\7-Zip\7z.exe' }
if (-not (Test-Path -LiteralPath $sevenZipPath)) { throw '7-Zip is required; this script does not install a global dependency.' }
$extractPath = Join-Path $runtimePath 'freecad-1.1.4'
& $sevenZipPath x $archivePath ('-o'+$extractPath) -y -bso0 -bsp0
if ($LASTEXITCODE -ne 0) { throw 'Portable extraction failed.' }
Write-Output 'Pinned portable FreeCAD runtime ready under Codex. Run launch-kurtshape.ps1.'
} finally {
    foreach ($name in @('TEMP','TMP')) {
        if ($previousEnvironment[$name].present) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name].value, 'Process') }
        else { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
    }
    $ProgressPreference = $previousProgressPreference
}
