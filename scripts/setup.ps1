# CV-Scope setup for Windows (PowerShell).
# Creates .venv, installs the backend (with GPU PyTorch when an NVIDIA driver is present),
# installs the frontend, downloads sample videos and applies database migrations.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-Cpu] [-NoSamples] [-Python py-launcher-version]

param(
    [switch]$Cpu,
    [switch]$NoSamples,
    [string]$Python = "3.11"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }

Step "Python virtual environment (.venv)"
if (-not (Test-Path ".venv")) {
    $py = $null
    try { & py -$Python --version | Out-Null; $py = "py -$Python" } catch {}
    if (-not $py) { $py = "python" }
    Invoke-Expression "$py -m venv .venv"
}
$pip = ".\.venv\Scripts\python.exe -m pip"
Invoke-Expression "$pip install --upgrade pip" | Out-Null

Step "PyTorch"
$hasNvidia = $false
if (-not $Cpu) {
    try { & nvidia-smi -L 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { $hasNvidia = $true } } catch {}
}
if ($hasNvidia) {
    Write-Host "NVIDIA GPU detected: installing CUDA 12.6 build"
    Invoke-Expression "$pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126"
} else {
    Write-Host "Installing CPU build"
    Invoke-Expression "$pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu"
}

Step "Backend package"
Invoke-Expression "$pip install -e `"backend[ultralytics,onnx-cpu,export,dev]`""

Step "Frontend dependencies"
Push-Location frontend
npm install --no-audit --no-fund
Pop-Location

Step "Database"
& .\.venv\Scripts\python.exe -m pathscope.cli migrate

if (-not $NoSamples) {
    Step "Sample videos (CC-BY-4.0)"
    & .\.venv\Scripts\python.exe scripts\download_samples.py
}

Step "Hardware summary"
& .\.venv\Scripts\python.exe -m pathscope.cli hardware

Write-Host "`nDone. Start CV-Scope with:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1" -ForegroundColor Green
Write-Host "Then open http://localhost:5173"
