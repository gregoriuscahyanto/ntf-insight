# Einfache Webscraper-GUI

Das separate Fenster startet die sechs vorhandenen CLI-Downloader und verwendet eine reduzierte schwarz-weiß-graue Gestaltung ohne zusätzliche Markenassets.

## Start (Python 3.11 / Windows PowerShell)

```powershell
python -m pip install -e .
ntf-insight-scraper
```

Alternativ: `python -m ntf_insight.app.scraper_gui`.

Die GUI ist derzeit für Python-/Wheel-Installationen vorgesehen und noch nicht in das vorhandene PyInstaller-Setup integriert.

## Bedienung

1. **TXT-Datei auswählen** öffnet den lokalen Windows-Dateidialog.
2. Eine TXT-Datei mit einer FIN je Zeile auswählen. TIPS akzeptiert alternativ eine Liste numerischer Fallnummern.
3. Auf den Button der gewünschten Quelle klicken: QEC, QuickTests, TIPS Writer, WEM, VeDoc-Fahrzeugcodes oder VeDoc-Hardwarehistorie.
   Bei **QEC** öffnet sich vorher ein Dialog für den optionalen **Benennungsfilter**.
   Dort z. B. `DCDC`, `DCDC223` oder `DCDC,DC/DC` eingeben und mit OK bestätigen.
   Mit **Abbrechen** wird kein Scraper gestartet.
4. Bei Bedarf die SSO-/PING-ID-Anmeldung im sichtbaren Edge durchführen.
5. Den Status im unteren Fensterbereich verfolgen oder den Vorgang abbrechen.

Es läuft immer nur ein Abruf gleichzeitig. Die Eingaben werden vom bestehenden CLI-Parser geprüft; die Oberfläche verändert keine Webscraper-Logik.

Der QEC-Dialog setzt den bestehenden CLI-Parameter `--benennung`. Der Suchbegriff
wird auf die **Bauteilbenennung der QEC-Suchergebnisse** angewendet, nicht als
zusätzlicher FIN-Suchwert im QEC-Portal eingegeben. `DCDC` umfasst z. B. auch
`DCDC223`; mit `DCDC223` lässt sich die Auswahl enger fassen. Mehrere Suchtexte
werden mit Komma als ODER-Auswahl eingegeben (`DCDC,DC/DC`).

**Leeres QEC-Eingabefeld:** Der vorhandene Standardfilter für
**Kühlmittelpumpen** bleibt aktiv. Deshalb können DCDC-Schadteilfälle trotz
QEC-Treffern ausgefiltert werden. Der zuletzt akzeptierte Suchbegriff wird
während der Fensterlaufzeit im nächsten QEC-Dialog vorbelegt (nicht dauerhaft
gespeichert). Andere Datenquellen erhalten keine QEC-Filter.

Die VeDoc-Hardwarehistorie nutzt weiterhin DCDC223 / Seriennummer. Spezielle
Filter (z. B. CPC3, Sachnummern, Anhangmodus) sind weiterhin über die CLI
verfügbar: [Datenbeschaffung](datenbeschaffung-cli.md).

Die Downloads werden ausschließlich lokal unter `%USERPROFILE%\.ntf-insight\abrufe\<TXT-Name>\<Quelle>` gespeichert. Die Basis lässt sich über `NTF_INSIGHT_DATA_DIR` ändern. FINs, Reports, Passwörter und Cookies gehören nicht ins GitHub-Repository.

Der Abruf erfordert Microsoft Edge, Unternehmenszugang und die Berechtigung für die jeweilige Quelle. Die Oberfläche wurde nicht gegen echte interne Portale getestet.
