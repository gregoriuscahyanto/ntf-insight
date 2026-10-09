"""Pseudonymisierte, lokale Cluster-Pruefpakete fuer eine externe Fachbesprechung.

Eine ZIP ist keine Freigabe zur Weitergabe. Insbesondere technische DTC-Muster
koennen intern vertraulich sein. Keine FIN, QEC-ID, SSL-Freitexte, Rohberichte,
Lieferantenkennungen, Pruefer oder Originalreferenzen verlassen den Export.
Zuordnungstabellen entstehen als separate lokale Dateien, NIEMALS in der ZIP.
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from ntf_insight.analysis.case_clustering import signature_for
from ntf_insight.analysis.diagnostic_evidence_audit import DiagnosticEvidenceAudit
from ntf_insight.analysis.diagnostic_gap_investigation import DiagnosticGapReport
from ntf_insight.analysis.hdbscan_clustering import HDBSCANMethodComparison, MLClusterResult
from ntf_insight.analysis.mechanism_review import ConfirmedMechanism, safe_spreadsheet_cell
from ntf_insight.analysis.representative_transfer import plan_representative_transfer
from ntf_insight.domain.case import NTFCase


PACKAGE_FILES = (
    "README.txt",
    "manifest.json",
    "cluster.csv",
    "repraesentanten.csv",
    "cluster_mitglieder.csv",
    "interne_fallpaare.csv",
    "diagnosemerkmale.csv",
    "dtc_haeufigkeiten.csv",
    "diagnosequalitaet.csv",
    "ausgeschlossene_faelle.csv",
    "methodenvergleich.csv",
)


@dataclass(frozen=True, slots=True)
class ClusterZipExport:
    zip_path: Path
    private_case_map: Path
    private_dtc_map: Path
    cluster_count: int
    representative_count: int
    case_count: int


def _cell(value: object) -> object:
    if isinstance(value, str):
        return safe_spreadsheet_cell(value)
    return value


def _csv_bytes(headers: tuple[str, ...], rows: list[tuple]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(tuple(_cell(value) for value in row))
    return stream.getvalue().encode("utf-8-sig")


def _zip_entry(archive: ZipFile, name: str, payload: bytes) -> None:
    # Fixed internal names and timestamps; no source paths, file metadata,
    # host/usernames or case identifiers in ZIP headers.
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, payload)


def _score(distance: float) -> float:
    # HDBSCAN uses Euclidean distances of normalized nonnegative TF-IDF vectors.
    return round(max(0.0, min(1.0, 1.0 - distance * distance / 2.0)), 4)


def _validate(
    cases: list[NTFCase],
    result: MLClusterResult,
    audit: DiagnosticEvidenceAudit,
    confirmations: tuple[ConfirmedMechanism, ...],
    gaps: DiagnosticGapReport | None,
) -> dict[str, NTFCase]:
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("Mehrfach angelegte QEC-Fall-ID: ZIP-Export abgebrochen.")
    if result.case_count != len(cases) or audit.scoped_cases != len(cases):
        raise ValueError("ML-Ergebnis und Diagnoseaudit passen nicht zum Fallbestand.")
    if {row.case_id for row in audit.cases} != set(by_id):
        raise ValueError("Die Diagnoseprüfung enthält andere Fälle.")
    if result.dtc_source != audit.dtc_source or result.lookback_days != audit.lookback_days:
        raise ValueError("Diagnoseprüfung und ML-Szenario haben verschiedene Quellen/Zeitfenster.")
    eligible = set(result.eligible_case_ids)
    listed = eligible | set(result.excluded_case_ids)
    if listed != set(by_id) or eligible & set(result.excluded_case_ids):
        raise ValueError("ML-Ergebnis enthält keine vollständige Fallpartition.")
    member_ids = [member.case_id for group in result.clusters for member in group.members]
    if len(member_ids) != len(set(member_ids)) or not set(member_ids).issubset(eligible):
        raise ValueError("Ungültige ML-Gruppenzuordnung.")
    if any(group.representative_case_id not in group.case_ids for group in result.clusters):
        raise ValueError("ML-Repräsentant fehlt in der eigenen Gruppe.")
    if (set(member_ids) | set(result.noise_case_ids)) != eligible:
        raise ValueError("Ausreißer/Gruppierung passen nicht zur ML-Kohorte.")
    if len(set(result.noise_case_ids)) != len(result.noise_case_ids):
        raise ValueError("Ausreißer mehrfach aufgeführt.")
    if len(result.distances) != len(result.eligible_case_ids):
        raise ValueError("ML-Distanzmatrix hat falsche Größe.")
    if any(len(row) != len(eligible) for row in result.distances):
        raise ValueError("ML-Distanzmatrix ist nicht quadratisch.")
    label_ids = [label.case_id for label in confirmations]
    if len(label_ids) != len(set(label_ids)) or not set(label_ids).issubset(by_id):
        raise ValueError("Fachbestätigungen passen nicht zum QEC-Fallbestand.")
    if gaps is not None and not {r.case_id for r in gaps.cases}.issubset(by_id):
        raise ValueError("FIN-Rohdatenaudit bezieht sich auf andere QEC-Fälle.")
    return by_id


def write_cluster_review_zip(
    destination: Path,
    cases: list[NTFCase],
    result: MLClusterResult,
    audit: DiagnosticEvidenceAudit,
    *,
    confirmations: tuple[ConfirmedMechanism, ...] = (),
    gaps: DiagnosticGapReport | None = None,
    comparison: HDBSCANMethodComparison | None = None,
) -> ClusterZipExport:
    """Write a self-contained, pseudonymized analysis ZIP and TWO private mappings.

    Pseudonyms are stable *within one package*, not cryptographic anonymization.
    All free-text findings, real ECU/DTC keys, VIN/FIN, QEC IDs, source references,
    supplier identities and workshop dates are deliberately excluded.
    CSVs are tabular summaries, NOT independent technical verification.
    """
    by_id = _validate(cases, result, audit, confirmations, gaps)
    target = Path(destination).expanduser()
    if target.suffix.lower() != ".zip":
        raise ValueError("Bitte eine ZIP-Datei mit Endung .zip wählen.")
    if not target.parent.is_dir():
        raise ValueError("Zielordner für ZIP-Export existiert nicht.")
    case_map = target.with_name(target.stem + "_NICHT_HOCHLADEN_FALLZUORDNUNG.csv")
    fault_map = target.with_name(target.stem + "_NICHT_HOCHLADEN_DTC_ZUORDNUNG.csv")
    if any(path.exists() for path in (target, case_map, fault_map)):
        raise FileExistsError(
            "ZIP oder private Zuordnung existiert bereits. "
            "Bitte anderen Dateinamen wählen; vorhandene Daten bleiben unverändert."
        )

    case_ids = sorted(by_id)
    vins = sorted({case.vin for case in cases})
    aliases = {cid: f"F{i:04d}" for i, cid in enumerate(case_ids, start=1)}
    vin_aliases = {vin: f"V{i:04d}" for i, vin in enumerate(vins, start=1)}
    group_for = {
        member.case_id: f"H{group.cluster_id}"
        for group in result.clusters for member in group.members
    }
    signatures = {
        cid: signature_for(
            by_id[cid],
            dtc_source=result.dtc_source,
            lookback_days=result.lookback_days,
        )
        for cid in result.eligible_case_ids
    }
    all_faults = sorted({fault for sig in signatures.values() for fault in sig.faults})
    fault_aliases = {
        fault: f"D{i:04d}" for i, fault in enumerate(all_faults, start=1)
    }
    frequencies = Counter(
        fault for signature in signatures.values() for fault in signature.faults
    )
    confirmed = {label.case_id: label for label in confirmations}
    transfer = plan_representative_transfer(cases, result, confirmations)
    transfer_for = {(item.group, item.target_case_id): item for item in transfer.rows}
    positions = {cid: i for i, cid in enumerate(result.eligible_case_ids)}

    cluster_rows = []
    rep_rows = []
    member_rows = []
    pair_rows = []
    feature_rows = []
    for group in result.clusters:
        cluster_key = f"H{group.cluster_id}"
        medoid = group.representative_case_id
        mechanism = confirmed.get(medoid)
        cluster_rows.append((
            cluster_key, group.case_count, group.vehicle_count,
            aliases[medoid], round(group.mean_to_representative, 4),
            group.weakest_internal_similarity,
            group.median_internal_similarity, group.p10_internal_similarity,
            group.weak_pair_count, group.internal_pair_count,
            group.min_membership_strength, len(group.common_faults),
            group.ssl_finding_count, group.screening_status,
            int(any("SSL-Endbefundtexte weichen" in flag for flag in group.warnings)),
        ))
        rep_rows.append((
            cluster_key, aliases[medoid], vin_aliases[by_id[medoid].vin],
            group.case_count, len(group.common_faults),
            int(mechanism is not None),
            mechanism.mechanism_code if mechanism else "",
            int(group.ssl_finding_count > 0),
            "Mechanismus am Repräsentanten bestätigt, nicht am Cluster"
            if mechanism else "Keine bestätigte technische Ursache",
        ))
        for member in group.members:
            cid = member.case_id
            hypothesis = transfer_for.get((cluster_key, cid))
            member_label = confirmed.get(cid)
            member_rows.append((
                cluster_key, aliases[cid], vin_aliases[by_id[cid].vin],
                aliases[medoid], int(cid == medoid),
                member.similarity_to_representative,
                member.membership_strength, len(member.shared_faults),
                int(by_id[cid].vin == by_id[medoid].vin),
                int(member_label is not None),
                member_label.mechanism_code if member_label else "",
                hypothesis.status if hypothesis else "Repräsentant",
                hypothesis.mechanism_hypothesis if hypothesis else "",
            ))
        for first, second in combinations(group.case_ids, 2):
            similarity = _score(result.distances[positions[first]][positions[second]])
            pair_rows.append((
                cluster_key, aliases[first], aliases[second], similarity,
                int(similarity < 0.45), int(by_id[first].vin == by_id[second].vin),
            ))

    for cid in result.eligible_case_ids:
        case = by_id[cid]
        tag = group_for.get(cid, "RAUSCHEN")
        signature = signatures[cid]
        for fault in sorted(signature.faults):
            feature_rows.append((
                aliases[cid], tag, vin_aliases[case.vin],
                fault_aliases[fault], int(fault[0] == "CPC3"),
                int(
                    result.common_dtc_cutoff is None
                    or frequencies[fault] / len(result.eligible_case_ids)
                    < result.common_dtc_cutoff
                ),
            ))

    dtc_rows = []
    for fault in all_faults:
        freq = frequencies[fault]
        dtc_rows.append((
            fault_aliases[fault], freq,
            round(freq / len(result.eligible_case_ids), 5)
            if result.eligible_case_ids else 0,
            int(fault[0] == "CPC3"),
        ))
    audit_rows = [
        ("QEC-Fälle", audit.scoped_cases),
        ("QEC mit Vorher-DTC", audit.eligible_cases),
        ("Kein QEC-DTC", audit.without_any_dtc),
        ("Tauschanker fehlt", audit.without_anchor),
        ("DTC zeitlich nicht sicher vorher", audit.only_after_swap_or_undated),
        ("Vorher-DTC nicht aus gewählter Quelle", audit.no_selected_source),
        ("Vorher-DTC außerhalb Zeitfenster", audit.outside_lookback),
        ("Quellüberschneidungen je QEC", audit.with_source_overlap),
    ]
    if gaps is not None:
        audit_rows += [
            ("FIN-Rohquellen geprüft", int(gaps.raw_available)),
            ("Ausgeschlossene Fälle mit Vorher-Rohhinweis", gaps.with_raw_pre_hint),
            ("QEC-DTC am Tauschtag", gaps.qec_same_day_cases),
            ("QEC-DTC nach Tausch", gaps.qec_post_only_cases),
        ]
    gaps_by_case = {item.case_id: item for item in gaps.cases} if gaps else {}
    excluded_rows = []
    for row in sorted(audit.cases, key=lambda value: value.case_id):
        if row.reason == "Auswertbare Vor-Tausch-Diagnose":
            continue
        gap = gaps_by_case.get(row.case_id)
        excluded_rows.append((
            aliases[row.case_id], vin_aliases[by_id[row.case_id].vin],
            row.reason, row.all_event_rows,
            gap.qec_same_day if gap else "",
            gap.qec_after if gap else "",
            gap.raw_pre_dtc_rows if gap else "",
            gap.raw_same_day_dtc_rows if gap else "",
            gap.raw_post_dtc_rows if gap else "",
            gap.raw_unusable_date_rows if gap else "",
        ))

    comparison_rows = []
    if comparison is not None and comparison.eligible_case_count:
        if (
            comparison.eligible_case_count != len(result.eligible_case_ids)
            or comparison.dtc_source != result.dtc_source
            or comparison.lookback_days != result.lookback_days
            or comparison.common_dtc_cutoff != result.common_dtc_cutoff
        ):
            raise ValueError("EOM/Leaf-Vergleich gehört zu einem anderen ML-Szenario.")
        for line in comparison.rows:
            comparison_rows.append((
                line.selection_method, line.group_count, line.clustered_cases,
                line.noise_cases, round(line.weak_pair_fraction, 5),
                line.median_of_group_medians,
                comparison.pair_coassignment_jaccard,
            ))

    metadata = {
        "format": "ntf-insight-cluster-review",
        "version": 1,
        "pseudonymisiert": True,
        "enthält": "Nur abgeleitete Diagnosetabellen und Prüfhypothesen",
        "freie_ssl_texte": False,
        "fin_oder_qec_ids": False,
        "ecu_dtc_originalschluessel": False,
        "unabhaengige_fachbestaetigungen": len(confirmed),
        "cluster": len(result.clusters),
        "repraesentanten": len(rep_rows),
        "faelle": result.case_count,
        "fahrzeuge": result.vehicle_count,
        "ml_geeignete_faelle": len(result.eligible_case_ids),
        "ml_ausreisser": len(result.noise_case_ids),
        "ml_ausgeschlossen": len(result.excluded_case_ids),
        "gruppierte_faelle": result.clustered_count,
        "szenario": {
            "methode": result.selection_method,
            "min_cluster_size": result.min_cluster_size,
            "min_samples": result.min_samples,
            "quellen": result.dtc_source,
            "vor_tausch_tage": result.lookback_days,
            "dtc_filter_ab": result.common_dtc_cutoff,
        },
        "schwelle_45_prozent_nicht_kalibriert": True,
        "befundtransfer_nur_hypothese": True,
        "fachliche_ursache_aus_clusters_allein": False,
    }
    readme = (
        "NTF INSIGHT – PSEUDONYMISIERTES CLUSTER-PRÜFPAKET\n"
        "================================================\n"
        "Enthält Modellkennzahlen, Pseudonyme, Diagnosemuster und Prüfhypothesen.\n"
        "Enthält KEINE FINs, QEC-IDs, SSL-Freitexte, Labororiginalberichte,\n"
        "Werkstattbeschwerden, Quellpfade, Lieferantennamen oder Prüferdaten.\n"
        "Fxxxx bezeichnet einen QEC-Fall, Vxxxx ein Fahrzeug und Dxxxx\n"
        "eine identische ECU:DTC-Kombination innerhalb DIESES Pakets.\n"
        "Dxxxx ist KEIN auswertbarer Original-DTC-Code. CPC3 wird als\n"
        "boolesches Merkmal ausgewiesen. Gleiche Dxxxx sind vergleichbar.\n"
        "Die Zuordnungstabellen mit echten Schlüsseln liegen SEPARAT\n"
        "neben der ZIP und dürfen NICHT hochgeladen werden.\n"
        "Wichtig: Pseudonymisierung bedeutet nicht automatische Freigabe\n"
        "nach Unternehmensrichtlinien. Inhalt vor Weitergabe freigeben.\n"
        "Cluster und Fallpaar-Ähnlichkeiten beweisen keine gemeinsame Ursache.\n"
        "Fachlich bestätigte Repräsentantenmechanismen sind NICHT automatisch\n"
        "bestätigte Mechanismen für andere Fahrzeuge. NTF oder Lieferanten-\n"
        "verantwortung kann aus diesen Kennzahlen nicht bewiesen werden.\n"
        "Für die fachliche Ursachenanalyse können intern weiterhin SSL-,\n"
        "Labor- und Befundoriginale sowie gesicherte DTC-Bedeutungen nötig sein.\n"
        "CSV-Trennzeichen ist Semikolon; Zeichensatz UTF-8 mit BOM.\n"
    )
    files = {
        "README.txt": readme.encode("utf-8"),
        "manifest.json": (
            json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        "cluster.csv": _csv_bytes((
            "Gruppe", "QEC-Fälle", "Fahrzeuge", "Repräsentant",
            "Ø Cosinus zu Repräsentant", "Schwächstes internes Paar",
            "Median interne Paare", "10%-Quantil interne Paare",
            "Paare unter 45%", "Alle internen Paare", "Min. HDBSCAN-Stabilität",
            "Durchgehend gemeinsame ECU:DTC", "SSL-Befunde vorhanden",
            "Screening", "SSL-Texte unterscheiden sich",
        ), cluster_rows),
        "repraesentanten.csv": _csv_bytes((
            "Gruppe", "Repräsentanten-Fall", "Repräsentanten-Fahrzeug",
            "QEC-Fälle im Cluster", "Gemeinsame DTCs", "Fachlich bestätigt",
            "Bestätigter Mechanismus NUR am Repräsentanten",
            "Cluster enthält SSL-Endbefund", "Hinweis",
        ), rep_rows),
        "cluster_mitglieder.csv": _csv_bytes((
            "Gruppe", "Fall", "Fahrzeug", "Repräsentant", "Ist Repräsentant",
            "Cosinus zum Repräsentanten", "HDBSCAN-Stabilität",
            "Gemeinsame DTC mit Repräsentant", "Gleiche FIN wie Repräsentant",
            "Mechanismus am Fall unabhängig bestätigt",
            "Unabhängig bestätigter Mechanismus am Fall",
            "Übertragungsprüfung", "Mechanismus NUR als Hypothese",
        ), member_rows),
        "interne_fallpaare.csv": _csv_bytes((
            "Gruppe", "Fall A", "Fall B", "Cosinus", "Unter 45%",
            "Gleiches Fahrzeug",
        ), pair_rows),
        "diagnosemerkmale.csv": _csv_bytes((
            "Fall", "Gruppe / Rauschen", "Fahrzeug", "DTC-Alias",
            "CPC3-Quelle", "Merkmal im gewählten ML-Szenario",
        ), feature_rows),
        "dtc_haeufigkeiten.csv": _csv_bytes((
            "DTC-Alias", "QEC-Fälle mit DTC", "Anteil an geeigneten QEC-Fällen",
            "CPC3-Quelle",
        ), dtc_rows),
        "diagnosequalitaet.csv": _csv_bytes(("Prüfgröße", "Anzahl"), audit_rows),
        "ausgeschlossene_faelle.csv": _csv_bytes((
            "Fall", "Fahrzeug", "Primärer Ausschluss", "QEC-DTC-Zeilen",
            "QEC-DTC am Tauschtag", "QEC-DTC nach Tausch",
            "FIN-Roh-DTC vor Tausch", "Roh-DTC gleicher Tag",
            "FIN-Roh-DTC nach Tausch", "Roh-DTC ohne Zeit",
        ), excluded_rows),
        "methodenvergleich.csv": _csv_bytes((
            "Methode", "Cluster", "Gruppierte Fälle", "Ausreißer",
            "Schwache Fallpaare Anteil", "Median Cluster-Paarmediane",
            "EOM-Leaf-Paarzuordnung Jaccard",
        ), comparison_rows),
    }
    if set(files) != set(PACKAGE_FILES):
        raise ValueError("ZIP-Struktur unvollständig.")

    local_cases = _csv_bytes(("Fall-Alias", "QEC-Fall-ID", "FIN", "Fahrzeug-Alias"), [
        (aliases[cid], cid, by_id[cid].vin, vin_aliases[by_id[cid].vin])
        for cid in case_ids
    ])
    local_dtcs = _csv_bytes(("DTC-Alias", "ECU", "DTC"), [
        (fault_aliases[fault], fault[0], fault[1]) for fault in all_faults
    ])

    # Commit ZIP and private mapping tables only from a completed temp directory.
    with tempfile.TemporaryDirectory(
        prefix="ntf-review-export-", dir=target.parent
    ) as scratch:
        temp = Path(scratch)
        staged_zip = temp / "package.zip"
        with ZipFile(staged_zip, mode="w", compression=ZIP_DEFLATED) as archive:
            for name in PACKAGE_FILES:
                _zip_entry(archive, name, files[name])
        staged_cases = temp / "case_mapping.csv"
        staged_dtcs = temp / "dtc_mapping.csv"
        staged_cases.write_bytes(local_cases)
        staged_dtcs.write_bytes(local_dtcs)
        # The generated private lookup tables are deliberately *not* in ZIP.
        os.replace(staged_cases, case_map)
        os.replace(staged_dtcs, fault_map)
        os.replace(staged_zip, target)

    return ClusterZipExport(
        zip_path=target, private_case_map=case_map, private_dtc_map=fault_map,
        cluster_count=len(result.clusters), representative_count=len(rep_rows),
        case_count=result.case_count,
    )
