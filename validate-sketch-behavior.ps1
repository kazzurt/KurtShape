param([switch]$FreshProfile, [switch]$WriteEvidence)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'tools\validation-session.ps1')
$sketchRoot=$PSScriptRoot
$sketchSession=Join-Path $sketchRoot $(if ($FreshProfile) {"runtime/sketch-behavior-fresh-validation-$([DateTime]::Now.ToString('yyyyMMdd-HHmmss'))"} else {'runtime/sketch-behavior-validation'})
Initialize-KurtShapeValidationEnvironment -Root $sketchRoot -Session $sketchSession -WriteEvidence:$WriteEvidence
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$sketchExe=Join-Path $sketchRoot 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/freecad.exe'
$sketchArguments=@('-u',('"'+(Join-Path $sketchSession 'user-data/user.cfg')+'"'),'-s',('"'+(Join-Path $sketchSession 'user-data/system.cfg')+'"'),'--log-file',('"'+(Join-Path $sketchSession 'freecad.log')+'"'),('"'+(Join-Path $sketchRoot 'tools/sketch-behavior-validation.FCMacro')+'"'))
$sketchProcess=Start-Process -FilePath $sketchExe -ArgumentList $sketchArguments -WorkingDirectory $sketchRoot -WindowStyle Hidden -PassThru
Register-KurtShapeValidationProcess -Process $sketchProcess -Executable $sketchExe -Arguments $sketchArguments
$sketchProcess | Select-Object Id
Write-Output ('Report: ' + (Join-Path (Get-KurtShapeEvidenceDirectory 'sketch-behavior') 'native-behavior.json'))
