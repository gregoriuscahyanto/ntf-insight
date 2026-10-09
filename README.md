# NTF Insight

**Component-agnostic field-failure and root-cause analytics for No Trouble Found (NTF) cases.**

NTF Insight is a Python project for reconstructing and analysing vehicle field cases around replaced components. The first use case is a coolant pump whose own diagnostic capability is limited, while the surrounding vehicle — especially the controlling ECU and workshop/field history — contains the evidence needed to understand the case.

The architecture is intentionally **not tied to one component**. Coolant pumps, HV batteries and future component families should use the same generic case, timeline, evidence, similarity and reporting engines, with component-specific profiles and rules layered on top.

> **Status:** pre-alpha native desktop prototype. Local parsers cover QuickTest PDFs, QEC case spreadsheets (including all sheet/column raw records), AutoExport diagnosis/workshop CSVs, Candela diagnostic service descriptions and product Part History PDFs. Supplier-report conclusions, SMR-D trigger semantics and HW/SW release applicability still require source-specific validation.

## Questions the project should answer

For every vehicle / case, NTF Insight should eventually help answer questions such as:

- Why was the returned component classified as NTF?
- Was the replaced component a plausible root cause?
- Did the same fault reappear after component replacement?
- How long / how many kilometres passed until recurrence?
- Did new faults appear after replacement?
- Which evidence points toward the component, vehicle, wiring, software, workshop process or another system?
- Is supplier involvement supported by evidence, unsupported or still unknown?
- Which NTF cases are diagnostically similar?
- Are certain part numbers, variants, suppliers, batches, software states or vehicle populations overrepresented?
- Which cases should an expert review first?
- Which data is missing and prevents a reliable conclusion?

## Design principles

1. **Vehicle- and case-centred, not component-centred**  
   The exchanged part is one event in a larger vehicle history.

2. **Event-based timeline**  
   DTCs, workshop visits, replacements, software changes, supplier findings and reports are represented as dated events.

3. **Explainability before automation**  
   Root-cause assessments must expose the evidence that supports or weakens a conclusion.

4. **Component-agnostic core**  
   Generic logic lives in the core analysis layers. Component-specific knowledge lives in component profiles.

5. **Rules and ML are separate concerns**  
   Rules encode engineering knowledge. Similarity / clustering discovers recurring patterns. A cluster is not automatically a root cause.

6. **Traceability to source data**  
   Derived findings should remain traceable to the original report, diagnostic export or manual source.

7. **Raw data is immutable**  
   Source files are archived unchanged; parsing and enrichment create derived data.

8. **Sensitive field data never belongs in Git**  
   Real VINs/FINs, raw reports, credentials and confidential supplier data must stay outside the repository.

## High-level architecture

```mermaid
flowchart LR
    A[External report systems] --> B[Acquisition providers]
    B --> C[Immutable raw archive]
    C --> D[Ingestion adapters]
    D --> E[Normalization and case assembly]
    E --> F[DuckDB local store]
    F --> G[Case and vehicle timeline]
    G --> H[Feature extraction]
    G --> I[Evidence / rule engine]
    H --> J[Similarity and clustering]
    I --> K[Root-cause assessment]
    J --> K
    K --> L[PySide6 desktop app / reports / exports]

    M[Component profiles] --> E
    M --> H
    M --> I
    N[SMR-D trigger catalog] --> I
    O[HW/SW change catalog] --> H
    O --> I
```

## Component extensibility

A component profile should describe only the knowledge that differs between component families, for example:

- relevant ECUs and DTC families
- component-specific event parsers
- known failure modes
- recurrence rules
- supplier / part metadata
- component-specific features
- evidence rules and thresholds

Conceptually:

```text
components/
├── coolant_pump/
│   ├── rules
│   ├── feature definitions
│   └── mappings
├── hv_battery/
│   ├── rules
│   ├── feature definitions
│   └── mappings
└── ...
```

The generic timeline, evidence, similarity, storage and UI layers should not need to know whether a case concerns a pump or a battery.

