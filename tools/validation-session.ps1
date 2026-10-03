# Shared environment and process records for isolated validation scripts.
function Initialize-KurtShapeValidationEnvironment {
    param([string]$Root, [string]$Session, [switch]$WriteEvidence, [string]$SessionBase)
    $Root = [IO.Path]::GetFullPath($Root)
    $Session = [IO.Path]::GetFullPath($Session)
    $runtimeRoot = Join-Path $Root 'runtime'
    if (-not $SessionBase) { $SessionBase = $runtimeRoot }
    $SessionBase = [IO.Path]::GetFullPath($SessionBase).TrimEnd('\','/')
    if ($Session.TrimEnd('\','/') -eq $SessionBase -or $Session.TrimEnd('\','/') -eq $runtimeRoot.TrimEnd('\','/')) {
        throw 'Validation must use a private session, never the live runtime folder.'
    }
    if (-not $Session.StartsWith($SessionBase + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Validation scratch must be under the selected session base.'
    }
    $relative = $Session.Substring($SessionBase.Length + 1)
    $createdRoot = Join-Path $SessionBase (($relative -split '[\\/]')[0])
    $wasPresent = Test-Path -LiteralPath $createdRoot
    $privateFolders = @('user-data','temporary','appdata','localappdata','evidence','test-tmp')
    foreach ($folder in $privateFolders) {
        $target = Join-Path $Session $folder
        try { $entry = Get-Item -LiteralPath $target -Force -ErrorAction Stop }
        catch {
            if ($_.CategoryInfo.Category -ne [Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
            $entry = $null
        }
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw ('Validation private folder cannot be a junction or symbolic link: ' + $target)
        }
    }
    foreach ($folder in $privateFolders) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Session $folder) | Out-Null
    }
    $records = Join-Path $runtimeRoot 'longrun'
    New-Item -ItemType Directory -Force -Path $records | Out-Null
    if (-not $wasPresent) {
        $label = if ($createdRoot.StartsWith($Root.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { $createdRoot.Substring($Root.Length + 1) } else { $createdRoot }
        Add-Content -LiteralPath (Join-Path $records 'created.txt') -Value $label
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
    param([string]$Executable, [string[]]$Arguments, [string]$Name,
        [switch]$PassThru, [ValidateRange(0,7500)][int]$TimeoutSeconds = 0)
    $processFolder = Join-Path $env:KURTSHAPE_SESSION_DIR 'process-logs'
    New-Item -ItemType Directory -Force -Path $processFolder | Out-Null
    $stamp = [Guid]::NewGuid().ToString('N')
    $stdout = Join-Path $processFolder ($Name + '-' + $stamp + '-stdout.txt')
    $stderr = Join-Path $processFolder ($Name + '-' + $stamp + '-stderr.txt')
    $quoted = @($Arguments | ForEach-Object { '"' + $_ + '"' })
    $process = Start-Process -FilePath $Executable -ArgumentList $quoted -WorkingDirectory $env:KURTSHAPE_ROOT -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $ownershipTransferred = $false
    try {
        Register-KurtShapeValidationProcess -Process $process -Executable $Executable -Arguments $quoted
        if ($TimeoutSeconds -gt 0) {
            if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
                if (-not $process.HasExited) {
                    try { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
                    catch { if (-not $process.HasExited) { throw } }
                }
                if (-not $process.WaitForExit(5000)) { throw ($Name + ' owned process did not exit after timeout: ' + $process.Id) }
                throw ($Name + ' timed out after ' + $TimeoutSeconds + ' seconds. Logs: ' + $processFolder)
            }
        } else { $process.WaitForExit() }
        $process.Refresh()
        if (Test-Path -LiteralPath $stdout) { Get-Content -LiteralPath $stdout | Write-Host }
        if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr | Write-Host }
        if ($process.ExitCode -ne 0) { throw ($Name + ' failed with exit code ' + $process.ExitCode + '. Logs: ' + $processFolder) }
        if ($PassThru) { $ownershipTransferred = $true; $process }
    } catch {
        $failure = $_
        if (-not $process.HasExited) {
            try {
                Stop-Process -Id $process.Id -Force -ErrorAction Stop
                if (-not $process.WaitForExit(5000)) { throw ('Owned process remains running: ' + $process.Id) }
            } catch { Write-Warning ($Name + ' cleanup failed for owned PID ' + $process.Id + ': ' + $_.Exception.Message) }
        }
        throw $failure
    } finally {
        if (-not $ownershipTransferred) { $process.Dispose() }
    }
}
