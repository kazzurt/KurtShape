param(
    [string]$OutputPath = (Join-Path (Split-Path -Parent $PSScriptRoot) 'KurtShape.exe'),
    [string]$SourcePath = (Join-Path $PSScriptRoot 'KurtShapeLauncher.cs')
)
$ErrorActionPreference = 'Stop'
$SourcePath = [IO.Path]::GetFullPath($SourcePath)
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    throw ('The Windows .NET Framework C# compiler is missing: ' + $compiler)
}
if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
    throw ('Launcher source is missing: ' + $SourcePath)
}
$outputDirectory = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    throw ('Output directory does not exist: ' + $outputDirectory)
}
& $compiler /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll "/out:$OutputPath" $SourcePath
if ($LASTEXITCODE -ne 0) { throw ('Launcher compilation failed with exit code ' + $LASTEXITCODE) }
Get-Item -LiteralPath $OutputPath
