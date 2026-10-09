# Warum werden weniger QEC-Fälle und Cluster angezeigt?

Diese Anleitung erläutert **Zählweisen**, **Vorher-Merkmale** und
**Cluster-Ausschlussgründe**, damit ein größerer AutoExport nicht als
zusätzliche QEC-Schadteilfallzahl missverstanden wird.

## Die Grundgesamtheiten sind verschieden

| Größe | Bedeutung | Darf ohne weitere Evidenz in automatische QEC-Cluster? |
| --- | --- | --- |
| Angelegte QEC-/NTF-Fälle | Eindeutige untersuchte Schadteilreferenzen aus dem QEC-Hauptblatt | Ja, sofern Tauschanker, DTC-Überlapp und Qualitätsregeln erfüllt |
| QEC-Quellzeilen | Alle Excel-Blätter, einschließlich Neben-/NTF-Clusterblätter mit möglicherweise denselben Referenzen | Nein, nicht als neue Fall-IDs |
| AutoExport-DTC-Zeilen | Beobachtungen/Fehlerspeichermeldungen, wiederholt je FIN und Diagnosezeit | Nein, keine neuen Schadteilfälle |
| Unterschiedliche AutoExport-FINs | Diagnostizierte Fahrzeuge unabhängig von einem QEC-Fall | Nein, zunächst reine FIN-Historie |
| TIPS-Zeilen | Dokumentierte Werkstatt-Vorgänge, einschließlich möglicher Wiederholungen derselben TIPS-ID | Nicht als neuer QEC-Fall; eigenständig dokumentierte TIPS-Fallnummern sind separat zählbar |
| Angezeigte 2D-Punkte | QEC-Fälle mit DTCs oder initialen Beanstandungen **vor** dem untersuchten Tausch | Eine Punktposition ist keine bestätigte Clusterzuordnung |
| Fälle in Clustern | QEC-Fälle, deren relevante Paarbeziehungen den Jaccard-Score, 50%-Abdeckungswert, gemeinsamen ECU:DTC und Tauschanker bestehen | Ja |

Beispiel aus dem Nutzer-Screenshot (die Zahlen werden nicht in Software
hartkodiert): 336 QEC-Fälle, 170 mit Vorher-Merkmalen, 166 nicht
projizierbar, ein automatisch bestätigter Cluster mit zwei Fällen.
Die Rohdaten können gleichzeitig tausende weitere FINs enthalten. Diese
können im **FIN / Fallanalyse → AutoExport-Gesamthistorie nach FIN**
durchsucht werden, ohne einen falschen Pumpenausfall zu erzeugen.

**Wichtig:** Die angezeigte Zahl der gescannten CSV-Zeilen, die Zahl der
archivierten Datensätze und die Zahl der angehängten Ereignisse sind
unterschiedliche Dinge. Ein nicht mit QEC verknüpfter Rohdatensatz
ist nicht verloren: Quellenwissen hält ihn weiterhin FIN-spezifisch.

## Warum fielen die Clusterzahlen nach dem AutoExport?

Der konservative Vergleich benutzt grundsätzlich die *Mengen* aus
ECU:DTC, DTC, ECU, vor dem Tausch bekannte Beanstandungen,
ECU-Softwareständen und Fahrzeugvariante. Der gewichtete Jaccard
berücksichtigt sowohl gemeinsame als auch unterschiedliche Merkmale.

Beispiel: zwei Fälle mit einem gemeinsamen Pumpen-DTC aus QuickTests
können zunächst sehr ähnlich sein. Wenn später jeder Fall noch
15 unterschiedliche ältere DTCs aus anderen Steuergeräten erhält,
vergrößern sich die Vereinigungsmengen. Der Gesamt-Jaccard sinkt.
Eine bisher überschrittene Grenze (Standard **0,65**) kann dadurch
unterschritten werden, obwohl der gemeinsame Pumpen-DTC bleibt.

