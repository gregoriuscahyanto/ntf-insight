# Lokale Windows-Runner fuer NTF Insight

Diese Anleitung ergaenzt die bereits fuer `Vehicle_Performance_Simulation`
registrierten Runner. Beide Repositories sind getrennt: Ein
**Repository-Runner** kann nicht automatisch Jobs des anderen Repositories
ausfuehren.

## Zwei zusaetzliche Instanzen auf demselben PC

1. `https://github.com/gregoriuscahyanto/ntf-insight/settings/actions/runners`
   oeffnen, **New self-hosted runner** auswaehlen und **Windows / x64**
   einstellen.
2. In `C:\actions-runner-ntf-1` die von GitHub angezeigten Download- und
   Installationsbefehle ausfuehren. Die alte Runnerinstallation fuer das
   Simulationsrepository **nicht** anfassen.
3. Beim `config.cmd` fuer NTF Insight den Namen
   `vehicle-sim-windows-laptop` und das zusaetzliche Label
   `ntf-insight-1` setzen. Dazu den **neuen Registrierungstoken aus
   NTF Insight** verwenden, nie den bisherigen Token wiederverwenden.
4. Die Schritte in einem **zweiten, eigenen** Verzeichnis
   `C:\actions-runner-ntf-2` wiederholen; Runnername
   `vehicle-sim-windows-laptop-2`, Label `ntf-insight-2`. Ein
   Runner-Verzeichnis darf niemals fuer zwei Registrierungen dienen.
5. Je nach Nutzung `run.cmd` in einer angemeldeten Sitzung starten
   oder bei der Registrierung fuer reine Hintergrundtests einen
   **Windows-Dienst unter einem eingeschraenkten Konto** konfigurieren.
   Native GUI-/Screenshottests benoetigen eine interaktive Sitzung.
6. In den **NTF Insight**-Einstellungen kontrollieren, dass beide neuen
   Runner online sind. Die Original-Runner des Simulationsrepos bleiben
   unangetastet.

GitHub zeigt die jeweils aktuelle Runner-Version und die passenden
Registrierungsbefehle an. **Registrierungstoken niemals in Chats, Issues,
Commits oder Logs kopieren.**

## Datenspeicher nur lokal freigeben

Der Runner fuehrt beliebigen Code aus dem freigegebenen Repository auf dem
Rechner aus. Daher darf sein Windows-Konto nur auf Daten zugreifen, fuer
die diese Nutzung intern explizit genehmigt ist. Kein Administrator-Konto
verwenden. Keine fremden Pull Requests oder ungepruefte Branches starten.

Fuer den optionalen Echtdaten-Check muss im **Windows-Konto des jeweiligen
Runners** die lokale Umgebungsvariable `NTF_INSIGHT_DATA_DIR` auf das
geschuetzte Datenverzeichnis zeigen. Dort muss bereits eine importierte
`ntf-insight.duckdb` liegen. Der Pfad gehoert weder in das Repository
noch in das Workflow-Log. Nach Aenderungen an der Umgebungsvariable die
Runner-Anwendung/den Dienst neu starten.

Das Python-Skript `ci/windows_local_readonly_check.py` verbindet sich mit
`duckdb.connect(..., read_only=True)`. Es fuehrt ausschliesslich
Struktur-/Konsistenzpruefungen aus. FINs, Dokumentnamen, Rohdaten und
Ausnahmen-Inhalte werden nicht geloggt. Es werden keine GitHub-Artefakte
hochgeladen. Ein geoeffnetes NTF Insight kann die DuckDB-Datei sperren;
bei einem Lock-Fehler die App schliessen und erneut pruefen.

## Manuell testen

Nach Merge des Workflows auf `main` unter **Actions > NTF Insight -
Windows lokal (manuell) > Run workflow**:

- `runner`: `ntf-insight-1` oder `ntf-insight-2`
- `pruefung=code`: Python/Qt-Tests mit synthetischen Daten in einem
  **isolierten temporaren Verzeichnis**
- `pruefung=lokal-readonly`: zusaetzlich Validierung einer bereits
  importierten lokalen DuckDB (ohne Aenderungen)

Der Workflow darf nur auf `main` und vom Repositorybesitzer manuell
angestossen werden, laedt keine Rohdaten hoch und nutzt nur lesende
Repository-Berechtigungen. Die portable CI aus `tests.yml` laeuft
unveraendert auf GitHub-gehosteten Maschinen.

Das ist zunaechst ein **Readiness- und Integritaets-Check**, kein vollstaendiger
Regressionstest saemtlicher Maschinen-/Werkstattberichte. Erweiterte Tests
koennen spaeter als separate, fachlich gepruefte lokale Pruefmodule
hinzugefuegt werden. Sensible Daten bleiben grundsaetzlich am Speicherort.
