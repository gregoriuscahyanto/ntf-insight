param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "Das Windows-Setup kann nur unter Windows gebaut werden."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    # Anders als 'py -3.11' nutzt 'python' die aktive .venv bzw. setup-python.
    & $Python -c "import sys, struct; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8, 'Python 3.11 (64 Bit) erforderlich'"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 x64 nicht verfügbar. Nutze den GitHub-Workflow oder eine korrekt eingerichtete Python-Installation."
    }
    & $Python -m pip --version
    if ($LASTEXITCODE -ne 0) {
        throw "Pip fehlt in dieser Python-Installation. Nutze den GitHub-Workflow."
    }
    & $Python -c "import PyInstaller, ntf_insight, PySide6, polars, duckdb"
    if ($LASTEXITCODE -ne 0) {
        throw "Abhängigkeiten fehlen. Entwickler: python -m pip install -e '.[dev]' pyinstaller==6.22.3"
    }

    $version = (& $Python -c "import tomllib; from pathlib import Path; print(tomllib.loads(Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])").Trim()
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') {
        throw "Ungültige Versionsnummer in pyproject.toml."
    }

    $pyinstallerArgs = @(
        "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "NTF Insight",
        "--specpath", "build\spec",
        "--workpath", "build\pyinstaller",
        "--distpath", "dist",
        "--paths", "src",
        "--collect-submodules", "ntf_insight",
        "--collect-all", "duckdb",
        "--collect-all", "polars",
        "--collect-all", "pyarrow",
        "--collect-all", "playwright",
        "--hidden-import", "PySide6.QtSvg",
        "src\ntf_insight\__main__.py"
    )
    & $Python -m PyInstaller @pyinstallerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller konnte die Anwendung nicht erstellen."
    }

    $appExe = Join-Path $repoRoot "dist\NTF Insight\NTF Insight.exe"
    if (-not (Test-Path $appExe)) {
        throw "Das erzeugte NTF Insight.exe wurde nicht gefunden."
    }

    $iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    $isccPath = if ($iscc) { $iscc.Source } else { $null }
    if (-not $isccPath) {
        $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
        $candidate = Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe"
        if (Test-Path $candidate) { $isccPath = $candidate }
    }
    if (-not $isccPath) {
        throw "Inno Setup 6 fehlt. Auf GitHub installiert der Release-Workflow es automatisch."
    }

    New-Item -ItemType Directory -Path "dist\installer" -Force | Out-Null
    & $isccPath "-dAppVersion=$version" "installer\ntf-insight.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup konnte das Windows-Setup nicht erstellen."
    }

    $setupPath = Join-Path $repoRoot "dist\installer\NTF-Insight-Setup-$version.exe"
    if (-not (Test-Path $setupPath)) {
        throw "Setup-Datei fehlt: $setupPath"
    }
    if ((Get-Item $setupPath).Length -ge 2GB) {
        throw "Die Setup-Datei ist zu gross fuer ein GitHub-Release-Asset (max. unter 2 GiB)."
    }

    $sha256 = (Get-FileHash -Path $setupPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$sha256  $(Split-Path $setupPath -Leaf)" |
        Set-Content -Path (Join-Path $repoRoot "dist\installer\SHA256SUMS.txt") -Encoding ascii

    Write-Host "Windows-Setup erstellt: $setupPath"
    Write-Host "SHA256: $sha256"
}
finally {
    Pop-Location
}
