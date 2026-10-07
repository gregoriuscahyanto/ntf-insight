# Data requirements

NTF Insight reconstructs a field case around a component replacement. The minimum useful dataset therefore needs more than a DTC list: it needs a vehicle identifier, the diagnostic events, the replacement anchor and the finding on the returned component.

## Minimum viable dataset

### 1. Case / vehicle list

One row per investigated case, ideally including:

- FIN / VIN or a stable anonymised case ID
- component family
- vehicle variant / model series
- case or claim identifier
- customer complaint date if available

This is the master list used to join all other sources.

### 2. Short-test / diagnostic results

This is the first parser target.

Prefer the **complete vehicle short test across all ECUs**, not only the controlling ECU. For each DTC, preserve as much source information as possible:

- FIN / VIN
- test timestamp
- mileage
- ECU name / address
- DTC code
- DTC text / engineering data
- status (current, stored, intermittent, etc.)
- occurrence counter
- environmental / freeze-frame data when available
- software / hardware state when contained in the export

For the coolant-pump use case, CPC3 is especially relevant, but cross-ECU DTCs are important for detecting supply, communication or system-level problems.

**Do not discard a short test just because it contains zero relevant DTCs.** NTF Insight stores the diagnostic session itself separately from its DTC entries. This lets the analysis distinguish a known post-replacement test with no matching fault from a case where no post-replacement diagnostic data exists at all.

### 3. Component replacement event

This is the analytical anchor for pre/post comparison and is **required** for recurrence analysis.

Needed fields:

- FIN / VIN
- replacement date/time
- mileage at replacement
- component type
- old part number
- new part number
- supplier when known
- serial / batch / lot when available

Without the replacement date or mileage, the system cannot reliably decide which DTCs occurred before or after the replacement.

### 4. Return / supplier finding

Needed to understand why a case became NTF and to assess supplier involvement:

- finding date
- final finding: NTF / fault found / other
- reproduced customer complaint: yes / no / unknown
- failure mode
- test steps or test result summary
- responsible party / cause if formally documented
- supplier statement

The application should keep the original wording and source reference; it should not convert a supplier statement directly into a causal truth.

## Strongly recommended data

### 5. Workshop / claim history

Useful fields:

- customer complaint / symptom text
- workshop diagnosis
- repair actions
- replaced or checked surrounding components
- wiring / connector work
- TIPS / support case reference and dates
- diagnostic instructions that were executed

This is important for distinguishing a genuine component failure from a diagnosis or process problem.

### 6. ECU software and configuration history

Especially for the ECU that monitors or controls the component:

- software version
- hardware version
- coding / parameterisation state
- flash date
- relevant service measure or software campaign

This allows the analysis to test whether a fault pattern correlates with software state or disappears after a software change.

### 7. Component / supplier master data

For supplier and field-pattern analysis:

- part number and revision
- supplier
- manufacturing date
- batch / lot
- plant / production line when permitted

## Later, for statistically valid supplier comparisons

### 8. Installed population / denominator data

Raw NTF counts are not enough to compare suppliers or part variants. Ideally obtain installed population by:

- supplier
- part number / revision
- production period
- vehicle variant

This enables rates such as NTF cases per installed population instead of misleading absolute counts.

## Recommended first input package

To build the first real coolant-pump pipeline, provide an anonymised package containing:

1. 1–3 representative short-test files in their original export format,
2. a small table with FIN / case ID and pump replacement date + mileage,
3. if available, the corresponding return / supplier finding for those same cases,
4. optionally the workshop complaint / repair text for those cases.

From these files we can define the parser schema before scaling to hundreds of vehicles.

## Processing order

The initial pipeline should be built in this order:

1. parse short-test files into canonical diagnostic events,
2. import replacement events,
3. join both by FIN / case ID,
4. build the chronological vehicle timeline,
5. calculate pre/post replacement recurrence features,
6. add workshop and supplier findings as evidence,
7. implement explainable root-cause rules,
8. add similarity / clustering,
9. add population-normalised supplier analytics.
