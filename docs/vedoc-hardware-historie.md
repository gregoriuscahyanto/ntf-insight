# VeDoc: Hardware-Seriennummern und Änderungshistorien für frei gewählte Objekte

Der bisherige VeDoc-Exporter ist nicht mehr auf DCDC223 beschränkt. Du
bestimmst das **Objekt** und das **Attribut** aus dem VeDoc-Historienreiter
selbst. Es werden nur Zeilen mit passendem vollständigem FIN-, Objekt- und
Attributnamen übernommen.

**Kurz-FINs:** Die CLI akzeptiert auch die 14-stellige Mercedes-
Fahrzeugkennung (Baumuster + individuelle Kennung) ohne zusätzlichen WMI-Präfix.
Der Browser sucht exakt diesen Wert. Angezeigte 17-stellige VeDoc-FINs
werden anhand der letzten 14 Zeichen verglichen. Ist die Zuordnung
mehrdeutig oder liefert VeDoc keine bestätigte FIN, wird das
Ergebnis nicht als bestätigt ausgegeben. Andere Datenquellen sind
hierdurch nicht automatisch für Kurz-FINs freigeschaltet.

## Einmal installieren

Nach Aktualisierung des Repositorys in der aktiven Python-Umgebung:

```powershell
python -m pip install -e .
```

## Beispiele

**CPC3-Seriennummernhistorie:**

```powershell
ntf-insight-vedoc-historie --eingabe ".\FIN-Liste SensorIssue.txt" --objekt CPC3
```

**Anderes Historienattribut:**

```powershell
ntf-insight-vedoc-historie --eingabe ".\FIN-Liste SensorIssue.txt" --objekt CPC3 --attribut Hardwarestand
```

`Hardwarestand` ist hier nur ein **synthetisches Beispiel**. Der tatsächlich
verwendete Attributname muss genau so im VeDoc-Historienreiter stehen.

- `--objekt`: Freitext für den exakten VeDoc-Objektnamen; Alias `--steuergeraet`.
- `--attribut`: Freitext für das exakte VeDoc-Historienattribut; Standard `Seriennummer`.
- `--eingabe`: Pfad zu einer TXT-Datei mit jeweils einer vollständigen FIN pro Zeile.
- `--ausgabe`: optionaler Zielordner. Bei fehlender Angabe wird der Name der
  FIN-Liste in `data/processed/<Listenname>/` verwendet.
- `--login-manuell`, `--nur-login`, `--historie-wartezeit` und
  `--login-timeout` funktionieren wie beim bisherigen VeDoc-Skript.

Der alte Aufruf bleibt unverändert gültig:

```powershell
ntf-insight-vedoc-dcdc223 --eingabe .\fins.txt
```

Er nutzt standardmäßig `DCDC223` / `Seriennummer` und die alten Dateinamen
`dcdc223_seriennummern.json` sowie `dcdc223_seriennummern.xlsx`. Auch
dieser alte Befehl akzeptiert jetzt `--objekt` und `--attribut`.

## Parallel mit weiteren Datenquellen

```powershell
ntf-insight-beschaffung --eingabe .\fins.txt --quellen vedoc-historie,quicktests,wem --objekt CPC3 --parallel 3
```

Der Sammelabruf akzeptiert alternativ die historische Quellen-ID `dcdc223`.
Die Hardwareoptionen gehen **nur an die VeDoc-Historie**, nicht an QEC,
WEM, QuickTests oder andere Quellen. Für mehrere verschiedene Hardwareobjekte
separate Aufrufe verwenden.

## Ausgabe und Abgrenzung

Für `FIN-Liste SensorIssue.txt` und `--objekt CPC3`:

```text
data/
  processed/
    FIN-Liste SensorIssue/
      vedoc_historie/
        cpc3_seriennummern.json
        cpc3_seriennummern.xlsx
```

Bei `--attribut Hardwarestand` heißen die Dateien beispielsweise
`cpc3_hardwarestand.json` / `cpc3_hardwarestand.xlsx`. Ungewöhnliche
Zeichen im Objektnamen werden für Windows-sichere Dateinamen umgeschrieben
und bei Bedarf mit einem Kurz-Hash versehen, damit verschiedene Objekte
sich nicht gegenseitig überschreiben.

JSON enthält `objekt`, `attribut`, `letzter_neuer_wert` und alle Einträge
der Änderungshistorie mit altem und neuem Wert. Die früheren Felder
`steuergeraet` und `seriennummer` bleiben erhalten; bei anderen Attributen
als `Seriennummer` ist `seriennummer` in JSON leer, damit der Attributwert
nicht als Seriennummer fehlinterpretiert wird.

Die Excel-Datei enthält die Blätter `Uebersicht` und `Historie`;
für den alten DCDC223-Standard heißt das erste Blatt weiterhin `DCDC223`.

**Wichtig:** Der zuletzt dokumentierte neue Wert ist kein eigenständig
nachgewiesener aktueller Hardware-Einbauzustand. Keine gefundene Änderung
bedeutet nicht, dass die Hardware nicht verbaut ist. Die vorhandenen
Warte-/Nachprüfungsregeln schützen vor vorschnellen Negativbefunden.
SSO und PING ID bleiben unverändert; die PING-ID-Freigabe erfolgt
weiterhin manuell über das berechtigte Verfahren. Beim parallelen
CLI-Abruf mit einer oder mehreren der **sechs Datenquellen** werden
alle SSO-/PING-ID-Anmeldungen **nacheinander** ausgefuehrt; danach
laufen die eigentlichen FIN-Abfragen parallel.
Der Status fin_nicht_bestaetigt bedeutet, dass VeDoc **nach der
Anmeldung** die gesuchte Fahrzeugkennung nicht bestaetigt hat.
Bei 14-stelliger FIN kann eine fehlende Unterstuetzung dieser Kurzsuche
die Ursache sein; ggf. eine vollstaendige 17-stellige FIN testen oder
das Such-Timeout erhoehen.

Keine realen FINs, VeDoc-Ergebnisse oder SSO-Daten in GitHub einchecken.
Ein echter Live-Test eines anderen Objekts als DCDC223 muss im
berechtigten Unternehmensnetz durchgeführt werden.
