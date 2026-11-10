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

## 14-stellige Mercedes-Kurz-FINs

Die **VeDoc-Historie** und **Diagnosis Viewer QuickTests** können in der CLI
neben vollständigen 17-stelligen Fahrzeugkennungen auch 14-stellige
Mercedes-Kurz-FINs als TXT-Eingabe verwenden. Synthetisches Beispiel:

```text
1671061B000001
1671061B000002
```

```powershell
ntf-insight-beschaffung --eingabe .\\kurz-fins.txt --quellen vedoc-historie,quicktests --objekt DCDC223 --parallel 2
```

Die Eingabe wird **nicht** automatisch mit einem geratenen WMI-Präfix
erweitert. Zeigt VeDoc oder Diagnosis Viewer eine 17-stellige Kennung,
werden nur Ergebnisse mit exakt passenden letzten 14 Zeichen akzeptiert.
Zwei verschiedene 17-stellige Kennungen zur gleichen Kurz-FIN gelten als
**mehrdeutig und führen zum Fehler**, nicht zu einem Download.
Ein Live-Test mit berechtigtem Zugriff bleibt erforderlich, da die
serverseitige Suche nach Kurz-FINs von den Quellsystemen abhängt.

Andere Datenquellen (**WEM, SA-Codes, QEC, TIPS**) verlangen vorerst
vollständige 17-stellige FINs. Enthält die Liste eine Kurz-FIN, werden
diese Quellen im Sammelabruf vor dem Start abgelehnt. Dafür `--quellen
vedoc-historie,quicktests` wählen oder eine Liste mit Voll-FINs nutzen.
Bei gemischter Kurz-/Voll-FIN-Liste gelten dieselben Einschränkungen.

## Die sechs Befehle

Mit `FIN-Liste DCDC223 SensorIssue.txt` als Eingabe:

```powershell
ntf-insight-vedoc-dcdc223 --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
# Alternativ: beliebiges VeDoc-Hardwareobjekt / Hardwareattribut
ntf-insight-vedoc-historie --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --objekt CPC3 --attribut Seriennummer
ntf-insight-wem --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
ntf-insight-vedoc-codes --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
ntf-insight-quicktests --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
ntf-insight-qec --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
ntf-insight-tips --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"
```

Ohne `--ausgabe` wird ausschliesslich aus dem **TXT-Dateinamen** ein
Windows-sicherer Ordnername gebildet. Sonderzeichen wie `: ? * < > | " / `
und Steuerzeichen werden durch `_` ersetzt. Bei reservierten Windows-Namen
(`CON`, `PRN`, `COM1` usw.) wird ein Unterstrich vorangestellt.
Leere Namen erhalten `FIN-Liste`; sehr lange Namen werden auf 80 Zeichen
mit kurzem Hash verkuerzt. Leerzeichen im Namen bleiben erhalten.

```text
data/
  processed/
    FIN-Liste DCDC223 SensorIssue/
      vedoc_dcdc223/
        dcdc223_seriennummern.json
        dcdc223_seriennummern.xlsx
      diagnosis_viewer_warn_error/
        warnings_errors.json
        warnings_errors_teile/
      vedoc_codes/
        vedoc_codes.json
      diagnosis_viewer_quicktests/
        <FIN>/QuickTest-*.pdf
      qec/
        <FIN>/ref_<QEC-Referenz>/qec.json
      tips_writer/
        <FIN>/fall_<Fallnummer>/tips.json
```

**Vorhandene CLI-Daten bleiben am bisherigen Speicherort** und werden nicht
automatisch verschoben. Es wird beim neuen Aufruf nur ein neuer Listenordner
angelegt. Das gilt auch fuer Wiederaufnahmedateien. Zum Fortsetzen alter
Datenstaende einfach `--ausgabe` mit dem bisherigen Pfad angeben.

`--ausgabe` hat in jedem Einzelbefehl Vorrang:
- VeDoc-Codes und WEM: eine **.json-Datei**, wie bisher.
- DCDC223, QuickTests, QEC und TIPS: ein **Verzeichnis**, wie bisher.

Beispiele:

```powershell
ntf-insight-wem --eingabe .\fins.txt --ausgabe "D:\NTF\wem.json"
ntf-insight-qec --eingabe .\fins.txt --ausgabe "D:\NTF\qec"
```

## Frei waehlbare VeDoc-Hardwarehistorie

Die bisher fest auf DCDC223 eingestellte VeDoc-Historie kann jetzt jedes
**exakt im VeDoc-Historienreiter auftauchende Objekt** abfragen. Mit
`--objekt` wird das Objekt, mit `--attribut` das genaue Feld gewaehlt.
Beide sind reine Suchtexte und werden nicht als Code ausgefuehrt.

