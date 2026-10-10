# NTF Insight – Self-Hosted Runner unter Windows: sicherer Einstieg

## Aktueller Zweck

Der Runner ist zunächst **ausschließlich für einen Verbindungstest** vorgesehen,
ohne Zugang zu vertraulichen QEC-, FIN-, SSL-, CPC3-, Labor- oder QuickTest-Daten.
Das Test-Workflow `.github/workflows/runner-smoke.yml` kann **nur manuell**
(`workflow_dispatch`) und **nur auf `main`** ausgeführt werden.
Es lädt keinen Code in den Runner, führt keinen `checkout` aus, öffnet keine
lokalen Quelldateien und lädt keine Artefakte hoch.

Das GitHub-Repository ist privat. **Privat bedeutet nicht vertrauenswürdig**:
Jede berechtigte Änderung an Workflows oder ausgeführtem Code kann auf einem
Self-Hosted Runner lokale Befehle ausführen. Ein dediziertes Runner-Label ist
lediglich eine Job-Auswahlhilfe, **keine** Berechtigungsgrenze. Auch `.gitignore`
schützt keine lokalen Dateien vor GitHub-Actions-Jobs.

## Sicherheitsanforderungen vor der Installation

1. **IT-/Informationsschutz-Freigabe** einholen, insbesondere auf einem
   Mercedes-Benz-Firmenrechner oder einem Rechner mit Unternehmensdaten.
2. Für den Runner möglichst eine **isolierte Windows-VM oder einen separaten
   Rechner ohne Zugriff auf Originaldaten** verwenden. Nicht in der
   angemeldeten Windows-Sitzung starten, die Zugriff auf vertrauliche
   FIN-/QEC-/SSL-Daten hat. Ein eigenes Windows-Standardkonto mit minimalen
   Dateirechten ist nur eine zweite Wahl; Workflows können damit weiterhin
   unter dessen Berechtigungen beliebige Befehle ausführen.
3. Vor echtem Datenzugriff den Standardbranch `main` schützen, verpflichtende
   Reviews und Einschränkungen für Änderungen unter `.github/workflows/`
   festlegen; ggf. ein **separates, streng zugriffsbeschränktes
   Analyse-Repository** einsetzen. Beim Anlegen dieses Dokuments war `main`
   noch **nicht** als geschützter Branch markiert.
4. Nur von der IT ausdrücklich erlaubte Domains/Dienste und ausgehende
   HTTPS-Verbindungen erlauben. Runner benötigt ausgehend TCP/443 für GitHub
   Actions; keine eingehenden Ports oder Fernwartungsfreigaben nötig.
5. **Kein Administrator-Runner**, keine dauerhaften Produktions-Credentials,
   keine Unternehmensgeheimnisse in GitHub Secrets ohne Freigabe.
   `permissions: {}` minimiert nur das GitHub-Token, nicht Windows-Rechte.
6. Keine Original-FINs, echten QEC-IDs, SSL-Texte, Original-DTC-Schlüssel,
   internen Pfade oder Kundendaten in Workflow-Logs, Reports, Caches oder
   GitHub-Artefakte übertragen. Auch anonymisierte Technikmuster erst nach
   Freigabe teilen.

## Schritt 1 – Windows-Runner über GitHub anlegen

GitHub öffnen:

`https://github.com/gregoriuscahyanto/ntf-insight/settings/actions/runners`

Unter **New self-hosted runner** → **Windows** → **x64** auswählen.
Berechtigung: Repositorybesitzer bzw. Repositoryadministrator.

Die dort **aktuell angezeigten** Installationsbefehle zur Installation in
einer isolierten Arbeitsumgebung ausführen (empfohlen: `C:\actions-runner`,
außerhalb von Git-Projekt- und Datenordnern). Die Download-URL, Version
und Prüfsumme **nicht** aus alten Beispielen übernehmen. Die
Runner-Registrierung benötigt ein **zeitlich begrenztes Token**, das
normalerweise nach einer Stunde verfällt.

**Das Token niemals im Chat, in Screenshots, im Repository oder in Logs
veröffentlichen.**

