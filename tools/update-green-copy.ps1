param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Commit,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$mainRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$codexRoot = Split-Path -Parent $mainRoot
$greenRoot = Join-Path $codexRoot 'kurtshape-green'
$launcherPath = Join-Path $codexRoot 'KurtShape-green.cmd'
$runtimeRoot = Join-Path $mainRoot 'runtime'
$metadata = [ordered]@{
    status = 'refused'
    changed = $false
    reason = $null
    requested_commit = $Commit
    resolved_commit = $null
    previous_commit = $null
    previous_tag = $null
    green_commit = $null
    green_tag = $null
    main_path = $mainRoot
    green_path = $greenRoot
    launcher_path = $launcherPath
    runtime_root = $runtimeRoot
    active_pids = @()
    git_output = @()
    git_diagnostics = @()
}

function Get-KurtShapeGreenGuard {
    param([object[]]$Processes = @(), [string[]]$TrackedChanges = @())
    $active = @()
    $unreadable = @()
    foreach ($process in $Processes) {
        if ($process.Name -ine 'freecad.exe') { continue }
        if ([string]::IsNullOrWhiteSpace($process.CommandLine)) {
            $unreadable += $process.ProcessId
        } elseif ($process.CommandLine.Replace('/', '\').IndexOf('\kurtshape-green\', [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $active += $process.ProcessId
        }
    }
    if ($unreadable.Count) {
        return [pscustomobject]@{status = 'refused'; reason = ('FreeCAD command line unavailable for PID(s): ' + ($unreadable -join ', ')); pids = $unreadable}
    }
    if ($active.Count) {
        return [pscustomobject]@{status = 'skipped'; reason = 'A FreeCAD process is using kurtshape-green'; pids = $active}
    }
    if (@($TrackedChanges | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count) {
        return [pscustomobject]@{status = 'refused'; reason = 'Green worktree has modified tracked files'; pids = @()}
    }
    return [pscustomobject]@{status = 'ready'; reason = $null; pids = @()}
}

function Invoke-KurtShapeGreenGit {
    param([string]$At = $mainRoot, [string[]]$Arguments, [switch]$AllowFailure)
    # Native stderr is captured as data; the exit code decides success.
    $ErrorActionPreference = 'Continue'
    $gitOptions = @('-c', ('safe.directory=' + $mainRoot))
    if ($At.Equals($greenRoot, [StringComparison]::OrdinalIgnoreCase) -and $greenRegistered) {
        $gitOptions += @('-c', ('safe.directory=' + $greenRoot))
    }
    $scratch = Join-Path $mainRoot 'runtime\longrun\green-copy-working'
    New-Item -ItemType Directory -Force -Path $scratch -ErrorAction Stop | Out-Null
    $stderrPath = Join-Path $scratch ([Guid]::NewGuid().ToString('N') + '-git-stderr.txt')
    try {
        $lines = @(& $gitExecutable @gitOptions -C $At @Arguments 2> $stderrPath | ForEach-Object { $_.ToString() })
        $code = $LASTEXITCODE
        $diagnostics = @(Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)
        if ($diagnostics.Count) {
            $metadata.git_diagnostics += [pscustomobject]@{at = $At; arguments = $Arguments; exit_code = $code; stderr = $diagnostics}
        }
        if ($code -ne 0 -and -not $AllowFailure) {
            throw ('git failed (' + $code + '): ' + (@($lines) + @($diagnostics) -join [Environment]::NewLine))
        }
        return [pscustomobject]@{code = $code; lines = $lines; stderr = $diagnostics}
    } finally {
        Remove-Item -LiteralPath $stderrPath -ErrorAction SilentlyContinue
    }
}

function Get-KurtShapeGreenTag {
    param([string]$At)
    $result = Invoke-KurtShapeGreenGit -At $At -Arguments @('describe', '--tags', '--exact-match', 'HEAD') -AllowFailure
    if ($result.code -eq 0) { return ($result.lines -join '').Trim() }
    return $null
}

try {
    if ($mainRoot.Equals($greenRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Run this updater from the main checkout, not kurtshape-green.'
    }
    $gitExecutable = (Get-Command git -CommandType Application -ErrorAction Stop).Source
    $resolved = Invoke-KurtShapeGreenGit -Arguments @('rev-parse', '--verify', '--end-of-options', ($Commit + '^{commit}'))
    $metadata.resolved_commit = ($resolved.lines -join '').Trim()
    if ($metadata.resolved_commit -notmatch '^[0-9a-fA-F]{40,64}$') {
        throw 'The requested revision did not resolve to a local commit.'
    }
    $worktrees = Invoke-KurtShapeGreenGit -Arguments @('worktree', 'list', '--porcelain')
    $registered = @($worktrees.lines | Where-Object { $_.StartsWith('worktree ') } | ForEach-Object {
        [IO.Path]::GetFullPath($_.Substring(9)).TrimEnd('\', '/')
    })
    $greenRegistered = @($registered | Where-Object {
        $_.Equals($greenRoot.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase)
    }).Count -gt 0
    $greenExists = Test-Path -LiteralPath $greenRoot
    $trackedChanges = @()
    if ($greenExists) {
        $directory = Get-Item -LiteralPath $greenRoot
        if (-not $directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The green path must be a real directory, not a file or linked directory.'
        }
        if (-not $greenRegistered) { throw 'The existing green path is not a worktree of this repository.' }
        $previous = Invoke-KurtShapeGreenGit -At $greenRoot -Arguments @('rev-parse', 'HEAD')
        $metadata.previous_commit = ($previous.lines -join '').Trim()
        $metadata.previous_tag = Get-KurtShapeGreenTag -At $greenRoot
        $metadata.green_commit = $metadata.previous_commit
        $metadata.green_tag = $metadata.previous_tag
        $tracked = Invoke-KurtShapeGreenGit -At $greenRoot -Arguments @('status', '--porcelain=v1', '--untracked-files=no')
        $trackedChanges = $tracked.lines
    } elseif ($greenRegistered) {
        throw 'The registered green worktree directory is missing; refusing to replace it.'
    }
    try {
        $processes = @(Get-CimInstance Win32_Process -Filter "Name='freecad.exe'" -ErrorAction Stop)
    } catch {
        throw ('Process inventory unavailable; refusing to update green copy: ' + $_.Exception.Message)
    }
    $guard = Get-KurtShapeGreenGuard -Processes $processes -TrackedChanges $trackedChanges
    $metadata.status = $guard.status
    $metadata.reason = $guard.reason
    $metadata.active_pids = @($guard.pids)
    if ($guard.status -eq 'ready' -and -not $CheckOnly) {
        if ($greenExists) {
            $updated = Invoke-KurtShapeGreenGit -At $greenRoot -Arguments @('checkout', '--detach', $metadata.resolved_commit)
        } else {
            $updated = Invoke-KurtShapeGreenGit -Arguments @('worktree', 'add', '--detach', $greenRoot, $metadata.resolved_commit)
        }
        $metadata.git_output = @($updated.lines)
        $metadata.changed = $true
        $head = Invoke-KurtShapeGreenGit -At $greenRoot -Arguments @('rev-parse', 'HEAD')
        $metadata.green_commit = ($head.lines -join '').Trim()
        $metadata.green_tag = Get-KurtShapeGreenTag -At $greenRoot
        if ($metadata.green_commit -ne $metadata.resolved_commit) {
            throw 'Green worktree HEAD does not match the requested commit.'
        }
        $mainName = (Split-Path -Leaf $mainRoot).Replace('%', '%%')
        $launcher = @(
            '@echo off',
            ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0kurtshape-green\launch-kurtshape.ps1" -RuntimeRoot "%~dp0' + $mainName + '\runtime" -SessionRoot "%~dp0' + $mainName + '\runtime"'),
            'if errorlevel 1 pause'
        ) -join "`r`n"
        [IO.File]::WriteAllText($launcherPath, $launcher + "`r`n", [Text.UTF8Encoding]::new($false))
        $metadata.status = 'updated'
    }
} catch {
    $metadata.status = 'refused'
    $metadata.reason = $_.Exception.Message
}
$metadata | ConvertTo-Json -Depth 5
if ($metadata.status -eq 'refused') { exit 2 }
exit 0