```powershell
ntf-insight-vedoc-historie --eingabe .\fins.txt --objekt CPC3
ntf-insight-vedoc-historie --eingabe .\fins.txt --objekt CPC3 --attribut Hardwarestand
ntf-insight-vedoc-dcdc223 --eingabe .\fins.txt      # Legacy-Standard DCDC223/Seriennummer
```

Das neue Kommando `ntf-insight-vedoc-historie` speichert standardmaessig
unter `data/processed/<TXT-Name>/vedoc_historie/` und verwendet je
Objekt/Attribut sichere, unterschiedliche Dateinamen (z. B.
`cpc3_seriennummern.json` und `cpc3_hardwarestand.xlsx`).
Der DCDC223-Legacy-Aufruf ohne zusaetzliche Optionen verwendet weiter
`vedoc_dcdc223/dcdc223_seriennummern.{json,xlsx}`. Ein letzter
neuer Wert ist nur ein **dokumentierter Historienwert**, kein Nachweis des
aktuell verbauten Hardwarezustands.

Auch im Sammelabruf sind `--objekt` und `--attribut` moeglich,
wenn die VeDoc-Historie selektiert ist:

```powershell
ntf-insight-beschaffung --eingabe .\fins.txt --quellen vedoc-historie,quicktests --objekt CPC3 --attribut Hardwarestand --parallel 2
ntf-insight-beschaffung --eingabe .\fins.txt --quellen dcdc223,wem --objekt CPC3 --parallel 2
```

`vedoc-historie` ist ein lesbarer Alias fuer die historische Quellen-ID
`dcdc223`. Wird eines der neuen Argumente gesetzt, schreibt der Sammelabruf
in `vedoc_historie/`; andere Datenquellen erhalten diese Optionen **nicht**.
Einen gleichzeitigen Abruf mehrerer verschiedener Hardwareobjekte in
denselben Exportdateien bitte nicht verwenden: Fuer unterschiedliche Objekte
werden getrennte JSON-/XLSX-Dateinamen erzeugt, die Prozesse einer Quelle
laufen jedoch weiterhin nacheinander. Weitere Hinweise:
[VeDoc-Hardwarehistorie](vedoc-hardware-historie.md).

## Alle Quellen parallel abrufen

Im selben Terminal koennen alle **sechs unterschiedlichen** Datenquellen
parallel laufen. Der Sammelbefehl erzeugt keine eigene Scraper-Logik, sondern
startet die sechs installierten Einzel-CLIs als voneinander unabhaengige
Prozesse. Jede Quelle schreibt in ihren eigenen Unterordner.

```powershell
# Maximal 2 Quellen gleichzeitig (Standard):
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt"

# Maximal 3 unterschiedliche Quellen gleichzeitig:
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --parallel 3

# Alle 6 Quellen gleichzeitig, wenn PC, Netzwerk und Unternehmenssysteme mitmachen:
ntf-insight-beschaffung --eingabe ".\FIN-Liste DCDC223 SensorIssue.txt" --parallel 6

# Nur QEC, QuickTests und WEM gleichzeitig:
ntf-insight-beschaffung --eingabe .\fins.txt --quellen qec,quicktests,wem --parallel 3

# Eigenen Sammelordner setzen:
ntf-insight-beschaffung --eingabe .\fins.txt --ausgabe "D:\NTF\Batch-1" --parallel 2
```

Mit `--ausgabe` beim Sammelbefehl wird **der Basisordner** angegeben
(`D:\NTF\Batch-1`), nicht eine einzelne JSON-Datei. Der Sammelprozess
ergänzt die spezifischen Quellunterordner und JSON-Dateinamen automatisch.

Alle sechs Datenquellen können unterschiedliche Edge-Fenster gleichzeitig
öffnen und eigene SSO-/PING-ID-Freigaben benötigen. **VeDoc-Historie und
QuickTests** haben eine gemeinsame prozessuebergreifende SSO-Sperre:
PING-ID-Anmeldungen finden **nacheinander** statt, die FIN-Abfragen
anschliessend weiterhin **parallel**. Zuerst die erste PING ID im
Smartphone bestaetigen, dann die zweite. Unter
%USERPROFILE%\.ntf-insight\sso-anmeldung.lock liegen keine persoenlichen
Daten; der Betriebssystem-Lock wird beim Prozessende freigegeben.
Die anderen vier Quellen sind noch nicht an diese Sperre angebunden.

