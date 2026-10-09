# Roadmap

NTF Insight is being built as a reusable, component-agnostic platform for No-Trouble-Found field analysis.

The implementation order is deliberate: trustworthy source data and traceability first, deterministic engineering analysis second, clustering/ML only after the underlying case model is reliable.

## Phase 0 — Project foundation

**Goal:** maintainable native Python desktop application.

- [x] Repository, README and project structure
- [x] PySide6 desktop scaffold
- [x] pytest CI including offscreen GUI smoke test
- [x] Local data-directory configuration with demo/local bootstrap
- [x] DuckDB dependency and local persistence foundation
- [ ] Dependency lock strategy
- [x] Rotating local structured logging
- [ ] Coding/linting conventions
- [ ] Enterprise deployment and credential configuration

## Phase 1 — Generic domain model

**Goal:** describe an NTF case independently of a particular component or source system.

Implemented:

- [x] Vehicle
- [x] NTFCase
- [x] DiagnosticSession
- [x] DiagnosticEvent
- [x] ECUStateObservation
- [x] RepairEvent
- [x] PartReplacement
- [x] SoftwareEvent
- [x] SupplierFinding
- [x] Evidence / Assessment
- [x] DTCTriggerDefinition
- [x] ECUChangeRecord
- [x] PopulationExposure
- [x] component_profile_id and explicit replacement anchor support
- [x] synthetic cases for recurrence, component fault, supply issue, software issue, new post-swap fault and insufficient data

## Phase 2 — Acquisition, ingestion and provenance

**Goal:** every imported result remains traceable to its original source.

Implemented source-independent foundation:

- [x] SHA-256 content-addressed raw archive
- [x] source-artifact provenance persisted in DuckDB
- [x] versioned parser-run provenance (success/partial/failure, output count, errors)
- [x] local manual revision log with actor, timestamp and before/after JSON
- [x] desktop raw-file archive/import view
- [x] multi-file Drag & Drop with explicit empty state
- [x] parser contracts for vehicle lists, short tests, replacements, supplier findings, workshop history, vehicle SW history, SMR-D, HW/SW changes and population data
- [x] canonical parser result models
- [x] ambiguity-safe case assembly by FIN / explicit case ID
- [x] report-provider interface for future API/browser download
- [x] batch acquisition orchestration with per-FIN failures
- [x] canonical source-contract documentation

Pending real files/systems:

- [x] QEC Excel vehicle/case and replacement anchor parser
- [x] QuickTest PDF diagnostic sessions with all-ECU DTC and HW/SW states
- [x] AutoExport DTC CSV parser (date-only observations, no invented clean sessions)
- [x] AutoExport workshop/claim CSV parser
- [x] all-FIN AutoExport raw-record persistence, including duplicated header fields
- [x] QEC workbook all-sheet/all-column source records without duplicate NTF cases
- [x] Candela CDD diagnostic class/service/qualifier parser (no invented SMR-D rules)
- [x] product Part History PDF change and calendar-week granularity parser
- [x] source knowledge explorer with local DB search, filters and pagination
- [x] safe ZIP expansion, automatic format recognition, SHA-256 archive
- [x] idempotent FIN/fall attachment and asynchronous desktop import
- [x] FIN-scoped QuickTest storage without an existing QEC case
- [x] safely reprocess previously archived/uncategorized QuickTests without changing provenance
- [x] archive view for processed, all and outstanding source files
- [ ] additional replacement-list formats
- [ ] SMR-D parser
- [ ] HW/SW release/change parser
- [x] vehicle-specific HW/SW state extraction from supported QuickTest/CSV
- [ ] parse vehicle-specific SW flash/update history from separate sources
- [ ] supplier finding parser
- [x] workshop/claim parser for supported AutoExport CSV
- [ ] installed-population parser
- [ ] concrete automated report provider(s)

## Phase 3 — Coolant-pump profile

**Goal:** add coolant-pump engineering knowledge without contaminating the generic core.

Implemented:

- [x] generic ComponentProfile API and registry
- [x] coolant_pump profile
- [x] CPC3 recorded as primary ECU
- [x] HV-battery placeholder profile proving multi-component structure

Pending source-grounded knowledge:

- [ ] actual CPC3 DTC families
- [ ] DTC-to-symptom/failure-mode mappings
- [ ] SMR-D trigger/enable/healing logic
- [ ] applicable CPC3 HW/SW change records
- [ ] verify applicability of product Part History to individual serial numbers and FINs
- [ ] map CDD service definitions to actual CPC3 diagnostic applicability
- [ ] part/supplier metadata mappings
- [ ] validated recurrence windows
- [ ] component-specific root-cause rules

## Phase 4 — Timeline and pre/post replacement analysis

**Goal:** use the replacement as a diagnostic experiment.

Implemented:

- [x] chronological multi-source timeline
- [x] per-case temporal plot for DTCs and engineering events
- [x] explicit diagnostic sessions, including zero-DTC tests
- [x] same-fault recurrence
- [x] disappeared faults only when a real post-test exists
- [x] new post-replacement faults
- [x] time to first recurrence
- [x] distance to first recurrence
- [x] unique DTC / ECU counts in feature extraction
- [x] actual ECU HW/SW state observations
- [x] reference linkage to DTC triggers and HW/SW changes

Pending calibration:

- [ ] PRE / POST_SHORT / POST_LONG windows validated on field data
- [ ] component-specific recurrence equivalence rules
- [ ] richer temporal co-occurrence features
- [ ] cross-case / fleet temporal trend plots with DTC and event filters

## Phase 5 — Explainable evidence and root cause

**Goal:** engineering evidence before opaque classification.

Implemented:

