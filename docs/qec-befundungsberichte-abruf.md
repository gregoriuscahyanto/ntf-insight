# QEC-Befundungsberichte in der FIN-/Fallanalyse

## Bedienung

Der QEC-Abruf befindet sich **nicht mehr in einer eigenen Navigationsseite**,
sondern direkt unter **Fälle / FIN → FIN / Fallanalyse**, unterhalb der Falltabelle.

- **Alle QEC-Berichte herunterladen** ruft alle geeigneten Tabellenfälle ab,
  auch bei aktivem Textfilter. Für größere Mengen fragt die App vorab nach.
- **Ausgewählte herunterladen** ruft nur die in der Tabelle markierten
  Zeilen ab; Mehrfachauswahl mit Strg bzw. Umschalt. Der Bezug zu einer
  vorhandenen QEC-Referenznummer bleibt erhalten, auch bei mehreren
  Schadteilfällen derselben FIN. Eine FIN ohne bekannte QEC-Referenz wird
  ausschließlich mit der vollständigen FIN und Pumpenbezeichnung gesucht.
- Die neue Spalte **QEC-Abrufdatum ↗** zeigt Datum/Uhrzeit des lokalen
  Abrufs. Anklicken öffnet den **Fallordner im Datei-Explorer**.
  Der Link wird nur angezeigt, wenn **vollständige FIN und QEC-Referenz**
  im gespeicherten JSON übereinstimmen.
- Die neue Spalte **TIPS-Fall** zeigt `Ja` bei einer fallbezogen verknüpften
  TIPS-Beobachtung, `FIN-Hinweis` bei bislang nur über dieselbe FIN bekannten
  TIPS-Vorgängen und `—` ohne erfassten Zusammenhang. Ein FIN-Hinweis
  ist **keine bestätigte Verknüpfung** zu einem Schadteilfall.

Der Abruf bleibt mit Microsoft Edge sichtbar. Automatische Klicks und
Seitenwechsel besitzen eine kurze, abbrechbare Sicherheitswartezeit.
Benutzer-ID und Passwort sind **dieselben wie beim QuickTest-Abruf**.
Nur dessen Betriebssystem-Tresoreintrag wird verwendet. Ist ein gültiges
Paar gespeichert, zeigen QuickTest und Fallanalyse den Status grün und
mit einem Text-Häkchen an. Die Eingabe/Änderung der Zugangsdaten erfolgt
weiterhin unter **QuickTest-Abruf**. Ohne gespeicherte Daten kann das
SSO manuell in Edge abgeschlossen werden. PING ID bleibt eine manuelle
Freigabe auf dem Smartphone.

## Sichere Zuordnung

QEC sucht anhand der Baureihe (FIN-Stellen 4–6) und der Endnummer
(letzte sechs Stellen). Der Download akzeptiert einen Treffer erst nach
Prüfung der **kompletten FIN** aus der Ergebnistabelle. Für einen aus
der Falltabelle gewählten QEC-Fall wird zusätzlich die **exakte
Referenznummer** geprüft; führende Nullen bleiben erhalten.
Unbekannte oder ungültige Referenzen werden nicht stillschweigend
durch FIN-weite Ergebnisse ersetzt.

## Neues lokales Ablageformat

```text
%USERPROFILE%\.ntf-insight\
  qec\
    <FIN>\
      abrufstatus.json                 # FIN-weiter technischer Abrufstatus
      ref_<QEC-Referenz>\
        qec.json                       # alle 5 QEC-Reiter in einer JSON-Datei
        anhaenge\
          <Anhang-ID>_<Dateiname>       # echte Originaldokumente
  edge-qec-profile\
```

`qec.json` enthält `schema_version=2`, die vollständige FIN,
QEC-Referenz, Sachnummer, Bezeichnung, Zeitpunkt `abgerufen_am_utc`
und das Array `abschnitte`. Die fünf Elemente heißen:

1. WE-Daten
2. Voranalysen
3. Stellungnahme Lieferant
4. Ergebnis + Nachanalyse
5. Historie

Jeder Abschnitt enthält `sichtbarer_text`, `felder` einschließlich
Optionen/Auswahltexte, `tabellen` mit Zeilen/Spalten und den einzelnen
Aufnahmezeitpunkt. `vollstaendige_reiter` kennzeichnet die Abdeckung.
Die Anhangliste samt Downloadstatus, sichtbaren Metadaten, Fehlern und
lokal gespeichertem Dateinamen steht unter `anhaenge` im selben JSON.
Das separate `anhangliste.json` wird **nicht mehr neu erzeugt**.
Ein `abrufstatus.json` je FIN bleibt für den technischen Batchstatus
und die Zuordnung mehrerer Referenzen vorhanden.

Neue Abrufe erzeugen **weder `laeufe/` noch
`01_WE-Daten/` bis `05_Historie/` und keine `ansicht.html`**.
Ältere Exporte bleiben unverändert erhalten; die Falltabelle kann deren
Datum aus den vorhandenen `daten.json`-Dateien weiterhin lesen.
Die Anwendung löscht ältere Befunde niemals automatisch. Sobald ein
neuer Abruf stattfindet, entsteht daneben `qec.json` im Fallordner.

Erfolgreich heruntergeladene Fall-JSONs und Anhänge werden außerdem
der lokalen Datenquellenarchivierung übergeben. Unbekannte Formate
bleiben Originaldateien ohne automatische fachliche Klassifizierung.

## Einschränkungen

- Die QEC-Detailreiter und Downloads benötigen den berechtigten
  Unternehmenszugang. Eine vollständige Live-Browserprüfung ist
  nur auf dem freigegebenen Firmenrechner möglich.
- Ausgeblendete Dialoge, nicht geöffnete Popups oder Inhalte anderer
  Frames sind nicht automatisch Teil eines Reiter-Snapshots.
- Interne QEC-Anhangweiterleitungen sind erlaubt, nicht aber
  fremde Domains, unerwartete Login-HTMLs oder ungültige PDFs.
- Die strukturierten Werte sind **Originalbefunde**, nicht automatisch
  eine sichere Ursache oder ein Lieferantenverschulden.
- **Keine echten FINs, QEC-Berichte, Kennwörter, Cookies oder
  Browserprofile in GitHub/CI/öffentliche Tickets hochladen.**