## Initial domain model

The first domain model is expected to revolve around:

- `Vehicle`
- `NTFCase`
- `DiagnosticSession`
- `DiagnosticEvent`
- `DTCTriggerDefinition`
- `ECUChangeRecord`
- `RepairEvent`
- `PartReplacement`
- `SoftwareEvent`
- `SupplierFinding`
- `Evidence`
- `Assessment`

A replacement event is the central anchor for **pre/post analysis**.

Example windows:

```text
PRE          replacement          POST_SHORT           POST_LONG
<----------------|--------------------|-------------------->
```

The exact time and mileage windows should be configurable per component and validated on real cases.

## Repository structure

```text
ntf-insight/
├── docs/                       # Architecture and engineering documentation
├── data/                       # Documentation only; no real field data in Git
├── src/ntf_insight/
│   ├── acquisition/            # Provider contracts for automated report download
│   ├── app/                    # PySide6 desktop UI / application layer
│   ├── domain/                 # Generic entities and value objects
│   ├── ingestion/              # Source adapters and parsers
│   ├── storage/                # Persistence abstractions
│   ├── analysis/               # Timeline, recurrence, evidence, quality, similarity
│   ├── demo/                   # Synthetic development/reference fixtures
│   └── components/
│       ├── coolant_pump/       # First component profile
│       └── hv_battery/         # Future / reference component profile
├── tests/
├── ROADMAP.md
├── pyproject.toml
└── README.md
```

## Planned analysis layers

### 1. Timeline reconstruction

Bring all evidence for one FIN/case combination into a chronological table and time plot:

```text
DTCs -> workshop visit -> replacement -> DTCs after replacement -> supplier finding
```

### 2. Replacement recurrence analysis

Derived features should include at least:

- `same_fault_before_after`
- `new_fault_after_replacement`
- `fault_disappeared_after_replacement`
- `time_to_recurrence`
- `distance_to_recurrence`
- `related_ecus_before_after`

### 3. Evidence-based root-cause assessment

The system should distinguish between categories such as:

- component / supplier
- vehicle electrical supply
- wiring / connector
- controlling ECU / software
- surrounding vehicle system
- workshop / process
- unknown / insufficient evidence

Assessments should contain both a result and the evidence behind it.

### 4. Similarity and clustering

Clustering is intended to discover recurring diagnostic patterns, not to assign blame.

Supplier, batch and part metadata should generally be evaluated **after** diagnostic clustering so that the clustering itself is not trivially driven by supplier identity.

## Getting started

### Requirements

- Python 3.11+
- Git

### Local setup

```bash
git clone https://github.com/gregoriuscahyanto/ntf-insight.git
cd ntf-insight

python -m venv .venv
```

Activate the environment and install the project in development mode:

```bash
python -m pip install -e ".[dev]"
pytest
```

Start the desktop application:

```bash
python -m ntf_insight
# or, after installation:
ntf-insight
```

The GUI is a native **PySide6 / Qt desktop application**. The analysis core remains independent of the GUI so that other frontends can be added later without rewriting the engineering logic.

The test suite covers domain models, synthetic cases, GUI startup, raw-file archiving, DuckDB round-trips, case assembly, recurrence, reference knowledge, evidence generation, data quality, similarity, supplier denominators and acquisition orchestration.

## Local data directory

The desktop app stores local working data outside the Git repository by default:

```text
~/.ntf-insight/
├── ntf-insight.duckdb
└── raw/
```

Set `NTF_INSIGHT_DATA_DIR` to override that location. If neither real cases nor FIN-scoped QuickTests exist in the database, the app starts in clearly labelled **demo mode** with fictional data. The Data Sources page archives arbitrary original files with SHA-256 provenance. Known QEC, AutoExport and QuickTest formats are now also parsed locally; unsupported sources remain archived with an explicit pending state.

## Desktop views

