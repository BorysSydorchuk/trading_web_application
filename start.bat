@echo off
rem Trading Journal: one-click start on Windows. See README.md.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [start] Python 3.12 not found on PATH. Install it first, see README.md ^(Prerequisites^).
    pause
    exit /b 1
)

python scripts\dev.py %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo [start] Stopped with an error ^(exit code %EXITCODE%^). See the messages above and logs\.
    pause
)
exit /b %EXITCODE%
