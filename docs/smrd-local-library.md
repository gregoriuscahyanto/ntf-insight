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


## Eigenstaendiger Offline-Modus (OHNE Softing-DTS, OHNE Lizenz, OHNE Internet)

Ab jetzt gibt es **zwei getrennte Wege**:

1. Der portable Modus `offline-convert` nutzt ausschliesslich die Python-
   Standardbibliothek und den lokalen NTF-SMR-D/XML-Parser. Er benoetigt
   **keine** Softing.Dts.dll, keinen Dongle, keine BaseSystem-Lizenz und
   **keinen Internetzugriff**.
2. Der optionale `native-export` nutzt wie zuvor eine offiziell
   lizenzierte Softing-Runtime. Er bleibt optional und ist bei der
   derzeitigen Installation wegen `eSYSTEM_LICENSE_ERROR` gesperrt.

**Technische Grenze:** Das gepruefte Original
`CPC3_24.01.00.smr-d` enthaelt zwar lesbare SMR-D-Container-Metadaten,
aber keine klartextlichen ECU-/DTC-XML-Daten im binären Payload. Die
Datenbereiche sind undurchsichtig codiert. Der portable Modus **umgeht
keine Verschluesselung und keine Softing-Lizenzkontrolle**. Wenn nur eine
SMR-D-Datei existiert, wird ein echtes `metadata_only`-Paket erzeugt,
**keine erfundene vollstaendige DTC-Liste**.

Wenn bereits lokal erzeugte XML-Exporte vorliegen, kann NTF Insight
diese offline mit der SMR-D verknuepfen, analysieren und alle vorhandenen
ECUs, Varianten, DTCs, Services, Parameter und SDGs als portables
JSON-Referenzpaket exportieren. Fehlende Felder wie `REPAIR_ACTION`,
`POSSIBLE_CAUSES` und `ERROR_LEVEL` werden **nicht hinzuerfunden**.

### Grafische Offline-Oberflaeche in NTF Insight

Die SMR-D-Verarbeitung kann ohne Terminal in einem separaten,
lizenzfreien PySide6-Fenster gestartet werden:

```powershell
cd (Join-Path $env:USERPROFILE "Documents\GitHub\ntf-insight")
python -m ntf_insight.smrd gui

# Alternative: direktes Modul
python -m ntf_insight.smrd.offline_gui
```

Die Oberflaeche zeigt die bereits im lokalen Ordner
`.ntf-insight/smrd/originale` vorhandenen Dateien, laesst optional
mehrere XML-Referenzen auswaehlen und zeigt die Ausgabe-/Datenabdeckung
an. Zunaechst wird **nur** eine Offline-JSON-Datei erstellt; der
Datenbankimport erfolgt erst nach einem separaten Knopfdruck.
Die GUI verwendet einen eigenen lokalen Worker-Thread und keine
Softing-DTS-API.

Die Hauptanwendung wird hierbei nicht umgebaut. Nach einem optionalen
Offline-Import sind die referenzierten DTCs, Services, Parameter, ECU-
Varianten und SDGs unter **Quellenwissen** als separate SMR-D/XML-Typen
filterbar. Ein echter Fahrzeug-DTC oder eine Fehlerschwelle wird dabei
nicht behauptet.

### Portable Befehle

```powershell
$smrd = "$env:USERPROFILE\.ntf-insight\smrd\originale\CPC3_24.01.00.smr-d"

# Nur SMR-D vorhanden: geschuetzten Container inspizieren und JSON ausgeben
python -m ntf_insight.smrd offline-convert $smrd

# Vorhandene, lokale XMLs als referenzierbare Offline-Daten zuordnen
# (eigene Pfade anpassen, XML muss bereits vorliegen)
$ecuXml = "$env:USERPROFILE\.ntf-insight\smrd\exporte\CPC3_ECU_Export.xml"
$dtcXml = "$env:USERPROFILE\.ntf-insight\smrd\exporte\CPC3_24.01.00_DTCSXML.xml"
python -m ntf_insight.smrd offline-convert $smrd --xml $ecuXml --xml $dtcXml --remember

# Die Verbindung (SMR-D SHA-256 -> lokale XML SHA-256) ist danach gespeichert.
# Die naechste Ausfuehrung braucht weder XML-Argumente noch Softing-Laufzeit:
python -m ntf_insight.smrd offline-convert $smrd

# OPTIONAL: Verifizierte XML-Referenzdaten aus dem Offline-Paket in eine
# lokale NTF-Insight-DuckDB aufnehmen (kein Fahrzeugereignis):
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $smrd).Hash.ToLowerInvariant()
$bundle = "$env:USERPROFILE\.ntf-insight\smrd\exporte\$sha.offline.json"
python -m ntf_insight.smrd offline-import $bundle
```