The current prototype includes Overview, Data Sources, the unified **FIN / Case / 2D scatter / QuickTest** workspace, DTC Explorer, Suppliers and Data Quality. The FIN/Case workspace treats the FIN + case combination as the analysis unit and includes a chronological time plot for DTCs, diagnostic sessions, ECU states, replacements, software, workshop and supplier events. Data Sources supports multiple files and ZIP packages with local Drag & Drop, automatic format detection and asynchronous ingestion into DuckDB. The Case view can export a deterministic Markdown analysis report.

## Echte Quelldateien lokal laden

Auf einem für Felddaten zugelassenen Rechner im Tab **Datenquellen** die
**Quellenart „Automatisch erkennen“** wählen und ein ZIP oder mehrere
Einzeldateien hineinziehen. QEC-Excel legt FIN/Fall-Anker an, AutoExport-CSV
ergänzt Diagnose-/Werkstattinformationen, QuickTest-PDF ergänzt vollständige
Diagnosesitzungen einschließlich ECU-HW/SW-Ständen.

Alternativ für große ZIP-Pakete:

```powershell
ntf-insight-import "C:\\interner-pfad\\quellen.zip"
python -m ntf_insight
```

Echte Fahrzeug-/Werkstattdaten werden **nicht nach GitHub hochgeladen**,
sondern ausschließlich im konfigurierten lokalen Datenverzeichnis archiviert,
verarbeitet und verknüpft. Unklare FIN/Fall-Zuordnungen werden nicht erzwungen.

Details und aktuelle Grenzen: [docs/real-data-import.md](docs/real-data-import.md).

## QuickTest-PDF mit automatischer FIN-Zuordnung

In **Datenquellen** einen oder mehrere QuickTest-PDFs per Drag & Drop
einfügen. NTF Insight erkennt das Format und liest automatisch FIN,
Diagnosezeit, Kilometerstand, alle Steuergeräte-HW/SW-Metadaten,
DTC-Code/-Status/-Häufigkeit sowie Snapshot-Parameter und den vollständigen
auslesbaren PDF-Seitentext aus.

Das Ergebnis wird **direkt FIN-bezogen in der lokalen DuckDB** gespeichert –
**auch ohne vorhandenen QEC-Fall**. Die App zeigt die Daten unter
**Fälle / FIN → QuickTests nach FIN**. Ein später importierter passender
QEC-Fall kann die bereits gespeicherten Diagnoseereignisse als
abgeleitete Falltimeline übernehmen.

Der ältere einmalige SQLite-Export ist für diese App-Funktion **nicht**
erforderlich. Die PDF-Originale und die Fahrzeugdaten werden nicht nach
GitHub übertragen.

[QuickTest-Import: Bedienung, Datenbanktabellen und Grenzen](docs/quicktest-fin-import.md)

## FIN-Diagnose auch ohne QEC-Fall

Bereits ein erfolgreich importierter QuickTest erscheint im Tab
**Fälle / FIN → FIN / Fallanalyse** mit der Kennzeichnung
**„Nur QuickTests (kein Fall)“**. Die DTCs und Diagnosesitzungen
sind im **Zeitplot und der Ereignistabelle** sichtbar. Es wird
**kein künstlicher NTF-Fall** erzeugt, weshalb noch keine
Vorher-/Nachher-Bewertung oder Lieferantenursache behauptet wird.

Im Tab **Datenquellen** zeigt das Rohdatenarchiv standardmäßig
**verarbeitete Dateien**. Für alte, noch nicht geparste Originale:
**„Alle archivierten Dateien“** oder **„Noch nicht verarbeitet / Fehler“**
auswählen, den Eintrag markieren und über
**„Markierte Datei neu prüfen…“** erneut einlesen.
Die Originale werden dadurch **weder gelöscht noch überschrieben**.

[Mehr zur FIN-Diagnose und Archivbereinigung](docs/quicktest-fin-import.md)

## CDD, Part History, QEC und AutoExport in der Desktop-App

