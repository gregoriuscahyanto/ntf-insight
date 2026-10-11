param(
    [Parameter(Mandatory = $true)]
    [string]$WheelPfad,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "Das Offline-Paket ist fuer Windows 64 Bit und Python 3.11 vorgesehen."
}

$repo = Split-Path -Parent $PSScriptRoot
$wheel = (Resolve-Path -LiteralPath $WheelPfad -ErrorAction Stop).Path
$datei = Split-Path $wheel -Leaf
if ($datei -notmatch '^ntf_insight-(\d+\.\d+\.\d+)-.*\.whl$') {
    throw "Erwartet wird eine Datei wie ntf_insight-0.1.0-py3-none-any.whl."
}
$version = $Matches[1]
& $Python -c "import sys, struct, pip; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8, 'Python 3.11 x64 erforderlich'"
if ($LASTEXITCODE -ne 0) { throw "Die angegebene Python-Installation ist nicht bereit." }

$paketOrdner = Join-Path $repo "dist\wheel-paket"
$ausgabeOrdner = Join-Path $repo "dist\offline"
$wheelOrdner = Join-Path $paketOrdner "wheels"
if (Test-Path -LiteralPath $paketOrdner) {
    Remove-Item -LiteralPath $paketOrdner -Recurse -Force
}
New-Item -ItemType Directory -Path $wheelOrdner -Force | Out-Null
New-Item -ItemType Directory -Path $ausgabeOrdner -Force | Out-Null

# Das bereits gebaute Wheel bestimmt die Abhaengigkeiten, nicht der Quellcode.
& $Python -m pip download --disable-pip-version-check --only-binary=:all: --dest $wheelOrdner $wheel
if ($LASTEXITCODE -ne 0) {
    throw "Eine oder mehrere Windows-Abhaengigkeiten konnten nicht als Wheel heruntergeladen werden."
}
Copy-Item -LiteralPath $wheel -Destination (Join-Path $wheelOrdner $datei) -Force
$appWheels = @(Get-ChildItem -LiteralPath $wheelOrdner -Filter "ntf_insight-*.whl" -File)
if ($appWheels.Count -ne 1) { throw "Genau ein NTF-Insight-Wheel ist erforderlich." }

Copy-Item -LiteralPath (Join-Path $repo "installer\wheel\installiere_offline.ps1") -Destination $paketOrdner
Copy-Item -LiteralPath (Join-Path $repo "installer\wheel\installiere_offline.cmd") -Destination $paketOrdner
Copy-Item -LiteralPath (Join-Path $repo "installer\wheel\LESMICH.txt") -Destination $paketOrdner
$zipName = "NTF-Insight-Wheel-Offline-$version-Windows-x64-Python311.zip"
$zipPath = Join-Path $ausgabeOrdner $zipName
Compress-Archive -Path (Join-Path $paketOrdner "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force
if (-not (Test-Path -LiteralPath $zipPath)) { throw "Offline-ZIP wurde nicht erstellt." }
if ((Get-Item -LiteralPath $zipPath).Length -ge 2GB) {
    throw "Offline-ZIP ist zu gross fuer ein GitHub-Release-Asset (2 GiB)."
}
$pruefsumme = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$pruefsumme  $zipName" | Set-Content -Path (Join-Path $ausgabeOrdner "SHA256SUMS-WHEEL.txt") -Encoding ascii
Write-Host "Offline-Paket fertig: $zipPath"
Write-Host "SHA256: $pruefsumme"
