# QEC-Befundungsberichte in der FIN-/Fallanalyse

## Bedienung auf dem aktuellen Hauptbranch

Der QEC-Abruf ist unmittelbar unter **Fälle / FIN → FIN / Fallanalyse** in
die bestehende QuickTest-Downloadoberfläche eingebaut. Er verwendet **genau
dieselben Checkboxen in der ersten Spalte der Falltabelle** wie QuickTest.
Das Ankreuzen bleibt auch beim Sortieren und Filtern an die stabile Fall-ID
gebunden.

**QuickTest und QEC erscheinen in zwei gleich gestalteten Bereichen:**

- `Alle Quicktests herunterladen/aktualisieren`
- `Quicktests für ausgewählte Fälle herunterladen/aktualisieren`
- `Alle QEC-Berichte herunterladen/aktualisieren`
- `QEC-Berichte für ausgewählte Fälle herunterladen/aktualisieren`

QEC übernimmt **keine eigene Anmeldung**: Die Benutzer-ID, das Passwort und
die Option **Sicher speichern** stehen gemeinsam direkt über den
QuickTest-Aktionen. Gespeicherte SSO-Zugangsdaten im
Betriebssystem-Anmeldeinformationsmanager werden im Bereich **grün mit Text**
markiert. Bei QEC werden nicht gespeicherte, aber gerade eingegebene
QuickTest-Zugangsdaten ebenfalls für den jeweiligen Abruf benutzt.
**PING ID muss weiterhin manuell bestätigt werden.** Die Anwendungen haben
getrennte Edge-Profile und unabhängige Download-Threads.

Der QEC-Downloader wartet etwa 0,85 Sekunden nach Navigationsaktionen und
Klicks, zusätzlich zu Playwrights Sichtbarkeits- und Ladeprüfungen.
Wartezeiten lassen sich über die Abbruch-Schaltfläche unterbrechen.

## Neue Spalten

Die Tabelle zeigt **TIPS-Fall**, **QEC-Abrufdatum** und das vorhandene
**QuickTest-Abruf-Datum**. Ein blau unterstrichenes QEC-Datum öffnet
den jeweiligen QEC-Referenzordner. Ein Datum wird nur aus einem
lokalen Export übernommen, wenn FIN und QEC-Referenznummer **exakt**
zu diesem Fall passen.

`TIPS-Fall = Ja`: Eine TIPS-Beobachtung ist dem konkreten Fall zugeordnet.
`FIN-Hinweis`: TIPS-Einträge sind unter derselben FIN bekannt, aber
nicht sicher mit diesem konkreten QEC-Schadteilfall verknüpft.
`—`: keine bekannte fallbezogene TIPS-Beobachtung.

## Download-Zuordnung

Bei **allen** Fällen werden die in der Tabelle vorhandenen eindeutigen FINs
und – falls vorhanden – QEC-Referenzen benutzt. Bei **ausgewählten** Fällen
werden nur die IDs mit aktivierter Checkbox betrachtet, unabhängig davon,
ob diese Zeilen aktuell weggefiltert sind.

QEC sucht zunächst nach FIN-Baureihe (Stellen 4–6) und letzter
Endnummer (sechs Zeichen). Ein Schadteil wird erst dann verwendet,
wenn die komplette FIN und bei referenzbezogenem Abruf die **exakte
Referenznummer** übereinstimmen. Führende Nullen bleiben erhalten.
Eine fehlerhafte Referenz darf nicht stillschweigend zu einem
FIN-weiten Abruf erweitert werden.

## Optionaler Sachnummernfilter und Anhangmodus in der CLI

Der bisherige GUI-Abruf bleibt standardmäßig referenzstreng. Die
Kommandozeile kann jetzt eine Sachnummer vorgeben, statt sie in jede
Zeile der FIN-Liste einzutragen:

```powershell
ntf-insight-qec --eingabe .\fins.txt --sachnummer "A 123 456 78 90"
ntf-insight-qec --eingabe .\fins.txt --sachnummer "A 123 456 78 90" --anhaenge alle
```

Eine explizite Sachnummer wird mit den QEC-Suchergebnissen **exakt**
abgeglichen, auch für andere Hardware als eine Kühlmittelpumpe (z. B.
DCDC223). Eine FIN mit mehreren QEC-Fällen kann deshalb anhand der
Sachnummer gezielt eingeschränkt werden. Mehrere Referenzen mit
derselben Sachnummer werden weiterhin separat gespeichert.

Für Dateianhänge gibt es zwei bewusst unterschiedliche Modi:
`referenz` (Standard) lädt nur Dateien mit dieser **exakten
Referenznummer im sichtbaren Dateinamen**. `alle` lädt **alle im
jeweiligen QEC-Popup angezeigten Dateien**, auch wenn kein
Referenzbezug im Dateinamen erkennbar ist. Ein Popup kann fremde
Dateien enthalten. Deshalb wird jede Datei im betreffenden
`qec.json` mit `auswahlmodus`, `sichtbar_bei_referenz`,
`referenz_im_dateinamen_bestaetigt` und `zuordnung` markiert.
Ungeprüfte Anhänge werden nicht als referenzbestätigte QEC-Belege
bezeichnet und müssen später fachlich bzw. in der ChatGPT-Auswertung
geprüft werden. Die Herkunft des Popups ist nur ein Kontextsignal.
SSO, PING ID, URL- und Dateisicherheitsprüfungen bleiben unverändert.

**Keine Sachnummer vorhanden:** Der CLI-Parameter `--benennung DCDC`
filtert alle QEC-Schadteilzeilen, deren Spalte `Benennung` den Text
`DCDC` enthaelt (ohne Beachtung der Gross-/Kleinschreibung). Es werden
auch unterschiedliche DCDC-Sachnummern innerhalb der ausgewählten FINs
erfasst. Mehrere alternative Stichwoerter sind als
`--benennung "DCDC,DC/DC"` moeglich (ODER); mit zusaetzlicher
`--sachnummer` gilt UND. **Ohne** Sachnummer/Benennung bleibt der
bisherige Pumpenfilter aktiv. Die originale QEC-Referenznummer und die
exakt passende 17-stellige FIN bleiben weiterhin verbindlich.

```powershell
ntf-insight-qec --eingabe .\fins.txt --benennung DCDC --anhaenge alle
ntf-insight-beschaffung --eingabe .\fins.txt --quellen alle --parallel 6 --benennung DCDC --anhaenge alle
```

Der parallele Sammelbefehl reicht `--sachnummer`, `--benennung` und
`--anhaenge` ausschließlich an die Quelle `qec` weiter.
Alle sechs CLI-Quellen verwenden dieselbe Betriebssystem-Sperre fuer
die nacheinander erfolgenden SSO-/PING-ID-Anmeldungen; die Downloads
bleiben parallel. Andere Quellen werden durch die QEC-Filter nicht
eingeschraenkt.

## Neues Speicherformat (lokal)

```text
%USERPROFILE%\.ntf-insight\
  qec\
    <FIN>\
      abrufstatus.json
      ref_<QEC-Referenz>\
        qec.json
        anhaenge\
          <ID>_<Originaldateiname>
  edge-qec-profile\
```

`qec.json` pro **QEC-Schadteilfall** enthält `schema_version=2`,
`fin`, `referenznummer`, `sachnummer`, `bezeichnung`,
`abgerufen_am_utc`, `vollstaendige_reiter`, `anhaenge`,
`hinweise` und `fehler` sowie die vollständigen `abschnitte`:

1. WE-Daten
2. Voranalysen
3. Stellungnahme Lieferant
4. Ergebnis + Nachanalyse
5. Historie