`--remember` speichert nur die **lokale Zuordnung** unter
`.ntf-insight/smrd/manifeste/offline-links/<SMR-D-SHA256>.json`.
Wenn eine XML-Datei veraendert oder geloescht wird, verweigert der
Converter die alte Zuordnung, bis `--xml --remember` erneut
ausgefuehrt wurde. Das eigentliche Offline-Paket liegt unter
`.ntf-insight/smrd/exporte/<SMR-D-SHA256>.offline.json`.

Bei den beiden bereits bereitgestellten CPC3-Referenz-XMLs
entspricht die exportierte ECU-Information **nur der XML-Abdeckung**:
- `CPC3_ECU_Export.xml`: 3 Varianten, 311 Services, 8.487 Parameter,
  201 SDGs und 1.571 DTC-Referenzen
- `CPC3_24.01.00_DTCSXML.xml`: 1.571 DTC-Referenzen zu denselben
  drei Varianten
- Das Portable-Paket fuehrt gleiche ECU-/Variant-/DTC-Referenzen mit
  mehreren Quellnachweisen zusammen; Unterschiede in Beschreibungen
  bleiben als Alternativen sichtbar.

Alle bekannten Diagnosedaten behalten die Kennzeichnung
`trigger_conditions_validated: false`,
`is_vehicle_observation: false` und
`from_native_smrd_payload: false`. `offline-import` behandelt sie
ausschliesslich als **ECU-Referenzwissen**, niemals als echten Fehler
eines Fahrzeugs.

Die Offline-Funktion kann im Labor dauerhaft ohne Internet laufen,
**sobald die benoetigten referenzierbaren XML-Daten lokal vorhanden sind**.
Sie ist aber **kein gleichwertiger Ersatz** fuer eine vollstaendige
Dekodierung verschluesselter SMR-D-Nutzdaten. Zum Erzeugen bislang
fehlender Informationen wird eine berechtigte Quelle (z.B. bereits
verfuegbare ODX/PDX oder ein lizenzierter Export) benoetigt.

## Nativer Offline-DTS-Exporter (experimentell, Windows x64)

Der native Exporter nutzt die **lokal installierte, lizenzierte** Softing-DTS-.NET-
API `Softing.Dts.dll`; er ruft **nicht** `Smrd2Xml.exe` auf. Die nötigen
DLLs werden weder mit dem Paket ausgeliefert noch ins Git-Repository kopiert.
DTS-Initialisierung und das Laden echter SMR-D-Dateien müssen auf dem lokalen
Windows-PC validiert werden.

### Lokale Runtime

Wird die Lizenz-/Laufzeitinstallation vom Benutzer bereitgestellt, erwartet
NTF-Insight sie standardmäßig unter:

```text
%USERPROFILE%\.ntf-insight\smrd\runtime\SMRxView\
    mvci\bin\Softing.Dts.dll
    mvci\bin\csWrap.dll
    mvci\SystemConfig.xml
    mvci\config\DtsConfig64.xml
    ...
```

Eine andere Installationsstelle kann mit `--runtime-dir` oder
`NTF_SOFTING_RUNTIME_DIR` angegeben werden. Die Runtime muss vollständig
konfiguriert und rechtmäßig lizenziert sein. Keine automatische
Lizenzaktivierung, Entschlüsselung, Config-Manipulation oder Umgehung.

### Beschaedigte Runtime-XML: Wiederherstellung aus dem Original-ZIP

Wenn `native-doctor` `not well-formed (invalid token)` meldet,
**nicht** `native-export` ausfuehren. Es ist moeglich, dass die lokale
Runtime-Konfiguration nach dem Umzug oder durch Bearbeitung ungueltiges XML
enthaelt. Die beiden Konfigurationsdateien im vom Benutzer urspruenglich
bereitgestellten `SMRxView.zip` lassen sich dagegen als gueltiges XML lesen.

Die wiederherstellende Funktion kopiert **nur** defekte
`mvci/SystemConfig.xml` und `mvci/config/DtsConfig64.xml` aus einem vom
Benutzer lokal bereitgestellten Original-ZIP. Bevor Aenderungen moeglich
sind, muessen vier native DLLs im ZIP und in der lokalen Runtime dieselben
SHA-256-Pruefsummen haben. Bereits gueltige Konfigurationsdateien werden
nicht ersetzt. Standardmaessig erfolgt **nur eine Vorschau**.

