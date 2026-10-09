# Diagnose-Datenlücken und Repräsentantenprüfung

## Ziel

Ein realer Medoid je ML-Cluster soll fachlich untersucht werden. Dessen
**unabhängig bestätigter** Fehlermechanismus kann für ähnliche Fälle im selben
Cluster als **Prüfhypothese** vorgeschlagen werden. Er wird niemals automatisch
zum bestätigten QEC-/SSL-/Lieferantenbefund der übrigen Fälle.

## Lokale Diagnose-Datenlücken

Die Auswertung verwendet dieselben ausgeschlossenen QEC-Fälle wie das bestehende
HDBSCAN-Evidenzaudit. Falls eine lokale Datenbank angebunden ist, prüft sie
FIN-bezogene QuickTest-DTC-Sitzungen und AutoExport-Roh-DTC-Zeilen getrennt.

- Kein QEC-DTC, DTC nicht sicher vor Tausch, sonstige Ausschlussgründe
  bleiben als primäre Klassifikation erhalten.
- Zweite Ebene: QEC-DTCs nach Tausch, am Tauschtag oder zeitlich unklar.
- Separate FIN-Rohdaten-Hinweise: vor Tausch, gleicher Tag, nach Tausch,
  Zeit nicht rekonstruierbar; QuickTest und AutoExport getrennt.
- Roh-DTC-Zeilen sind weder deduplizierte Diagnoseereignisse noch Beweis
  einer Zugehörigkeit zu einer bestimmten QEC-Schadteilreklamation.
- Mehrere QEC-Fälle je FIN dürfen keinesfalls ohne unabhängigen Nachweis
  nachträglich miteinander verknüpft werden.
- Kein automatischer Reimport, keine Änderung von Tauschankern, Labels,
  Klassifikation, originalen Quellen oder HDBSCAN-Mitgliedschaft.

Das Rohdaten-Audit ist bewusst unabhängig vom Quellen-/Lookback-Filter der
ML-Eingabesignatur. Es zeigt mögliche verlorene Evidenz und keinen neuen,
automatisch auswertbaren Fall.

## Repräsentanten-Transfer (nur Prüfhypothesen)

- Der bestehende Medoid ist ein realer QEC-Fall, keine erfundene
  Durchschnittsdiagnose.
- Fachbestätigung mit Mechanismus, Prüfer, Evidenzreferenz und Datum erfolgt
  mit der vorhandenen lokalen CSV-Prüfvorlage.
- Für Ziele mit gleicher FIN, widersprechend bestätigtem Mechanismus, ohne
  gemeinsame ECU:DTC oder unzureichender Ähnlichkeit bleibt die Übertragung
  gesperrt oder zurückgestellt.
- Vorläufiges Screening: keine heterogene Gruppe, mindestens ein geteilter
  ECU:DTC, Cosinus zum Medoid >=45 %. Die 45 % sind nicht kalibriert und
  erlauben keine automatische Ursachenzuordnung oder Reparaturempfehlung.
- Auch ein Ziel, das diese Kriterien erfüllt, erhält nur eine
  **unbestätigte Hypothese**. Erst separate technische Evidenz am Zielfall
  kann eine bestätigte Ursache begründen.

Der Bestand von 336 QEC-Fällen liegt nur lokal; synthetische CI-Tests sind
kein Nachweis einer tatsächlichen Ursachenübertragbarkeit.
