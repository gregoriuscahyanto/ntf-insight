"""Versionierter ChatGPT-Rückgabe-Vertrag für NTF-/QEC-Fallbewertungen.

Die Antwort aus einem externen Analysemodell bleibt eine überprüfbare Hypothese,
kein automatischer Ersatz für QEC-Entscheidungen oder manuelle Fallbewertungen.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
]
Bewertung = Literal[
    "NTF plausibel", "NTF fraglich", "Kein reiner NTF",
    "Nicht bewertbar", "Nicht bewertet",
]
Sicherheit = Literal["Hoch", "Mittel", "Niedrig", "Offen"]
Zuordnung = Literal["Belegt", "Plausibel", "Offen"]
Prioritaet = Literal["P1", "P2", "P3", "Offen"]


class ChatGPTBeleg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quelle: BelegQuelle
    quelle_id: str = Field(default="", max_length=90)
    fundstelle: str = Field(default="", max_length=500)
    aussage: str = Field(default="", max_length=1800)
    belegstatus: Literal[
        "Originalbefund", "Abgeleitet", "Nicht verifiziert",
    ] = "Nicht verifiziert"


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
    sicherheit_bewertung: Sicherheit = "Offen"
    themen: list[str] = Field(default_factory=list, max_length=30)
    belege: list[ChatGPTBeleg] = Field(default_factory=list, max_length=40)


class ChatGPTCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cluster_id: str = Field(max_length=90)
    titel: str = Field(default="", max_length=180)
    fall_ids: list[str] = Field(min_length=1, max_length=5000)
    technische_hypothese: str = Field(default="", max_length=4000)
    sicherheit: Sicherheit = "Offen"
    belege: list[ChatGPTBeleg] = Field(default_factory=list, max_length=40)


class ChatGPTRueckgabe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["ntf-insight-chatgpt-rueckgabe"] = FORMAT
    schema_version: Literal[1] = SCHEMA_VERSION
    paket_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    analyse_id: str = Field(max_length=90)
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
            "Paketkennung der privaten Zuordnung stimmt nicht mit dem ChatGPT-Ergebnis überein."
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
            if art not in {"fahrzeug", "fall", "qec_bericht", "quicktest", "teil"}:
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
                else row["sachnummer_original"]
            )
            result[key] = {
                "art": art, "pseudonym": pseudo, "original": original,
                "fin": row["fin"], "qec_referenz": row["qec_referenz_original"],
            }
        return result

    @staticmethod
    def _validate_belege(
        belege: list[ChatGPTBeleg], mapping: dict[tuple[str, str], dict],
    ) -> None:
        types = {
            "qec_berichte": "qec_bericht",
            "qec_felder": "qec_bericht",
            "qec_dokumente": "qec_bericht",
            "quicktests": "quicktest",
            "dtc_beobachtungen": "quicktest",
            "ecu_staende": "quicktest",
            "tips": "fall",
        }
        for item in belege:
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

    def import_file(
        self, path: Path, *, private_csv: Path | None = None,
    ) -> dict:
        """Validate all identities and evidence before an atomic INSERT.

        A case's operational assessment, manual revisions and supplier finding
        are NEVER overwritten by an external model's hypothesis.
        """
        path = Path(path)
        if path.suffix.casefold() != ".json" or not path.is_file():
            raise ValueError("Bitte eine ChatGPT-Ergebnisdatei im Format .json wählen.")
        if path.stat().st_size > MAX_JSON_SIZE:
            raise ValueError("ChatGPT-Ergebnisdatei ist zu groß.")
        content = path.read_bytes()
        try:
            data = ChatGPTRueckgabe.model_validate_json(content)
        except (ValueError, ValidationError) as exc:
            raise ValueError("ChatGPT-Ergebnis entspricht nicht der gültigen Analysevorlage.") from exc
        if not _IDENT.fullmatch(data.analyse_id) or not _PAKET_ID.fullmatch(data.paket_id):
            raise ValueError("Ungültige Paket- oder Analysekennung.")
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

        cluster_ids: set[str] = set()
        members: dict[str, str] = {}
        for cluster in data.cluster:
            if not _IDENT.fullmatch(cluster.cluster_id) or cluster.cluster_id in cluster_ids:
                raise ValueError("Clusterkennung ungültig oder doppelt.")
            cluster_ids.add(cluster.cluster_id)
            self._validate_belege(cluster.belege, mapping)
            for pseudo in cluster.fall_ids:
                if pseudo not in case_by_alias:
                    raise ValueError("Unbekannter Fall im Cluster.")
                if pseudo in members:
                    raise ValueError("Ein Fall darf nur einem Cluster zugeordnet werden.")
                members[pseudo] = cluster.cluster_id

        input_cases: set[str] = set()
        for finding in data.faelle:
            pseudo = finding.fall_id
            if pseudo not in case_by_alias or pseudo in input_cases:
                raise ValueError("Unbekannte oder doppelte Fallkennung in ChatGPT-Ergebnis.")
            input_cases.add(pseudo)
            if finding.cluster_id is not None:
                if finding.cluster_id not in cluster_ids:
                    raise ValueError("Falldatensatz verweist auf einen unbekannten Cluster.")
                if members.get(pseudo) != finding.cluster_id:
                    raise ValueError("Cluster-Mitgliedschaft widerspricht der Fallbewertung.")
            elif pseudo in members:
                raise ValueError("Clusterzuordnung fehlt bei einem aufgeführten Mitglied.")
            self._validate_belege(finding.belege, mapping)

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
                con.executemany(
                    "INSERT INTO chatgpt_cluster VALUES (?,?,?)",
                    [
                        (data.analyse_id, cluster.cluster_id,
                         cluster.model_dump_json(exclude_none=True))
                        for cluster in data.cluster
                    ],
                ) if data.cluster else None
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
            raise ValueError("ChatGPT-Fallbewertung nicht gefunden.")
