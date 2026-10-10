"""Self-hosted, manual, read-only NTF pump analysis with local-only output.

The default workflow prints only a static completion marker. It cannot read
from arbitrary paths supplied through GitHub workflow inputs. DB and report
locations are configured *locally* on the runner, not in GitHub.
"""
from __future__ import annotations

import argparse
import json
import os
from contextlib import redirect_stderr, redirect_stdout
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _local_paths(database: Path | None, output_dir: Path | None) -> tuple[Path, Path]:
    # Delay project/ML imports until stdout/stderr is isolated by main().
    from ntf_insight.app.settings import AppPaths

    source = (
        database
        if database is not None
        else Path(os.environ.get("NTF_INSIGHT_RUNNER_DB") or AppPaths.default().database_path)
    )
    output = (
        output_dir
        if output_dir is not None
        else Path(os.environ.get("NTF_INSIGHT_RUNNER_REPORT_DIR")
                  or (AppPaths.default().data_dir / "runner-analysen"))
    )
    db = source.expanduser().resolve()
    directory = output.expanduser().resolve()
    repository = ROOT.resolve()
    # Never place confidential analysis outputs in any git worktree path.
    if repository == directory or repository in directory.parents:
        raise ValueError("Ausgabeordner muss außerhalb des Repositories liegen.")
    if repository == db or repository in db.parents:
        raise ValueError("Lokale Originaldatenbank darf nicht im Repository liegen.")
    if db == directory or db in directory.parents:
        raise ValueError("Ausgabeordner darf nicht innerhalb der Datenbank liegen.")
    return db, directory


def run_local_analysis(
    *,
    database: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Read from an existing DB with DuckDB read_only=True. Write local JSON."""
    from ntf_insight.analysis.local_runner_report import build_runner_local_analysis
    from ntf_insight.analysis.pilot_expert_validation import write_pilot_review_template
    from ntf_insight.storage.quicktest_store import QuickTestStore
    from ntf_insight.storage.readonly_case_store import ReadOnlyCaseStore
    from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore

    db_path, target = _local_paths(database, output_dir)
    store = ReadOnlyCaseStore(db_path)
    available_tables = store.tables()
    if "case_snapshots" not in available_tables:
        raise ValueError("Die lokale Datenbank enthält keine QEC-Fall-Snapshots.")
    qt = (
        QuickTestStore(store, initialize=False)
        if {"quicktest_reports", "quicktest_dtcs"}.issubset(available_tables)
        else None
    )
    auto = (
        SourceKnowledgeStore(store, initialize=False)
        if "source_knowledge_rows" in available_tables
        else None
    )
    cases = store.load_cases()
    report, plan = build_runner_local_analysis(
        cases, quicktests=qt, autoexport=auto,
    )
    if len(plan.inspections) != plan.representative_count + plan.independent_targets:
        raise ValueError("Pilotprüfplan widersprüchlich: QEC-CSV wird nicht geschrieben.")
    target.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # No personal identifiers or source paths in the output directory name.
    folder = target / f"NTF_Lauf_{stamp}_{secrets.token_hex(4)}"
    folder.mkdir(mode=0o700)
    payload = (json.dumps(
        report, ensure_ascii=False, sort_keys=True, indent=2,
    ) + "\n").encode("utf-8")
    (folder / "lokale_aggregatanalyse_NICHT_AUTOMATISCH_HOCHLADEN.json").write_bytes(
        payload
    )
    # This existing, reviewed GUI import format contains REAL QEC IDs, FINs,
    # and possibly SSL findings. Never copy it into GitHub workspace, stdout,
    # stderr, CI artifacts or the aggregate JSON above. The output directory
    # is a preconfigured local-only path protected by Windows ACLs.
    private_file = folder / "pilot_fachpruefung_FIN_SSL_NICHT_HOCHLADEN.csv"
    with private_file.open("w", encoding="utf-8-sig", newline="") as destination:
        write_pilot_review_template(destination, cases, plan)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Nur lokal: read-only Analyse der vorhandenen Kühlmittelpumpen."
    )
    parser.add_argument("--datenbank", type=Path, default=None)
    parser.add_argument("--ausgabeordner", type=Path, default=None)
    parser.add_argument(
        "--freigabe-summen", action="store_true",
        help="Nur explizit erlaubte aggregierte Ganzzahlen in Actions-Logs ausgeben.",
    )
    parser.add_argument(
        "--methodenvergleich-freigeben", action="store_true",
        help="Separater Opt-in: ausschließlich vier aggregierte Methodenstatistiken.",
    )
    args = parser.parse_args(argv)
    try:
        # 3rd party libraries (e.g. sklearn/HDBSCAN) may emit FutureWarnings
        # with internal runtime paths or data details to stderr. The runner
        # must not relay arbitrary analysis output into GitHub Actions.
        with open(os.devnull, "w", encoding="utf-8") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                report = run_local_analysis(
                    database=args.datenbank, output_dir=args.ausgabeordner,
                )
                if args.freigabe_summen:
                    from ntf_insight.analysis.local_runner_report import (
                        approved_public_totals,
                    )
                    permitted = approved_public_totals(report)
                else:
                    permitted = None
                if args.methodenvergleich_freigeben:
                    from ntf_insight.analysis.method_comparison_audit import (
                        approved_method_totals,
                    )
                    method_totals = approved_method_totals(report)
                else:
                    method_totals = None
    except Exception:
        # Never print exceptions, Python tracebacks, paths, FINs, SSL,
        # QEC identifiers, SQL fragments, evidence refs or DTC values.
        print(
            "NTF_LOKALE_ANALYSE_FEHLER: Keine Daten an GitHub uebertragen. "
            "Bitte Datenbankverfuegbarkeit, Berechtigungen, "
            "offene NTF-Insight-App und Runner-Umgebung lokal pruefen.",
            file=sys.stderr,
        )
        return 2
    print("NTF_LOKALE_ANALYSE_OK")
    if permitted is not None:
        # Whitelist-only numeric totals after EXPLICIT workflow approval.
        print(
            "NTF_FREIGEGEBENE_SUMMEN_JSON="
            + json.dumps(permitted, ensure_ascii=True, sort_keys=True)
        )
    if method_totals is not None:
        # This is a SEPARATE manual opt-in, never implied by summen_freigeben.
        # No group labels, individual cases, FINs, QECs or original DTCs.
        print(
            "NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON="
            + json.dumps(method_totals, ensure_ascii=True, sort_keys=True)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
