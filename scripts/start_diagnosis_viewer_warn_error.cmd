@echo off
setlocal
cd /d "%~dp0.."
set "EINGABE=%CD%\data\raw\diagnosis_viewer_warn_error\fins.txt"
set "AUSGABE=%CD%\data\processed\diagnosis_viewer_warn_error\warnings_errors.json"

if not exist "%EINGABE%" (
  if not exist "data\raw\diagnosis_viewer_warn_error" mkdir "data\raw\diagnosis_viewer_warn_error"
  >"%EINGABE%" echo # Eine 17-stellige FIN pro Zeile. Beispielwerte entfernen.
  echo FIN-Datei angelegt: "%EINGABE%"
  echo Bitte echte FINs lokal eintragen, speichern und diese Startdatei erneut ausfuehren.
  echo Die FIN-Datei wird von Git ignoriert.
  pause
  exit /b 2
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3.11 "%~dp0diagnosis_viewer_warn_error.py" --eingabe "%EINGABE%" --ausgabe "%AUSGABE%" %*
) else (
  python "%~dp0diagnosis_viewer_warn_error.py" --eingabe "%EINGABE%" --ausgabe "%AUSGABE%" %*
)
set "CODE=%ERRORLEVEL%"
echo.
echo JSON: "%AUSGABE%"
echo Zum Fortsetzen die CMD-Datei einfach erneut starten.
pause
exit /b %CODE%