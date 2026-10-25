"""Versionierter LLM-Rückgabe-Vertrag für NTF-/QEC-Fallbewertungen.

Die Antwort aus einem externen Analysemodell bleibt eine überprüfbare Hypothese,
kein automatischer Ersatz für QEC-Entscheidungen oder manuelle Fallbewertungen.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal
from zipfile import BadZipFile, ZipFile

import duckdb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ntf_insight.reporting.llm2_legacy_detail import normalize_legacy_llm2_detail
from ntf_insight.storage.duckdb_store import DuckDBStore

FORMAT = "ntf-insight-chatgpt-rueckgabe"
SCHEMA_VERSION = 1
MAX_JSON_SIZE = 16 * 1024 * 1024
_PAKET_ID = re.compile(r"[0-9a-f]{32}\Z")
_IDENT = re.compile(r"[A-Za-z0-9_.:\-]{1,90}\Z")
_PSEUDONYM = re.compile(r"(?:F[0-9]{4,6}|V[0-9]{4,6}|Q[0-9]{5,7}|QT[0-9]{5,7})\Z")
_REVIEW = {"Offen", "Bestätigt", "Abgelehnt"}

BelegQuelle = Literal[
    "qec_berichte", "qec_felder", "qec_dokumente", "quicktests",
    "dtc_beobachtungen", "ecu_staende", "tips", "technische_referenz",
    "autoexport_diagnosen", "werkstatt_historie", "autoexport_tips",
    "pumpentausch_historie", "fall_ereignisse", "ecu_versionshistorie",
    "diagnose_qualitaet", "lieferantenbefunde_NICHT_CLUSTER",
    "lieferantenquellen_bestand_NICHT_CLUSTER",
]
Bewertung = Literal[
    "NTF plausibel", "NTF fraglich", "Kein reiner NTF",
    "Nicht bewertbar", "Nicht zuordenbar", "Nicht bewertet",
]
Sicherheit = Literal["Hoch", "Mittel", "Niedrig", "Offen"]
Zuordnung = Literal["Belegt", "Plausibel", "Offen"]
Prioritaet = Literal["P1", "P2", "P3", "Offen"]
Wiederkehr = Literal[
    "Nach Tausch erneut nachgewiesen",
    "Hinweise auf Wiederkehr",
    "Kein erneuter Fehler im dokumentierten Nachtest",
    "Nicht beurteilbar",
]


class ChatGPTBeleg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quelle: BelegQuelle
    quelle_id: str = Field(default="", max_length=90)
    fundstelle: str = Field(default="", max_length=500)
    aussage: str = Field(default="", max_length=1800)
    belegstatus: Literal[
        "Originalbefund", "Abgeleitet", "Nicht verifiziert",
    ] = "Nicht verifiziert"


FehlerbildKategorie = Literal[
    "Stromaufnahme zu hoch / Überstrom",
    "Stromaufnahme zu niedrig / fehlender Strom",
    "Stromaufnahme unplausibel (hoch/niedrig)",
    "Kurzschluss / Sicherung",
    "Bus / Kommunikation",
    "Versorgung / Spannung / Masse",
    "Ansteuerung / Software / Regelung",
    "Leistung / Funktion / Temperatur",
    "Mechanik / Geräusch / Beschädigung",
    "Feuchte / Korrosion / Abdichtung",
    "Sensorik / Signal",
    "Sonstige Symptome",
    "Unbekannt",
]
FehlerbildNachweis = Literal[
    "Werkstattangabe", "Diagnostisch belegt",
    "Laborbefund", "Mehrfach belegt", "Hypothese / unbestätigt",
]
NachweisProfil = Literal[
    "Werkstattangabe vorhanden",
    "Diagnose vor Tausch (Datum)",
    "Diagnose am Tauschtag (km-Indiz vor)",
    "Diagnose am Tauschtag (km-Indiz nach)",
    "Diagnose am Tauschtag (Reihenfolge offen)",
    "Diagnose nach Tausch (Datum)",
    "Zeitrelation widersprüchlich",
    "Laborfehler reproduziert",
    "Laborfehler nicht reproduziert",
    "Laborbefund optisch auffällig",
    "Datenlage unzureichend",
]


class LLMFehlerbild(BaseModel):
    """Mehrfachnennung eines SYMPTOMS; kein automatischer Verursachernachweis."""

    model_config = ConfigDict(extra="forbid")
    kategorie: FehlerbildKategorie
    nachweisstatus: FehlerbildNachweis = "Hypothese / unbestätigt"
    sicherheit: Sicherheit = "Offen"
    begruendung: str = Field(default="", max_length=1800)
    belege: list[ChatGPTBeleg] = Field(default_factory=list, max_length=15)


class ChatGPTFall(BaseModel):
    """Spalten aus der gelieferten QEC-Auswertung; IDs sind pseudonymisiert."""

    model_config = ConfigDict(extra="forbid")
    fall_id: str = Field(max_length=20)
    cluster_id: str | None = Field(default=None, max_length=90)
    ntf_bewertung: Bewertung = "Nicht bewertet"
    prioritaet: Prioritaet = "Offen"
    befund: str = Field(default="", max_length=4000)
    verursachungsbereich: str = Field(default="Nicht zuordenbar", max_length=150)
    sicherheit_zuordnung: Zuordnung = "Offen"
    begruendung_zuordnung: str = Field(default="", max_length=4000)
    begruendung_ntf: str = Field(default="", max_length=4000)
    ursachenhypothese: str = Field(default="", max_length=4000)
    klaerung_durch: str = Field(default="", max_length=1200)
    naechster_schritt: str = Field(default="", max_length=2400)
    pruefungen_grenzen: str = Field(default="", max_length=3000)
    weitere_auffaelligkeiten: str = Field(default="", max_length=2500)
    # Optional fuer alte Runde-1-/Legacy-JSON: vollstaendige Vor-/Nach-
    # Tausch-Pruefung erfolgt erst in Runde 2 mit gesicherten Zeitankern.
    fehlerwiederkehr: Wiederkehr = "Nicht beurteilbar"
    begruendung_fehlerwiederkehr: str = Field(default="", max_length=2400)
    sicherheit_bewertung: Sicherheit = "Offen"
    themen: list[str] = Field(default_factory=list, max_length=30)
    # Ebene 1: alle Faelle haben ein oder mehrere, auch nur gemeldete,
    # Fehlerbilder; Multi-Label, unabhaengig von exklusiver cluster_id.
    # Ebene 2: Herkunft/Abdeckung ist getrennt von der Ursache bewertet.
    # Optional fuer alte erste/zweite LLM-JSONs.
    fehlerbilder: list[LLMFehlerbild] = Field(default_factory=list, max_length=15)
    nachweisprofil: list[NachweisProfil] = Field(default_factory=list, max_length=12)
    belege: list[ChatGPTBeleg] = Field(default_factory=list, max_length=40)
    symptomcluster_begruendung: str = Field(default="", max_length=3500)


class ChatGPTCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cluster_id: str = Field(max_length=90)
    titel: str = Field(default="", max_length=180)
    fall_ids: list[str] = Field(min_length=1, max_length=5000)
    technische_hypothese: str = Field(default="", max_length=4000)
    sicherheit: Sicherheit = "Offen"
    belege: list[ChatGPTBeleg] = Field(default_factory=list, max_length=40)
    ebene: Literal["T", "S"] | None = None
    cluster_typ: str = Field(default="", max_length=180)
    evidenzklasse: str = Field(default="", max_length=1000)
    abgrenzung: str = Field(default="", max_length=2000)
    empfohlene_pruefung: str = Field(default="", max_length=2000)


class ChatGPTRueckgabe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["ntf-insight-chatgpt-rueckgabe"] = FORMAT
    schema_version: Literal[1] = SCHEMA_VERSION
    paket_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    analyse_id: str = Field(max_length=90)
    analyse_id_vorher: str | None = Field(default=None, max_length=90)
    cluster_abdeckung: Literal["T_S_v1"] | None = None
    # Nur der NEUE LLM2-Export setzt diese optionale Markierung. Alte
    # JSONs und LLM1 bleiben unveraendert kompatibel.
    fehlerbild_methodik: Literal["multilabel_symptom_nachweis_v2"] | None = None
    clustermethode: str = Field(default="", max_length=800)
    verwendete_merkmale: list[str] = Field(default_factory=list, max_length=70)
    unsicherheiten: list[str] = Field(default_factory=list, max_length=50)
    cluster: list[ChatGPTCluster] = Field(default_factory=list, max_length=500)
    faelle: list[ChatGPTFall] = Field(min_length=1, max_length=10000)


def ergebnis_vorlage(paket_id: str) -> dict:
    """The same skeleton is embedded into each export ZIP and can be returned."""
    if not _PAKET_ID.fullmatch(paket_id):
        raise ValueError("Ungültige Analysepaketkennung.")
    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "paket_id": paket_id,
        "analyse_id": "Analyse-" + paket_id[:12] + "-01",
        "cluster_abdeckung": None,
        "clustermethode": "",
        "verwendete_merkmale": ["Vor-Tausch-DTCs; keine NTF-/SSL-Ergebnis-Labels"],
        "unsicherheiten": [],
        "cluster": [],
        "faelle": [],
    }


def ergebnis_schema() -> dict:
    return ChatGPTRueckgabe.model_json_schema()


def _csv_private_mapping(csv_path: Path, paket_id: str) -> list[dict]:
    path = Path(csv_path)
    if not path.is_file() or path.stat().st_size > 15 * 1024 * 1024:
        raise ValueError("Lokale NICHT_HOCHLADEN-Zuordnung fehlt oder ist zu groß.")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "paket_id", "art", "pseudonym", "fin", "fall_id_original",
            "qec_referenz_original", "sachnummer_original", "quelle_id_original",
        }
        if not required.issubset(set(reader.fieldnames or ())):
            raise ValueError(
                "Die private Zuordnungs-CSV hat nicht das neue, paketgebundene Format."
            )
        rows = list(reader)
    if not rows or len(rows) > 100_000:
        raise ValueError("Private Zuordnung ist leer oder zu groß.")
    if any(row["paket_id"] != paket_id for row in rows):
        raise ValueError(
            "Paketkennung der privaten Zuordnung stimmt nicht mit dem LLM-Ergebnis überein."
        )
    return rows


class ChatGPTAnalyseStore:
    """Keep original case data and external analysis physically separate."""

    def __init__(self, store: DuckDBStore) -> None:
        self.store = store
        with self.store.connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chatgpt_export_mapping (
                    paket_id VARCHAR NOT NULL,
                    art VARCHAR NOT NULL,
                    pseudonym VARCHAR NOT NULL,
                    original_id VARCHAR NOT NULL,
                    fin VARCHAR,
                    qec_reference VARCHAR,
                    PRIMARY KEY (paket_id, art, pseudonym)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chatgpt_imports (
                    analyse_id VARCHAR PRIMARY KEY,
                    paket_id VARCHAR NOT NULL,
                    sha256 VARCHAR NOT NULL,
                    importiert_am TIMESTAMP NOT NULL,
                    original_json VARCHAR NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chatgpt_cluster (
                    analyse_id VARCHAR NOT NULL,
                    cluster_id VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL,
                    PRIMARY KEY (analyse_id, cluster_id)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS chatgpt_fallanalysen (
                    analyse_id VARCHAR NOT NULL,
                    case_id VARCHAR NOT NULL,
                    fall_pseudonym VARCHAR NOT NULL,
                    cluster_id VARCHAR,
                    payload_json VARCHAR NOT NULL,
                    review_status VARCHAR NOT NULL DEFAULT 'Offen',
                    reviewed_at TIMESTAMP,
                    PRIMARY KEY (analyse_id, case_id)
                )
            """)

    def save_mapping(self, paket_id: str, rows: list[dict]) -> None:
        if not _PAKET_ID.fullmatch(paket_id):
            raise ValueError("Ungültige Paketkennung.")
        items: list[tuple] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if row.get("paket_id") != paket_id:
                raise ValueError("Private Zuordnung enthält eine falsche Paketkennung.")
            art = str(row.get("art") or "")
            pseudo = str(row.get("pseudonym") or "")
            if art not in {
                "fahrzeug", "fall", "qec_bericht", "quicktest", "teil",
                "quelle", "tips_ref", "lieferant", "seriennummer", "charge",
            }:
                raise ValueError("Unbekannter privater Zuordnungstyp.")
            if not _IDENT.fullmatch(pseudo):
                raise ValueError("Ungültiges Pseudonym in der privaten Zuordnung.")
            key = (art, pseudo)
            if key in seen:
                raise ValueError("Doppelte Zuordnung im Analysepaket.")
            seen.add(key)
            original = (
                str(row.get("fall_id_original") or "")
                if art == "fall"
                else str(row.get("quelle_id_original") or "")
                if art in {"quicktest", "qec_bericht"}
                else str(row.get("fin") or "")
                if art == "fahrzeug"
                else str(row.get("sachnummer_original") or "")
                if art == "teil" else str(row.get("original_wert") or "")
            )
            if not original:
                raise ValueError("Leere Originalkennung in der privaten Zuordnung.")
            items.append((
                paket_id, art, pseudo, original,
                str(row.get("fin") or ""),
                str(row.get("qec_referenz_original") or ""),
            ))
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                existing = con.execute(
                    "SELECT COUNT(*) FROM chatgpt_export_mapping WHERE paket_id=?",
                    [paket_id],
                ).fetchone()[0]
                if existing:
                    raise ValueError("Analysepaket-Kennung ist bereits lokal registriert.")
                con.executemany(
                    "INSERT INTO chatgpt_export_mapping VALUES (?,?,?,?,?,?)", items,
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise

    def _mapping(self, paket_id: str, private_csv: Path | None) -> dict[tuple[str, str], dict]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT art,pseudonym,original_id,fin,qec_reference "
                "FROM chatgpt_export_mapping WHERE paket_id=?",
                [paket_id],
            ).fetchall()
        if rows:
            return {
                (art, pseudo): {
                    "art": art, "pseudonym": pseudo, "original": original,
                    "fin": fin, "qec_referenz": reference,
                }
                for art, pseudo, original, fin, reference in rows
            }
        if private_csv is None:
            raise ValueError(
                "Paketzuordnung nicht in DuckDB gefunden. "
                "Bitte die lokale Datei *_NICHT_HOCHLADEN_ZUORDNUNG.csv wählen."
            )
        csv_rows = _csv_private_mapping(private_csv, paket_id)
        result: dict[tuple[str, str], dict] = {}
        for row in csv_rows:
            art, pseudo = row["art"], row["pseudonym"]
            key = (art, pseudo)
            if key in result:
                raise ValueError("Doppelte private Paketzuordnung.")
            original = (
                row["fall_id_original"] if art == "fall"
                else row["quelle_id_original"] if art in {"quicktest", "qec_bericht"}
                else row["fin"] if art == "fahrzeug"
                else row["sachnummer_original"] if art == "teil"
                else row.get("original_wert", "")
            )
            result[key] = {
                "art": art, "pseudonym": pseudo, "original": original,
                "fin": row["fin"], "qec_referenz": row["qec_referenz_original"],
            }
        return result

    _ROW_EVIDENCE = {
        "autoexport_diagnosen": (
            "autoexport_diagnosen.csv", "beobachtung_id", r"AE[0-9]{7}"
        ),
        "lieferantenbefunde_NICHT_CLUSTER": (
            "lieferantenbefunde_NICHT_CLUSTER.csv", "befund_id", r"LB[0-9]{6}"
        ),
    }

    def _validate_export_rows(
        self, paket_id: str, requested: dict[str, set[str]],
    ) -> dict[str, set[str]]:
        """Belegzeilen nur gegen das *unveränderte* exportierte ZIP prüfen.

        AE... und LB... sind CSV-Zeilenbezeichner, keine Alias-Typen
        der privaten FIN-Zuordnung. Insbesondere LB... ist KEIN Fall-Pseudonym.
        """
        if not requested:
            return {}
        try:
            with self.store.connect() as con:
                row = con.execute(
                    "SELECT a.payload_json,f.sha256 "
                    "FROM workflow_first_ai_packages f "
                    "JOIN source_artifacts a ON a.sha256=f.sha256 "
                    "WHERE f.paket_id=? ORDER BY f.registered_at DESC LIMIT 1",
                    [paket_id],
                ).fetchone()
        except duckdb.CatalogException:
            # Standalone-Rückimport ohne einen registrierten Workflow-Export.
            row = None
        if row is None:
            raise ValueError(
                "Zur Prüfung der AE-/LB-Belegzeilen fehlt das ursprünglich "
                "exportierte LLM-Analyse-ZIP im lokalen Projektarchiv. "
                "Bitte den passenden Projektstand bzw. das erste Analysepaket "
                "auf diesem PC wiederherstellen; Belege werden nicht geraten."
            )
        artifact = json.loads(row[0])
        path = Path(artifact["archived_path"])
        if not path.is_file() or path.is_symlink():
            raise ValueError(
                "Das archivierte Analyse-ZIP fehlt. Der Rückimport wurde "
                "zum Schutz der Belegzuordnung abgelehnt."
            )
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != row[1]:
            raise ValueError("Die Prüfsumme des archivierten Analyse-ZIPs stimmt nicht.")
        found: dict[str, set[str]] = defaultdict(set)
        try:
            with ZipFile(path) as archive:
                for category, needed in requested.items():
                    filename, id_column, _ = self._ROW_EVIDENCE[category]
                    with archive.open(filename) as binary:
                        records = csv.DictReader(
                            io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
                        )
                        if id_column not in (records.fieldnames or ()):
                            raise ValueError(
                                f"Exportierte Belegtabelle {filename} ist unvollständig."
                            )
                        for record in records:
                            alias = str(record.get(id_column) or "")
                            if alias in needed:
                                found[category].add(alias)
                            if found[category] == needed:
                                break
        except (BadZipFile, KeyError, UnicodeError) as exc:
            raise ValueError(
                "Das archivierte Analyse-ZIP enthält nicht alle benötigten "
                "CSV-Belegtabellen."
            ) from exc
        for category, needed in requested.items():
            missing = needed - found[category]
            if missing:
                raise ValueError(
                    "Belegzeile ist im ursprünglichen Analyse-ZIP nicht vorhanden: "
                    f"{category}/{sorted(missing)[0]}"
                )
        return found

    def _verify_qec_field_locations(
        self, paket_id: str, references: set[tuple[str, str]],
    ) -> None:
        """Feldbelege aus einem QEC-Erstpaket nur fuer echte ZIP-Fundstellen.

        Das neue QEC-Paket erzwingt feldgenaue Belege. Fuer alte, breiter
        angelegte Analysepakete bleibt die bestehende Legacy-Validierung.
        """
        if not references:
            return
        try:
            with self.store.connect() as con:
                indexed = con.execute(
                    "SELECT a.payload_json,f.sha256 "
                    "FROM workflow_first_ai_packages f "
                    "JOIN source_artifacts a ON a.sha256=f.sha256 "
                    "WHERE f.paket_id=? LIMIT 1",
                    [paket_id],
                ).fetchone()
        except duckdb.CatalogException:
            # Legacy-Standalone-Paket ohne Workflowregister: bestehende
            # QEC-Aliasvalidierung beibehalten.
            return
        if indexed is None:
            # Alte allgemeine Exportpakete muessen nicht registriert sein.
            # Neue Workflow-QEC-Pakete sind automatisch registriert.
            return
        artifact = json.loads(indexed[0])
        path = Path(artifact["archived_path"])
        if not path.is_file() or path.is_symlink():
            raise ValueError("Erstes Analyse-ZIP ist lokal nicht mehr verfuegbar.")
        with path.open("rb") as source:
            digest = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != indexed[1]:
            raise ValueError("Die SHA-256 der ersten QEC-Basis stimmt nicht.")
        try:
            with ZipFile(path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                if manifest.get("analyseumfang") != "workflow_01_02_qec":
                    return
                with archive.open("qec_felder.csv") as source:
                    rows = csv.DictReader(
                        io.TextIOWrapper(
                            source, encoding="utf-8-sig", newline=""
                        )
                    )
                    # Der Feldpfad im CSV ist die verbindliche Identitaet.
                    # Zusatzbezeichnungen (z.B. "[monteurBefund]") sind
                    # nur dann zulaessig, wenn sie EXAKT mit dem im
                    # archivierten Erstpaket enthaltenen Label uebereinstimmen.
                    existing = {
                        (str(item.get("qec_bericht_id") or ""),
                         str(item.get("fundstelle") or "")):
                        str(item.get("original_beschriftung_opt_in") or "")
                        for item in rows
                    }
        except (BadZipFile, KeyError, UnicodeError, ValueError) as exc:
            raise ValueError(
                "QEC-Belegindex im registrierten Erstpaket nicht lesbar."
            ) from exc
        unknown = set()
        for alias, position in references:
            if (alias, position) in existing:
                continue
            # Lesbare QEC-Beleganzeige: exportierter Pfad + [Original-Label].
            # Ohne exakte, nichtleere Beschriftung im archivierten ZIP
            # wird der Beleg weiterhin konsequent zurueckgewiesen.
            labeled = re.fullmatch(r"(.+?) \[([^\[\]\r\n]+)\]", position)
            if labeled:
                origin = (alias, labeled.group(1))
                original_label = existing.get(origin, "")
                if original_label and original_label == labeled.group(2):
                    continue
            unknown.add((alias, position))
        if unknown:
            alias, position = sorted(unknown)[0]
            raise ValueError(
                f"QEC-Feldbeleg nicht im exportierten Original vorhanden: "
                f"{alias}/{position or '[Fundstelle fehlt]'}"
            )

    def _validate_first_round_focus(self, data: ChatGPTRueckgabe) -> None:
        """Neue QEC-Erstrunde darf KEINE Clusteranalyse vorwegnehmen.

        Legacy- und allgemeine Quellenpakete sowie die zweite Runde
        behalten ihre bisherigen kompatiblen Rueckgabeformate.
        """
        if data.analyse_id != ergebnis_vorlage(data.paket_id)["analyse_id"]:
            return
        try:
            with self.store.connect() as con:
                archived = con.execute(
                    "SELECT a.payload_json FROM workflow_first_ai_packages f "
                    "JOIN source_artifacts a ON a.sha256=f.sha256 "
                    "WHERE f.paket_id=? LIMIT 1",
                    [data.paket_id],
                ).fetchone()
        except duckdb.CatalogException:
            return
        if archived is None:
            return
        source_path = Path(json.loads(archived[0])["archived_path"])
        try:
            with ZipFile(source_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
        except (OSError, BadZipFile, ValueError, KeyError) as exc:
            raise ValueError(
                "Erste QEC-Analyse-ZIP fuer die Rundenzuordnung "
                "nicht lesbar."
            ) from exc
        if manifest.get("analysezweck") == "ntf_erstentscheidung_ohne_cluster":
            if (
                data.cluster or data.clustermethode.strip()
                or any(case.cluster_id is not None for case in data.faelle)
            ):
                raise ValueError(
                    "LLM-Durchlauf 1 darf keine Cluster enthalten. "
                    "Bitte cluster=[], clustermethode='' und "
                    "cluster_id=null je Fall liefern. Clusterung erst in Runde 2."
                )
            if any(case.ntf_bewertung == "Nicht bewertet" for case in data.faelle):
                raise ValueError(
                    "Jeder Fall im LLM-Durchlauf 1 benoetigt eine "
                    "NTF-Einstufung. Bei Datenluecken 'Nicht bewertbar' "
                    "oder 'Nicht zuordenbar' verwenden."
                )

    @staticmethod
    def _validate_belege(
        belege: list[ChatGPTBeleg], mapping: dict[tuple[str, str], dict],
        verified_rows: dict[str, set[str]] | None = None,
    ) -> None:
        types = {
            "qec_berichte": "qec_bericht",
            "qec_felder": "qec_bericht",
            "qec_dokumente": "qec_bericht",
            "quicktests": "quicktest",
            "dtc_beobachtungen": "quicktest",
            "ecu_staende": "quicktest",
            "tips": "fall",
            "autoexport_diagnosen": "quelle",
            "werkstatt_historie": "quelle",
            "autoexport_tips": "quelle",
            "ecu_versionshistorie": "quelle",
            "pumpentausch_historie": "fall",
            "fall_ereignisse": "fall",
            "diagnose_qualitaet": "fall",
            "lieferantenbefunde_NICHT_CLUSTER": "fall",
            "lieferantenquellen_bestand_NICHT_CLUSTER": "quelle",
        }
        for item in belege:
            spec = ChatGPTAnalyseStore._ROW_EVIDENCE.get(item.quelle)
            if spec and re.fullmatch(spec[2], item.quelle_id):
                if item.quelle_id not in (verified_rows or {}).get(item.quelle, set()):
                    raise ValueError(
                        f"Belegzeile nicht verifiziert: {item.quelle}/{item.quelle_id}"
                    )
                continue
            if item.quelle == "technische_referenz":
                if not item.fundstelle:
                    raise ValueError("Technischer Beleg braucht eine dokumentierte Fundstelle.")
                continue
            art = types[item.quelle]
            if (art, item.quelle_id) not in mapping:
                raise ValueError(
                    "Beleg referenziert eine nicht vorhandene Paket-Quelle: "
                    f"{item.quelle}/{item.quelle_id}"
                )

    def _validate_ts_revision(self, data: ChatGPTRueckgabe) -> None:
        """Die einmal validierten T-Cluster/NTF-Urteile bei Neuverteilung erhalten."""
        parent = data.analyse_id_vorher
        if parent is None:
            return
        if (data.cluster_abdeckung != "T_S_v1"
                or not _IDENT.fullmatch(parent)
                or parent == data.analyse_id):
            raise ValueError("Neue T/S-Version braucht eine gültige Vorgänger-ID.")
        with self.store.connect() as con:
            linked = con.execute(
                "SELECT 1 FROM workflow_ai_rounds r "
                "JOIN chatgpt_imports i ON i.analyse_id=r.analyse_id "
                "WHERE r.paket_id=? AND r.analyse_id=? "
                "AND r.round_number=2 AND i.paket_id=?",
                [data.paket_id, parent, data.paket_id],
            ).fetchone()
            if not linked:
                raise ValueError("Die vorherige zweite Analyse ist nicht importiert.")
            cases = con.execute(
                "SELECT fall_pseudonym,cluster_id,payload_json "
                "FROM chatgpt_fallanalysen WHERE analyse_id=?",
                [parent],
            ).fetchall()
            clusters = con.execute(
                "SELECT cluster_id,payload_json "
                "FROM chatgpt_cluster WHERE analyse_id=?",
                [parent],
            ).fetchall()
        old_cases = {pseudo: (cid, json.loads(payload))
                     for pseudo, cid, payload in cases}
        updated_cases = {case.fall_id: case for case in data.faelle}
        if not old_cases or set(old_cases) != set(updated_cases):
            raise ValueError("Die neue T/S-JSON muss exakt dieselben Fälle enthalten.")
        old_t = {cid: json.loads(raw) for cid, raw in clusters
                 if cid.startswith("T")}
        new_t = {group.cluster_id: group for group in data.cluster
                 if group.ebene == "T"}
        if set(old_t) != set(new_t):
            raise ValueError("Die bisherigen technischen T-Cluster wurden verändert.")
        for code, old in old_t.items():
            now = new_t[code]
            for field in ("titel", "fall_ids", "technische_hypothese",
                          "sicherheit", "belege"):
                if now.model_dump(mode="json")[field] != old.get(field):
                    raise ValueError(
                        f"Technischer Cluster {code} weicht vom Vorgänger ab."
                    )
        stable = (
            "ntf_bewertung", "prioritaet", "befund", "verursachungsbereich",
            "sicherheit_zuordnung", "begruendung_zuordnung",
            "begruendung_ntf", "ursachenhypothese", "klaerung_durch",
            "naechster_schritt", "pruefungen_grenzen",
            "sicherheit_bewertung", "fehlerwiederkehr",
            "begruendung_fehlerwiederkehr",
        )
        for pseudo, case in updated_cases.items():
            old_id, old = old_cases[pseudo]
            if old_id is not None and old_id.startswith("T"):
                if case.cluster_id != old_id:
                    raise ValueError(
                        f"Technische Fallzuordnung geändert: {pseudo}"
                    )
            elif not case.cluster_id or not case.cluster_id.startswith("S"):
                raise ValueError(
                    f"Nicht technisch belegter Fall braucht S-Cluster: {pseudo}"
                )
            for field in stable:
                before = old.get(field, ChatGPTFall.model_fields[field].default)
                if getattr(case, field) != before:
                    raise ValueError(
                        f"NTF-/Verursacher-/Wiederkehrwert verändert: {pseudo}/{field}"
                    )

    def import_file(
        self, path: Path, *, private_csv: Path | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        """Validate all identities and evidence before an atomic INSERT.

        A case's operational assessment, manual revisions and supplier finding
        are NEVER overwritten by an external model's hypothesis.
        """
        def report(message: str) -> None:
            if progress is not None:
                progress(message)

        report("LLM-Datei prüfen …")
        path = Path(path)
        if path.suffix.casefold() != ".json" or not path.is_file():
            raise ValueError("Bitte eine LLM-Ergebnisdatei im Format .json wählen.")
        if path.stat().st_size > MAX_JSON_SIZE:
            raise ValueError("LLM-Ergebnisdatei ist zu groß.")
        content = path.read_bytes()
        def model_error(exc: ValidationError) -> ValueError:
            details = "; ".join(
                f"{'.'.join(str(x) for x in item['loc'])}: {item['msg']}"
                for item in exc.errors()[:3]
            )
            return ValueError(
                "LLM-Ergebnis entspricht nicht der gültigen Analysevorlage: "
                + details
            )

        try:
            data = ChatGPTRueckgabe.model_validate_json(content)
        except ValidationError as exc:
            # Das zweite ZIP enthielt frueher irrtuemlich das Schema der
            # Erstrunde. Nur das bekannte erweiterte Altdetailformat
            # wird fuer den Import kanonisiert; keine beliebigen Extras.
            try:
                original = json.loads(content)
            except (ValueError, UnicodeDecodeError) as json_exc:
                raise ValueError("LLM-Ergebnis enthält ungültiges JSON.") from json_exc
            try:
                compatible = normalize_legacy_llm2_detail(
                    original,
                    root_fields=set(ChatGPTRueckgabe.model_fields),
                    case_fields=set(ChatGPTFall.model_fields),
                )
            except ValueError as compat_exc:
                raise ValueError(
                    "Altes LLM2-Detailformat nicht importierbar: "
                    + str(compat_exc)
                ) from compat_exc
            if compatible is None:
                raise model_error(exc) from exc
            try:
                data = ChatGPTRueckgabe.model_validate(compatible)
            except ValidationError as compat_exc:
                raise model_error(compat_exc) from compat_exc
        except ValueError as exc:
            raise ValueError("LLM-Ergebnis enthält ungültiges JSON.") from exc
        if not _IDENT.fullmatch(data.analyse_id) or not _PAKET_ID.fullmatch(data.paket_id):
            raise ValueError("Ungültige Paket- oder Analysekennung.")
        # Jedes in künftigen zweiten ZIPs generierte ClusterTS-Ergebnis
        # muss den vollständigen T/S-Vertrag mitführen. Ohne Marker
        # darf ein LLM nicht still 104 Fälle wieder null zuordnen.
        if (data.analyse_id.startswith("ClusterTS-")
                and data.cluster_abdeckung != "T_S_v1"):
            raise ValueError(
                "Das zweite LLM-Paket verlangt T/S-Abdeckung aller Fälle; "
                "cluster_abdeckung=T_S_v1 fehlt."
            )
        report("Lokale Paket- und FIN-Zuordnung prüfen …")
        mapping = self._mapping(data.paket_id, private_csv)
        source_sha = hashlib.sha256(content).hexdigest()
        with self.store.connect() as con:
            old = con.execute(
                "SELECT sha256 FROM chatgpt_imports WHERE analyse_id=?", [data.analyse_id],
            ).fetchone()
        if old:
            if old[0] == source_sha:
                return {"analyse_id": data.analyse_id, "faelle": len(data.faelle),
                        "cluster": len(data.cluster), "bereits_importiert": True}
            raise ValueError(
                "Analyse-ID ist bereits mit anderem Inhalt gespeichert. "
                "Für eine neue Version bitte eine neue analyse_id vergeben."
            )
        self._validate_first_round_focus(data)

        case_by_alias: dict[str, str] = {}
        for (art, pseudo), row in mapping.items():
            if art != "fall":
                continue
            original_id = row["original"]
            case = self.store.get_case(original_id)
            if (case is None or case.vin != row["fin"]
                    or str(getattr(case, "qec_reference", "") or "") != row["qec_referenz"]):
                raise ValueError(
                    "Lokale Fallzuordnung ist veraltet oder widersprüchlich; "
                    "Import wird ohne Änderungen abgebrochen."
                )
            case_by_alias[pseudo] = original_id
        if not case_by_alias:
            raise ValueError("Die lokale Zuordnung enthält keine gültigen Fälle.")

        # Belegprüfung gilt fuer die neuen mehrdimensionalen
        # Fehlerbild-Zuordnungen genauso wie fuer Cluster und Einzelfaelle.
        # Eine Quelle darf nicht durch Verschachtelung ungeprueft werden.
        all_evidence = [
            evidence
            for item in (*data.cluster, *data.faelle)
            for evidence in item.belege
        ]
        all_evidence.extend(
            evidence
            for finding in data.faelle
            for symptom in finding.fehlerbilder
            for evidence in symptom.belege
        )

        # AE-/LB-IDs sind Zeilennummern im originalen Export, keine Einträge
        # der privaten Pseudonymzuordnung. Nur durch ZIP-Prüfung akzeptieren.
        requested_rows: dict[str, set[str]] = defaultdict(set)
        for evidence in all_evidence:
            spec = self._ROW_EVIDENCE.get(evidence.quelle)
            if spec and re.fullmatch(spec[2], evidence.quelle_id):
                requested_rows[evidence.quelle].add(evidence.quelle_id)
        report("Zeilenbelege gegen das archivierte Analysepaket prüfen …")
        verified_rows = self._validate_export_rows(data.paket_id, requested_rows)
        qec_fields = {
            (evidence.quelle_id, evidence.fundstelle)
            for evidence in all_evidence
            if evidence.quelle == "qec_felder"
        }
        self._verify_qec_field_locations(data.paket_id, qec_fields)

        cluster_ids: set[str] = set()
        members: dict[str, str] = {}
        for cluster in data.cluster:
            if not _IDENT.fullmatch(cluster.cluster_id) or cluster.cluster_id in cluster_ids:
                raise ValueError("Clusterkennung ungültig oder doppelt.")
            cluster_ids.add(cluster.cluster_id)
            self._validate_belege(cluster.belege, mapping, verified_rows)
            for pseudo in cluster.fall_ids:
                if pseudo not in case_by_alias:
                    raise ValueError("Unbekannter Fall im Cluster.")
                if pseudo in members:
                    raise ValueError("Ein Fall darf nur einem Cluster zugeordnet werden.")
                members[pseudo] = cluster.cluster_id

        input_cases: set[str] = set()
        for number, finding in enumerate(data.faelle, 1):
            if number == 1 or number % 10 == 0 or number == len(data.faelle):
                report(f"Fallbewertungen prüfen ({number}/{len(data.faelle)}) …")
            pseudo = finding.fall_id
            if pseudo not in case_by_alias or pseudo in input_cases:
                raise ValueError("Unbekannte oder doppelte Fallkennung in LLM-Ergebnis.")
            input_cases.add(pseudo)
            if finding.cluster_id is not None:
                if finding.cluster_id not in cluster_ids:
                    raise ValueError("Falldatensatz verweist auf einen unbekannten Cluster.")
                if members.get(pseudo) != finding.cluster_id:
                    raise ValueError("Cluster-Mitgliedschaft widerspricht der Fallbewertung.")
            elif pseudo in members:
                raise ValueError("Clusterzuordnung fehlt bei einem aufgeführten Mitglied.")
            self._validate_belege(finding.belege, mapping, verified_rows)
            categories = [symptom.kategorie for symptom in finding.fehlerbilder]
            if len(categories) != len(set(categories)):
                raise ValueError(
                    "Fehlerbild mehrfach angegeben: pro Kategorie nur eine "
                    "Zuordnung mit zusammengefassten Belegen verwenden."
                )
            for symptom in finding.fehlerbilder:
                self._validate_belege(symptom.belege, mapping, verified_rows)

        if data.cluster_abdeckung == "T_S_v1":
            if set(input_cases) != set(members):
                raise ValueError(
                    "Nicht alle Fälle haben eine T- oder S-Zuordnung."
                )
            for group in data.cluster:
                prefix = group.cluster_id[:1]
                if (prefix not in ("T", "S")
                        or not re.fullmatch(r"[TS][0-9]{2,4}", group.cluster_id)
                        or group.ebene != prefix):
                    raise ValueError(
                        "T/S-Cluster benötigen eindeutige Kennung und Ebene."
                    )
                if prefix == "S" and group.sicherheit == "Hoch":
                    raise ValueError(
                        "Symptomcluster dürfen nicht als technisch hoch "
                        "gesicherter Ursachencluster ausgegeben werden."
                    )
            for case in data.faelle:
                if case.cluster_id is None:
                    raise ValueError("Fall ohne Cluster: " + case.fall_id)
            self._validate_ts_revision(data)

        if data.fehlerbild_methodik == "multilabel_symptom_nachweis_v2":
            missing = set(case_by_alias) - input_cases
            if missing:
                raise ValueError(
                    "LLM-Durchlauf 2 unvollstaendig: "
                    f"{len(missing)} QEC-Faelle ohne Bewertung. "
                    "Auch Faelle ohne DTC oder Werkstatttext muessen "
                    "'Unbekannt' als Fehlerbild erhalten."
                )
            empty_symptom = [
                item.fall_id for item in data.faelle if not item.fehlerbilder
            ]
            if empty_symptom:
                raise ValueError(
                    "LLM-Durchlauf 2 enthaelt einen Fall ohne "
                    f"Fehlerbild-Zuordnung: {empty_symptom[0]}. "
                    "Auch bei Datenluecken Kategorie 'Unbekannt' angeben."
                )
            empty_proof = [
                item.fall_id for item in data.faelle if not item.nachweisprofil
            ]
            if empty_proof:
                raise ValueError(
                    "LLM-Durchlauf 2 enthaelt einen Fall ohne "
                    f"Nachweisprofil: {empty_proof[0]}. "
                    "'Datenlage unzureichend' ist zulaessig."
                )

        report("Analyse und Cluster in einer Transaktion speichern …")
        with self.store.connect() as con:
            con.execute("BEGIN TRANSACTION")
            try:
                con.execute(
                    "INSERT INTO chatgpt_imports VALUES (?,?,?,?,?)",
                    [
                        data.analyse_id, data.paket_id, source_sha,
                        datetime.now(), content.decode("utf-8-sig"),
                    ],
                )
                if data.cluster:
                    con.executemany(
                        "INSERT INTO chatgpt_cluster VALUES (?,?,?)",
                        [
                            (data.analyse_id, cluster.cluster_id,
                             cluster.model_dump_json(exclude_none=True))
                            for cluster in data.cluster
                        ],
                    )
                con.executemany(
                    "INSERT INTO chatgpt_fallanalysen "
                    "(analyse_id,case_id,fall_pseudonym,cluster_id,payload_json,review_status) "
                    "VALUES (?,?,?,?,?,'Offen')",
                    [
                        (
                            data.analyse_id, case_by_alias[finding.fall_id],
                            finding.fall_id, finding.cluster_id,
                            finding.model_dump_json(exclude_none=True),
                        )
                        for finding in data.faelle
                    ],
                )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return {
            "analyse_id": data.analyse_id, "faelle": len(data.faelle),
            "cluster": len(data.cluster), "bereits_importiert": False,
        }

    def list_case_findings(self, limit: int = 2000) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT f.analyse_id,f.case_id,f.fall_pseudonym,f.cluster_id,"
                "f.payload_json,f.review_status,i.importiert_am "
                "FROM chatgpt_fallanalysen f JOIN chatgpt_imports i "
                "ON i.analyse_id=f.analyse_id "
                "ORDER BY i.importiert_am DESC,f.fall_pseudonym LIMIT ?",
                [min(max(limit, 1), 10000)],
            ).fetchall()
        return [
            {
                "analyse_id": row[0], "case_id": row[1],
                "fall_pseudonym": row[2], "cluster_id": row[3],
                "bewertung": json.loads(row[4]), "review_status": row[5],
                "importiert_am": row[6],
            }
            for row in rows
        ]

    def latest_for_case(self, case_id: str) -> dict | None:
        with self.store.connect() as con:
            row = con.execute(
                "SELECT f.analyse_id,f.cluster_id,f.payload_json,f.review_status "
                "FROM chatgpt_fallanalysen f JOIN chatgpt_imports i "
                "ON f.analyse_id=i.analyse_id "
                "WHERE f.case_id=? "
                "ORDER BY i.importiert_am DESC,f.analyse_id DESC LIMIT 1",
                [case_id],
            ).fetchone()
        if row is None:
            return None
        return {
            "analyse_id": row[0], "cluster_id": row[1],
            "bewertung": json.loads(row[2]), "review_status": row[3],
        }

    def set_review_status(self, analyse_id: str, case_id: str, status: str) -> None:
        if status not in _REVIEW:
            raise ValueError("Unbekannter Prüfstatus.")
        with self.store.connect() as con:
            updated = con.execute(
                "UPDATE chatgpt_fallanalysen "
                "SET review_status=?,reviewed_at=? "
                "WHERE analyse_id=? AND case_id=? RETURNING case_id",
                [status, datetime.now() if status != "Offen" else None,
                 analyse_id, case_id],
            ).fetchone()
        if not updated:
            raise ValueError("LLM-Fallbewertung nicht gefunden.")
