# CPC3-Softwarestand und Kühlmittelpumpen-Fälle (Issue #36)

NTF Insight wertet die **beobachteten Softwarestände** des Steuergeräts CPC3
FIN-bezogen aus. Ein Softwarestand in einem Kurztest ist **keine**
Software-Releasenote, ein Pumpentauschdatum **kein bewiesenes Ausfalldatum**.
Die Analyse arbeitet ausschließlich mit lokal importierten Daten.

## Modulare ECU-Auswahl und vollständig archivierte SW-Historie

In **Fälle / FIN → ECU · SW-Übersicht** steht oben die
**Steuergeräte-Auswahl** (Standard `CPC3`). Sie wird aus den tatsächlich
archivierten `EcuNm`-Werten der lokalen DuckDB und den Fallinformationen
befüllt. Für andere Steuergeräte (z. B. MCM) wird exakt dieselbe
Software-, Tauschanalyse und Diagnoseevidenz neu berechnet; beim Öffnen
eines Falls folgt auch das ECU-SW-Detailpanel der Auswahl.

Die Analyse liest `EcuSwVersionTxt` **unverändert** aus
`source_knowledge_rows.payload_json` der importierten
**AutoExport-Diagnosequelle**, auch wenn deren Beobachtungen keinem
QEC-Fallereignis zugeordnet wurden. Dazu werden Quell-FIN und die
QEC-FIN nach der bekannten MBC-Präfixregel abgeglichen.
Mehrere DTC-Rohzeilen derselben ECU-/Diagnose-/SW-Messung werden
**nur als ein Snapshot** gezählt; ihre positiven DTC-Codes bleiben
erhalten. Alle *verschiedenen* SW-Stände und ihr Beobachtungsverlauf
bleiben dagegen verfügbar.

Neben `SW vor Tausch` und `SW nach Tausch` gibt es deshalb
`SW am Tauschtag (Reihenfolge offen)`, `SW-Zeitlage`,
`Alle SW-Stände dieser FIN`, `Chronologischer SW-Verlauf`,
`Anzahl SW-Stände` sowie eine **SW-Messhistorientabelle** zum
ausgewählten Fall. **Eine SW-Messung am Tauschtag ist ein gültiger
Softwarebeleg, auch wenn das Tauschprotokoll keine Reparaturuhrzeit
enthält.** Die App erfindet daraus keinen Vorher- oder Nachher-Stand.
Das gilt auch bei mehreren Messungen mit identischem SW-Stand. Bei
unterschiedlichen SW-Ständen am Tauschtag wird der Konflikt benannt.

Der zusätzliche **SW-Zeitlage-Filter** sowie das Diagramm
**„Zeitliche SW-Datenlage“** unterscheiden sicher vorher gemessene
Stände, ausschließlich am Tauschtag gemessene Stände, widersprüchliche
Tauschtagsmessungen, erst danach gemessene Stände und echte Datenlücken.
Ein eigener **CPC3 anzeigen**-Button stellt die Standardsteuergerätewahl
wieder her. Die SW-Messhistorie kann eingeklappt werden, damit bei
vielen Pumpenfällen mehr Platz für die Haupttabelle bleibt. Der lokale Excel-Export enthält eine eigene
Tabelle **SW-Messhistorie** mit Zeit und Quellbeleg. Tagesgenaue
Beobachtungen erhalten niemals eine künstliche Uhrzeit.

Das Rohwissen wird in FIN-Gruppen aus DuckDB gelesen; pro FIN werden
höchstens **20.000 zusammengefasste Beobachtungen** geladen.
Bei einer Begrenzung wird der Fall als unvollständig markiert.
Die Quelldateien werden weder erneut geschrieben noch auf GitHub geladen.

### Die vier Ringdiagramme

Die Donuts verwenden ausschließlich **gegenseitig ausschließende
Pumpenfälle im aktuell sichtbaren Filter** als Nenner, keine
CSV-Zeilen:

1. **ECU-DTC vor Pumpentausch:** positiv beobachteter ECU-DTC;
   vollständiger ECU-QuickTest ohne ECU-DTC; oder
   **keine ausreichende Diagnose**.
2. **SW vor / am Tauschtag:** fünf häufigste belegte
   Vor-Tausch-SW-Stände und separat etikettierte Tauschtags-SW-Stände,
   weitere und fehlende/unklare SW-Beobachtungen.
   **Jeder Fall zählt genau einmal**, unabhängig von der Anzahl
   der Diagnosezeilen. Eine reine Tauschtagsmessung ist **nicht** als
   zuvor installierter Stand nachgewiesen.
3. **Zeitliche SW-Datenlage:** SW sicher vor dem Tausch, nur am
   Tauschtag, SW-Konflikt am Tauschtag, erst nach dem Tausch,
   sonst zeitlich unklar oder keine SW-Daten.
4. **ECU-DTC nach Pumpentausch:** DTC positiv beobachtet;
   vollständiger ECU-Nachtest ohne DTC; oder
   **kein belastbarer Nachtest**.

**Ganz wichtig:** Wenn es nach dem Pumpentausch keine AutoExport-DTC-Zeile
gibt, liegt deshalb **nicht automatisch ein DTC-freier ECU-Test** vor.
Außerdem kann der ECU-SW-Stand in einem DTC-only-Export unbekannt bleiben,
obwohl am Fahrzeug weiterhin Software installiert ist.

