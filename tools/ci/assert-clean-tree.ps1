$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
    $status = @(& git status --porcelain --ignored=matching --untracked-files=normal)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect CI repository status.' }
    $unexpected = @($status | Where-Object { $_ -notin @('!! runtime/', '!! projects/') })
    # Setup creates this empty first-save destination. It must not leave models.
    $projects = Join-Path $root 'projects'
    if ((Test-Path -LiteralPath $projects) -and @(Get-ChildItem -LiteralPath $projects -Force).Count) {
        throw 'Fresh CI setup must leave projects/ empty.'
    }
    if ($unexpected.Count) {
        $unexpected | Write-Host
        throw 'Fresh CI checkout changed; only ignored runtime/ and empty projects/ are allowed.'
    }
    $status | Write-Output
} finally { Pop-Location }
