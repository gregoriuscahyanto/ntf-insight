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


## Nativer Offline-DTS-Exporter (experimentell, Windows x64)

Der native Exporter nutzt die **lokal installierte, lizenzierte** Softing-DTS-.NET-
API \`Softing.Dts.dll\`; er ruft **nicht** \`Smrd2Xml.exe\` auf. Die nötigen
DLLs werden weder mit dem Paket ausgeliefert noch ins Git-Repository kopiert.
DTS-Initialisierung und das Laden echter SMR-D-Dateien müssen auf dem lokalen
Windows-PC validiert werden.

### Lokale Runtime

Wird die Lizenz-/Laufzeitinstallation vom Benutzer bereitgestellt, erwartet
NTF-Insight sie standardmäßig unter:

\`\`\`text
%USERPROFILE%\.ntf-insight\smrd\runtime\SMRxView\
    mvci\bin\Softing.Dts.dll
    mvci\bin\csWrap.dll
    mvci\SystemConfig.xml
    mvci\config\DtsConfig64.xml
    ...
\`\`\`

Eine andere Installationsstelle kann mit \`--runtime-dir\` oder
\`NTF_SOFTING_RUNTIME_DIR\` angegeben werden. Die Runtime muss vollständig
konfiguriert und rechtmäßig lizenziert sein. Keine automatische
Lizenzaktivierung, Entschlüsselung, Config-Manipulation oder Umgehung.

### Befehle

\`\`\`powershell
$smrd = "$env:USERPROFILE\.ntf-insight\smrd\originale\CPC3_24.01.00.smr-d"
$runtime = "$env:USERPROFILE\.ntf-insight\smrd\runtime\SMRxView"

# Prüft lediglich die öffentliche .NET-API, ohne SMR-D zu öffnen
python -m ntf_insight.smrd native-probe --runtime-dir $runtime

# Liest DTCs und DTC-spezifische SDGs mit der nativen Offline-DTS-API
python -m ntf_insight.smrd native-export $smrd --runtime-dir $runtime

# Erst lokale JSON-Datei inspizieren, ohne DuckDB zu ändern
$json = "$env:USERPROFILE\.ntf-insight\smrd\exporte\<SHA256>.native-dtc.json"
python -m ntf_insight.smrd native-preview $json --query P060FFB

# Expliziter lokaler DB-Import
python -m ntf_insight.smrd native-import $json

# Optional Export + Import in einem Schritt (nur bei erfolgreichem Export):
python -m ntf_insight.smrd native-export $smrd --runtime-dir $runtime --import-result
\`\`\`

Die Ausgabe enthält für jeden DTC: ECU, Variante, Diagnoseort, DTC-Nummer,
DTC-Text, numerisches Fehlerlevel, alle DTC-spezifischen SDG-Gruppen
(einschließlich Semantik, Caption, Elemente, Originaltext und Text-ID).
\`REPAIR_ACTION\` und \`POSSIBLE_CAUSES\` werden zusätzlich in dedizierten
Feldern zusammengefasst, wenn die Original-Semantik dies belegt. Unbekannte
Hersteller-SDGs bleiben vollständig erhalten.

Unvollständige, leere oder fehlerhafte Exporte werden **nicht importiert**.
Ein temporärer Export wird erst nach erfolgreicher Prüfung atomar im lokalen
\`smrd/exporte\`-Ordner gespeichert. Der Import läuft idempotent über eine
stabile, vom SMR-D-Hash abgeleitete Quellenkennung und erzeugt **keine**
FIN-/VIN-bezogenen Diagnoseereignisse. Fehlerlevel und Reparaturvorschläge
sind keine bewiesenen DTC-Auslösebedingungen.

### Grenzen

- Die öffentliche DTS-API und Signaturen wurden statisch am bereitgestellten
  Softing-Binary geprüft. Der **End-to-End-Lauf mit echter DTS-Runtime** muss
  noch auf einem lizenzierten Windows-PC validiert werden; ein API- oder
  Projektinitialisierungsfehler ist bis dahin möglich.
- Ohne konfigurierte Softing-Laufzeit bleiben \`where\`, \`list\`, \`inspect\`,
  \`preview\`, \`import-xml\` und \`native-preview\` verfügbar;
  \`native-export\` ist dann **nicht möglich**.
- Eine PySide6-Oberfläche wird später separat über
  \`native_export.export_native_dtcs\` und
  \`native_details.import_native_details\` angeschlossen.
- Die Aufrufkette verwendet nur das Offline-Viewer-Projekt.
  Fahrzeugkommunikation, Änderungen an ECU-Parametern oder Flashvorgänge
  werden nicht angestoßen.
