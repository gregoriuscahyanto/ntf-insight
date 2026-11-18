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


## Fehler bei PDF-Klick und neuem Fenster

Ein im Browser sichtbares PDF-Fenster ist noch kein gespeicherter
QuickTest. Der Downloader lauscht jetzt auf Downloads **am ursprünglichen
Diagnosis-Viewer-Tab und an neu geöffneten, von diesem Tab ausgelösten
PDF-Fenstern**. Bereits vorhandene Browser-Tabs werden nicht als
Belegquelle benutzt.

Die Statusmeldungen unterscheiden drei Fälle:

- **PDF gespeichert:** Die Datei wurde tatsächlich heruntergeladen,
  als PDF validiert und im FIN-Ordner gespeichert.
- **PDF-Fenster ohne Download:** Edge hat ein zusätzliches Fenster
  geöffnet, aber innerhalb des Download-Timeouts kein Download-Ereignis
  ausgelöst. Prüfen, ob Edge PDFs intern anzeigt statt sie
  herunterzuladen. Der Downloader stoppt den aktuellen FIN-Lauf, um
  nicht alle anderen QuickTest-Buttons sinnlos zu wiederholen.
- **Viewer-Tab geschlossen, Browser noch verbunden:** Der Verlust
  betrifft nur das Tab. Es wird **höchstens einmal** ein neues
  Viewer-Tab geöffnet und die FIN erneut geprüft. Bereits gespeicherte
  Sitzungs-PDFs werden weiterhin erkannt.
- **Edge-Verbindung verloren:** Der Browser oder Playwright hat die
  Verbindung tatsächlich verloren. Der vorhandene einmalige
  Browser-Neustart bleibt aktiv; weitere Abfragen werden bei
  wiederholtem Absturz gestoppt.

QEC und QuickTests nutzen standardmäßig **verschiedene Edge-Profile**,
und die gemeinsame SSO-Sperre koordiniert nur den PING-ID-Login.
Ein Browserabsturz direkt nach dem PDF-Klick ist daher **kein Beleg**
einer PING-ID-Kollision. Bei parallelen Browserproblemen testweise
die GUI-Parallelität auf **1** stellen und prüfen, ob die Ursache
danach noch auftritt. Keine internen PDFs, Cookies oder vollständigen
FINs an GitHub oder CI übermitteln.


## Inline-PDFs im Edge-Fenster (Download ohne Download-Event)

Bei bestimmten Diagnosis-Viewer-Sitzungen oeffnet der PDF-Button einen neuen
Edge-Tab mit der integrierten PDF-Vorschau. Ein solches Fenster bedeutet nicht,
dass Playwright eine PDF-Datei heruntergeladen hat. Das kann erklaeren, warum
ein Popup erkannt wird, aber PDF 1/N weiterhin fehlschlaegt.

Der CLI-Downloader hat deshalb drei streng begrenzte Alternativen:

1. **Normales Download-Ereignis:** unveraendert erste Wahl. Die Original-PDF
   wird anhand ihres Dateikopfes geprueft und atomar gespeichert.
2. **Beobachtete PDF-Netzwerkantwort:** Bereits beim Klick wird nur im aktuellen
   Browserkontext auf PDF-Antworten gehoert. Eine Datei wird ausschliesslich
   dem gerade angeklickten Viewer-Tab oder einem von ihm geoeffneten PDF-Tab
   zugeordnet und nur mit nachgewiesenen PDF-Bytes uebernommen.
3. **Bereits geoeffnete PDF-Vorschau:** Wenn kein Download-Ereignis erscheint,
   kann die exakt im Popup geoeffnete HTTPS-Adresse einmalig nachgeladen
   werden, sofern sie auf dem **gleichen verifizierten Diagnosis-Viewer-Host**
   liegt. Auch ein vorhandenes Same-Origin-Blob kann lokal im Browser
   ausgelesen werden. Andere Hosts, fremde Weiterleitungen, Skript-/Datei-
   URLs und Login-HTML bleiben ausgeschlossen.

Jede Variante durchlaeuft dieselbe Dateisignatur-, Groessen- und
Sitzungs-Praefix-Pruefung. Es werden keine Cookies, Tokens oder
Anhang-URLs in Logdateien geschrieben. Bereits gespeicherte QuickTests
bleiben bei einem weiteren Resume erhalten.

Die Meldung **PDF-Vorschaufenster erkannt, aber kein Download gestartet und
keine gueltige PDF-Netzwerkantwort erhalten** bedeutet, dass selbst nach
diesen Versuchen keine verifizierte Original-PDF vorlag. Dies ist
**nicht automatisch ein SSO-Fehler** und darf niemals als erfolgreiche
PDF-Speicherung markiert werden.

