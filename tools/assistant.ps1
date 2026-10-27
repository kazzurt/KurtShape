# Send one request to a KurtShape bridge with the bundled Python.
#   .\tools\assistant.ps1                                   # the user's running app (capabilities)
#   .\tools\assistant.ps1 -Hidden -ProjectRoot <folder>      # a hidden agent app: start or reuse, then send
#   .\tools\assistant.ps1 -Hidden -Stop                      # stop the hidden agent app (its folder is kept)
# -Hidden runs a private KurtShape with its own profile and port under runtime\private\<HiddenSession>
# (offscreen, no window, never the user's app or profile). It prints its session file; pass that to
# assistant_client.py --session (or send(..., session_path)) for further requests.
# -PinPerformanceCores / -NoPinPerformanceCores pass through to private-session.ps1 when it starts the hidden app.
param(
    [string]$RequestFile,
    [ValidateSet('capabilities','list_documents')][string]$Operation = 'capabilities',
    [string]$Session,
    [string]$RuntimeRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime'),
    [switch]$Hidden,
    [switch]$Stop,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,23}$')][string]$HiddenSession = 'agent',
    [string[]]$ProjectRoot = @(),
    [switch]$PinPerformanceCores,
    [switch]$NoPinPerformanceCores
)
$ErrorActionPreference = 'Stop'
$privateSession = Join-Path $PSScriptRoot 'private-session.ps1'
if ($Stop) {
    # Only ever stops a hidden agent app this script started; the user's app is never stopped from here.
    if (-not $Hidden) { throw '-Stop applies only with -Hidden (the hidden agent app).' }
    & $privateSession -Session $HiddenSession -Stop
    return
}
$pythonPath = Join-Path ([IO.Path]::GetFullPath($RuntimeRoot)) 'freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup.ps1 first.' }
$clientArgs = @('-B', (Join-Path $PSScriptRoot 'assistant_client.py'))
if ($Hidden) {
    if ($Session) { throw '-Hidden and -Session are exclusive.' }
    & $privateSession -Session $HiddenSession -Ensure -ProjectRoot $ProjectRoot `
        -PinPerformanceCores:$PinPerformanceCores -NoPinPerformanceCores:$NoPinPerformanceCores | Out-Null
    $Session = Join-Path (Split-Path -Parent $PSScriptRoot) ('runtime\private\' + $HiddenSession + '\assistant-session.json')
    Write-Host ('Hidden KurtShape session file: ' + $Session + '  (stop it with -Hidden -Stop)')
} elseif ($ProjectRoot.Count) {
    throw '-ProjectRoot applies only with -Hidden; the user grants folders to their own app via Save.'
} elseif ($PinPerformanceCores -or $NoPinPerformanceCores) {
    throw '-PinPerformanceCores / -NoPinPerformanceCores apply only with -Hidden (they set the hidden app''s affinity when it starts).'
}
if (-not $Session) {
    $sessionBase = if ($env:KURTSHAPE_SESSION_DIR) { $env:KURTSHAPE_SESSION_DIR } else { Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime' }
    $Session = Join-Path $sessionBase 'assistant-session.json'
}
if (-not (Test-Path -LiteralPath $Session -PathType Leaf)) { throw 'No assistant session found. Use -Hidden for a hidden agent app, launch KurtShape.cmd when the user wants to watch, or pass -Session for a running instance.' }
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
