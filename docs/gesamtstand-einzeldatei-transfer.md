# NTF Insight: vollständigen Analysestand in einer Datei übertragen

## Ziel

**Einmal auf Rechner A herunterladen, parsen und analysieren.**
Danach eine einzige Datei übertragen und auf Rechner B direkt arbeiten –
ohne erneuten QuickTest-, QEC- oder AutoExport-Parserlauf.

Das transportable Format hat die Endung **.ntfbackup**. Technisch ist es
ein geprüftes ZIP mit einer eigenständigen, bereits gefüllten
**DuckDB-Datenbank** und den zugehörigen lokalen Originaldateien.
Eine nackte `ntf-insight.duckdb` allein ist **nicht** der vollständige
Arbeitsstand, da sie absolute Rohdateipfade und externe PDF/JSON-Anhänge
referenziert.

## Bedienung

**Rechner A:**

1. QuickTests und QEC-Berichte herunterladen, bis der anschließende
   Quellenimport abgeschlossen ist.
2. Unter **Datenquellen → Gesamtdatenstand zwischen PCs übertragen**
   **„Gesamtstand als eine Datei exportieren“** wählen.
3. Einen Speicherort **außerhalb** des NTF-Insight-Datenordners auswählen.
4. Die resultierende **.ntfbackup**-Datei über einen genehmigten,
   geschützten Mercedes-Benz-Transferweg weitergeben.

**Rechner B:**

1. Kompatible NTF-Insight-Version installieren und starten.
2. Unter **Datenquellen → Gesamtdatenstand zwischen PCs übertragen**
   **„Gesamtstand aus Datei wiederherstellen“** wählen.
3. Die **.ntfbackup**-Datei auswählen und das **Ersetzen des bisherigen
   lokalen Datenstands** ausdrücklich bestätigen.
4. Die Anwendung lädt die übertragene DuckDB automatisch neu.
   Bereits gespeicherte QuickTests, QEC-/TIPS-Dokumente, FINs, Fälle,
   Prüfmarkierungen und manuelle Änderungen sind direkt nutzbar.

Beim Wiederherstellen werden weder Webseite noch SSO benötigt.
Es wird keine PDF erneut geparst. Die Datei darf nicht im aktiven
Datenverzeichnis liegen.

## Was enthalten ist?

- Eine mittels **DuckDB COPY FROM DATABASE** erstellte vollständige
  Datenbankkopie einschließlich Rohdatenindizes, QuickTest-Tabellen,
  QEC-Fall- und Analyse-Snapshots, manuelle Änderungen, Reviews,
  Clustergrundlagen, Verlauf und Referenz-/TP-Daten
- Alle aus **source_artifacts** referenzierten Rohdateien unter `raw/`
- Lokale `quicktests/<FIN>/`, `qec/<FIN>/` und `tips/<FIN>/`
  mit unterstützten Dokumenttypen einschließlich QEC-JSON, PDF und archivierten älteren QEC-HTML-Ansichten
- Manifest mit Dateiliste, Größen und **SHA-256** zur Integritätsprüfung
- Beim Import: automatische Anpassung der
  `source_artifacts.archived_path`-Einträge an den neuen Datenordner

## Was ausdrücklich nicht enthalten ist?

- Anmeldeinformationen aus dem Windows Credential Manager
- Edge-/SSO-Profile, Cookies, Browser-Sitzungen, PING-ID
- Programmdateien/Installer und lokal gewählte UI-Erscheinungsoptionen
- Beliebige Dateien außerhalb des NTF-Insight-Datenordners
- Extern gespeicherte Exportdateien und nicht registrierte
  Dateien im `raw/`-Verzeichnis

Es handelt sich um einen **vollständigen analysierten Datenstand**,
nicht um eine Zusammenführung zweier Datenbanken. Das Zielsystem
ersetzt die lokale DuckDB und die vier Datenordner. Daher **vorher
selbst eine Sicherung des bisherigen Zielrechners erstellen**.

## Prüfung und Grenzen

- Die App prüft alle ZIP-Pfade und Dateihashes **vor** einem Eingriff in
  die bestehenden lokalen Daten. Bei einem Installationsfehler wird
  versucht, den vorherigen Stand vollständig zurückzurollen.
- Bereits vorhandene Daten werden von der Python-API standardmäßig
  **nicht** überschrieben; die GUI erfordert eine ausdrückliche
  Bestätigung für die ersetzende Wiederherstellung.
- Keine parallelen QuickTest-/QEC-Downloads, FIN-ZIP-Exporte oder
  Quellenimporte während der Transferaktion durchführen.
- Unterschiedliche, inkompatible DuckDB-Versionen können ein
  Transferpaket möglicherweise nicht öffnen; beide PCs sollten
  dieselbe NTF-Insight-Version verwenden.
- **Das Transferpaket ist nicht verschlüsselt und nicht digital
  signiert.** SHA-256 erkennt Beschädigung, beweist aber nicht
  die Herkunft. Nur selbst erzeugte, vertrauenswürdige Pakete über
  firmenfreigegebene, verschlüsselte Speicher und Transportwege
  verwenden. Keine echten FINs/QEC/TIPS-Daten in GitHub oder CI laden.
- Die bereits bestehende QEC-JSON-Erfassung wird dadurch nicht
  automatisch zu einer vollumfänglichen fachlichen QEC-Parserlogik.
  Der Status der Analyse entspricht exakt dem Zustand auf Rechner A.

Die Funktion wird nur mit synthetischen Testdaten in GitHub-CI geprüft.
Eine fachliche Abnahme mit genehmigten Datensätzen auf zwei echten
Windows-Arbeitsplätzen ist vor Produktiveinsatz erforderlich.
