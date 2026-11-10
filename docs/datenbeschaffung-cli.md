# Datenbeschaffung: sechs installierte CLIs

Alle sechs Datenquellen besitzen nach Installation von `ntf-insight` eigene Befehle
mit **`--eingabe`** (FIN-TXT) und optional **`--ausgabe`**. Ein
`python scripts/...py` ist nicht mehr notwendig. Vorhandene Skriptaufrufe
bleiben rueckwaertskompatibel.

## Installation / Aktualisierung

Im Repository und in der aktiven Python-Umgebung:

```powershell
python -m pip install -e .
```

Nach einem Git-Pull diese Installation erneut ausfuehren, damit die neuen
Console-Scripts bekannt sind. Bei Wheel-Installationen die neu gebaute
`.whl`-Datei installieren. Ein bereits installiertes Windows-Setup aktualisiert
seine Kommandozeileneinstiege **nicht automatisch** durch einen Git-Merge.

## Die sechs Befehle

```powershell
# VeDoc: DCDC223-Seriennummern und Aenderungshistorie -> Ordner mit JSON + XLSX
ntf-insight-vedoc-dcdc223 --eingabe .\fins.txt --ausgabe .\data\processed\vedoc_dcdc223

# Diagnosis Viewer: Warning / Error Messages -> Gesamt-JSON + FIN-Teildateien
ntf-insight-wem --eingabe .\fins.txt --ausgabe .\data\processed\diagnosis_viewer_warn_error\warnings_errors.json

# VeDoc: Fahrzeug-/SA-Codes -> eine JSON-Datei
ntf-insight-vedoc-codes --eingabe .\fins.txt --ausgabe .\data\processed\vedoc_codes.json

# Diagnosis Viewer: QuickTest-PDFs -> <FIN> / PDFs + abrufstatus.json
ntf-insight-quicktests --eingabe .\fins.txt --ausgabe .\data\processed\diagnosis_viewer_quicktests

# QEC: Pumpenbezogene Schadteilfaelle mit Befunden und Anhaengen
ntf-insight-qec --eingabe .\fins.txt --ausgabe .\data\processed\qec

# XENTRY TIPS Writer: Fallinhalte und Anhaenge pro FIN
ntf-insight-tips --eingabe .\fins.txt --ausgabe .\data\processed\tips_writer
```

**Die Ausgabeform ist quellenabhaengig:** VeDoc-Codes und WEM erwarten
`--ausgabe` als **.json-Dateipfad**; die anderen vier Befehle erwarten
ein **Verzeichnis**. Alle haben Standardpfade unter `data/processed/`,
wenn `--ausgabe` weggelassen wird.

`fins.txt` enthaelt eine FIN pro Zeile, z. B.:

```text
WDD12345678901234
WDD12345678901235
```

Die FINs oben sind rein synthetisch. Leere Zeilen, Kommentarzeilen
(`#`) und Duplikate werden unterstuetzt. Nur bei **QEC** kann pro Zeile
optional eine Sachnummer mit Semikolon folgen:

```text
WDD12345678901234; A 123 456 78 90
```

Fuer einen gemeinsamen FIN-Bestand mit allen sechs Tools **keine
Sachnummer anhaengen**, da die anderen Scraper einfache FINs lesen.
QEC filtert standardmaessig auf Kuehlmittelpumpen; `--alle-bauteile`
erweitert die Suche ausdruecklich auf alle QEC-Schadteile zur FIN.
Bei einer solchen erweiterten Suche nur im freigegebenen Umfang abrufen.

## QEC-Ablage

```text
data/processed/qec/
  <FIN>/
    abrufstatus.json
    ref_<QEC-Referenz>/
      qec.json
      anhaenge/
        <Originalanhaenge>
```

