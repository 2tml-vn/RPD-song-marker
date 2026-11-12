@echo off
REM ============================================================
REM  One-time setup: register the jrpd:// protocol handler so the
REM  browser panel's Start button can launch the pipeline.
REM
REM  Run this ONCE (double-click from Explorer is fine).
REM  It writes to HKEY_CURRENT_USER only - no admin needed.
REM
REM  To undo:  reg delete "HKCU\Software\Classes\jrpd" /f
REM ============================================================

setlocal

REM Resolve the absolute python.exe that "python" resolves to
for /f "usebackq delims=" %%P in (`python -c "import sys; print(sys.executable)"`) do set "PYEXE=%%P"
if not defined PYEXE (
    echo [ERROR] Python not found on PATH. Run this from an environment where "python" works.
    pause
    exit /b 1
)

set "SCRIPT=%~dp0jrpd_protocol.py"
if not exist "%SCRIPT%" (
    echo [ERROR] jrpd_protocol.py not found next to this batch file: %SCRIPT%
    pause
    exit /b 1
)

echo Registering: jrpd:// -^> "%PYEXE%" "%SCRIPT%"

reg add "HKCU\Software\Classes\jrpd" /ve /d "URL:JRPD Protocol" /f >nul
reg add "HKCU\Software\Classes\jrpd" /v "URL Protocol" /f >nul
reg add "HKCU\Software\Classes\jrpd\DefaultIcon" /ve /d "%PYEXE%,0" /f >nul
reg add "HKCU\Software\Classes\jrpd\shell\open\command" /ve /d "\"%PYEXE%\" \"%SCRIPT%\" \"%%1\"" /f >nul

echo.
echo Done. The panel's Start button will now open jrpd:// links.
echo The first time, the browser asks for permission - choose "Always allow".
echo.
echo To undo: reg delete "HKCU\Software\Classes\jrpd" /f
echo.
pause
