# FIN-ZIP-Import und QuickTest-Gesamtauswertung

## Zwischen PCs übertragen

Die bestehenden Tasten **Alle FINs als ZIP exportieren** und
**Ausgewählte FINs als ZIP exportieren** stehen unter
**Fälle / FIN → FIN / Fallanalyse**. Sie erstellen ein ZIP je FIN mit
Original-QuickTests, QEC-JSON, QEC-PDF-Anhängen und vorhandenen TIPS-Dateien.

1. ZIPs auf genehmigtem Mercedes-Benz-Datenträger übertragen (nicht GitHub).
2. Auf dem Ziel-PC NTF Insight starten.
3. **Datenquellen → Automatisch erkennen → Dateien auswählen…**
   und die FIN-ZIPs gleichzeitig wählen.
4. Die Importzusammenfassung auf Fehler und Datenlücken prüfen.
5. **Fälle / FIN → QuickTest-Gesamtauswertung** aufrufen.

Der Import prüft vor der Installation das Manifest und alle SHA-256-Werte,
die FIN, QEC-Referenz und das erlaubte Pfadschema. QEC-Konflikte werden
nicht überschrieben; zugehörige QEC-Anhänge werden ebenfalls ausgelassen.
Verschiedene QuickTest-PDFs mit gleichem Namen werden separat gespeichert.
Die üblichen PDF-Parser speichern FIN, Steuergeräte und DTCs in DuckDB.

**Nicht enthalten:** Zugangskennwörter, Edge-SSO-Profile, der gesamte
DuckDB-Datenbestand, manuelle Fallkorrekturen und bereits berechnete
Analyse-/Review-Zustände. Der FIN-ZIP-Import ist ein **Quellimport**,
kein Komplett-Backup eines PCs. Die ZIPs können auch FINs ohne QEC-Fall
enthalten. QEC-JSONs bleiben unverändert in ihrer referenzierten lokalen
Ablage, werden aber nicht automatisch als neue Fälle erfunden.

## QuickTest-Gesamtauswertung

Unter **Fälle / FIN → QuickTest-Gesamtauswertung**:

- FIN-Übersicht: Anzahl QuickTests, erste/letzte Beobachtung und DTC-Zahl
- ECU:DTC-Muster: Häufigkeit, beteiligte FINs und Diagnosetermine
- Steuergeräte: gesamte ECU-/FIN-Abdeckung
- ECU-Softwarestände: Versionen und Anzahl der beobachteten FINs
- Filter auf CPC3 (voreingestellt) sowie DTC-Code
- Doppelklick auf FIN öffnet die Einzel-QuickTest-Ansicht

Die Gesamtkennzahlen zählen alle gespeicherten Berichte. ECU/DTC-Filter
betreffen die Muster-Tabellen, **nicht** die FIN-Basisstatistik.
Ein QuickTest mit null DTC bleibt als dokumentierte Diagnosesitzung
erhalten; ein fehlender QuickTest wird niemals als fehlerfrei gezählt.

Eine DTC-Beobachtung ist kein Nachweis einer tatsächlich defekten
Kühlmittelpumpe und noch keine Hersteller-/Lieferantenverantwortung.
Für Vorher-/Nachher-Aussagen werden belastbare Tauschdaten benötigt.

## Sicherheit und Validierung

Die ZIP-Dateien enthalten vertrauliche Fahrzeug- und Lieferantendaten.
Nur freigegebene Unternehmensrechner und Transferwege verwenden.
Keine Rohdaten ins öffentliche Repository, in Issues oder CI-Logs laden.
Die Implementierung wurde mit synthetischen Quellpaketen abgesichert;
der produktive Import ist zusätzlich mit repräsentativen echten FIN-ZIPs
im genehmigten Unternehmensnetz fachlich zu prüfen.
