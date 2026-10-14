"""Lokaler FIN-ZIP-Export: Quellenabdeckung und Datenschutz mit synthetischen Daten."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from ntf_insight.reporting.fin_zip_export import export_fin_zip

FIN = "WDD12345678901234"
OTHER_FIN = "WDD12345678901235"


def _make_file(root: Path, relative: str, data: bytes = b"%PDF-1.7\nsynthetic") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _qec_case(root: Path, fin: str, ref: str) -> Path:
    case = root / "qec" / fin / f"ref_{ref}"
    case.mkdir(parents=True, exist_ok=True)
    (case / "qec.json").write_text(json.dumps({
        "fin": fin, "referenznummer": ref,
        "abschnitte": [{"bereich": "WE-Daten"}, {"bereich": "Historie"}],
    }), encoding="utf-8")
    return case


def test_fin_export_contains_all_quicktests_qec_references_and_future_tips(tmp_path):
    data = tmp_path / "input"
    exports = tmp_path / "output"
    report1 = _make_file(data, f"quicktests/{FIN}/quicktest-1.pdf")
    report2 = _make_file(data, f"quicktests/{FIN}/quicktest-2.PDF", b"%PDF-1.5\nsecond")
    _make_file(data, f"quicktests/{FIN}/abrufstatus.json", b'{"secret": "not exported"}')
    _make_file(data, f"quicktests/{OTHER_FIN}/other-vin.pdf", b"%PDF-other")
    first = _qec_case(data, FIN, "022301658")
    second = _qec_case(data, FIN, "022301659")
    pdf = _make_file(first, "anhaenge/1603327_bericht.pdf")
    _make_file(second, "anhaenge/1580627_zweiter-bericht.PDF")
    _make_file(first, "anhaenge/vorschau.html", b"<html>not exported</html>")
    _qec_case(data, OTHER_FIN, "022301660")
    _make_file(data, f"qec/{OTHER_FIN}/ref_022301660/anhaenge/other.pdf")
    _make_file(data, f"edge-qec-profile/{FIN}/Cookies", b"secret")
    _make_file(data, f"tips/{FIN}/tips.json",
               json.dumps({"fin": FIN, "fall": "synthetisch"}).encode("utf-8"))
    _make_file(data, f"tips/{FIN}/dateien/foto.jpg", b"FAKE-JPEG")
    _make_file(data, f"tips/{FIN}/dateien/anhang.docx", b"synthetic-doc")
    _make_file(data, f"tips/{FIN}/dateien/script.exe", b"not included")

    result = export_fin_zip(FIN, data, exports)
    assert result.zip_path == exports / f"{FIN}_NTF-Export.zip"
    assert result.file_count == 9
    assert result.counts == {
        "quicktests": 2, "qec_json": 2, "qec_pdfs": 2,
        "tips_json": 1, "tips_dateien": 2,
    }
    with ZipFile(result.zip_path) as archive:
        paths = set(archive.namelist())
        assert paths == {
            "quicktests/quicktest-1.pdf",
            "quicktests/quicktest-2.PDF",
            "qec/ref_022301658/qec.json",
            "qec/ref_022301659/qec.json",
            "qec/ref_022301658/anhaenge/1603327_bericht.pdf",
            "qec/ref_022301659/anhaenge/1580627_zweiter-bericht.PDF",
            "tips/tips.json",
            "tips/dateien/foto.jpg",
            "tips/dateien/anhang.docx",
            "export_manifest.json",
        }
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in paths)
        assert archive.read("quicktests/quicktest-1.pdf") == report1.read_bytes()
        assert archive.read("quicktests/quicktest-2.PDF") == report2.read_bytes()
        assert archive.read("qec/ref_022301658/anhaenge/1603327_bericht.pdf") == pdf.read_bytes()
        manifest = json.loads(archive.read("export_manifest.json"))
        assert manifest["fin"] == FIN
        assert manifest["schema_version"] == 1
        assert manifest["anzahl"] == result.counts
        assert manifest["fehlende_quellen"] == []
        assert len(manifest["dateien"]) == 9
        assert next(item["sha256"] for item in manifest["dateien"]
                    if item["pfad"] == "quicktests/quicktest-1.pdf") == hashlib.sha256(
                        report1.read_bytes()
                    ).hexdigest()


def test_no_data_skips_zip_instead_of_publishing_empty_archive(tmp_path):
    output = tmp_path / "exports"
    result = export_fin_zip(FIN, tmp_path / "data", output)
    assert result.zip_path is None
    assert result.file_count == 0
    assert "Keine lokalen Quelldateien" in result.warnings[-1]
    assert not output.exists()


def test_partial_sources_include_manifest_with_missing_categories(tmp_path):
    data = tmp_path / "data"
    _make_file(data, f"quicktests/{FIN}/nur-quicktest.pdf")
    result = export_fin_zip(FIN, data, tmp_path / "export")
    assert result.file_count == 1
    with ZipFile(result.zip_path) as archive:
        manifest = json.loads(archive.read("export_manifest.json"))
        assert manifest["fehlende_quellen"] == [
            "qec_json", "qec_pdfs", "tips_json", "tips_dateien",
        ]
        assert set(archive.namelist()) == {"quicktests/nur-quicktest.pdf", "export_manifest.json"}


def test_wrong_fin_or_reference_in_qec_json_never_exports_that_case(tmp_path):
    data = tmp_path / "data"
    first = _qec_case(data, FIN, "022301658")
    wrong_fin = first / "qec.json"
    wrong_fin.write_text(json.dumps({
        "fin": OTHER_FIN, "referenznummer": "022301658",
    }), encoding="utf-8")
    _make_file(first, "anhaenge/privat.pdf")
    second = _qec_case(data, FIN, "022301659")
    (second / "qec.json").write_text("{invalid", encoding="utf-8")
    _make_file(second, "anhaenge/privat-2.pdf")
    result = export_fin_zip(FIN, data, tmp_path / "out")
    assert result.zip_path is None
    assert result.file_count == 0
    assert len([w for w in result.warnings if "ausgelassen" in w]) == 2


def test_missing_qec_json_never_exports_orphan_pdf(tmp_path):
    data = tmp_path / "data"
    _make_file(data, f"qec/{FIN}/ref_022301658/anhaenge/verwaist.pdf")
    _make_file(data, f"quicktests/{FIN}/einzig.pdf")
    result = export_fin_zip(FIN, data, tmp_path / "out")
    with ZipFile(result.zip_path) as archive:
        assert "quicktests/einzig.pdf" in archive.namelist()
        assert not any(name.startswith("qec/") for name in archive.namelist())
    assert any("nicht eindeutig verifizierbar" in note for note in result.warnings)


def test_repeated_exports_do_not_overwrite_first_zip(tmp_path):
    data = tmp_path / "data"
    _make_file(data, f"quicktests/{FIN}/a.pdf")
    first = export_fin_zip(FIN, data, tmp_path / "out")
    second = export_fin_zip(FIN, data, tmp_path / "out")
    assert first.zip_path != second.zip_path
    assert second.zip_path.name.endswith("_2.zip")
    assert first.zip_path.read_bytes() and second.zip_path.read_bytes()
    assert not list((tmp_path / "out").glob("*.partial"))


@pytest.mark.parametrize("invalid", [
    "../" + FIN, FIN[:-1], FIN.lower(), "A/B/C", "WDD1234567890123I",
    "", None,
])
def test_invalid_fin_rejected_before_filesystem_access(tmp_path, invalid):
    with pytest.raises(ValueError, match="17-stellige FIN"):
        export_fin_zip(invalid, tmp_path / "data", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_tips_json_with_foreign_fin_is_excluded(tmp_path):
    data = tmp_path / "data"
    _make_file(data, f"quicktests/{FIN}/test.pdf")
    _make_file(data, f"tips/{FIN}/tips.json",
               json.dumps({"fin": OTHER_FIN}).encode("utf-8"))
    result = export_fin_zip(FIN, data, tmp_path / "out")
    with ZipFile(result.zip_path) as archive:
        assert not any(item.startswith("tips/") for item in archive.namelist())
    assert result.counts["tips_json"] == 0
    assert any("abweichender FIN" in warning for warning in result.warnings)


@pytest.mark.skipif(os.name == "nt", reason="Symlinks ohne Developer Mode unter Windows eingeschränkt")
def test_symlinked_files_and_directories_are_never_exported(tmp_path):
    data = tmp_path / "data"
    foreign = _make_file(tmp_path, "foreign/geheim.pdf", b"%PDF-1.7\nprivate")
    (data / "quicktests" / FIN).mkdir(parents=True)
    (data / "quicktests" / FIN / "link.pdf").symlink_to(foreign)
    _make_file(data, f"quicktests/{FIN}/safe.pdf")
    (data / "tips" / FIN).mkdir(parents=True)
    (data / "tips" / FIN / "extern").symlink_to(foreign.parent, target_is_directory=True)
    result = export_fin_zip(FIN, data, tmp_path / "out")
    with ZipFile(result.zip_path) as archive:
        assert "quicktests/safe.pdf" in archive.namelist()
        assert "quicktests/link.pdf" not in archive.namelist()
        assert not any(item.startswith("tips/") for item in archive.namelist())
