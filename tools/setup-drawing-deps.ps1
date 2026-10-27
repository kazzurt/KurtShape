# Installs the 2D drawing dependency (kurtshape.drawing) into runtime\vendor\drawing-py311.
#
# ezdxf (MIT) drafts the DXF; olefile (BSD) reads the template logo. Both are pure Python and
# pinned. --no-deps keeps pip away from the FreeCAD runtime's own numpy, matplotlib, fontTools,
# pyparsing and Pillow, which ezdxf uses as they are; the check below confirms they import.
param(
    [string]$RuntimeRoot = (Join-Path (Split-Path -Parent $PSScriptRoot) 'runtime'),
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
$runtime = [IO.Path]::GetFullPath($RuntimeRoot)
$python = Join-Path $runtime 'freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.ps1 to install the pinned runtime first.' }
$target = Join-Path $runtime 'vendor\drawing-py311'
$packages = @('ezdxf==1.4.5', 'olefile==0.47')

if ($Force -and (Test-Path -LiteralPath $target)) { Remove-Item -LiteralPath $target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $target | Out-Null
& $python -m pip install --disable-pip-version-check --no-deps --upgrade --target $target @packages
if ($LASTEXITCODE -ne 0) { throw "pip install failed ($LASTEXITCODE)" }

# Import check in the windowless interpreter, output captured to files (no console window).
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
$work = Join-Path ([IO.Path]::GetTempPath()) ('kurtshape-drawing-deps-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $work | Out-Null
$script = Join-Path $work 'check.py'
@"
import sys
sys.path.append(r'$target')
import ezdxf, olefile, numpy, matplotlib, fontTools, pyparsing, typing_extensions, PIL
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from ezdxf.npshapes import to_matplotlib_path
from ezdxf.addons.drawing.pipeline import RenderPipeline2d
print('ezdxf', ezdxf.__version__, '| olefile', olefile.__version__, '| numpy', numpy.__version__,
      '| matplotlib', matplotlib.__version__, '| fontTools', fontTools.version, '| PIL', PIL.__version__)
"@ | Set-Content -LiteralPath $script -Encoding utf8
$p = Start-Process -FilePath $pythonw -ArgumentList '-I', "`"$script`"" -RedirectStandardOutput (Join-Path $work 'out.txt') `
    -RedirectStandardError (Join-Path $work 'err.txt') -Wait -NoNewWindow -PassThru
Get-Content (Join-Path $work 'out.txt')
if ($p.ExitCode -ne 0) {
    Get-Content (Join-Path $work 'err.txt')
    throw 'The drawing dependency does not import in the bundled runtime.'
}
Remove-Item -LiteralPath $work -Recurse -Force
Write-Output ('Drawing dependency ready: ' + $target)
