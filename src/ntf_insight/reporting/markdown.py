"""Deterministic Markdown case report."""

from __future__ import annotations

from pathlib import Path

from ntf_insight.analysis.case_analysis import CaseAnalysis, analyze_case
from ntf_insight.analysis.recurrence import format_faults
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.reference_repositories import ReferenceRepository


def render_case_report(
    case: NTFCase,
    references: ReferenceRepository | None = None,
) -> str:
    analysis = analyze_case(case, references)
    recurrence = analysis.recurrence
    replacement = recurrence.replacement

    lines = [
        f"# NTF Insight Case Report — {case.case_id}",
        "",
        "> Generated from normalized source data. Automated evidence is a diagnostic aid, not a final causal verdict.",
        "",
        "## Case",
        "",
        f"- FIN / VIN: {case.vin}",
        f"- Component: {case.component_type}",
        f"- Component profile: {case.component_profile_id or '—'}",
        f"- Replacement: {replacement.occurred_at.isoformat(sep=' ') if replacement else '—'}",
        f"- Replacement mileage: {replacement.mileage_km if replacement and replacement.mileage_km is not None else '—'}",
        "",
        "## Current assessment",
        "",
    ]

    if case.assessment is None:
        lines.append("- No confirmed/manual assessment is stored.")
    else:
        lines.extend(
            [
                f"- Root cause: {case.assessment.root_cause}",
                f"- Supplier involvement: {case.assessment.supplier_involvement}",
                f"- Confidence: {case.assessment.confidence}",
                f"- Summary: {case.assessment.summary or '—'}",
            ]
        )

    lines.extend(["", "## Pre/post replacement analysis", ""])
    if not recurrence.assessable:
        lines.append("- Recurrence: insufficient data")
    else:
        lines.extend(
            [
                f"- Same faults: {format_faults(recurrence.same_faults)}",
                f"- Disappeared faults: {format_faults(recurrence.disappeared_faults)}",
                f"- New faults: {format_faults(recurrence.new_faults)}",
                f"- First recurrence after: {recurrence.first_recurrence_after or '—'}",
                f"- Distance to recurrence: {recurrence.distance_to_recurrence_km if recurrence.distance_to_recurrence_km is not None else '—'}",
            ]
        )

    lines.extend(["", "## Generated evidence", ""])
    if not analysis.evidence.evidence:
        lines.append("- No generic evidence generated.")
    else:
        for item in analysis.evidence.evidence:
            lines.append(
                f"- **{item.code}** — {item.direction}; category: "
                f"{item.category_hint or '—'}; provisional weight: {item.weight:.2f}. "
                f"{item.description}"
            )

    balances = analysis.evidence.balance_by_category()
    if balances:
        lines.extend(["", "### Provisional evidence balance", ""])
        for category, score in sorted(
            balances.items(), key=lambda item: abs(item[1]), reverse=True
        ):
            lines.append(f"- {category}: {score:+.2f}")

    lines.extend(["", "## Data quality", ""])
    for check in analysis.quality.checks:
        lines.append(f"- **{check.label}** — {check.status}: {check.detail}")

    lines.extend(["", "## Timeline", "", "| Time | km | Type | Event | Details | Source |", "| --- | ---: | --- | --- | --- | --- |"])
    for entry in analysis.timeline:
        detail = entry.detail.replace("|", "\\|") if entry.detail else "—"
        title = entry.title.replace("|", "\\|")
        source = (entry.source_ref or "—").replace("|", "\\|")
        lines.append(
            f"| {entry.occurred_at.isoformat(sep=' ', timespec='minutes')} | "
            f"{entry.mileage_km if entry.mileage_km is not None else '—'} | "
            f"{entry.kind} | {title} | {detail} | {source} |"
        )

    lines.extend(["", "## Feature snapshot", ""])
    for key, value in analysis.features.as_dict().items():
        lines.append(f"- {key}: {value}")

    return "\n".join(lines) + "\n"


def save_case_report(
    path: Path,
    case: NTFCase,
    references: ReferenceRepository | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_case_report(case, references), encoding="utf-8")
    return path
