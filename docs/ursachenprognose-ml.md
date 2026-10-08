# Selbstlernende Ursachenprognose

Das Modul `analysis/root_cause_ml.py` ergänzt die bestehende regelbasierte Evidenz-Engine.
Die Architektur ist einem probabilistischen Diagnose-Assistenten ähnlich, stellt aber
**keine Replikation eines internen Mercedes-Benz-IPBA-Modells** dar.

## Datengrundlage

Es werden ausschließlich unabhängig bestätigte Ursachen gelernt. Das Label wird
lokal in `confirmed_root_causes` gespeichert (Fall-ID, Ursache, Prüfer, Evidenzreferenz,
Datum). Eine vorhandene Fallbewertung ist **kein Trainingslabel**. Das gilt auch für
synthetische Demo-Fälle und vom Modell erzeugte Prognosen.

Pro Bauteilfamilie mindestens 30 bestätigte Fälle, zwei Ursachenklassen und
mindestens sechs Fälle und fünf unabhängige FINs je vorhandener Klasse.
Bei dünner oder einseitiger Datenlage gibt es keine Prozentprognose.

## Verfahren

- `DictVectorizer` + regularisierte multinomiale logistische Regression.
- DTCs und ECU-Vorkommen, CPC3-Diagnose, zeitlich bekannte Softwarestände,
  sowie diagnostisch beobachtbare Wiederholung nach Tausch.
- Kein Lieferant, keine FIN, keine Charge, kein Lieferantenbefund,
  keine `Assessment.root_cause` als Eingangsmerkmal (Leakage-Schutz).
- Stratifizierte 5-fache Gruppeneinteilung nach FIN: eine Partition Training,
  eine Temperaturkalibrierung, eine vollständig separater Test.
- Brier-Score, Log-Loss und Trefferquote werden auf dem unbeeinflussten Testteil gemessen.
- Bereits bestätigte Fälle können nach neuem fachlichen Feedback neu trainiert werden;
  keine automatische Übernahme von Prognosen als Wahrheit.
- Für den Vorhersagezeitpunkt `as_of` können spätere Ereignisse ausgeschlossen werden;
  ohne `as_of` handelt es sich um eine *retrospektive* Ursachenprognose.
- Prozente sind **nur auf die tatsächlich trainierten Klassen** normiert. Nicht
  vorhandene Ursachen sind „nicht trainiert“, nicht „0 %“.
- Die Anzeige enthält Unsicherheits- und Abweichungshinweise sowie positive
  logistische Merkmalsbeiträge. Letztere zeigen Modellkorrelationen, keine Kausalität.

## Einschränkungen

Ohne externe Validierung und ausreichend unabhängige, repräsentative Fälle ist die
Qualität statistisch nicht belastbar. Ein guter Hold-out-Score beweist keine
Kausalität. Persistente Modelle werden zunächst absichtlich **nicht** als unkontrollierte
Pickle-Dateien gespeichert; Training wird aus geprüften lokalen Feedbacklabels
deterministisch rekonstruiert. Das ist für eine erste Desktopversion leichter auditierbar.

Die Nutzeroberfläche benutzt die vorhandene neutrale Mercedes-kompatible
Corporate-Design-Fallback-Palette. Proprietäre Fonts, Logos, echte FINs
und vertrauliche Quellen dürfen nicht in das öffentliche GitHub-Repository.
