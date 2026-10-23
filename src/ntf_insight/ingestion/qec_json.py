"""Strukturierte, verlustfrei referenzierbare QEC-Schadteilberichte aus qec.json.

Nur die fünf QEC-Reiter werden gelesen. Anhänge bleiben unangetastete Dateien;
ihr Metadateneintrag ist ausdrücklich kein analysierter Prüf- oder Befundinhalt.
Es werden keine NTF-Urteile, Lieferantenschuld oder Reparaturereignisse erfunden.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ntf_insight.ingestion.reference_source_parsers import KnowledgeResult

QEC_SECTIONS = (
    "WE-Daten",
    "Voranalysen",
    "Stellungnahme Lieferant",
    "Ergebnis + Nachanalyse",
    "Historie",
)
_FIN = re.compile(r"[A-HJ-NPR-Z0-9]{17}\Z")
_REFERENCE = re.compile(r"[0-9]{1,14}\Z")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 50_000


def list_downloaded_qec_reports(data_dir: Path) -> list[Path]:
    """Find only local qec/<FIN>/ref_<Referenz>/qec.json, without symlink escapes."""
    root = Path(data_dir) / "qec"
    if not root.is_dir() or root.is_symlink():
        return []
    files: list[Path] = []
    for fin_dir in sorted(root.iterdir()):
        if (not fin_dir.is_dir() or fin_dir.is_symlink()
                or not _FIN.fullmatch(fin_dir.name)):
            continue
        for ref_dir in sorted(fin_dir.iterdir()):
            if (not ref_dir.is_dir() or ref_dir.is_symlink()
                    or not ref_dir.name.startswith("ref_")
                    or not _REFERENCE.fullmatch(ref_dir.name[4:])):
                continue
            report = ref_dir / "qec.json"
            if report.is_file() and not report.is_symlink():
                files.append(report)
    return files


class QECJsonParser:
    """Read QEC schema v2 into source-indexed, searchable field and table rows.

    A qec_value is a *literal source value*, not a classified cause or test
    outcome. Original JSON text, fields, and table cells remain recoverable.
    """

    name = "qec_json_structured"
    version = "1.0.0"

    @staticmethod
    def _text(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    def parse(self, path: Path) -> KnowledgeResult:
        path = Path(path)
        if path.stat().st_size > MAX_JSON_BYTES:
            raise ValueError("QEC-JSON überschreitet die zulässige Größe.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("QEC-Bericht enthält kein gültiges JSON.") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 2:
            raise ValueError("QEC-JSON benötigt das unterstützte Schema 2.")
        fin = self._text(payload.get("fin"))
        reference = self._text(payload.get("referenznummer"))
        if not _FIN.fullmatch(fin) or not _REFERENCE.fullmatch(reference):
            raise ValueError("QEC-Bericht enthält keine gültige FIN/Referenz.")
        sections = payload.get("abschnitte")
        if not isinstance(sections, list) or len(sections) > 20:
            raise ValueError("QEC-Bericht hat keine gültige Reiterliste.")

        # Only source facts, never generated supplier or NTF assessments.
        result = KnowledgeResult(kind="qec_live_report")
        fields_total = 0
        values_total = 0
        table_rows_total = 0
        stale: list[str] = []
        seen: set[str] = set()

        def add(category: str, location: str, label: str, data: dict) -> None:
            if len(result.records) >= MAX_RECORDS:
                raise ValueError("QEC-Bericht enthält zu viele strukturierte Einträge.")
            result.records.append({
                "category": category,
                "source_location": location,
                "fin": fin,
                "reference": reference,
                "label": label,
                "data": data,
            })

        for index, section in enumerate(sections, start=1):
            if not isinstance(section, dict):
                result.issues.append("Ein QEC-Reiter ist nicht lesbar.")
                continue
            name = self._text(section.get("bereich"))
            if name not in QEC_SECTIONS:
                result.issues.append("Ein QEC-Reiter hat eine unbekannte Bezeichnung.")
                continue
            if name in seen:
                result.issues.append("Ein QEC-Reiter ist mehrfach vorhanden.")
                continue
            if ((section.get("fin") is not None and section.get("fin") != fin)
                    or (section.get("referenznummer") is not None
                        and str(section.get("referenznummer")) != reference)):
                raise ValueError("QEC-Reiter gehört zu einer anderen FIN/Referenz.")
            seen.add(name)
            old = section.get("aus_vorherigem_abruf") is True
            if old:
                stale.append(name)
            fields = section.get("felder", [])
            tables = section.get("tabellen", [])
            if not isinstance(fields, list) or not isinstance(tables, list):
                result.issues.append("Ein QEC-Reiter enthält ungültige Felder/Tabellen.")
                fields = fields if isinstance(fields, list) else []
                tables = tables if isinstance(tables, list) else []
            prefix = f"QEC/{index:02d}-{name}"
            add("qec_section", prefix, name, {
                "bereich": name,
                "zeitpunkt_utc": self._text(section.get("zeitpunkt_utc")),
                "aus_vorherigem_abruf": old,
                "sichtbarer_text": self._text(section.get("sichtbarer_text")),
                "anzahl_felder": len(fields),
                "anzahl_tabellen": len(tables),
            })

            for number, field in enumerate(fields, start=1):
                if not isinstance(field, dict):
                    result.issues.append("Ein QEC-Eingabefeld ist ungültig.")
                    continue
                label = (
                    self._text(field.get("beschriftung"))
                    or self._text(field.get("name"))
                    or f"Feld {number}"
                )
                kind = self._text(field.get("typ")).lower()
                raw = self._text(field.get("wert"))
                option = self._text(field.get("optionwert"))
                selected_text = self._text(field.get("auswahltext"))
                location = f"{prefix}/feld:{number}"
                data = {
                    "bereich": name,
                    "name": self._text(field.get("name")),
                    "beschriftung": self._text(field.get("beschriftung")),
                    "typ": kind,
                    "wert": raw,
                    "optionwert": option,
                    "auswahltext": selected_text,
                    "deaktiviert": field.get("deaktiviert") is True,
                    "aus_vorherigem_abruf": old,
                }
                add("qec_field", location, label, data)
                fields_total += 1
                # No negative fact is inferred from an unchecked checkbox/radio.
                value = (
                    (selected_text or option or label or "Ja") if raw == "ja" else ""
                ) if kind in {"checkbox", "radio"} else (
                    selected_text or raw if kind in {"select", "select-one", "select-multiple"}
                    else raw
                )
                if value:
                    add("qec_value", location, label, {
                        "bereich": name,
                        "wert": value,
                        "rohwert": raw,
                        "quelle": "formular",
                        "aus_vorherigem_abruf": old,
                    })
                    values_total += 1

            for table_no, table in enumerate(tables, start=1):
                if not isinstance(table, dict) or not isinstance(table.get("zeilen"), list):
                    result.issues.append("Eine QEC-Tabelle ist ungültig.")
                    continue
                for row_no, row in enumerate(table["zeilen"], start=1):
                    if not isinstance(row, list):
                        result.issues.append("Eine QEC-Tabellenzeile ist ungültig.")
                        continue
                    cells = []
                    for cell in row:
                        if not isinstance(cell, dict):
                            continue
                        cells.append({
                            "text": self._text(cell.get("text")),
                            "typ": self._text(cell.get("typ")),
                            "colspan": cell.get("colspan") if type(cell.get("colspan")) is int else 1,
                        })
                    location = f"{prefix}/tabelle:{table_no}/zeile:{row_no}"
                    add("qec_table_row", location, f"{name} · Tabelle {table_no}", {
                        "bereich": name,
                        "tabelle": table_no,
                        "zeile": row_no,
                        "zellen": cells,
                        "aus_vorherigem_abruf": old,
                    })
                    table_rows_total += 1
                    # Plain two-cell label/value rows can be searched directly.
                    # Other table layouts are stored as rows, without guessing headers.
                    if (len(cells) == 2 and cells[0]["text"] and cells[1]["text"]
                            and cells[0]["typ"] != "th"
                            and cells[1]["typ"] != "th"):
                        add("qec_value", location, cells[0]["text"], {
                            "bereich": name,
                            "wert": cells[1]["text"],
                            "quelle": "tabelle",
                            "aus_vorherigem_abruf": old,
                        })
                        values_total += 1

        attachments = payload.get("anhaenge", [])
        if not isinstance(attachments, list):
            result.issues.append("QEC-Anhangsliste ist ungültig.")
            attachments = []
        for index, item in enumerate(attachments, start=1):
            if not isinstance(item, dict):
                result.issues.append("Ein QEC-Anhangsverweis ist ungültig.")
                continue
            # Inventory only. Never open, interpret or parse the binary attachment.
            add("qec_attachment", f"QEC/anhang:{index}", self._text(item.get("dateiname")), {
                "anhang_id": self._text(item.get("anhang_id")),
                "dateiname": self._text(item.get("dateiname")),
                "datei": self._text(item.get("datei")),
                "linktext": self._text(item.get("linktext")),
                "spalten": item.get("spalten") if isinstance(item.get("spalten"), list) else [],
            })

        missing = [name for name in QEC_SECTIONS if name not in seen]
        if missing:
            result.issues.append("Nicht alle fünf QEC-Reiter sind vorhanden.")
        if stale:
            result.issues.append("Mindestens ein QEC-Reiter stammt aus einem früheren Abruf.")
        if payload.get("vollstaendige_reiter") is not True:
            result.issues.append("Der QEC-Abruf ist nicht als vollständig bestätigt.")
        if payload.get("fehler"):
            result.issues.append("Der QEC-Abruf enthält protokollierte Fehler.")
        fresh_complete = (
            not missing and not stale and payload.get("vollstaendige_reiter") is True
        )
        result.metadata = {
            "schema_version": 2,
            "parser_version": self.version,
            "fin": fin,
            "reference": reference,
            "part_number": self._text(payload.get("sachnummer")),
            "description": self._text(payload.get("bezeichnung")),
            "downloaded_at_utc": self._text(payload.get("abgerufen_am_utc")),
            "sections": len(seen),
            "fresh_sections": len(seen) - len(stale),
            "stale_sections": stale,
            "missing_sections": missing,
            "fresh_complete": fresh_complete,
            "fields": fields_total,
            "values": values_total,
            "table_rows": table_rows_total,
            "attachments": sum(isinstance(item, dict) for item in attachments),
            "download_errors": len(payload.get("fehler") or []),
        }
        return result
