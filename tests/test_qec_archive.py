"""Lokale QEC-Fallordner ohne Fremdzuordnung oder Legacy-Datenverlust."""

import json

import pytest

from ntf_insight.acquisition.qec_archive import case_folder, local_qec_archive

FIN = "WDD12345678901234"
REFERENCE = "022301658"


def test_one_case_json_by_full_fin_and_exact_reference(tmp_path):
    target = case_folder(tmp_path, FIN, REFERENCE)
    target.mkdir(parents=True)
    payload = {
        "fin": FIN, "referenznummer": REFERENCE, "schema_version": 2,
        "abgerufen_am_utc": "2026-10-13T17:30:00+00:00",
        "abschnitte": [{"bereich": "WE-Daten"}],
    }
    (target / "qec.json").write_text(json.dumps(payload), encoding="utf-8")
    archive = local_qec_archive(tmp_path, FIN, REFERENCE)
    assert archive is not None
    assert archive.folder == target
    assert "2026" in archive.date_label
    assert archive.legacy is False
    assert local_qec_archive(tmp_path, FIN, "022301659") is None

    payload["fin"] = "WDD98745678901234"
    (target / "qec.json").write_text(json.dumps(payload), encoding="utf-8")
    assert local_qec_archive(tmp_path, FIN, REFERENCE) is None


def test_legacy_qec_pages_are_visible_but_never_rewritten(tmp_path):
    folder = case_folder(tmp_path, FIN, REFERENCE)
    data = folder / "laeufe" / "20261013" / "01_WE-Daten" / "daten.json"
    data.parent.mkdir(parents=True)
    data.write_text(json.dumps({
        "fin": FIN, "referenznummer": REFERENCE,
        "zeitpunkt_utc": "2026-10-13T16:12:00+00:00",
    }), encoding="utf-8")
    info = local_qec_archive(tmp_path, FIN, REFERENCE)
    assert info is not None and info.legacy
    assert info.folder == folder
    assert data.exists()  # Legacy source stays untouched.


def test_qec_export_folder_rejects_traversal_and_unverified_references(tmp_path):
    with pytest.raises(ValueError):
        case_folder(tmp_path, FIN, "../evil")
    with pytest.raises(ValueError):
        case_folder(tmp_path, "NOT-A-FIN", REFERENCE)
    with pytest.raises(ValueError):
        case_folder(tmp_path, FIN, "")
    assert local_qec_archive(tmp_path, FIN, "../../other") is None


def test_export_with_malformed_timestamp_has_no_date_link(tmp_path):
    folder = case_folder(tmp_path, FIN, REFERENCE)
    folder.mkdir(parents=True)
    (folder / "qec.json").write_text(
        json.dumps({"fin": FIN, "referenznummer": REFERENCE,
                    "abgerufen_am_utc": "ungültig"}),
        encoding="utf-8",
    )
    assert local_qec_archive(tmp_path, FIN, REFERENCE) is None
