# Shared environment and process records for isolated validation scripts.
function Initialize-KurtShapeValidationEnvironment {
    param([string]$Root, [string]$Session, [switch]$WriteEvidence)
    $Root = [IO.Path]::GetFullPath($Root)
    $Session = [IO.Path]::GetFullPath($Session)
    $runtimeRoot = Join-Path $Root 'runtime'
    if ($Session.TrimEnd('\','/') -eq $runtimeRoot.TrimEnd('\','/')) {
        throw 'Validation must use a private session, never the live runtime folder.'
    }
    if (-not $Session.StartsWith($runtimeRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Validation scratch must be under this checkout runtime folder.'
    }
    $relative = $Session.Substring($Root.Length + 1)
    $createdRoot = Join-Path $Root (($relative -split '[\\/]')[0..1] -join [IO.Path]::DirectorySeparatorChar)
    $wasPresent = Test-Path -LiteralPath $createdRoot
    foreach ($folder in @('user-data','temporary','appdata','localappdata','evidence','test-tmp')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Session $folder) | Out-Null
    }
    $records = Join-Path $runtimeRoot 'longrun'
    New-Item -ItemType Directory -Force -Path $records | Out-Null
    if (-not $wasPresent) {
        Add-Content -LiteralPath (Join-Path $records 'created.txt') -Value $createdRoot.Substring($Root.Length + 1)
    }
    $env:KURTSHAPE_ROOT = $Root
    $env:KURTSHAPE_SESSION_DIR = $Session
    $env:KURTSHAPE_EVIDENCE_DIR = Join-Path $Session 'evidence'
    if ($WriteEvidence) { $env:KURTSHAPE_WRITE_EVIDENCE = '1' }
    else { Remove-Item Env:KURTSHAPE_WRITE_EVIDENCE -ErrorAction SilentlyContinue }
    $env:FREECAD_USER_HOME = Join-Path $Session 'user-data'
    $env:TEMP = Join-Path $Session 'temporary'
    $env:TMP = $env:TEMP
    $env:APPDATA = Join-Path $Session 'appdata'
    $env:LOCALAPPDATA = Join-Path $Session 'localappdata'
    $env:KURTSHAPE_TEST_TMP = Join-Path $Session 'test-tmp'
    $env:PYTHONDONTWRITEBYTECODE = '1'
}

function Get-KurtShapeEvidenceDirectory {
    param([string]$Name = '')
    $base = if ($env:KURTSHAPE_WRITE_EVIDENCE -eq '1') { Join-Path $env:KURTSHAPE_ROOT 'validation' }
            else { $env:KURTSHAPE_EVIDENCE_DIR }
    if ($Name) { Join-Path $base $Name } else { $base }
}

function Register-KurtShapeValidationProcess {
    param([System.Diagnostics.Process]$Process, [string]$Executable, [string[]]$Arguments)
    $recordPath = Join-Path $env:KURTSHAPE_ROOT 'runtime\longrun\pids.txt'
    Add-Content -LiteralPath $recordPath -Value (
        '{0} PID={1} COMMAND="{2}" {3}' -f [DateTimeOffset]::UtcNow.ToString('o'), $Process.Id, $Executable, ($Arguments -join ' '))
}

function Invoke-KurtShapeValidationPython {
    param([string]$Executable, [string[]]$Arguments, [string]$Name)
    $processFolder = Join-Path $env:KURTSHAPE_SESSION_DIR 'process-logs'
    New-Item -ItemType Directory -Force -Path $processFolder | Out-Null
    $stamp = [Guid]::NewGuid().ToString('N')
    $stdout = Join-Path $processFolder ($Name + '-' + $stamp + '-stdout.txt')
    $stderr = Join-Path $processFolder ($Name + '-' + $stamp + '-stderr.txt')
    $quoted = @($Arguments | ForEach-Object { '"' + $_ + '"' })
    $process = Start-Process -FilePath $Executable -ArgumentList $quoted -WorkingDirectory $env:KURTSHAPE_ROOT -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    Register-KurtShapeValidationProcess -Process $process -Executable $Executable -Arguments $quoted
    $process.WaitForExit()
    $process.Refresh()
    if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout | Write-Host }
    if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr | Write-Host }
    if ($process.ExitCode -ne 0) { throw ($Name + ' failed with exit code ' + $process.ExitCode + '. Logs: ' + $processFolder) }
}
