param([switch]$FreshProfile)
$ErrorActionPreference='Stop'
$sketchRoot=$PSScriptRoot
$sketchSession=Join-Path $sketchRoot $(if ($FreshProfile) {"runtime/sketch-behavior-fresh-validation-$([DateTime]::Now.ToString('yyyyMMdd-HHmmss'))"} else {'runtime/sketch-behavior-validation'})
foreach ($folder in @('temporary','user-data','appdata','localappdata')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $sketchSession $folder) | Out-Null
}
$env:KURTSHAPE_ROOT=$sketchRoot
$env:KURTSHAPE_SESSION_DIR=$sketchSession
$env:FREECAD_USER_HOME=Join-Path $sketchSession 'user-data'
$env:TEMP=Join-Path $sketchSession 'temporary'
$env:TMP=$env:TEMP
$env:APPDATA=Join-Path $sketchSession 'appdata'
$env:LOCALAPPDATA=Join-Path $sketchSession 'localappdata'
$env:PYTHONDONTWRITEBYTECODE='1'
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$sketchExe=Join-Path $sketchRoot 'runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/freecad.exe'
$sketchArguments=@('-u',('"'+(Join-Path $sketchSession 'user-data/user.cfg')+'"'),'-s',('"'+(Join-Path $sketchSession 'user-data/system.cfg')+'"'),'--log-file',('"'+(Join-Path $sketchSession 'freecad.log')+'"'),('"'+(Join-Path $sketchRoot 'tools/sketch-behavior-validation.FCMacro')+'"'))
Start-Process -FilePath $sketchExe -ArgumentList $sketchArguments -WorkingDirectory $sketchRoot -WindowStyle Hidden -PassThru | Select-Object Id
