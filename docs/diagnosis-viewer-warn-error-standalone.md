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