Jeder Abschnitt enthält sichtbaren Text, Felder einschließlich
ausgewählter Optionsbezeichnungen und Tabellenzeilen. Dateianhänge
bleiben als **echte Dateien** im `anhaenge/`-Ordner.

**Neue Abrufe erzeugen keine** `laeufe/`, `01_WE-Daten/` usw.
und keine `ansicht.html`. Alte exportierte Fälle bleiben
aus Nachvollziehbarkeitsgründen unverändert; ihr Datum kann die
Anwendung weiter anzeigen. Vorherige Reiterdaten, die bei einem
erneuten, unvollständigen Abruf übernommen werden, erhalten den
Hinweis `aus_vorherigem_abruf` und zählen nicht als frischer
Vollständigkeitsbeleg.

Die QEC-Hauptansicht wird für jeden Schadteilfall erneut geöffnet,
um veraltete Suchergebnisse zu vermeiden. Für echte Anhänge akzeptiert
der Download QEC-interne Weiterleitungen, verwendet bei Bedarf
einen Browser-Fallback und lehnt fremde Hosts sowie Login-HTML als
Dateianhänge ab.

## Einheitlicher Fahrzeugordner bei Kurz-FIN

Bei einer QEC-Suche mit **14-stelliger Kurz-FIN** wird kein eigener
Kurz-FIN-Fahrzeugordner mehr erstellt. Erst wenn die QEC-Trefferliste
vollständig geprüft ist und **genau eine 17-stellige VIN** bestätigt,
werden Befundungsberichte, Anhänge und `abrufstatus.json` ausschließlich
unter **`<QEC-Ausgabe>/<17-stellige-VIN>/`** gespeichert.

Der Status enthält zusätzlich `such_fin` mit der ursprünglichen
14-stelligen Eingabe. **Resume** prüft den vollständigen VIN-Ordner,
exakte Suchparameter, alle fünf Reiter und vorhandene Dateianhänge;
bei mehrdeutigen VIN-Ordnern wird niemals stillschweigend zugeordnet.

Wenn keine Voll-VIN bestätigt werden kann (0 Treffer, mehrdeutig,
unvollständige Trefferliste oder Navigationsfehler), wird nur die Datei
`<QEC-Ausgabe>/qec_suchstatus_<14-stellige-FIN>.json` geschrieben,
**kein** Fahrzeugordner angelegt. Eine WMI wird nicht erraten.

**Rückwärtskompatibles Resume:** Läuft noch ein alter QEC-Prozess,
diesen zuerst vollständig beenden, bevor die neue Version gestartet wird.
Bei einer erneuten Suche nach derselben 14-stelligen FIN prüft der
Downloader sowohl das neue Voll-VIN-Manifest als auch das alte
`<Kurz-FIN>/abrufstatus.json`. Das alte Manifest wird **nur dann**
für ein direktes Resume verwendet, wenn der dokumentierte Erfolg, die
eindeutige vollständige VIN, die Abfrageparameter, QEC-Referenzen,
Berichtsreiter sowie alle zuvor gespeicherten Anhänge übereinstimmen.
Fehlt einer dieser Nachweise oder wurde der alte Prozess mitten in
einem Fall beendet, wird die Suche neu geöffnet. Bereits nachweislich
vollständige Falldateien im 17er-Ordner bleiben dabei erhalten und
werden beim Einzelfall-Resume wiederverwendet.

Ein alter, gültiger Kurz-FIN-Checkpoint darf einen neuen Status im
vollständigen VIN-Ordner ergänzen, **wenn dort noch keiner vorhanden
ist**. Ein bestehender neuer VIN-Checkpoint wird niemals durch alte
Metadaten überschrieben. Die ursprünglichen 14-stelligen
Statusordner bleiben read-only; Dateien werden weder verschoben
noch gelöscht. Das alte Format funktioniert damit weiterhin,
ohne dass die neue Version zusätzliche Kurz-FIN-Ordner erzeugt.

