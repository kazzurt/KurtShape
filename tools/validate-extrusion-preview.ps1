param([switch]$WriteEvidence)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'validation-session.ps1')
$previewProject = Split-Path -Parent $PSScriptRoot
$previewRuntime = Join-Path $previewProject 'runtime\ui-refinement-preview'
Initialize-KurtShapeValidationEnvironment -Root $previewProject -Session $previewRuntime -WriteEvidence:$WriteEvidence
$previewBin = Join-Path $previewProject 'runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin'
Invoke-KurtShapeValidationPython -Executable (Join-Path $previewBin 'python.exe') -Arguments @('-B','-m','unittest','discover','-s',(Join-Path $previewProject 'tests'),'-p','test_extrusion_preview.py','-v') -Name 'native-extrusion-preview'
$previewArgs = @('-u', ('"' + (Join-Path $previewRuntime 'user-data\user.cfg') + '"'),
                 '-s', ('"' + (Join-Path $previewRuntime 'user-data\system.cfg') + '"'),
                 '--log-file', ('"' + (Join-Path $previewRuntime 'freecad.log') + '"'),
                 ('"' + (Join-Path $PSScriptRoot 'extrusion-preview-validation.FCMacro') + '"'))
$previewProcess = Start-Process -FilePath (Join-Path $previewBin 'freecad.exe') -ArgumentList $previewArgs -WorkingDirectory $previewProject -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $previewProcess -Executable (Join-Path $previewBin 'freecad.exe') -Arguments $previewArgs
Write-Output ('Hidden preview validation PID: ' + $previewProcess.Id)
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'ui-refinement-preview') 'gui-result.json'))
