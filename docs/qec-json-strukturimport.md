# QEC-JSON: strukturierte Erfassung

## Ziel und Umfang

Die vom QEC-Abruf erzeugten Dateien `qec/<FIN>/ref_<Referenz>/qec.json` (Schema 2)
werden lokal als **QEC-Befundbericht · JSON** erkannt und unabhängig von
der QEC-FIN-Excel-Liste strukturiert in DuckDB aufgenommen.

- Unterstützte Reiter: **WE-Daten**, **Voranalysen**, **Stellungnahme Lieferant**,
  **Ergebnis + Nachanalyse**, **Historie**.
- Gespeichert werden die Reiter einschließlich Abrufzeitpunkt, Quelltext,
  Formularfelder einschließlich Originalwerten/Auswahltexten, Tabellenzeilen,
  einfache zweispaltige Bezeichnung/Wert-Paare und die Anhangsverweise.
- Jeder Datensatz trägt **FIN, exakte QEC-Referenz, Ursprungs-SHA-256 und
  Quellposition** (z. B. `QEC/03-Stellungnahme Lieferant/feld:2`).
- Die Daten stehen in `source_knowledge_documents` und
  `source_knowledge_rows`, die `qec_section`, `qec_field`,
  `qec_value`, `qec_table_row` und `qec_attachment` enthalten.
  `SourceKnowledgeStore.list_rows(category="qec_value", fin="...")`
  liefert gezielt abfragbare Werte.
- Die QEC-JSON-Originaldatei wird unverändert im Rohdatenarchiv gespeichert,
  der Datensatz trägt deren SHA-256. Wiederholter Import derselben Datei
  aktualisiert ihre strukturierten Datensätze ohne Dubletten.

## Anwendung

1. Beim normalen QEC-Download wird `qec.json` automatisch an den
   bestehenden Import übergeben. Anhänge können im Rohdatenarchiv
   verbleiben und werden fachlich **nicht** analysiert.
2. **Datenquellen → Bereits heruntergeladene QEC-Berichte einlesen** durchsucht
   die lokalen QEC-Referenzordner nach `qec.json` und liest Altbestände nach.
   Der Vorgang benötigt keine Netzwerkverbindung oder erneuten QEC-Abruf.
3. Die Tabelle **Datenbereitschaft** auf der Seite **Datenquellen** zeigt die
   Anzahl eingelesener QEC-Berichte, der vollständig erfassten Berichte und
   ihrer strukturierten Datensätze. Im Rohdatenarchiv sind Parse-Status und
   Originaldatei nachvollziehbar.

## Vollständigkeit und Auswertung

Der Status **vollständig** bedeutet nur, dass alle fünf Reiter vorhanden,
nicht als ältere Abrufe markiert und vom Downloader als vollständig
bestätigt wurden. Ein vollständig erfasster Reiter ist **keine** geprüfte
Qualitätsaussage. Fehlende Reiter, ältere Abrufe und Abruffehler bleiben als
Hinweise und Metadaten sichtbar. Die Quelle kann Freitext enthalten; der Parser
entscheidet **nicht** automatisch, ob ein NTF vorliegt, ein Lieferant ursächlich
war oder ein Fehler nach Bauteiltausch erneut auftrat. Dies erfordert
nachvollziehbare Verknüpfung mit Diagnose-/Werkstattdaten und fachliche Prüfung.

## Transfer zwischen Rechnern

Der bestehende **Gesamtstand als eine Datei exportieren**-Vorgang erzeugt
`.ntfbackup` und enthält sowohl die DuckDB mit den bereits strukturierten
QEC-Datensätzen als auch `qec.json` und alle zulässigen unveränderten
QEC-Anhangsdateien. Wiederherstellung ersetzt den bisherigen lokalen
Gesamtstand; kein erneutes Parsen ist nötig.

Der Export ist **nicht verschlüsselt**. FINs, Befunde und Anhänge dürfen nur
in dafür freigegebene Unternehmenssysteme übertragen werden. Keine echten
QEC-Daten in GitHub, Test-Fixtures oder CI-Logs speichern.