```powershell
$runtime = "$env:USERPROFILE\.ntf-insight\smrd\runtime\SMRxView"
$originalZip = "$env:USERPROFILE\Downloads\SMRxView.zip"

# Vorschau, keine Veraenderungen
python -m ntf_insight.smrd native-restore-config --runtime-dir $runtime --source-zip $originalZip

# Nur falls die Vorschau zur erwarteten Runtime passt: explizit wiederherstellen
python -m ntf_insight.smrd native-restore-config --runtime-dir $runtime --source-zip $originalZip --apply

# Rein lesend pruefen; alte C:\Nisp-Pfade bleiben zunaechst erhalten.
python -m ntf_insight.smrd native-doctor --runtime-dir $runtime

# Alte Pfade (zuerst nur als Vorschau) auf die lokale Runtime kopieren
python -m ntf_insight.smrd native-prepare --runtime-dir $runtime
python -m ntf_insight.smrd native-prepare --runtime-dir $runtime --apply

# Danach erneut read-only kontrollieren
python -m ntf_insight.smrd native-doctor --runtime-dir $runtime
```

Bei `--apply` entstehen vor jeder geaenderten Datei Sicherungen mit
`.before_smrd_restore_<SHA>.bak`. Lizenzdateien, Runtime-DLLs, SMR-D-Dateien,
andere XML-Dateien und die produktive DuckDB bleiben unveraendert. Der
Wiederherstellungsbefehl entpackt **nicht** das ganze ZIP und schreibt nur
innerhalb von `.ntf-insight/smrd/runtime`.

Sowohl der Wiederherstellungstest als auch der spaetere `native-doctor`
pruefen lediglich statische Voraussetzungen, nicht die korrekte Laufzeit-
Initialisierung. Auch nach gruenem Doctor kann der proprietaere DTS-Aufruf
noch abstuerzen und sollte dann nicht wiederholt werden.

### Laufzeit-Initialisierung und AccessViolationException

Wenn `native-probe` erfolgreich ist, kann sich die native Softing-Laufzeit
trotzdem noch nicht initialisieren: der Probe testet nur die **verwaltete
.NET-Assembly und Methodennamen**, nicht `Statics.getSystem()`.

Das bereitgestellte ursprüngliche SMRxView-Archiv enthält in
`mvci/SystemConfig.xml` und `mvci/config/DtsConfig64.xml` sechs
absolute Pfade zu `C:\\Nisp\\SMRxView`, die nach einem Umzug unter
`.ntf-insight/smrd/runtime/SMRxView` falsch sein können. Der neue
`native-doctor` prüft diese Pfade und die wichtigsten Runtime-Dateien
**rein lesend**, ohne native Funktionen auszuführen.

```powershell
$runtime = "$env:USERPROFILE\.ntf-insight\smrd\runtime\SMRxView"
python -m ntf_insight.smrd native-doctor --runtime-dir $runtime

# Trockenlauf: druckt nur die geplanten Aenderungen
python -m ntf_insight.smrd native-prepare --runtime-dir $runtime

# NUR auf ausdrueckliche Entscheidung des Benutzers hin, in seiner lokalen Kopie
python -m ntf_insight.smrd native-prepare --runtime-dir $runtime --apply

# Danach noch einmal rein lesend kontrollieren
python -m ntf_insight.smrd native-doctor --runtime-dir $runtime
```

`native-prepare --apply` ist **opt-in**; Änderungen sind nur unter
`.ntf-insight/smrd/runtime/` erlaubt. Vor jeder Änderung werden
inhaltshash-benannte `.bak`-Sicherungen der beiden XML-Dateien angelegt.
Nur die bekannten XML-Verzeichnisfelder werden geändert; `license.bin`,
`Softing.Dts.dll`, `csWrap.dll` und SMR-D-Dateien bleiben unverändert.
`native-export` verweigert einen riskanten Aufruf, wenn diese statischen
Voraussetzungen noch nicht erfüllt sind.

Eine grüne Doctor-Meldung **garantiert keinen funktionierenden DTS-Server**.
Wenn `getSystem()` auch nach passender Pfadkonfiguration abstürzt, native
Exportversuche nicht wiederholen: zuerst vollständige DTS-Installation,
Laufzeit-/DLL-Versionen und lizenzierte Initialisierungsumgebung klären.
Das Aufrufverfahren kann sich zwischen Softing-Versionen unterscheiden.

### CSWrap.dll: fehlender Viewer-Einstiegspunkt

Bei der echten Windows-Ausfuehrung war `getSystem()` nach Korrektur
der Runtime-Konfiguration erfolgreich; der Aufruf `LoadViewerProject()`
scheiterte mit `EntryPointNotFoundException`:
`CSNIDTS_DtsSystem_loadViewerProject` fehlt in `csWrap.dll`.

