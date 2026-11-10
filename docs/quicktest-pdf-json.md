# QuickTest-PDFs lokal in strukturierte JSON-Dateien konvertieren

NTF Insight nutzt den **bereits vorhandenen XENTRY-QuickTest-PDF-Parser**
aus `ntf_insight.ingestion.quicktest_detailed`. Die neue CLI exportiert
dessen vollständiges Datenmodell als JSON. Sie ersetzt **nicht** den
bisherigen DuckDB-Import; Original-PDFs bleiben erhalten.

## Automatisch nach dem Herunterladen

Die QuickTest-CLI und die sechs Quellen umfassende Sammel-CLI konvertieren
lokal vorhandene QuickTest-PDFs **standardmäßig** nach dem Download.
Das gilt auch für bereits vorhandene PDFs übersprungener FINs.

```powershell
ntf-insight-quicktests --eingabe ".\FIN Liste DCDC223.txt"
ntf-insight-beschaffung --eingabe ".\FIN Liste DCDC223.txt" --quellen alle --parallel 6
```

Nur PDFs herunterladen, **ohne** JSON zu erzeugen:

```powershell
ntf-insight-quicktests --eingabe ".\FIN Liste DCDC223.txt" --ohne-json
ntf-insight-beschaffung --eingabe ".\FIN Liste DCDC223.txt" --quellen alle --ohne-quicktest-json
```

Für die Konvertierung wird **keine Anmeldung** benötigt. Beim parallelen
Abruf bleiben die notwendigen PING-ID-Freigaben nacheinander.

## Nachträglich: bereits vorhandene PDFs, ohne Edge/SSO

Als `--ordner` kann direkt der **Basisordner** mit dem Unterordner
`diagnosis_viewer_quicktests` übergeben werden:

```powershell
ntf-insight-quicktests-json --ordner "data/processed/FIN Liste DCDC223 NTF PDF"
```

Auch der QuickTest-Unterordner selbst wird akzeptiert:

```powershell
ntf-insight-quicktests-json --ordner "data/processed/FIN Liste DCDC223 NTF PDF/diagnosis_viewer_quicktests"
```

**Optional:** `--erneut` verarbeitet auch unveränderte JSONs erneut; mit
`--ausgabe "D:\NTF\JSON"` kann ein anderer JSON-Zielordner gewählt werden.
Für diesen Offline-Befehl ist **keine FIN-TXT** erforderlich.

## Ablage

Die neue JSON-Spiegelstruktur liegt **neben** den PDFs:

```text
data/processed/FIN Liste DCDC223 NTF PDF/
|-- diagnosis_viewer_quicktests/
|   |-- <FIN>/
|       |-- S1_QuickTest.pdf
|       |-- abrufstatus.json
|-- diagnosis_viewer_quicktests_json/
    |-- <FIN>/
    |   |-- S1_QuickTest.pdf.json
    |-- konvertierungsstatus.json
```

Die JSON enthält das **vollständige vom Parser erkannte Berichtsmodell**:
`report_id`, `fin`, `vin`, `diag_start`, `distance_km`, `header` mit
QuickTest-Durchläufen, `page_texts` (Rohtext sämtlicher PDF-Seiten),
`ecus` mit HW-/SW-Metadaten, DTCs, Status, Kilometerständen,
Häufigkeitszählern, Parameterwerten und
`reported_ecu_count`/`observed_dtc_count`.

Dazu kommen eine `source_sha256`, die `parser_version` und
`quell_pdf` (ursprünglicher PDF-Name, relativer Pfad, Prüfsumme, Größe).
Eine DTC-Beobachtung zum Diagnosezeitpunkt ist **kein Beweis**, dass
der Fehler zu diesem Zeitpunkt erstmals entstanden ist.

## Wiederaufnahme und Sicherheitsprüfungen

- Das PDF wird anhand seiner **eigenen 17-stelligen FIN** geprüft. Eine
  14-stellige Kurz-FIN im Ordner ist nur zulässig, wenn die letzten
  14 Zeichen der PDF-FIN exakt übereinstimmen. Es wird kein WMI geraten.
- Der Konverter liest nur unmittelbare PDF-Dateien unter
  `diagnosis_viewer_quicktests/<FIN>/`. Symlinks, ungültige
  FIN-Unterordner und andere Dateien werden ignoriert.
- **Resume:** Beim nächsten Start werden nur unveränderte JSONs mit
  gleichem PDF-SHA-256, Parserstand und bestätigter FIN übersprungen.
  Neue, geänderte oder fehlerhafte JSONs werden neu erzeugt.
- Fehlerhafte, verschlüsselte und bildbasierte PDFs oder Dokumente mit
  nicht zuverlässig erkannter ECU-/DTC-Struktur erhalten **keine**
  künstlich erfolgreichen JSONs. Die Fehler werden in
  `konvertierungsstatus.json` vermerkt; weitere PDFs werden bearbeitet.
  Es wird **keine OCR** durchgeführt.
- Das bestehende 80-MB-, 1000-Seiten- und 8-Mio.-Zeichen-Limit
  des Parsers bleibt aktiv. JSON-Dateien werden atomar ersetzt.
- PDF-Originale werden **weder geändert noch gelöscht**.
  Echte FINs und Diagnosedaten dürfen **nicht in GitHub hochgeladen**
  werden; die Verarbeitung erfolgt lokal im berechtigten Umfeld.

Nach dem Merge:

```powershell
git pull
python -m pip install -e .
ntf-insight-quicktests-json --help
```
