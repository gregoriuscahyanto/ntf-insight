"""QEC SSL end finding for post-cluster interpretation, never a similarity feature."""

from __future__ import annotations

from dataclasses import dataclass

from ntf_insight.domain.case import NTFCase


@dataclass(frozen=True, slots=True)
class QECFinding:
    text: str
    date_label: str | None
    source_ref: str | None


def qec_ssl_finding(case: NTFCase) -> QECFinding | None:
    """Prefer the original QEC column, including undated findings.

    A supplier-finding event exists only when the QEC supplied an actual
    finding date. Historical cases without the extra field can still use a
    QEC-sourced finding event for display.
    """
    text = getattr(case, "qec_ssl_end_finding", None)
    if isinstance(text, str) and text.strip():
        value = getattr(case, "qec_ssl_end_date", None)
        return QECFinding(
            text=text.strip(),
            date_label=str(value) if value else None,
            source_ref=getattr(case, "source_ref", None),
        )
    for finding in case.supplier_findings:
        if (
            "Schadteile QEC" in (finding.source_ref or "")
            and finding.failure_mode
        ):
            return QECFinding(
                text=finding.failure_mode,
                date_label=finding.occurred_at.date().isoformat(),
                source_ref=finding.source_ref,
            )
    return None


def qec_ssl_finding_label(case: NTFCase) -> str:
    finding = qec_ssl_finding(case)
    if finding is None:
        return "Kein QEC-SSL-Endbefund dokumentiert"
    when = finding.date_label or "Befundabschlussdatum unbekannt"
    return f"{finding.text} · {when} (QEC-Befund, keine bestätigte Ursache)"
