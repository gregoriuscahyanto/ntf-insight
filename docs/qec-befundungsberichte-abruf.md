# QEC-Tool: Befundungsberichte und Fallinformationen abrufen

Diese Funktion ist im Branch `feature/qec-befundungsberichte-playwright` als
**QEC-Abruf** in NTF Insight verfügbar. Sie arbeitet **neben** dem
Diagnosis-Viewer-QuickTest-Abruf (unabhängige Edge-Profile und Threads).

## Voraussetzung und Bedienung

- Das System muss Microsoft Edge, Playwright und einen berechtigten Zugang zum
  QEC-Tool im Mercedes-Benz-Unternehmensnetz besitzen. Benutzer-ID und Passwort
  koennen optional in der QEC-Abruf-Maske eingegeben werden. Playwright fuellt die
  Felder **nur auf https://login.mercedes-benz.com** aus; die PING-ID-Bestaetigung
  erfolgt stets manuell am Smartphone. Alternativ beide Felder leer lassen und
  die komplette SSO-Anmeldung im sichtbaren Edge-Fenster selbst eingeben.
- Die optionale Einstellung zum Merken speichert die QEC-Zugangsdaten ausschliesslich
  im Betriebssystem-Tresor unter einem separaten QEC-Eintrag. Ohne Zustimmung
  findet keine dauerhafte Passwortspeicherung statt. Kein Klartext-Fallback.
- In **QEC-Abruf** FINs zeilenweise eintragen, aus lokalen Fällen uebernehmen
  oder eine TXT-/CSV-Datei laden. Pro Zeile ist optional eine Sachnummer möglich:
  `17-STELLIGE-FIN;SACHNUMMER`. Die Anzeige der FIN erfolgt **nicht** im Repo.
- Standardmäßig werden nur Schadteile gesucht, deren QEC-Bezeichnung
  Kühlmittelpumpe, Umwälzpumpe oder `coolant pump` enthaelt. Bei abweichender
  Benennung kann der Filter deaktiviert und/oder die exakte Sachnummer angegeben werden.
- **QEC-Daten und Berichte abrufen** klicken, SSO/PING ID bei Bedarf bestaetigen
  und das **Ablaufprotokoll** beobachten. Nach der Anmeldung muss dort der
  Schritt **QEC: Anmeldung abgeschlossen; Schadteilsuche wird geoeffnet.**
  erscheinen. Anschliessend werden die Suchfelder ausgefuellt und Filtern geklickt.
  Die fallbezogenen Ergebnisse im lokalen Ordner pruefen.
- Unter **QuickTest-Abruf** können unabhängig davon Diagnose-PDFs fuer die
  gleichen FINs heruntergeladen werden. Beide Downloads können mit
  unterschiedlichen Profilen nebeneinander laufen.

## Abfolge laut gelieferter QEC-Anleitung

1. **Fuer jede neue FIN und jeden weiteren Schadteil-Treffer** die
   QEC-Hauptansicht neu oeffnen. Laut Anleitung zeigt QEC andernfalls
   moeglicherweise noch den vorherigen Vorgang. Nach SSO wird neben dem
   Navigationslink auch die Hauptseite `qecentry.qec` erkannt. Falls der Link
   im HTML noch fehlt, wird der aus dem Beispiel bekannte gleichnamige
   QEC-Navigationspfad verwendet.
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
- Nur aktive, autorisierte SSO-Sitzungen verwenden. Das automatische Ausfuellen
  des Mercedes-SSO-Formulars umgeht **keine** Anmeldung und **keine** PING-ID-Freigabe.
  Keine Cookie-Extraktion oder Umgehung von Freigaben. Browserprofil, Downloads,
  Fallberichte und FINs **nie** in GitHub, Releases oder CI hochladen.
- Bei einem HTML-/Anmeldeseiten-Download anstelle eines Anhangs wird ein Fehler
  protokolliert, keine HTML-Datei als vermeintlicher PDF-Bericht ausgegeben.
- Unvollständige Reiter und nicht erreichbare Dateianhänge bleiben in
  `abrufstatus.json` als Warnung bzw. Fehler sichtbar und dürfen bei der
  Ursachenbewertung nicht stillschweigend als vollstaendige Befundung gelten.

## Wenn "Keine passenden Schadteile" trotz manuellem QEC-Treffer erscheint

Der Downloader wartet nach **Filtern** auf die bestaetigte Serverantwort. Die
QEC-Suchergebnisse gelten erst als geladen, wenn die Seite die abgesendeten
BR-/Endnummer-Werte in den HTML-Formularattributen wiederholt und entweder
eine Ergebnistabelle oder eine explizite Meldung **0 Treffer** enthaelt.
Eine noch leere Suchmaske gilt **nicht** als negativer Suchnachweis.

Die Datei `<Speicherort>/qec/<FIN>/abrufstatus.json` enthaelt jetzt unter
`suchdiagnose` (nur lokal) folgende Felder:

- `bestaetigt`: Ob die Suchantwort eindeutig geladen wurde.
- `qec_trefferzahl`: Anzahl laut QEC-Meldung, sofern auslesbar.
- `sichtbare_zeilen`: Anzahl aktuell erkennbarer Tabellenlinks.
- `fin_identisch`: Treffer mit **vollstaendig** gleicher FIN (WHC + BR + BM + Werk + Endnummer).
- `pumpen`: Davon durch die QEC-Benennung als Pumpe identifizierbar.
- `sachnummer`: Treffer nach aktivem Pumpenfilter und optionalem Sachnummerfilter.

