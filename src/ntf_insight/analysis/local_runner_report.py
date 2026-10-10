"""Local-only aggregate report; no FIN/QEC/DTC/SSL identifiers are serialized.

The detailed cluster and cross-cluster statistics remain LOCAL by default.
Only a small hard-coded selection of INTEGER totals can optionally be printed
by an explicitly authorized workflow_dispatch input.
"""
from __future__ import annotations

from collections import Counter

from ntf_insight.analysis.case_clustering import _component_key
from ntf_insight.analysis.cluster_pilot_priority import (ClusterPilotPlan, prioritize_cluster_pilots)
from ntf_insight.analysis.cross_cluster_bridges import build_cluster_bridges
from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.diagnostic_gap_investigation import investigate_diagnostic_gaps
from ntf_insight.analysis.hdbscan_clustering import (
    cluster_hdbscan_cases,
    compare_hdbscan_methods,
)
from ntf_insight.analysis.pilot_expert_validation import validate_pilot_evidence
from ntf_insight.analysis.recurrence_coverage_audit import audit_recurrence_coverage
from ntf_insight.domain.case import NTFCase


def build_runner_local_analysis(
    cases: list[NTFCase],
    *,
    component: str = "coolant_pump",
    quicktests=None,
    autoexport=None,
) -> tuple[dict, ClusterPilotPlan]:
    """Calculate safe aggregate report AND confidential in-memory pilot plan.

    Returning the existing prioritized pilot plan avoids a second HDBSCAN
    calculation. The plan contains real case IDs and must NEVER enter the
    JSON report, GitHub Actions logs or CI artifacts.
    """
    scoped = [
        case for case in cases if _component_key(case) == component
    ]
    if not scoped:
        raise ValueError("Keine auswertbaren Fälle der Bauteilfamilie vorhanden.")
    audit = audit_diagnostic_evidence(
        scoped, dtc_source="all", lookback_days=None,
    )
    model = cluster_hdbscan_cases(
        scoped, selection_method="leaf", min_cluster_size=3,
        min_samples=2, dtc_source="all", lookback_days=None,
        common_dtc_cutoff=None,
    )
    methods = compare_hdbscan_methods(
        scoped, min_cluster_size=3, min_samples=2, dtc_source="all",
        lookback_days=None, common_dtc_cutoff=None,
    )
    gaps = investigate_diagnostic_gaps(
        scoped, audit, quicktests=quicktests, autoexport=autoexport,
    )
    coverage = audit_recurrence_coverage(scoped, quicktests=quicktests)
    bridges = build_cluster_bridges(scoped, model, audit)
    pilot = prioritize_cluster_pilots(
        scoped, model, audit, bridges=bridges,
    )
    expert = validate_pilot_evidence(scoped, model, ())
    if audit.scoped_cases != model.case_count:
        raise ValueError("Kohortengrößen sind inkonsistent.")
    if model.clustered_count + len(model.noise_case_ids) != len(model.eligible_case_ids):
        raise ValueError("Gruppen und HDBSCAN-Ausreißer sind nicht konsistent.")
    groups_by_name = {p.group: p for p in pilot.groups}
    group_rows = []
    for group in model.clusters:
        p = groups_by_name[f"H{group.cluster_id}"]
        group_rows.append({
            "gruppe": p.group,
            "faelle": group.case_count,
            "fahrzeuge": group.vehicle_count,
            "cpc3_kern_dtc_anzahl": p.cpc3_core_count,
            "gemeinsame_ecu_dtc_anzahl": len(group.common_faults),
            "median_interne_cosinus": group.median_internal_similarity,
            "p10_interne_cosinus": group.p10_internal_similarity,
            "schwache_fallpaare_unter_45_prozent": group.weak_pair_count,
            "alle_internen_fallpaare": group.internal_pair_count,
            "prioritaet": p.priority[:2],
            "unabhaengige_zielfin_kandidaten": p.independent_validation_candidates,
            "gezielte_pilotvergleiche": p.selected_comparison_cases,
            "diagnostische_brueckengruppen": list(p.bridge_neighbors),
        })
    group_rows.sort(key=lambda item: int(item["gruppe"][1:]))
    links = [{
        "cluster_a": link.left,
        "cluster_b": link.right,
        "gemeinsame_cpc3_kern_dtc_anzahl": len(link.shared_cpc3),
        "repraesentanten_cosinus": link.medoid_cosine,
        "median_grenzen_cosinus": link.between_median_cosine,
        "schwache_grenz_fallpaare": link.weak_between_pairs,
        "alle_grenz_fallpaare": link.between_pairs,
        "gleiche_fin_grenz_fallpaare": link.same_fin_between_pairs,
    } for link in bridges.links]

    report = {
        "format": "ntf-insight-lokale-aggregatanalyse",
        "version": 1,
        "ausgabe": "NUR_LOKAL_VERTRAULICH",
        "urspuengliche_fallkennungen_enthalten": False,
        "technische_original_dtc_enthalten": False,
        "ssl_freitexte_enthalten": False,
        "hinweis": (
            "Nur explorative Diagnosegruppen; kein unabhängiger Fehlerursachen-"
            "Nachweis, keine NTF-/Lieferantenhaftungsentscheidung. "
            "45%-Screening nicht kalibriert."
        ),
        "szenario": {
            "bauteilfamilie": component,
            "quellen": "QuickTest + AutoExport (QEC-zugeordnet)",
            "vor_tausch": "gesamte belegte Vorher-Historie",
            "hdbscan": "leaf",
            "mindestcluster": 3,
            "min_samples": 2,
            "dtc_haeufigkeitsfilter": False,
        },
        "summen": {
            "qec_faelle": model.case_count,
            "verschiedene_fahrzeuge": model.vehicle_count,
            "qec_mit_vor_tausch_diagnose": audit.eligible_cases,
            "qec_ohne_vor_tausch_diagnose": audit.excluded_count,
            "ml_geeignete_faelle": len(model.eligible_case_ids),
            "ml_cluster": len(model.clusters),
            "ml_clusterfaelle": model.clustered_count,
            "ml_ausreisser": len(model.noise_case_ids),
            "gruppen_ohne_schwache_interne_paare": sum(
                group.weak_pair_count == 0 for group in model.clusters
            ),
            "cluster_bruecken_cpc3": len(bridges.links),
            "repraesentanten_zur_pruefung": pilot.representative_count,
            "unabhaengige_pilotvergleiche_vorgeschlagen": pilot.independent_targets,
            "fachlich_bestaetigte_repraesentanten": expert.reviewed_representatives,
        },
        "datenqualitaet": {
            "qec_ohne_dtc": audit.without_any_dtc,
            "qec_nur_nach_tausch_oder_ohne_zeit": audit.only_after_swap_or_undated,
            "qec_ohne_tauschanker": audit.without_anchor,
            "ausgeschlossene_faelle_mit_fin_rohhinweis_vor_tausch": (
                gaps.with_raw_pre_hint
            ),
            "fin_rohhinweise_vorhanden": gaps.raw_available,
            "qec_vorher_dtc_ohne_vorher_sitzung": coverage.pre_dtc_but_no_pre_session,
            "qec_mit_vorher_sitzung": coverage.qec_with_before_session,
            "qec_mit_nachher_sitzung": coverage.qec_with_after_session,
            "rekurrenz_beurteilbar": coverage.assessable_qec,
            "fin_roh_quicktests_angebunden": coverage.raw_qt_available,
            "fin_roh_quicktests_vor_tausch_bei_faellen": (
                coverage.raw_qt_possible_before
            ),
            "fin_roh_quicktests_nach_tausch_bei_faellen": (
                coverage.raw_qt_possible_after
            ),
            "qec_vorgaenge_mehrfacher_fin": coverage.repeated_fin_cases,
        },
        "methodenvergleich": {
            "eom_gruppen": methods.eom.group_count,
            "eom_gruppierte_faelle": methods.eom.clustered_cases,
            "leaf_gruppen": methods.leaf.group_count,
            "leaf_gruppierte_faelle": methods.leaf.clustered_cases,
            "eom_leaf_paar_jaccard": methods.pair_coassignment_jaccard,
        },
        "cluster_nur_lokal": group_rows,
        "cpc3_bruecken_nur_lokal": links,
        "pilot_prioritaeten_nur_lokal": dict(
            sorted(Counter(group["prioritaet"] for group in group_rows).items())
        ),
    }
    return report, pilot


