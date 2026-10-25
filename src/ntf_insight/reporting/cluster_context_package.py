"""Zweiter LLM-Durchlauf: vorhandene KI-Basis plus technische Fachunterlagen.

Kein Upload, keine Neu-Pseudonymisierung und keine automatische Schuldzuweisung.
Das bestehende JSON-Rückgabeformat wird unverändert übernommen, damit die
Ergebnisse wieder über den vorhandenen LLM-Import validiert werden können.
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
    ChatGPTRueckgabe, ergebnis_schema, ergebnis_vorlage,
)
from ntf_insight.storage.cluster_evidence_store import (
    CATEGORY_LABELS, ClusterEvidenceStore, MAX_EVIDENCE_BYTES, part_key,
)
from ntf_insight.storage.workflow_projects import WorkflowProjectStore
from ntf_insight.reporting.cluster_technical_data import (
    export_parsed_diagnostics,
    export_tips_filtered,
    export_tp_filtered,
    load_technical_scope,
    parsed_source_hashes,
    plan_original_context,
)

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
                "KI-Analysepaket fehlt die Manifest-/LLM-Rückgabevorlage."
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
    include_confidential_basis: bool = False,
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
        progress("Erste LLM-Analyse und Quelldateien prüfen …")
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
    scope = None
    if project_scoped:
        with ZipFile(first_package) as base:
            scope = load_technical_scope(
                store.store, package_id, base, profile_id, part_number,
            )
    verified_result = (
        ChatGPTRueckgabe.model_validate(first_result)
        if first_result is not None else None
    )
    if verified_result is not None and verified_result.paket_id != package_id:
        raise ValueError("Erstes LLM-Ergebnis gehört nicht zur gewählten KI-Basis.")
    evidence = store.list_files(profile_id, part_number)
    counts = store.counts(profile_id, part_number)
    project = WorkflowProjectStore(store.store).get(profile_id, part_number)
    analysis_id = (
        "Cluster-" + package_id[:12] + "-" + secrets.token_hex(4)
    )
    planned_originals = []
    if scope is not None:
        parsed_shas = parsed_source_hashes(store.store, scope)
        files_manifest, planned_originals = plan_original_context(
            store.store, scope, evidence, parsed_shas,
            include_originals=include_originals,
        )
        for item in files_manifest:
            item["kategorie_name"] = CATEGORY_LABELS.get(
                item["kategorie"], "Nicht geparster Diagnosis-Viewer-Beleg",
            )
    else:
        # Legacy-Pakete ohne Projektumfang nur mit explizitem Warnhinweis.
        files_manifest = []
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
                "zuordnung": "Manuell/Legacy, nicht projektgeprueft",
            })
    if include_originals and sum(
        item.size_bytes for item in evidence
    ) > MAX_PACKAGE_BYTES and scope is None:
        raise ValueError("Fachunterlagen überschreiten zusammen 1 GiB.")
    if include_originals and sum(
        item.path.stat().st_size for item in planned_originals
    ) > MAX_PACKAGE_BYTES:
        raise ValueError(
            "Mehr als 1 GiB projektbezogene Originale. "
            "Bitte Unterlagen sachgerecht aufteilen, nicht still auslassen."
        )
    component_name = (
        project.component_name if project is not None
        else profile_id.replace("_", " ")
    )
    instruction_lines = [
        "NTF Insight · Zweiter LLM-Durchlauf / vertiefter Analysekontext",
        "",
        f"Bauteil: {component_name}. Technische Interpretation immer nur anhand "
        "der tatsaechlich vorliegenden Quellen; keine pauschalen ECU-/DTC-Annahmen.",
        "1. Die erste QEC-Analysebasis liegt unter basis/. Die zugehoerige erste "
        "LLM-Auswertung liegt in voranalyse/erstes_chatgpt_ergebnis.json "
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
        "7. Der Ordner diagnose/ enthaelt geparste Diagnosis-Viewer-QuickTests "
        "(Berichte, ECU-Staende, alle DTCs, DTC-Parameter und fallbezogene "
        "Zeitvergleiche), FIN-gefilterte TP-Dashboard-Zeilen und vorhandene "
        "TIPS-Writer-Reiter. Die eigentlichen Diagnoseinformationen stammen "
        "vom Gesamtfahrzeug und sind noch kein Nachweis fuer das untersuchte "
        "Bauteil. Die QuickTest-Seitentexte koennen vertraulich sein.",
        "8. unterlagen/ enthaelt die explizit freigegebenen Originalbelege "
        "des Sachnummernprojekts und pro FIN fehlende Parserfassungen "
        "als QuickTest-PDF-Fallback. Geparste QuickTests werden nicht "
        "zusaetzlich als PDF dupliziert. Wenn ein Beleg im Manifest "
        "als nicht aufgenommen gekennzeichnet ist, NICHT so tun, als "
        "waere sein Inhalt ausgewertet worden.",
        "9. Untersuche ALLE Faelle einzeln und fasse gemeinsame Muster "
        "nur mit positiven technischen Indizien zusammen. Gleiche FIN "
        "bedeutet nicht gleicher Schadteilfall. QEC- und SSL-Ergebnislabels "
        "nicht als Ursache oder Clustermerkmal verwenden.",
        "10. Untersuche diagnostisch belegte Fehler vor und nach dem "
        "Bauteiltausch nur bei belegtem Tauschanker, Diagnosezeitpunkt "
        "und vorliegenden Vergleichsdaten. Wiederkehr und Dauerhaftigkeit "
        "getrennt beurteilen; fehlende Nachtests sind nicht fehlerfrei.",
        "11. Dokumentiere pro Fall: NTF-Hypothese, moeglichen "
        "Verursachungsbereich (Lieferant/Integration/Netzwerk/Werkstatt/"
        "unbekannt, nur wenn belegt), Gegenindizien, Unsicherheit, "
        "zu bestaetigende Hypothesen und konkrete naechste Pruefung. "
        "Markiere jeden fehlenden Nachweis explizit.",
        "12. Fuehre die vorhandene erste KI-Bewertung als Ausgangshypothese "
        "mit, bewerte ihre Sicherheit anhand der NEUEN technischen Quellen "
        "erneut und benenne Aenderungen explizit. Belege fuer neue "
        "technische Zeilen als quelle=technische_referenz mit der "
        "tatsaechlichen Datei und Zeilen-/Seitenfundstelle angeben. "
        "Nur wirklich vorhandene Anhaenge und Fundstellen zitieren.",
        "13. Die Original-TP-Dashboard-Sammel-CSV wird wegen "
        "Fahrzeuguebergreifung NICHT ungefiltert in die ZIP kopiert: "
        "die zulassigen FIN-bezogenen Befundzeilen liegen unter diagnose/.",
        "14. Grosse Diagnosetabellen liegen in mehreren CSV-Teilen: "
        "die erste Datei heisst z.B. diagnose/dtc_parameter.csv, "
        "weitere heissen diagnose/dtc_parameter_teil_0002.csv usw. "
        "Das Manifest listet ALLE Teile und ihre Zeilenzahlen unter "
        "diagnose_tabellen auf. Fuer eine vollstaendige Analyse muessen "
        "saemtliche Teile mitgezahlt und ausgewertet werden. "
        "Die Wiederholung des CSV-Headers ist KEINE Diagnosezeile.",
        "15. ZWEI ANALYSEEBENEN - ALLE FAELLE: Ebene A sind GEMELDETE "
        "FEHLERBILDER, Ebene B ist der technische NACHWEISGRAD. "
        "Fuer JEDEN Fall fehlerbilder[] und nachweisprofil[] nach dem "
        "JSON-Schema ausfuellen. Mehrere Fehlerbilder pro Fall sind "
        "ERWUENSCHT. Generische Kategorien sind Stromaufnahme zu "
        "hoch/zu niedrig, Kurzschluss/Sicherung, Bus/Kommunikation, "
        "Versorgung/Masse, Ansteuerung, Leistung/Temperatur, Mechanik, "
        "Feuchte/Korrosion, Sensorik oder Sonstige Symptome. Ohne "
        "zuordenbares Symptom EXPLIZIT 'Unbekannt' statt still leer. "
        "Nur dokumentierte Originalangaben verwenden.",
        "16. FEHLERBILD IST KEINE URSACHE: Jede Fehlerbild-Kategorie "
        "traegt nachweisstatus, sicherheit, begruendung und wirkliche "
        "belege. Eine Werkstattbeanstandung ist 'Werkstattangabe', "
        "kein laborbestaetigter Defekt; ein Pumpen-DTC ist ein "
        "Diagnosehinweis, kein Beweis fuer den Tauschkomponentendefekt. "
        "QEC-/SSL-/NTF-Endlabels und behauptete Lieferantenschuld NIE "
        "als Clustermerkmal oder Kausalnachweis einsetzen. "
        "Nachweisprofil separat aus den vorhandenen Quellen ableiten.",
        "17. KEINE FORCIERTE TECHNISCHE URSACHENCLUSTERUNG: Txx "
        "nur bei positiven fallbezogenen technischen Indizien; "
        "andere Faelle IMMER Sxx nach gemeldetem Symptom oder "
        "expliziter Datenlage/Prozessart zuordnen. Jeder Fall hat "
        "genau EINE T- oder S-cluster_id, keine null-Zuordnungen. "
        "Mehrere fehlerbilder[] sind zulaessig. S ist niemals "
        "gleichbedeutend mit einem belegten Defekt oder Verursacher. "
        "Alle vier Dimensionen (T/S-Aehnlichkeit, Fehlerbild, "
        "Nachweisbasis, Ursachenbereich) getrennt bewerten.",
        "18. QUICKTESTS AM TAUSCHTAG NICHT IGNORIEREN: "
        "diagnose/quicktest_fallbezug.csv enthaelt km_quicktest, "
        "km_tausch, km_differenz_zum_tausch und zeitliche_sicherheit. "
        "gleicher_tag_km_vor_tausch_indiz bedeutet einen plausiblen "
        "Vortausch-KANDIDATEN, NICHT einen bewiesenen Vortausch-QT. "
        "gleicher_tag_km_nach_tausch_indiz ist ein Nachtausch-Indiz. "
        "Gleiches Datum und gleicher/fehlender km-Stand bleibt "
        "zeitlich_unklar_gleicher_tag. datum_km_widerspruch gesondert "
        "als ungeklärt behandeln. Ohne originale QEC-Tausch-Uhrzeit "
        "keine Chronologie behaupten. Niemals pauschal "
        "'kein Vortausch-QuickTest' behaupten, wenn ein taggleicher "
        "plausibler Kandidat vorhanden ist: seine km-Werte und "
        "die Unsicherheit nennen.",
        "19. FAELLE VOLLSTAENDIG UND OHNE ERFUNDENE BELEGE: "
        "auch am Tauschtag vorliegende QuickTests mit DTCs beruecksichtigen. "
        "DTCs koennen andere Pumpen/ECUs/Baugruppen betreffen. Ein "
        "historisch gespeicherter DTC nach Tausch ist ohne neuen "
        "Ereignis-km/Loeschhistorie KEIN Wiederkehrbeweis. "
        "Datenluecken getrennt ausweisen, statt Faelle auszuschliessen.",
        "20. VERBINDLICHER RUECKGABEVERTRAG: Nur das JSON-Schema "
        "chatgpt_ergebnis_schema.json im WURZELVERZEICHNIS dieser "
        "zweiten ZIP verwenden, niemals das historisch beigefuegte "
        "basis/chatgpt_ergebnis_schema.json. Die erlaubten "
        "Feldnamen, Fehlerbild-Kategorien und Nachweisprofil-Werte "
        "wortgetreu aus den JSON-Schema-Enums uebernehmen. "
        "Keine zusaetzlichen Fallattribute erfinden. Bei Belegen "
        "quelle=qec_felder die fundstelle EXAKT aus der Spalte "
        "fundstelle in basis/qec_felder.csv verwenden, ohne "
        "nachtraegliche [Feldnamen]-Ergaenzungen. "
        "Die Felder fehlerbild_methodik und cluster_abdeckung aus "
        "der Ergebnisvorlage unveraendert beibehalten.",
        "21. VOLLSTAENDIGE T/S-ABDECKUNG: JEDER exportierte QEC-Fall "
        "muss genau einer cluster_id zugeordnet sein; null ist in "
        "Runde 2 nicht mehr erlaubt. Txx bezeichnet technische "
        "Aehnlichkeitscluster mit konkreten Belegen (DTC, ECU, "
        "Originalbefund). Wenn das nicht begruendbar ist, den Fall "
        "einem Sxx-Cluster fuer ein vergleichbares GEMELDETES "
        "Symptom oder eine explizite Datenlage-/Prozessgruppe zuordnen. "
        "Nicht belegte Symptome niemals erfinden. Alle cluster[] "
        "haben ebene='T' oder ebene='S' entsprechend ihrer ID. "
        "S-Cluster sind KEIN Ursachenbeweis und begruenden niemals "
        "automatisch Lieferantenverantwortung. In S-Gruppen "
        "cluster_typ, evidenzklasse, abgrenzung und Original-Fundstellen "
        "dokumentieren. In faelle[] muss cluster_id auf genau eine "
        "existierende T- oder S-Gruppe verweisen. Ergebnis: "
        "Anzahl aller T- und S-Mitglieder == Anzahl QEC-Faelle."
    ]
    # Diese neutralen Zusatzanforderungen bleiben unabhaengig vom
    # CSV-Groesstdaten-Fix im separaten PR #60.
    instruction_lines.extend([
        "ZUSATZAUFTRAG T/S-CLUSTER: Untersuche ALLE Faelle auf technische "
        "und symptomatische Aehnlichkeit. Txx nur fuer belegbasierte "
        "technische Muster aus DTC/ECU/Fehlerbedingungen/Originalbefunden. "
        "Wenn das nicht vorliegt: Sxx nach Werkstatt-Meldebild, "
        "Leistungs-/Temperaturhinweis oder explizit unzureichender "
        "Datenlage; gleiche Reparaturanweisung ist kein technischer "
        "Fehlermechanismus. JEDER Fall muss in genau einer T- oder "
        "S-Gruppe sein. Auch Unbekannt/Datenlage unzureichend darf "
        "in eine S-Gruppe. Nie kuenstlich T, nur um 100 Prozent "
        "zu erreichen. Weder QEC-/NTF-/SSL-Labels noch gemeinsame "
        "FIN beweisen eine Ursache. Je Cluster ebene, cluster_id, "
        "titel, fall_ids, technische_hypothese (bei S nur als "
        "vorsichtige Arbeitshypothese), sicherheit, belege, "
        "cluster_typ, evidenzklasse, abgrenzung und empfohlene_pruefung "
        "ausfuellen. Die Ergebnisdatei hat nur EIN gemeinsames "
        "cluster[] und faelle[] ohne getrennte Zusatzdatei.",
        "ZUSATZAUFTRAG VERURSACHUNG: Fuer jeden Fall verursachungsbereich "
        "(Bauteil/Lieferant, Ansteuerung/ECU, Kommunikation, Bordnetz, "
        "Leitung/Stecker, Einbau/Montage/Werkstatt oder Nicht zuordenbar), "
        "sicherheit_zuordnung, begruendung_zuordnung, ursachenhypothese, "
        "klaerung_durch, naechster_schritt und belege ausfuellen. "
        "Gegenbeweise und Alternativhypothesen auffuehren. Eine "
        "Lieferantenverantwortung niemals aus QEC-/NTF-/SSL-Labels, "
        "Clusterhaeufigkeit oder einem DTC allein behaupten.",
        "ZUSATZAUFTRAG WIEDERKEHR: fehlerwiederkehr exakt einer von "
        "'Nach Tausch erneut nachgewiesen', 'Hinweise auf Wiederkehr', "
        "'Kein erneuter Fehler im dokumentierten Nachtest' oder "
        "'Nicht beurteilbar'. begruendung_fehlerwiederkehr mit belegtem "
        "Tauschanker, Diagnosezeitpunkt, DTC-Code und Fundstelle "
        "befuellen. Ohne echten Nachtest niemals Fehlerfreiheit behaupten.",
        "ZUSATZAUFTRAG GESAMTAUSWERTUNG: Zweite Runde ist die umfassende "
        "technische NTF-Neubewertung. Pro Fall beweise und Gegenindizien, "
        "Verursachungssicherheit, Grenzen und priorisierte Pruefungen "
        "angeben; Abweichungen zur ersten Runde begruenden. "
        "Alle Fallpseudonyme genau einmal auswerten.",
    ])
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
        "ausgewaehlte_fahrzeuge": len(scope.fins) if scope else None,
        "ausgewaehlte_qec_faelle": len(scope.cases) if scope else None,
        "relevante_ecus_konfiguriert": (
            list(project.ecu_names) if project is not None else []
        ),
        "sachnummer_wurde_lokal_gefiltert": project_scoped,
        "fehlerbild_methodik": "multilabel_symptom_nachweis_v2",
        "cluster_abdeckung": "T_S_v1",
        "cluster_semantik": (
            "T = technische Aehnlichkeit; S = Symptom/Prozess/Datenlage; "
            "alle Faelle genau einmal, keine Ursache aus S ableiten"
        ),
        "quicktest_zeitrelation": "datum_plus_km_indiz_ohne_tausch_uhrzeit",
        "unterlagen_nach_sachnummer_zugeordnet": bool(part_number.strip()),
        "basis_nicht_nach_sachnummer_gefiltert": not project_scoped,
        "erster_chatgpt_durchlauf": {
            "enthalten": verified_result is not None,
            "analyse_id": verified_result.analyse_id if verified_result else None,
        },
        "analyse_id_zweiter_durchlauf": analysis_id,
        "inhalt_originaldateien": include_originals,
        "vertrauliche_basis_gesondert_freigegeben": include_confidential_basis,
        "technischer_exportmodus": (
            "projektbezogen_strukturiert_mit_pdf_fallback"
            if project_scoped else "legacy_ungefiltert"
        ),
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
            if (
                not base_manifest.get("pseudonymisiert", False)
                and not include_confidential_basis
            ):
                raise ValueError(
                    "Die erste LLM-Basis enthält vertrauliche QEC-Texte "
                    "oder QEC-Originale. Bitte die getrennte Freigabe "
                    "'Vertrauliche erste QEC-Basis übernehmen' aktivieren."
                )
            for index, info in enumerate(infos, 1):
                if progress:
                    progress(f"KI-Basis kopieren: {index}/{len(infos)}")
                # Bereits pseudonymisierte Daten und gegebenenfalls vom Nutzer
                # freigegebene Originale der Basis exakt und ohne Umbenennung erhalten.
                if (
                    not include_confidential_basis
                    and info.filename.startswith("qec_originale/")
                ):
                    raise ValueError(
                        "Die erste QEC-Basis enthält Originalbelege; "
                        "hierfür ist eine gesonderte QEC-Basisfreigabe erforderlich."
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
            followup_template["cluster_abdeckung"] = "T_S_v1"
            # Kennzeichnet das NEUE zweite Ergebnis; beim Import werden
            # damit Fehlerbild und Nachweisgrad je QEC-Fall verlangt.
            followup_template["fehlerbild_methodik"] = (
                "multilabel_symptom_nachweis_v2"
            )
            _zip_text(
                archive, "chatgpt_ergebnis_vorlage.json",
                json.dumps(followup_template, ensure_ascii=False, indent=2),
            )
            # Runde 2 hat einen eigenen, streng typisierten Vertrag.
            # Das Schema der archivierten QEC-Erstrunde kann aelter sein
            # und darf nicht im Widerspruch zur neuen Vorlage stehen.
            _zip_text(
                archive, "chatgpt_ergebnis_schema.json",
                json.dumps(
                    ergebnis_schema(), ensure_ascii=False, indent=2,
                ),
            )
            if verified_result is not None:
                _zip_text(
                    archive, "voranalyse/erstes_chatgpt_ergebnis.json",
                    verified_result.model_dump_json(indent=2, exclude_none=True),
                )
            if scope is not None:
                table_files: dict[str, list[dict]] = {}
                if progress:
                    progress(
                        "Diagnosis-Viewer-QuickTests, ECUs und DTCs "
                        "sachnummernbezogen aus Parserdaten exportieren ..."
                    )
                diagnosis_stats, _source_shas = export_parsed_diagnostics(
                    archive, store.store, scope,
                    include_fulltext=include_originals, progress=progress,
                    table_files=table_files,
                )
                if progress:
                    progress(
                        "TP-Dashboard- und TIPS-Quelldaten nach FIN filtern ..."
                    )
                tp_stats = export_tp_filtered(
                    archive, store.store, scope, progress=progress,
                    table_files=table_files,
                )
                tips_stats = export_tips_filtered(
                    archive, store.store, scope,
                    include_fulltext=include_originals,
                    progress=progress, table_files=table_files,
                )
                manifest["diagnose_tabellen"] = table_files
                manifest["diagnose_auszug"] = {
                    **diagnosis_stats, **tp_stats, **tips_stats,
                    "originale_projektdateien": len(planned_originals),
                    "nicht_aufgenommene_unterlagen": sum(
                        not item["original_aufgenommen"]
                        for item in files_manifest
                    ),
                }
                manifest["diagnose_hinweis"] = (
                    "QuickTests/TP sind FIN-bezogene Gesamtfahrzeugdaten. "
                    "Keine bewiesene Bauteilverursachung. Projektbelege "
                    "sind manuell zugeordnet; fremde FINs innerhalb "
                    "unstrukturierter Dateien sind nicht sicher ausgeschlossen. "
                    "Parsertexte sind NICHT garantiert anonymisiert."
                )
                _zip_text(
                    archive, "diagnose/LESEHINWEISE.txt",
                    "NTF INSIGHT / DIAGNOSEDATEN DER VERTIEFUNG\n\n"
                    "Erstes QEC-Paket: basis/; erster KI-Befund: voranalyse/.\n"
                    "Diagnosis-Viewer-QuickTests: quicktests.csv. "
                    "Dazu ECU-Staende, DTC-Beobachtungen, DTC-Parameter, "
                    "geparste Seitentexte (nur nach Freigabe) und "
                    "Fall-Zeitvergleiche im Ordner diagnose/.\n"
                    "Berichtspseudonym QTnnnnnn ist NUR lokal fuer diese "
                    "zweite ZIP. QEC-Fall Fnnnn und Fahrzeug Vnnnn stammen "
                    "aus der ersten QEC-Basis.\n"
                    "Die VIN-gefilterten TP-Dashboard-Tabellen liegen "
                    "unter diagnose/tp_dashboard_*.csv. TIPS-Writer-Auswertung "
                    "liegt unter diagnose/tips_writer.csv.\n"
                    "Grosse Tabellen werden NICHT abgeschnitten, sondern "
                    "in CSV-Teile aufgeteilt: nach dem ersten Dateinamen "
                    "folgen gleichnamige Dateien mit _teil_0002.csv, "
                    "_teil_0003.csv usw. Der Index diagnose_tabellen "
                    "in cluster_kontext_manifest.json enthaelt alle "
                    "Dateinamen und Zeilenzahlen. ALLE Teile auswerten.\n"
                    "Originale aus Schritt 04 und ungeparste QT-PDFs liegen "
                    "nach Freigabe unter unterlagen/. Sie sind nicht "
                    "automatisch anonymisiert. Das Manifest dokumentiert "
                    "auch ausgelassene / mehrdeutige Dateien.\n"
                    "Quellen sind fahrzeugbezogen, nicht zwingend "
                    "schadteilursachlich. Fallzuordnungen zu Diagnose-"
                    "Zeitpunkten nur mit belegtem QEC-Tauschanker auswerten.\n"
                    "Als Beleg in JSON quelle=technische_referenz und "
                    "fundstelle='diagnose/<datei>.csv/Zeile...' bzw. "
                    "'unterlagen/<kategorie>/<datei> Seite...' verwenden.\n"
                    "Nicht durch andere Sachnummern oder Fremd-FINs "
                    "ergaenzen. Fehlende Dokumente sind zulaessig.\n"
                )
            if include_originals:
                if scope is not None:
                    # Exakt nach Profil/Sachnummer geplante Projektdateien
                    # sowie nur ungeparste PDF-Fallbacks.
                    total_originals = len(planned_originals)
                    for index, original in enumerate(planned_originals, 1):
                        if progress:
                            progress(
                                f"Technische Unterlagen beifuegen "
                                f"({index}/{total_originals}) ..."
                            )
                        path = original.path
                        if (
                            path.is_symlink() or not path.is_file()
                            or path.stat().st_size > MAX_EVIDENCE_BYTES
                        ):
                            raise ValueError(
                                "Technische Originaldatei nicht mehr verfuegbar."
                            )
                        # Datenhaltung im Roharchiv ODER FIN-bezogenes
                        # Downloadverzeichnis; keine fremden Dateipfade.
                        raw_root = store.archive.root.resolve()
                        quick_root = store.store.path.parent.joinpath(
                            "quicktests"
                        ).resolve()
                        tips_root = store.store.path.parent.joinpath(
                            "tips"
                        ).resolve()
                        if not (
                            path.resolve().is_relative_to(raw_root)
                            or (
                                original.category == "diagnosis_viewer_fallback"
                                and path.resolve().is_relative_to(quick_root)
                            )
                            or (
                                original.category in {
                                    "tips_writer_fall", "tips_writer_anhang",
                                }
                                and path.resolve().is_relative_to(tips_root)
                            )
                        ):
                            raise ValueError(
                                "Original liegt ausserhalb der erlaubten "
                                "projektbezogenen Quellverzeichnisse."
                            )
                        with path.open("rb") as original_file:
                            total_bytes += _copy_member(
                                original_file, archive, original.zip_path,
                                expected_sha=original.sha256,
                            )
                        if total_bytes > MAX_PACKAGE_BYTES:
                            raise ValueError("Export ueberschreitet 1 GiB.")
                else:
                    raw_root = store.archive.root.resolve()
                    for index, (original, meta) in enumerate(
                        zip(evidence, files_manifest), 1,
                    ):
                        if progress:
                            progress(
                                f"Fachunterlagen einfuegen: {index}/{len(evidence)}"
                            )
                        path = original.source_path
                        if (
                            path.is_symlink() or not path.is_file()
                            or not path.resolve().is_relative_to(raw_root)
                            or path.stat().st_size > MAX_EVIDENCE_BYTES
                        ):
                            raise ValueError("Fachunterlage ungueltig.")
                        with path.open("rb") as source:
                            total_bytes += _copy_member(
                                source, archive, meta["datei_im_paket"],
                                expected_sha=original.sha256,
                            )
                        if total_bytes > MAX_PACKAGE_BYTES:
                            raise ValueError("Export ueberschreitet 1 GiB.")
            if sum(item.file_size for item in archive.infolist()) > MAX_PACKAGE_BYTES:
                raise ValueError("Zweiter LLM-Export ueberschreitet 1 GiB.")
            _zip_text(
                archive, "cluster_kontext_manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            _zip_text(archive, "CHATGPT_2_DURCHLAUF.txt", instructions)
        if destination.exists():
            raise FileExistsError("Zieldatei wurde inzwischen angelegt.")
        os.replace(temp, destination)
        if progress:
            progress("Zweites LLM-Paket vollständig gespeichert.")
    finally:
        temp.unlink(missing_ok=True)
    return ClusterContextExport(
        path=destination,
        parent_package_id=package_id,
        category_count=sum(value > 0 for value in counts.values()),
        file_count=len(evidence),
        included_files=(
            len(planned_originals) if scope is not None
            else len(evidence) if include_originals else 0
        ),
        analysis_id=analysis_id,
    )
