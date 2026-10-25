"""Zweiter ChatGPT-Durchlauf: vorhandene KI-Basis plus technische Fachunterlagen.

Kein Upload, keine Neu-Pseudonymisierung und keine automatische Schuldzuweisung.
Das bestehende JSON-Rückgabeformat wird unverändert übernommen, damit die
Ergebnisse wieder über den vorhandenen ChatGPT-Import validiert werden können.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from dataclasses import dataclass
from typing import Callable
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTRueckgabe, ergebnis_vorlage,
)
from ntf_insight.storage.cluster_evidence_store import (
    CATEGORY_LABELS, ClusterEvidenceStore, MAX_EVIDENCE_BYTES, part_key,
)
from ntf_insight.storage.workflow_projects import WorkflowProjectStore

FORMAT = "ntf-cluster-kontext"
VERSION = 1
MAX_PACKAGE_BYTES = 1024**3  # Maximal 1 GiB Original-/Basisdaten.
MAX_SOURCE_FILES = 6000
MAX_MEMBER_BYTES = 200 * 1024**2
_HEX_ID = re.compile(r"[a-f0-9]{32}\Z")
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class ClusterContextExport:
    path: Path
    parent_package_id: str
    category_count: int
    file_count: int
    included_files: int
    analysis_id: str


def _valid_entry(name: str) -> bool:
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
        return False
    if any(ord(c) < 32 for c in name):
        return False
    parts = PurePosixPath(name).parts
    return bool(parts) and all(
        part not in ("", ".", "..") and not part.endswith((" ", "."))
        and ":" not in part for part in parts
    )


def _safe_infos(archive: ZipFile) -> list[ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_SOURCE_FILES or len(infos) != len({
        item.filename.casefold() for item in infos
    }):
        raise ValueError("Erstes KI-Paket enthält zu viele oder doppelte Einträge.")
    if any(
        item.is_dir()
        or not _valid_entry(item.filename)
        or (item.external_attr >> 16) & 0o170000 == stat.S_IFLNK
        or item.file_size > MAX_MEMBER_BYTES
        or "nicht_hochladen" in item.filename.casefold()
        for item in infos
    ):
        raise ValueError("Erstes KI-Paket enthält unsichere oder private Einträge.")
    if sum(item.file_size for item in infos) > MAX_PACKAGE_BYTES:
        raise ValueError("Erstes KI-Paket überschreitet das Größenlimit.")
    return infos


def validate_first_package(archive_path: Path) -> str:
    """Nur das von NTF Insight erzeugte Analysepaket samt Rückgabevorlage."""
    path = Path(archive_path)
    if path.suffix.lower() != ".zip" or not path.is_file() or path.is_symlink():
        raise ValueError("Bitte ein vorhandenes KI-Analysepaket (.zip) wählen.")
    with ZipFile(path) as archive:
        members = {item.filename for item in _safe_infos(archive)}
        required = {
            "manifest.json", "chatgpt_ergebnis_schema.json",
            "chatgpt_ergebnis_vorlage.json",
        }
        if not required <= members:
            raise ValueError(
                "KI-Analysepaket fehlt die Manifest-/ChatGPT-Rückgabevorlage."
            )
        manifest = json.loads(archive.read("manifest.json"))
        package_id = manifest.get("paket_id")
        if (
            manifest.get("schema_version") != 3
            or not isinstance(package_id, str)
            or not _HEX_ID.fullmatch(package_id)
        ):
            raise ValueError("Unbekannte Version oder Paket-ID der Analysebasis.")
        # Vorlage muss dieselbe Paket-ID enthalten, die später beim Import geprüft wird.
        template = json.loads(archive.read("chatgpt_ergebnis_vorlage.json"))
        if template.get("paket_id") != package_id:
            raise ValueError("Vorlage und Analysebasis haben verschiedene Paket-IDs.")
        return package_id


def _copy_member(source, target, name: str, expected_sha: str | None = None) -> int:
    digest = hashlib.sha256()
    total = 0
    with target.open(name, "w", force_zip64=True) as output:
        while block := source.read(_CHUNK):
            total += len(block)
            if total > MAX_MEMBER_BYTES:
                raise ValueError("Originaldatei überschreitet das Exportlimit.")
            digest.update(block)
            output.write(block)
    if expected_sha is not None and digest.hexdigest() != expected_sha:
        raise ValueError("Originaldatei stimmt nicht mehr mit dem archivierten SHA-256 überein.")
    return total


def _zip_text(archive: ZipFile, name: str, content: str) -> None:
    archive.writestr(name, content.encode("utf-8"))


def export_cluster_context(
    store: ClusterEvidenceStore,
    profile_id: str,
    part_number: str,
    first_package: Path,
    destination: Path,
    *,
    include_originals: bool = False,
    first_result: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> ClusterContextExport:
    """Kontextpaket aus der verifizierten KI-Analysebasis und kategorisierten Belegen."""
    first_package = Path(first_package).absolute()
    destination = Path(destination).absolute()
    if destination.suffix.lower() != ".zip":
        raise ValueError("Zieldatei muss die Endung .zip haben.")
    if destination == first_package or destination.exists():
        raise FileExistsError("Ziel existiert bereits oder ist das ursprüngliche KI-Paket.")
    root = store.store.path.parent.absolute()
    if destination.is_relative_to(root) or destination.is_symlink():
        raise ValueError("Analyse-ZIP außerhalb des NTF-Datenverzeichnisses speichern.")

    if progress:
        progress("Erste ChatGPT-Analyse und Quelldateien prüfen …")
    package_id = validate_first_package(first_package)
    with ZipFile(first_package) as base:
        base_manifest = json.loads(base.read("manifest.json"))
    project_scoped = base_manifest.get("analyseumfang") == "workflow_01_02_qec"
    if project_scoped:
        # Erste und zweite Runde sind mit derselben registrierten
        # Profil-/Sachnummernzuordnung verbunden. Gleiche FIN genuegt nie.
        if base_manifest.get("projektprofil") != profile_id:
            raise ValueError(
                "Die erste QEC-Analysebasis gehoert einem anderen Bauteilprofil."
            )
        with store.store.connect() as con:
            stored = con.execute(
                "SELECT sha256 FROM workflow_first_ai_packages "
                "WHERE profile_id=? AND part_key=? AND paket_id=?",
                [profile_id, part_key(part_number), package_id],
            ).fetchone()
        digest = hashlib.sha256()
        with first_package.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(chunk)
        if stored is None or stored[0] != digest.hexdigest():
            raise ValueError(
                "Erste Analysebasis ist nicht zu diesem Sachnummernprojekt "
                "registriert oder die ZIP-Pruefsumme weicht ab."
            )
    verified_result = (
        ChatGPTRueckgabe.model_validate(first_result)
        if first_result is not None else None
    )
    if verified_result is not None and verified_result.paket_id != package_id:
        raise ValueError("Erstes ChatGPT-Ergebnis gehört nicht zur gewählten KI-Basis.")
    evidence = store.list_files(profile_id, part_number)
    counts = store.counts(profile_id, part_number)
    project = WorkflowProjectStore(store.store).get(profile_id, part_number)
    analysis_id = (
        "Cluster-" + package_id[:12] + "-" + secrets.token_hex(4)
    )
    files_manifest: list[dict] = []
    for index, item in enumerate(evidence, 1):
        label = f"D{index:04d}"
        target = (
            f"unterlagen/{item.category}/{label}{item.source_path.suffix.lower()}"
            if include_originals else None
        )
        files_manifest.append({
            "beleg_id": label, "kategorie": item.category,
            "kategorie_name": CATEGORY_LABELS[item.category],
            "datei_im_paket": target,
            "original_aufgenommen": bool(target),
        })
    if include_originals and sum(x.size_bytes for x in evidence) > MAX_PACKAGE_BYTES:
        raise ValueError("Fachunterlagen überschreiten zusammen 1 GiB.")
    component_name = (
        project.component_name if project is not None
        else profile_id.replace("_", " ")
    )
    instruction_lines = [
        "NTF Insight · Zweiter ChatGPT-Durchlauf / vertiefter Analysekontext",
        "",
        f"Bauteil: {component_name}. Technische Interpretation immer nur anhand "
        "der tatsaechlich vorliegenden Quellen; keine pauschalen ECU-/DTC-Annahmen.",
        "1. Die erste QEC-Analysebasis liegt unter basis/. Die zugehoerige erste "
        "ChatGPT-Auswertung liegt in voranalyse/erstes_chatgpt_ergebnis.json "
        "(soweit vorhanden). Fehlende QEC-Berichte sind eine legitime Datenluecke.",
        "2. Nutze Unterlagen aus dem aktuell ausgewaehlten Profil- und "
        "Sachnummernprojekt fuer neue Hypothesen: Diagnoseprotokolle, "
        "Fehlersetzbedingungen, Steuergeraetekommunikation, "
        "Fahrzeugnetzwerk, HW-/SW-Aenderungen und Bauteildaten.",
        "3. Nur dort Vor-/Nach-Tausch-Aussagen treffen, wo Tauschzeitpunkt, "
        "Diagnosezeitpunkt und Fallzuordnung belegt sind. Fehlende QuickTests, "
        "AutoExport-, TIPS- oder QEC-Daten niemals erfinden. "
        "Andere Bauteile und andere Sachnummern nicht vermischen.",
        "4. Eine Lieferantenverursachung ist niemals aus NTF-, SSL-, "
        "Diagnose- oder Lieferantenlabels allein bewiesen. Differenziere "
        "technische Moeglichkeit, Hypothese, Verifikation und Verantwortung.",
        "5. Gib ausschliesslich das JSON nach chatgpt_ergebnis_schema.json aus. "
        "Die paket_id aus chatgpt_ergebnis_vorlage.json bleibt identisch; "
        "die neue analyse_id muss der Vorlage entsprechen. "
        "Belegreferenzen nur fuer wirklich vorhandene Quellen verwenden.",
        "6. Die private Pseudonymzuordnung gehoert niemals in den Upload. "
        "Pseudonymisierte technische Daten sind nicht garantiert anonymisiert. "
        "Externe Verarbeitung nur mit Unternehmensfreigabe.",
    ]
    if project is not None and project.ecu_names:
        instruction_lines.insert(
            3, "Projektseitig konfigurierte moeglich relevante ECUs "
            "(kein Nachweis fuer DTC oder Ursache): "
            + ", ".join(project.ecu_names) + "."
        )
    instructions = "\n".join(instruction_lines) + "\n"
    manifest = {
        "format": FORMAT,
        "schema_version": VERSION,
        "basis_paket_id": package_id,
        "profil": profile_id,
        "bauteilbezeichnung": component_name,
        "relevante_ecus_konfiguriert": (
            list(project.ecu_names) if project is not None else []
        ),
        "sachnummer_wurde_lokal_gefiltert": project_scoped,
        "unterlagen_nach_sachnummer_zugeordnet": bool(part_number.strip()),
        "basis_nicht_nach_sachnummer_gefiltert": not project_scoped,
        "erster_chatgpt_durchlauf": {
            "enthalten": verified_result is not None,
            "analyse_id": verified_result.analyse_id if verified_result else None,
        },
        "analyse_id_zweiter_durchlauf": analysis_id,
        "inhalt_originaldateien": include_originals,
        "bestand": counts,
        "belege": files_manifest,
        "datenfreigabe_automatisch": False,
        "anonymisiert_garantiert": False,
        "rueckgabe": "chatgpt_ergebnis_vorlage.json",
        "rueckgabe_schema": "chatgpt_ergebnis_schema.json",
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tempname = tempfile.mkstemp(
        prefix=".ntf-cluster-", suffix=".partial", dir=destination.parent,
    )
    os.close(fd)
    temp = Path(tempname)
    try:
        total_bytes = 0
        with ZipFile(first_package, "r") as base, ZipFile(
            temp, "w", compression=ZIP_DEFLATED, compresslevel=3,
        ) as archive:
            infos = _safe_infos(base)
            base_manifest = json.loads(base.read("manifest.json"))
            if base_manifest.get("paket_id") != package_id:
                raise ValueError("Analysepaket wurde seit der Auswahl verändert.")
            if not include_originals and not base_manifest.get("pseudonymisiert", False):
                raise ValueError(
                    "Die gewählte KI-Basis enthält Freitext/Originaldaten. "
                    "Bitte eine pseudonymisierte Basis auswählen oder "
                    "Originale nach Unternehmensfreigabe ausdrücklich aktivieren."
                )
            for index, info in enumerate(infos, 1):
                if progress:
                    progress(f"KI-Basis kopieren: {index}/{len(infos)}")
                # Bereits pseudonymisierte Daten und gegebenenfalls vom Nutzer
                # freigegebene Originale der Basis exakt und ohne Umbenennung erhalten.
                if not include_originals and info.filename.startswith("qec_originale/"):
                    raise ValueError(
                        "Basis-ZIP enthält QEC-Originale; bitte Original-Option "
                        "bewusst aktivieren oder Basis ohne Originale erstellen."
                    )
                with base.open(info, "r") as source:
                    total_bytes += _copy_member(
                        source, archive, "basis/" + info.filename,
                    )
                if total_bytes > MAX_PACKAGE_BYTES:
                    raise ValueError("Export überschreitet 1 GiB.")
            # Die zweite Auswertung erhält dieselbe Paket-/Fallzuordnung,
            # aber eine neue eindeutige ID statt einer Kopie der 1.-Runde-Vorlage.
            followup_template = ergebnis_vorlage(package_id)
            followup_template["analyse_id"] = analysis_id
            _zip_text(
                archive, "chatgpt_ergebnis_vorlage.json",
                json.dumps(followup_template, ensure_ascii=False, indent=2),
            )
            _zip_text(
                archive, "chatgpt_ergebnis_schema.json",
                base.read("chatgpt_ergebnis_schema.json").decode("utf-8-sig"),
            )
            if verified_result is not None:
                _zip_text(
                    archive, "voranalyse/erstes_chatgpt_ergebnis.json",
                    verified_result.model_dump_json(indent=2, exclude_none=True),
                )
            if include_originals:
                raw_root = store.archive.root.resolve()
                for index, (original, meta) in enumerate(
                    zip(evidence, files_manifest), 1,
                ):
                    if progress:
                        progress(f"Fachunterlagen einfügen: {index}/{len(evidence)}")
                    path = original.source_path
                    if (
                        path.is_symlink() or not path.is_file()
                        or not path.resolve().is_relative_to(raw_root)
                        or path.stat().st_size > MAX_EVIDENCE_BYTES
                    ):
                        raise ValueError("Unterlage fehlt oder liegt außerhalb des Quellarchivs.")
                    with path.open("rb") as source:
                        total_bytes += _copy_member(
                            source, archive, meta["datei_im_paket"],
                            expected_sha=original.sha256,
                        )
                    if total_bytes > MAX_PACKAGE_BYTES:
                        raise ValueError("Export überschreitet 1 GiB.")
            _zip_text(
                archive, "cluster_kontext_manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            _zip_text(archive, "CHATGPT_2_DURCHLAUF.txt", instructions)
        if destination.exists():
            raise FileExistsError("Zieldatei wurde inzwischen angelegt.")
        os.replace(temp, destination)
        if progress:
            progress("Zweites ChatGPT-Paket vollständig gespeichert.")
    finally:
        temp.unlink(missing_ok=True)
    return ClusterContextExport(
        path=destination,
        parent_package_id=package_id,
        category_count=sum(value > 0 for value in counts.values()),
        file_count=len(evidence),
        included_files=len(evidence) if include_originals else 0,
        analysis_id=analysis_id,
    )
