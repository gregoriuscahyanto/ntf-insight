<#
.SYNOPSIS
  Konfiguriert NTF Insight LOKAL fuer den GitHub-Runner ntf-insight-1.
.DESCRIPTION
  Speichert drei Pfade ausschliesslich in der lokalen Runner-.env.
  -AnalyseStarten fordert spaeter mit GitHub CLI einen manuellen Lauf an.
#>
[CmdletBinding()]
param(
    [string]$RunnerRoot = 'C:\Users\Cahyanto\actions-runner-ntf-1',
    [string]$PythonPath = '',
    [string]$DatabasePath = '',
    [string]$OutputDirectory = '',
    [switch]$NurPruefen,
    [switch]$AnalyseStarten,
    [switch]$SummenFreigeben,
    [switch]$MethodenFreigeben
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $RepoRoot '.venv\Scripts\python.exe'
}
if ([string]::IsNullOrWhiteSpace($DatabasePath)) {
    $DatabasePath = Join-Path $HOME '.ntf-insight\ntf-insight.duckdb'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $HOME '.ntf-insight\runner-analysen'
}

function FullPath([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value -match '[\r\n]') {
        throw 'Ungueltige lokale Pfadangabe.'
    }
    return [IO.Path]::GetFullPath($Value).TrimEnd('\')
}
function IsInDirectory([string]$Child, [string]$Parent) {
    $parentPath = $Parent.TrimEnd('\') + '\'
    return ($Child.Equals($Parent, [StringComparison]::OrdinalIgnoreCase) -or
        $Child.StartsWith($parentPath, [StringComparison]::OrdinalIgnoreCase))
}

$Root = FullPath $RunnerRoot
$Python = FullPath $PythonPath
$Database = FullPath $DatabasePath
$Output = FullPath $OutputDirectory
$Repository = FullPath $RepoRoot
$RunnerConfig = Join-Path $Root '.runner'
$EnvFile = Join-Path $Root '.env'
$RunCommand = Join-Path $Root 'run.cmd'

if (-not (Test-Path -LiteralPath $RunnerConfig -PathType Leaf) -or
    -not (Test-Path -LiteralPath $RunCommand -PathType Leaf)) {
    throw 'Runner ntf-insight-1 wurde am angegebenen Installationsort nicht gefunden.'
}
$Agent = Get-Content -LiteralPath $RunnerConfig -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Agent.agentName -ne 'vehicle-sim-windows-laptop') {
    throw 'Runner-Identitaet passt nicht zu ntf-insight-1. Runner 2 bleibt unberuehrt.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Lokales Python aus der vorbereiteten virtuellen Umgebung fehlt.'
}
if (-not (Test-Path -LiteralPath $Database -PathType Leaf)) {
    throw 'Bestehende NTF-DuckDB nicht gefunden. Bitte den lokalen Pfad angeben.'
}
if (IsInDirectory $Database $Repository) {
    throw 'NTF-Datenbank darf nicht im Git-Repository liegen.'
}
if ((IsInDirectory $Output $Repository) -or (IsInDirectory $Output $Root)) {
    throw 'Vertrauliche Ausgaben duerfen nicht in Git/Runner-Arbeitsverzeichnisse.'
}
if (IsInDirectory $Database $Output) {
    throw 'Ausgabeordner darf nicht die vorhandene Datenbank enthalten.'
}

# Only dependency imports are checked; no QEC/DTC data is read.
$null = & $Python -c 'import duckdb, sklearn, ntf_insight' 2>&1
if ($LASTEXITCODE -ne 0) {
    throw 'Python-Umgebung ist unvollstaendig. Lokal NTF Insight installieren.'
}
Write-Host 'NTF_RUNNER_VORAUSSETZUNGEN_OK'

if ($AnalyseStarten) {
    if ($NurPruefen) {
        throw 'Parameterkombination widerspruechlich.'
    }
    if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
        throw 'Runner noch nicht eingerichtet. Zuerst ohne -AnalyseStarten ausfuehren.'
    }
    $configured = Get-Content -LiteralPath $EnvFile -Encoding UTF8
    foreach ($key in @('NTF_INSIGHT_RUNNER_PYTHON',
                       'NTF_INSIGHT_RUNNER_DB',
                       'NTF_INSIGHT_RUNNER_REPORT_DIR')) {
        if (-not ($configured | Where-Object { $_.StartsWith("$key=") })) {
            throw 'Runnerkonfiguration fehlt; bitte Einrichtung zuerst ausfuehren.'
        }
    }
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw 'GitHub CLI (gh) fehlt. Nach Installation gh auth login ausfuehren.'
    }
    Write-Host 'Starte einen MANUELL autorisierten GitHub-Lauf auf main.'
    Write-Host 'Voraussetzung: Runner 1 wurde nach der Konfiguration neu gestartet.'
    $release = if ($SummenFreigeben) { 'true' } else { 'false' }
    $methods = if ($MethodenFreigeben) { 'true' } else { 'false' }
    & gh workflow run local-analysis.yml --repo gregoriuscahyanto/ntf-insight --ref main --field analyse_freigegeben=true --field "summen_in_actions_log_freigeben=$release" --field "methodenvergleich_freigeben=$methods"
    if ($LASTEXITCODE -ne 0) {
        throw 'GitHub-Lauf konnte nicht gestartet werden; gh auth und main pruefen.'
    }
    Write-Host 'NTF_GITHUB_ANALYSE_AUFTRAG_GESENDET'
    exit 0
}

