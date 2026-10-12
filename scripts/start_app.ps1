param([int]$Port = 8501)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $Root "runtime") -Force | Out-Null
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Install requirements into .venv first." }
if (-not (Test-Path -LiteralPath (Join-Path $Root "frontend/dist/index.html"))) {
    throw "Build the frontend first: npm ci --prefix frontend; npm run build --prefix frontend"
}
while (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { $Port++ }
$Arguments = @("-X", "utf8", "-m", "uvicorn", "src.api.app:app",
    "--port", "$Port", "--host", "127.0.0.1", "--workers", "1")
$Process = Start-Process -FilePath $Python -ArgumentList $Arguments -WindowStyle Hidden -PassThru `
    -WorkingDirectory $Root `
    -RedirectStandardOutput (Join-Path $Root "runtime\app.stdout.log") `
    -RedirectStandardError (Join-Path $Root "runtime\app.stderr.log")
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if ($Process.HasExited) { throw "Application exited. See runtime\app.stderr.log" }
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2 | Out-Null
        Write-Host "Spark Guard: http://127.0.0.1:$Port (PID $($Process.Id))"
        exit 0
    } catch {}
}
throw "Application did not become ready."
