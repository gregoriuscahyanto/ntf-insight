# Architecture

NTF Insight separates generic NTF analytics from component-specific engineering knowledge. The primary user interface is a native **PySide6 / Qt desktop application**; the analysis core must remain independent from Qt.

## Layers

1. **Ingestion** — adapters and parsers for external source systems.
2. **Domain** — generic vehicle, case, event, evidence and assessment models.
3. **Storage** — persistence abstractions for raw metadata and normalized data.
4. **Analysis** — timeline reconstruction, recurrence, feature extraction, evidence rules and clustering.
5. **Components** — coolant-pump, HV-battery and future component-specific profiles.
6. **Desktop app** — PySide6 pages, widgets and Qt models for engineering workflows and visualisation.

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
