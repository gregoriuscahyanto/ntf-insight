# Standalone: Diagnosis Viewer Warning and Error Messages

Das eigenstaendige Python-Skript `scripts/diagnosis_viewer_warn_error.py` liest fuer eine lokale FIN-Liste die im Diagnosis Viewer vorhandenen Warning- und Error-Meldungen und schreibt eine JSON-Datei. Es laedt **keine QuickTest-PDFs** herunter und ist nicht an die NTF-Insight-GUI gebunden.

## Vorbereitung (Windows)

1. Python 3.11+ und Microsoft Edge installieren.
2. Im Repository: `py -3.11 -m pip install -r scripts/requirements_diagnosis_viewer_warn_error.txt`
3. Einen lokalen Ordner fuer die Eingabe anlegen und in `data/raw/diagnosis_viewer_warn_error/fins.txt` jeweils eine 17-stellige FIN pro Zeile eintragen (UTF-8, Leerzeilen und Kommentare mit # erlaubt). Die Datenordner sind durch `.gitignore` ausgeschlossen.

## Start

Fuer den einfachen Start `scripts/start_diagnosis_viewer_warn_error.cmd` doppelklicken. Die JSON liegt dann unter `data/processed/diagnosis_viewer_warn_error/warnings_errors.json`.

Alternativ in PowerShell:

```powershell
py -3.11 scripts/diagnosis_viewer_warn_error.py --eingabe 'C:\lokal\fins.txt' --ausgabe 'C:\lokal\warnings_errors.json'
```

Zugangsdaten aus dem Windows-Anmeldeinformationsmanager von NTF Insight werden automatisch uebernommen, falls vorhanden. Sonst kann die Anmeldung im sichtbaren Browserfenster erfolgen. Die PING-ID-Bestaetigung bleibt manuell. `--login-manuell` unterbindet das Tresor-Auslesen und `--nur-login --login-manuell` prueft nur die Anmeldung, ohne FINs oder JSON zu bearbeiten.

Bei Abbruch denselben Befehl/die CMD erneut starten. Die JSON wird pro Sitzung atomar gespeichert; erfolgreiche Sitzungen werden nicht erneut bearbeitet. `--aktualisieren` sucht nach neuen Sitzungen, `--erneut` liest auch bereits erfolgreiche erneut.

Bei jeder Meldung werden soweit verfuegbar Kennung, Status, erstes und letztes Auftreten, Hauefigkeit, Zuendzyklen, Ereignistyp und Meldungstexte abgelegt. In der JSON bleiben bei strukturierter Auslese zusaetzlich die Originalfelder erhalten. Fehlgeschlagene Auslesungen werden nicht als leere Meldungen markiert.

## Test und Grenzen

`py -3.11 -m pytest -q tests/test_diagnosis_viewer_warn_error.py`

Die Tests verwenden synthetische FINs. Kein Live-Test im Unternehmensnetz wurde durchgefuehrt. Vor Seriennutzung den Export mit einer berechtigten Test-FIN gegen den Viewer vergleichen. Echte FINs, Diagnoseberichte oder Zugangsdaten duerfen nicht ins Repository oder CI-Artefakte gelangen.

## Schnellmodus, fehlender Abschnitt und Restzeit (Update)

- **Keine kuenstliche Pause:** Der Standard ist jetzt `--abstand 0`. Browseraktionen werden ohne festen Abstand ausgefuehrt; notwendige Lade- und Zustandspruefungen bleiben bestehen. FINs und Sitzungen werden weiterhin nacheinander ausgelesen, nicht parallel. Fuer eine vorsichtigere Lastbegrenzung kann `--abstand 1.5` gesetzt werden.
- **Abschnitt fehlt:** Wenn die Diagnose-Sitzungsinformationen vollstaendig geladen sind und `Warning and Error Messages` nach einer kurzen stabilen Kontrolle nicht existiert, speichert das Skript die Sitzung mit dem eindeutigen Status `abschnitt_fehlt` und verarbeitet sofort die naechste. Eine explizite Abschnittsliste der Quelle kann das ebenfalls direkt belegen. `anzahl_meldungen` ist hier `null`, nicht 0; `keine_meldungen` bleibt fuer eine nachweislich leere Warnungsliste reserviert. Beim Resume wird `abschnitt_fehlt` uebersprungen, mit `--erneut` neu geprueft.
- **Unvollstaendige Ansicht:** Laedt die Sitzung nicht ausreichend, bleibt der Datensatz `fehler` und wird bei einem Folgeabruf erneut versucht; ein fehlender Abschnitt wird nicht einfach geraten. Standardmaessig ist die Suche nach dem Abschnitt auf 25 Sekunden begrenzt; ein eventuell haengender direkter API-Leseversuch auf 4 Sekunden.
- **Restzeit:** Die PowerShell-Konsole zeigt nach jeder FIN-Suche und Sitzung die bisherige Laufzeit und eine **grob geschaetzte Restzeit**. Sie berechnet sich aus den bisher gemessenen Such-/Sitzungszeiten und der durchschnittlichen Sitzungszahl pro FIN. Vor dem ersten ausreichenden Messwert steht `Restzeit wird ermittelt`; die Schaetzung ist keine Zusage, weil manche FINs deutlich mehr Sitzungen haben.

Optionen fuer langsamere Netze oder geaenderte Oberflaechen: `--sitzungs-timeout 45`, `--abschnitt-wartezeit 2`, `--seiten-timeout 90` oder `--abstand 0.5`. Unternehmensrichtlinien fuer berechtigten Zugriff gelten weiterhin.
