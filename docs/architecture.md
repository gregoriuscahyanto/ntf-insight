# Architecture

NTF Insight separates generic NTF analytics from component-specific engineering knowledge.

## Layers

1. **Ingestion** — adapters and parsers for external source systems.
2. **Domain** — generic vehicle, case, event, evidence and assessment models.
3. **Storage** — persistence abstractions for raw metadata and normalized data.
4. **Analysis** — timeline reconstruction, recurrence, feature extraction, evidence rules and clustering.
5. **Components** — coolant-pump, HV-battery and future component-specific profiles.
6. **App** — user-facing engineering workflows and visualisation.

A component profile should extend the generic pipeline through configuration and dedicated rules rather than duplicating the pipeline.
