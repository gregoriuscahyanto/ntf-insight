# QEC-Tauschdatum, AutoExport-Reparaturdatum und wählbare Zeitplot-Achse

## Zwei Quellen – zwei verschiedene Bedeutungen

- **QEC `Rep.-Datum`**: Der im Schadteil-/QEC-Fall dokumentierte
  Austauschanker. Er ist nicht automatisch das belegte physische
  Ausbaudatum. Die bisherige NTF-Vorher-/Nachher-Analyse verwendet ihn,
  solange kein Fachanwender einen anderen untersuchten Tausch verifiziert.
- **AutoExport `RepairDt`**: Das Datum des Werkstatt-/
  Reparaturvorgangs. Zusammen mit **FIN**, **`PartLetterCd`**
  (Teilenummer), **`KmReadingNum`** und Reparaturdetails kann daraus
  ein **Tauschkandidat** ermittelt werden. Eine Reparatur mit Teilen
  beweist nicht allein, dass die untersuchte Pumpe physisch gewechselt
  wurde.

NTF Insight ermittelt nur Vorschläge bei **identischer FIN und
Teilenummer**. Für den automatischen Vergleich gelten vorläufige
technische Plausibilitätsgrenzen: bis zu 365 Tage Datumsdifferenz,
maximal 1.000 km Differenz, ohne beidseitige Kilometerangabe maximal
45 Tage. Diese Grenzen sind **noch nicht fachlich kalibriert**;
ein Treffer ist keine bestätigte Reparaturmaßnahme.

Sind **mehrere** passende AutoExport-Daten vorhanden, werden **alle**
gezeigt und als mehrdeutig markiert. Eine vermeintlich beste Auswahl
wird dann nicht stillschweigend zum echten Tausch erklärt.

Die AutoExport-CSV-Zeilen werden unabhängig von QEC-Fällen in
`source_knowledge_rows` gespeichert und können deshalb auch dann
als Reparaturkandidaten herangezogen werden, wenn die AutoExport-CSV
vor dem QEC-Fall importiert wurde oder die ursprüngliche enge
Reparatur-Zeitfensterzuordnung die Zeile nicht an die Falltimeline
gehängt hat. Alte, bereits importierte Daten müssen **nicht erneut
hochgeladen** werden, sofern sie mit dem vollständigen AutoExport-
Quellzeilenspeicher importiert wurden.

## Anzeige in „Fälle / FIN → FIN / Fallanalyse“

Die Statusfelder über dem Zeitplot zeigen:

- **QEC-/dokumentiertes Tauschdatum** – unveränderte Quellangabe
- **AutoExport-Reparaturdatum** – ein oder mehrere Kandidaten
- **Für NTF verwendeter Tauschanker** – welcher dokumentierte/manuell
  bestätigte Zeitpunkt gerade die Vorher-/Nachher-Regeln steuert
- **Datumsabgleich** – gleiche Daten, Anzahl Tage Abweichung,
  fehlende oder mehrere Kandidaten
- **Quellenabgleich** – Detailbegründung und Kilometerdifferenz

Im Plot sind QEC-Tauschanker (gestrichelte Linie) und AutoExport-
Reparaturkandidaten (gepunktete Linie) **separat** markiert. Auch bei
deckungsgleichen Daten bleiben beide Quellen dokumentiert.

## X-Achse wählen

Über **X-Achse** stehen zur Auswahl:

- **Datum / Uhrzeit**: chronologische Darstellung aller Ereignisse.
- **Kilometerstand**: Eintrag anhand des im jeweiligen Quellereignis
  **tatsächlich dokumentierten** km-Werts. Unbekannte Kilometerstände
  erscheinen im rechten Bereich **„km unbekannt“**, nicht mit einem
  geschätzten oder vom benachbarten Kurztest kopierten km-Wert.

Ein rein datumsbasierter Reparatureintrag darf deshalb nicht plötzlich
ein scheinbar exakt gemessener Kilometerstand sein.

## DTC-Filter und dauerhafte Kontext-Ereignisse

Das Eingabefeld **„Nur DTCs filtern“** filtert die DTC-Beobachtungen
nach Steuergerät (z. B. CPC3) oder Code (z. B. P26F100).
**Immer sichtbar bleiben** Kurztests, Steuergerät-HW-/SW-Stände,
Tauschanker, AutoExport-Reparaturkandidaten, Werkstatt-/Softwareaktionen
und Lieferantenbefunde.

- **Steuergerät HW-/SW-Stand** bedeutet, dass bei einem Kurztest die
  Version/Parametrierung des Steuergeräts beobachtet wurde. **Dies ist
  nicht notwendigerweise ein Softwareupdate**, sondern lediglich eine
  zeitlich dokumentierte Version.
- **Lieferantenbefund** bedeutet das protokollierte Ergebnis der
  Schadteilprüfung (z. B. NTF oder bestätigter Fehler), **nicht**, dass
  der Lieferant als Ursache feststeht. Ein Lieferantenbefund kann zudem
  viel später als die eigentliche Reparatur eingetragen sein.

## Einen AutoExport-Kandidaten manuell bestätigen

Nur wenn **genau ein** ausreichend plausibler AutoExport-Kandidat vorliegt,
kann ein berechtigter Fachanwender auf
**„AutoExport-Datum als Tauschanker bestätigen…“** klicken.

Die Bestätigung verlangt eine zusätzliche Rückfrage, ob der tatsächliche
Pumpentausch anhand der Werkstattunterlagen geprüft wurde. Erst danach
wird über den bereits vorhandenen Auditdienst ein **neuer manueller
Tauschanker** angelegt und für die Recurrence-Analyse gewählt.
Der originale QEC-Eintrag und der AutoExport-Quellbeleg bleiben
unverändert; die Änderung wird in **Änderungsverlauf** dokumentiert.

Es findet **keine automatische Korrektur** des QEC-Datums statt.

### Dateien

- `analysis/replacement_dates.py`: Nachvollziehbarer Abgleich und Konflikte
- `analysis/timeline.py`: Getrennte Zeitplot-Einträge pro Quelle
- `app/widgets/event_time_plot.py`: Zeit- oder Kilometerachse und DTC-Filter
- `app/pages/case_page.py`: Vergleich, Warnhinweise und Audit-Bestätigung
- `tests/test_replacement_date_plot.py`: fachliche Regeln und Plot
- `tests/test_replacement_date_gui.py`: GUI und Bestätigungs-Audit