Unter **Datenquellen** die Datei oder das ZIP per Drag & Drop importieren.
Die Formate werden erkannt und getrennt behandelt:

- **CDD/Candela:** Diagnoseklassen und Services werden als **globales
  Steuergerätewissen** gespeichert und durchsucht. Es werden daraus
  **keine unbestätigten DTC-Trigger** oder Fehlerursachen erzeugt.
- **Part History PDF:** produktbezogene Änderungen nach Tag oder
  Kalenderwoche; ohne eine belegte Zuordnung **nicht als FIN-Ereignis**.
- **QEC Excel:** Kanonische QEC-Fälle und zusätzlich sämtliche
  Quellzeilen aus allen enthaltenen Tabellenblättern.
- **AutoExport CSV:** Rohfelder und Diagnose-/Werkstattdaten für
  **alle** importierten FINs werden gespeichert; eine Falltimeline
  erhält nur eindeutig zugeordnete Ereignisse.

Die Inhalte sind in **Quellenwissen** mit Suchfunktion, Filter und
vollständiger Zeilenansicht prüfbar. Bereits archivierte Quellen
können über „**Markierte Datei neu prüfen…**“ erneut verarbeitet
werden, ohne dass die Originaldatei gelöscht wird.

[Details zum lokalen Echtdatenimport](docs/real-data-import.md).

## Reparaturdatum abgleichen und Zeitplot nach km / Datum

Im Tab **Fälle / FIN → FIN / Fallanalyse** werden QEC-`Rep.-Datum` und
ein **mit FIN und Teilenummer übereinstimmender** AutoExport-`RepairDt`
getrennt angezeigt. Ein Reparaturdatum ist nur ein **möglicher
Pumpentausch**, nicht automatisch ein bestätigter physischer Wechsel.

Im Plot sind beide Quellen markiert. Die **X-Achse** lässt sich
zwischen **Datum/Uhrzeit** und **tatsächlichem Kilometerstand** umstellen;
fehlende km-Werte werden unter `km unbekannt` angezeigt, nicht erfunden.
Der **DTC-Filter** blendet nur unpassende DTCs aus; Kurztests,
Steuergeräte-HW-/SW-Stände, Tauschdaten und Lieferantenbefunde
bleiben als Kontext sichtbar.

Bei eindeutigem Kandidaten ist nach Werkstattprüfung eine
**manuelle Tauschanker-Bestätigung mit Audit-Eintrag** möglich.
Bis dahin bleibt die Wiederauftretensanalyse auf dem bisher
dokumentierten Tauschanker.

[Methodik, Bedienung und Bedeutung von ECU-Stand/Lieferantenbefund](docs/replacement-date-comparison.md).

## HW-/SW-Standabweichungen zwischen QuickTests

NTF Insight erkennt jetzt je **FIN und Steuergerät**, wenn sich der
ausgelesene **Hardware- oder Softwarestand** zwischen zwei QuickTests
unterscheidet. In **Fälle / FIN → FIN / Fallanalyse** werden die
alte/neue Version, beide Beobachtungszeitpunkte und Kilometerstände in
einer Vergleichstabelle angezeigt. Im Zeitplot erscheinen **HW-Quadrate**
und **SW-Dreiecke** sowie der mögliche Beobachtungszeitraum.

In **QuickTests nach FIN** werden abweichende ECU-HW-/SW-Werte für den
ausgewählten Bericht kontrastreich hervorgehoben. Die Markierungen
bleiben auch beim Filtern von DTCs sichtbar und funktionieren mit beiden
X-Achsen (**Datum** und **Kilometerstand**).

**Wichtig:** Eine nachgewiesene Versionsabweichung ist **kein
nachgewiesener Flash, Steuergerätetausch oder tatsächliches Update am
späteren QuickTest-Tag**. Der Änderungszeitpunkt bleibt unbekannt.

[Erkennung, Anzeige und fachliche Grenzen](docs/ecu-stand-vergleich.md)

