"""Statische Schutzprüfungen für den Windows-Release-Build."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_release_is_manual_and_hosted() -> None:
    workflow = (ROOT / ".github/workflows/release-windows.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "refs/heads/main" in workflow
    assert "gh release create" in workflow
    assert "self-hosted" not in workflow


def test_installer_creates_shortcuts_without_admin() -> None:
    installer = (ROOT / "installer/ntf-insight.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in installer
    assert r"{group}\NTF Insight" in installer
    assert r"{autodesktop}\NTF Insight" in installer
    assert r"Source: ..\dist\NTF Insight" in installer
    assert "NTF_INSIGHT_DATA_DIR" not in installer
    assert "UninstallDelete" not in installer


def test_windows_packaging_uses_pinned_python_runtime_and_checksum() -> None:
    script = (ROOT / "scripts/baue_windows_setup.ps1").read_text(encoding="utf-8")
    assert "sys.version_info[:2] == (3, 11)" in script
    assert "--onedir" in script
    assert "Get-FileHash" in script
    assert "NTF-Insight-Setup-" in script


def test_readme_has_end_user_setup_and_python_download() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Windows" in readme
    assert "NTF-Insight-Setup-" in readme
    assert "python-3.11.9-amd64.exe" in readme
    assert "## Ziele der App" in readme
