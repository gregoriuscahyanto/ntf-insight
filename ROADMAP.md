# Roadmap

This roadmap turns NTF Insight from a project scaffold into a reusable analytics platform for No Trouble Found (NTF) field cases.

The order is deliberate: **first create trustworthy, traceable case data; then add engineering logic; then add similarity / clustering; finally build a polished application.**

## Phase 0 — Project foundation

**Goal:** establish a maintainable, component-agnostic Python project.

- [x] Create repository
- [x] Add project README
- [x] Add initial source and test structure
- [ ] Define coding conventions and contribution workflow
- [ ] Add CI for linting and tests
- [ ] Add dependency locking
- [ ] Add structured logging
- [ ] Define configuration approach for local / enterprise environments

**Exit criterion:** a clean Python package installs locally and the test suite runs.

---

## Phase 1 — Domain model and synthetic cases

**Goal:** represent an NTF case independently from any concrete source system.

Implement core entities:

- [ ] Vehicle
- [ ] NTFCase
- [ ] DiagnosticEvent
- [ ] RepairEvent
- [ ] PartReplacement
- [ ] SoftwareEvent
- [ ] SupplierFinding
- [ ] Evidence
- [ ] Assessment

Define stable identifiers and relationships between them.

Create synthetic fixtures for:

- [ ] clear component fault
- [ ] same DTC before and after replacement
- [ ] voltage / supply issue
- [ ] wiring / connector issue
- [ ] software-related case
- [ ] insufficient-data case

**Exit criterion:** a synthetic case can be loaded and rendered as a chronological vehicle timeline.

---

## Phase 2 — Data ingestion and raw archive

**Goal:** automate acquisition and parsing while preserving source evidence.

Build ingestion interfaces for:

- [ ] vehicle / FIN lists
- [ ] diagnostic exports
- [ ] workshop / field reports
- [ ] part replacement history
- [ ] software history
- [ ] supplier findings
- [ ] generic file imports such as CSV, XLSX, PDF and JSON where required

For every source artifact store metadata such as:

- source system
- vehicle / case reference
- retrieval time
- report date
- file hash
- parser version
- parse status

Raw files should remain immutable.

**Exit criterion:** a FIN list can be processed reproducibly into normalized case data.

---

## Phase 3 — Coolant pump profile

**Goal:** implement the first real component profile without contaminating the generic core.

Define for the coolant pump:

- [ ] relevant ECUs
- [ ] relevant CPC3 DTC families
- [ ] known DTC-to-symptom mappings
- [ ] replacement event detection
- [ ] component-specific part metadata
- [ ] recurrence windows
- [ ] initial root-cause categories
- [ ] known confounders such as supply, wiring, connector, ECU and cooling-system faults

**Exit criterion:** a coolant-pump case can be analysed using only generic core services plus the coolant-pump profile.

---

## Phase 4 — Timeline and pre/post replacement analysis

**Goal:** make the replacement event analytically useful.

Implement configurable windows such as:

- PRE
- POST_SHORT
- POST_LONG

Derive features including:

- [ ] same_fault_before_after
- [ ] new_fault_after_replacement
- [ ] fault_disappeared_after_replacement
- [ ] time_to_recurrence
- [ ] distance_to_recurrence
- [ ] DTC frequency before / after replacement
- [ ] affected ECU count
- [ ] concurrent voltage / communication faults
- [ ] software changes around the event

**Exit criterion:** the system automatically describes what changed before and after replacement.

---

## Phase 5 — Evidence and root-cause engine

**Goal:** produce explainable engineering assessments rather than opaque labels.

Initial root-cause categories:

- component / supplier
- electrical supply
- wiring / connector
- controlling ECU / software
- surrounding vehicle system
- workshop / process
- unknown / insufficient evidence

Each rule should produce:

- supporting evidence
- contradicting evidence
- source references
- confidence / strength
- human-readable explanation

Supplier involvement must remain an **evidence-based assessment**, not an automatic conclusion from a single DTC or return status.

**Exit criterion:** every automated assessment can explain why it reached its result.

---

## Phase 6 — Similarity and clustering

**Goal:** discover recurring NTF patterns across vehicles.

Start with interpretable feature engineering:

- DTC sets and frequencies
- ECU participation
- voltage / communication indicators
- recurrence behaviour
- repair actions
- software state
- timing / mileage context
- structured findings from reports

Evaluate approaches such as:

- weighted similarity
- Jaccard / cosine distances
- HDBSCAN
- UMAP for visualization

Later evaluate text embeddings for workshop and supplier notes.

Important: supplier, batch and part identity should normally be analysed **after diagnostic clustering** to avoid trivial clusters.

**Exit criterion:** engineers can inspect coherent groups of diagnostically similar NTF cases and understand the features that connect them.

---

## Phase 7 — Supplier and population analysis

**Goal:** move from case-level evidence to statistically useful field patterns.

Analyse by:

- supplier
- part number
- batch / lot
- production period
- vehicle variant
- software version
- plant / market where appropriate

Where population data is available, calculate rates using meaningful denominators instead of comparing raw case counts only.

Examples:

- NTF cases per installed population
- recurrence rate after replacement
- supplier-related finding rate
- unresolved-case rate

**Exit criterion:** dashboards distinguish absolute counts from normalized field rates.

---

## Phase 8 — Web application

**Goal:** create a modern engineering interface.

Initial views:

- [ ] Overview
- [ ] Vehicle / FIN explorer
- [ ] Case timeline
- [ ] DTC explorer
- [ ] Root-cause evidence view
- [ ] Similar-case explorer
- [ ] Cluster explorer
- [ ] Supplier / population analytics
- [ ] Data-quality view

Recommended first-stack candidates:

- Streamlit for fastest engineering prototype
- Plotly for interactive visuals
- DuckDB + Parquet for local analytical storage

A later production architecture may move to FastAPI + PostgreSQL and a separate frontend if required.

**Exit criterion:** an engineer can go from a vehicle list to an explainable NTF case assessment without manually combining multiple spreadsheets.

---

## Phase 9 — Additional component families

**Goal:** prove that the architecture is genuinely reusable.

Candidate next profiles:

- [ ] HV battery
- [ ] other pumps / actuators
- [ ] sensors
- [ ] ECUs
- [ ] additional returned supplier components

Each new component should add profile-specific knowledge, not fork the analysis pipeline.

**Exit criterion:** a second substantially different component works without redesigning the core domain model.

---

## Cross-cutting workstreams

These apply throughout all phases.

### Data quality

Track missing and contradictory information explicitly. A missing value must not silently become a negative finding.

### Traceability

Every derived result should be traceable to its source record and parser / rule version.

### Testing

Use synthetic and anonymised fixtures. Add regression tests whenever a real engineering edge case is discovered.

### Security and confidentiality

Never commit real VINs, reports, credentials or confidential supplier material. Production connectors must support secure credential handling and controlled local / enterprise storage.

### Human-in-the-loop

The application should support expert confirmation, correction and annotation of automated findings. These decisions can later become high-quality labels for supervised models.

---

## Near-term milestone

The recommended first practical milestone is:

1. define the domain model,
2. create 10–20 synthetic or anonymised coolant-pump cases,
3. represent CPC3 DTCs and pump replacement events,
4. render a chronological case timeline,
5. detect same / new / disappeared faults after replacement,
6. only then connect the first real source system.

This gives a testable foundation before UI and ML complexity are introduced.
