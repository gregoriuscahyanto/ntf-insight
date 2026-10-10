# Fahrzeugweite AutoExport-Muster: eigene Grundgesamtheit, kein NTF-Label

## Warum ein zweiter Analysebereich?

**Fälle / FIN → Clusteranalyse** bleibt die zeitbezogene QEC-Auswertung
für einen untersuchten Pumpentausch. Für die vorliegende importierte
Datenbasis zeigen die vom Nutzer lokal genannten Summen z. B. 336
Pumpen-QEC-Fälle, 324 FINs, davon 170 mit geeigneter Vor-Tausch-Diagnose.
Die übrigen QEC-Fälle dürfen nicht durch Nach-Tausch-Diagnosen ergänzt
werden, nur damit ein größerer Cluster entsteht.

**Fälle / FIN → Fahrzeugmuster (AutoExport)** verwendet unabhängig davon
**alle lokal importierten AutoExport-FINs**. Im aktuell gezeigten lokalen
Datenbestand: 11.667 verschiedene FINs, davon 10.898 mit DTC-Zeilen,
469.777 DTC-Rohzeilen, dazu Werkstatt- und TIPS-Rohzeilen.
Mehrfache Meldungen desselben ECU:DTC in derselben FIN werden nicht als
mehrere Fahrzeuge oder mehrere unterschiedliche Diagnoseschlüssel
interpretiert. Der tatsächliche Datenbestand wird jedes Mal neu gelesen
und ist nicht im Code hartkodiert.

Die FIN-Historie ist **kein automatisch bestätigter Tauschanker**:
AutoExport-Werkstattzeilen können alle möglichen Reparaturen betreffen.
Eine beliebige DTC-Beobachtung im AutoExport muss also weder die
Kühlmittelpumpe betreffen noch zeitlich vor einem Pumpentausch liegen.
**Die AutoExport-Gruppen heißen daher Diagnosemuster, nicht NTF-Fälle,
Pumpen-Schadteilfälle oder technische Ursachencluster.**

## Bedienung

1. Im QEC-Reiter **Alle AutoExport-FINs nach Diagnosemustern untersuchen**
   drücken oder **Fahrzeugmuster (AutoExport)** öffnen.
2. **Alle AutoExport-FINs clustern** starten. Lesen und Berechnung laufen
   im Hintergrund und ausschließlich lokal aus der vorhandenen DuckDB.
3. Sechs Summen unterscheiden Gesamt-FINs, FINs mit DTC, FINs in Gruppen,
   FINs mit DTC aber ohne Gruppe, FINs ohne DTC und Mustergruppen.
   Dabei muss *in Gruppen + DTC ohne Gruppe + ohne DTC* genau der
   Gesamtzahl importierter FINs entsprechen.
4. Das Balkendiagramm zeigt die 14 größten Gruppen; **alle** Gruppen
   stehen in der Tabelle. Eine Gruppe zeigt ihre **echten FINs**,
   häufige ECU:DTC-Schlüssel mit Zahl betroffener FINs sowie
   DTC-Klartexte, soweit sie in importierten AutoExport-Daten vorkommen.
5. FIN-Suche funktioniert auch bei FINs **ohne Gruppe** oder **ohne DTC**.
   Die Schaltfläche öffnet die lokal archivierte AutoExport-Gesamthistorie
   der FIN, auch wenn kein QEC-Fall existiert.
6. **Davon FINs mit QEC** bedeutet lediglich, dass zur gleichen FIN
   mindestens ein QEC-Fall bekannt ist. Es ist **keine** Bestätigung,
   dass die DTC-Historie diesen Pumpenfall erklärt.

## Methode und Einschränkungen

Die lokale DuckDB aggregiert aus allen Originaldaten pro FIN die Menge
**eindeutiger ECU:DTC-Kombinationen**. Nicht belegte Klartexte werden
nicht ergänzt. Der Python-Prozess erhält für die Musterbildung nur
reduzierte Schlüsselmengen und optionale DTC-Klartexte; originale
Reparaturfreitexte, ZIPs, SSL-Befunde und Rohdateien bleiben unberührt.

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
