# Windows-Setup und GitHub Release

## Für Anwender

1. [GitHub Releases öffnen](https://github.com/gregoriuscahyanto/ntf-insight/releases).
2. `NTF-Insight-Setup-<Version>.exe` herunterladen und über einen freigegebenen Weg auf den Windows-64-Bit-Rechner übertragen.
3. Setup per Doppelklick ausführen. Die Installation erfolgt ohne Administratorrechte in das Benutzerprofil.
4. NTF Insight über Startmenü oder Desktop-Verknüpfung öffnen.

Python und eine virtuelle Umgebung sind **nicht** notwendig: PyInstaller bündelt die Python-Laufzeit und die benötigten Pakete; Inno Setup erstellt die Installationsdatei.

Die Datenbank und Originalberichte verbleiben getrennt vom Programm unter `%USERPROFILE%\.ntf-insight\` oder im über `NTF_INSIGHT_DATA_DIR` freigegebenen Speicherort. Deinstallation und App-Updates löschen diese Daten nicht.

**Wichtig:** Das Setup ist bisher nicht durch ein internes Unternehmenszertifikat signiert. Auf verwalteten Firmen-PCs kann eine IT-Freigabe erforderlich sein. Sicherheitsregeln nicht umgehen. Der Release enthält keine realen Fahrzeug- oder Lieferantendaten.

## Für Entwickler: Setup automatisch über GitHub bauen

1. Versionsnummer in `pyproject.toml` auf den gewünschten neuen Wert setzen und nach `main` übernehmen.
2. [Actions → Windows Setup und Release](https://github.com/gregoriuscahyanto/ntf-insight/actions/workflows/release-windows.yml) öffnen.
3. `Run workflow` und Branch `main` wählen.
4. Der Workflow testet die Anwendung, erstellt einen Windows-Installer, führt einen Installations- und GUI-Starttest durch und veröffentlicht einen **Prerelease** mit Setup-Datei und `SHA256SUMS.txt`.

Der Workflow läuft **ausschließlich manuell auf GitHub-gehosteten Windows-Runnern**, nicht auf lokalen Runnern mit vertraulichen Daten. Eine vorhandene Release-Version wird nicht überschrieben. Bei einem fehlgeschlagenen Test wird nichts veröffentlicht.

GitHub Releases erlauben Dateien unter 2 GiB. Größere Setup-Dateien werden im Build zurückgewiesen. Es werden keine GitHub-Actions-Artefakte hochgeladen.

## Lokal bauen (optional)

Auf einem Windows-PC mit installiertem Inno Setup 6, funktionierendem Python 3.11 (64 Bit) und Internetzugang:

**[Python 3.11.9 – Windows-Installer 64 Bit](https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe)** (nur für Entwickler, nicht für App-Anwender).

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]" pyinstaller==6.22.3
.\scripts\baue_windows_setup.ps1 -Python ".\.venv\Scripts\python.exe"
```

Bei bereits aktivierter `.venv` ist auch `python -m pip ...` möglich. **Nicht `py -3.11` verwenden**, wenn dieser Befehl die defekte Actions-Runner-Python-Installation auswählt. Mit `python -c "import sys; print(sys.executable)"` lässt sich der tatsächlich verwendete Interpreter anzeigen.

Ergebnis: `dist/installer/NTF-Insight-Setup-<Version>.exe` und `dist/installer/SHA256SUMS.txt`.

## Werkzeuge und Grenzen

- **PyInstaller:** erstellt den Ordner `dist/NTF Insight` mit GUI, Python-Laufzeit und Bibliotheken.
- **Inno Setup:** erstellt daraus eine EXE mit Deinstallation sowie Startmenü- und optionaler Desktop-Verknüpfung.
- **CI-Prüfung:** `ci/quality_gate.py` mit Tests sowie ein tatsächlicher Start der installierten App im Qt-Offscreen-Modus.
- **Signierung:** Noch nicht integriert. Für den produktiven Mercedes-Benz-Rollout müssen die dafür freigegebenen internen Prozesse genutzt werden.
- **Datenschutz:** Reale FINs, interne Berichte und vertrauliche Dateien dürfen weder in GitHub noch in den Release gelangen.
