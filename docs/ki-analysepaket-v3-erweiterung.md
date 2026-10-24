# Erweiterter KI-Analysepaket-Export (Feature-Branch, noch nicht freigegeben)

Die Erweiterung `ki_analysepaket_erweiterung.py` bereitet lokale AutoExport-Diagnosen, AutoExport-Fallbezug, Werkstattvorgaenge, AutoExport-TIPS, Pumpentausche, Fallereignisse, ECU-Versionshistorie, Diagnosequalitaet sowie separate Lieferantenbefund-Tabellen auf.

## Analysegrenzen

- Cluster-Merkmale: Nur technisch geeignete, nachweislich vor dem Pumpentausch liegende ECU:DTC-Beobachtungen. AutoExport-Diagnosen sind einzelne positive Beobachtungen und keine vollstaendigen fehlerfreien QuickTests.
- Nachgelagerte Validierung: Werkstattmassnahmen, Pumpentausche, Nach-Tausch-Diagnosen, Lieferantenbefunde und Laborergebnisse.
- Gleichdatige Beobachtungen bleiben zeitlich unklar. AutoExport-Reparaturdatum ist kein nachgewiesener Pumpentausch.
- Selbst ein NTF-Befund des Lieferanten beweist keine kausale Verantwortlichkeit oder deren Abwesenheit.

## Lieferantenbefunde (PDF/JPG/PNG)

- Bei aktivierter Option `Vollstaendige QEC-Befundungsdokumente und Anhaenge` enthaelt die ZIP verfuegbare PDF/JPG/PNG-Anhaenge, die einer QEC-JSON nachweislich zugeordnet sind.
- Eigenstaendig in NTF Insight archivierte Lieferantenberichte gehoeren nicht automatisch dazu. Der neue Baustein inventarisiert explizite Lieferantenquellen getrennt, exportiert aber deren Originaldateien nicht. Eine spaetere Originalexport-Funktion benoetigt explizite Freigabe, eindeutige Fallbindung und Schutz vor Personen-/FIN-Leakage.
- `lieferantenbefunde_NICHT_CLUSTER.csv` und `lieferantenquellen_bestand_NICHT_CLUSTER.csv` duerfen keine Eingangsdaten der Cluster-Methode sein.

## Datenschutz

Keine echten FINs, QEC-Referenzen, Teil-, Serien- und Chargennummern oder SHA-Quellschluessel in der Analyse-ZIP. Die reversible Zuordnung bleibt ausschliesslich in der privaten lokalen Mapping-Datei und in der lokalen DuckDB. Bei Originalfreitext-Opt-in sind QEC/TIPS/AutoExport-Freitexte nicht anonymisiert. Export bedeutet keine Freigabe fuer externen Upload.

## Status / Abnahme

Der zusaetzliche Modulbaustein ist noch nicht mit `export_ki_analysepaket` verbunden und darf nicht als produktiv wirksame Erweiterung bezeichnet werden. Vor Merge benoetigt: Integration, synthetische Export- und Datenschutztests, CI und lokaler Windows-Smoketest.
