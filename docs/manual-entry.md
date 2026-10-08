# Manuelle Fallerfassung

NTF Insight unterstützt die manuelle Erfassung auch ohne Original-Kurztests oder Parser. Die Eingaben werden **lokal und dauerhaft in DuckDB** gespeichert, nicht im GitHub-Repository.

## Bedienung

1. **Fälle / FIN** öffnen und auf **+ Neuer Fall** klicken.
2. Fall-ID, FIN und Bauteil eingeben. Baureihe, Variante und Markt sind optional. Dieselbe FIN darf zu mehreren Fällen gehören; jede Fall-ID muss eindeutig sein.
3. Den angelegten Fall auswählen und über **+ Ereignis** eine Ereignisart wählen.
4. Zeitpunkt und bei Bedarf Kilometerstand eintragen; unbekannter km-Stand bleibt leer.
5. Speichern. Die App aktualisiert Timeline, Zeitplot, Vorher-/Nachher-Analyse, DTC-Explorer, Cluster, Datenqualität und Dashboard.

### Unterstützte Ereignisse

| Ereignis | Wesentliche Felder |
|---|---|
| Kurztest | Zeitpunkt, km, Bezeichnung, Anzahl Steuergeräte/DTCs |
| DTC | ECU, DTC-Code, Text, Status, Häufigkeit, optional Kurztest |
| Bauteiltausch | Bauteil, alte/neue Teilenummer, Lieferant, Seriennummer, Charge, Analyseanker |
| Werkstattmaßnahme | Beanstandung, Maßnahme, Notiz |
| HW-/SW-Update | ECU, SW-/HW-Version, Codierung, Maßnahme |
| ECU-Stand | ECU, HW-/SW-Version, Codierung, optional Kurztest |
| Lieferantenbefund | Lieferant, NTF/Fehler gefunden, reproduzierbar, Fehlerbild, Notiz |
| Freie Notiz | Freitext, gespeichert als Werkstatteintrag |

Ein **Kurztest mit 0 DTCs** kann explizit erfasst werden. Das ist methodisch etwas anderes als **kein Kurztest vorhanden**.

### Datum ohne bekannte Uhrzeit

Ist nur das Datum bekannt, **„Nur Datum bekannt“** markieren. Intern wird dann 12:00 als rein technischer Plot-Wert gespeichert und `time_precision = "date"` hinterlegt. Die Ereignistabelle zeigt **„Uhrzeit unbekannt“**. Diese Uhrzeit ist kein verifizierter Diagnosezeitpunkt.

### Korrekturen und Provenienz

Zum Korrigieren einen Eintrag in der Ereignistabelle markieren und **„Markiertes Ereignis korrigieren“** verwenden. Über **„Änderungsverlauf“** bleiben Zeitpunkt, lokaler Benutzer, Typ und Vorher-/Nachher-Zustand nachvollziehbar.

Neue manuelle Ereignisse erhalten eine `source_ref` wie `manual:<Änderungs-ID>`, Korrekturen `manual:correction:<Änderungs-ID>`. Der vorherige Wert und der ursprüngliche Quellverweis bleiben im Audit-Protokoll erhalten. Ein importierter Originalreport wird **niemals** durch eine manuelle Korrektur überschrieben.

**Demo-Fälle können nicht bearbeitet werden**: Sie sind fiktive Testdaten. Über **+ Neuer Fall** wird ein echter lokaler Fall angelegt; danach wechselt die Anwendung automatisch vom Demo-Modus zum lokalen Datenmodus. Demo-Fälle werden dabei nicht mitgespeichert.

## Speicherort und Datenschutz

Standardmäßig unter `~/.ntf-insight/ntf-insight.duckdb` auf dem jeweiligen Rechner. Der Speicherort lässt sich über `NTF_INSIGHT_DATA_DIR` konfigurieren. Echte FINs, Werkstatttexte oder Lieferantenbefunde nur auf für diese Daten zugelassenen Mercedes-Benz-Rechnern bzw. Speicherorten erfassen. Originaldateien, Datenbank und Audit-Protokoll nicht nach GitHub committen.

## Aktuelle Grenzen

- Ereigniserfassung und nachvollziehbare Ereigniskorrektur sind verfügbar; vollständige Fallstammdaten-Bearbeitung, Lösch-/Freigabeworkflows und Rollenberechtigungen stehen noch aus.
- Die lokale Audit-Historie ist nachvollziehbar, aber **kein manipulationssicheres, zentral administriertes Revisionssystem**.
- Fachliche Datenvalidierung und automatische Erkennung von Duplikaten aus externen Quellen müssen mit repräsentativen Originaldateien weiterentwickelt werden.
- Die berechnete Root-Cause-Evidenz ist eine Untersuchungshilfe und kein automatischer finaler Schuldnachweis.
