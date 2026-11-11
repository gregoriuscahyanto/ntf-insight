# Diagnosis Viewer QuickTests: CLI-Download

Die CLI ist eine zusaetzliche Oberflaeche fuer den **bereits vorhandenen GUI-Scraper**
\`ntf_insight.acquisition.diagnosis_viewer.DiagnosisViewerDownloader\`.
Sie verwendet die gleichen PDF-Pruefungen, FIN-Validierung und Statusdateien.
Die **CLI** ueberspringt eine FIN nur, wenn ihr bisheriger Abrufstand
keine fehlenden PDF-Sitzungen ausweist. Eine FIN mit 1 von 14 gespeicherten
PDFs wird erneut geoeffnet, aber die vorhandene PDF nicht nochmals geladen.
Die **GUI** behaelt ihre bisherige 24-Stunden-Regel.
Bei parallelem VeDoc-/QuickTest-Abruf erfolgt die PING-ID-Anmeldung seriell.

## QuickTest-PDFs automatisch in JSON konvertieren

Die CLI konvertiert **standardmäßig nach dem Download** alle lokalen
QuickTest-PDFs der angefragten FINs mit dem bereits vorhandenen
NTF-Insight-XENTRY-Parser. Das gilt auch bei übersprungenen Downloads,
sofern die PDF im FIN-Ordner schon existiert. Original-PDFs bleiben
erhalten; JSONs liegen im parallelen Ordner
`diagnosis_viewer_quicktests_json/<FIN>/<PDF-Dateiname>.json`.

```powershell
# Üblicher PDF-Download inklusive JSON
ntf-insight-quicktests --eingabe .\fins.txt

# Nur PDFs herunterladen
ntf-insight-quicktests --eingabe .\fins.txt --ohne-json

