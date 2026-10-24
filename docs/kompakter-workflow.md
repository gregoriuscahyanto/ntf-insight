# Kompakter Workflow (Branch `feature/kompakter-ntf-workflow`)

Die neue Startseite **Workflow** ersetzt perspektivisch die Navigation über
**Datenquellen (alt)**. Alle bisherigen Parser und Fachseiten bleiben verfügbar.

## Anzeige

- Kein Scrollbereich. Die organischen Knoten skalieren mit der verfügbaren Fläche.
- **Grün:** Daten bzw. Bearbeitung vorhanden/abgeschlossen.
- **Gelb:** teilweise erfasst oder in Bearbeitung.
- **Grau:** noch nicht begonnen oder kein Beleg vorhanden.
- Ampelfarbe und Fortschrittsbalken bezeichnen **Datenabdeckung**, niemals
  eine automatische NTF-Entscheidung oder Lieferantenschuld.
- Der eingerahmte Knoten ist die aktuelle **Auswahl**, der kleine Innenmarker
  bezeichnet die **nächste Datenlücke**. Knoten per Klick oder Pfeiltasten wählen.
- QEC-FIN-Anzahl, Befundungsabdeckung, NTF-Entscheidungen, TP-Abdeckung,
  QuickTests und freigegebene NTF-FINs werden aus dem lokalen Bestand ermittelt.
- **Sachnummer** ist frei eingebbar, optional und filtert die QEC-Kohorte exakt
  (ohne Trennzeichen-Unterschiede). Bauteilbezeichnung ist eine lokale
  Benutzerpräferenz. Sachnummerfilter steuert **noch keine** Webscraper,
  kein Löschen und keine automatische Bauteilklassifizierung.

## Tasten und Datenintegrität

| Taste | Vorhandene Implementierung |
|---|---|
| Dateien selbst importieren | `SourcesPage._archive_paths` mit automatischer Quellerkennung |
| QuickTests / QEC einlesen | vorhandene lokale inkrementelle Importwege |
| Abbrechen / Fortsetzen | sicherer Dateigrenzen-Abbruch und persistente Parser-Läufe; Resume nur für unterstützte lokale Modi |
| Fehlerhafte QuickTests | gezielter Neuversuch bekannter Problemdateien statt Scan aller PDFs |
| Parser-Diagnose | lokal erzeugtes ZIP mit optionalen, vertraulichen Originalen |
| PC-Import / -Export | `.ntfbackup`, bestehende Datenbank und Originale; Restore nur nach expliziter Ersetzungsbestätigung |
| ChatGPT-Import / -Export | bestehendes KI-ZIP mit `chatgpt_ergebnis_vorlage.json`, `chatgpt_ergebnis_schema.json`; validierter JSON-Rückimport |

ChatGPT-Pakete sind standardmäßig pseudonymisiert und ohne Rohdokumente
bzw. Freitext. **Die private Pseudonym-Zuordnung nicht hochladen.**
Pseudonymisierte technische Daten können weiterhin vertraulich sein.
Export nur gemäß Unternehmensfreigabe. Rückgaben werden zunächst als
ungeprüfte Vorschläge getrennt von fachlichen Fallentscheidungen gespeichert.

## Grenzen

Die QEC-Einstufung wird weiterhin von autorisierten Nutzern in
**Datenquellen (alt)** vorgenommen. Der Cluster-Knoten führt zur
bestehenden FIN-/Clusterseite; ein gelber Knoten ist keine fertige
Clusteranalyse. Ebenso sind Lieferantenursache, Wiederkehr nach Tausch
und Diagnoseinterpretation keine allein aus Ampelfarben ableitbaren Urteile.
Der QEC-Workflow erlaubt weiterhin alle Sachnummern und Bauteile.
