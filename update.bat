@echo off
setlocal EnableDelayedExpansion

echo ============================================
echo  Battery Monitor — Update ^& Restart
echo ============================================
echo.

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "PID_FILE=%PROJECT_DIR%\tray_app.pid"
set "SCRIPT=%PROJECT_DIR%\tray_app.py"

:: ── 1. Kill the running instance ─────────────────────────────────────────────
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    echo Stopping process PID !OLD_PID! ...
    taskkill /PID !OLD_PID! /F >nul 2>&1
    del /f "%PID_FILE%" >nul 2>&1
    :: Give it a moment to fully exit
    timeout /t 2 /nobreak >nul
) else (
    echo No running instance found, skipping kill step.
)

:: ── 2. Pull latest code ───────────────────────────────────────────────────────
echo.
echo Pulling latest code from git...
cd /d "%PROJECT_DIR%"
git pull
if errorlevel 1 (
    echo WARNING: git pull failed. Restarting with existing code.
)

:: ── 3. Install/update dependencies ───────────────────────────────────────────
echo.
echo Updating dependencies...
pip install -q -r "%PROJECT_DIR%\requirements.txt"

:: ── 4. Find pythonw ───────────────────────────────────────────────────────────
set "PYTHONW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if not defined PYTHONW set "PYTHONW=%%i"
)

if not defined PYTHONW (
    echo ERROR: pythonw.exe not found.
    pause
    exit /b 1
)

:: ── 5. Restart the tray app ───────────────────────────────────────────────────
echo.
echo Starting Battery Monitor...
start "" "!PYTHONW!" "!SCRIPT!"

echo Done. Check the system tray.
echo.
timeout /t 3 /nobreak >nul