# Ältere PDFs ausschließlich lokal in JSON wandeln, ohne Edge/SSO
ntf-insight-quicktests-json --ordner "data/processed/FIN Liste DCDC223 NTF PDF"
```

Alle Details zur FIN-Prüfung, zum SHA-256-Resume und zu Fehlern
stehen unter [QuickTest PDF → JSON](quicktest-pdf-json.md).

## Aufruf

**14-stellige Mercedes-Kurz-FINs:** Dieser CLI-Einstieg akzeptiert neben
17-stelligen FINs auch 14-stellige Fahrzeugkennungen. Er erfindet keinen
Herstellerpräfix. Wenn Diagnosis Viewer eine 17-stellige FIN anzeigt, muss
deren 14-stelliger Fahrzeugteil exakt der Eingabe entsprechen; sonst
werden keine fremden QuickTests übernommen. Ob das Portal die Kurz-FIN
serverseitig als Suchanfrage unterstützt, ist intern zu prüfen.
Der GUI-Standard bleibt zunächst auf die bisherige 17-stellige Eingabe
beschränkt.

Nach \`python -m pip install -e .\` im Projektverzeichnis:

\`\`\`powershell
ntf-insight-quicktests --eingabe .\fins.txt
\`\`\`

Alternativ direkt aus dem Repository:

\`\`\`powershell
py -3.11 scripts/diagnosis_viewer_quicktests.py --eingabe .\fins.txt
\`\`\`

Mit eigenem Ausgabeordner:

\`\`\`powershell
ntf-insight-quicktests --eingabe .\fins.txt --ausgabe "D:\NTF\quicktests"
\`\`\`

Eine FIN pro Zeile in der TXT-Datei (14 oder 17 Zeichen, ohne I/O/Q). Leerzeilen,
mit \`#\` kommentierte Zeilen, Komma-/Semikolon-Trennzeichen und Duplikate
werden unterstuetzt. Ungueltige FINs stoppen den Abruf vor dem Browserstart.

## Ablage

Standardmaessig relativ zum aktuellen Arbeitsverzeichnis:

\`\`\`text
data/
  processed/
    <bereinigter TXT-Name>/
      diagnosis_viewer_quicktests/
        <FIN-1>/
        <Datum_Quelle_Quicktest>.pdf
        abrufstatus.json
      <FIN-2>/
        <Datum_Quelle_Quicktest>.pdf
        abrufstatus.json
\`\`\`

Das gilt ausschliesslich fuer die neue CLI. Die GUI behält ihre bisherige
Ablage \`%USERPROFILE%\.ntf-insight\quicktests\<FIN>\`.
PDFs werden nicht ueberschrieben; identische Downloads werden anhand SHA-256
erkannt. \`abrufstatus.json\` haelt den letzten FIN-Abrufversuch, den Status,
PDF-Dateinamen, Fehler und Sitzungen ohne QuickTest fest. Nach jedem
erfolgreich gespeicherten PDF wird der Abrufstatus atomar aktualisiert.
Der Resume-Abgleich verwendet den Sitzungs-Zeitpunkt und die Quelle aus
dem PDF-Dateinamen sowie den `%PDF-`-Dateikopf. Bei mehrfach vorhandenen
gleichen Zeitstempel-/Quellenpaaren wird aus Sicherheitsgruenden kein
Dateiname als eindeutiger Sitzungsbeleg angenommen.

Sind im bisherigen Status beispielsweise 14 Sitzungen dokumentiert,
aber erst eine PDF gespeichert, beginnt der naechste CLI-Lauf erneut mit
der FIN. Der Downloader ueberspringt die eindeutig bereits lokal
gespeicherten Sitzungs-PDFs und versucht die fehlenden. Bei
**Altbeständen ohne Sitzungszaehler** bleibt das bisherige
Ueberspringen bei mindestens einer gueltigen PDF bestehen, da deren
Vollstaendigkeit nicht automatisch belegbar ist. Mit `--erneut` wird
die Wiederverwendung bestehender Sitzungs-PDFs deaktiviert.

## SSO / PING ID

Ein eigenes sichtbares Edge-Profil liegt unter
\`%USERPROFILE%\.ntf-insight\edge-diagnosis-viewer-cli-profile\`.
Die CLI prueft zunaechst gespeicherte Zugangsdaten aus dem vorhandenen
**NTF-Insight-Betriebssystem-Tresor** (dieselben Daten wie in der GUI).
Bei Bedarf werden Benutzer-ID und Passwort ausschliesslich auf der verifizierten
Mercedes-SSO-HTTPS-Domain eingegeben. Die PING-ID-Freigabe erfolgt stets
**manuell auf dem Smartphone**. Der Scraper wartet bis zur erfolgreichen
Weiterleitung; keine Automatisierung oder Umgehung der PING-ID.

Die QuickTest-CLI teilt eine OS-Dateisperre mit **allen sechs
NTF-Datenbeschaffungs-CLIs** unter
`%USERPROFILE%\.ntf-insight\sso-anmeldung.lock`. Damit beginnt
immer nur **eine** PING-ID-Anmeldung gleichzeitig. **Nach dem Login**
werden die Datenabrufe dennoch parallel ausgefuehrt. Die Datei enthaelt
keine FINs, Login-Daten oder Cookies; ein Prozessende gibt den Lock frei.

Falls keine sicheren Zugangsdaten vorhanden sind, kann die Anmeldung
interaktiv in Edge erfolgen. Weitere Optionen:

- \`--login-manuell\`: Betriebssystem-Tresor nicht lesen, Anmeldung in Edge.
- \`--passwort-abfragen\`: Benutzerkennung und Passwort fuer den laufenden
  Prozess im Terminal abfragen; Passwort wird maskiert und nicht gespeichert.
- \`--benutzer-id ID --passwort-abfragen\`: nur Passwort abfragen; keine
  Passwoerter als CLI-Argumente verwenden.
- \`--anmelde-timeout 600\`: mehr Zeit fuer SSO/PING ID einraeumen
  (Standard: 300 Sekunden).
- \`--profil PFAD\`: unabhaengiges lokales Edge-Profil waehlen.
- `--erneut`: auch FINs mit bereits vorhandener PDF erneut herunterladen.

**Wichtig:** Die CLI greift auf interne Unternehmenssysteme nur mit
bestehender Berechtigung zu. Nie reale FINs, QuickTests, Passwoerter oder
SSO-Cookies ins Repository oder in CI-Artefakte uebertragen. Live-Tests
im internen Unternehmensnetz und mit einer freigegebenen Test-FIN sind
erforderlich; Offline-Tests pruefen keine reale SSO-/PING-ID-Sitzung.

## Browserabsturz und SSO-Wiederanlauf

Die SSO-Erkennung prueft nach PING ID die sichtbare FIN-Suchmaske
auf der authentifizierten Diagnosis-Viewer-Domain, auch in einem
eingebetteten Frame oder neu geoeffneten Tab. Falls die Viewer-Seite
geladen ist, aber das Suchfeld laenger nicht erscheint, wird die
Seite hoechstens einmal neu geladen. PING ID bleibt vollstaendig manuell.

Verliert Playwright die Edge-Verbindung waehrend eines PDFs, bricht
der Downloader die Sitzungsschleife sofort ab. Er versucht maximal
**einen kontrollierten Neustart pro CLI-Lauf** mit demselben Profil.
Eine erneute PING-ID-Freigabe kann erforderlich sein. Falls auch der
Neustart fehlschlaegt, werden die Fehler in `abrufstatus.json`
protokolliert und der Abruf gestoppt. Gespeicherte PDF-Originale
werden nicht geloescht oder ueberschrieben.

**Wichtig:** Weder ein einmaliger Neustart noch das Anlegen eines
neuen Edge-Profils beweist die Ursache eines Browserabsturzes.
Bei wiederholten Abstuerzen zuerst Edge und den Firmenzugang pruefen.
Nicht waehrend eines laufenden Downloads `main` aktualisieren oder
die aktuell verwendete Python-Installation austauschen.

## Rueckgabewerte

- \`0\`: alle FIN-Abrufe ohne Downloadfehler abgeschlossen oder
  regelkonform uebersprungen; auch FINs ohne verfuegbare QuickTests.
- \`1\`: mindestens ein FIN-Abruf fehlgeschlagen oder abgebrochen.
- \`2\`: ungueltige Eingaben, lokale Fehler oder ein nicht startbarer Browser.
- \`130\`: durch Strg+C abgebrochen.

Alle sechs Datenquellen koordinieren ihre SSO-Anmeldungen mit einer
prozessuebergreifenden Sperre, auch aus getrennten Terminals. Jedes
Tool verwendet weiterhin sein eigenes Edge-Profil und Ausgabeordner.
