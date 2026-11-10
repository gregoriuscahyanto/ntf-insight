# Diagnosis Viewer QuickTests: CLI-Download

Die CLI ist eine zusaetzliche Oberflaeche fuer den **bereits vorhandenen GUI-Scraper**
\`ntf_insight.acquisition.diagnosis_viewer.DiagnosisViewerDownloader\`.
Sie verwendet die gleichen PDF-Pruefungen, die FIN-Validierung, die 24-Stunden-Sperre,
die Statusdateien und die SSO-/PING-ID-Wartelogik. Die GUI selbst bleibt unveraendert.

## Aufruf

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

Eine FIN pro Zeile in \`fins.txt\` (17 Zeichen, ohne I/O/Q). Leerzeilen,
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
PDF-Dateinamen, Fehler und Sitzungen ohne QuickTest fest. Wiederholte Aufrufe
ueberspringen FINs, deren letzter Versuch weniger als 24 Stunden zurueckliegt.
Mit \`--erneut\` kann diese Sperre gezielt aufgehoben werden.

## SSO / PING ID

Ein eigenes sichtbares Edge-Profil liegt unter
\`%USERPROFILE%\.ntf-insight\edge-diagnosis-viewer-cli-profile\`.
Die CLI prueft zunaechst gespeicherte Zugangsdaten aus dem vorhandenen
**NTF-Insight-Betriebssystem-Tresor** (dieselben Daten wie in der GUI).
Bei Bedarf werden Benutzer-ID und Passwort ausschliesslich auf der verifizierten
Mercedes-SSO-HTTPS-Domain eingegeben. Die PING-ID-Freigabe erfolgt stets
**manuell auf dem Smartphone**. Der Scraper wartet bis zur erfolgreichen
Weiterleitung; keine Automatisierung oder Umgehung der PING-ID.

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
- \`--erneut\`: den lokalen 24h-Schutz fuer diesen Lauf uebergehen.

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

Die parallelen CLI-Skripte fuer VeDoc-DCDC223, VeDoc-Fahrzeugcodes und
Diagnosis-Viewer-WEM bleiben unabhaengig. Alle Dienste koennen die
gleiche FIN-TXT-Datei verwenden; fuer gleichzeitig laufende Browser
sollte jedes Skript sein eigenes Profil verwenden.
