# Diagnosis Viewer: QuickTest-PDF-Abruf

In **QuickTest-Abruf** FINs eintragen (eine pro Zeile), Ordner wählen und
**QuickTests abrufen** klicken. Alternativ die FINs aus den lokalen NTF-Fällen
übernehmen oder eine TXT/CSV-Datei laden.

## SSO und PING ID

Die zusätzliche Anleitung stellt folgende, im Login-HTML belegte Schritte dar:

1. Playwright startet ausschließlich das bereits installierte **Microsoft Edge**
   über \`channel="msedge"\` im sichtbaren Modus. Es installiert keinen zweiten Browser.
2. Die Anwendung öffnet den Diagnosis Viewer mit der FIN in der URL. Beim
   erstmaligen Besuch auf **SSO** klicken (automatisch, wenn der Button erscheint).
3. Bei einer erforderlichen neuen Anmeldung kann die App die **Benutzer-ID**
   in \`#userid\` ausfüllen und **Weiter** (\`#next-btn\`) klicken.
4. Danach wird das Passwort in \`#password\` eingetragen und **Anmelden**
   (\`#loginSubmitButton\`) geklickt. Die Anmeldung wird nur auf der
   überprüften HTTPS-Domain \`login.mercedes-benz.com\` automatisiert.
5. Die Freigabe per **PING ID** bleibt zwingend beim Benutzer und erfolgt
   auf dessen Smartphone. Die Anwendung wartet bis zur automatischen
   Weiterleitung zum Diagnosis Viewer, statt voreilig eine zweite Suche zu starten.
6. Die App füllt dort \`input[name="finVin"]\`, klickt einmal auf **Search**,
   sucht aktiv anklickbare \`span.cursor-pointer:has(svg.lucide-file-down)\`
   und speichert die verfügbaren PDF-QuickTests.

Falls PING ID mehr als etwa zehn Sekunden benötigt, wartet die App weiter
(bis zu vier Minuten). Abgelaufene oder fehlerhafte SSO-Sitzungen können
weiterhin manuell in Edge abgeschlossen werden.

## Zugangsdaten und Sicherheit

- Beim ersten Abruf können **Benutzer-ID** und **Passwort** in der App
  eingegeben werden. Das Passwortfeld ist maskiert und wird nach Start geleert.
- Ist „Zugangsdaten im Windows-Anmeldeinformationsmanager speichern“
  ausgewählt, werden sie ausschließlich im geschützten Betriebssystem-Tresor
  gespeichert; kein Klartext in Konfigurationsdateien oder Protokollen.
- Bei einem Folgeabruf kann das Passwortfeld leer bleiben, wenn passende
  Zugangsdaten sicher gespeichert sind. Die PING-ID-Freigabe kann dennoch
  erneut verlangt werden.
- „Zugangsdaten löschen“ entfernt die gespeicherten Einträge.
- Die manuelle Anmeldung in Edge ohne gespeicherte Zugangsdaten bleibt möglich
  (beide Loginfelder leer lassen).
- Die automatische Passwortverwendung sollte den internen IT-/SSO-Richtlinien
  entsprechen. Wenn der Passwort-Tresor gesperrt ist, gibt es keinen unsicheren
  Datei-Fallback.

Für bestehende Python-/Wheel-Installationen ist das Zusatzpaket \`keyring\`
erforderlich: \`python -m pip install keyring\` in der **gleichen**
Python-Umgebung, in der NTF Insight ausgeführt wird. Neu gebaute
NTF-Insight-Pakete bringen \`keyring\` als Abhängigkeit mit.

## Ablage und 24-Stunden-Regel

Standardordner: \`%USERPROFILE%\.ntf-insight\quicktests\<FIN>\`.

- Pro FIN ein Unterordner mit PDF-Dateien und \`abrufstatus.json\`.
- Die Tabelle wird **beim Öffnen der Seite, beim Ordnerwechsel und nach einem Abruf**
  aus **allen gültigen FIN-Unterordnern** aufgebaut – unabhängig von der
  aktuellen FIN-Liste. Über **„Bestand aktualisieren“** wird sie manuell
  neu eingelesen.
- Auch ältere FIN-Verzeichnisse, die nur PDF-Dateien und noch keine
  \`abrufstatus.json\` enthalten, erscheinen mit der Anzahl aller PDFs.
  Das Datum lautet dann **„Nicht dokumentiert“**, da das Dateidatum kein
  zuverlässiges Datum des tatsächlichen Abrufversuchs ist.
- Die App merkt sich den **letzten Abrufversuch**, nicht nur erfolgreiche
  Downloads, und zeigt ihn als **„Letzter Abruf“** in der GUI-Tabelle.
- Liegt der letzte Versuch weniger als 24 Stunden zurück, wird diese FIN
  standardmäßig **übersprungen**, ohne erneut Edge anzusteuern.
- Für einen notwendigen gezielten Wiederholungsversuch gibt es die explizite
  Option **„24-Stunden-Sperre einmalig übergehen“**.
- Zwischen automatisierten Browseraktionen (Navigation, SSO-Klicks,
  Eingaben, Suche und Download-Klicks) wird ein **Mindestabstand von 1,5 s**
  eingehalten. Zusätzlich wartet Playwright auf erfolgreiche Navigation,
  die richtigen FIN-Suchergebnisse und abgeschlossene PDF-Downloads.
  Diese begrenzte Abrufrate dient Stabilität und Rücksicht auf das System;
  sie ist **keine Umgehung eines Bot-Schutzes** und bietet keine Garantie,
  dass die Webseite den Abruf zulässt.
- PDF-Dateien werden am Header geprüft, bereits vorhandene gleiche Dateien
  nicht erneut gespeichert; fehlerhafte Dateien werden nicht importiert.
- Neue Dateien werden mit SHA-256-Provenienz durch die bestehende lokale
  Importpipeline archiviert und der jeweiligen FIN zugeordnet.

Das separate Edge-Profil liegt unter
\`%USERPROFILE%\.ntf-insight\edge-diagnosis-viewer-profile\`.
Die Unternehmensrichtlinien können eine erneute SSO-Anmeldung verlangen.

## Grenzen und Prüfbedarf

- Es wurde **kein** Zugriff auf den internen Produktivserver oder echte
  PING-ID-Bestätigungen zum Testen verwendet. Die HTML-Auszüge zeigen
  die Selektoren, nicht das vollständige dynamische Login-Verhalten.
- Falls der Diagnosis Viewer HTML statt PDF herunterlädt, muss der
  **Downloadtyp PDF** in den Benutzereinstellungen ausgewählt werden.
- Die Ergebnis-Paginierung und Rollen/Berechtigungen sollten anhand einer
  freigegebenen Test-FIN im Unternehmensnetz überprüft werden.
- Keine echten FINs, Passwörter, SSO-Cookies, QuickTest-Berichte oder
  interne Daten in GitHub, CI-Artefakte oder Releasepakete übertragen.
