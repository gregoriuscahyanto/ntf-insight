<#
.SYNOPSIS
  Bereinigt ausschliesslich alte NTF-Insight-CI-Artefakte per GitHub CLI.

.DESCRIPTION
  Benutzt das vorhandene, lokal mit "gh auth login" angemeldete Konto.
  Ohne -Loeschen gibt es NUR eine Vorschau. Keine Secrets im Skript,
  keine Uploads und KEIN GitHub Actions Runner erforderlich.
  GitHub kann mehrere Stunden brauchen, um Speicherzahlen anzuzeigen.

.EXAMPLE
  .\scripts\bereinigung_actions_artifacts.ps1
  .\scripts\bereinigung_actions_artifacts.ps1 -Loeschen
#>
[CmdletBinding()]
param(
    [switch]$Loeschen
)

$ErrorActionPreference = "Stop"
$repo = "gregoriuscahyanto/ntf-insight"
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI fehlt. Bitte https://cli.github.com/ installieren."
}
& gh auth status --hostname github.com | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Bitte 'gh auth login' ausfuehren. Token niemals in Chat/Logs teilen."
}

# Nur wegwerfbare CI-Reports und lokal neu erstellbare Wheel-Pakete.
# Fuer andere Workflow-Artefakte keine Berechtigung zur Loeschung ableiten.
$allowed = '^(reports-(Linux|Windows)|ntf-insight-wheel-(Linux|Windows))$'
$all = [System.Collections.Generic.List[object]]::new()
$page = 1
do {
    $json = & gh api -H "Accept: application/vnd.github+json" "repos/$repo/actions/artifacts?per_page=100&page=$page"
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub API konnte die Artefaktliste nicht lesen (Seite $page)."
    }
    $response = $json | ConvertFrom-Json
    $batch = @($response.artifacts | Where-Object { $null -ne $_ })
    foreach ($artifact in $batch) {
        if ($artifact.name -match $allowed -and -not $artifact.expired) {
            $all.Add($artifact)
        }
    }
    $page++
} while ($batch.Count -eq 100)

$artifacts = @($all | Sort-Object -Property created_at)
$bytes = ($artifacts | Measure-Object -Property size_in_bytes -Sum).Sum
if (-not $bytes) { $bytes = 0 }
Write-Output ("Repository: " + $repo)
Write-Output ("CI-Artefakte: " + $artifacts.Count)
Write-Output ("Zusammen: {0:N1} MiB" -f ($bytes / 1MB))
if (-not $Loeschen) {
    Write-Output "VORSCHAU: Noch nichts geloescht."
    Write-Output "Nur die oben genannten, gefilterten Reports/Wheels koennen entfernt werden."
    Write-Output "Zum Loeschen: .\scripts\bereinigung_actions_artifacts.ps1 -Loeschen"
    exit 0
}

$deleted = 0
$errors = 0
foreach ($artifact in $artifacts) {
    # GH token requires repo Actions:write. Do not echo the token.
    & gh api --method DELETE "repos/$repo/actions/artifacts/$($artifact.id)" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $deleted++
    } else {
        $errors++
        Write-Warning ("Artefakt " + $artifact.id + " nicht geloescht.")
    }
}
Write-Output ("CI-Artefakte geloescht: " + $deleted)
if ($errors -gt 0) {
    throw "$errors Artefakte konnten nicht geloescht werden. Bitte GitHub-Rechte pruefen."
}
