param([ValidateSet('copy','lifecycle','recovery','interaction','startup','baseline','step','assembly')][string]$Scenario='copy', [switch]$WriteEvidence)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'tools\validation-session.ps1')
$reviewRoot=$PSScriptRoot
$reviewSession=Join-Path $reviewRoot "runtime\review-$Scenario-validation"
Initialize-KurtShapeValidationEnvironment -Root $reviewRoot -Session $reviewSession -WriteEvidence:$WriteEvidence
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
if ($Scenario -eq 'baseline') { $env:KURTSHAPE_STARTUP_BASELINE='1'; $env:KURTSHAPE_NO_DEMO='1' }
else { Remove-Item Env:KURTSHAPE_STARTUP_BASELINE -ErrorAction SilentlyContinue }
$reviewMacro=@{copy='general-actions-validation.FCMacro';lifecycle='sketch-lifecycle-validation.FCMacro';recovery='review-recovery-crash.FCMacro';interaction='gui-review-validation.FCMacro';startup='gui-startup-diagnostics.FCMacro';baseline='gui-startup-diagnostics.FCMacro';step='step-import-gui-validation.FCMacro';assembly='assembly-gui-validation.FCMacro'}[$Scenario]
$reviewExe=Join-Path $reviewRoot 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\freecad.exe'
$reviewArgs=@('-u',('"'+(Join-Path $reviewSession 'user-data\user.cfg')+'"'),'-s',('"'+(Join-Path $reviewSession 'user-data\system.cfg')+'"'),('--log-file'),('"'+(Join-Path $reviewSession 'freecad.log')+'"'),('"'+(Join-Path $reviewRoot "tools\$reviewMacro")+'"'))
$reviewProcess=Start-Process -FilePath $reviewExe -ArgumentList $reviewArgs -WorkingDirectory $reviewRoot -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $reviewProcess -Executable $reviewExe -Arguments $reviewArgs
$reviewProcess | Select-Object Id
$reviewReports=@{copy='general-actions-gui-result.json';lifecycle='sketch-lifecycle-result.json';recovery='review-followup\recovery-crash.json';interaction='review-followup\gui-review.json';step='step-import\gui-test-result.json';assembly='assembly-workflow\gui-test-result.json'}
if ($reviewReports.ContainsKey($Scenario)) { Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory) $reviewReports[$Scenario])) }
else { Write-Output ('Startup log: ' + (Join-Path $reviewSession 'freecad.log')) }
