@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation abgeschlossen. Zum Starten Starten.cmd oeffnen.
pause
exit /b 0
:failed
echo Installation fehlgeschlagen. Python 3.11 oder neuer in 64 Bit wird benoetigt.
pause
exit /b 1
