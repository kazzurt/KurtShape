$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
    $status = @(& git status --porcelain --ignored=matching --untracked-files=normal)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect CI repository status.' }
    $unexpected = @($status | Where-Object { $_ -ne '!! runtime/' })
    if ($unexpected.Count) {
        $unexpected | Write-Host
        throw 'Fresh CI checkout changed; only ignored runtime/ is allowed.'
    }
    $status | Write-Output
} finally { Pop-Location }
