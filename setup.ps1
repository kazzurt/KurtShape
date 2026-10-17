# Windows PowerShell 5.1 and PowerShell 7. No administrator privileges required.
param(
    [string]$RuntimeRoot = (Join-Path $PSScriptRoot 'runtime'),
    [switch]$RepairRuntime
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'install-runtime.ps1') -RuntimeRoot $RuntimeRoot -Repair:$RepairRuntime
& (Join-Path $PSScriptRoot 'tools\check-install.ps1') -RuntimeRoot $RuntimeRoot
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'projects') | Out-Null
Write-Output 'Setup passed. Double-click KurtShape.cmd to start the app.'
if ([IO.Path]::GetFullPath($RuntimeRoot) -ne (Join-Path $PSScriptRoot 'runtime')) {
    Write-Output ('For this custom engine location use: .\launch-kurtshape.ps1 -RuntimeRoot "' + [IO.Path]::GetFullPath($RuntimeRoot) + '"')
}
