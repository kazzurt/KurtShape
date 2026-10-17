param([string]$RuntimeRoot = (Join-Path $PSScriptRoot 'runtime'), [switch]$Repair)
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or -not [Environment]::Is64BitOperatingSystem) {
    throw 'This installer supports 64-bit Windows only.'
}
$runtimePath = [IO.Path]::GetFullPath($RuntimeRoot)
$extractPath = Join-Path $runtimePath 'freecad-1.1.4'
$engineBin = Join-Path $extractPath 'FreeCAD_1.1.4-Windows-x86_64-py311\bin'
$missing = @('python.exe','freecad.exe','freecadcmd.exe','FreeCAD.pyd','opengl32sw.dll') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $engineBin $_) -PathType Leaf) }
if (-not $Repair -and -not $missing) {
    Write-Output ('Portable runtime already present: ' + $engineBin)
    return
}
$sevenZipPath = $env:KURTSHAPE_7Z
if (-not $sevenZipPath) { $sevenZipPath = (Get-Command 7z.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1).Source }
if (-not $sevenZipPath) { $sevenZipPath = 'C:\Program Files\7-Zip\7z.exe' }
if (-not (Test-Path -LiteralPath $sevenZipPath -PathType Leaf)) {
    throw 'Install 7-Zip first (winget install --id 7zip.7zip --exact), or set KURTSHAPE_7Z to the full path of 7z.exe. Then rerun setup.ps1.'
}
$previousEnvironment = @{}
foreach ($name in @('TEMP','TMP')) {
    $previousEnvironment[$name] = @{present=(Test-Path -LiteralPath ('Env:' + $name));value=[Environment]::GetEnvironmentVariable($name, 'Process')}
}
$previousProgressPreference = $ProgressPreference
try {
$downloadPath = Join-Path $runtimePath 'downloads'
$temporaryPath = Join-Path $runtimePath 'temporary'
New-Item -ItemType Directory -Force -Path $downloadPath,$temporaryPath | Out-Null
$env:TEMP = $temporaryPath
$env:TMP = $temporaryPath
$archivePath = Join-Path $downloadPath 'FreeCAD_1.1.4-Windows-x86_64-py311.7z'
$expectedHash = '4828741fc91ee37fafcdb97a1abacb18b04ba451ac4372d9ff7a7349b36f4d6d'
if (-not (Test-Path -LiteralPath $archivePath)) {
    $ProgressPreference = 'SilentlyContinue'
    # An interrupted download must never be mistaken for a complete cached archive.
    $partialPath = $archivePath + '.partial'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/FreeCAD/FreeCAD/releases/download/1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311.7z' -OutFile $partialPath
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $partialPath).Hash.ToLowerInvariant() -ne $expectedHash) { throw ('Official archive SHA256 mismatch: ' + $partialPath) }
    Move-Item -LiteralPath $partialPath -Destination $archivePath
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant() -ne $expectedHash) { throw ('Cached archive SHA256 mismatch. Remove this archive and retry: ' + $archivePath) }
& $sevenZipPath x $archivePath ('-o'+$extractPath) -y -bso0 -bsp0
if ($LASTEXITCODE -ne 0) { throw 'Portable extraction failed.' }
Write-Output ('Pinned portable FreeCAD runtime ready: ' + $extractPath)
} finally {
    foreach ($name in @('TEMP','TMP')) {
        if ($previousEnvironment[$name].present) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name].value, 'Process') }
        else { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
    }
    $ProgressPreference = $previousProgressPreference
}
