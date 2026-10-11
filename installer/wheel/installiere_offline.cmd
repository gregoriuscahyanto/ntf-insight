@echo off
setlocal
echo NTF Insight - Offline-Installation
echo.
powershell.exe -NoLogo -NoProfile -File "%~dp0installiere_offline.ps1"
if errorlevel 1 (
    echo.
    echo Die Installation ist fehlgeschlagen. Bitte die Meldung oben lesen.
    pause
    exit /b 1
)
echo.
echo Die Installation ist abgeschlossen.
pause
