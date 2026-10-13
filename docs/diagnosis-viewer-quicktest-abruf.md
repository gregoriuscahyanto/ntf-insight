# Diagnosis Viewer: QuickTest-PDF-Abruf

In **QuickTest-Abruf** FINs eintragen (eine pro Zeile), Ordner wählen und
**QuickTests abrufen** klicken. Alternativ die FINs aus den lokalen NTF-Fällen
übernehmen oder eine TXT/CSV-Datei laden.

## Ablauf

1. Playwright startet ausschließlich das bereits installierte **Microsoft Edge**
   über \`channel="msedge"\`, sichtbar mit eigenem lokalen Profil.
2. Die Anwendung öffnet
   \`https://app.diagviewer.prod.gspp-eu.cloud.corpintra.net/search?fin=<FIN>&sources=XD%2CXD%28AQT%29%2CTD%2CDAS\`.
3. Bei der ersten Sitzung SSO und PING ID manuell auf dem Mobilgerät bestätigen.
   Es werden weder Passwörter abgefragt noch SSO-Schutzmechanismen umgangen.
4. Die Anwendung füllt das Feld \`name="finVin"\` und klickt genau einmal
   die Schaltfläche **Search**.
5. Sie ermittelt in den Diagnosezeilen die freigeschalteten
   \`span.cursor-pointer:has(svg.lucide-file-down)\`. Deaktivierte Symbole
   werden übersprungen. Die Anwendung erwartet einen Browser-PDF-Download.
6. Pro FIN werden PDFs mit Zeitstempel und Quellart gespeichert.
   Die Datei wird anhand des PDF-Headers geprüft und nicht überschrieben.
   Ein \`abrufstatus.json\` zeigt erfolgreiche und fehlgeschlagene Downloads.
7. Die bereits implementierte lokale Importpipeline archiviert die PDFs mit
   Provenienz und erstellt die QuickTest-FIN-Daten für die NTF-Analyse.

## Lokale Ablage

Standardmäßig: \`%USERPROFILE%\.ntf-insight\quicktests\<FIN>\`.

Das separat gespeicherte Edge-Profil liegt unter
\`%USERPROFILE%\.ntf-insight\edge-diagnosis-viewer-profile\`.
Die Unternehmensrichtlinien können eine erneute Anmeldung verlangen.

## Technische Grenzen

- Der GUI-Abruf funktioniert nur mit installiertem Edge und erlaubt keine
  vollständige Headless-Anmeldung mit PING ID. Das ist beabsichtigt.
- Falls der Diagnosis Viewer den Downloadtyp HTML eingestellt hat, muss dieser
  in den Benutzereinstellungen auf **PDF** umgestellt werden.
- Die Anwendung folgt den im Beispiel-HTML sichtbaren Ergebnissen; die
  dynamische Produktivseite, Rollen/Berechtigungen, Ergebnis-Paginierung und
  eventuelle Änderungen sind vor Ort mit freigegebenen FINs zu prüfen.
- Download-Dateien und Browserprofile dürfen **niemals in GitHub, CI-Artefakte
  oder Releases** gelangen. Die Funktion ist nur im Unternehmensnetz und mit
  entsprechendem Benutzerzugriff einzusetzen.
