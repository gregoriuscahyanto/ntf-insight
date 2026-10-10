# Fahrzeugweite AutoExport-Muster: eigene Grundgesamtheit, kein NTF-Label

## Eine Clusteranalyse für AutoExport und QEC

Unter **Fälle / FIN → Clusteranalyse** gibt es nur **einen** Reiter.
Das Dropdown **Analysebestand** wählt eine von zwei Grundgesamtheiten:

- **Alle FINs – AutoExport + QEC gemeinsam (Standard):** Eine eindeutige
  FIN ist genau ein Fahrzeug und **ein Clustering-Datenpunkt**. Die
  App vereinigt den lokal importierten AutoExport-FIN-Bestand und
  die FINs aus QEC-Kühlmittelpumpenfällen. Sie verbindet wiederholte
  ECU:DTC-Beobachtungen aus AutoExport mit **zeitlich gesicherten
  Vor-Tausch-DTCs aus QEC/QuickTests derselben FIN**, statt dieselbe
  FIN zweimal zu berücksichtigen. QEC-FINs ohne AutoExport können als
  eigene Fahrzeuge dazukommen. QEC-IDs und der QEC-Bezug bleiben
  Attribute für die Fachprüfung und sind KEINE künstlichen Fahrzeuge.
- **Nur QEC-Pumpenfälle (Vor-Tausch-Analyse):** Die bestehende
  fallbezogene QEC-Analyse mit HDBSCAN Leaf/EOM,
  Complete-Link, konservativen Prüfgruppen und 2D/3D bleibt unverändert.
  Sie nutzt weiterhin ausschließlich gesicherte Diagnosen vor dem
  dokumentierten Bauteiltausch.

Die im Nutzer-Screenshot angegebenen Beispielzahlen sind 11.667
verschiedene lokal importierte AutoExport-FINs und 324 QEC-Pumpen-FINs
(336 QEC-Fälle). Die tatsächliche gemeinsame Gesamtzahl ist
**11.667 + QEC-FINs, die im AutoExport fehlen**, und wird erst
lokal nach dem FIN-Abgleich angezeigt. Die App legt keine dieser
Zahlen als festen Modellparameter fest.

Für **AutoExport-FINs mit QEC-Pumpentauschanker** gilt im kombinierten
Modus dieselbe konservative Vor-Tausch-Regel für beide Quellen:
DTCs von Tagen **vor** dem frühesten dokumentierten QEC-
`Rep.-Datum` sind zulässig; DTCs am Tauschtag, danach und
DTCs ohne hinreichenden Zeitnachweis sind keine Vor-Tausch-Merkmale.
Für **AutoExport-FINs ohne Pumpentauschanker** bleibt die gesamte
allgemeine AutoExport-Diagnosehistorie für die Mustererkennung
zugänglich. Diese beiden Beobachtungsfenster sind verschieden:
Die gemeinsame Gruppe ist deshalb nur ein **exploratives
Diagnosemuster**, kein Nachweis für einen gemeinsamen Pumpendefekt
oder NTF.

Die FIN-Historie ist **kein automatisch bestätigter Tauschanker**:
AutoExport-`RepairDt` bezeichnet zunächst einen Werkstatttermin
und beweist keinen Austausch der Kühlmittelpumpe. Die einzige
hier automatisch verwendete Pumpentauschquelle ist
**QEC / Schadteile QEC / Rep.-Datum**.

## Bedienung

1. **Fälle / FIN → Clusteranalyse** öffnen.
2. Im oberen Feld **Analysebestand** standardmäßig
   **Alle FINs – AutoExport + QEC gemeinsam** wählen. Das ist ein
   EINZIGER Clusterlauf für die zusammengeführten FIN-Diagnosemerkmale.
   Für die detaillierte bisherige Pumpen-QEC-Auswertung stattdessen
   **Nur QEC-Pumpenfälle** wählen.
3. Optional **Nur FINs mit belegtem QEC-Pumpentausch** aktivieren:
   Dann sind ausschließlich FINs mit QEC-`Rep.-Datum` und
   Diagnoseereignisse von früheren Tagen zugelassen. Diese
   Einstellung kann die Anzahl der FINs deutlich verringern.
4. **Clusteranalyse starten**. Sechs Summen zeigen die Gesamtzahl
   der einzigartigen FINs, FINs mit DTC, zugeordnete FINs, FINs
   mit DTC ohne Gruppe, FINs ohne DTC und die Anzahl der Mustergruppen.
   Zugeordnete + unzugeordnete FINs mit DTC + FINs ohne DTC
   ergeben exakt die Gesamtgrundgesamtheit.
5. Die Balkengrafik zeigt die 14 größten FIN-Muster, die Tabelle
   **alle** Mustergruppen. Die FIN-Tabelle enthält echte FINs,
   QEC-Fallzahl und **Diagnosequelle (AutoExport, QEC/QuickTest oder beide)**.
   Gemeinsame ECU:DTCs und verfügbare Klartexte erklären die Gruppen.
   Der QEC-Bezug bedeutet nicht, dass der Pumpendefekt bewiesen ist.
6. Die FIN-Suche findet Fahrzeuge in Gruppen, außerhalb von Gruppen
   und ohne DTC. Über die Aktion zur FIN-Historie sind importierte
   AutoExport-Daten lokal erreichbar. FINs ohne AutoExport können
   dort eine leere Historie haben, obwohl ein QEC-Fall bekannt ist.

## Methode und Einschränkungen

