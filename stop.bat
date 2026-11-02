@echo off
rem Trading Journal: stop the app started by start.bat or make dev (python scripts\dev.py --stop).
rem Stops only processes of this app; safe to run when nothing is running. See README.md.
setlocal
cd /d "%~dp0"
rem UTF-8 console for the Ukrainian messages; the previous code page is restored at the end.
for /f "tokens=2 delims=:." %%a in ('chcp') do set "OLDCP=%%a"
chcp 65001 >nul

where python >nul 2>nul
if errorlevel 1 (
    echo [stop] Не знайдено Python 3.12 у PATH. Див. README.md ^(Prerequisites^).
    set "EXITCODE=1"
    goto :failed
)

python scripts\dev.py --stop
set "EXITCODE=%ERRORLEVEL%"
if "%EXITCODE%"=="0" goto :done
:failed
pause
:done
if defined OLDCP chcp %OLDCP% >nul
endlocal & exit /b %EXITCODE%
