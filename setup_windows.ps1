# One-time Windows setup: creates a local .venv, installs dependencies, and verifies the app can start.
# Usage: double-click setup_windows.bat, or run: powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1
$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

$MinMajor = 3
$MinMinor = 10
$VenvDir = Join-Path $PSScriptRoot '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'

function Write-Step($Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }

function Fail($Message) {
    Write-Host "`nSetup failed: $Message" -ForegroundColor Red
    exit 1
}

function Test-Python($Command, $Arguments) {
    try {
        $version = & $Command @Arguments -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) { return $false }
        $parts = $version.Trim().Split('.')
        return ([int]$parts[0] -gt $MinMajor) -or ([int]$parts[0] -eq $MinMajor -and [int]$parts[1] -ge $MinMinor)
    } catch {
        return $false
    }
}

Write-Step "Locating Python $MinMajor.$MinMinor or newer"
$pythonCommand = $null
$pythonArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    if (Test-Python 'py' @('-3')) { $pythonCommand = 'py'; $pythonArgs = @('-3') }
}
if (-not $pythonCommand -and (Get-Command python -ErrorAction SilentlyContinue)) {
    if (Test-Python 'python' @()) { $pythonCommand = 'python' }
}
if (-not $pythonCommand) {
    Fail "Python $MinMajor.$MinMinor+ was not found. Install it from https://www.python.org/downloads/windows/ (keep 'tcl/tk and IDLE' checked), then run this script again."
}
Write-Host "Using: $pythonCommand $($pythonArgs -join ' ')"

Write-Step 'Checking Tkinter (required for the GUI)'
& $pythonCommand @pythonArgs -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "This Python has no Tkinter. Re-run the Python installer, choose Modify, and enable 'tcl/tk and IDLE'."
}

Write-Step 'Creating virtual environment (.venv)'
if ((Test-Path $VenvPython) -and -not (Test-Python $VenvPython @())) {
    Write-Host 'Existing .venv is unusable or outdated; recreating it.'
    Remove-Item -Recurse -Force $VenvDir
}
if (-not (Test-Path $VenvPython)) {
    & $pythonCommand @pythonArgs -m venv $VenvDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $VenvPython)) { Fail 'Could not create the virtual environment.' }
} else {
    Write-Host '.venv already exists.'
}

Write-Step 'Installing dependencies from requirements.txt'
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail 'Could not upgrade pip. Check your internet connection.' }
& $VenvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { Fail 'Dependency installation failed. Check your internet connection and the messages above.' }

Write-Step 'Verifying installation'
$check = @'
import tkinter, exifread, matplotlib, numpy, PIL, pyproj, scipy, shapely, simplekml, tkinterdnd2
from shapely import concave_hull, union_all
import sys
sys.path.insert(0, 'src')
import jpg_boundary_kmz_gui
print('All imports OK')
'@
& $VenvPython -c $check
if ($LASTEXITCODE -ne 0) { Fail 'Installed packages did not import correctly. See the error above.' }

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host 'Launch the app by double-clicking run_jpg_boundary_gui.bat.'
Write-Host 'Note: the optional World Imagery basemap needs an internet connection.'
