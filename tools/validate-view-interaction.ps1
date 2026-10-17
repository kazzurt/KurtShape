param(
    [ValidateRange(1,7200)][int]$TimeoutSeconds = 180,
    [switch]$WriteEvidence
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'run_gui_recipe.ps1') -Recipe view-interaction -TimeoutSeconds $TimeoutSeconds -WriteEvidence:$WriteEvidence