In Edge im QuickTest-Scraper-Profil kann die Einstellung
**PDF-Dateien immer herunterladen** unter
edge://settings/content/pdfDocuments geprueft werden. Unternehmensrichtlinien
gehen vor; die App aendert weder Browserrichtlinien noch den SSO-Status.
Wenn auch mit aktivierter PDF-Download-Einstellung dieselbe erste Sitzung
einen Tab- oder Prozessabsturz erzeugt, fuer eine Diagnose nur die
**bereinigten Statusmeldungen und das Fehlerstadium** weitergeben,
niemals vertrauliche PDF-Originale, Cookie-Werte, URLs mit Tokens oder FINs.


## Diagnose: Edge schliesst sich beim ersten PDF-Download

Ein erkannter PDF-Popup-Tab beweist noch keinen abgeschlossenen Download.
Wenn sich **der komplette Edge-/Playwright-Kontext beim PDF-Klick oder
beim PDF-Speichern beendet**, kann auch ein nativer Edge-Absturz
vorliegen. Insbesondere mit **wiederverwendeten persistenten
Edge-Profilen** ist ein entsprechender Windows-/Edge-152-Fall
dokumentiert (Playwright-Issue #42506, MicrosoftEdge/DevTools #461).
Ein solches Problem kann auch ohne das interne Portal und ohne SSO
auftreten. Das ist eine **moegliche Ursache**, keine Diagnose der
lokalen Edge-Version.

### 1. Isolierte lokale Probe (ohne Unternehmensdaten)

Nach Installation der aktualisierten App in PowerShell:

\`\`\`powershell
ntf-insight-edge-probe
\`\`\`

Die Probe laedt eine **ausschliesslich synthetische PDF-Datei**
von einer lokalen \`data:\`-Adresse herunter. Sie startet Microsoft Edge
in **zwei separaten Python-Prozessen** mit einem **neuen Wegwerfprofil**,
das beim zweiten Start wiederverwendet wird. Bei einem Fehler im
zweiten Lauf testet sie zusaetzlich ein neues Kontrollprofil.
Es wird **keine** FIN, Loginseite, PING ID oder sonstige Firmenadresse
geoeffnet. Das bereits produktiv benutzte QuickTest-Edge-Profil und
gespeicherte QuickTest-Originale werden nicht beruehrt.

Die Statusausgabe enthaelt nur Phasen, Exitcodes und eine vorsichtige
Interpretation; Browser-Cookies und PDF-/Portaldaten werden nicht
erfasst. Ein Windows-Absturzcode wie \`3221225477\` kann auf einen
nativen Edge-Absturz hinweisen. Bestehen beide Testlaeufe, bleibt
ein **portal-/PDF-viewer-spezifisches** Problem moeglich.

### 2. Ohne neue Version: frisches Edge-Profil fuer QuickTests testen

In der Lightweight-App unter **QuickTests → Einstellungen → Eigener
Edge-Profilordner** einen **neuen lokalen Ordnerpfad** eingeben
(z. B. unter \`%LOCALAPPDATA%\\NTF-Insight\\edge-quicktests-test\`).
Das Feld akzeptiert einen neuen, noch nicht existierenden Pfad.
Nicht denselben Ordner wie bei QEC oder einem anderen laufenden Job
verwenden. Ausgabeverzeichnis und FIN-/Resume-TXT unveraendert lassen.
Die neue Edge-Sitzung benoetigt eine **erneute manuelle PING-ID-Freigabe**.
Es werden keine bestehenden Edge-Profile, PDFs oder Checkpoints geloescht.

Zunaechst nur **eine** Datenquelle parallel starten. Wenn bereits
ein synthetischer Download mit frischem Profil abstuerzt, Edge-Version
unter \`edge://settings/help\` sowie
\`edge://policy\` durch die Unternehmens-IT pruefen lassen.
Die PDF-Option unter \`edge://settings/content/pdfDocuments\`
darf nur geaendert werden, wenn die Unternehmenseinstellungen dies
erlauben. Sicherheitsrichtlinien nicht umgehen oder abschalten.

### 3. Neue Browser-Phasen im Status

Beim QuickTest-Absturz gibt der Downloader die letzte erkannte
Phase aus, z. B. **PDF-Klick**, **PDF-Download erhalten** oder
**PDF-Speichern**. Ein unerwartetes \`BrowserContext.close\`-Ereignis
wird von einem normalen Programmende getrennt.
Damit laesst sich unterscheiden, ob das Problem beim Laden des
PDF-Viewers oder erst beim Speichern des Downloads entsteht.
Der alte automatische Wiederanlauf kann einen nativen Edge-Fehler
nicht beseitigen; die vorhandenen PDF-Dateien bleiben per Resume
erhalten.

**Datenschutz:** Bei einer Fehlermeldung vor dem Teilen immer die
vollstaendige FIN, persoenliche Angaben, PDF-Inhalte und URLs mit
Tokens entfernen. Nur Edge-Version, Phasenmeldung und Probe-Exitcodes
werden fuer die technische Eingrenzung benoetigt.

Weitere Referenzen:
- https://github.com/microsoft/playwright/issues/42506
- https://github.com/MicrosoftEdge/DevTools/issues/461

