param(
    [switch]$NoFrontend
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RuntimeDir = Join-Path $Root ".runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$BackendPort = 8010

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null

function Stop-PortProcess {
    param([int[]]$Ports)

    $connections = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

Stop-PortProcess -Ports @(8000, $BackendPort, 5173, 5174, 5175, 5176)
Start-Sleep -Seconds 1

$AiosqliteInstalled = python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('aiosqlite') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing missing aiosqlite dependency..."
    python -m pip install aiosqlite
}

$BackendOut = Join-Path $LogDir "backend.out.log"
$BackendErr = Join-Path $LogDir "backend.err.log"
$Backend = Start-Process `
    -FilePath "python" `
    -ArgumentList "-m uvicorn app.main:app --app-dir `"$BackendDir`" --reload --reload-dir `"$BackendDir`" --host 0.0.0.0 --port $BackendPort" `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $BackendOut `
    -RedirectStandardError $BackendErr `
    -PassThru
Set-Content -Path (Join-Path $RuntimeDir "backend.pid") -Value $Backend.Id

if (-not $NoFrontend) {
    $FrontendOut = Join-Path $LogDir "frontend.out.log"
    $FrontendErr = Join-Path $LogDir "frontend.err.log"
    $FrontendCommand = "`$env:VITE_API_BASE_URL='http://localhost:$BackendPort'; cd '$FrontendDir'; npm run dev -- --host 0.0.0.0"
    $Frontend = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $FrontendCommand) `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendOut `
        -RedirectStandardError $FrontendErr `
        -PassThru
    Set-Content -Path (Join-Path $RuntimeDir "frontend.pid") -Value $Frontend.Id
}

Start-Sleep -Seconds 3

Write-Host "Backend:  http://localhost:$BackendPort/docs"
if (-not $NoFrontend) {
    Write-Host "Frontend: http://localhost:5173"
    Write-Host "Delivery: http://localhost:5173"
}
Write-Host "Logs:     $LogDir"
