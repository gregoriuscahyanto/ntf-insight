# SMR-D: lokale Bibliothek und allgemeiner XML-Parser

Dieser erste Stand verarbeitet **beliebige ECU-Namen** und die beobachteten
`Smrd2Xml`-XML-Schemata `ECUS` und `Smrd2Xml`. Der Code liegt in
`src/ntf_insight/smrd/`. Proprietäre SMR-D-Dateien, Softing-Binaries,
Lizenzen und exportierte Fahrzeugdaten gehören **nicht** ins Repository.

## Speicherorte

```text
~/.ntf-insight/
  ntf-insight.duckdb
  smrd/
    originale/   # SMR-D, auch manuell abgelegt; Dateinamen bleiben erhalten
    exporte/     # optionale XML-Exporte aus lizenzierter lokaler Runtime
    manifeste/   # SHA-256-Provenienz
```

`NTF_INSIGHT_DATA_DIR` überschreibt wie bisher den Datenstammordner.
Ein zusätzlicher `benutzer/<name>`-Ordner wird **nicht** angelegt.

## CLI

```powershell
python -m ntf_insight.smrd where
python -m ntf_insight.smrd list
python -m ntf_insight.smrd add ".\smrd_files\ECU.smr-d"
python -m ntf_insight.smrd preview ".\CPC3.xml"
python -m ntf_insight.smrd import-xml ".\CPC3.xml" --skip-dtcs
```

Importierte XML-Referenzen werden in der bestehenden DuckDB über
`SourceKnowledgeStore` gespeichert, nicht als fahrzeugspezifische DTC-Ereignisse.
`Min`/`Max` von Parametern sind **keine** nachgewiesenen DTC-Auslöseschwellen.

## Grenzen und nächste Schritte

Der binäre Diagnose-Payload einer proprietären `.smr-d` wird nicht ohne
Softing-Laufzeit decodiert. `REPAIR_ACTION`, `POSSIBLE_CAUSES` und
DTC-Fehlerlevel werden ausschließlich importiert, **wenn sie im XML stehen**.
Die aktuellen `Smrd2Xml.exe`-Exporte enthalten diese Informationen zum Teil
nicht. Ein eigener, lizenzkonformer DTS-Detail-Exporter und eine GUI sind
separate Arbeiten. Bitte `SMRxView` und die bestehende Bridge **noch nicht
löschen**, bevor der Windows-Exportersatz getestet ist.
