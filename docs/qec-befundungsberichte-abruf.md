# QEC-Tool: Befundungsberichte und Fallinformationen abrufen

Diese Funktion ist im Branch `feature/qec-befundungsberichte-playwright` als
**QEC-Abruf** in NTF Insight verfügbar. Sie arbeitet **neben** dem
Diagnosis-Viewer-QuickTest-Abruf (unabhängige Edge-Profile und Threads).

## Voraussetzung und Bedienung

- Das System muss Microsoft Edge, Playwright und einen berechtigten Zugang zum
  QEC-Tool im Mercedes-Benz-Unternehmensnetz besitzen. SSO und gegebenenfalls
  PING ID erfolgen **interaktiv im sichtbaren Edge-Fenster**.
- In **QEC-Abruf** FINs zeilenweise eintragen, aus lokalen Fällen uebernehmen
  oder eine TXT-/CSV-Datei laden. Pro Zeile ist optional eine Sachnummer möglich:
  `17-STELLIGE-FIN;SACHNUMMER`. Die Anzeige der FIN erfolgt **nicht** im Repo.
- Standardmäßig werden nur Schadteile gesucht, deren QEC-Bezeichnung
  Kühlmittelpumpe, Umwälzpumpe oder `coolant pump` enthaelt. Bei abweichender
  Benennung kann der Filter deaktiviert und/oder die exakte Sachnummer angegeben werden.
- **QEC-Daten und Berichte abrufen** klicken, bei Bedarf SSO bestätigen und
  die fallbezogenen Ergebnisse im lokalen Ordner pruefen.
- Unter **QuickTest-Abruf** können unabhängig davon Diagnose-PDFs fuer die
  gleichen FINs heruntergeladen werden. Beide Downloads können mit
  unterschiedlichen Profilen nebeneinander laufen.

## Abfolge laut gelieferter QEC-Anleitung

1. **Fuer jede neue FIN und jeden weiteren Schadteil-Treffer** die
   QEC-Hauptansicht neu öffnen. Laut Anleitung zeigt QEC andernfalls
   möglicherweise noch den vorherigen Vorgang.
2. In **Schadteilsuche** die Felder `_finBR` (FIN-Stellen 4 bis 6)
   und `_finEndnummerFrom` (letzte 6 Zeichen) ausfuellen, **Filtern** klicken.
3. Den Tabellen-Treffer ausschliesslich bei Übereinstimmung der **gesamten FIN**
   aus WHC, BR, BM, Werk und Endnummer verwenden. Optional zusätzlich
   Sachnummer und Pumpenbezeichnung pruefen. Mehrere passende Referenznummern
   werden separat gesichert.
4. Die Reiter **WE-Daten**, **Voranalysen**, **Stellungnahme Lieferant**,
   **Ergebnis + Nachanalyse** und **Historie** öffnen. Pro Reiter werden sichtbarer
   Text und Formularwerte strukturiert als `daten.json` sowie eine **passive**
   `ansicht.html` abgelegt. Passwoerter, versteckte Formular-Tokens, Cookies
   und Skripte sind nicht Bestandteil der Offline-Ansicht.
5. In der **Stellungnahme Lieferant** gegebenenfalls **Dateianhänge** öffnen.
   Anhänge werden ueber die dokumentierten
   `displayPruefberichtFile.qec?attachmentId=…`-Links mit der **bestehenden,
   angemeldeten Browser-Sitzung** abgerufen. Doppelte IDs werden ignoriert;
   veränderte Dateien werden nicht ueberschrieben.

Die von der Anleitung bereitgestellten Beispiel-HTMLs liegen **nur lokal** im
übergebenen ZIP: *QEC-Tool - Hauptansicht.html*, *QEC-Tool - Schadteilsuche
mit FIN ….html*, *QEC-Tool - Stellungnahme Lieferant - Dateianhänge.html*.
Sie werden weder ins Repository eingecheckt noch als Testdaten geteilt.

## Ablage

Standardmäßig im lokalen, nicht versionierten Datenbereich:

```
~/.ntf-insight/qec/<FIN>/abrufstatus.json
~/.ntf-insight/qec/<FIN>/ref_<Referenz>/anhaenge/<ID>_<Dateiname>
~/.ntf-insight/qec/<FIN>/ref_<Referenz>/laeufe/<Zeitstempel>/01_WE-Daten/daten.json
~/.ntf-insight/qec/<FIN>/ref_<Referenz>/laeufe/<Zeitstempel>/01_WE-Daten/ansicht.html
... Reiter 02 bis 05 entsprechend
~/.ntf-insight/edge-qec-profile/
```

Die Datei `abrufstatus.json` weist Referenznummern, angelegte Dateien,
Fehler und Warnungen nachvollziehbar aus. Originalanhaenge werden nach
SHA-256-Inhalt dedupliziert. Falls die lokale Datenquellenarchivierung aktiviert
ist, werden heruntergeladene Dokumente zusätzlich an den bestehenden
Quellenimport übergeben; ohne vorhandenen Parser bleiben sie als Originaldatei
archiviert. Eine **automatische fachliche Interpretation** aller QEC-Felder
ist nicht Bestandteil dieser ersten Ausbaustufe.

## Grenzen und Datenschutz

- Die Suche und das Anhang-Popup sind anhand der gelieferten **gespeicherten
  HTML-Dateien** offline getestet. Die Detailreiter liegen nur als Screenshots
  vor. Ihre Klickbarkeit, Popups, Paginierung und die Berechtigungen muessen
  im Unternehmensnetz anhand freigegebener Faelle validiert werden.
- Nur aktive, autorisierte SSO-Sitzungen verwenden; keine Login-Automation,
  Cookie-Extraktion oder Umgehung von Freigaben. Browserprofil, Downloads,
  Fallberichte und FINs **nie** in GitHub, Releases oder CI hochladen.
- Bei einem HTML-/Anmeldeseiten-Download anstelle eines Anhangs wird ein Fehler
  protokolliert, keine HTML-Datei als vermeintlicher PDF-Bericht ausgegeben.
- Unvollständige Reiter und nicht erreichbare Dateianhänge bleiben in
  `abrufstatus.json` als Warnung bzw. Fehler sichtbar und dürfen bei der
  Ursachenbewertung nicht stillschweigend als vollstaendige Befundung gelten.
