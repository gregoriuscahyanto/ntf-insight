# Lokale Kühlmittelpumpen-Analyse auf einem Self-Hosted Windows Runner

## Ziel und Sicherheitsmodell

Mit dem bereits vorhandenen, isolierten Windows-Runner `ntf-insight-1`
kann GitHub einen **manuell autorisierten, ausschließlich lesenden**
Analysevorgang anstoßen. Die Original-DuckDB mit QEC-/FIN-/CPC3-/
QuickTest-/AutoExport-Informationen bleibt **auf dem Runner**.
Die Auswertung wird lokal als aggregierte JSON-Datei gespeichert.

Die GitHub-Workflow-Standardausgabe enthält nur einen statischen
Erfolgs- oder Fehlerstatus. **Keine Originaldaten, FINs, QEC-IDs,
ECU:DTC-Schlüssel, Prüfer, SSL-Texte, Dateipfade oder ZIP-Dateien** gelangen
standardmäßig in GitHub-Logs oder Artefakte.

**Optional** darf ein Berechtigter bei jedem manuellen Start gesondert
`summen_in_actions_log_freigeben` auswählen. Dies veröffentlicht
ausschließlich eine feste Whitelist von zehn **Ganzzahl-Summen** in den
GitHub-Actions-Logs. Auch diese zusammengefassten Informationen können
unternehmensintern vertraulich sein und erfordern eine Freigabe.
Das ist keine automatische Dauerfreigabe.

GitHub-Actions-Jobs sind **keine direkte ChatGPT-Fernwartung**: ChatGPT kann
nur die ausdrücklich freigegebenen Logs / GitHub-Informationen sehen,
nicht die lokale JSON oder DuckDB. Das Skript lädt nichts hoch.

## Status der Entwicklung

Dieser neue Workflow basiert auf den Analysefunktionen aus PR #17.
Er ist **nicht** allein mit dem aktuellen alten `main` lauffähig.
Zuerst die abhängigen PRs reviewen und ordnungsgemäß übernehmen.

Auch der reine Runner-Smoke-Workflow aus PR #18 muss, falls noch nicht
geschehen, gesondert reviewt und auf `main` integriert werden.
Grüne allgemeine `quality-gate`-Tests sind kein Beleg dafür,
dass die beiden lokalen Self-Hosted Runner den Smoke-Test bestanden haben.

Vor realem Datenzugriff `main` schützen, Reviews insbesondere für
`.github/workflows/` und `scripts/runner_local_analysis.py` verlangen.
Ein Runner-Label ist keine Zugriffskontrolle; der Runnerprozess darf nur
die für ihn freigegebenen Datenkopien lesen.

## Einmaliges Windows-Einrichtungsskript (empfohlen)

Das Skript `scripts/konfiguriere_ntf_runner.ps1` prüft die bestehende
registrierte Runner-Identität (`vehicle-sim-windows-laptop` für
`ntf-insight-1`), die lokale Python-Umgebung und die vorhandene
DuckDB. Es verändert **nur** die **lokale** `.env` im Installationsordner
von Runner 1 (mit lokalem Backup bei vorhandener Konfiguration).
Es verändert weder Runner 2 noch die Datenbank.

Wenn du `main` lokal synchronisiert hast, in PowerShell am Repo-Root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\konfiguriere_ntf_runner.ps1 -NurPruefen
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\konfiguriere_ntf_runner.ps1
```

Die Standardannahmen sind `C:\actions-runner-ntf-1`,
`<Repo>\.venv\Scripts\python.exe`,
`~\.ntf-insight\ntf-insight.duckdb` und
`~\.ntf-insight\runner-analysen`. Stimmen sie nicht, Parameter
`-RunnerRoot`, `-PythonPath`, `-DatabasePath` und
`-OutputDirectory` verwenden. Das Skript zeigt keine echten Pfade an.
Die Werte werden **nur lokal** in der Runner-Konfiguration gespeichert.

**Anschließend Runner 1 neu starten**, damit die lokale `.env`
wirksam wird. Bei interaktivem Runner `Ctrl+C` im Runner-Terminal,
danach in dessen Installationsverzeichnis `run.cmd` starten.
Beim Windows-Dienst muss die berechtigte IT den Dienst neu starten.
Nicht die Runner-Registrierung löschen oder die Dienstidentität
eigenmächtig verändern.

Sobald der neue Workflow auf `main` vorhanden und Runner 1 wieder
`Idle` ist, kann derselbe lokale Einrichtungshelfer den **ausdrücklich
angeforderten Einzel-Lauf** per vorhandener, angemeldeter GitHub CLI
(`gh auth login`) starten:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\konfiguriere_ntf_runner.ps1 -AnalyseStarten
```

