# QuickTest-PDF: automatische FIN-Zuordnung und vollständige lokale Extraktion

NTF Insight liest einen QuickTest-PDF **direkt in der Desktop-App** ein. Die
früher einmalig erzeugte SQLite-Datei wird dafür **nicht benötigt**: Die
Anwendung speichert die neuen Diagnoseinformationen im bereits verwendeten
lokalen **DuckDB-Datenspeicher**.

## Bedienung

1. **Datenquellen** öffnen.
2. Quellenart **Automatisch erkennen (empfohlen)** belassen.
3. QuickTest-PDF (oder mehrere PDFs/ein ZIP) per Drag & Drop hineinziehen oder
   über **Dateien auswählen…** wählen.
4. Hintergrundverarbeitung abwarten. Nach einem neuen PDF wechselt die App
   automatisch auf **Fälle / FIN → QuickTests nach FIN**.
5. FIN wählen, Diagnosezeitpunkt auswählen, alle Steuergeräte prüfen,
   relevante DTCs anklicken und die Snapshot-Parameter ansehen.
6. Unter **Original-PDF-Seitentext** lässt sich der ausgelesene Text jeder
   Seite nachvollziehen.

Das QuickTest enthält die FIN **selbst**. Du musst sie weder manuell
eingeben noch vor dem Import einen QEC-Fall anlegen. Ein optionaler manueller
FIN-Hinweis wird **niemals** verwendet, um die berichtete FIN zu überschreiben.

## Parser 4.1.0: grosse Diagnosis-Viewer-Berichte und erneuter Fehlerimport

Eine lokale Diagnoseprobe mit drei zuvor fehlgeschlagenen
XENTRY-QuickTest-PDFs zeigte zwei konkrete Fehlerursachen:
Ein Bericht mit **632 Seiten und neun QuickTest-Durchlaeufen** lag
ueber der bisherigen Grenze von 400 Seiten. Zwei weitere Berichte
enthielten **EV-DEV-Fehlereintraege unmittelbar vor dem naechsten
Steuergeraet**; der Parser zaehlte sie faelschlich als weitere ECU.
Parser **4.1.0** akzeptiert bis zu **1000 Seiten** (weiterhin maximal
80 MiB PDF-Dateigroesse und 8 Mio. Zeichen extrahierter Text) und
unterscheidet den DTC-Beginn vor der ECU-Kopferkennung.

Die bestehenden Konsistenzpruefungen bleiben erhalten: Die deklarierte
ECU-Anzahl und die DTC-Anzahl jeder ECU muessen mit der extrahierten
Struktur uebereinstimmen. Es werden keine fiktiven Steuergeraete oder
DTCs ergaenzt, um fehlende Eintraege zu kaschieren.

**Nach dem Update** unter **Datenquellen** zuerst die Aktion
**„Nur fehlerhafte QuickTests erneut einlesen“** ausfuehren.
Sie versucht gezielt bereits protokollierte fehlgeschlagene Quellen aus
dem lokalen, per SHA-256 geschuetzten Archiv erneut und laesst
erfolgreich gespeicherte Berichte unberuehrt. Im Workflow kann
**„Parsing fortsetzen“** ausstehende verifizierte Quelldateien nachholen.
Ein erneuter Download oder ein komplettes „Alle neu parsen“ ist fuer
diese drei Fehlfaelle normalerweise nicht notwendig, sofern die
Originaldateien weiterhin lokal vorhanden sind.

Die Diagnoseprobe wurde ausschliesslich lokal untersucht;
**keine Original-PDFs, realen FINs oder extrahierten Diagnosedaten**
sind Bestandteil des Repository-Commits oder der Regressionstests.

## Was gespeichert wird?

Die Daten liegen in separaten, relationalen FIN-Tabellen in
`ntf-insight.duckdb`, nicht nur als Freitextfeld:

| Tabelle | Inhalt |
| --- | --- |
| `quicktest_reports` | FIN, ggf. separate US-VIN, Diagnosezeit, Kilometerstand, ECU-/DTC-Anzahl, Kopfmetadaten |
| `quicktest_sources` | Zu welcher Rohdatei (SHA-256) gehört der Bericht? |
| `quicktest_pages` | Vollständiger maschinenlesbarer Text je PDF-Seite |
| `quicktest_ecus` | Alle erkannten ECU-Blöcke mit Typ, Variante, HW-/SW-Daten, Lieferant, Seitenbereich, kompletten Rohtexten |
| `quicktest_dtcs` | ECU-DTC, Code, FC/EV, Beschreibung, Status, Häufigkeit, KM-Werte, Ignition-Counter, PDF-Seiten, vollständiger DTC-Rohblock |
| `quicktest_parameters` | Alle erkannten Freeze-Frame-/Snapshot-Parameter einschließlich erster und letzter Werte |
| `source_artifacts` | Unveränderte Originaldatei mit SHA-256 und Dateinamen |
| `parse_runs` | Parser-Version, Status und Fehler-/Warnprotokoll |

