# Diagnosis Viewer: QuickTest-PDF-Abruf

Die Bedienung befindet sich jetzt ausschließlich unter **Fälle / FIN →
FIN / Fallanalyse**. Der separate Navigationseintrag **QuickTest-Abruf** wurde
entfernt.

Die bestehende Falltabelle bietet links eine **Auswahl-Checkbox je Fall** und
rechts die Spalte **„QuickTest-Abruf-Datum“**. Ein vorhandenes Abrufdatum
erscheint als **anklickbarer Link auf den lokalen FIN-Ordner**. Ohne lokales
Abrufprotokoll steht dort \`n.a.\`; existiert bereits ein PDF-Ordner, kann
auch \`n.a.\` als Ordnerlink verwendet werden.

Unter der Tabelle stehen:

- **„Alle Quicktests herunterladen/aktualisieren“**: sämtliche in der
  Falltabelle enthaltenen FINs, unabhängig von Sortierung und Filter;
  gleiche FINs werden nur einmal abgerufen.
- **„Quicktests für ausgewählte Fälle herunterladen/aktualisieren“**:
  ausschließlich die über Checkboxen markierten Fälle. Die Taste ist bis
  zur ersten Auswahl deaktiviert.
- **„Abbrechen“** für laufende Downloads und eine bewusst aktivierbare
  Option zur einmaligen Umgehung der lokalen 24-Stunden-Sperre.

Benutzer-ID und Passwort, „Sicher speichern“ und „Anmeldedaten löschen“
befinden sich ebenfalls unter der Falltabelle. Nach dem PDF-Download
werden die Dateien über den bestehenden Quellenimport archiviert und die
Fallanalyse aktualisiert, ohne auf den separaten QuickTest-Explorer umzuschalten.

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
- Die separate frühere Bestandsansicht wurde in die **Spalte „QuickTest-Abruf-Datum“**
  der Falltabelle überführt. Die Datumsanzeige wird **beim Öffnen der Fallanalyse
  und nach jedem Abruf**
  aus **allen gültigen FIN-Unterordnern** gelesen, die zu einer FIN in der
  Falltabelle gehören. Dateien anderer FINs bleiben selbstverständlich im
  Speicher, werden aber ohne zugehörigen Fall nicht als neue Fallzeilen erzeugt.
- Auch ältere FIN-Verzeichnisse mit PDFs ohne \`abrufstatus.json\` werden
  erkannt. Das Datum lautet dann \`n.a.\`, kann bei vorhandenem Ordner aber
  angeklickt werden. Das PDF-Dateidatum wird nicht als Abrufdatum ausgegeben.
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
