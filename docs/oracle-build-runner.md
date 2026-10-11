# Oracle-Linux-Runner für NTF Insight

## Einschätzung

Im Repository `gregoriuscahyanto/Vehicle_Performance_Simulation` sind zwei Oracle-Linux-Runner konfiguriert:

- `vehicle-sim-oracle`: Linux ARM64
- `vehicle-sim-oracle-x64`: Linux X64

Diese Runner werden im anderen Projekt bereits für CI und Daten-/Simulationsaufgaben verwendet. Ihre Daten- und Credential-Isolation zu NTF Insight ist **nicht nachgewiesen**. Sie dürfen deshalb **nicht einfach für NTF Insight freigeschaltet oder umgehängt** werden.

**PyInstaller ist kein Cross-Compiler.** Ein Windows-Setup muss auf Windows entstehen. Oracle Linux eignet sich später für reine Python-Wheels und Prüfungen; Windows-Abhängigkeiten müssten gezielt für Windows x64 / CPython 3.11 bezogen und auf Windows getestet werden.

## Sicherer Anschluss

Die manuelle [Windows-Release-Pipeline](../.github/workflows/release-windows.yml) nutzt zunächst nur den GitHub-gehosteten Windows-Runner. Die vertraulichen Runner `ntf-insight-1` und `ntf-insight-2` werden nicht eingesetzt.

1. **Eine eigene isolierte Oracle-VM** für NTF-Builds bereitstellen. Sie darf keinen Zugriff auf interne Fahrzeugdaten, bestehende Runner-Arbeitsverzeichnisse, SSH-Schlüssel, Datenmounts oder produktive Credentials haben. Ein neues Label auf demselben Benutzerkonto schafft **keine** Isolation.
2. IT-/Informationsschutzfreigabe einholen. VM, Firewall, IAM, Paketquellen und Benutzerrechte müssen freigegeben sein.
3. In [NTF Insight → Settings → Actions → Runners](https://github.com/gregoriuscahyanto/ntf-insight/settings/actions/runners) **New self-hosted runner → Linux / x64** wählen.
4. Die **von GitHub aktuell angezeigten** Installationsbefehle auf der separaten VM ausführen. Nicht die bestehende VPS-Runner-Installation oder deren Registrierung übernehmen. Bei `config.sh` den Namen `ntf-oracle-build` und das zusätzliche Label **`ntf-build-oracle-x64`** verwenden.
5. Runner unter einem eigenen, minimal berechtigten Linux-Benutzer starten. Den zeitlich begrenzten Registrierungstoken niemals in Chat, Repos oder Logs kopieren.
6. [Actions → Oracle Build Runner Verbindungstest](https://github.com/gregoriuscahyanto/ntf-insight/actions/workflows/oracle-build-smoke.yml) auf `main` manuell starten. Der Test führt **keinen Checkout aus**, liest keine Dateien und lädt nichts hoch.

Die bloße Registrierung oder der Verbindungstest ist **noch keine Freigabe für Build-Jobs**. Ein Wheel-Build-Workflow auf Oracle sollte erst nach bestandener Isolation und IT-Freigabe aktiviert werden. Das Windows-Setup und das vollständige Windows-Offline-Paket bleiben bis dahin auf dem GitHub-Windows-Runner.

GitHub-Runner auf Repository-Ebene gehören jeweils zu einem Repository. In einer Organisation lassen sich Runner über ausdrücklich zugelassene Repository-Zugriffsgruppen teilen. Für die beiden bestehenden persönlichen Repositories ist eine **neue Registrierung auf einer isolierten VM** die passende Variante.

[Offizielle GitHub-Anleitung](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/add-runners) · [Sicherheitsreferenz](https://docs.github.com/en/actions/reference/security/secure-use)