if ($NurPruefen) {
    Write-Host 'NTF_RUNNER_TEST_OK_KEINE_KONFIGURATION_GEAENDERT'
    exit 0
}

# The GitHub runner loads the environment when it starts.
# No path is printed or copied into GitHub.
if (-not (Test-Path -LiteralPath $Output -PathType Container)) {
    $null = New-Item -ItemType Directory -Path $Output -Force
}
$Keys = @('NTF_INSIGHT_RUNNER_PYTHON',
          'NTF_INSIGHT_RUNNER_DB',
          'NTF_INSIGHT_RUNNER_REPORT_DIR')
$NewLines = [Collections.Generic.List[string]]::new()
if (Test-Path -LiteralPath $EnvFile -PathType Leaf) {
    foreach ($line in (Get-Content -LiteralPath $EnvFile -Encoding UTF8)) {
        $eq = $line.IndexOf('=')
        $key = if ($eq -ge 0) { $line.Substring(0, $eq).Trim() } else { '' }
        if ($Keys -contains $key) { continue }
        $NewLines.Add($line)
    }
}
$NewLines.Add("NTF_INSIGHT_RUNNER_PYTHON=$Python")
$NewLines.Add("NTF_INSIGHT_RUNNER_DB=$Database")
$NewLines.Add("NTF_INSIGHT_RUNNER_REPORT_DIR=$Output")

$Temporary = Join-Path $Root ('.env.ntf-' + [guid]::NewGuid().ToString('N') + '.tmp')
$Backup = Join-Path $Root ('.env.ntf-backup-' + (Get-Date -Format 'yyyyMMddHHmmss'))
try {
    [IO.File]::WriteAllLines(
        $Temporary, $NewLines.ToArray(), [Text.UTF8Encoding]::new($false)
    )
    if (Test-Path -LiteralPath $EnvFile -PathType Leaf) {
        [IO.File]::Replace($Temporary, $EnvFile, $Backup)
    }
    else {
        [IO.File]::Move($Temporary, $EnvFile)
    }
}
finally {
    if (Test-Path -LiteralPath $Temporary) {
        Remove-Item -LiteralPath $Temporary -Force
    }
}
Write-Host 'NTF_RUNNER_KONFIGURIERT_LOKAL'
Write-Host 'Bitte Runner 1 neu starten (interaktiv: Ctrl+C, danach run.cmd).'
Write-Host 'Bei Windows-Dienst: nur mit den vorgesehenen IT-Dienstrechten neu starten.'
Write-Host 'Danach kannst du die Analyse per -AnalyseStarten anfordern.'
Write-Host 'Standard: Keine Fallzahlen, Dokumente oder Reports in GitHub-Logs.'
