# Canonical source contracts

NTF Insight deliberately separates **source formats** from the **canonical domain model**.

A CSV, XLSX, PDF export, XML file, SMR-D package or proprietary report may look completely different, but each parser must emit the same normalized objects. The concrete mappings below remain provisional until representative original files are available.

## Linking strategy

Preferred linkage hierarchy:

1. FIN / VIN
2. explicit case / claim ID where available
3. diagnostic session / report identifier
4. timestamp + mileage as supporting temporal linkage
5. part identifiers and replacement IDs for component-level linkage

Never silently join records only because text or dates look similar. Ambiguous joins should become data-quality issues.

## Vehicle / case list

Canonical output: `Vehicle` plus case metadata.

Minimum useful fields:

- FIN / VIN
- component family
- case / claim ID where available

Useful additions:

- vehicle series / variant
- production date
- market
- complaint date

## Short test / diagnostic export

Canonical output:

- one `DiagnosticSession` per known test run, even if zero relevant DTCs are present
- zero or more `DiagnosticEvent` records
- zero or more `ECUStateObservation` records

Important fields:

- FIN / VIN
- test timestamp
- mileage
- ECU
- DTC code and text
- status / occurrence data
- freeze-frame / environmental values
- observed ECU HW/SW/coding state
- source reference

The full vehicle short test should be retained whenever possible. Restricting input to CPC3 too early would hide multi-ECU supply, communication or system-level evidence.

## Component replacement data

Canonical output: `PartReplacement`.

Important fields:

- FIN / VIN
- replacement timestamp/date
- mileage
- component type
- old/new part number
- supplier
- serial/batch/lot where available
- source reference

The replacement event is the anchor for pre/post analysis.

## Supplier / returned-part findings

Canonical output: `SupplierFinding`.

Important fields:

- FIN / VIN or replacement/case linkage
- finding date
- NTF / fault found / other
- complaint reproduced: yes/no/unknown
- failure mode
- test-result summary
- supplier
- source reference

Supplier statements remain evidence. They are not converted directly into a causal truth.

## Workshop / claim history

Canonical output: `RepairEvent`.

Useful fields:

- FIN / VIN
- timestamp/date
- mileage
- customer complaint
- workshop diagnosis
- action performed
- wiring/connector checks
- surrounding parts repaired/replaced
- support/TIPS reference
- source reference

## SMR-D / DTC trigger definitions

Canonical output: one or more `DTCTriggerDefinition` records per ECU/DTC.

Multiple definitions for the same DTC are supported because monitor logic may differ by software, hardware, coding or vehicle variant.

Parse where available:

- ECU
- DTC code/text
- set/trigger condition
- enable conditions
- debounce/counter/time logic
- healing/reset conditions
- applicability / variant
- HW/SW scope
- semantic tags derived by controlled engineering mapping
- exact source/version reference

Semantic tags such as `supply_voltage` are normalized engineering annotations used by generic rules. They must be explainable and traceable, not guessed from the DTC code alone.

## HW/SW/calibration change history

Canonical output: `ECUChangeRecord`.

Useful fields:

- ECU
- change type
- from/to version
- effective/release date
- title
- detailed change description
- affected DTCs/monitors
- affected functions/components
- source reference

A release note does **not** prove that a specific vehicle had that software.

## Vehicle-specific software history

Canonical output:

- `SoftwareEvent` for flash/update/change events
- `ECUStateObservation` for an observed HW/SW state at a known point in time

This is what connects release knowledge to a specific FIN.

## Installed population / exposure

Canonical output: `PopulationExposure`.

Useful dimensions:

- component family
- supplier
- part number/revision
- production period
- vehicle variant
- plant/market where permitted
- installed units
- source reference

Rates are calculated only when a valid denominator exists. Raw NTF case counts are never presented as supplier failure rates.

## Provenance requirements

Every original source file should be archived before parsing.

NTF Insight already supports:

- SHA-256 hashing
- immutable content-addressed raw archive
- original filename
- source type
- file size
- import timestamp
- parser name/version
- DuckDB registration

Derived records should retain `source_ref` values that point back to their original artifact or record.

## Missing-data rule

Missing data is an explicit state.

Examples:

- no post-replacement short test != post-test with zero matching DTCs
- no supplier finding != supplier finding NTF
- no HW/SW history != no software update
- no trigger definition != DTC has no trigger conditions

This rule is enforced throughout recurrence and data-quality analysis.

## Parser implementation order once files are available

1. short-test parser
2. replacement-list parser
3. SMR-D trigger parser
4. HW/SW change-history parser
5. vehicle HW/SW state extraction
6. supplier finding parser
7. workshop/claim parser
8. installed-population parser

Each parser should be regression-tested against anonymized fixtures derived from real source structures.