Die urspruenglich mitgelieferte Hersteller-DLL wurde deshalb statisch
auf ihre **tatsaechlich exportierten Funktionen** untersucht. Der
`LoadViewerProject`-Einstiegspunkt ist in der nativen DLL nicht vorhanden,
obwohl die .NET-Assembly eine entsprechend benannte Methode anbietet.
Vorhanden sind hingegen `selectDynamicProject`,
`DtsProject_getDbProject` und `deselectProject` sowie die
DTC-Level- und SDG-Lesemethoden.

Der Exporter verwendet jetzt `SelectDynamicProject(..., string[])`
und die ueber das Interface `MCDProject` erreichbare Eigenschaft
`DbProject`. Die aktuelle .NET-Version kennt **keine oeffentliche**
Methode `DtsSystem.DeselectProject()`, obwohl die native DLL einen
aehnlich benannten Export enthaelt. Deshalb darf die Managed-API-Pruefung
diese Methode nicht voraussetzen. Zum Aufraeumen wird das zurueckgegebene
Projekt nur bei `IDisposable` freigegeben; die Softing-Laufzeit wird
danach mit `Uninitialize()` geschlossen.

Die .NET-Methodendeklarationen `DtsSystem.SelectDynamicProject`,
`MCDProject.DbProject` und `DtsProjectImpl.Dispose` wurden in der
bereitgestellten Assembly statisch verifiziert. Der vollstaendige
Offline-Export einer echten SMR-D ist **noch nicht** bestaetigt.

```powershell
$runtime = "$env:USERPROFILE\.ntf-insight\smrd\runtime\SMRxView"

# Nur DLL-Exporte lesen, ohne Hersteller-DLL auszufuehren
python -m ntf_insight.smrd native-capabilities --runtime-dir $runtime

# .NET-Methoden und native Exportvoraussetzungen pruefen
python -m ntf_insight.smrd native-probe --runtime-dir $runtime
```

`native-capabilities` liest nur die PE-Exporttabelle und laedt bzw.
startet keine proprietaere DLL. Es erwartet:
`native_api_ready: true` und `has_dynamic_project_api: true`;
`managed_only_viewer_api: true` bedeutet, dass der alte
`LoadViewerProject`-Einstiegspunkt **fehlt**, nicht dass die neue
Projektmethode unbrauchbar ist.

Der nachfolgende `native-export` laeuft weiterhin in einem separaten
Windows-PowerShell-Prozess. Bei einem Fehler wird weder die produktive
NTF-DuckDB beschrieben noch ein unvollstaendiger JSON-Export gespeichert.
Es findet keine Fahrzeugkommunikation statt. Ein weiterer nativer
Laufzeitfehler darf nicht mit angeblich erfolgreicher DTC-Extraktion
verwechselt werden.

### Lizenzstatus vor nativer Projektauswahl

Nach erfolgreichen 12 lokalen Regressionstests, `native-capabilities`
(1.777 Funktionen) und `native-probe` war beim echten Aufruf von
`SelectDynamicProject` die Hersteller-Laufzeit **nicht lizenziert**:
`eSYSTEM_LICENSE_ERROR` (58679), `No BaseSystem license was found.
Add license in Configurator under General Settings!` (59075).

Das ist ein Fehler der **Softing-Lizenzverwaltung**, weder ein DTC-
Parserfehler noch ein Hinweis auf eine defekte `.smr-d`. Eine vorhandene
`mvci/config/license.bin`, das Laden der DLL und ein erfolgreicher
`native-probe` garantieren keine aktive DTS-BaseSystem-Berechtigung.

Nur bei vorhandener, rechtmaessiger Berechtigung kann der Benutzer
im **offiziellen Softing DTS System Configurator** unter
**General Settings / Licenses** die aktive BaseSystem-Lizenz und
die zugehoerige Lizenzierungs-Hardware (z.B. USB-Lizenzdongle
oder unterstuetztes Hardware-Interface) pruefen. Bei fehlender
Berechtigung oder unpassender DTS-Version muss der Lizenzverantwortliche
oder Softing-Support kontaktiert werden; eine Demo-/OEM-Ausgabe darf
nicht als voll lizenzierte DTS-Laufzeit angenommen werden.

**Wichtig:** Weder `native-doctor` noch `native-prepare` stellt eine
Softing-Lizenz her. Es gibt keinen automatisierten Lizenz-Import,
keine Lizenzmanipulation und keine Umgehung. Bis der Hersteller die
BaseSystem-Berechtigung bestaetigt, `native-project-test` und
`native-export` nicht erneut aufrufen. Die bereits funktionierenden
XML-Referenzparser und die manuell abgelegten SMR-D-Dateien bleiben
weiterhin verfuegbar.