Die QuickTest-**CLI** ueberspringt nur FINs mit bereits vorhandener
lesbarer PDF im passenden FIN-Unterordner. Ein alter oder juengster
Abrufversuch ohne PDF wird wiederholt; --erneut erzwingt den Abruf
auch bei bereits vorhandenen PDFs. Mit
`--login-manuell` wird bei allen die Anmeldung manuell durchgeführt.
**PING ID bleibt in jedem Fall manuell.** Der Standard von zwei parallelen
Diensten reduziert Browser-/Serverlast; `--parallel 6` ist optional
und nicht garantiert schneller (Anmeldungen, Serverlimits und RAM).
Eine einzelne Quelle wird niemals zweimal parallel gestartet; **FINs
innerhalb derselben Quelle** werden weiterhin sequenziell verarbeitet.
Der Sammelprozess gibt pro Quelle den Exitcode aus und meldet Teilausfälle.

Auch ohne Sammelbefehl sind **mehrere eigene Terminals** mit unterschiedlichen
Einzel-CLIs möglich. Zwei gleichzeitige Aufrufe **derselben** Quelle
mit demselben Profil oder Ausgabeordner vermeiden.

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
Stattdessen kann eine Sachnummer fuer alle FINs direkt uebergeben werden:

```powershell
# Nur QEC-Faelle mit exakt dieser Sachnummer, auch ohne Pumpenbezeichnung:
ntf-insight-qec --eingabe .\fins.txt --sachnummer "A 123 456 78 90"

# Alle Dateianhaenge aus den Fall-Popups mitnehmen:
ntf-insight-qec --eingabe .\fins.txt --sachnummer "A 123 456 78 90" --anhaenge alle

# Parallel mit anderen Quellen (Sachnummer/Anhangmodus nur fuer QEC):
ntf-insight-beschaffung --eingabe .\fins.txt --quellen qec,quicktests,wem --sachnummer "A 123 456 78 90" --anhaenge alle --parallel 3
```

`--sachnummer` gilt fuer alle FINs der Eingabe. Falls eine Zeile bereits
`FIN;Sachnummer` enthaelt, muss sie mit dem CLI-Wert uebereinstimmen,
andernfalls wird der Abruf vor dem Login abgelehnt. Eine **explizite
Sachnummer** nimmt den alten Pumpenbezeichnungsfilter fuer diese FIN
zurueck und prueft die Sachnummer genau; ohne Sachnummer bleibt der
Kuehlmittelpumpenfilter aktiv. `--alle-bauteile` ist weiterhin die
bewusste Auswahl saemtlicher Schadteilarten ohne Sachnummerfilter.

**Anhaenge:** Standard `--anhaenge referenz`: Nur Dateien, deren
sichtbarer Name die exakte QEC-Referenz enthaelt. `--anhaenge alle`:
**alle im Popup der ausgewaehlten QEC-Faelle sichtbaren Dateien**
herunterladen, selbst wenn ihr Dateiname keine Referenznummer enthaelt.
Dies kann **fremde QEC-Fallanhaenge** einschliessen. Dateien sind daher
nur als im Popup gesichtete Belege nachgewiesen, nicht als gepruefte
Referenzzuordnung. In der `anhaenge`-Liste der jeweiligen `qec.json` werden
`sichtbar_bei_referenz`, `auswahlmodus` und
`referenz_im_dateinamen_bestaetigt` sowie `zuordnung` dokumentiert.
Erst im spaeteren fachlichen bzw. ChatGPT-Schritt darf die Zugehoerigkeit
bewertet werden.

Bei einer erweiterten Suche nur im freigegebenen Umfang abrufen.

## QEC-Ablage

```text
data/processed/<TXT-Name>/qec/
  <FIN>/
    abrufstatus.json
    ref_<QEC-Referenz>/
      qec.json
      anhaenge/
        <Originalanhaenge>
```

Ein Fahrzeug kann mehrere QEC-Referenzen haben. Die Auswahl der
QEC-Schadteilfaelle erfolgt mit **exakter Voll-FIN und optional exakter
Sachnummer**. Jeder ausgewaehlte QEC-Fall bleibt in seinem eigenen
`ref_<QEC-Referenz>`-Ordner. Ohne `--anhaenge alle` bleibt die
Referenznummer im Dateinamen die Voraussetzung fuer jeden Anhang.
Im erweiterten Anhangmodus bleiben auch **nicht bestaetigte**
Popup-Anhaenge erhalten; sie werden im Fall-JSON gekennzeichnet und
duerfen nicht ohne Pruefung einem QEC-Fall zugeschrieben werden.
Die fuenf QEC-Abschnitte werden vollstaendig erfasst; vorhandene
Anhaenge werden anhand ihrer IDs und Metadaten abgeglichen.

## XENTRY-TIPS-Ablage

```text
data/processed/<TXT-Name>/tips_writer/
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
