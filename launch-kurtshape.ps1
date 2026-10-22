param(
    [string]$FilePath,
    [switch]$Validation,
    [switch]$WriteEvidence,
    [ValidateNotNullOrEmpty()][string]$RuntimeRoot = (Join-Path $PSScriptRoot 'runtime'),
    [ValidateNotNullOrEmpty()][string]$SessionRoot = (Join-Path $PSScriptRoot 'runtime'),
    [switch]$PrintOnly
)
$ErrorActionPreference = 'Stop'
$openFile = $null
if ($FilePath) {
    if ($Validation) { throw '-FilePath cannot be combined with -Validation.' }
    $openFile = [IO.Path]::GetFullPath($FilePath)
    if ([IO.Path]::GetExtension($openFile) -ine '.FCStd') { throw 'Select a native .FCStd project.' }
    if (-not (Test-Path -LiteralPath $openFile -PathType Leaf)) { throw ('Project does not exist: ' + $openFile) }
}
$kurtshapeRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$SessionRoot = [IO.Path]::GetFullPath($SessionRoot)
if ($Validation) {
    $protectedFolders = @('user-data','temporary','appdata','localappdata','project-recovery','freecad-1.1.4','downloads')
    foreach ($liveBase in @((Join-Path $kurtshapeRoot 'runtime'), $RuntimeRoot) | Select-Object -Unique) {
        foreach ($folder in $protectedFolders) {
            $protected = (Join-Path $liveBase $folder).TrimEnd('\','/')
            if ($SessionRoot.TrimEnd('\','/') -eq $protected -or $SessionRoot.StartsWith($protected + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw ('Validation session base cannot be inside a live profile or engine folder: ' + $SessionRoot)
            }
        }
    }
    $ancestor = Join-Path $SessionRoot 'interface-validation'
    while ($ancestor) {
        try { $entry = Get-Item -LiteralPath $ancestor -Force -ErrorAction Stop }
        catch {
            if ($_.CategoryInfo.Category -ne [Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
            $entry = $null
        }
        if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw ('Validation session path cannot pass through a junction or symbolic link: ' + $ancestor)
        }
        $parent = [IO.Directory]::GetParent($ancestor)
        $ancestor = if ($parent) { $parent.FullName } else { $null }
    }
}
$runtimePath = if ($Validation) { Join-Path $SessionRoot 'interface-validation' } else { $SessionRoot }
$exePath = Join-Path $RuntimeRoot 'freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
$macroPath = Join-Path $kurtshapeRoot $(if ($Validation) {'tools\gui-validation.FCMacro'} else {'KurtShape.FCMacro'})
$userConfigPath = Join-Path $runtimePath 'user-data\user.cfg'
$systemConfigPath = Join-Path $runtimePath 'user-data\system.cfg'
$launchArguments = @('-u', ('"'+$userConfigPath+'"'), '-s', ('"'+$systemConfigPath+'"'), '--log-file', ('"'+(Join-Path $runtimePath 'freecad-launch.log')+'"'))
$launchArguments += ('"'+$macroPath+'"')
$launchWindowStyle = if ($Validation) { 'Hidden' } else { 'Normal' }
$launchEnvironment = [ordered]@{
    KURTSHAPE_ROOT = $kurtshapeRoot
    KURTSHAPE_OPEN_FILE = $openFile
    KURTSHAPE_SESSION_DIR = $runtimePath
    KURTSHAPE_NO_DEMO = $(if ($Validation) { '1' } else { $null })
    FREECAD_USER_HOME = Join-Path $runtimePath 'user-data'
    TEMP = Join-Path $runtimePath 'temporary'
    TMP = Join-Path $runtimePath 'temporary'
    APPDATA = Join-Path $runtimePath 'appdata'
    LOCALAPPDATA = Join-Path $runtimePath 'localappdata'
    PYTHONDONTWRITEBYTECODE = '1'
}
if ($Validation) {
    $launchEnvironment.KURTSHAPE_DEMO = $null
    $launchEnvironment.KURTSHAPE_EVIDENCE_DIR = Join-Path $runtimePath 'evidence'
    $launchEnvironment.KURTSHAPE_TEST_TMP = Join-Path $runtimePath 'test-tmp'
    $launchEnvironment.KURTSHAPE_WRITE_EVIDENCE = $(if ($WriteEvidence) { '1' } else { $null })
}
if ($PrintOnly) {
    [ordered]@{
        executable = $exePath
        macro = $macroPath
        session = $runtimePath
        runtime_root = $RuntimeRoot
        session_root = $SessionRoot
        working_directory = $kurtshapeRoot
        environment = $launchEnvironment
        arguments = $launchArguments
        window_style = $launchWindowStyle
    } | ConvertTo-Json -Depth 5
    return
}
if ($openFile) {
    # A KurtShape already running for this session opens the file in its own window.
    if (& (Join-Path $PSScriptRoot 'tools\open-in-running-app.ps1') -Session $runtimePath -FilePath $openFile) { return }
}
if ($Validation) {
    . (Join-Path $PSScriptRoot 'tools\validation-session.ps1')
    Initialize-KurtShapeValidationEnvironment -Root $kurtshapeRoot -Session $runtimePath -SessionBase $SessionRoot -WriteEvidence:$WriteEvidence
} else {
    foreach ($folder in @('temporary','user-data','appdata','localappdata')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $runtimePath $folder) | Out-Null
    }
    $env:KURTSHAPE_ROOT = $kurtshapeRoot
    $env:KURTSHAPE_OPEN_FILE = $openFile
    $env:KURTSHAPE_SESSION_DIR = $runtimePath
    Remove-Item Env:KURTSHAPE_NO_DEMO -ErrorAction SilentlyContinue
    $env:FREECAD_USER_HOME = Join-Path $runtimePath 'user-data'
    $env:TEMP = Join-Path $runtimePath 'temporary'
    $env:TMP = $env:TEMP
    $env:APPDATA = Join-Path $runtimePath 'appdata'
    $env:LOCALAPPDATA = Join-Path $runtimePath 'localappdata'
    $env:PYTHONDONTWRITEBYTECODE = '1'
}
if ($Validation) {
    Remove-Item Env:KURTSHAPE_OPEN_FILE -ErrorAction SilentlyContinue
    $env:KURTSHAPE_NO_DEMO = '1'
    Remove-Item Env:KURTSHAPE_DEMO -ErrorAction SilentlyContinue
}
if (-not (Test-Path -LiteralPath $exePath)) { throw 'Run install-runtime.ps1 first.' }
$launchProcess = Start-Process -FilePath $exePath -ArgumentList $launchArguments -WorkingDirectory $kurtshapeRoot -WindowStyle $launchWindowStyle -PassThru
if ($Validation) {
    Register-KurtShapeValidationProcess -Process $launchProcess -Executable $exePath -Arguments $launchArguments
    Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'interface-pass') 'gui-test-result.json'))
}
$launchProcess | Select-Object Id