## Ein gemeinsamer Arbeitsbereich: Streudiagramm, FIN/Fallanalyse, QuickTests

Unter **Fälle / FIN** gibt es jetzt genau drei zusammengehörige Register:
**2D-Streudiagramm**, **FIN / Fallanalyse** und **QuickTests nach FIN**.
Eine gemeinsame Fall-/FIN-Auswahl verbindet die Informationen.
Punkt- und Tabellenklicks im Scatter wählen denselben echten QEC-/NTF-Fall
wie die Fallanalyse; der QuickTest-Reiter übernimmt dessen FIN.
QuickTest-FINs ohne Schadteilfall bleiben als eigene, read-only
FIN-Vorschau sichtbar und erscheinen **nicht als zusätzliche Scatter-Punkte**.

Das **2D-Streudiagramm** enthält unmittelbar unter dem Plot die
Berechnungsgrundlage (sechs Gruppen, Gewichte, SVD-Transformation),
die Anzahl der Matrixspalten, erklärte Varianz, wichtigste
Achsenladungen, alle Fallkoordinaten, sowie **tatsächliche
gewichtete Jaccard-Paarähnlichkeiten** mit Merkmalsabdeckung,
Gruppenwerten und vollständig nachvollziehbarer Summenformel.

Die konservative Complete-Link-Clusterung bleibt unverändert für
die Farben und Zuordnungen erhalten. Die früheren eigenständigen
Oberflächen **Fall-Cluster**, **DTC-Netzwerk** und
**Paarvergleich (Basis)** entfallen aus der Navigation.
Die SVD-Punktabstände sind keine Ursachenwahrscheinlichkeiten
und keine Jaccard-Werte. QEC-/SSL-Endbefundtexte werden nur
**nachgelagert** eingeblendet, nie als Diagnosemerkmale verwendet.

**QuickTest und AutoExport** können dieselbe DTC-Beobachtung enthalten:
die Originalquellen bleiben nachvollziehbar erhalten, und
DTC-Ansichten konsolidieren eindeutige Querquellenüberlappungen
vorsichtig. Die Scatter-/Cluster-Signatur verwendet ohnehin
je Fall einzigartige ECU:DTC-Merkmale.

[Bedienung und komplette numerische Methodik](docs/fin-workspace.md) ·
[Clustering-Grundlagen und fachliche Grenzen](docs/case-clustering.md)

## Manuelle Fallerfassung

Unter **Fälle / FIN** sind **+ Neuer Fall** und **+ Ereignis** verfügbar. Kurztests (auch mit **0 DTCs**), DTCs, Tausche, Werkstattmaßnahmen, ECU-HW/SW-Stände, Software-Updates, Lieferantenbefunde und freie Notizen können ohne Parser erfasst werden.

Ein Eintrag lässt sich über **Ereignistabelle → Markiertes Ereignis korrigieren** überarbeiten. **Änderungsverlauf** zeigt den Vorher-/Nachher-Zustand mit Zeitstempel und lokalem Benutzer. Manuelle Informationen werden in DuckDB gespeichert; Originaldateien bleiben unverändert.

Demo-Fälle sind schreibgeschützt. Ein neu angelegter echter Fall wechselt automatisch in den lokalen Datenmodus, ohne die Demo-Daten zu übernehmen. Bei jeder Speicherung aktualisiert die App die anderen Ansichten.

Anleitung und Grenzen: [docs/manual-entry.md](docs/manual-entry.md).

## Fallähnlichkeit und Clustering

Die neue Oberfläche liegt vollständig unter **Fälle / FIN → 2D-Streudiagramm**.
Sie zeigt QEC-/NTF-Fälle als farbige Punkte mit einer vollständigen
Berechnungserklärung (Gewichte, Matrixgröße, SVD-Varianz und -Ladungen,
Fallkoordinaten, Jaccard-Score einschließlich aller Gruppenbeiträge).

