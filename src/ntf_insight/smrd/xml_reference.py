"""Generic read-only parser for the observed Smrd2Xml XML formats."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


def parse_xml(path: Path, *, include_dtcs: bool = True, max_records: int = 250000) -> tuple[dict, list[dict]]:
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".xml":
        raise ValueError("XML-Datei nicht gefunden")
    if not 0 < path.stat().st_size <= 160000000:
        raise ValueError("XML-Dateigroesse nicht unterstuetzt")
    raw = path.read_bytes()
    upper = raw.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("DOCTYPE und ENTITY sind nicht erlaubt")
    root = ET.fromstring(raw)
    rows: list[dict] = []
    counts: Counter = Counter()
    root_tag = root.tag.split("}")[-1]
    if root_tag.upper() not in {"ECUS", "SMRD2XML"}:
        raise ValueError(f"Nicht unterstuetztes XML-Format: {root_tag}")

    def emit(category: str, reference: str, label: str, variant: str,
             ecu: str, version: str, location: str, attributes: dict | None = None,
             extra: dict | None = None) -> None:
        if len(rows) >= max_records:
            raise ValueError("Zu viele XML-Eintraege")
        data = {"ecu": ecu, "ecu_version": version or None, "variant": variant or None,
                "attributes": attributes or {}, "trigger_conditions_validated": False,
                "is_vehicle_observation": False, **(extra or {})}
        rows.append({"category": category, "source_location": location,
                     "fin": None, "reference": reference, "label": label[:4000], "data": data})
        counts[category] += 1

    def details(node: ET.Element) -> dict:
        fields: dict[str, list[str]] = {}
        for child in node:
            key = (child.get("SEMANTIC") or child.get("semantic") or
                   child.get("name") or child.get("NAME") or child.tag)
            value = (child.get("sdgdata") or child.get("content") or (child.text or "")).strip()
            if value:
                fields.setdefault(key, []).append(value)
        normalized = {key.upper().replace("-", "_").replace(" ", "_"): value
                      for key, value in fields.items()}
        level = (node.get("ERROR_LEVEL") or node.get("errorLevel") or
                 (normalized.get("ERROR_LEVEL") or [None])[0])
        return {"dtc_raw_text": (node.text or "").strip(),
                "error_level": level,
                "repair_action": (normalized.get("REPAIR_ACTION") or [None])[0],
                "possible_causes": (normalized.get("POSSIBLE_CAUSES") or [None])[0],
                "extra_fields": fields}

    if root_tag.upper() == "ECUS":
        for ei, ecu_node in enumerate(root.findall("./ECU"), 1):
            ecu = ecu_node.get("NAME") or ""
            version = ecu_node.get("VERSION") or ""
            emit("smrd_xml_ecu", ecu, ecu, "", ecu, version, f"/ECUS/ECU[{ei}]")
            for vi, variant_node in enumerate(ecu_node.findall("./VARIANT"), 1):
                variant = variant_node.get("NAME") or ""
                base = f"/ECUS/ECU[{ei}]/VARIANT[{vi}]"
                emit("smrd_xml_variant", variant, variant, variant, ecu, version, base)
                if include_dtcs:
                    for di, dtc_node in enumerate(variant_node.findall("./DTC"), 1):
                        code = dtc_node.get("NAME") or ""
                        raw_text = (dtc_node.text or "").strip()
                        emit("smrd_xml_dtc", code, f"{code}: {raw_text}", variant, ecu,
                             version, f"{base}/DTC[{di}]", dict(dtc_node.attrib),
                             details(dtc_node))
    else:
        ecu = root.get("EcuName") or ""
        version = root.get("Version") or ""
        emit("smrd_xml_ecu", ecu, ecu, "", ecu, version, "/Smrd2Xml")
        for vi, variant_node in enumerate(root.findall("./Variants"), 1):
            variant = variant_node.get("name") or ""
            base = f"/Smrd2Xml/Variants[{vi}]"
            emit("smrd_xml_variant", variant, variant, variant, ecu, version, base)
            for si, svc in enumerate(variant_node.findall("./Services"), 1):
                service = svc.get("name") or ""
                loc = f"{base}/Services[{si}]"
                emit("smrd_xml_service", service, service, variant, ecu, version,
                     loc, dict(svc.attrib))
                for pi, param in enumerate(svc, 1):
                    if param.tag not in {"InParams", "OutParams"}:
                        continue
                    pname = param.get("name") or param.get("Name") or ""
                    emit("smrd_xml_parameter", pname, f"{pname} [{service}]", variant,
                         ecu, version, f"{loc}/{param.tag}[{pi}]", dict(param.attrib),
                         {"service_name": service, "direction": "input" if param.tag == "InParams" else "output",
                          "unit": param.get("Unit"), "choices": [(x.text or "") for x in param.findall("./Choices")]})
            if include_dtcs:
                for di, dtc in enumerate(variant_node.findall("./DTCs"), 1):
                    code = dtc.get("name") or ""
                    raw_text = (dtc.text or "").strip()
                    emit("smrd_xml_dtc", code, f"{code}: {raw_text}", variant, ecu,
                         version, f"{base}/DTCs[{di}]", dict(dtc.attrib), details(dtc))
            for gi, sdg in enumerate(variant_node.findall("./SDGs"), 1):
                ref = sdg.get("name") or ""
                emit("smrd_xml_sdg", ref, f"{ref}: {sdg.get('sdgdata') or ''}",
                     variant, ecu, version, f"{base}/SDGs[{gi}]", dict(sdg.attrib))
    return {"format": root_tag, "ecus": sorted({(r["data"]["ecu"], r["data"]["ecu_version"]) for r in rows if r["category"] == "smrd_xml_ecu"}), "counts": dict(counts)}, rows
