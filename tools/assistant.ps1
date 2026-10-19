param(
    [string]$RequestFile,
    [ValidateSet('capabilities','list_documents')][string]$Operation = 'capabilities',
    [string]$Session,
    [string]$RuntimeRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime')
)
$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path ([IO.Path]::GetFullPath($RuntimeRoot)) 'freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first.' }
$clientArgs = @('-B', (Join-Path $PSScriptRoot 'assistant_client.py'))
if (-not $Session) {
    $sessionBase = if ($env:KURTSHAPE_SESSION_DIR) { $env:KURTSHAPE_SESSION_DIR } else { Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime' }
    $Session = Join-Path $sessionBase 'assistant-session.json'
}
if (-not (Test-Path -LiteralPath $Session -PathType Leaf)) { throw 'No assistant session found. Launch KurtShape.cmd from this checkout, or pass -Session for your running instance.' }
$clientArgs += @('--session', [IO.Path]::GetFullPath($Session))
if ($RequestFile) {
    $clientArgs += @('--request-file', [IO.Path]::GetFullPath($RequestFile))
} else {
    # Request files avoid Windows PowerShell 5.1 native JSON argument quoting.
    $RequestFile = Join-Path $PSScriptRoot ('..\examples\' + $Operation + '-request.json')
    $clientArgs += @('--request-file', $RequestFile)
}
# The client writes its request identity to stderr; under Windows PowerShell 5.1 with 'Stop' a native
# command's stderr can become a terminating NativeCommandError before the exit code is read.
$ErrorActionPreference = 'Continue'
& $pythonPath @clientArgs
$code = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
switch ($code) {
    0 { }
    1 { throw 'Bridge request was rejected or failed; read the response above. An identical replay returns the same answer.' }
    2 { throw 'Bridge request is still pending: reconcile with its request_id (assistant_client.py --reconcile --request-id ...); do not resend with a new request_id.' }
    3 { throw 'Bridge request outcome is unknown: inspect before acting, reconcile with its request_id; do not resend with a new request_id.' }
    4 { throw 'Bridge request is safe to retry: inspect first, and give a mutation a new request_id.' }
    64 { throw 'The client was called incorrectly (usage error); nothing was sent.' }
    default { throw ('Bridge request failed with exit code ' + $code + '; read the response above. Do not blindly retry a mutation.') }
}