Bei importierten QuickTests prüft der Parser die **im PDF deklarierte Anzahl
der Steuergeräte und die DTC-Anzahl je ECU**. Bei Widersprüchen verwirft er
die strukturierte Übernahme und protokolliert den Fehler, statt unbemerkt
unvollständige Diagnosedaten als vollständig zu kennzeichnen.

Dateien mit gleicher Textsubstanz, aber unterschiedlichen PDF-Metadaten,
werden als **ein logischer QuickTest** behandelt. Beide Originaldateien können
weiterhin im Roharchiv nachgewiesen werden.

## Wo erscheinen FINs ohne Schadteilfall?

Bereits mit **einem einzigen erfolgreich importierten QuickTest** erscheint
die FIN unter **Fälle / FIN → FIN / Fallanalyse** als
**„Nur QuickTests (kein Fall)“**. Die Übersicht zeigt die Zahl der DTCs,
die **Diagnose-Timeline** mit QuickTest-Zeitpunkten, die DTC-Beobachtungen
und die Steuergeräte-Stände. Auch der Zeitplot funktioniert ohne QEC-Fall.

Die Anzeige ist dann **schreibgeschützt** und enthält **keine
NTF-Ursachen- oder Lieferantenbewertung**. Erst ein gesonderter
Fall/Tauschanker macht den Vorher-/Nachher-Vergleich fachlich möglich.

## Warum stehen noch alte Dateien in „Datenquellen“?

Das Rohdatenarchiv ist bewusst revisionsfreundlich: Ein früher hochgeladenes
PDF oder eine CDD-Datei wird durch einen neuen Import **nicht gelöscht**.

Über **Archivansicht** kannst du zwischen
**„Verarbeitete Dateien“** (Standard), **„Alle archivierten Dateien“** und
**„Noch nicht verarbeitet / Fehler“** wechseln.

Falls ein älterer QuickTest zuvor als **„Sonstiges“** archiviert wurde:

1. **„Alle archivierten Dateien“** auswählen.
2. Alten PDF-Eintrag markieren.
3. Quellenart **„Automatisch erkennen“** belassen oder bewusst
   „Kurztest“ auswählen.
4. **„Markierte Datei neu prüfen…“** anklicken.

Das ursprüngliche PDF und sein historischer Archiv-Eintrag bleiben
erhalten. Eine erfolgreiche Neuverarbeitung legt die FIN-Diagnose
auch nachträglich an, ohne sie doppelt zu zählen.

## FIN ≠ Fall

Ein QuickTest gehört zunächst **zum Fahrzeug (FIN)**, auch wenn noch kein
Gewährleistungsfall oder Pumpentausch bekannt ist. Er wird deshalb in den
separaten QuickTest-Tabellen vollständig gespeichert und im Tab
**QuickTests nach FIN** angezeigt.

Wenn ein QEC-Fall vorhanden ist, übernimmt die Falltimeline die
passenden Diagnoseinformationen als **abgeleitete Projektion**. Bei mehreren
QEC-Fällen derselben FIN, fehlendem Tauschanker oder unklarer zeitlicher
Zuordnung wird **nicht automatisch ein beliebiger Fall ausgewählt**.

Trifft der QEC-Fall erst nach dem QuickTest-Import ein, kann NTF Insight
die bereits gespeicherten QuickTests mit den Fällen verknüpfen, ohne die PDFs
erneut importieren zu müssen.

## Fachliche Grenzen

- Der QuickTest-Diagnosezeitpunkt ist **Beobachtungszeitpunkt** des
  gespeicherten Fehlercodes, kein gesicherter Zeitpunkt der ersten Fehlfunktion.
- Ein ausgelesener Fehlerzähler oder historischer km-Wert ersetzt keine
  gesicherte Fehlerentstehungszeit.
- Ein QuickTest ohne DTCs ist ein echter, dokumentierter fehlerfreier
  Diagnosebericht – **nicht** gleichbedeutend mit fehlender Diagnosedatenbasis.
- Es wird nur die maschinenlesbare **Textebene** extrahiert. Bildbasierte
  PDF-Scans benötigen künftig einen separaten, geprüften OCR-Workflow.
- Bei nicht erkanntem oder widersprüchlichem Layout bleiben die
  **Originaldatei und der Parserfehler** erhalten; Daten werden nicht
  anhand von Dateinamen oder FIN-Hinweisen frei geraten.
- Der Parser speichert alle auslesbaren Rohseiten und Blöcke. Bei künftigen
  QuickTest-Layouts müssen neue unbekannte Elemente gegebenenfalls separat
  als strukturierte Felder ergänzt werden.
- Die Datenbank ist nicht selbst verschlüsselt; lege sie nur auf einer
  für Fahrzeug- und Werkstattdaten freigegebenen Umgebung ab.

## Lokaler Test

```powershell
git pull
python -m pip install -e ".[dev]"
pytest
python -m ntf_insight
```

Echte Mercedes-Benz FINs, Diagnosen und Berichte gehören **nicht in das
öffentliche GitHub-Repository**.
