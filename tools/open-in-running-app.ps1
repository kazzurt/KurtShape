# Hands a project to the KurtShape already running for a session folder (src/kurtshape/open_handoff.py).
# Prints True when that app took the file and False when no KurtShape runs for the session. Throws when
# the running app stays busy or refuses the file, so the caller does not start a second KurtShape.
param(
    [string]$Session,
    [string]$FilePath,
    [int]$ConnectMilliseconds = 1000,
    [int]$ReplySeconds = 60
)
$ErrorActionPreference = 'Stop'
if (-not $Session -or -not $FilePath) { throw 'Pass -Session and -FilePath.' }
# Same name as open_handoff.pipe_name: normalized, lower-case session path.
$key = [IO.Path]::GetFullPath($Session).TrimEnd('\', '/').ToLowerInvariant()
$sha = [Security.Cryptography.SHA256]::Create()
try { $digest = $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($key)) } finally { $sha.Dispose() }
$pipeName = 'KurtShape-' + (-join ($digest | ForEach-Object { $_.ToString('x2') })).Substring(0, 24)
$pipe = New-Object IO.Pipes.NamedPipeClientStream('.', $pipeName, [IO.Pipes.PipeDirection]::InOut, [IO.Pipes.PipeOptions]::Asynchronous)
try {
    try { $pipe.Connect($ConnectMilliseconds) }
    catch [TimeoutException] { return $false }
    $utf8 = New-Object Text.UTF8Encoding($false)
    $reader = New-Object IO.StreamReader($pipe, $utf8)
    $writer = New-Object IO.StreamWriter($pipe, $utf8)
    $writer.NewLine = "`n"
    $writer.AutoFlush = $true
    function Read-Reply {
        $line = $reader.ReadLineAsync()
        if (-not $line.Wait([TimeSpan]::FromSeconds($ReplySeconds))) {
            throw ('KurtShape is busy and did not take ' + $FilePath + '. Try again when it responds.')
        }
        if ($null -eq $line.Result) { throw 'KurtShape closed the connection before answering.' }
        return ($line.Result | ConvertFrom-Json)
    }
    $hello = Read-Reply
    if ($hello.app -ne 'KurtShape') { return $false }
    # This launch came from the user's double-click, so it may let KurtShape take the foreground.
    try {
        Add-Type -Namespace KurtShapeHandoff -Name Window -MemberDefinition '[DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(int processId);'
        $null = [KurtShapeHandoff.Window]::AllowSetForegroundWindow([int]$hello.pid)
    } catch {}
    $writer.WriteLine((@{ open = [IO.Path]::GetFullPath($FilePath) } | ConvertTo-Json -Compress))
    $reply = Read-Reply
    if (-not $reply.ok) { throw ('KurtShape did not open ' + $FilePath + ': ' + $reply.message) }
    return $true
} finally {
    $pipe.Dispose()
}
