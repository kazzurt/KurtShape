# Start or stop a PRIVATE KurtShape app for end-to-end bridge checks (never Kurt's app or profile).
#
#   .\tools\private-session.ps1 -Session v32smoke            # start; prints the session file to use
#   & $PYW -B tools\assistant_client.py --session runtime\private\v32smoke\assistant-session.json --json '{"op":"capabilities"}'
#   .\tools\private-session.ps1 -Session v32smoke -Stop -Remove
#   .\tools\private-session.ps1 -Session agent -Ensure -ProjectRoot C:\...\projects   # start, or reuse a running one
#
# The session lives in runtime\private\<name> (<= 24 characters) with its own user/system config,
# TEMP, APPDATA, LOCALAPPDATA, evidence folder, ephemeral bridge port and assistant-session.json.
# Defaults: QT_QPA_PLATFORM=offscreen and a hidden window (a Windows-QPA app would show its main
# window on the desktop; Windows-QPA evidence comes from run_gui_recipe.ps1). -Visible keeps the
# native platform with a minimized window. The process environment is restored afterwards.
# -Stop kills only the recorded process, and only when its PID, start time and command line (which
# must contain this session's user.cfg) all match the record; Kurt's app runs the same freecad.exe.
# -Ensure reuses the session when its recorded process is still running (instead of refusing), after
# checking that it already grants every -ProjectRoot. -ProjectRoot adds existing folders the app may
# save and export to (the session folder itself is always granted).
# -PinPerformanceCores / -NoPinPerformanceCores set the started freecad.exe's affinity to the performance
# cores or leave it alone (default: tools\performance-cores.ps1); the record keeps the applied mask. A reused
# (-Ensure) app keeps the affinity it was started with.
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$')][string]$Session,
    [switch]$Stop,
    [switch]$Remove,
    [switch]$Visible,
    [switch]$Ensure,
    [string[]]$ProjectRoot = @(),
    [ValidateRange(10,900)][int]$TimeoutSeconds = 120,
    [switch]$PinPerformanceCores,
    [switch]$NoPinPerformanceCores
)
$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'validation-session.ps1')
. (Join-Path $PSScriptRoot 'performance-cores.ps1')
if ($PinPerformanceCores -and $NoPinPerformanceCores) { throw '-PinPerformanceCores and -NoPinPerformanceCores are exclusive.' }
$sessionBase = Join-Path $repositoryRoot 'runtime\private'
$sessionPath = Join-Path $sessionBase $Session
$recordPath = Join-Path $sessionPath 'private-app.json'
$sessionFile = Join-Path $sessionPath 'assistant-session.json'
$userConfig = Join-Path $sessionPath 'user-data\user.cfg'
$systemConfig = Join-Path $sessionPath 'user-data\system.cfg'
$executable = Join-Path $repositoryRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
$maxTemp = 104

# Never pass through a junction or symbolic link on the way to the private session.
$ancestor = $sessionPath
while ($ancestor) {
    try { $entry = Get-Item -LiteralPath $ancestor -Force -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -ne [Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
        $entry = $null
    }
    if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw ('Private session cannot pass through a junction or symbolic link: ' + $ancestor)
    }
    $parent = [IO.Directory]::GetParent($ancestor)
    $ancestor = if ($parent) { $parent.FullName } else { $null }
}

function Get-OwnedPrivateProcess {
    # Returns the live process only when PID, start time and command line all match the record.
    param($Record)
    $process = Get-Process -Id ([int]$Record.pid) -ErrorAction SilentlyContinue
    if (-not $process) { return $null }
    $startTime = $process.StartTime.ToUniversalTime().ToString('o')
    if ($startTime -ne [string]$Record.start_time_utc) { return $null }
    $instance = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + [int]$Record.pid) -ErrorAction SilentlyContinue
    if (-not $instance -or -not $instance.CommandLine) { return $null }
    if ($instance.CommandLine.IndexOf([string]$Record.user_config, [StringComparison]::OrdinalIgnoreCase) -lt 0) { return $null }
    if ([IO.Path]::GetFullPath($instance.ExecutablePath) -ne [IO.Path]::GetFullPath($executable)) { return $null }
    return $process
}

