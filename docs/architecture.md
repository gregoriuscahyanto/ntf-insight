# Architecture

NTF Insight separates generic NTF analytics from component-specific engineering knowledge. The primary user interface is a native **PySide6 / Qt desktop application**; the analysis core must remain independent from Qt.

## Layers

1. **Acquisition** — provider contracts for API/browser-based report retrieval by FIN.\n2. **Ingestion** — immutable raw archive, provenance, adapters, parsers and case assembly.
2. **Domain** — generic vehicle, case, event, evidence and assessment models.
3. **Storage** — persistence abstractions for raw metadata and normalized data.
4. **Analysis** — timeline reconstruction, recurrence, feature extraction, evidence rules and clustering.
5. **Components** — coolant-pump, HV-battery and future component-specific profiles.
7. **Desktop app** — PySide6 pages, widgets and Qt models for engineering workflows and visualisation.

A component profile should extend the generic pipeline through configuration and dedicated rules rather than duplicating the pipeline.

## Dependency direction

```text
PySide6 desktop app
        |
        v
application services
        |
        v
domain + analysis
        |
        v
storage / ingestion

component profiles --> domain + analysis
```

The domain and analysis layers must not import from the GUI package. This keeps the project testable and allows a CLI, API or alternative frontend to be added later.

## Desktop structure

```text
app/
├── application.py
├── styles.py
├── windows/
│   └── main_window.py
├── pages/
│   ├── dashboard_page.py
│   ├── vehicles_page.py
│   └── generic_page.py
├── widgets/
│   ├── navigation.py
│   └── status_card.py
└── models/
    └── vehicle_table_model.py
```

Qt's Model/View architecture should be preferred for large vehicle, DTC and case tables instead of embedding data directly in widgets.

## Engineering reference knowledge

NTF Insight keeps two different kinds of data separate:

- **Vehicle/case events** describe what happened on a specific FIN/VIN: short tests, DTC observations, replacements, workshop actions and actual software states.
- **Engineering reference knowledge** describes how the system is designed: DTC trigger definitions from SMR-D sources and documented HW/SW/calibration changes between ECU releases.

This separation is important for causal reasoning. A release note that changes a DTC monitor does not prove that a specific vehicle had that software; the vehicle timeline must still provide the actual software state. Likewise, a DTC trigger definition explains the monitor logic but does not by itself prove the physical root cause.

Conceptually:

```text
SMR-D trigger definitions ─────────┐
                                  ├──> evidence / root-cause analysis
HW/SW change catalog ─────────────┤
                                  │
vehicle short tests + SW state ───┤
replacement / workshop events ────┘
```


## Local persistence

The desktop prototype uses a local DuckDB database outside the repository. Canonical Pydantic objects are currently stored as JSON snapshots with indexed identity columns, allowing lossless round-trips while the real source schemas are still unknown. Analytical/materialized tables can be added later without changing the domain API.

Original source files are archived separately in a content-addressed raw archive using SHA-256. The database stores provenance metadata; raw source bytes are never committed to Git.

The default location is `~/.ntf-insight`, configurable with `NTF_INSIGHT_DATA_DIR`.

## Case assembly

Parsers do not mutate the UI directly. They emit canonical records, which are assembled into cases. A FIN that maps to multiple cases is treated as ambiguous unless an explicit case ID is supplied. The system records an import error instead of guessing.

## Acquisition boundary

Automated report download is represented by a `ReportProvider` interface plus batch orchestration. Concrete provider implementations are deferred until the actual target systems, authentication constraints and report formats are known. Downloaded files flow immediately into the immutable raw archive before parsing.