Für einen vollständig bereinigten Altbestand bitte die Inhalte anhand
der `fin`/`such_fin` und Referenznummern prüfen, bevor etwas manuell
archiviert wird. Andere Quellen verwenden ihre bisherigen strikt
validierten VIN-/JSON-Ablagen; die Änderung betrifft die doppelte
QEC-Fahrzeugordner-Erstellung.

## Verhalten bei QEC-Suchergebnissen

- Die Servermeldung **„Die Abfrage ergab keinen Treffer“** gilt nach
  bestaetigter FIN-Suche als **0 Treffer**; der Batch faehrt ohne
  kompletten Navigationstimeout mit der naechsten FIN fort.
- Bei **Treffern** wird zuerst die bestaetigte Ergebnisliste fuer die
  Schadteilauswahl genutzt, ohne die erste Suche ein zweites Mal zu
  starten. Die Detailansicht wird auch in QEC-Frames erkannt.
- Die **QEC-Trefferzahl** ist nicht automatisch die Zahl passender
  Kuehlmittelpumpen: Der Export prueft weiterhin die **vollstaendige
  FIN**, die Bauteilbenennung und optionale Sachnummern/Referenzen.
  Wenn QEC Treffer zeigt, aber kein Fall heruntergeladen wird,
  gibt `abrufstatus.json` unter `suchdiagnose` an, wie viele
  sichtbare Zeilen, volle FIN-Treffer und passende Bauteile vorlagen.
- Scheitert das Oeffnen eines bestaetigten Treffers, wird die
  Referenz als Fehler protokolliert, statt einen erfolgreichen
  Download vorzutäuschen.

## Diagnose bei haengendem Anhang-Popup

Die QEC-Downloadlogik zeigt im Fortschritt nun die Popup-Phase, die
Anzahl erkannter QEC-Dateilinks, den direkten Downloadversuch,
gegebenenfalls den Edge-Fallback und das Speichern oder Fehlschlagen
jedes Anhangs. Der erste direkte API-Versuch ist auf **25 Sekunden**
begrenzt, bevor der vorhandene Browser-Fallback greift.
Nach `domcontentloaded` wird die Anhangliste kurz erneut geprueft,
auch in QEC-Unterframes, weil sie verzoegert geladen werden kann.

Wenn das Fenster Dateien zeigt, aber **0 QEC-Dateilinks** erkannt
werden, kann die QEC-Version andere Linktypen als
`displayPruefberichtFile.qec?attachmentId=...` benutzen. In diesem
Fall nicht blind fremde URLs herunterladen: Eine berechtigte Person
soll die Linkstruktur (ohne FINs, Passwoerter und vertrauliche Berichte)
fuer einen gezielten Selector-Fix pruefen. Das lokale `qec.json`
enthaelt `hinweise` bzw. `fehler` und die jeweiligen
Anhang-Statuswerte; es werden keine aktiven HTML-Seiten als Diagnoselog
gespeichert.

**Wichtig:** `--anhaenge alle` steuert nur die Auswahl **erkannter**
Links. Es behebt kein fehlgeschlagenes Laden oder keine unbekannte
Linkstruktur. Die exakte FIN-Pruefung und die Kennzeichnung von
nicht bestaetigten Anhang-Referenzen bleiben unveraendert.

## Grenzen und Sicherheit

- Der vollständige QEC-Liveablauf und tatsächliche Dateidownload
  können nur im berechtigten Mercedes-Benz-Unternehmensnetz geprüft werden.
- Ein QEC-Datenexport ist ein Ausgangsbefund, keine automatische
  Lieferanten-Schuldzuweisung.
- FINs, Befundungsberichte, Betriebsdaten, Cookies und Anmeldeinformationen
  dürfen weder in GitHub noch in CI-Protokolle oder Releases gelangen.
- Die TIPS-Spalte unterscheidet eine bestätigte Verknüpfung explizit
  von einem bloßen FIN-Hinweis.
