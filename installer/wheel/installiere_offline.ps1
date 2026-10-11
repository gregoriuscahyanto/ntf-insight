param(
    [string]$Installationsordner = (Join-Path $env:LOCALAPPDATA "Programs\NTF Insight (Wheel)"),
    [switch]$KeineVerknuepfungen
)

$ErrorActionPreference = "Stop"

try {
    if ($env:OS -ne "Windows_NT") {
        throw "Dieses Installationspaket ist nur fuer Windows geeignet."
    }

    $wheelOrdner = Join-Path $PSScriptRoot "wheels"
    if (-not (Test-Path -LiteralPath $wheelOrdner -PathType Container)) {
        throw "Ordner 'wheels' fehlt. Bitte das vollstaendige Offline-ZIP entpacken."
    }
    $appWheels = @(Get-ChildItem -LiteralPath $wheelOrdner -File -Filter "ntf_insight-*.whl")
    if ($appWheels.Count -ne 1) {
        throw "Es muss genau ein NTF-Insight-Wheel im Ordner 'wheels' liegen."
    }
    if ($appWheels[0].Name -notmatch '^ntf_insight-(\d+\.\d+\.\d+)-') {
        throw "Die Versionsnummer des NTF-Insight-Wheels ist nicht erkennbar."
    }
    $version = $Matches[1]

    # Die Python-Launcher-Auswahl 'py -3.11' kann auf defekte Runner-Pythons zeigen.
    # Deshalb zuerst gewoehnliche Installationen und erst danach den Launcher pruefen.
    $pythonPfade = [Collections.Generic.List[string]]::new()
    if ($env:NTF_INSIGHT_PYTHON311) { $pythonPfade.Add($env:NTF_INSIGHT_PYTHON311) }
    $pythonPfade.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"))
    $pythonPfade.Add((Join-Path $env:ProgramFiles "Python311\python.exe"))
    foreach ($registry in @(
        "HKCU:\Software\Python\PythonCore\3.11\InstallPath",
        "HKLM:\Software\Python\PythonCore\3.11\InstallPath"
    )) {
        if (Test-Path -LiteralPath $registry) {
            $base = (Get-Item -LiteralPath $registry).GetValue("")
            if ($base) { $pythonPfade.Add((Join-Path $base "python.exe")) }
        }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $pythonPfade.Add($command.Source) }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $found = & $launcher.Source -3.11 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) {
                $pythonPfade.Add(([string]($found | Select-Object -Last 1)).Trim())
            }
        }
        catch { }
    }

    $python = $null
    foreach ($candidate in ($pythonPfade | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            & $candidate -c "import sys, struct, pip, venv; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
        }
        catch { }
    }
    if (-not $python) {
        throw "Python 3.11 (64 Bit) mit pip fehlt. Bitte zuerst die verlinkte Python-Version installieren oder das Windows-Setup ohne Python nutzen."
    }

    New-Item -ItemType Directory -Path $Installationsordner -Force | Out-Null
    $venvOrdner = Join-Path $Installationsordner "venv"
    $venvPython = Join-Path $venvOrdner "Scripts\python.exe"
    $venvPythonW = Join-Path $venvOrdner "Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Write-Host "Richte die virtuelle Umgebung ein ..."
        & $python -m venv $venvOrdner
        if ($LASTEXITCODE -ne 0) { throw "Die virtuelle Umgebung konnte nicht erstellt werden." }
    }
    Write-Host "Installiere NTF Insight $version ohne Internet ..."
    & $venvPython -m pip install --disable-pip-version-check --no-index --find-links $wheelOrdner --upgrade "ntf-insight==$version"
    if ($LASTEXITCODE -ne 0) { throw "Die Offline-Installation ist fehlgeschlagen." }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Python-Abhaengigkeiten sind unvollstaendig." }
    if (-not (Test-Path -LiteralPath $venvPythonW -PathType Leaf)) {
        throw "Pythonw fehlt in der virtuellen Umgebung."
    }

    if (-not $KeineVerknuepfungen) {
        $shell = New-Object -ComObject WScript.Shell
        $startMenue = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\NTF Insight"
        New-Item -ItemType Directory -Path $startMenue -Force | Out-Null
        $ziele = @((Join-Path $startMenue "NTF Insight (Wheel).lnk"))
        $desktop = [Environment]::GetFolderPath("Desktop")
        if ($desktop -and (Test-Path -LiteralPath $desktop)) {
            $ziele += (Join-Path $desktop "NTF Insight (Wheel).lnk")
        }
        foreach ($ziel in $ziele) {
            $shortcut = $shell.CreateShortcut($ziel)
            $shortcut.TargetPath = $venvPythonW
            $shortcut.Arguments = "-m ntf_insight"
            $shortcut.WorkingDirectory = $Installationsordner
            $shortcut.Description = "NTF Insight starten"
            $shortcut.Save()
        }
    }
    Write-Host ""
    Write-Host "NTF INSIGHT INSTALLIERT: Version $version"
    if (-not $KeineVerknuepfungen) {
        Write-Host "Start ueber die Desktop- oder Startmenue-Verknuepfung 'NTF Insight (Wheel)'."
    }
}
catch {
    Write-Host ("FEHLER: " + $_.Exception.Message)
    exit 1
}
