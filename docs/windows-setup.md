# NTF Insight: Windows-Setup und Wheel-Offline-Paket

Es gibt zwei gleichwertige Installationswege. Für Anwender ist das Windows-Setup ohne Python am einfachsten. Beide Installationsdateien werden in **[GitHub Releases](https://github.com/gregoriuscahyanto/ntf-insight/releases)** abgelegt.

## Weg 1 – Setup.exe ohne Python

1. `NTF-Insight-Setup-<Version>.exe` unter GitHub Releases herunterladen.
2. Auf den Windows-64-Bit-PC übertragen und doppelklicken.
3. NTF Insight über die Desktop- oder Startmenü-Verknüpfung starten.

Inno Setup installiert die mit PyInstaller erzeugte GUI samt Python-Laufzeit ins Benutzerprofil; Administratorrechte sind normalerweise nicht erforderlich. Auf verwalteten Rechnern können Unternehmensrichtlinien den unsignierten Installer trotzdem blockieren.

## Weg 2 – Wheel-Offline-ZIP mit Python 3.11

1. [Python 3.11.9, 64-Bit-Installer](https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe) bereitstellen, falls Python noch fehlt.
2. `NTF-Insight-Wheel-Offline-<Version>-Windows-x64-Python311.zip` vollständig entpacken.
3. `installiere_offline.cmd` doppelklicken.
4. Über Desktop oder Startmenü `NTF Insight (Wheel)` öffnen.

Enthalten sind `wheels/` mit dem NTF-Insight-Wheel und **allen** für Windows x64/Python 3.11 benötigten Abhängigkeiten, `installiere_offline.cmd`, `installiere_offline.ps1` und `LESMICH.txt`. Das PowerShell-Skript legt eine private `venv` unter `%LOCALAPPDATA%\Programs\NTF Insight (Wheel)\venv` an, installiert mit `--no-index`, prüft mit `pip check` und erstellt Verknüpfungen, die `pythonw.exe -m ntf_insight` starten. Der Offline-PC benötigt keine Verbindung zum Internet.

**Wichtig:** `py -3.11` kann auf manchen Entwicklerrechnern auf eine defekte Actions-Runner-Python-Installation zeigen. Das Installationsskript sucht daher eine funktionierende 64-Bit-Python-3.11-Installation mit `pip` und `venv`. Wenn die Suche fehlschlägt, hilft eine korrekt installierte Python-Version oder das Setup aus Weg 1. Es werden **keine** PowerShell-Sicherheitsrichtlinien umgangen; bei Richtlinienproblemen bitte die IT kontaktieren.

## Beide Pakete automatisiert auf GitHub erstellen

1. Bei einer neuen Version `version` in `pyproject.toml` erhöhen und nach `main` übernehmen.
2. [Actions → Windows Release – Setup und Wheel](https://github.com/gregoriuscahyanto/ntf-insight/actions/workflows/release-windows.yml) öffnen.
3. `Run workflow`, `main` und `paket=beide` auswählen. Alternativ ausschließlich `setup` oder `wheel` für die **fehlende** Variante einer bereits veröffentlichten Version wählen.
4. Der Workflow führt Tests aus, baut die ausgewählten Pakete, installiert sie auf dem kurzlebigen Windows-Runner testweise, startet die jeweilige GUI im Qt-Offscreen-Modus und veröffentlicht danach die Dateien als GitHub-Prerelease.

Ein vorhandener Release wird **nicht überschrieben**. Einzelne bislang fehlende Pakete können ergänzt werden, **wenn das Tag zum selben Commit gehört**. Bereits vorhandene Asset-Dateien mit identischem Namen werden nicht überschrieben. Der Veröffentlichungs-Token ist nur für die Release-Prüfung und den Upload verfügbar; `checkout` speichert keine Anmeldedaten. Es gibt keinen Push-/PR-Trigger und **keinen Zugriff auf Self-Hosted-Runner oder Echtdaten**.

Release-Dateien nach vollständigem Durchlauf:

- `NTF-Insight-Setup-<Version>.exe` und `SHA256SUMS.txt`.
- `ntf_insight-<Version>-py3-none-any.whl`, `NTF-Insight-Wheel-Offline-<Version>-Windows-x64-Python311.zip` und `SHA256SUMS-WHEEL.txt`.

Die Dateien dürfen die GitHub-Release-Assetgrenze von 2 GiB nicht überschreiten. Es werden keine GitHub-Actions-Artefakte gespeichert, um das Actions-Kontingent zu schonen.

## Eigenes bereits erstelltes Wheel manuell hochladen

Falls das lokale Wheel `ntf_insight-0.1.0-py3-none-any.whl` schon vorliegt, muss es **nicht nochmals gebaut werden**. Auf einem Entwickler-PC mit Internet, Windows x64 und funktionierendem Python 3.11:

```powershell
.\scripts\baue_offline_wheel_paket.ps1 -WheelPfad ".\dist\ntf_insight-0.1.0-py3-none-any.whl" -Python ".\.venv\Scripts\python.exe"
```

Das Skript verwendet **genau das angegebene Wheel**, lädt die für Windows passenden Abhängigkeiten herunter und erzeugt `dist\offline\NTF-Insight-Wheel-Offline-0.1.0-Windows-x64-Python311.zip` sowie `dist\offline\SHA256SUMS-WHEEL.txt`. Die drei Dateien (das ursprüngliche `.whl`, das ZIP und die Prüfsumme) lassen sich unter **GitHub → Releases → Draft a new release** hochladen, z. B. für `v0.1.0`. Bei einem bestehenden Release **Edit** und zusätzliche Dateien in `Assets` hochladen.

**Achtung:** Wenn du dein Wheel bereits manuell zu `v0.1.0` hochgeladen hast, starte danach nicht nochmals den automatischen Wheel-Upload derselben Version: Er würde wegen des doppelt belegten Dateinamens abbrechen. Das Setup lässt sich über `paket=setup` separat ergänzen, sofern das vorhandene Release-Tag auf dem aktuellen Commit liegt.

Eine einzelne Wheel-Datei kann bei vorhandener Internetverbindung auch mit `pip install` und Online-Abhängigkeiten installiert werden. Für die Installation ohne Internet bitte **immer das vollständige ZIP** benutzen.

## Daten, Sicherheit und Oracle-Runner

Originalberichte und DuckDB bleiben standardmäßig unter `%USERPROFILE%\.ntf-insight` und nicht im Programmordner. Updates oder Deinstallation des Setups löschen diese Daten nicht automatisch. Keine realen FINs, QEC-/QuickTest-Berichte, Kundendaten, Credentials, Unternehmensfonts oder vertraulichen Laborbefunde in GitHub, in einen Release oder in die Wheel-Dateien aufnehmen.

Für produktiven Mercedes-Benz-Einsatz sind interne Freigabe, Security-/Lizenzprüfungen und eine unternehmenskonforme Codesignatur nötig. Die hier veröffentlichten Dateien sind technische **Test-Releases**, keine freigegebenen Unternehmensinstallationen.

Die vorhandenen Windows-Runner `ntf-insight-1` und `ntf-insight-2` sowie die Oracle-Runner aus `Vehicle_Performance_Simulation` werden wegen möglicher vertraulicher Daten **nicht** für Builds genutzt. Nur ein neuer, isolierter Oracle-Runner kann zukünftig für reine Wheel-Aufgaben angebunden werden: [Sichere Oracle-Anbindung](oracle-build-runner.md).