Die beiden bereits registrierten Windows-Runner besitzen die gemeinsamen
Standardlabels `self-hosted`, `Windows`, `X64` und je **ein eigenes Label**:

- `vehicle-sim-windows-laptop`: `ntf-insight-1`
- `vehicle-sim-windows-laptop-2`: `ntf-insight-2`

**Kein neues Label und keine erneute Registrierung nötig.** Der manuelle
Verbindungstest verwendet genau diese beiden bestehenden Labels. Die Labels
sind lediglich Auswahlkriterien – sie garantieren keine Isolation der
Dateisysteme oder Prozesse. Bei einem neuen Runner muss er entsprechend
gekennzeichnet sein.

Für den Test den Runner interaktiv mit `run.cmd` starten und das
Terminal geöffnet lassen. **Noch nicht als Windows-Dienst aktivieren**:
Der Dienst müsste bei der Windows-Konfiguration ausdrücklich gewählt
werden, und sollte nur von der IT mit einem minimal berechtigten Konto
betrieben werden. Auch nicht automatisch beim Login starten.

## Schritt 2 – Nur die Verbindung testen

Der neue Workflow `runner-smoke.yml` muss zunächst **reviewt und nach
`main` gemergt sein**. GitHub bietet die manuelle `workflow_dispatch`-
Schaltfläche erst, wenn das Workflow auf dem Standardbranch vorhanden ist.

Auf GitHub unter **Actions → NTF Runner Verbindungstest → Run workflow**
`main` auswählen und starten. GitHub erstellt **zwei getrennte Jobs**:
`Verbindungstest (ntf-insight-1)` und
`Verbindungstest (ntf-insight-2)`. Beide Runner müssen `Online` sein,
anderenfalls wartet der jeweilige Job auf seinen passenden Runner.
Jeder Runner verarbeitet höchstens den für seine Labels passenden Testjob;
die Tests können parallel laufen.

Bei Erfolg erscheint in **beiden** Jobs ausschließlich:

```text
NTF_SELF_HOSTED_RUNNER_OK
Keine lokalen QEC-, FIN-, SSL-, QuickTest- oder Datenbankdateien gelesen.
```

**Keine** produktiven Workflows auf `runs-on: self-hosted` umstellen:
Die bestehenden Tests laufen weiterhin auf `ubuntu-latest` und
`windows-latest` mit ausschließlich synthetischen Testdaten.

## Schritt 3 – Erst danach Datenauswertung genehmigen

Eine spätere Analyse mit realen lokalen Dateien erfordert einen **eigenen
geprüften Workflow** und vorab die Freigabe von IT/Informationsschutz:
- nur fest definierte, lesbare lokale Verzeichnisse, möglichst getrennte
  freigegebene Datenkopien oder abgeleitete Merkmale,
- keine unkontrollierten Shell-Befehle, beliebigen Skripte oder PR-Code
  ausführen,
- ausschließlich freigegebene, aggregierte Ergebnisse;
  niemals Rohberichte, FINs, QEC-IDs, Original-DTCs und Referenzen,
- wenn Ergebnisse auf dem Host **bleiben**, kann ChatGPT sie **nicht**
  automatisch sehen. Für eine Auswertung durch den GitHub-Connector
  müssten genau definierte und freigegebene Resultate kontrolliert an
  GitHub übergeben werden. Workflow-Logs und Artefakte liegen dann
  außerhalb des lokalen Rechners.

Ein GitHub Self-Hosted Runner ist **kein Fernzugriff** und keine
direkte ChatGPT-Verbindung zu einer lokalen Windows-Sitzung.

## Deaktivieren

Zum Beenden des **interaktiven Tests** das Runner-Terminal schließen
oder `Ctrl+C` drücken. In GitHub unter
**Settings → Actions → Runners** lässt sich der Runner entfernen.
Bei einem künftig als Dienst betriebenen Runner gelten die von
GitHub dokumentierten Windows-Dienstverfahren.

## Quellen (GitHub)

- https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners
- https://docs.github.com/en/actions/reference/security/secure-use
- https://docs.github.com/en/actions/reference/runners/self-hosted-runners
- https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