Die lokale DuckDB aggregiert aus importierten AutoExport-Daten je FIN
die Menge **eindeutiger ECU:DTC-Kombinationen**. Die im QEC-Bestand
vor dem untersuchten Kühlmittelpumpentausch dokumentierten
ECU:DTC-Kombinationen werden in denselben **FIN-Merkmalsvektor**
eingetragen. Mehrfach beobachtete DTCs zählen pro FIN nur einmal.
Ein vollständiger QEC- oder Lieferantenbefund ist **kein
Gruppierungsmerkmal**. DTC-Klartexte dienen nur als Beschriftung,
nicht als Vektorinput. Nicht belegte Klartexte werden nicht erfunden.
Reparaturfreitexte, ZIPs, SSL-Befunde und Originaldateien bleiben
unberührt.

Nur Fehlercodes, die bei **mindestens zwei verschiedenen FINs** vorkommen,
erzeugen gemeinsame Mustermerkmale. Daraus entsteht eine **sparse
TF-IDF-Matrix**. Anschließend wird experimentell ein
**MiniBatchKMeans**-Modell mit deterministischem Start angewandt.
Die Zahl initialer Suchbereiche orientiert sich an der Anzahl der
Fahrzeuge, hat jedoch eine Obergrenze von 64. Die resultierenden
Gruppen verlangen mindestens drei FINs und mindestens 35 % Cosinus-
Ähnlichkeit zum Musterschwerpunkt; diese Schwelle ist **nicht technisch
kalibriert**. FINs ohne gemeinsame Merkmale oder mit schwachen bzw.
zu kleinen Gruppen bleiben bewusst *ohne Gruppe*.

Das Verfahren vermeidet eine quadratische Distanzmatrix über alle FINs.
Bei über 10.000 Fahrzeugen wäre ein vollständiger paarweiser
Distanzvergleich unnötig groß. Die Balken statt 10.000 übereinanderliegender
Punkte bieten einen leichter lesbaren Überblick. Zur Überprüfung einzelner
Fahrzeuge existieren die vollständigen lokalen Tabellen.

Gruppenmitgliedschaft, Schwerpunkt-Ähnlichkeit und ein wiederkehrender
DTC sind **keine** Fehlerursachenwahrscheinlichkeiten und keine Belege
für einen Bauteil- oder Lieferantenfehler. Nur eine spätere unabhängige
Prüfung kann NTF-Mechanismen bestätigen. Insbesondere ist ein DTC-Text
eine Annotation, kein Clustering-Merkmal.

## Warum waren einzelne QEC-Fälle vor dem Tausch ausgeschlossen?

Die bisherige QEC-Kreisdarstellung ergänzt nun die **sechs disjunkten
Ausschlussgründe** für die gerade gewählte Methode und Datenbasis:
kein belegter Tauschanker, kein verknüpfter DTC, kein DTC aus der
ausgewählten Quelle, kein geeigneter DTC vor dem Tausch, DTCs durch
einen bewusst aktivierten Häufigkeitsfilter ausgeschlossen und
Restkategorie. Jede ausgeschlossene QEC-ID wird genau einmal gezählt.

Die Restkategorie ist ein Hinweis auf eine noch genauer zu
prüfende Zuordnungs- oder Filterbedingung, kein Fehlerurteil.
Wenn ein DTC zeitlich nicht sicher **vor** dem Tausch liegt, wird
er nicht nachträglich zum sicheren Vor-Tausch-Nachweis erklärt.
Fehlende Auswertbarkeit bedeutet **nicht**, dass nie eine
Werkstattdiagnose stattfand.

## Datenschutz / Offline

- Keine FINs, QEC-Schadteilfälle, DTCs aus dem Nutzerbestand, SSL-Berichte
  oder Herstellertexte in GitHub-Tests oder Chat.
- Alle Regressionstests sind vollständig synthetisch; die CI benötigt
  weder Werkstattdaten noch Zugriff auf den internen AutoExport.
- Die neue Datenabfrage ist **lesend**; lokale Rohdaten und QEC-Fallanker
  werden nicht überschrieben. Die Rechenroutine erzeugt keine neuen
  QEC-Schadteilfälle und nimmt keine FIN-zu-Pumpen-Reparaturzuordnung vor.

## GitHub-Quota und lokale CI-Artefaktbereinigung

Die PR-CI verwendet ausschließlich `windows-latest`, einen maximal
20-minütigen Qualitätslauf und **keine Actions-Artefakt-Uploads**.
Wegen des knappen Runner-Kontingents wird ein PR-Test nur durch
bewusste Freigabe von *Draft* zu *Ready for review* ausgelöst, nicht
für jede einzelne Codeänderung. Der manuelle lokale Analyse-Workflow
mit vertraulichen Pumpendaten bleibt weiterhin getrennt und darf nur
auf dem geprüften Hauptbranch laufen.

Das Skript `scripts/bereinigung_actions_artifacts.ps1` prüft über die
bereits angemeldete lokale GitHub CLI (`gh`) ausschließlich
wegwerfbare CI-Report- und Wheel-Artefakte dieser Repositorys.
Es löscht sie **erst nach** Aufruf mit `-Loeschen`, nicht bei einer
normalen Vorschau. Das angeschlossene GitHub-Werkzeug besitzt keine
Artefakt-DELETE-Funktion; die Löschung muss deshalb bewusst mit
`gh auth login` lokal ausgeführt werden. Die Speicheranzeige
von GitHub kann sich erst einige Stunden später aktualisieren.
