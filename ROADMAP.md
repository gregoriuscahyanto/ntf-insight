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
- [x] desktop raw-file archive/import view
- [x] parser contracts for vehicle lists, short tests, replacements, supplier findings, workshop history, vehicle SW history, SMR-D, HW/SW changes and population data
- [x] canonical parser result models
- [x] ambiguity-safe case assembly by FIN / explicit case ID
- [x] report-provider interface for future API/browser download
- [x] batch acquisition orchestration with per-FIN failures
- [x] canonical source-contract documentation

Pending real files/systems:

- [ ] vehicle / FIN list parser
- [ ] short-test parser
- [ ] replacement-list parser
- [ ] SMR-D parser
- [ ] HW/SW release/change parser
- [ ] vehicle-specific HW/SW extraction
- [ ] supplier finding parser
- [ ] workshop/claim parser
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
- [ ] part/supplier metadata mappings
- [ ] validated recurrence windows
- [ ] component-specific root-cause rules

## Phase 4 — Timeline and pre/post replacement analysis

**Goal:** use the replacement as a diagnostic experiment.

Implemented:

- [x] chronological multi-source timeline
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
- [x] similarity view in desktop app

Pending real sample size:

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
- [x] Vehicle / FIN explorer
- [x] Case timeline
- [x] Generated evidence
- [x] DTC Explorer with trigger/change linkage
- [x] Similarity / clustering baseline
- [x] Supplier analytics foundation
- [x] Data Quality
- [ ] real import workflow after concrete parsers exist
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

Once representative original files are available:

1. inspect and freeze anonymized fixtures for 1–3 real short tests,
2. implement the short-test parser including ECU HW/SW states,
3. import the pump replacement anchor,
4. replace selected DEMO cases with real normalized cases,
5. implement the SMR-D trigger parser,
6. implement the CPC3 HW/SW change-history parser,
7. validate recurrence/evidence rules against manually reviewed cases,
8. only then tune clustering and automated root-cause proposals.
