# Zentraler NTF-Workflow (experimentelle Oberfläche)

Der Einstiegspunkt **Workflow** verbindet bereits bestehende Ansichten, ohne bestehende Quellenparser, historische Daten oder Clustering zu ersetzen.

## Schritte

1. **QEC-FIN-Liste:** Kohorte mit frei eingebbarer Sachnummer. Die Auswahl `alle` entsteht durch ein leeres Feld, nicht durch eine fest einprogrammierte Pumpensachnummer.
2. **QEC-Befundung:** Download-/Befundabdeckung aus dem bestehenden QEC-Prüfworkflow.
3. **NTF-Entscheidung:** Offen, NTF und Kein NTF bleiben getrennt; eine Lieferantenschuld wird nicht automatisch zugewiesen.
4. **CPC3 / Diagnose:** Öffnet die existierende QuickTest-/FIN-Analyse. Die Steuergerät-Zuordnung bleibt vom Bauteilprofil abhängig.
5. **Clusteranalyse:** Öffnet die existierende Clusteranalyse. Erst die explizite Fachbestätigung markiert den Workflow-Schritt als geprüft.
6. **Auswertung:** Bericht und versionierter ChatGPT-Rückimport über die bestehenden Funktionen; manuelle Bestätigung wird separat gespeichert.

## Bedienung

- **Direkte Navigation:** Die sechs großen Kacheln sind Schaltflächen. Ein Klick öffnet direkt den QEC-Quellbereich, den QEC-Berichtsabruf, die NTF-Fallentscheidung, QuickTests, die Pumpen-Clusteranalyse oder das ChatGPT-Analysepaket. Die Seite springt dabei zum richtigen Bereich innerhalb der bestehenden Detailansicht; die Workflow-Startseite selbst ist nicht scrollbar.
- **Weiter / Zurück:** Wählt den Nachbar-Schritt und öffnet ebenfalls dessen Arbeitsbereich. Über die Seitenleiste **Workflow** gelangt man jederzeit zur Statusübersicht zurück.
- **Import abbrechen / fortsetzen:** Wenn kein laufender bzw. fortsetzbarer Import vorhanden ist, erscheint direkt auf der Workflow-Seite eine kurze Statusmeldung statt einer funktionslosen Navigation.

- Die Startseite enthält keine `QScrollArea`. Bei einer zu kleinen Fensterhöhe wird kein eigenständiger Seitenscrollbereich hinzugefügt; die Anordnung richtet sich nach der Fenstergröße.
- Der aktive Schritt erhält eine hervorgehobene Kontur; offene und bereits bearbeitete Stationen sind separat markiert. Der Fortschrittsbalken nutzt Quellabdeckung und die explizit bestätigten fachlichen Schritte. Er ist keine Qualitäts- oder Ursachenwahrscheinlichkeit.
- **Pausieren** blockiert Schrittwechsel und fachliche Bestätigung; **Fortsetzen** stellt den Zustand wieder her. Ein bereits laufender Quellenimport wird dadurch nicht abgebrochen. Dies erfolgt weiterhin über den vorhandenen Button **Import abbrechen**, anschließend **Import fortsetzen** unter Datenquellen.
- **Eigene Dateien importieren** öffnet den vorhandenen Dateidialog. Der automatisierte Import bleibt unverändert.
- **PC-Export/-Import** verwendet weiterhin das lokale `.ntfbackup` (vollständiger Snapshot, beim Wiederherstellen Ersetzen statt Zusammenführen).
- **ChatGPT-Paket exportieren / Ergebnis importieren** verwendet die bestehende pseudonymisierte ZIP/JSON-Vorlage samt Paket-ID und Schema-Validierung. Keine automatische Weitergabe; externe Übermittlung und vertrauliche Freitexte benötigen die entsprechenden Freigaben.

## Speicherung und Grenzen

Der Bearbeitungsstand wird unter `workflow_progress` und `workflow_current_context` in derselben lokalen DuckDB gespeichert. Ein `.ntfbackup` übernimmt diese Tabellen mit dem restlichen Datenbestand. Die Sachnummer filtert auf der Workflow-Seite QEC-Abdeckung und NTF-Entscheidungen; **sie begrenzt noch nicht automatisch jede nachgelagerte Clusterrechnung**. Für die Clusterrechnung sind die dortigen vorhandenen Kohorten- und DTC-Filter weiter zu verwenden. Die Workflow-Sachnummer wird beim Öffnen der Pumpen-Clusteranalyse auf deren QEC-Fallkohorte angewendet. Die weitere AutoExport-Analyse ist an die dortige QEC-Kohorte gebunden. Für andere Bauteilprofile ist die bestehende pumpenspezifische Clusteransicht bewusst gesperrt. Der Fortschritt ist eine Navigations-/Review-Hilfe und keine automatische fachliche Freigabe.

Die KI-Ergebnisvorlage liegt bereits im vorhandenen Export als `chatgpt_ergebnis_vorlage.json` zusammen mit `chatgpt_ergebnis_schema.json`; der Import prüft Paket-ID und Belegverweise und markiert die Ergebnisse zuerst ungeprüft.

**Sicherheit:** Keine Firmen-FINs oder vertraulichen Quellberichte in GitHub, öffentliche ChatGPT-Uploads oder Testfixtures übernehmen. Der Transfer ist nicht verschlüsselt; nur freigegebene Speicher- und Übertragungswege verwenden.
