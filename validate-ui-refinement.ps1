param([ValidateSet('interface','preview','modeling')][string]$Scenario='interface', [switch]$WriteEvidence)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'tools\validation-session.ps1')
$refinementRoot=$PSScriptRoot
$refinementBin=Join-Path $refinementRoot 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin'
$refinementSession=Join-Path $refinementRoot "runtime/ui-refinement-$Scenario-validation"
Initialize-KurtShapeValidationEnvironment -Root $refinementRoot -Session $refinementSession -WriteEvidence:$WriteEvidence
if ($Scenario -eq 'modeling') {
    Invoke-KurtShapeValidationPython -Executable (Join-Path $refinementBin 'python.exe') -Arguments @('-B',(Join-Path $refinementRoot 'tools/validate_modeling_workflows.py')) -Name 'modeling-workflows'
    Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'ui-refinement') 'modeling-workflows.json'))
    exit 0
}
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$refinementMacro=@{interface='ui-refinement-validation.FCMacro';preview='extrusion-preview-validation.FCMacro'}[$Scenario]
$refinementArguments=@('-u',('"'+(Join-Path $refinementSession 'user-data/user.cfg')+'"'),'-s',('"'+(Join-Path $refinementSession 'user-data/system.cfg')+'"'),'--log-file',('"'+(Join-Path $refinementSession 'freecad.log')+'"'),('"'+(Join-Path $refinementRoot "tools/$refinementMacro")+'"'))
$refinementExe=Join-Path $refinementBin 'freecad.exe'
$refinementProcess=Start-Process -FilePath $refinementExe -ArgumentList $refinementArguments -WorkingDirectory $refinementRoot -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $refinementProcess -Executable $refinementExe -Arguments $refinementArguments
$refinementProcess | Select-Object Id
$refinementReport=if ($Scenario -eq 'interface') { 'ui-refinement\gui-refinement.json' } else { 'ui-refinement-preview\gui-result.json' }
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory) $refinementReport))
