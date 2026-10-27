param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$RefreshInstance
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$inputPath = (Resolve-Path -LiteralPath $FilePath).Path
$out = [IO.Path]::GetFullPath($OutputDirectory)
if ($out -eq [IO.Path]::GetDirectoryName($inputPath)) { throw 'Use a separate regression directory to preserve the input.' }
New-Item -ItemType Directory -Force -Path $out | Out-Null
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$bin = Join-Path $repo 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
$initialHash = (Get-FileHash -LiteralPath $inputPath -Algorithm SHA256).Hash
foreach ($mode in @('headless','gui')) {
    $sessionRoot = Join-Path $repo ('runtime\reopen-' + $mode + '-' + $PID)
    Initialize-KurtShapeValidationEnvironment -Root $repo -Session $sessionRoot
    $env:KURTSHAPE_ROOT = $repo
    $env:QT_QPA_PLATFORM = 'offscreen'
    $config = @{input=$inputPath;output=$out;refresh_instance=$RefreshInstance}
    if ($mode -eq 'gui') { $config.input = (Get-Content -LiteralPath (Join-Path $out 'headless-report.json') -Raw | ConvertFrom-Json).output }
    $env:KURTSHAPE_REOPEN_CONFIG = Join-Path $sessionRoot 'reopen-config.json'
    [IO.File]::WriteAllText($env:KURTSHAPE_REOPEN_CONFIG,($config | ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $env:KURTSHAPE_SESSION_DIR 'settings.json'),(@{workspace_layout='portable';project_roots=@($out)}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    if ($mode -eq 'headless') {
        $exe = Join-Path $bin 'pythonw.exe'
        $arguments = @('-B',('"'+(Join-Path $PSScriptRoot 'validate_fixture_reopen.py')+'"'))
    } else {
        $exe = Join-Path $bin 'freecad.exe'
        $arguments = @('-u',('"'+$env:FREECAD_USER_HOME+'\user.cfg"'),'-s',('"'+$env:FREECAD_USER_HOME+'\system.cfg"'),('"'+(Join-Path $PSScriptRoot 'assembly-reopen-validation.FCMacro')+'"'))
    }
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $out ($mode+'-stdout.txt')) -RedirectStandardError (Join-Path $out ($mode+'-stderr.txt'))
    if (-not $process.WaitForExit(180000)) { $process.Kill(); $process.WaitForExit(); throw "$mode regression timed out; only its owned child was stopped" }
    $report = Get-Content -LiteralPath (Join-Path $out ($mode+'-report.json')) -Raw | ConvertFrom-Json
    if (-not $report.passed) { throw ($mode + ' regression failed: ' + $report.error) }
    Write-Output ($mode + ': PASS; 3 reopen cycles, embedded-change detection; ' + $report.seconds + ' s')
}
if ((Get-FileHash -LiteralPath $FilePath -Algorithm SHA256).Hash -ne $initialHash) { throw 'Original file changed during regression' }
Write-Output ('Original preserved; reports: ' + $out)