**Die Clusterfarben stammen unverändert aus der konservativen
Complete-Link-Berechnung.** TruncatedSVD bestimmt nur die X-/Y-Position.
Die Abstände sind keine Jaccard-Werte. Bauteilfamilien werden getrennt
projiziert; QuickTests ohne Schadteilfall werden nicht als Clusterfall gezählt.

**QuickTest und AutoExport:** Überlappende ECU:DTC-Beobachtungen werden
bei exakt übereinstimmenden Identifikatoren, Datum und km konservativ
in Ereigniszahlen und Timeline nur einmal gezählt. Die Originalzeilen
und beide Quellenbelege bleiben erhalten. Die Clustersignatur verwendet
einzigartige ECU:DTC-Mengen pro Fall.

**QEC-/SSL-Endbefunde** werden nur nachgelagert angezeigt, nicht zur
Position oder Fallähnlichkeit verwendet. Ein fehlendes
Befundabschlussdatum wird nicht künstlich als Tauschdatum ausgegeben.

**PCA/SVD werden nicht als Clusterverfahren eingesetzt.**
Die Clusterbildung beruht weiterhin auf gewichteten Jaccard-Vergleichen
und Complete-Link. Die Gewichte und Schwellen müssen mit echten,
fachlich geprüften Fällen validiert werden.

[Experimentelle ML-Cluster mit HDBSCAN](docs/experimental-hdbscan.md) ·
[Repräsentative Fälle für begrenztes Untersuchungsbudget (K-Medoids)](docs/representative-clustering.md) ·
[Warum die Fallzahlen/Cluster nach dem AutoExport anders aussehen](docs/cluster-quality-audit.md) ·
[Neuer gemeinsamer FIN-Arbeitsbereich und Zahlenmethodik](docs/fin-workspace.md) ·
[Clustering-Grundlagen](docs/case-clustering.md).

## Development conventions

- Keep the generic domain model independent from a specific component.
- Put source-system specifics behind ingestion adapters.
- Put component-specific engineering knowledge under `components/`.
- Prefer small, testable transformations over large notebooks or scripts.
- Store normalized data locally in DuckDB / Parquet-compatible structures and keep raw source files unchanged.
- Every automated assessment should be reproducible from stored input evidence.
- Use synthetic or anonymised fixtures in tests.

## Data protection and confidentiality

This project is intended to work with potentially sensitive field, vehicle, diagnostic and supplier information.

Do **not** commit:

- real VINs / FINs
- downloaded field or workshop reports
- customer information
- credentials, tokens or cookies
- confidential supplier findings
- proprietary diagnostic databases or exports

Use synthetic or irreversibly anonymised data for examples and automated tests.

## Input data

See [docs/data-requirements.md](docs/data-requirements.md) for the minimum and recommended source files and [docs/source-contracts.md](docs/source-contracts.md) for canonical parser outputs. In addition to per-vehicle events, NTF Insight treats SMR-D DTC trigger definitions and HW/SW release changes as versioned engineering reference knowledge. A known diagnostic session with zero relevant DTCs is preserved explicitly so missing data is never confused with a clean post-replacement test.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the implementation plan.

Concrete QEC, AutoExport CSV and QuickTest PDF formats are now supported by synthetic regression-tested local ingestion. Next priorities are expert review of imported cases, Candela/SMR-D semantics, HW/SW change-history formats and supplier-report extraction.

## Weitere Dokumentation

- [Mercedes-Benz Corporate Design](docs/mercedes-design.md)
- [Managed Windows Environment](docs/windows-managed-environment.md)
- [Enterprise CI/CD Pipeline](docs/enterprise-pipeline.md)
- [Canonical Source Contracts](docs/source-contracts.md)
- [Lokaler ZIP- und Echtdatenimport](docs/real-data-import.md)
- [Automatischer QuickTest-PDF-Import nach FIN](docs/quicktest-fin-import.md)
- [Manuelle Fallerfassung](docs/manual-entry.md)
- [Fall-Clustering und Ähnlichkeitsmethodik](docs/case-clustering.md)
