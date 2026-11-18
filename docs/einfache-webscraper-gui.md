# Einfache Webscraper-GUI – Optionen pro Datenquelle

Das separate Fenster startet die sechs bestehenden CLI-Downloader von NTF Insight.
Die Bedienung ist deutsch und benutzt eine zurückhaltende schwarz-weiß-graue Gestaltung.
Die CLI-Module, Anmeldung, FIN-Prüfung und Download-/Wiederaufnahmelogik bleiben erhalten.

## Start (Python 3.11 / Windows PowerShell)

```powershell
git switch main
git pull origin main
python -m pip install -e .
ntf-insight-scraper
```

Alternativ: `python -m ntf_insight.app.scraper_gui`.
Die Lightweight-GUI setzt eine Python-/Wheel-Installation voraus und ist derzeit
kein eigener Startknopf im bestehenden PyInstaller-Setup.

## Bedienung

1. **TXT-Datei auswählen**: lokalen Dateidialog für FINs (bei TIPS alternativ Fallnummern) öffnen.
2. Einen der sechs **Webscraper-Buttons** anklicken. **Jede Quelle** öffnet jetzt
   einen Einstellungsdialog mit ihren eigenen optionalen CLI-Parametern.
3. Gewünschte Felder ändern und **Abruf starten** drücken. **Abbrechen** schließt
   den Dialog, ohne einen neuen Prozess zu starten.
4. Gegebenenfalls SSO-/PING-ID-Anmeldung in Microsoft Edge bestätigen.
5. Die Statuszeile beobachten oder den Abruf abbrechen. Es läuft höchstens
   **ein** Quellenprozess gleichzeitig.

Die zuletzt bestätigten Optionen werden **pro Datenquelle nur während der
aktuellen Fensterlaufzeit** vorbelegt. Nicht geänderte Felder benutzen die
bestehenden CLI-Standardwerte. Es werden keine Shell-Befehle aus Nutzereingaben
erzeugt: Nur vorher definierte Flags werden als separate Prozessargumente übergeben.

## Parameter in den Dialogen

| Quelle | Verfügbare Einstellungen |
| --- | --- |
| **QEC** | Benennungsfilter (`--benennung`), Sachnummer, `--alle-bauteile`, **Anhangmodus `referenz`/`alle`**, SSO-Timeout, eigener Profilordner, manueller Login, Ausgabeort |
| **Diagnosis Viewer – QuickTests** | Erneut herunterladen, nur PDF (`--ohne-json`), SSO-Timeout, Profil, manueller Login, Ausgabeort |
| **XENTRY TIPS Writer** | SSO-Timeout, Profil, manueller Login, Ausgabeort (Eingabe über den globalen TXT-Dialog) |
| **Diagnosis Viewer – WEM** | Neue Sitzungen (`--aktualisieren`), erneut lesen, zusammenfassen, aufteilen, ohne Gesamt-JSON, nur Login, SSO-Tresor, Browser, vier Zeit-/Abstandsparameter, Profil, manueller Login, Ausgabeort |
| **VeDoc – Fahrzeugcodes** | Erneut lesen, nur Login, Anmelde-/Ladezeit, Pause, Profil, manueller Login, Ausgabeort |
| **VeDoc – Hardwarehistorie** | Objekt (z. B. `CPC3`), Attribut, nur Login, Browser, Schritt-/Login-/Historien-Timeout, alternative freigegebene URL, manueller Login, Ausgabeort |

**QEC-Anhänge:** `referenz` ist die sichere Voreinstellung: Nur Dateien,
deren sichtbarer Dateiname die aktuelle QEC-Referenznummer bestätigt, werden
heruntergeladen. **`alle` lädt alle vom Downloader erkannten und im Popup
des jeweiligen passenden Schadteilfalls sichtbaren Anhänge**.
Ein sichtbarer Anhang ist dadurch nicht automatisch fachlich genau diesem
Fall zugeordnet; solche Dateien bleiben im `qec.json` als ungeprüft markiert.
Beispiel für DCDC: **QEC → Benennung `DCDC` → Anhänge `Alle im Fall-Popup sichtbaren Anhänge` → Abruf starten**.

**QEC-Filter:** Ohne Benennung und Sachnummer greift wie bisher der
Kühlmittelpumpen-Standardfilter. `DCDC` umfasst z. B. `DCDC223`.
Ein Komma verbindet alternative Benennungen durch ODER (`DCDC,DC/DC`).
Eine zusätzlich angegebene exakte Sachnummer wirkt als UND.

**Pfadoptionen:** Standardmäßig werden Downloads lokal unter
`%USERPROFILE%\.ntf-insight\abrufe\<TXT-Name>\<Quelle>` abgelegt
(oder unter `NTF_INSIGHT_DATA_DIR`, falls konfiguriert).
Ein optionaler anderer Ausgabeort kann im Popup ausgewählt werden.
WEM und VeDoc-Fahrzeugcodes benötigen als Ziel eine **`.json`-Datei**;
die anderen Quellen verwenden **Verzeichnisse**.
Browserprofile und Berichtsordner müssen voneinander getrennt bleiben.

**Sicherheit / Grenze:** Die Terminal-Parameter `--passwort-abfragen` und
`--benutzer-id` werden bewusst **nicht** im Popup angeboten: Der bestehende
CLI-Prozess wird ohne interaktives Terminal gestartet, und ein geheimer
Passwortwert darf nicht als Kommandozeilenargument oder Log erscheinen.
Stattdessen im Unternehmens-Browser manuell anmelden oder das unterstützte
Betriebssystem-Schlüsselspeicherverfahren verwenden. Für direkte
Passwortabfrage muss die betreffende CLI in PowerShell gestartet werden.

Ungültige Optionen (z. B. WEM `--sso-tresor` zusammen mit
`--login-manuell` oder gleichzeitig `--nur-aufteilen` und
`--nur-zusammenfassen`) werden vor dem Download abgelehnt.
Der Zugriff auf interne Portale erfordert weiterhin Microsoft Edge bzw.
den ausgewählten Browser, Unternehmenszugang und die nötigen Berechtigungen.
Keine realen FINs, Berichte, Browserprofile oder Zugangsdaten in GitHub speichern.

## Regressionstests (ohne Unternehmenszugang)

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_scraper_gui.py
```

Die Tests überprüfen Dialoge und lokale CLI-Befehlsübergabe, nicht das echte
QEC-/TIPS-/VeDoc-Portal. Live-Abnahmen müssen auf einem berechtigten Arbeitsplatz erfolgen.
