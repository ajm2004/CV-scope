# Start the CV-Scope API and the frontend dev server (Windows).
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# API:      http://127.0.0.1:8420  (docs at /api/docs)
# Frontend: http://localhost:5173  (proxies /api and /ws to the API)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "No .venv found. Run scripts\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

$api = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "pathscope.cli", "serve" -PassThru -NoNewWindow
Start-Sleep -Seconds 2
Push-Location frontend
try {
    npm run dev
} finally {
    Pop-Location
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force }
}