Ein Fahrzeug kann mehrere QEC-Referenzen haben. Der Downloader ordnet
Anhänge weiterhin **referenzgenau** zu und ueberschreibt keine vorhandenen
Fremdfalldaten. Die fünf vorhandenen QEC-Abschnitte werden in der
Fall-JSON erfasst. Bereits vorhandene Anhänge werden anhand ihrer
bestehenden Metadaten abgeglichen.

## XENTRY-TIPS-Ablage

```text
data/processed/tips_writer/
  <FIN>/
    abrufstatus.json
    fall_<Fallnummer>/
      tips.json
      dateien/
        <Anhaenge>
```

Die TIPS-JSON enthaelt die von der bestehenden GUI verwendeten
Fallabschnitte und Suchtreffer; Dateien werden ueber den vorhandenen
Anhang-Downloader archiviert.

## Anmeldung, PING ID und Laufverhalten

QEC und TIPS verwenden direkt die vorhandenen, **lesenden** GUI-Downloader.
Beide starten das installierte Microsoft Edge sichtbar mit getrennten
persistenten CLI-Profilen unter `%USERPROFILE%\.ntf-insight`.

- Standard: Benutzer-ID und Passwort nach Moeglichkeit aus demselben
  sicheren Betriebssystem-Tresor wie die NTF-Insight-GUI.
- `--login-manuell`: Anmeldung ausschliesslich in Edge.
- `--passwort-abfragen`: Benutzer-ID und Passwort verdeckt im Terminal
  fuer diesen Lauf verwenden; keine Passwortdatei.
- `--benutzer-id KENNUNG --passwort-abfragen`: Benutzer-ID vorgeben.
- `--anmelde-timeout 600`: bis zu zehn Minuten fuer interaktive
  SSO-/PING-ID-Abschluesse warten (Standard 300 Sekunden).
- `--profil PFAD`: eigenes Edge-Profil, nicht im Ausgabeordner.

Die **PING-ID-Bestaetigung bleibt manuell auf dem Smartphone**.
Der Scraper wartet nach dem SSO automatisch auf die freigeschaltete
QEC- bzw. TIPS-Suchmaske. Nur eine berechtigte Unternehmensanmeldung
erlaubt die Downloads; es findet keine Umgehung statt.

QEC/TIPS: Rueckgabewert `0` fuer vollstaendig abgeschlossene Suche
(auch wenn keine passenden Faelle vorliegen), `1` bei unvollstaendigen
oder fehlgeschlagenen Ergebnissen, `2` bei Eingabe-/Systemfehlern,
`130` bei Unterbrechung. Der bestehende QEC-/TIPS-Downloader fuehrt
seine bewährte lokale Datei- und Abrufstatus-Verwaltung weiter.

**Abgrenzung:** Diese neuen CLIs laden Daten lokal herunter. Im Gegensatz
zum GUI-Workflow findet durch die CLI kein automatischer anschliessender
Import in die interne NTF-Datenbank statt. CLI-Dateien koennen auf
autorisierte Weise in die bestehende lokale Datenpipeline uebernommen
werden.

## Teststand und Datenschutz

Die CLI-Adapter und die bestehenden Downloader werden durch synthetische
Offline-Tests geprüft. Ein Live-End-to-End-Test von Edge-SSO,
PING-ID-Freigabe, dynamischer QEC/TIPS-Suche und Berechtigungen ist
im Unternehmensnetz erforderlich.

Keine echten FINs, QEC-/TIPS-Dateien, SSO-Sitzungen, Zugangsdaten oder
Browserprofile in GitHub, CI-Artefakte oder andere nicht freigegebene
Dienste uebertragen. Die Standardordner unter `data/processed` sind
durch `.gitignore` ausgeschlossen.

Siehe auch [QuickTest-GUI](diagnosis-viewer-quicktest-abruf.md),
[QuickTest-CLI](diagnosis-viewer-quicktests-cli.md),
[VeDoc-Codes](vedoc-codes-abruf.md) und
[WEM-CLI](diagnosis-viewer-warn-error-standalone.md).
