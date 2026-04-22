@echo off
setlocal EnableDelayedExpansion

echo ============================================
echo  Battery Monitor — Install startup task
echo ============================================
echo.

:: Resolve the directory of this script (project root)
set "PROJECT_DIR=%~dp0"
:: Remove trailing backslash
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "SCRIPT=%PROJECT_DIR%\tray_app.py"

:: Find pythonw.exe (runs Python without a console window)
set "PYTHONW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if not defined PYTHONW set "PYTHONW=%%i"
)

if not defined PYTHONW (
    echo ERROR: pythonw.exe not found.
    echo Make sure Python is installed and added to PATH.
    pause
    exit /b 1
)

echo Python  : !PYTHONW!
echo Script  : !SCRIPT!
echo.

:: Register the Task Scheduler task
::   /sc ONLOGON  — trigger on user logon
::   /delay       — wait 30 s after logon so the desktop is ready
::   /f           — overwrite if it already exists
schtasks /create ^
    /tn "BatteryMonitor" ^
    /sc ONLOGON ^
    /tr "\"!PYTHONW!\" \"!SCRIPT!\"" ^
    /delay 0000:30 ^
    /f >nul

if errorlevel 1 (
    echo ERROR: Failed to create scheduled task.
    pause
    exit /b 1
)

echo Task "BatteryMonitor" registered successfully.
echo Battery Monitor will start automatically on your next login.
echo.
echo To start it right now, run:  update.bat
echo To remove the startup task:  uninstall.bat
echo.
pause