- [x] generic Evidence model with category hints and support/contradiction direction
- [x] same fault after replacement weakens component hypothesis
- [x] known post-test disappearance supports component hypothesis
- [x] returned-part NTF / fault-found evidence
- [x] semantic multi-ECU supply-voltage signal
- [x] documented HW/SW changes linked to observed DTCs
- [x] actual vehicle software state linked separately from release knowledge
- [x] unified analyze_case service
- [x] evidence shown in desktop case view
- [x] structural case-integrity validation

Pending real-case validation:

- [ ] calibrate rule strengths
- [ ] connector/wiring-specific rules
- [ ] cooling-system/system-level rules
- [ ] workshop-process rules
- [ ] final root-cause proposal policy and confidence model
- [ ] expert confirmation/correction workflow

## Phase 6 — Similarity and clustering

**Goal:** discover recurring diagnostic patterns without using supplier identity as the clustering shortcut.

Implemented:

- [x] interpretable case feature extraction
- [x] Polars feature frame
- [x] transparent weighted/Jaccard similarity baseline
- [x] pre-intervention diagnostic signature (without supplier or repair-outcome leakage)
- [x] conservative complete-link case clusters with adjustable similarity threshold
- [x] case similarity heatmap and nearest-neighbour retrieval
- [x] display historical interventions and post-intervention evidence separately
- [x] similarity view in desktop app
- [x] interactive DTC co-occurrence network visualization

Pending real sample size:

- [ ] evaluate whether diagnostically similar cases share expert-confirmed effective solutions
- [ ] calibrate diagnostic weights and minimum evidence on reviewed field cases
- [ ] feature validation / scaling
- [ ] HDBSCAN
- [ ] UMAP visualization
- [ ] cluster explanations
- [ ] text embeddings for complaint/workshop text if they add value

## Phase 7 — Supplier and population analytics

**Goal:** distinguish raw sample counts from statistically meaningful field rates.

Implemented:

- [x] supplier summaries use only the investigated replacement
- [x] summaries are separated by component type
- [x] returned NTF / fault-found / recurrence counts
- [x] PopulationExposure model
- [x] normalized NTF-per-1000 calculation only when denominator exists
- [x] desktop supplier view leaves rates blank when population data is absent

Pending:

- [ ] real installed-population data
- [ ] part number / revision / batch views
- [ ] production-period and vehicle-variant stratification
- [ ] uncertainty/statistical comparison once sample sizes justify it

## Phase 8 — Desktop application

Current PySide6 views:

- [x] Overview
- [x] Data Sources + raw archive
- [x] Combined FIN + case explorer
- [x] read-only FIN-only QuickTest previews in case table, timeline and time plot (no fabricated NTF case)
- [x] QEC-/AutoExport-Datumsabgleich nach FIN, Teilenummer und Kilometerstand
- [x] separate Tausch- und Reparaturkandidaten im Zeitplot
- [x] umschaltbare X-Achse (Datum / Kilometerstand), fehlende km sichtbar
- [x] DTC-Filter mit stets sichtbaren Kurztest-, ECU-, Tausch- und Lieferantenereignissen
- [x] manuelle Bestätigung eines Tauschankers mit Audit-Trail
- [x] dashboard vehicle/QuickTest counts independent of existing QEC cases
- [x] Manually create FIN/case combinations in persistent DuckDB
- [x] Manually add short tests, DTCs, replacements, repairs, software/ECU state, supplier findings and notes
- [x] Correct individual case events with audit history; original raw reports stay intact
- [x] Automatically refresh all analytical desktop views after manual changes
- [x] Case timeline table and temporal plot
- [x] Generated evidence
- [x] DTC Explorer with trigger/change linkage
- [x] Similarity / clustering baseline
- [x] native desktop case-cluster/heatmap and comparable repair evidence
- [x] Supplier analytics foundation
- [x] Data Quality
- [ ] edit case master metadata with history
- [ ] role-based permissions / centrally governed audit retention
- [x] real source ZIP drag & drop import with automatic classification
- [ ] interactive source-to-evidence drill-down
- [ ] cluster visualization
- [x] deterministic Markdown case report/export
- [ ] PDF/HTML report rendering
- [ ] packaging as distributable Windows executable

## Phase 9 — Additional component families

**Goal:** prove that new components are profiles, not forks.

- [x] HV-battery placeholder
- [ ] reintroduce HV-battery source/rule profile
- [ ] additional pumps/actuators
- [ ] sensors
- [ ] ECUs
- [ ] other returned supplier components

## Cross-cutting rules

**Missing data is explicit.** No post-test is not the same as a clean post-test.

**Traceability is mandatory.** Derived evidence must retain a route back to the source artifact and parser/rule version.

**Supplier blame is never inferred from one DTC.** Supplier involvement is an evidence-based conclusion.

**Reference knowledge and vehicle state remain separate.** A release note does not prove that a FIN had that release.

**Raw counts are not failure rates.** Supplier rates require installed-population denominators.

**ML does not assign causality by itself.** Clustering discovers patterns; root-cause assessment remains explainable.

## Next source-dependent milestone

With representative QEC, AutoExport and QuickTest structures now available:

1. run the new local ZIP importer on an authorized machine and check case/FIN links,
2. manually validate completeness and before/after evidence for selected cases,
3. validate product Part History / Candela reference rows and implement applicability matching,\n4. add structured supplier-return report parsing,
5. obtain actual SMR-D triggers and implement the condition/healing parser,
6. obtain CPC3 HW/SW release/change history and validate version applicability,
7. validate recurrence/evidence rules against reviewed cases,
8. calibrate clustering and only then automated root-cause proposals.