Die Standardeinstellung gibt **keine Analysekennzahlen an GitHub**.
Nur bei separater ausdrücklicher Erlaubnis:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\konfiguriere_ntf_runner.ps1 -AnalyseStarten -SummenFreigeben
```

Das benötigt eine funktionierende Anmeldung der GitHub CLI auf dem PC.
Das Skript startet **niemals** beim Konfigurieren automatisch eine
Datenanalyse. Die Remote-Ausführung kann aus diesem Chat heraus
nicht durch einen nicht vorhandenen Workflow-Dispatch-Connector
ersetzt werden.

## Vorbereitung auf `ntf-insight-1` (nicht in GitHub speichern)

Der Runner benötigt eine bereits bereitgestellte Python-Umgebung
(Version 3.11+ mit den NTF-Insight-Paketen). **Im Workflow werden weder
`pip install` noch beliebige GitHub-PR-Skripte ausgeführt.**

Drei Einstellungen sind **lokale Umgebungsvariablen des RUNNERPROZESSES**:

| Variable | Inhalt (keine tatsächlichen Werte ins Chat/Repo schreiben) |
|---|---|
| `NTF_INSIGHT_RUNNER_PYTHON` | Vollständiger Pfad zur vorhandenen `python.exe` der freigegebenen lokalen `.venv` |
| `NTF_INSIGHT_RUNNER_DB` | Vollständiger Pfad zur **bestehenden** `ntf-insight.duckdb` |
| `NTF_INSIGHT_RUNNER_REPORT_DIR` | Nur lokal freigegebener, geschützter Ergebnisordner **außerhalb des Git-Repositories** |

Für einen interaktiv über `run.cmd` gestarteten Runner können sie **vorher
in dessen PowerShell-Sitzung** gesetzt werden. Beispiel **mit fiktiven
Pfaden**, nicht unverändert kopieren:

```powershell
$env:NTF_INSIGHT_RUNNER_PYTHON = "D:\\Freigaben\\NTF-Venv\\Scripts\\python.exe"
$env:NTF_INSIGHT_RUNNER_DB = "D:\\Freigaben\\NTF-Daten\\ntf-insight.duckdb"
$env:NTF_INSIGHT_RUNNER_REPORT_DIR = "D:\\Freigaben\\NTF-Ergebnisse"
.\\run.cmd
```

Diese Variablen gelten nur für den so gestarteten Runner-Prozess.
**Ein Windows-Dienst erbt diese Session-Variablen nicht**. Bei
Runnerdiensten muss die IT die Dienstumgebung und Zugriffsrechte
separat konfigurieren und den Dienst nach Änderung neu starten.
Alle drei Werte dürfen nicht in GitHub-Workflow-`env:`, Issues,
Pull Requests, Logs oder Secrets ungeprüft hinterlegt werden.

Die Datenbank muss geschlossen und ohne widersprüchliche DuckDB-Sperre
lesbar sein. Bei einer konkurrierenden NTF-Insight-App kann DuckDB den
Read-only-Zugriff zurückweisen: Dann den Lauf abbrechen, nicht mit
Schreibmodus oder erzwungener Entsperrung fortsetzen.

## Manuelle Analyse in GitHub ausführen

Nach erfolgreichem Code-Review, Branchschutz und Merge aller
Abhängigkeiten auf `main`:

1. In GitHub **Actions → NTF Lokale Kuehlmittelpumpen-Analyse** auswählen.
2. **Run workflow** mit `main` auswählen.
3. `analyse_freigegeben` **bewusst** auf `true` setzen.
   Voreinstellung ist `false` (der Job wird dann übersprungen).
4. `summen_in_actions_log_freigeben` nur bei separater Freigabe
   aktivieren. Voreinstellung `false`.
5. Starten. Der Workflow verwendet **nur `ntf-insight-1`**,
   die bestehende CI läuft weiterhin auf GitHub-hosted Rechnern.
6. Bei Erfolg erscheint `NTF_LOKALE_ANALYSE_OK` und
   `NTF_RUNNER_FERTIG_NUR_LOKAL`. Kein Ergebnisexport über GitHub.

Für Debugging der Registrierung bleibt Runner `ntf-insight-2`
unverändert; im Analyseworkflow wird er nicht verwendet.

## Was tatsächlich berechnet wird

Die Python-Analyse benutzt dieselbe Kühlmittelpumpen-Grundgesamtheit
und HDBSCAN-Parameter wie die GUI:

- **Bauteilfamilie** `coolant_pump`, Diagnosequellen QuickTest +
  AutoExport, ausschließlich sicher vor dem Pumpentausch belegte
  QEC-DTCs, gesamte Vorher-Historie.
- **HDBSCAN** Leaf, Mindestclustergröße 3, MinSamples 2,
  35%-DTC-Häufigkeitsfilter aus.
- **Diagnoseaudit**: Geeignete QEC-Fälle, ausgeschlossene Fälle
  und dokumentierte QEC-DTC-Evidenz.
- **FIN-Rohquellen** QuickTest (einschließlich Berichte ohne DTCs)
  und AutoExport als separate Suchhinweise, ohne automatische
  QEC-Verknüpfung oder Umdeutung von Tauschtagen.
- **Vorher-/Nachher-Sitzungen**: belegte QEC-Sitzungen versus nur
  FIN-bezogene Roh-QuickTests; Wiederauftreten wird nur bei
  beidseitig verknüpften Diagnosesitzungen beurteilbar.
- **Clusterbrücken** mit CPC3-Kernüberschneidungen, ohne
  Ursachenzuweisung und ohne automatische Clusterfusion.
- **Pilotpriorisierung**: ein echter Medoid je Cluster,
  bis zu zwei unabhängige Vergleichs-FINs pro Gruppe; **keine
  Ursachenbestätigung** durch DTC-Ähnlichkeit.
- **EOM/Leaf-Methodenvergleich** ohne Veränderung der ursprünglichen Fälle.

Pro Lauf entstehen im vorab konfigurierten **privaten lokalen
Ergebnisordner** zwei Dateien:

- `lokale_aggregatanalyse_NICHT_AUTOMATISCH_HOCHLADEN.json`:
  bislang unveränderte aggregierte Auswertung (19 Cluster im bisherigen
  Kühlmittelpumpenbestand, QEC-Summen, Diagnosequalität, Clusterbrücken).
- `pilot_fachpruefung_FIN_SSL_NICHT_HOCHLADEN.csv`:
  eine **priorisierte lokale Prüf- und Fachbestätigungsvorlage** mit einem
  echten QEC-Repräsentanten samt FIN je HDBSCAN-Cluster sowie bis zu zwei
  FIN-getrennten Vergleichsfällen pro Gruppe (starker Vergleich und
  Grenz-/Widerspruchsfall). Die Reihenfolge folgt den bestehenden
  P1/P2/P3/P4-Diagnoseprioritäten.

Die CSV enthält **echte QEC-IDs, FINs und ggf. SSL-Freitextbefunde**.
Sie ist deshalb besonders vertraulich, gehört **nicht** in Git,
Chat, GitHub Actions, Artefakte oder externe ZIP-Pakete.
Sie bleibt auf dem Runner-Rechner und kann lokal in NTF Insight unter
`Bestätigte Fehlermechanismen lokal einlesen` verwendet werden,
nachdem wirklich eigenständig belegte technische Befunde nachgetragen
wurden. Ausgangszustand aller Einträge: `review_status=pending`.
Keine Vermutung wird als bestätigter Mechanismus eingetragen.

Die CSV wird automatisch zusammen mit dem Aggregatbericht geschrieben:
**keine zusätzliche Freigabe in GitHub** und kein zweiter HDBSCAN-Lauf.
Der normale GitHub-Logmodus enthält nach wie vor nur einen festen
Erfolgsmarker; selbst `-SummenFreigeben` veröffentlicht **nur dieselben
zehn ausdrücklich freigegebenen Ganzzahl-Summen**, niemals diese CSV.

Die Quelle wird via DuckDB **`read_only=True`** geöffnet; Tabellen
werden nicht erzeugt oder migriert.

Die aktuell nicht verfügbaren Labor-/Schadteilbefunde werden nicht
ersetzt oder simuliert. Bis unabhängig bestätigte technische
Fehlermechanismen vorliegen, bleibt `fachlich_bestaetigte_repraesentanten=0`.

## Aufruf ohne GitHub (lokal, einmalig)

Als unabhängig prüfbarer Test auf einer lokalen NTF-Insight-Installation:

```powershell
python scripts/runner_local_analysis.py
```

Ohne explizite Argumente gelten die drei lokalen Runner-Variablen.
Alternativ können für diesen **direkten lokalen Aufruf** Pfade per
`--datenbank` und `--ausgabeordner` angegeben werden. In
GitHub-Workflows werden **keine Pfade über Benutzereingaben
angenommen**.

Ohne `--freigabe-summen` gibt die CLI nur `NTF_LOKALE_ANALYSE_OK`
aus. Bei Fehlern gibt sie einen **statischen, nicht identifizierenden**
Fehlerstatus aus; Pfade und Exception-Texte werden nicht an GitHub
weitergegeben. Fehlerursachen gegebenenfalls **lokal** prüfen.

## Nicht implementiert / bewusst gesperrt

- Autonomer Abruf von SSL/Labor/Fachberichten, die noch fehlen.
- Automatische NTF-Ursachen- oder Lieferantenverantwortungszuschreibung.
- Automatische Fachlabel-Erstellung oder Bestätigung anderer Clusterfälle.
- Hochladen der privaten DuckDB, Pseudonymisierungszuordnungen,
  Detail-JSON, PDF- oder Excel-Berichte an GitHub.
- Ausführung ungeprüften PR-Codes auf den Self-Hosted Runnern.

Der präzise Ablauf für die spätere explizite Ergebnisfreigabe und
weitere automatisierte Analysen wird nach erfolgreichem lokalen
Probelauf festgelegt.
