# Install the built setup silently, check that CV-Scope works, uninstall it.
#
#   powershell -ExecutionPolicy Bypass -File installer\smoke_test.ps1 -Installer installer\build\output\CV-Scope-Setup-Windows-x64.exe
#
# Uses the CPU build of PyTorch, YOLO11n and the sample videos, a private
# folder and port 8499. Checks: Setup's exit code, the files it created, the
# Start-menu shortcut, the launcher starting the server (API and web page), a
# detector benchmark on a sample video, and that Uninstall removes the
# application but keeps the data. The release workflow runs it on a clean runner.

param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$Work = (Join-Path ([IO.Path]::GetTempPath()) "cvscope-smoke"),
    [int]$Port = 8499
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Installer = (Resolve-Path $Installer).Path
$app = Join-Path $Work "app"
$data = Join-Path $Work "data"
$logs = Join-Path $Work "logs"
if (Test-Path "$app\unins000.exe") {  # left over by an interrupted run
    Start-Process -FilePath "$app\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
    for ($i = 0; $i -lt 30 -and (Test-Path "$app\.venv"); $i++) { Start-Sleep -Seconds 1 }
}
if (Test-Path $Work) { Remove-Item -Recurse -Force $Work }
New-Item -ItemType Directory -Force $logs | Out-Null

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Check($ok, $msg) { if (-not $ok) { throw "FAILED: $msg" }; Write-Host "ok  $msg" }
function Status() {
    try { return Invoke-RestMethod -TimeoutSec 3 "http://127.0.0.1:$Port/api/system/status" } catch { return $null }
}

Step "Install (silent, CPU, YOLO11n, samples)"
$t0 = Get-Date
$p = Start-Process -FilePath $Installer -Wait -PassThru -ArgumentList @(
    "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/TORCH=cpu",
    "/DIR=`"$app`"", "/DATADIR=`"$data`"", "/COMPONENTS=`"detectors\yolo11n,samples`"", "/TASKS=`"`"",
    "/LOG=`"$logs\setup.log`"")
Write-Host ("Setup finished with exit code {0} after {1:N0} s" -f $p.ExitCode, ((Get-Date) - $t0).TotalSeconds)
if (Test-Path "$app\logs\install.log") { Copy-Item "$app\logs\install.log" $logs }
Check ($p.ExitCode -eq 0) "Setup exit code 0 (10 = core install failed, 11 = optional downloads failed)"
Check (Test-Path "$app\.venv\Scripts\pythonw.exe") "virtual environment created"
Check (Test-Path "$data\pathscope.db") "database created in the chosen data folder"
Check (Test-Path "$data\models\yolo11n.pt") "YOLO11n downloaded"
Check (Test-Path "$app\samples\videos\people-detection.mp4") "sample videos downloaded"
Check (Test-Path "$app\frontend\dist\index.html") "web interface installed"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "CV-Scope.lnk"
Check (Test-Path $shortcut) "Start-menu shortcut created"
$env_ = Get-Content "$app\.env" -Raw
Check ($env_ -match "PATHSCOPE_DATA_DIR='") "data folder written to .env"
$head = [IO.File]::ReadAllBytes("$app\.env") | Select-Object -First 3
Check (-not ($head[0] -eq 0xEF -and $head[1] -eq 0xBB -and $head[2] -eq 0xBF)) ".env has no byte order mark"

$py = "$app\.venv\Scripts\python.exe"
Step "Launcher starts the server"
$launcher = Start-Process -FilePath $py -ArgumentList "-m", "pathscope.launcher", "--console", "--no-browser", "--port", "$Port" `
    -WorkingDirectory $app -PassThru -RedirectStandardOutput "$logs\launcher.out" -RedirectStandardError "$logs\launcher.err"
try {
    $status = $null
    for ($i = 0; $i -lt 180 -and -not $status; $i++) { Start-Sleep -Seconds 1; $status = Status; if ($launcher.HasExited) { break } }
    Check ($null -ne $status) "API answers on port $Port"
    Check ((Resolve-Path $status.data_dir).Path -eq (Resolve-Path $data).Path) "server uses the data folder chosen in Setup"
    $page = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "http://127.0.0.1:$Port/"
    Check ($page.Content -match "<title>CV-Scope</title>") "web interface served at http://127.0.0.1:$Port/"
    $models = Invoke-RestMethod -TimeoutSec 10 "http://127.0.0.1:$Port/api/models"
    $y = @($models.models | Where-Object { $_.id -eq "yolo11n" })[0]
    Check ($y.installed) "the Models page lists YOLO11n as installed"
    $samples = Invoke-RestMethod -TimeoutSec 10 "http://127.0.0.1:$Port/api/videos/samples"
    Check (@($samples).Count -ge 1) "the first-run wizard offers the sample videos"
} finally {
    if (-not $launcher.HasExited) { Stop-Process -Id $launcher.Id -Force }  # like ending it in the Task Manager
}
Start-Sleep -Seconds 3
$gone = $true
for ($i = 0; $i -lt 30 -and (Status); $i++) { Start-Sleep -Seconds 1 }
if (Status) { $gone = $false }
Check $gone "the server stops when the launcher is ended"

Step "Detector benchmark on a sample video"
$bench = & $py -m pathscope.cli benchmark yolo11n --device cpu --video "$app\samples\videos\people-detection.mp4" 2>&1 | Out-String
$bench | Set-Content "$logs\benchmark.json"
Check ($LASTEXITCODE -eq 0) "cvscope benchmark yolo11n runs (PyTorch, Ultralytics and OpenCV work)"

Step "Uninstall (silent: keeps the data)"
$u = Start-Process -FilePath "$app\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$logs\uninstall.log`"" -Wait -PassThru
Check ($u.ExitCode -eq 0) "Uninstall exit code 0"
for ($i = 0; $i -lt 20 -and (Test-Path "$app\.venv"); $i++) { Start-Sleep -Seconds 1 }  # the uninstaller finishes in a copy of itself
Check (-not (Test-Path "$app\.venv")) "application and Python environment removed"
Check (-not (Test-Path $shortcut)) "Start-menu shortcut removed"
Check (Test-Path "$data\pathscope.db") "data folder kept"
Write-Host "`nSmoke test passed." -ForegroundColor Green
