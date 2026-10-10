"""Datensparsame, ausschließlich lokale Clusterzahlen für die Zusammenarbeit.

Liest die BESTEHENDE NTF-DuckDB read_only=True und berechnet das bisherige
explorative Kühlmittelpumpen-Szenario neu. Es werden KEINE Original-FINs,
QEC-Fall-IDs, ECU-/DTC-Schlüssel, SSL-Freitexte, lokalen Verzeichnisse oder
Einzelfalldateien ausgegeben, gespeichert, hochgeladen oder ins Git geschrieben.

STANDARD: nur die zehn zuvor autorisierbaren Aggregatsummen und die bereits
separat freigebbaren methodischen Aggregatzahlen.
K1: separat, nur mit --k1-zahlen-nach-freigabe; die kleinen Gruppenzahlen
können trotz entfernter Kennungen intern vertraulich sein.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parent.parent


def _existing_local_database(provided: Path | None) -> Path:
    from ntf_insight.app.settings import AppPaths

    database = (
        provided if provided is not None
        else Path(
            os.environ.get("NTF_INSIGHT_RUNNER_DB")
            or AppPaths.default().database_path
        )
    ).expanduser().resolve()
    root = REPOSITORY.resolve()
    if database == root or root in database.parents:
        raise ValueError("Vertrauliche Datenbank im Git-Repository unzulässig.")
    if not database.is_file():
        raise FileNotFoundError("Die bestehende lokale DuckDB wurde nicht gefunden.")
    return database


def _numbers_only_k1(
    scoped, totals: dict, methods: dict,
) -> dict[str, int | bool]:
    """Recalculate K1 with GUI defaults; serialize ZERO source identifiers."""
    from ntf_insight.analysis.cluster_core_review import link_core_review_groups
    from ntf_insight.analysis.cluster_workspace_engine import (
        ClusterParameters, calculate_clusters,
    )
    from ntf_insight.analysis.hdbscan_clustering import cluster_hdbscan_cases

    base = cluster_hdbscan_cases(
        scoped, selection_method="leaf", min_cluster_size=3, min_samples=2,
        dtc_source="all", lookback_days=None, common_dtc_cutoff=None,
    )
    leaf = calculate_clusters(
        scoped, ClusterParameters(method="leaf"), reference=base,
    )
    strict = calculate_clusters(
        scoped, ClusterParameters(method="complete_cosine",
                                 minimum_similarity=0.45),
        reference=base, projection=leaf.positions,
    )
    if (
        len(leaf.groups) != totals["ml_cluster"]
        or len(strict.groups) != methods["methode_complete_link_45"]["cluster"]
        or strict.clustered_count
        != methods["methode_complete_link_45"]["clusterfaelle"]
    ):
        raise ValueError("Kernprüfgruppen stimmen nicht mit den Summen überein.")

    links = link_core_review_groups(leaf, strict)
    if not links:
        return {"k1_vorhanden": False}
    first = links[0]
    group = first.core
    if group.minimum_pair_similarity is None:
        raise ValueError("K1 ohne Mindest-Paarähnlichkeit.")
    return {
        "k1_vorhanden": True,
        "qec_faelle": group.case_count,
        "unterschiedliche_fin": group.vehicle_count,
        "gemeinsame_ecu_dtc_anzahl": len(group.common_faults),
        "davon_gemeinsame_cpc3_dtc": sum(
            str(ecu).upper() == "CPC3" for ecu, _ in group.common_faults
        ),
        "min_paar_cosinus_promille": int(
            round(group.minimum_pair_similarity * 1000)
        ),
        "vollstaendig_innerhalb_eines_leaf_clusters": first.fully_contained,
        "ueberlappende_leaf_cluster_anzahl": len(first.active_group_ids),
        "faelle_im_stark_ueberlappenden_leaf_cluster": first.dominant_overlap,
    }


def calculate_shareable_results(
    database: Path | None = None,
    *,
    approve_k1: bool = False,
) -> tuple[dict, dict, dict | None]:
    """Compute an EXPLICIT, closed schema. No case-level records are returned."""
    from ntf_insight.analysis.case_clustering import _component_key
    from ntf_insight.analysis.local_runner_report import (
        approved_public_totals, build_runner_local_report,
    )
    from ntf_insight.analysis.method_comparison_audit import (
        approved_method_totals,
    )
    from ntf_insight.storage.readonly_case_store import ReadOnlyCaseStore

    store = ReadOnlyCaseStore(_existing_local_database(database))
    if "case_snapshots" not in store.tables():
        raise ValueError("Bestehende QEC-Tabelle nicht gefunden.")
    scoped = [
        case for case in store.load_cases()
        if _component_key(case) == "coolant_pump"
    ]
    if not scoped:
        raise ValueError("Keine Kühlmittelpumpen-Fälle verfügbar.")

    # This local report itself may contain sensitive per-group statistics.
    # It stays exclusively in memory; only two pre-reviewed white lists
    # below are permitted onto stdout.
    report = build_runner_local_report(scoped, component="coolant_pump")
    sums = approved_public_totals(report)
    methods = approved_method_totals(report)
    if (
        sums["qec_faelle"] != len(scoped)
        or sums["qec_mit_vor_tausch_diagnose"]
        + sums["qec_ohne_vor_tausch_diagnose"] != len(scoped)
        or methods["geeignete_faelle"]
        != sums["qec_mit_vor_tausch_diagnose"]
    ):
        raise ValueError("Ausgewiesene Analysesummen sind inkonsistent.")
    k1 = _numbers_only_k1(scoped, sums, methods) if approve_k1 else None
    return sums, methods, k1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lokal und read-only: nur explizit zugelassene "
            "Clusterzahlen für das Gespräch anzeigen."
        )
    )
    parser.add_argument(
        "--datenbank", type=Path, default=None,
        help="Optionaler LOKALER DuckDB-Pfad, wird niemals ausgegeben.",
    )
    parser.add_argument(
        "--k1-zahlen-nach-freigabe", action="store_true",
        help=(
            "Zusätzliche vertrauliche kleine K1-Aggregate nur nach "
            "interner Berechtigung anzeigen; KEINE FIN-/DTC-Schlüssel."
        ),
    )
    args = parser.parse_args(argv)
    try:
        # Third-party warnings may contain paths or original ECU data;
        # never leak arbitrary exceptions or library messages via the console.
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                totals, methods, k1 = calculate_shareable_results(
                    args.datenbank, approve_k1=args.k1_zahlen_nach_freigabe,
                )
    except Exception:
        print(
            "NTF_CLUSTER_STATUS_FEHLER: Kein Fallinhalt ausgegeben. "
            "Bitte GUI schließen, lokale DuckDB/venv/Abhängigkeiten prüfen.",
            file=sys.stderr,
        )
        return 2

    print(
        "NTF_FREIGEGEBENE_SUMMEN_JSON="
        + json.dumps(totals, ensure_ascii=True, sort_keys=True)
    )
    print(
        "NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON="
        + json.dumps(methods, ensure_ascii=True, sort_keys=True)
    )
    if k1 is not None:
        # Only when the human has separately approved the small-group totals.
        print(
            "NTF_K1_NUMERISCHE_DETAILS_NACH_FREIGABE_JSON="
            + json.dumps(k1, ensure_ascii=True, sort_keys=True)
        )
    print("NTF_CLUSTER_STATUS_OK_NUR_LOKAL_READ_ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