Daher ist **„nur 1 Cluster“ nicht automatisch ein Programmbug**, aber
auch **kein belastbarer fachlicher Beweis**, dass alle übrigen Fälle
verschiedene Fehlerursachen haben. DTC-Frequenz im historischen
AutoExport und ECU:DTC-Mengen sind unterschiedliche Merkmale; der
MVP nutzt eindeutige Schlüssel, nicht automatisch die historischen
Zähler als Ähnlichkeitsgewicht.

## Diagnose im neuen Streudiagramm

Im Tab **Fälle / FIN → 2D-Streudiagramm**:

1. **DTC-Datenbasis**: *QuickTest + AutoExport (Standard)*, *Nur
   QuickTest-PDFs* oder *Nur AutoExport-CSV*. Die Auswahl filtert nur
   DTC- und ECU-Zustandsbeobachtungen nach ihrer Quelle; Beanstandungen,
   Fahrzeugvariante und das historische QEC-Verzeichnis bleiben gleich.
2. **Diagnosefenster vor Tausch**: Vollhistorie (Standard) oder 30,
   90, 180 bzw. 365 Tage. Der Vergleich verwendet nur die zum
   Zeitpunkt **vor** dem untersuchten Tausch dokumentierten Signale.
   Ein QEC-Tauschdatum mit Tagespräzision lässt keine gesicherte
   Reihenfolge am selben Kalendertag zu: der betroffene
   DTC wird weiterhin nicht als „sicher vor Tausch“ behandelt.
3. **Cluster-Qualitätsprüfung** erklärt die tatsächlichen
   Ausschlusszahlen: fehlender Vorher-DTC, nur Beanstandung,
   fehlender Tauschanker, kein gemeinsamer ECU:DTC, zu geringe
   Merkmalsabdeckung oder Score unter dem Schwellwert.
   Außerdem werden die besten *abgelehnten* Fallpaare mit ihrem
   Ausschlussgrund aufgelistet. Eine einzelne passende Paarbeziehung
   ist noch **keine** bestätigte Complete-Link-Gruppe.
4. **Zählung der Originaldaten** unterscheidet QEC-Hauptblatt,
   QEC-Nebenblätter, TIPS-Vorgänge, Diagnosedatensätze und
   unterschiedliche FINs. Es werden keine AutoExport-FINs automatisch
   als QEC-Schadteilfälle erfunden.

Die **gleiche** Signatur (gewählte Quelle, gewähltes Zeitfenster) geht
in die vorhandene Jaccard-Complete-Link-Berechnung **und** die
TruncatedSVD-Projektion ein. Wechsel der Quelle oder des Zeitfensters
verändert deshalb beides. Ein reiner Wechsel der Jaccard-Schwelle
verändert dagegen nur die Cluster-Mitgliedschaft/Farben und nicht
die Position im Streudiagramm.

Diese Varianten sind **Sensitivitätsanalysen**, nicht fachlich
kalibrierte Definitionen einer Fehlerursache. Es werden weder
Originaldaten überschrieben noch neue Schadteilfälle angelegt.
Die Gewichte selbst bleiben unverändert und die Unterschiede der
Varianten müssen anhand von fachlich bestätigten QEC-Fällen
geprüft werden.

## Warum die Originaldaten trotzdem nicht automatisch „repariert“ werden

Die Entscheidung, welche historisch gespeicherten DTCs ursächlich
mit dem Pumpentausch zusammenhängen, kann der Parser nicht allein
aus dem Fahrzeug und den Zeitstempeln treffen. Ein automatisches
Wegfiltern aller zusätzlichen DTCs, nur damit wieder 14 Cluster
entstehen, würde ein Ergebnis vorwegnehmen.

Vergleiche deshalb zunächst die Originaldaten mit den Optionen
**Alle Quellen → Nur QuickTest-PDFs → 90 Tage**. Bleiben die
Gruppen klein, prüfe die Tabelle mit ausgeschlossenen Paaren.
Für einen fachlich festgelegten Standardfilter benötigt die App
eine validierte DTC-/ECU-Relevanzliste und repräsentative
QEC-Befund-/Tauschfälle.
