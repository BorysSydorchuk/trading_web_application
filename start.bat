@echo off
rem Trading Journal: one-click start on Windows. See README.md.
setlocal
cd /d "%~dp0"
rem UTF-8 console for the Ukrainian messages; the previous code page is restored at the end.
for /f "tokens=2 delims=:." %%a in ('chcp') do set "OLDCP=%%a"
chcp 65001 >nul

where python >nul 2>nul
if errorlevel 1 (
    echo [start] Не знайдено Python 3.12 у PATH. Спершу встановіть його, див. README.md ^(Prerequisites^).
    set "EXITCODE=1"
    goto :failed
)

python scripts\dev.py %*
set "EXITCODE=%ERRORLEVEL%"
if "%EXITCODE%"=="0" goto :done

echo.
echo [start] Зупинено з помилкою ^(код виходу %EXITCODE%^). Див. повідомлення вище та logs\.
:failed
pause
:done
if defined OLDCP chcp %OLDCP% >nul
endlocal & exit /b %EXITCODE%