Beispiel: `qec_trefferzahl=2`, `fin_identisch=0` bedeutet, dass in der
angezeigten Liste zwar Treffer vorhanden sind, aber keiner die komplette FIN
belegt. QEC sucht laut Anleitung nur mit Baureihe und Endnummer; ein passender
BR-/Endnummer-Wert allein beweist keine identische FIN. Deshalb wird keine
fremde Referenznummer automatisch dem Fahrzeug zugeordnet.

Wenn die Suche nach Ablauf der Wartezeit nicht eindeutig bestaetigt wird,
erzeugt der Downloader **Status Fehler**, statt "Keine passenden Schadteile".
Wenn mehr Treffer als sichtbare Zeilen gemeldet werden, wird auf moegliche
weitere Ergebnisseiten hingewiesen. Eine vollstaendige Paginierung ist noch
nicht anhand echter Firmen-Suchseiten verifiziert.

Bei Rueckfragen nur die Werte aus `suchdiagnose` und die letzten anonymisierten
Protokollzeilen mitteilen. Keine echten FINs, Anhaenge oder HTML-Seiten in GitHub
oder oeffentlichen Tickets ablegen.

## Wenn nach der Anmeldung nichts passiert

- Das Ablaufprotokoll unterscheidet **Warte auf SSO**, **QEC-Hauptansicht erkannt**,
  **Schadteilsuche wird geoeffnet**, **Suchfelder erkannt** und **Filtern**.
  Erst wenn alle Schritte sichtbar sind, wurde die FIN-Suche gestartet.
- Wenn die Hauptansicht offen ist, aber das Protokoll auf SSO wartet: Sicherstellen,
  dass die Webseite im von der App gestarteten Edge-Fenster und nicht in einem
  anderen Browserprofil geoeffnet ist. Pruefen, ob die URL nach der Anmeldung
  die QEC-Anwendungsdomain und `qecentry.qec` enthaelt.
- Wenn die Suche nicht geladen werden kann, gibt der Downloader jetzt eine
  konkrete Meldung ueber fehlende Suchfelder aus. Berechtigungen, abweichende
  Reiter und Live-SSO sind nur im Unternehmensnetz verifizierbar.
- Fuer Rueckfragen bitte nur **Statusmeldungen ohne FIN und sonstige Falldaten**
  weitergeben. Niemals Passwort, Cookies, SSO-Tokens oder interne HTML-Dumps senden.

## Anhangdownload: interne Weiterleitungen und Befundvollstaendigkeit

Bei QEC-Anhaengen bezeichnet der Link `displayPruefberichtFile.qec?attachmentId=...`
nur den **Einstiegspunkt**. Der Server kann intern auf eine andere QEC-Downloadaktion
weiterleiten. Die automatisierte Pruefung erwartet deshalb nicht mehr, dass
auch die **finale Antwort-URL** genau diese Dateibezeichnung traegt. Sie akzeptiert
nur HTTPS-Antworten innerhalb der erlaubten `/qec-access/`-Anwendung auf der
urspruenglichen QEC-Domain. Loginseiten, HTML-Antworten und falsch deklarierte
PDFs sind ausdruecklich **keine** gueltigen Befundungsberichte.

Der Abruf versucht zuerst eine Dateianforderung im eingeloggten Edge-Browserkontext
(mit dem QEC-Popup als Referer). Falls daraus keine nutzbare Datei entsteht,
klickt Playwright den Original-Anhanglink im sichtbaren Edge-Popup als Fallback.
Berechtigungen und PING ID werden nicht umgangen. Das Ablaufprotokoll zeigt
diesen zweiten Versuch separat an. Kann Edge die Datei ebenfalls nicht laden,
bleibt der Anhang im lokalen Manifest als Fehler sichtbar.

Zu jeder QEC-Referenz entsteht jetzt lokal `ref_<Referenz>/anhangliste.json`.
Sie enthaelt eindeutige Anhang-IDs, sichtbare Popup-Metadaten und den Downloadstatus
sowie ggf. den lokal gespeicherten Dateinamen. Erfolgreich gespeicherte Anhaenge
werden bei weiteren Reiter-Popups nicht erneut angefordert. Die
Datei `abrufstatus.json` zeigt weiterhin die tatsaechlich gespeicherten
Anhaenge unter `anhaenge`, Fehler unter `fehler`.

Die Reiter-Snapshots `daten.json` enthalten zusaetzlich zu `sichtbarer_text`
und `felder` jetzt die strukturierten `tabellen` (sichtbare Zeilen und Zellen).
Bei Formularfeldern werden, wo DOM-seitig vorhanden, `optionwert`,
`beschriftung` und `auswahltext` abgelegt. Dadurch bleibt beispielsweise die
ausgewaehlte SSL-Endbefund-Bezeichnung neben ihrem internen Code erhalten.
`ansicht.html` ist weiterhin eine **ausfuehrungsfreie, vereinfachte
Offline-Ansicht** – kein Original-QEC-HTML mit Scripts und Session-Tokens.

### Grenzen der Vollstaendigkeitspruefung

Ein Archiv mit nur `ansicht.html`/`daten.json` kann mit den gespeicherten
Werten abgeglichen werden, beweist aber **nicht**, dass jede urspruengliche
QEC-DOM-Information gespeichert wurde. Bildinhalte, fremde Frames,
nicht geoeffnete Dialoge, ausgeblendete Bereiche und Dateien hinter den
Anhanglinks werden damit nicht ersetzt. Bei unvollstaendigen Anhaengen darf
ein Fall nicht als vollstaendig befundet gewertet werden.

Fuer einen Folgetest genuegen anonymisierte Angaben:
Zahl der `anhaenge`, Zahl der `fehler`, Statuswerte der
`anhangliste.json` sowie die letzten Protokollschritte.
Echte FINs, Personen, Befundtexte, PDFs oder interne QEC-HTMLs nicht in
GitHub/CI hochladen.