if ($Stop) {
    if (-not (Test-Path -LiteralPath $recordPath -PathType Leaf)) {
        Write-Output ('No private app record: ' + $recordPath)
    } else {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        if ([string]$record.user_config -ne $userConfig) { throw ('Record does not belong to this session: ' + $recordPath) }
        $owned = Get-OwnedPrivateProcess $record
        if ($owned) {
            Stop-Process -Id $owned.Id -Force
            if (-not $owned.WaitForExit(15000)) { throw ('Private app did not exit: ' + $owned.Id) }
            Write-Output ('Stopped private app ' + $owned.Id)
        } else {
            Write-Output ('Recorded private app ' + $record.pid + ' is not running (or no longer matches its record); nothing stopped')
        }
        if (Test-Path -LiteralPath $sessionFile -PathType Leaf) {
            try { $published = Get-Content -LiteralPath $sessionFile -Raw | ConvertFrom-Json } catch { $published = $null }
            if ($published -and [int]$published.pid -eq [int]$record.pid) { Remove-Item -LiteralPath $sessionFile -Force }
        }
        Remove-Item -LiteralPath $recordPath -Force
    }
    if ($Remove -and (Test-Path -LiteralPath $sessionPath)) {
        Remove-Item -LiteralPath $sessionPath -Recurse -Force
        Write-Output ('Removed ' + $sessionPath)
    }
    return
}
if ($Remove) { throw '-Remove is only valid with -Stop' }
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw ('Pinned runtime is missing: ' + $executable) }
$grants = @()
foreach ($folder in $ProjectRoot) {
    if (-not [IO.Path]::IsPathRooted($folder) -or -not (Test-Path -LiteralPath $folder -PathType Container)) {
        throw ('-ProjectRoot must be an existing absolute folder: ' + $folder)
    }
    $grants += [IO.Path]::GetFullPath($folder).TrimEnd('\')
}
$settings = Join-Path $sessionPath 'settings.json'
if (Test-Path -LiteralPath $recordPath) {
    $previous = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    if (Get-OwnedPrivateProcess $previous) {
        if (-not $Ensure) { throw ('Private session is already running: PID ' + $previous.pid + '; stop it first') }
        $published = $null
        try { $published = Get-Content -LiteralPath $sessionFile -Raw | ConvertFrom-Json } catch { }
        if (-not $published -or [int]$published.pid -ne [int]$previous.pid) {
            throw ('Private session PID ' + $previous.pid + ' is running but has not published ' + $sessionFile + '; stop it and start again')
        }
        $granted = @((Get-Content -LiteralPath $settings -Raw | ConvertFrom-Json).project_roots | ForEach-Object { ([string]$_).TrimEnd('\') })
        $missing = @($grants | Where-Object { $granted -notcontains $_ })
        if ($missing.Count) {
            throw ('Running private session ' + $Session + ' does not grant ' + ($missing -join ', ') + '; stop it with -Stop and start it again')
        }
        $recordedMask = if ($previous.affinity_mask) { [string]$previous.affinity_mask } else { 'none' }
        if ($PinPerformanceCores -or $NoPinPerformanceCores) {
            $requested = Get-KurtShapePinningPlan -PinPerformanceCores:$PinPerformanceCores -NoPinPerformanceCores:$NoPinPerformanceCores
            $requestedMask = if ($requested.mask) { [string]$requested.mask } else { 'none' }
            if ($requestedMask -ne $recordedMask) {
                Write-Warning ('Reused PID ' + $previous.pid + ' keeps affinity ' + $recordedMask + ' (requested ' + $requestedMask + '); stop it with -Stop to change')
            }
        }
        Write-Output ('Private KurtShape PID ' + $previous.pid + ' (already running; affinity ' + $recordedMask + '); session file: ' + $sessionFile)
        return
    }
    Remove-Item -LiteralPath $recordPath -Force
}
$temporary = Join-Path $sessionPath 'temporary'
if ($temporary.Length -gt $maxTemp) { throw ('Private TEMP would be ' + $temporary.Length + ' characters; limit ' + $maxTemp) }

$environmentNames = @('KURTSHAPE_ROOT','KURTSHAPE_SESSION_DIR','KURTSHAPE_EVIDENCE_DIR','KURTSHAPE_WRITE_EVIDENCE',
    'FREECAD_USER_HOME','TEMP','TMP','APPDATA','LOCALAPPDATA','KURTSHAPE_TEST_TMP','PYTHONDONTWRITEBYTECODE',
    'QT_QPA_PLATFORM','KURTSHAPE_DEMO','KURTSHAPE_NO_DEMO','KURTSHAPE_PERF')
$environmentBefore = @{}
foreach ($name in $environmentNames) {
    $environmentBefore[$name] = @{present=(Test-Path -LiteralPath ('Env:' + $name));value=[Environment]::GetEnvironmentVariable($name, 'Process')}
}
try {
    # Refuses runtime\private itself and anything outside it, so it cannot resolve to a live profile folder.
    Initialize-KurtShapeValidationEnvironment -Root $repositoryRoot -Session $sessionPath -SessionBase $sessionBase
    if ($env:TEMP.Length -gt $maxTemp) { throw ('Private TEMP is ' + $env:TEMP.Length + ' characters; limit ' + $maxTemp) }
    Remove-Item Env:KURTSHAPE_DEMO -ErrorAction SilentlyContinue
    Remove-Item Env:KURTSHAPE_PERF -ErrorAction SilentlyContinue
    $env:KURTSHAPE_NO_DEMO = '1'
    if ($Visible) { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue } else { $env:QT_QPA_PLATFORM = 'offscreen' }
    # Without workspace_layout, Settings infers 'legacy' for an existing file, which grants CADkz/Codex.
    [IO.File]::WriteAllText($settings, (@{ workspace_layout = 'portable'; project_roots = @(@($sessionPath) + $grants) } | ConvertTo-Json),
        [Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $sessionFile -ErrorAction SilentlyContinue
    $arguments = @('-u', ('"' + $userConfig + '"'), '-s', ('"' + $systemConfig + '"'),
        '--log-file', ('"' + (Join-Path $sessionPath 'freecad.log') + '"'), ('"' + (Join-Path $repositoryRoot 'KurtShape.FCMacro') + '"'))
    $style = if ($Visible) { 'Minimized' } else { 'Hidden' }
    $pinning = Get-KurtShapePinningPlan -PinPerformanceCores:$PinPerformanceCores -NoPinPerformanceCores:$NoPinPerformanceCores
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $repositoryRoot -WindowStyle $style -PassThru `
        -RedirectStandardOutput (Join-Path $sessionPath 'freecad-stdout.txt') -RedirectStandardError (Join-Path $sessionPath 'freecad-stderr.txt')
    $null = $process.Handle
    $affinity = Set-KurtShapeProcessAffinity -Process $process -Plan $pinning
    Register-KurtShapeValidationProcess -Process $process -Executable $executable -Arguments $arguments
    $record = [ordered]@{
        pid = $process.Id; start_time_utc = $process.StartTime.ToUniversalTime().ToString('o'); user_config = $userConfig
        session = $sessionPath; session_file = $sessionFile; executable = $executable; visible = [bool]$Visible
        qpa = $(if ($Visible) { 'windows' } else { 'offscreen' }); started_utc = [DateTime]::UtcNow.ToString('o')
        pin_requested = $pinning.requested; affinity_mask = $affinity
    }
    [IO.File]::WriteAllText($recordPath, ($record | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ($true) {
        if (Test-Path -LiteralPath $sessionFile -PathType Leaf) {
            try { $published = Get-Content -LiteralPath $sessionFile -Raw | ConvertFrom-Json } catch { $published = $null }
            if ($published -and [int]$published.pid -eq $process.Id) { break }
        }
        if ($process.HasExited) { throw ('Private KurtShape exited with ' + $process.ExitCode + '; log: ' + (Join-Path $sessionPath 'freecad.log')) }
        if ((Get-Date) -gt $deadline) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw ('Private KurtShape did not publish its assistant-session.json within ' + $TimeoutSeconds + ' s')
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Output ('Private KurtShape PID ' + $process.Id + '; session file: ' + $sessionFile)
} finally {
    foreach ($name in $environmentNames) {
        if ($environmentBefore[$name].present) { [Environment]::SetEnvironmentVariable($name, $environmentBefore[$name].value, 'Process') }
        else { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
    }
}
