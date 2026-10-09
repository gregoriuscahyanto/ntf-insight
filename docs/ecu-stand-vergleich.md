# HW-/SW-Standabweichungen zwischen QuickTests

NTF Insight vergleicht die **beobachteten Hardware- und Softwareversionen**
derselben Steuergerätekennung über die QuickTests einer FIN hinweg.
Die Auswertung benötigt **keinen QEC-Fall**: QuickTests werden eigenständig
unter der FIN gespeichert.

## Was wird verglichen?

Für jedes Fahrzeug (**FIN**) und jede Steuergerätekennung (**ECU**) werden
Beobachtungen nach ihrem Diagnosezeitpunkt sortiert. HW- und SW-Version
werden **unabhängig** miteinander verglichen.

- Der **erste bekannte Wert** bildet die Vergleichsbasis.
- Wird in einem späteren QuickTest ein **anderer bekannter Wert** gemeldet,
  ist eine HW- beziehungsweise SW-**Standabweichung** nachgewiesen.
- Fehlende Versionen (z. B. `-`, `n/a`, `unbekannt`) gelten **nicht**
  als Versionswechsel. Wenn nur HW fehlt, lässt sich SW trotzdem vergleichen.
- Mehrfach identische ECU-Werte im selben Diagnosezeitpunkt zählen nicht
  mehrfach. Widersprüchliche Versionsangaben **zur selben Zeit** erzeugen
  keinen künstlichen Wechsel und setzen den betroffenen Vergleich zurück.
- Bei zwei nur tagesgenau bekannten Beobachtungen am selben Tag
  wird keine angebliche zeitliche Reihenfolge konstruiert.
- SW-Zeichenfolgen werden **nicht** zu einer vermeintlichen aufsteigenden
  Release-Reihenfolge uminterpretiert. `A → B` heißt nur: später als
  unterschiedlich ausgelesen, nicht zwangsläufig ein Upgrade.

## So werden die Änderungen angezeigt

Unter **Fälle / FIN → FIN / Fallanalyse** gibt es die Tabelle
**„Erkannte HW-/SW-Standabweichungen“**:

| Feld | Bedeutung |
|---|---|
| ECU | Identische Steuergerätekennung |
| Art | Hardware- oder Softwarestand |
| Vorher / Nachher | Tatsächlich ausgelesene Versionswerte |
| Letzter alter Stand | Letzter QuickTest mit altem Versionswert |
| Erster neuer Stand | Erster QuickTest mit neuem Versionswert |
| km vorher / km nachher | Kilometerstände der beiden QuickTests (falls vorhanden) |
| Quelle | Ursprüngliche spätere HW-/SW-Beobachtung |

Im **Zeitplot** werden Standabweichungen als eigene Ereignisse gezeigt:
Hardwareänderung als **Quadrat**, Softwareänderung als **Dreieck**.
Die **gepunktete Verbindung** zeigt den Zeitraum zwischen den
diagnostischen Beobachtungen. Im Kilometer-Modus wird die Verbindung
nur gezogen, wenn **beide realen km-Werte** vorhanden und plausibel
geordnet sind. Daten ohne km werden wie bisher als `km unbekannt`
angezeigt.

Die **DTC-Textfilterung** blendet diese Änderungsmarkierungen und die
regulären HW-/SW-Standbeobachtungen nicht aus.

Unter **Fälle / FIN → QuickTests nach FIN** zeigt die
Steuergeräte-Tabelle für den jeweils ausgewählten QuickTest in der
Spalte **„Standvergleich“**, welche HW- bzw. SW-Version im Vergleich
zu der zuvor bekannten Version abweicht. Die entsprechenden
HW-/SW-Zellen werden in Hell- und Dunkeldarstellung kontrastreich
hervorgehoben.

## Fachliche Grenzen

**Es wird nur eine Versionsabweichung nachgewiesen**, kein tatsächlicher
Flash-Vorgang oder physischer Steuergeräteaustausch. Der genaue
Änderungszeitpunkt liegt lediglich **zwischen** den beiden QuickTests.
Ein Unterschied kann auch durch Steuergerätetausch, Variantenauswahl,
erneute Programmierung oder Diagnose-/Quellartefakte entstehen.

Die Änderungen sind **keine automatischen Root-Cause-Beweise**.
Ein Zusammenhang zu DTCs oder dem Pumpentausch muss separat
geprüft werden.

Für eine bestätigte Update-Ursache werden insbesondere die
**HW-/SW-Änderungslisten, Werkstattmaßnahmen, ECU-Teilenummern,
Software-Releaseinformationen und Diagnosebedingungen** benötigt.

Diese Differenzen werden zur Laufzeit aus den gespeicherten QuickTest-
Beobachtungen abgeleitet; die Originaldateien und ECU-Werte werden
weder geändert noch dupliziert.

## Lokaler Start und Tests

```powershell
git pull
python -m pip install -e ".[dev]"
pytest
python -m ntf_insight
```

Tests: `tests/test_ecu_version_changes.py` und
`tests/test_ecu_version_gui.py` (rein synthetische Daten).