### Welche Softwarestände sind auffällig?

Die Tabelle **„Auffällige SW-Stände unter Pumpenfällen“** sortiert
nach der Zahl der Pumpenfälle **mit positiv nachgewiesenem ECU-DTC**
bei bekanntem Vor-Tausch-SW-Stand. Sie zeigt Fallanzahl,
unterschiedliche FINs, Fälle mit ECU-DTC, beidseitig verfügbare
vollständige ECU-QuickTests sowie im Nachtest erneut beobachtete
DTCs. Eine Wiederkehrrate wird **erst ab fünf auswertbaren
Vor-/Nachtest-Paaren** angegeben.

Dies ist eine **Beschreibung der untersuchten Rückläuferfälle**,
keine statistische „Problemwahrscheinlichkeit“ eines SW-Standes.
Dazu bräuchte man die eingesetzte Fahrzeug-/SW-Flottenpopulation,
vergleichbare Laufleistung und Einsatzbedingungen und ausreichenden
Nachbeobachtungszeitraum.


## Alle Pumpenfälle gemeinsam untersuchen

Unter **Fälle / FIN → ECU · SW-Übersicht** stehen **sämtliche
lokal vorhandenen Kühlmittelpumpenfälle** in einer Tabelle, auch wenn
ein Fall kein Tauschdatum oder keine CPC3-SW-Information hat.
**Eine Zeile ist ein Fall**, nicht eine FIN: Eine FIN mit mehreren
QEC-Tauschen erscheint entsprechend mehrfach.

Der Button **„Alle Pumpenfälle auswerten“** liest die lokal
archivierten CPC3-AutoExport-Daten im Hintergrund.
Das Ergebnis kann nach **FIN, Fall, Softwarestand, DTC, SW-Status**
durchsucht und nach SW-Status bzw. DTC-Wiederkehr gefiltert werden.
Doppelklick auf eine Zeile öffnet deren **FIN / Fallanalyse**.
Mit **„Sichtbare Fälle als Excel“** wird genau die gefilterte
Tabelle samt Quellenbelegen, Datenlücken und Fachprüffeldern lokal
gespeichert. Die Datei enthält echte FINs und darf nur in eine
freigegebene Ablage gelangen. Automatische Datenuploads finden nicht statt.

Die Spalten trennen:

- **ECU-SW vor/nach Pumpentausch**: Letzte belegte Version vor,
  erste belegte Version nach dem Tauschtag.
- **ECU-SW am Tauschtag**: Hier wird der tatsächlich am Reparaturtag
  beobachtete `EcuSwVersionTxt` einschließlich Quelldokumentation
  angezeigt. Ohne Reparaturuhrzeit ist das **kein gesichert vor** oder
  **nach** dem mechanischen Tausch installierter Stand.
- **SW-Maßnahme am Tauschtag**: Nur dann als **dokumentiert**
  ausgewiesen, wenn ein explizites CPC3-Softwareereignis mit
  Update-/Programmierungsaktion am selben Kalendertag vorliegt.
  Eine gemessene Versionsabweichung allein reicht dafür nicht.
- **SW-Maßnahme zeitnah**: Explizites Update-/Programmierungsereignis
  innerhalb **±14 Kalendertagen** des Pumpentauschs. Dieses
  konfigurationsfreie Suchfenster ist **kein** Nachweis der
  Gleichzeitigkeit oder des exakten Flash-Datums.
- **SW-Standabweichung**: Alter/neuer SW-Wert sind unterschiedlich,
  aber **wann** geändert wurde, bleibt zwischen den
  Diagnosebeobachtungen offen. Gleiche Werte beweisen kein
  ausgebliebenes Update.
- **CPC3-DTC vor/nach Pumpentausch**: Nur vollständige, diesem Fall
  zugeordnete CPC3-QuickTests; dieselben DTC-Codes werden auch in
  **späteren** vollständigen Nachtests erneut geprüft.
  AutoExport-DTC-Rohzeilen dienen nur als positive Hinweise.
- **DTC vor/nach dokumentierter SW-Maßnahme**: Eigenständiger Vergleich
  der CPC3-QuickTests vor und nach dem belegten Update-Ereignis.
  Ohne vollständige Tests oder bei mehreren Update-Ereignissen erscheint
  **nicht beurteilbar/nicht einzeln zuordenbar**.
- **SW-Wirkung**: Selbst wenn der DTC nach der Maßnahme nicht mehr
  beobachtet wird, steht **„keine kausal bestätigte SW-Heilung“**.
  Lag zwischen den QuickTests auch der **Pumpentausch**, wird der
  konkurrierende Eingriff explizit hervorgehoben.

**Interpretation:** „DTC nicht erneut gesehen“ bedeutet nur, dass
der Fehlercode in den vorhandenen vollständigen Nachtests nicht
wieder sichtbar war. Es sagt ohne Fahrprofil, Umgebungsbedingungen,
Fehlerursachenprüfungen und ggf. Freigabe-/Softwaredokumentation
**nicht**, ob die Software das Pumpenproblem gelöst hat.

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
python -m pytest -q tests/test_cpc3_pump_overview.py tests/test_cpc3_software_issue36.py tests/test_ecu_version_gui.py tests/test_ecu_version_changes.py
```

Der zentrale Quality Gate wird separat über den GitHub-PR (nur synthetische
Daten auf dem GitHub-Hosted-Runner) ausgeführt.
