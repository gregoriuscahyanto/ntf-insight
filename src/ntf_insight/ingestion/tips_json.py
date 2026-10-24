"""Strukturierter, ausschließlich lesender Parser für lokale TIPS-Writer-Berichte.

Eine gespeicherte tips.json wird nur mit korrektem FIN-/Fallnummer-Schlüssel
indexiert. Anhänge bleiben Referenzen; sie werden nicht als geparste Inhalte
oder als Beleg einer Ursache ausgegeben.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ntf_insight.ingestion.reference_source_parsers import KnowledgeResult

_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_CASE = re.compile(r"\d{4,16}\Z")
MAX_BYTES = 32 * 1024**2
MAX_ROWS = 50_000
SECTIONS = (
    "Erstanfrage", "Betriebsdaten", "Fahrzeugdaten", "Symptom",
    "Kommunikation", "Anhänge", "Funktionsgruppe", "Steuergerät/FC",
    "Zustandsdaten", "Inspektor / Notizen",
)


class TipsJsonParser:
    name = "tips_json_structured"
    version = "1.0.0"

    def parse(self, path: Path) -> KnowledgeResult:
        path = Path(path)
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            raise ValueError("TIPS-Datei ist nicht regulär oder zu groß.")
        try:
            report = json.loads(path.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("TIPS-Bericht ist kein gültiges JSON.") from exc
        if not isinstance(report, dict) or report.get("schema_version") != 1:
            raise ValueError("TIPS-JSON benötigt das unterstützte Schema 1.")
        fin = str(report.get("fin") or "")
        case_id = str(report.get("fallnummer") or "")
        if not _FIN.fullmatch(fin) or not _CASE.fullmatch(case_id):
            raise ValueError("TIPS-JSON hat keine gültige FIN/Fallnummer.")
        if path.name == "tips.json" and path.parent.name.startswith("fall_"):
            if (
                path.parent.name != f"fall_{case_id}"
                or path.parent.parent.name != fin
            ):
                raise ValueError("TIPS-Dateipfad und Berichtidentität widersprechen sich.")
        sections = report.get("abschnitte")
        if not isinstance(sections, list) or len(sections) > 20:
            raise ValueError("TIPS-Reiterliste fehlt oder ist ungültig.")
        result = KnowledgeResult(kind="tips_live_case")
        seen: set[str] = set()

        def put(category: str, location: str, label: str, value: dict) -> None:
            if len(result.records) >= MAX_ROWS:
                raise ValueError("Zu viele TIPS-Einträge.")
            result.records.append({
                "category": category, "source_location": location,
                "fin": fin, "reference": case_id, "label": label,
                "data": value,
            })

        put("tips_case", "TIPS/Kopfdaten", str(report.get("titel") or ""),
            {
                "titel": str(report.get("titel") or ""),
                "kopfdaten_text": str(report.get("kopfdaten_text") or ""),
                "suchtreffer": report.get("suchtreffer")
                if isinstance(report.get("suchtreffer"), dict) else {},
            })
        for position, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                result.issues.append("Ein TIPS-Reiter ist kein Objekt.")
                continue
            name = str(section.get("bereich") or "")
            if name not in SECTIONS or name in seen:
                result.issues.append("Unbekannter oder doppelter TIPS-Reiter.")
                continue
            seen.add(name)
            if section.get("aus_vorherigem_abruf") is True:
                result.issues.append("Reiter stammt aus vorherigem TIPS-Abruf.")
            put("tips_section", f"TIPS/{position:02d}", name, {
                "sichtbarer_text": str(section.get("sichtbarer_text") or ""),
                "aus_vorherigem_abruf": section.get("aus_vorherigem_abruf") is True,
            })
            fields = section.get("felder", [])
            for number, field in enumerate(fields if isinstance(fields, list) else [], start=1):
                if not isinstance(field, dict):
                    result.issues.append("Ungültiges TIPS-Feld.")
                    continue
                put("tips_field", f"TIPS/{position:02d}/feld:{number}",
                    str(field.get("beschriftung") or field.get("name") or ""),
                    dict(field))
            tables = section.get("tabellen", [])
            for number, table in enumerate(tables if isinstance(tables, list) else [], start=1):
                if not isinstance(table, dict) or not isinstance(table.get("zeilen"), list):
                    result.issues.append("Ungültige TIPS-Tabelle.")
                    continue
                for row_index, row in enumerate(table["zeilen"], start=1):
                    if not isinstance(row, list):
                        result.issues.append("Ungültige TIPS-Tabellenzeile.")
                        continue
                    put(
                        "tips_table_row",
                        f"TIPS/{position:02d}/tabelle:{number}/zeile:{row_index}",
                        name, {"zellen": row},
                    )
        if set(SECTIONS) - seen:
            result.issues.append("Nicht alle zehn TIPS-Reiter vorhanden.")
        if report.get("vollstaendige_reiter") is not True:
            result.issues.append("TIPS-Abruf nicht als vollständig bestätigt.")
        if report.get("fehler"):
            result.issues.append("TIPS-Abruf enthält Fehler.")
        # Anhänge ausdrücklich nicht als gelesen/geparst markieren.
        attachments = report.get("anhangliste", [])
        if isinstance(attachments, list):
            for i, entry in enumerate(attachments, start=1):
                if isinstance(entry, dict):
                    put("tips_attachment_reference", f"TIPS/anhang:{i}",
                        str(entry.get("dateiname") or ""), dict(entry))
        result.metadata = {
            "schema_version": 1,
            "parser_version": self.version,
            "fin": fin,
            "reference": case_id,
            "downloaded_at_utc": str(report.get("abgerufen_am_utc") or ""),
            "sections": len(seen),
            "missing_sections": sorted(set(SECTIONS) - seen),
            "full_sections": len(seen) == len(SECTIONS),
            "attachments_are_only_references": True,
        }
        return result
