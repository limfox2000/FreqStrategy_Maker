$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$apiDir = Join-Path $PSScriptRoot "api"
$webDir = Join-Path $PSScriptRoot "web"

Write-Host "Starting backend: http://127.0.0.1:8000"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$apiDir'; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
)

Write-Host "Starting frontend: http://127.0.0.1:5173"
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$webDir'; npm run dev -- --host 127.0.0.1 --port 5173"
)

Write-Host "Studio boot command dispatched."

