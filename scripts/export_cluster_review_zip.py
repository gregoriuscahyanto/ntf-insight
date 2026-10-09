"""Einmaliger lokaler ZIP-Export ohne manuelle Falllisten.

Aufruf im Repository (mit installiertem ntf-insight):
    python scripts/export_cluster_review_zip.py

Die ZIP kann NUR nach interner Freigabe extern besprochen werden.
Die zwei *_NICHT_HOCHLADEN_*.csv bleiben immer lokal.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ntf_insight.analysis.case_clustering import _component_key
from ntf_insight.analysis.cluster_review_zip import write_cluster_review_zip
from ntf_insight.analysis.diagnostic_evidence_audit import audit_diagnostic_evidence
from ntf_insight.analysis.diagnostic_gap_investigation import investigate_diagnostic_gaps
from ntf_insight.analysis.hdbscan_clustering import (
    cluster_hdbscan_cases, compare_hdbscan_methods,
)
from ntf_insight.analysis.mechanism_review import read_confirmed_mechanisms
from ntf_insight.analysis.recurrence_coverage_audit import audit_recurrence_coverage
from ntf_insight.app.settings import AppPaths
from ntf_insight.storage.duckdb_store import DuckDBStore
from ntf_insight.storage.quicktest_store import QuickTestStore
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt lokal eine pseudonymisierte HDBSCAN-Analyse-ZIP "
            "und zwei getrennte NICHT-HOCHLADEN-Zuordnungstabellen."
        ),
    )
    parser.add_argument(
        "--ausgabe", type=Path,
        default=Path("NTF_Cluster_Pruefpaket_ohne_FIN.zip"),
        help="Lokale ZIP-Zieldatei (Standard im aktuellen Verzeichnis).",
    )
    parser.add_argument(
        "--datenbank", type=Path,
        default=AppPaths.default().database_path,
        help="Pfad zur vorhandenen lokalen NTF-Insight-DuckDB-Datenbank.",
    )
    parser.add_argument(
        "--bauteil", default="coolant_pump",
        help="Interne Bauteilfamilie (Standard coolant_pump).",
    )
    parser.add_argument("--mindestcluster", type=int, default=3)
    parser.add_argument("--min-samples", type=int, default=2)
    parser.add_argument(
        "--methode", choices=("leaf", "eom"), default="leaf",
    )
    parser.add_argument(
        "--quelle", choices=("all", "quicktest", "autoexport"),
        default="all",
    )
    parser.add_argument(
        "--vorher-tage", type=int, default=None,
        help="Optionales Zeitfenster vor Tausch; Standard gesamte Vorher-Historie.",
    )
    parser.add_argument(
        "--haeufigkeitsfilter", action="store_true",
        help="Experimentellen 35%%-DTC-Häufigkeitsfilter einschalten.",
    )
    parser.add_argument(
        "--vergleich", action="store_true",
        help="Zusätzlich EOM/Leaf auf der gleichen ML-Datenbasis vergleichen.",
    )
    parser.add_argument(
        "--fachpruefung", type=Path,
        help="Optional: lokal geprüfte Mechanismus-CSV aus NTF Insight einlesen.",
    )
    options = parser.parse_args(argv)
    source = options.datenbank.expanduser()
    if not source.is_file():
        parser.error(
            "Lokale Datenbank nicht gefunden: bitte NTF Insight zuerst "
            "mit QEC/QuickTest/AutoExport-Daten befüllen oder --datenbank setzen."
        )
    try:
        db = DuckDBStore(source)
        cases = [
            case for case in db.load_cases()
            if _component_key(case) == options.bauteil.casefold().strip()
        ]
        if not cases:
            parser.error("Keine QEC-Fälle für die gewünschte Bauteilfamilie vorhanden.")
        confirmations = ()
        if options.fachpruefung:
            with options.fachpruefung.expanduser().open(
                encoding="utf-8-sig", newline=""
            ) as stream:
                confirmations = read_confirmed_mechanisms(stream, cases)
        audit = audit_diagnostic_evidence(
            cases, dtc_source=options.quelle,
            lookback_days=options.vorher_tage,
        )
        result = cluster_hdbscan_cases(
            cases, selection_method=options.methode,
            min_cluster_size=options.mindestcluster,
            min_samples=options.min_samples,
            dtc_source=options.quelle,
            lookback_days=options.vorher_tage,
            common_dtc_cutoff=0.35 if options.haeufigkeitsfilter else None,
        )
        raw_quicktests = QuickTestStore(db)
        gaps = investigate_diagnostic_gaps(
            cases, audit,
            quicktests=raw_quicktests,
            autoexport=SourceKnowledgeStore(db),
        )
        session_coverage = audit_recurrence_coverage(
            cases, quicktests=raw_quicktests,
        )
        comparison = None
        if options.vergleich:
            comparison = compare_hdbscan_methods(
                cases,
                min_cluster_size=options.mindestcluster,
                min_samples=options.min_samples,
                common_dtc_cutoff=0.35 if options.haeufigkeitsfilter else None,
                lookback_days=options.vorher_tage,
                dtc_source=options.quelle,
            )
        exported = write_cluster_review_zip(
            options.ausgabe, cases, result, audit,
            confirmations=confirmations, gaps=gaps, comparison=comparison,
            recurrence_coverage=session_coverage,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"ZIP erstellt: {exported.zip_path.resolve()} "
        f"({exported.cluster_count} Cluster, "
        f"{exported.representative_count} Repräsentanten, "
        f"{exported.case_count} QEC-Fälle)."
    )
    print(
        "Private Fallzuordnung – NICHT HOCHLADEN: "
        f"{exported.private_case_map.resolve()}"
    )
    print(
        "Private DTC-Zuordnung – NICHT HOCHLADEN: "
        f"{exported.private_dtc_map.resolve()}"
    )
    print(
        "Nur die ZIP nach interner Freigabe teilen. "
        "Sie enthält Prüfhypothesen, keine nachgewiesenen Cluster-Ursachen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
