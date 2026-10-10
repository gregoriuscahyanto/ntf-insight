# AutoExport ergänzt QEC – gemeinsames FIN-Clustering

Siehe auch **[Clusteranalyse – eine Oberfläche](clusteranalyse-einheitliche-seite.md)**.

## Ein statt zwei Clusteranalysen

**Fälle / FIN → Clusteranalyse** ist die einzige Clusterseite.
Der frühere experimentelle KMeans-/Balkendiagramm-Ansatz ist
nicht mehr aktiv. Die gemeinsame Punktwolke verwendet
**HDBSCAN Leaf, HDBSCAN EOM und konservatives Complete-Link**.

**Ein Datenpunkt = eine eindeutige FIN.** Originalbeobachtungen
aus AutoExport und QEC werden pro FIN zusammengeführt.
Zwei Diagnosen derselben FIN und dieselbe FIN aus beiden
Quellen erzeugen nie zwei verschiedene Fahrzeuge.

Datenbasis am Beispiel der vom Benutzer lokal genannten Summen:
11.667 AutoExport-FINs, davon 10.898 mit DTCs, gegenüber
324 FINs mit 336 QEC-Pumpenfällen. Die **gemeinsame FIN-Anzahl**
wird nach Deduplikation berechnet und kann größer sein als die
AutoExport-Anzahl. Die FIN-Zahlen sind kein Beleg, dass jedes
Fahrzeug eine defekte Kühlmittelpumpe hat.

## Warum werden manche FINs ausgeschlossen?

Eine AutoExport-FIN ohne beobachtete ECU:DTC-Diagnosedaten
bleibt in der Gesamtzahl sichtbar, aber wird nicht mit
einer erfundenen Merkmalskombination geclustert.
FINs mit DTCs können außerdem als HDBSCAN-Ausreißer
nicht zugeordnet werden. Das ist keine
Feststellung der Fehlerfreiheit.

Das zusätzliche Kästchen **Nur FINs mit QEC-Pumpentauschdatum**
ist ein bewusster enger fachlicher Filter. Ohne Haken
werden FINs ohne Pumpentausch trotzdem anhand ihrer
allgemeinen Diagnosehistorie verglichen. Bei FINs mit
dokumentiertem Tausch werden nur DTCs vor dem Tausch
verwendet. AutoExport-`RepairDt` belegt keinen Pumpentausch;
das untersuchte QEC-`Rep.-Datum` dient als zeitlicher Anker.

## Wie entsteht die Erklärung?

Für jeden angezeigten Cluster bleiben die originalen
ECU:DTC-Schlüssel der FINs nachprüfbar. Der Report nennt
auch Codes, die nur einen Teil der FINs betreffen
(`x von y`), und bekannte DTC-Klartexte. Fehlt der
Text, wird keine Beschreibung erfunden. Eine DTC-
Beschreibung kann aus einem anderen Diagnosezeitpunkt
stammen; sie ist **nur ein Label** und wird nicht
als Modellmerkmal, Verursachernachweis oder
Wirksamkeitsbeleg des Pumpentauschs verwendet.

QEC-Fälle erscheinen in der FIN-Tabelle als **Kennungen
und Anzahl**, bleiben jedoch Fallinformationen zum
Fahrzeug – keine zusätzlichen Clusterdatenpunkte.
Spätere Aussagen über tatsächliche Pumpentauschwirkung
erfordern separate Diagnosesitzungen vor und nach dem
Tausch und eine unabhängige technische Prüfung.

## Datenschutz und ressourcenschonende CI

Originale AutoExport-/QEC-Dateien, reale FINs,
DTC-Schlüssel und Herstellerbefunde verlassen die
lokale Windows-Analyseumgebung nicht. Alle
Repository-Tests sind ausschließlich synthetisch.
Der GitHub-PR bleibt bis zum Offline-Praxistest
außerhalb von `main`.

Die CI ist wegen der GitHub-Quota auf einen
Windows-Runner ohne Artefakt-Uploads umgestellt.
Das Skript `scripts/bereinigung_actions_artifacts.ps1`
kann alte wegwerfbare CI-Reports/Wheels zunächst
nur auflisten und bei explizitem `-Loeschen`
per lokal angemeldeter GitHub-CLI entfernen.
Keine CI-Artefaktbereinigung wird ohne ausdrückliche
Freigabe ausgeführt.
