@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "START_SCRIPT=%ROOT_DIR%studio\start_mvp.ps1"

if not exist "%START_SCRIPT%" (
    echo [ERROR] Can not find startup script:
    echo %START_SCRIPT%
    exit /b 1
)

where powershell >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell is not available in PATH.
    exit /b 1
)

echo Launching Freqtrade Strategy Studio...
powershell -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%"

if errorlevel 1 (
    echo [ERROR] Startup failed.
    exit /b 1
)

echo Startup command dispatched. Backend: http://127.0.0.1:8000  Frontend: http://127.0.0.1:5173
exit /b 0
