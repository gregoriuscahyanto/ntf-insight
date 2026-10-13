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

## Grenzen und Sicherheit

- Der vollständige QEC-Liveablauf und tatsächliche Dateidownload
  können nur im berechtigten Mercedes-Benz-Unternehmensnetz geprüft werden.
- Ein QEC-Datenexport ist ein Ausgangsbefund, keine automatische
  Lieferanten-Schuldzuweisung.
- FINs, Befundungsberichte, Betriebsdaten, Cookies und Anmeldeinformationen
  dürfen weder in GitHub noch in CI-Protokolle oder Releases gelangen.
- Die TIPS-Spalte unterscheidet eine bestätigte Verknüpfung explizit
  von einem bloßen FIN-Hinweis.
