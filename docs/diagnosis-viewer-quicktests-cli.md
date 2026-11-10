# Diagnosis Viewer QuickTests: CLI-Download

Die CLI ist eine zusaetzliche Oberflaeche fuer den **bereits vorhandenen GUI-Scraper**
\`ntf_insight.acquisition.diagnosis_viewer.DiagnosisViewerDownloader\`.
Sie verwendet die gleichen PDF-Pruefungen, FIN-Validierung und Statusdateien.
Die **CLI** ueberspringt eine FIN nur, wenn im FIN-Ausgabeordner bereits
eine lesbare PDF liegt; die **GUI** behaelt ihre bisherige 24-Stunden-Regel.
Bei parallelem VeDoc-/QuickTest-Abruf erfolgt die PING-ID-Anmeldung seriell.

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
PDF-Dateinamen, Fehler und Sitzungen ohne QuickTest fest. Wiederholte CLI-Aufrufe ueberspringen eine FIN **nur**, wenn eine gueltige
PDF-Datei im entsprechenden FIN-Unterordner vorhanden ist. Die PDF muss
mit der Kennung %PDF- beginnen. Ein `abrufstatus.json` mit Status Fehler,
Keine Quicktests oder gerade erfolgt ohne PDF wird *nicht* uebersprungen.
Mit `--erneut` werden auch FINs mit vorhandenen PDFs nochmals geladen.

## SSO / PING ID

Ein eigenes sichtbares Edge-Profil liegt unter
\`%USERPROFILE%\.ntf-insight\edge-diagnosis-viewer-cli-profile\`.
Die CLI prueft zunaechst gespeicherte Zugangsdaten aus dem vorhandenen
**NTF-Insight-Betriebssystem-Tresor** (dieselben Daten wie in der GUI).
Bei Bedarf werden Benutzer-ID und Passwort ausschliesslich auf der verifizierten
Mercedes-SSO-HTTPS-Domain eingegeben. Die PING-ID-Freigabe erfolgt stets
**manuell auf dem Smartphone**. Der Scraper wartet bis zur erfolgreichen
Weiterleitung; keine Automatisierung oder Umgehung der PING-ID.

Die QuickTest-CLI teilt eine OS-Dateisperre mit der VeDoc-Historien-CLI
unter `%USERPROFILE%\.ntf-insight\sso-anmeldung.lock`. Damit beginnt
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

## Rueckgabewerte

- \`0\`: alle FIN-Abrufe ohne Downloadfehler abgeschlossen oder
  regelkonform uebersprungen; auch FINs ohne verfuegbare QuickTests.
- \`1\`: mindestens ein FIN-Abruf fehlgeschlagen oder abgebrochen.
- \`2\`: ungueltige Eingaben, lokale Fehler oder ein nicht startbarer Browser.
- \`130\`: durch Strg+C abgebrochen.

VeDoc-Historie und QuickTests koordinieren ihre Anmeldungen mit einer
prozessuebergreifenden Sperre, auch aus getrennten Terminals. Beide
Tools verwenden weiterhin getrennte Edge-Profile und Ausgabeordner.
Andere Datenquellen sind noch nicht in diese Sperre eingebunden.
