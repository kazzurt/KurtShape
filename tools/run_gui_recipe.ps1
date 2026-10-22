param(
    [ValidateSet('plane-visibility','step-export','parts-refresh','geometry-check-timing','geometry-check-lifecycle','geometry-check','interface','ui-refinement','extrusion-preview','refinement-preview','sketch-behavior',
        'review-interaction','review-lifecycle','review-copy','review-recovery','review-startup','review-baseline','responsiveness-preview',
        'messages','assembly','step-import','assembly-step','carrier-spike','part-studio','bench-gui','onshape-workflows','view-interaction','design-surface','theme-startup','sketch-references','rollback-history','sketch-edit-state','history-selection','face-feature-selection','sketch-plane-editor','sketch-dimension-point-colors','sketch-regions','unused-sketch-visibility','presentation-scheduling','startup-view','sketch-origin-snap','sketch-drag','surface-snap','extrusion-edit','history-lifecycle','everyday-ui','dress-up-edit','headless-open','interaction-idle','document-lifecycle','result-validation','render-view','batch-undo','parameter-panel','parameter-panel-reopen','section-view','startup-blank','open-handoff','sketch-floating-controls','sketch-coincident-lines','sketch-midpoint-motion')]
    [string]$Recipe = 'interface',
    [ValidateRange(1,7200)][int]$TimeoutSeconds = 900,
    [switch]$WriteEvidence,
    [ValidateRange(1,1000)][int]$Holes = 20,
    [ValidateRange(1,100)][int]$Repeat = 3,
    [string]$PreviewSource = '',
    # Copied to user-data\user.cfg before FreeCAD starts (second process of a persistence pair).
    [string]$SeedUserConfig = '',
    # bench-gui: number of parameters its parameter metrics create (0 = none; contract 3.2 parameters).
    [ValidateRange(0,500)][int]$Parameters = 0
)
$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
. (Join-Path $PSScriptRoot 'validation-session.ps1')
function Convert-GuiRecipeUtc {
    param($Value)
    if ($Value -is [DateTimeOffset]) { return $Value.UtcDateTime }
    if ($Value -is [DateTime]) { return $Value.ToUniversalTime() }
    if ($Value -isnot [string]) { throw 'Recovery proof timestamp is missing or invalid.' }
    return [DateTimeOffset]::Parse($Value, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
}
$recipes = @{
    'plane-visibility' = @('plane-visibility-validation.FCMacro', 'plane-visibility\gui-result.json', 0)
    'step-export' = @('step-export-validation.FCMacro', 'step-export\gui-result.json', 0)
    'extrusion-edit' = @('extrusion-edit-gui-validation.FCMacro', 'extrusion-edit\gui-result.json', 0)
    'history-lifecycle' = @('history-lifecycle-validation.FCMacro', 'history-lifecycle\gui-result.json', 0)
    'everyday-ui' = @('everyday-ui-validation.FCMacro', 'everyday-ui\gui-result.json', 0)
    'dress-up-edit' = @('dress-up-edit-validation.FCMacro', 'dress-up-edit\gui-result.json', 0)
    'headless-open' = @('headless-open-validation.FCMacro', 'headless-open\gui-result.json', 0)
    'parts-refresh' = @('parts-refresh-validation.FCMacro', 'parts-refresh\gui-result.json', 0)
    'geometry-check-timing' = @('geometry-check-timing-validation.FCMacro', 'geometry-check-timing\gui-result.json', 0)
    'geometry-check-lifecycle' = @('geometry-check-lifecycle-validation.FCMacro', 'geometry-check-lifecycle\gui-result.json', 0)
    'geometry-check' = @('geometry-check-validation.FCMacro', 'geometry-check\gui-result.json', 0)
    'surface-snap' = @('surface-snap-validation.FCMacro', 'surface-snap\gui-result.json', 0)
    'startup-view' = @('startup-view-validation.FCMacro', 'startup-view\gui-result.json', 0)
    'sketch-origin-snap' = @('sketch-origin-snap-validation.FCMacro', 'sketch-origin-snap\gui-result.json', 0)
    'sketch-drag' = @('sketch-drag-validation.FCMacro', 'sketch-drag\gui-result.json', 0)
    'responsiveness-preview' = @('responsiveness-preview-benchmark.FCMacro', 'responsiveness-preview\gui-result.json', 0)
    'presentation-scheduling' = @('presentation-scheduling-validation.FCMacro', 'presentation-scheduling\gui-result.json', 0)
    'unused-sketch-visibility' = @('unused-sketch-visibility-validation.FCMacro', 'unused-sketch-visibility\gui-result.json', 0)
    'sketch-regions' = @('sketch-regions-validation.FCMacro', 'sketch-regions\gui-result.json', 0)
    'sketch-dimension-point-colors' = @('sketch-dimension-point-colors-validation.FCMacro', 'sketch-dimension-point-colors\gui-result.json', 0)
    'theme-startup' = @('theme-startup-validation.FCMacro', 'theme-startup\gui-result.json', 0)
    'design-surface' = @('design-surface-validation.FCMacro', 'onshape-design\gui-result.json', 0)
    'view-interaction' = @('view-interaction-validation.FCMacro', 'view-interaction\result.json', 0)
    'onshape-workflows' = @('onshape-workflows-validation.FCMacro', 'onshape-workflows\gui-result.json', 0)
    'interface' = @('gui-validation.FCMacro', 'interface-pass\gui-test-result.json', 0)
    'ui-refinement' = @('ui-refinement-validation.FCMacro', 'ui-refinement\gui-refinement.json', 0)
    'extrusion-preview' = @('extrusion-preview-validation.FCMacro', 'ui-refinement-preview\gui-result.json', 0)
    'refinement-preview' = @('extrusion-preview-validation.FCMacro', 'ui-refinement-preview\gui-result.json', 0)
    'sketch-behavior' = @('sketch-behavior-validation.FCMacro', 'sketch-behavior\native-behavior.json', 0)
    'sketch-references' = @('sketch-references-validation.FCMacro', 'sketch-references\gui-result.json', 0)
    'sketch-edit-state' = @('sketch-edit-state-validation.FCMacro', 'sketch-edit-state\gui-result.json', 0)
    'sketch-plane-editor' = @('sketch-plane-editor-validation.FCMacro', 'sketch-plane-editor\gui-result.json', 0)
    'history-selection' = @('history-selection-validation.FCMacro', 'history-selection\gui-result.json', 0)
    'face-feature-selection' = @('face-feature-selection-validation.FCMacro', 'face-feature-selection\gui-result.json', 0)
    'rollback-history' = @('rollback-history-validation.FCMacro', 'rollback-history\gui-result.json', 0)
    'review-interaction' = @('gui-review-validation.FCMacro', 'review-followup\gui-review.json', 0)
    'review-lifecycle' = @('sketch-lifecycle-validation.FCMacro', 'sketch-lifecycle-result.json', 0)
    'review-copy' = @('general-actions-validation.FCMacro', 'general-actions-gui-result.json', 0)
    'review-recovery' = @('review-recovery-crash.FCMacro', 'review-followup\recovery-crash.json', @(23, -1073740791))
    'review-startup' = @('gui-startup-diagnostics.FCMacro', 'startup-diagnostics\startup-result.json', 0)
    'review-baseline' = @('gui-startup-diagnostics.FCMacro', 'startup-diagnostics\baseline-result.json', 0)
    'messages' = @('messages-validation.FCMacro', 'messages-behavior\gui-result.json', 0)
    'assembly' = @('assembly-gui-validation.FCMacro', 'assembly-workflow\gui-test-result.json', 0)
    'step-import' = @('step-import-gui-validation.FCMacro', 'step-import\gui-test-result.json', 0)
    'assembly-step' = @('assembly-step-validation.FCMacro', 'assembly-step-import\gui-result.json', 0)
    'carrier-spike' = @('part-model-spike-gui-validation.FCMacro', 'u2-part-model-spike\gui-carrier-result.json', 0)
    'part-studio' = @('u2-part-model-gui-validation.FCMacro', 'u2-part-model\gui-result.json', 0)
    'bench-gui' = @('perf\bench_gui.FCMacro', 'perf\bench-gui.json', 0)
    'interaction-idle' = @('interaction-idle-validation.FCMacro', 'interaction-idle\gui-result.json', 0)
    'document-lifecycle' = @('document-lifecycle-gui-validation.FCMacro', 'document-lifecycle\gui-result.json', 0)
    'result-validation' = @('result-validation-gui-validation.FCMacro', 'result-validation\gui-result.json', 0)
    'render-view' = @('render-view-validation.FCMacro', 'render-view\gui-result.json', 0)
    'batch-undo' = @('batch-undo-validation.FCMacro', 'batch-undo\gui-result.json', 0)
    'parameter-panel' = @('parameter-panel-validation.FCMacro', 'parameter-panel\gui-result.json', 0)
    'parameter-panel-reopen' = @('parameter-panel-reopen-validation.FCMacro', 'parameter-panel-reopen\gui-result.json', 0)
    'section-view' = @('section-view-validation.FCMacro', 'section-view\gui-result.json', 0)
    'startup-blank' = @('startup-blank-validation.FCMacro', 'startup-blank\gui-result.json', 0)
    'open-handoff' = @('open-handoff-validation.FCMacro', 'open-handoff\gui-result.json', 0)
    'sketch-floating-controls' = @('sketch-floating-controls-validation.FCMacro', 'sketch-floating-controls\gui-result.json', 0)
    'sketch-coincident-lines' = @('sketch-coincident-lines-validation.FCMacro', 'sketch-coincident-lines\gui-result.json', 0)
    'sketch-midpoint-motion' = @('sketch-midpoint-motion-validation.FCMacro', 'sketch-midpoint-motion\gui-result.json', 0)
}
$recipeDefinition = $recipes[$Recipe]
$macroPath = Join-Path $PSScriptRoot $recipeDefinition[0]
$executable = Join-Path $repositoryRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw ('Pinned GUI runtime is missing: ' + $executable) }
if (-not (Test-Path -LiteralPath $macroPath -PathType Leaf)) { throw ('Recipe macro is missing: ' + $macroPath) }
if ($SeedUserConfig) {
    if ($Recipe -eq 'theme-startup') { throw 'theme-startup seeds its own user.cfg; do not combine it with -SeedUserConfig.' }
    $SeedUserConfig = [IO.Path]::GetFullPath($SeedUserConfig)
    if (-not (Test-Path -LiteralPath $SeedUserConfig -PathType Leaf)) { throw ('Seed user.cfg is missing: ' + $SeedUserConfig) }
}
if ($PreviewSource -and $Recipe -notin @('responsiveness-preview','interaction-idle')) { throw ('-PreviewSource applies to responsiveness-preview and interaction-idle only: ' + $Recipe) }
if ($Parameters -and $Recipe -ne 'bench-gui') { throw ('-Parameters applies to bench-gui only: ' + $Recipe) }
$runName = 'run-' + [Guid]::NewGuid().ToString('N')
$session = Join-Path $repositoryRoot ('runtime\ci-gui\' + $Recipe + '\' + $runName)

# Reject redirected ancestors before creating any profile or report folders.
$ancestor = $session
while ($ancestor) {
    try { $entry = Get-Item -LiteralPath $ancestor -Force -ErrorAction Stop }
    catch {
        if ($_.CategoryInfo.Category -ne [Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
        $entry = $null
    }
    if ($entry -and ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw ('GUI recipe session cannot pass through a junction or symbolic link: ' + $ancestor)
    }
    $parent = [IO.Directory]::GetParent($ancestor)
    $ancestor = if ($parent) { $parent.FullName } else { $null }
}
if (Test-Path -LiteralPath $session) { throw ('GUI recipe requires a new private session: ' + $session) }
$environmentNames = @('KURTSHAPE_ROOT','KURTSHAPE_SESSION_DIR','KURTSHAPE_EVIDENCE_DIR','KURTSHAPE_WRITE_EVIDENCE',
    'FREECAD_USER_HOME','TEMP','TMP','APPDATA','LOCALAPPDATA','KURTSHAPE_TEST_TMP','PYTHONDONTWRITEBYTECODE',
    'QT_QPA_PLATFORM','KURTSHAPE_DEMO','KURTSHAPE_STARTUP_BASELINE','KURTSHAPE_NO_DEMO','BENCH_HOLES','BENCH_REPEAT','BENCH_GUI_OUT','PREVIEW_BENCH_SOURCE','BENCH_PARAMETERS')
$environmentBefore = @{}
foreach ($name in $environmentNames) {
    $environmentBefore[$name] = @{present=(Test-Path -LiteralPath ('Env:' + $name));value=[Environment]::GetEnvironmentVariable($name, 'Process')}
}
try {
# A crash producer always writes private immutable input for independent proof.
# Explicit publication copies that input and its separate proof only after verification.
$publishRecoveryEvidence = $WriteEvidence -and $Recipe -eq 'review-recovery'
$directWriteEvidence = $WriteEvidence -and -not $publishRecoveryEvidence
Initialize-KurtShapeValidationEnvironment -Root $repositoryRoot -Session $session -WriteEvidence:$directWriteEvidence
if ($Recipe -eq 'theme-startup') {
    # Reproduce the saved native dark theme before FreeCAD initializes its GUI.
    # The bundled preference pack contains appearance defaults, no user paths.
    $themeSeedPath = Join-Path $repositoryRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\data\Gui\PreferencePacks\FreeCAD Dark\FreeCAD Dark.cfg'
    Copy-Item -LiteralPath $themeSeedPath -Destination (Join-Path $session 'user-data\user.cfg')
}
if ($SeedUserConfig) {
    # A previous private session's preferences (for example persisted panel sizes) for a reopen check.
    Copy-Item -LiteralPath $SeedUserConfig -Destination (Join-Path $session 'user-data\user.cfg')
}
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
Remove-Item Env:KURTSHAPE_DEMO -ErrorAction SilentlyContinue
Remove-Item Env:KURTSHAPE_STARTUP_BASELINE -ErrorAction SilentlyContinue
foreach ($name in @('BENCH_HOLES','BENCH_REPEAT','BENCH_GUI_OUT','PREVIEW_BENCH_SOURCE','BENCH_PARAMETERS')) {
    Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue
}
if ($Recipe -eq 'review-baseline') { $env:KURTSHAPE_STARTUP_BASELINE = '1' }
$env:KURTSHAPE_NO_DEMO = '1'
$reportPath = Join-Path (Get-KurtShapeEvidenceDirectory) $recipeDefinition[1]
if ($Recipe -eq 'bench-gui') {
    $env:BENCH_HOLES = [string]$Holes
    $env:BENCH_REPEAT = [string]$Repeat
    $env:BENCH_GUI_OUT = $reportPath
    $env:BENCH_PARAMETERS = [string]$Parameters
}
if ($Recipe -eq 'responsiveness-preview') {
    $env:BENCH_HOLES = [string]$Holes
    $env:BENCH_REPEAT = [string]$Repeat
    if ($PreviewSource) { $env:PREVIEW_BENCH_SOURCE = [IO.Path]::GetFullPath($PreviewSource) }
    else { Remove-Item Env:PREVIEW_BENCH_SOURCE -ErrorAction SilentlyContinue }
}
if ($Recipe -eq 'interaction-idle') {
    # A prepared plate FCStd (copied into the session, never opened in place); otherwise the macro
    # builds plate60, or a plate with -Holes holes when -Holes is given explicitly.
    if ($PSBoundParameters.ContainsKey('Holes')) { $env:BENCH_HOLES = [string]$Holes }
    if ($PreviewSource) {
        $env:PREVIEW_BENCH_SOURCE = [IO.Path]::GetFullPath($PreviewSource)
        if (-not (Test-Path -LiteralPath $env:PREVIEW_BENCH_SOURCE -PathType Leaf)) { throw ('Preview source is missing: ' + $env:PREVIEW_BENCH_SOURCE) }
    }
}
$logPath = Join-Path $session 'freecad.log'
$stdoutPath = Join-Path $session 'freecad-stdout.txt'
$stderrPath = Join-Path $session 'freecad-stderr.txt'
$resultPath = Join-Path $session 'recipe-result.json'
$previousReportTime = if (Test-Path -LiteralPath $reportPath -PathType Leaf) { (Get-Item -LiteralPath $reportPath).LastWriteTimeUtc.Ticks } else { $null }

# Embedded FreeCAD does not reliably honor PYTHONDONTWRITEBYTECODE at startup.
$bootstrapPath = Join-Path $session 'run-recipe.FCMacro'
$macroLiteral = ConvertTo-Json -InputObject $macroPath -Compress
$bootstrap = @"
import sys
sys.dont_write_bytecode = True
from pathlib import Path
_recipe_macro = Path($macroLiteral)
exec(compile(_recipe_macro.read_text(encoding="utf-8-sig"), str(_recipe_macro), "exec"), globals())
"@
[IO.File]::WriteAllText($bootstrapPath, $bootstrap, [Text.UTF8Encoding]::new($false))
$arguments = @('-u', ('"' + (Join-Path $session 'user-data\user.cfg') + '"'),
    '-s', ('"' + (Join-Path $session 'user-data\system.cfg') + '"'),
    '--log-file', ('"' + $logPath + '"'), ('"' + $bootstrapPath + '"'))
$started = [DateTime]::UtcNow
$result = [ordered]@{
    recipe = $Recipe; passed = $false; session = $session; macro = $macroPath; report = $reportPath
    log = $logPath; stdout = $stdoutPath; stderr = $stderrPath
    started_utc = $started.ToString('o'); exited_utc = $null; pid = $null; exit_code = $null; timed_out = $false
    method = 'Independent hidden native FreeCAD process; recipe report checked after owned process exit.'
}
$process = $null
try {
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $repositoryRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    # Windows PowerShell reports a null ExitCode unless the handle is opened while running.
    $null = $process.Handle
    $result.pid = $process.Id
    Register-KurtShapeValidationProcess -Process $process -Executable $executable -Arguments $arguments
    Write-Host ('PID: ' + $process.Id + '; report: ' + $reportPath + '; result: ' + $resultPath)
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $result.timed_out = $true
        if (-not $process.HasExited) {
            try { Stop-Process -Id $process.Id -Force -ErrorAction Stop }
            catch { if (-not $process.HasExited) { throw } }
        }
        if (-not $process.WaitForExit(5000)) { throw ('Owned GUI process did not exit after timeout: ' + $process.Id) }
        throw ('GUI recipe timed out after ' + $TimeoutSeconds + ' seconds: ' + $Recipe)
    }
    $process.Refresh()
    $result.exit_code = $process.ExitCode
    $exited = [DateTime]::UtcNow
    $result.exited_utc = $exited.ToString('o')
    if ($process.ExitCode -notin @($recipeDefinition[2])) {
        throw ('GUI recipe exited ' + $process.ExitCode + '; expected ' + (@($recipeDefinition[2]) -join ' or ') + ': ' + $Recipe)
    }
    if ($Recipe -in @('review-startup', 'review-baseline')) {
        $log = Get-Content -LiteralPath $logPath -Raw
        $markers = @([regex]::Matches($log, '(?m)^.*\bSTARTUP_PROBE_(BEFORE|AFTER|FINISHED)\r?$') | ForEach-Object { $_.Groups[1].Value })
        $startup = [ordered]@{
            passed = ($markers.Count -eq 3 -and ($markers -join ',') -eq 'BEFORE,AFTER,FINISHED')
            pid = $process.Id; exit_code = $process.ExitCode; markers = $markers; log = $logPath
            method = 'Fresh isolated native startup log; exactly three ordered STARTUP_PROBE markers and normal owned-process exit.'
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $reportPath) | Out-Null
        $startup | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
    }
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) { throw ('GUI recipe did not write its report: ' + $reportPath) }
    $reportFile = Get-Item -LiteralPath $reportPath
    $reportDeadline = if ($Recipe -in @('review-startup','review-baseline')) { [DateTime]::UtcNow } else { $exited }
    if ((-not $directWriteEvidence -and $reportFile.CreationTimeUtc -lt $started) -or
        $reportFile.LastWriteTimeUtc -lt $started -or $reportFile.LastWriteTimeUtc -gt $reportDeadline -or
        ($null -ne $previousReportTime -and $reportFile.LastWriteTimeUtc.Ticks -eq $previousReportTime)) {
        throw ('GUI recipe report was not freshly written: ' + $reportPath)
    }
    $nativeReport = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($nativeReport.passed -isnot [bool] -or -not $nativeReport.passed) { throw ('GUI recipe report did not pass: ' + $reportPath) }
    if ($Recipe -eq 'parameter-panel' -and (-not $nativeReport.owned_documents_closed -or $nativeReport.check_count -ne @($nativeReport.checks).Count -or $nativeReport.check_count -lt 75)) {
        throw ('parameter-panel report is incomplete (check count or owned documents): ' + $reportPath)
    }
    if ($Recipe -in @('onshape-workflows', 'part-studio')) {
        $scopeWarnings = @(Select-String -LiteralPath $logPath,$stdoutPath,$stderrPath -Pattern 'go out of the allowed scope' |
            ForEach-Object { $_.Line.Trim() } | Select-Object -Unique)
        $result.scope_warning_count = $scopeWarnings.Count
        if ($scopeWarnings.Count) {
            $result.scope_warnings = $scopeWarnings
            throw ('Workflow recipe emitted native link-scope warnings: ' + $scopeWarnings.Count)
        }
    }
    if ($Recipe -eq 'sketch-references') {
        $sketchReferenceWarnings = @(Select-String -LiteralPath $logPath,$stdoutPath,$stderrPath -Pattern @(
            'Reading failed from embedded file:.*(?:InternalShape|Shape)\.bin',
            'Unmanaged change of Constraint Property results in invalid constraint indices',
            'empty shape') | ForEach-Object { $_.Line.Trim() } | Select-Object -Unique)
        $result.sketch_reference_warning_count = $sketchReferenceWarnings.Count
        if ($sketchReferenceWarnings.Count) {
            $result.sketch_reference_warnings = $sketchReferenceWarnings
            throw ('Sketch references emitted native shape or constraint warnings: ' + $sketchReferenceWarnings.Count)
        }
    }
    if ($Recipe -eq 'review-recovery') {
        if (($nativeReport.pid -isnot [int] -and $nativeReport.pid -isnot [long]) -or $nativeReport.pid -ne $process.Id) {
            throw 'Recovery producer PID does not match the owned GUI process.'
        }
        $sessionPrefix = [IO.Path]::GetFullPath($session).TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
        foreach ($key in @('original_file','checkpoint_manifest')) {
            if ($nativeReport.$key -isnot [string] -or -not $nativeReport.$key) { throw ('Recovery path is missing: ' + $key) }
            $path = [IO.Path]::GetFullPath($nativeReport.$key)
            if (-not $path.StartsWith($sessionPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw ('Recovery path must stay inside the exact private session: ' + $key)
            }
            if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw ('Recovery file is missing: ' + $key) }
            $component = $path
            while ($component -and $component.StartsWith($sessionPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                $item = Get-Item -LiteralPath $component -Force -ErrorAction Stop
                if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw ('Recovery path cannot contain a junction or symbolic link: ' + $key) }
                $parent = [IO.Directory]::GetParent($component)
                $component = if ($parent) { $parent.FullName } else { $null }
            }
        }
        $originalHash = (Get-FileHash -LiteralPath $nativeReport.original_file -Algorithm SHA256).Hash.ToLowerInvariant()
        $producerReportHash = (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $proofSession = Join-Path $repositoryRoot ('runtime\ci-gui\review-recovery-proof\run-' + [Guid]::NewGuid().ToString('N'))
        $proofAncestor = $proofSession
        while ($proofAncestor) {
            try { $item = Get-Item -LiteralPath $proofAncestor -Force -ErrorAction Stop }
            catch {
                if ($_.CategoryInfo.Category -ne [Management.Automation.ErrorCategory]::ObjectNotFound) { throw }
                $item = $null
            }
            if ($item -and ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw ('Recovery proof profile cannot pass through a junction or symbolic link: ' + $proofAncestor) }
            $parent = [IO.Directory]::GetParent($proofAncestor)
            $proofAncestor = if ($parent) { $parent.FullName } else { $null }
        }
        if (Test-Path -LiteralPath $proofSession) { throw 'Recovery proof requires a new independent profile.' }
        $proofPath = Join-Path $proofSession 'evidence\review-followup\recovery-proof.json'
        $proofEnvironmentBefore = @{}
        foreach ($name in $environmentNames) {
            $proofEnvironmentBefore[$name] = @{present=(Test-Path -LiteralPath ('Env:' + $name));value=[Environment]::GetEnvironmentVariable($name, 'Process')}
        }
        $verifier = $null
        try {
        $verificationStarted = [DateTime]::UtcNow
        try {
            Initialize-KurtShapeValidationEnvironment -Root $repositoryRoot -Session $proofSession
            if (Test-Path -LiteralPath $proofPath) { throw 'Recovery proof output must be absent before launch.' }
            $verifier = Invoke-KurtShapeValidationPython -Executable (Join-Path (Split-Path -Parent $executable) 'python.exe') -Arguments @(
                '-B', (Join-Path $PSScriptRoot 'verify_recovery_recipe.py'), '--producer-session', $session,
                '--producer-pid', [string]$process.Id, '--producer-start-utc', $result.started_utc,
                '--producer-exit-utc', $result.exited_utc, '--producer-exit-code', [string]$process.ExitCode,
                '--out', $proofPath) -Name 'recovery-postverify' -PassThru -TimeoutSeconds 120
            $verificationFinished = [DateTime]::UtcNow
        } finally {
            foreach ($name in $environmentNames) {
                if ($proofEnvironmentBefore[$name].present) { [Environment]::SetEnvironmentVariable($name, $proofEnvironmentBefore[$name].value, 'Process') }
                else { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
            }
        }
        $verifiedFile = Get-Item -LiteralPath $proofPath
        if ($verifiedFile.CreationTimeUtc -lt $verificationStarted -or $verifiedFile.LastWriteTimeUtc -lt $verificationStarted -or
            $verifiedFile.LastWriteTimeUtc -gt $verificationFinished) {
            throw 'Recovery verifier did not freshly write its report.'
        }
        $verified = Get-Content -LiteralPath $proofPath -Raw | ConvertFrom-Json
        if ($verified.passed -isnot [bool] -or -not $verified.passed -or
            ($verified.pid -isnot [int] -and $verified.pid -isnot [long]) -or $verified.pid -ne $verifier.Id -or
            ($verified.producer_pid -isnot [int] -and $verified.producer_pid -isnot [long]) -or $verified.producer_pid -ne $process.Id) {
            throw 'Recovery verification report does not match the successful owned Python process.'
        }
        $proofStarted = Convert-GuiRecipeUtc $verified.started_utc
        $proofCompleted = Convert-GuiRecipeUtc $verified.completed_utc
        if ($proofStarted -lt $verificationStarted -or $proofCompleted -lt $proofStarted -or $proofCompleted -gt $verificationFinished) {
            throw 'Recovery verification timestamp is missing or stale.'
        }
        if (@($verified.checks).Count -ne 10) { throw 'Recovery verification did not run all ten consequence checks.' }
        foreach ($key in @('producer_report_verified','checkpoint_pair_verified','reopened_checkpoint','recovered_draft',
            'recovered_unsaved_native_semantics','explicit_cancel_restored_accepted_sketch','cancel_preserved_unsaved_geometry',
            'cancel_kept_unsaved_native_semantics','original_file_unchanged','saved_project_reopened','producer_files_unchanged')) {
            if ($verified.$key -isnot [bool] -or -not $verified.$key) { throw ('Recovery proof must be true: ' + $key) }
        }
        if ($verified.original_file_sha256 -isnot [string] -or $verified.original_file_sha256 -notmatch '^[0-9a-fA-F]{64}$' -or
            $verified.original_file_sha256.ToLowerInvariant() -ne $originalHash -or
            (Get-FileHash -LiteralPath $nativeReport.original_file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $originalHash -or
            (Get-FileHash -LiteralPath $reportPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $producerReportHash) {
            throw 'Recovery original-file SHA256 proof is invalid or changed.'
        }
        if ($verified.recovered_draft_geometry -ne 1 -or $verified.accepted_sketch_geometry -ne 0) { throw 'Recovery draft and accepted geometry counts do not match the fixture.' }
        foreach ($volume in @(@{Name='recovered_unsaved_volume_mm3';Expected=1800},@{Name='saved_volume_mm3';Expected=1200})) {
            $actual = [double]$verified.($volume.Name)
            if ($null -eq $verified.($volume.Name) -or [double]::IsNaN($actual) -or [double]::IsInfinity($actual) -or [Math]::Abs($actual - $volume.Expected) -ge 1e-6) {
                throw ('Recovery volume consequence is invalid: ' + $volume.Name)
            }
        }
        $result.exit_classification = if ($process.ExitCode -eq 23) { 'intentional crash exit 23' } else { 'abnormal native termination 0xC0000409' }
        $result.post_recovery = [ordered]@{
            verified=$true;pid=$verifier.Id;session=$proofSession;report=$proofPath;checks=@($verified.checks).Count
            started_utc=$verified.started_utc;completed_utc=$verified.completed_utc;original_file_sha256=$originalHash
            reopened_checkpoint=$verified.reopened_checkpoint;recovered_draft=$verified.recovered_draft
            explicit_cancel_restored_accepted_sketch=$verified.explicit_cancel_restored_accepted_sketch
            original_file_unchanged=$verified.original_file_unchanged;saved_project_reopened=$verified.saved_project_reopened
            recovered_unsaved_volume_mm3=$verified.recovered_unsaved_volume_mm3;saved_volume_mm3=$verified.saved_volume_mm3
            native_autosave_reopened=$verified.native_autosave_reopened;native_autosave=$verified.native_autosave
        }
        $result.recovery_proof = $verified
        if ($publishRecoveryEvidence) {
            $publication = Join-Path $repositoryRoot 'validation\review-followup'
            New-Item -ItemType Directory -Force -Path $publication | Out-Null
            Copy-Item -LiteralPath $reportPath -Destination (Join-Path $publication 'recovery-crash.json')
            Copy-Item -LiteralPath $proofPath -Destination (Join-Path $publication 'recovery-proof.json')
            $result.published_recovery_evidence = $publication
        }
        } finally { if ($verifier) { $verifier.Dispose() } }
    }
    $result.passed = $true
} catch {
    $result.error = $_.Exception.Message
    if ($process -and -not $process.HasExited) {
        try {
            Stop-Process -Id $process.Id -Force -ErrorAction Stop
            if (-not $process.WaitForExit(5000)) { $result.cleanup_error = 'Owned process remains running: ' + $process.Id }
        } catch { $result.cleanup_error = $_.Exception.Message }
    }
    throw
} finally {
    try {
        if ($process) {
            $process.Refresh()
            if ($process.HasExited -and -not $result.exited_utc) {
                $result.exit_code = $process.ExitCode
                $result.exited_utc = [DateTime]::UtcNow.ToString('o')
            }
        }
        $result.finished_utc = [DateTime]::UtcNow.ToString('o')
        $result | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $resultPath -Encoding utf8
    } finally { if ($process) { $process.Dispose() } }
}
Write-Output ('GUI recipe passed: ' + $Recipe + '; report: ' + $reportPath + '; result: ' + $resultPath)
} finally {
    foreach ($name in $environmentNames) {
        if ($environmentBefore[$name].present) { [Environment]::SetEnvironmentVariable($name, $environmentBefore[$name].value, 'Process') }
        else { Remove-Item -LiteralPath ('Env:' + $name) -ErrorAction SilentlyContinue }
    }
}