Der Python-Adapter erkennt die Lizenzfehlermeldung jetzt als
`NativeLicenseError` und nennt die offiziellen Fehlercodes,
statt sie mit inkompatiblen DLL-APIs oder einem Datenbankfehler
zu verwechseln.

### Gezielte dynamische Projektauswahl (ohne DTC-Export)

Wenn `native-probe` erfolgreich ist, sollte zunaechst nur die native
Projektauswahl geprueft werden. Das ist getrennt vom kompletten DTC- und
SDG-Durchlauf. Der neue Befehl startet Windows PowerShell in einem eigenen
Prozess, initialisiert die konfigurierte DTS-Laufzeit, ruft
`SelectDynamicProject` mit einer lokal vorhandenen SMR-D auf und prueft,
ob die `DbProject`-Eigenschaft ein Objekt zurueckgibt.

```powershell
$runtime = "$env:USERPROFILE\.ntf-insight\smrd\runtime\SMRxView"
$smrd = "$env:USERPROFILE\.ntf-insight\smrd\originale\CPC3_24.01.00.smr-d"
python -m ntf_insight.smrd native-project-test $smrd --runtime-dir $runtime --timeout 120
```

Bei Erfolg erscheint eine Zeile beginnend mit
`SOFTING_DTS_PROJECT_OPEN_OK`. Ein Erfolg bedeutet ausschliesslich,
dass die native Projektauswahl und die Datenbankobjekt-Abfrage funktioniert
haben. **Es werden weder DTCs enumeriert noch JSON-Dateien exportiert
oder Datenbankeintraege geschrieben.** Die Softing-Laufzeit kann allerdings
lokale Cache-/Projektdateien erzeugen. Der vollstaendige native DTC-Exporter
ist erst im naechsten Schritt zu testen. Auch dieser Schritt kann bei einer
inkompatiblen Hersteller-Runtime fehlschlagen oder abstuerzen.

### Befehle

```powershell
$smrd = "$env:USERPROFILE\.ntf-insight\smrd\originale\CPC3_24.01.00.smr-d"
$runtime = "$env:USERPROFILE\.ntf-insight\smrd\runtime\SMRxView"

# Prueft zuerst native DLL-Exporte ohne die Softing-Engine zu starten
python -m ntf_insight.smrd native-capabilities --runtime-dir $runtime

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
```

Die Ausgabe enthält für jeden DTC: ECU, Variante, Diagnoseort, DTC-Nummer,
DTC-Text, numerisches Fehlerlevel, alle DTC-spezifischen SDG-Gruppen
(einschließlich Semantik, Caption, Elemente, Originaltext und Text-ID).
`REPAIR_ACTION` und `POSSIBLE_CAUSES` werden zusätzlich in dedizierten
Feldern zusammengefasst, wenn die Original-Semantik dies belegt. Unbekannte
Hersteller-SDGs bleiben vollständig erhalten.

Unvollständige, leere oder fehlerhafte Exporte werden **nicht importiert**.
Ein temporärer Export wird erst nach erfolgreicher Prüfung atomar im lokalen
`smrd/exporte`-Ordner gespeichert. Der Import läuft idempotent über eine
stabile, vom SMR-D-Hash abgeleitete Quellenkennung und erzeugt **keine**
FIN-/VIN-bezogenen Diagnoseereignisse. Fehlerlevel und Reparaturvorschläge
sind keine bewiesenen DTC-Auslösebedingungen.

### Grenzen

- Die öffentliche DTS-API und Signaturen wurden statisch am bereitgestellten
  Softing-Binary geprüft. Der **End-to-End-Lauf mit echter DTS-Runtime** muss
  noch auf einem lizenzierten Windows-PC validiert werden; ein API- oder
  Projektinitialisierungsfehler ist bis dahin möglich.
- Ohne konfigurierte Softing-Laufzeit bleiben `where`, `list`, `inspect`,
  `preview`, `import-xml` und `native-preview` verfügbar;
  `native-export` ist dann **nicht möglich**.
- Eine PySide6-Oberfläche wird später separat über
  `native_export.export_native_dtcs` und
  `native_details.import_native_details` angeschlossen.
- Die Aufrufkette verwendet nur das Offline-Viewer-Projekt.
  Fahrzeugkommunikation, Änderungen an ECU-Parametern oder Flashvorgänge
  werden nicht angestoßen.