def build_runner_local_report(
    cases: list[NTFCase],
    *,
    component: str = "coolant_pump",
    quicktests=None,
    autoexport=None,
) -> dict:
    """Backward-compatible aggregate-only API; contains NO individual IDs."""
    report, _ = build_runner_local_analysis(
        cases, component=component,
        quicktests=quicktests, autoexport=autoexport,
    )
    return report


# These INTEGERS may appear in Actions logs ONLY after explicit manual
# authorisation. Never add free text, identifiers, per-cluster metrics or DTCs.
APPROVED_TOTAL_KEYS = (
    "qec_faelle",
    "qec_mit_vor_tausch_diagnose",
    "qec_ohne_vor_tausch_diagnose",
    "ml_cluster",
    "ml_clusterfaelle",
    "ml_ausreisser",
    "gruppen_ohne_schwache_interne_paare",
    "cluster_bruecken_cpc3",
    "repraesentanten_zur_pruefung",
    "unabhaengige_pilotvergleiche_vorgeschlagen",
)


def approved_public_totals(report: dict) -> dict[str, int]:
    """Strict numeric allowlist; no individual FIN, group or original DTC."""
    totals = report["summen"]
    result = {key: totals[key] for key in APPROVED_TOTAL_KEYS}
    if not all(type(value) is int and value >= 0 for value in result.values()):
        raise ValueError("Freigegebene Summen enthalten ungültige Werte.")
    return result
