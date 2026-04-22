@echo off
setlocal EnableDelayedExpansion

echo ============================================
echo  Battery Monitor — Uninstall startup task
echo ============================================
echo.

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "PID_FILE=%PROJECT_DIR%\tray_app.pid"

:: Stop running instance
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    echo Stopping process PID !OLD_PID! ...
    taskkill /PID !OLD_PID! /F >nul 2>&1
    del /f "%PID_FILE%" >nul 2>&1
)

:: Remove scheduled task
schtasks /delete /tn "BatteryMonitor" /f >nul 2>&1
if errorlevel 1 (
    echo Task "BatteryMonitor" not found or already removed.
) else (
    echo Task "BatteryMonitor" removed.
)

echo.
echo Battery Monitor will no longer start at login.
pause
