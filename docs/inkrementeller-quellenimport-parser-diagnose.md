# Quellenimport fortsetzen und Parser-Proben als ZIP exportieren

## Schnellablauf

Unter **Datenquellen** stehen nun für den lokalen Altbestand bereit:

- **Alle bereits heruntergeladenen QuickTests einlesen**
- **Bereits heruntergeladene QEC-Berichte einlesen**
- **Import abbrechen** (nur während des Imports aktiv)
- **Import fortsetzen** (nach einer gestarteten lokalen Importserie)
- **Nicht parsebare QuickTests/QEC als ZIP exportieren…**

Die beiden lokalen Importaktionen sind **inkrementell**. Das heißt:
Bereits erfolgreich eingelesene, byteidentische PDF- und QEC-JSON-Dateien
werden anhand ihrer **SHA-256-Prüfsumme**, des bestehenden Datenbankeintrags
und der aktuellen Parser-Version übersprungen. Das betrifft auch bereits
bekannte gescheiterte Dateien derselben Parser-Version, um endlose
Fehlversuche zu verhindern.

Eine **neu hinzugekommene** Datei wird eingelesen; wenn sich der Inhalt
einer vorhandenen Datei geändert hat, bekommt sie eine neue SHA-256 und
wird ebenfalls neu eingelesen. Es wird also bewusst **nicht allein nach
Dateidatum** entschieden. Nach einer neuen Parser-Version können ältere
Dateien erneut verarbeitet werden, damit Parser-Verbesserungen wirksam
werden.

Die Prozentzahl des ersten Abgleichs kann bei Tausenden Dateien etwas
langsamer voranschreiten, weil die Prüfsummen zunächst gelesen werden.
Dieses Verfahren ist aber deutlich günstiger als die komplette
PDF-/JSON-Inhaltsauswertung.

## Kontrolliert abbrechen und fortsetzen

**Import abbrechen** setzt eine Abbruchanforderung; die gerade bearbeitete
Datei wird sicher zu Ende verarbeitet. Es wird kein Python-Thread
hart beendet und keine laufende DuckDB-Transaktion abgewürgt.

- Bei Abbruch während der Originalarchivierung bleiben die archivierten
  Dateien erhalten; noch nicht geparste Dateien werden später nachgeholt.
- Bei Abbruch während der Parserphase sind fertig geparste Dokumente
  bereits dauerhaft gespeichert. Der normale nachgelagerte
  Fall-/Diagnoseabgleich wird abgeschlossen.
- **Import fortsetzen** durchsucht die lokale Quellenart erneut und
  lässt erledigte Quellen aus. Der zuletzt verwendete Importtyp bleibt
  innerhalb derselben App-Sitzung verfügbar.
- **Nach einem App-Neustart** genügt es, die jeweilige Schaltfläche
  **„bereits heruntergeladene … einlesen“** erneut zu drücken.
  Die persistierten Prüfsummen und Parsing-Ergebnisse sind das
  eigentliche Wiederaufnahmemerkmal.

Das gilt für den **lokalen Import**; es ist kein Pausieren eines
laufenden Netzwerk-Downloads. Das Verhalten für manuelle Einzeldateien
und ZIP-Bündel bleibt unverändert.

## Diagnosepaket für Parser-Version 3

Die Schaltfläche **„Nicht parsebare QuickTests/QEC als ZIP exportieren…“**
ermittelt lokal Problemdateien aus den gespeicherten Parser-Läufen und
dem QuickTest-/QEC-Archiv. Berücksichtigt werden gescheiterte,
nicht erkannte, nicht persistierte und nur teilweise ausgelesene
QuickTest-PDFs bzw. QEC-JSON-Dateien. Ein bloß heruntergeladener,
noch niemals importierter Bericht wird nicht voreilig als Fehler gewertet.

Der Standardmodus **„Nur technisches Fehlerprotokoll“** erzeugt
ein ZIP mit `diagnose.json` und `HINWEISE.txt`.
Es enthält technische Metadaten wie Parser-Version, SHA-256,
Quelldateityp, Größe und Fehlerstatus, **ohne Originaldateien, FINs,
Originaldateinamen, Dateipfade oder Exception-Freitexte**.
So lassen sich Umfang und Typen der Probleme zunächst gefahrlos
diskutieren, auch ohne Zugriff auf vertrauliche Inhalte.

Der **optionale** Modus **„Mit Originaldateien (vertraulich)“** darf
nur bewusst und nach einer zweiten Bestätigung gewählt werden.
Er legt die Originalbytes unter neutralen Namen wie
`originale/001.pdf` oder `originale/002.json` bei.

**Achtung:** Der zweite Modus anonymisiert weder PDF noch JSON. Auch
neutral benannte Originale können **echte FINs, Personenbezüge,
Lieferanten- und Diagnoseinformationen** enthalten. Das ZIP ist
**nicht verschlüsselt** und wird nicht automatisch hochgeladen.
Vor einem Upload an ChatGPT oder GitHub ist der Inhalt intern
freizugeben und fachgerecht zu anonymisieren; sensible Unterlagen
gehören nicht in öffentliche Repositories.

Um versehentlich riesige Pakete zu vermeiden, enthält der Export
höchstens **30** dokumentierte Problemdateien, höchstens
**35 MiB je Originaldatei** und insgesamt höchstens
**150 MiB Originalbytes**. Die Gesamtanzahl gefundener Problemdateien
bleibt im Manifest sichtbar; größere Mengen können nach Eingrenzung
mit gezielten Beispieldateien untersucht werden.

## Ein-Datei-Gesamtstand

Der **Gesamtstand als eine Datei exportieren** (`.ntfbackup`) bleibt
unverändert. Bereits geparste QuickTests, QEC-Datensätze, die
Parser-Laufprotokolle, Originaldateien und QEC-Anhänge befinden sich
weiterhin im Gesamtdatenpaket. Die inkrementelle Prüfung funktioniert
auf dem zweiten Rechner nach Wiederherstellung ohne erneute
Komplettverarbeitung. Das Gesamtpaket **ist nicht verschlüsselt**.

### Abgrenzung

Ein Parser-Fehlerpaket (`.zip`) ist ein **Diagnosehilfsmittel** und
kein Ersatz für das vollständige `.ntfbackup`. Ein Rohdatenexport
macht aus einem QEC-Lieferantenbefund keine automatische
Lieferantenverursachung oder NTF-Entscheidung.
