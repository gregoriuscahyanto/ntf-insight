# VeDoc: DCDC223-Seriennummern als JSON und Excel exportieren

Dieses **eigenständige Kommandozeilenskript** hat keine Verbindung zur NTF-Insight-GUI. Es liest eine TXT-Liste mit vollständigen Fahrzeug-Identnummern (FINs), fragt VeDoc nacheinander ab und schreibt JSON sowie Excel. Grundlage ist die bereitgestellte *Anleitung VeDoc*, insbesondere der Weg **Fahrzeugdaten → FIN-Suche → Steuergeräte → Filter DCDC223 → Seriennummer**.

## Voraussetzung

- Berechtigter VeDoc-Zugang, Unternehmensnetz/VPN und ggf. PING-ID/SSO.
- Python 3.11+ mit den bestehenden Projektabhängigkeiten (python -m pip install -e .).
- Microsoft Edge (Standard) oder Playwright-Chromium (python -m playwright install chromium).
- Die VeDoc-Startadresse aus der internen Anleitung **nur lokal** konfigurieren; sie wird nicht im Repository gespeichert.

## Ausführen (PowerShell)

Eine Datei fins.txt außerhalb des Git-Repositories erstellen, **eine vollständige FIN mit 17 Zeichen pro Zeile**. Leere Zeilen und Kommentarzeilen mit # sind erlaubt. Doppelte FINs werden nur einmal verarbeitet. Ungültige FINs führen vor dem Browserstart zu einem Fehler.

~~~powershell
$env:VEDOC_URL = '<VeDoc-Startadresse aus der internen Anleitung>'
python scripts/vedoc_dcdc223_seriennummern.py --eingabe 'C:\lokal\fins.txt' --ausgabe 'C:\lokal\vedoc-ergebnisse'
~~~

Der Browser öffnet sich sichtbar. VeDoc einschließlich SSO/PING-ID **selbst anmelden** und anschließend im Terminal die Eingabetaste drücken. Das Skript führt danach die FIN-Suche und das Auslesen der DCDC223-Seriennummer nacheinander durch. Falls Edge nicht verfügbar ist: --browser chromium. Bei langsamer Verbindung: --timeout 60.

## Ausgabe

Im angegebenen Ordner entstehen dcdc223_seriennummern.json und dcdc223_seriennummern.xlsx. Die Excel-Tabelle enthält **FIN**, **Steuergerät**, **Seriennummer**, **Status**, **Hinweis** und **Abfragezeit (UTC)**. Die Seriennummer wird bewusst als **Text** gespeichert, damit führende Nullen erhalten bleiben. Die JSON-Datei enthält dieselben Einträge unter fahrzeuge.

Statuswerte: gefunden, steuergeraet_nicht_gefunden, seriennummer_fehlt, mehrdeutig, fin_nicht_bestaetigt, zeitueberschreitung, fehler. **Nur gefunden bedeutet, dass für genau diese FIN eine Seriennummer ausgelesen wurde.** Alle anderen Werte müssen bei Bedarf manuell geprüft werden.

Nach jeder FIN wird ein JSON-Zwischenstand gespeichert; am Ende (auch bei Abbruch) werden beide Dateien geschrieben. Wiederholte Läufe im selben Ausgabeordner überschreiben die Dateien. Wenn einzelne FINs fehlen, können diese gezielt erneut abgefragt werden.

## Datenschutz und Grenzen

FINs und Seriennummern sind vertrauliche Fahrzeugdaten. Eingabelisten und Exporte gehören nur in freigegebene lokale Ablagen, **nicht in Git, GitHub Issues, Pull Requests oder CI-Artefakte**. Das Skript speichert keine Passwörter, Cookies, Browserprofile oder HTML-Snapshots; es verwendet nur die reguläre, interaktiv angemeldete VeDoc-Oberfläche. Es gibt keine Backend-API- oder Zugriffsrechtsumgehung.

Die HTML-Selektoren wurden anhand der bereitgestellten Anleitung und gespeicherten VeDoc-Seiten entwickelt. **Ein Live-Test im Unternehmensnetz mit berechtigtem Zugang ist noch erforderlich.** Ändert VeDoc die Oberfläche, müssen die Selektoren geprüft werden. Der Abgleich mit der von VeDoc angezeigten FIN verhindert die Zuordnung veralteter Daten vom vorherigen Fahrzeug.
