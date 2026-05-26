param(
    [switch]$NoFrontend,
    [int]$BackendPort = 8010,
    [int]$FrontendPort = 5173,
    [switch]$BackendReload
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeDir = Join-Path $Root ".runtime"
$LogDir = Join-Path $RuntimeDir "logs"
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

New-Item -ItemType Directory -Force -Path $RuntimeDir, $LogDir | Out-Null

function Get-CommandLine {
    param([int]$ProcessId)

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($process) {
        return [string]$process.CommandLine
    }
    return ""
}

function Test-WorkspaceProcess {
    param([int]$ProcessId)

    $commandLine = Get-CommandLine -ProcessId $ProcessId
    return $commandLine.IndexOf($Root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Stop-FromPidFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    $rawPid = Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue | Select-Object -First 1
    $parsedPid = 0
    if ([int]::TryParse([string]$rawPid, [ref]$parsedPid)) {
        Stop-Process -Id $parsedPid -Force -ErrorAction SilentlyContinue
    }
}

function Stop-WorkspaceListeners {
    param([int[]]$Ports)

    $connections = Get-NetTCPConnection -LocalPort $Ports -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        if (Test-WorkspaceProcess -ProcessId $connection.OwningProcess) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-PortFree {
    param([int]$Port)

    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return -not $connection
}

function Get-AvailablePort {
    param(
        [int]$PreferredPort,
        [int]$Attempts = 30
    )

    for ($offset = 0; $offset -lt $Attempts; $offset++) {
        $candidate = $PreferredPort + $offset
        if (Test-PortFree -Port $candidate) {
            return $candidate
        }
    }

    throw "No available port found from $PreferredPort to $($PreferredPort + $Attempts - 1)."
}

Stop-FromPidFile -Path (Join-Path $RuntimeDir "backend.pid")
Stop-FromPidFile -Path (Join-Path $RuntimeDir "frontend.pid")
Stop-WorkspaceListeners -Ports @($BackendPort, $FrontendPort, ($FrontendPort + 1), ($FrontendPort + 2), ($FrontendPort + 3))
Start-Sleep -Seconds 1

$BackendPort = Get-AvailablePort -PreferredPort $BackendPort
$FrontendPort = Get-AvailablePort -PreferredPort $FrontendPort

$aiosqliteInstalled = python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('aiosqlite') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing missing aiosqlite dependency..."
    python -m pip install aiosqlite
}

if (-not $NoFrontend) {
    $frontendBinDir = Join-Path $FrontendDir "node_modules\.bin"
    $viteCommands = @("vite.cmd", "vite.ps1", "vite")
    $viteAvailable = $false
    foreach ($viteCommand in $viteCommands) {
        if (Test-Path -LiteralPath (Join-Path $frontendBinDir $viteCommand)) {
            $viteAvailable = $true
            break
        }
    }

    if (-not $viteAvailable) {
        Write-Host "Installing missing frontend dependencies..."
        Push-Location -LiteralPath $FrontendDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    }
}

$backendOut = Join-Path $LogDir "backend.out.log"
$backendErr = Join-Path $LogDir "backend.err.log"
$backendArgs = "-m uvicorn app.main:app --app-dir `"$BackendDir`" --host 127.0.0.1 --port $BackendPort"
if ($BackendReload) {
    $backendArgs = "$backendArgs --reload --reload-dir `"$BackendDir`""
}

$backend = Start-Process `
    -FilePath "python" `
    -ArgumentList $backendArgs `
    -WorkingDirectory $BackendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $backendOut `
    -RedirectStandardError $backendErr `
    -PassThru
Set-Content -Path (Join-Path $RuntimeDir "backend.pid") -Value $backend.Id

$healthUrl = "http://127.0.0.1:$BackendPort/health"
$backendReady = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) {
            $backendReady = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $backendReady) {
    throw "Backend did not become healthy at $healthUrl. See logs: $LogDir"
}

if (-not $NoFrontend) {
    $frontendOut = Join-Path $LogDir "frontend.out.log"
    $frontendErr = Join-Path $LogDir "frontend.err.log"
    $frontendCommand = "`$env:VITE_API_BASE_URL='http://127.0.0.1:$BackendPort'; Set-Location -LiteralPath '$FrontendDir'; npm run dev -- --host 127.0.0.1 --port $FrontendPort --strictPort"
    $frontend = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $frontendCommand) `
        -WorkingDirectory $FrontendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOut `
        -RedirectStandardError $frontendErr `
        -PassThru
    Set-Content -Path (Join-Path $RuntimeDir "frontend.pid") -Value $frontend.Id
}

$ports = @{
    backend = $BackendPort
    frontend = if ($NoFrontend) { $null } else { $FrontendPort }
}
$ports | ConvertTo-Json | Set-Content -Path (Join-Path $RuntimeDir "ports.json")

Write-Host "Backend:  http://127.0.0.1:$BackendPort/docs"
if (-not $NoFrontend) {
    Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
    Write-Host "Delivery: http://127.0.0.1:$FrontendPort"
}
Write-Host "Logs:     $LogDir"
