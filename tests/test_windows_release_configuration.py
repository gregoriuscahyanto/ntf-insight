"""Statische Schutzprüfungen für den Windows-Release-Build."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_release_is_manual_and_hosted() -> None:
    workflow = (ROOT / ".github/workflows/release-windows.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "refs/heads/main" in workflow
    assert "gh release create" in workflow
    assert "gh release upload" in workflow
    assert "self-hosted" not in workflow
    assert "persist-credentials: false" in workflow
    assert "NTF-Insight-Wheel-Offline-" in workflow
    assert "ntf-insight-wheel-gui-stderr.txt" in workflow
    assert "-RedirectStandardError" in workflow
    assert "NTF_WHEEL_IMPORT_OK" in workflow
    assert "paket:" in workflow
    assert "GH_TOKEN:" in workflow


def test_installer_creates_shortcuts_without_admin() -> None:
    installer = (ROOT / "installer/ntf-insight.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in installer
    assert r"{group}\NTF Insight" in installer
    assert r"{autodesktop}\NTF Insight" in installer
    assert r"..\dist\NTF Insight\*" in installer
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


def test_wheel_installer_is_offline_and_creates_shortcuts() -> None:
    script = (ROOT / "installer/wheel/installiere_offline.ps1").read_text(encoding="utf-8")
    assert "--no-index" in script
    assert "pip check" in script
    assert r"Scripts\pythonw.exe" in script
    assert "WScript.Shell" in script
    assert "Get-Command python.exe" in script
    assert "KeineVerknuepfungen" in script
    wrapper = (ROOT / "installer/wheel/installiere_offline.cmd").read_text(encoding="utf-8")
    assert "installiere_offline.ps1" in wrapper
    assert "ExecutionPolicy Bypass" not in wrapper


def test_wheel_bundle_can_use_existing_local_wheel() -> None:
    script = (ROOT / "scripts/baue_offline_wheel_paket.ps1").read_text(encoding="utf-8")
    assert "WheelPfad" in script
    assert "pip download" in script
    assert "--only-binary=:all:" in script
    assert "SHA256SUMS-WHEEL.txt" in script
    assert "Compress-Archive" in script


def test_oracle_self_hosted_runner_is_opt_in_smoke_only() -> None:
    workflow = (ROOT / ".github/workflows/oracle-build-smoke.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "ntf-build-oracle-x64" in workflow
    assert "permissions: {}" in workflow
    assert "actions/checkout" not in workflow
    assert "upload-artifact" not in workflow
    assert "pip install" not in workflow
