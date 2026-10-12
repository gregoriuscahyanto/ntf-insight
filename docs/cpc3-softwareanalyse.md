# CPC3-Softwarestand und Kühlmittelpumpen-Fälle (Issue #36)

NTF Insight wertet die **beobachteten Softwarestände** des Steuergeräts CPC3
FIN-bezogen aus. Ein Softwarestand in einem Kurztest ist **keine**
Software-Releasenote, ein Pumpentauschdatum **kein bewiesenes Ausfalldatum**.
Die Analyse arbeitet ausschließlich mit lokal importierten Daten.

## In der Oberfläche

Unter **Fälle / FIN → FIN / Fallanalyse** eine FIN oder einen QEC-Fall
wählen. Die neue Sektion **„CPC3 · Softwarestand bei ausgefallener
Kühlmittelpumpe“** zeigt:

1. Den **letzten tatsächlich beobachteten CPC3-SW-Stand vor** dem
   dokumentierten Pumpentauschtag und den **ersten beobachteten danach**.
   Wenn die FIN kein Tauschdatum hat, bleibt die Zuordnung unbekannt.
   Messungen **am selben Tag** werden nicht ohne Uhrzeitbeleg vor oder
   nach dem Tausch eingeordnet.
2. Eine Tabelle sämtlicher **bekannter CPC3-SW-Stände dieser FIN**, ihrer
   ersten/letzten Beobachtungen, Datenherkünfte und positiven CPC3-DTC-Funde.
3. **Beobachtete SW-Standabweichungen** mit dem letzten alten und dem
   ersten neuen Messzeitpunkt. Das tatsächliche SW-Updatedatum liegt
   lediglich **irgendwo in diesem Intervall**, wenn keine gesonderte
   Werkstattdokumentation vorliegt.
4. **Unterschiede im CPC3-DTC-Bild** nur bei zwei vollständig
   auswertbaren QuickTest-Berichten: DTCs, die erstmals sichtbar wurden,
   und DTCs, die im späteren Test nicht mehr sichtbar waren.

**Wichtig:** „Nicht mehr gesehen“ gilt nur für die beiden vollständigen
QuickTest-Beobachtungen – nicht als Beweis, dass ein DTC endgültig
behoben wurde. Zusätzliche Spannungs-, Temperatur-, Hardware-, Sensor-
und Nutzungsbedingungen können den DTC-Unterschied erklären.
Die Zuordnung „SW-Änderung hat das Systemverhalten verursacht“ ist
**nicht automatisch zulässig**.

## Quellen und Feldzuordnung

| Quelle | Felder | Einschränkung |
|---|---|---|
| AutoExport-Diagnose-CSV | `Fin`, `EcuNm=CPC3`, `EcuSwVersionTxt`, `EcuSuppHwVersionTxt`, `DiagStartTs` / `DiagStartDt`, `EcuFaultNm` | Einzelne DTC-Rohzeilen sind **keine vollständigen Kurztests**. Fehlende DTCs beweisen nichts. |
| QuickTest-PDF | CPC3-Block → `Software Version`, `Hardware Version`, `DIAG START`, CPC3-`FAULT CODES` | Vollständig validierte Berichte erlauben eine **Momentaufnahme** einschließlich CPC3 mit null DTCs. |
| QEC-Pumpenfall | Explizit untersuchter Pumpentausch (`Rep.-Datum`) und zugehörige FIN | Dient nur als **Tauschanker**, nicht als Ausfall-/SW-Updatedatum. |
| Dokumentiertes CPC3-Softwareereignis | Zeit, SW, `action`, Quelle | Separater Werkstatt-/Manuelleintrag; eine abweichende SW-Messung allein erzeugt kein solches Ereignis. |

AutoExport-Versionen werden auch dann aus dem lokalen Quellenwissen gelesen,
wenn die CSV beim ursprünglichen Import **noch nicht** einem QEC-Fall
zugeordnet werden konnte. Eine FIN ohne QEC-Fall, aber mit QuickTest,
erhält ebenfalls eine FIN-Ansicht. Fehlende oder widersprüchliche
Versionsangaben bleiben als Datenlücke erkennbar.

Die AutoExport-Abfrage ist auf **5.000 CPC3-Zeilen pro FIN** begrenzt;
bei Abschneidung wird das Ergebnis ausdrücklich als unvollständig
gekennzeichnet. Die Original-CSV wird unverändert archiviert.
Keine QEC-FIN wird aus einem unvollständigen Export erfunden.

## Was für echte Software-Wirkungsanalysen noch benötigt wird

Für die Frage **„Welche SW-Änderung hat welches Systemverhalten geändert?“**
reichen zwei unterschiedliche Versionsbezeichnungen und DTCs nicht aus.
Benötigt werden freigegebene CPC3-Software-/Kalibrierungs-Release-Notes,
Änderungstickets, ggf. SW-Freigabestände, definierte Diagnose- und
Regelungsbedingungen sowie vergleichbare Fahrzeug-Messungen vor und nach
der Änderung.

Die Anwendung zeigt bis dahin **Evidenz und Datenlücken**, aber weder
eine bestätigte softwarebedingte Pumpenursache noch eine
Lieferantenverantwortung.

## Technische Prüfung

Die synthetischen Regressionstests enthalten keine reale FIN und keine
vertraulichen Mercedes-Benz-Softwarestände:

```powershell
python -m pytest -q tests/test_cpc3_software_issue36.py tests/test_ecu_version_gui.py tests/test_ecu_version_changes.py
```

Der zentrale Quality Gate wird separat über den GitHub-PR (nur synthetische
Daten auf dem GitHub-Hosted-Runner) ausgeführt.
