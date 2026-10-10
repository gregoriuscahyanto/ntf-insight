# Datensparsame Cluster-Ergebnisse zur gemeinsamen Auswertung

Die originale DuckDB mit QEC-/FIN-Daten bleibt **ausschließlich lokal**.
`scripts/cluster_ergebnisse_fuer_chatgpt.py` öffnet den bestehenden
Bestand **read_only=True** und berechnet die Szenarien für
**Kühlmittelpumpe, HDBSCAN Leaf/EOM, Complete-Link Cosinus 45 %/65 %**
auf der belegten Vor-Tausch-Diagnose.

**Wichtig:** Der Skriptlauf bildet die voreingestellte
Clusteranalyse **noch einmal neu**. Er liest nicht die gerade in der
Qt-GUI getätigte Auswahl aus. Daher gelten folgende Parameter:
`min_cluster_size=3`, `min_samples=2`, DTC-Quelle
`QuickTest + AutoExport (QEC-zugeordnet)`, gesamter belegter Zeitraum
vor Tausch, kein DTC-Häufigkeitsfilter. Beim Prüfen der
GUI-Zahlen bitte exakt diese Einstellungen benutzen.

## Auf dem eigenen Windows-Rechner ausführen

**GUI vorher schließen**, da die DuckDB bei gleichzeitigem Zugriff
gesperrt sein kann. Dann im Repository auf `main`:

```powershell
git switch main
git status
git fetch origin
git merge --ff-only origin/main
.\.venv\Scripts\python.exe .\scripts\cluster_ergebnisse_fuer_chatgpt.py
```

Das Skript erwartet die lokale Datenbank unter
`$HOME\.ntf-insight\ntf-insight.duckdb` oder verwendet optional die
lokale Umgebungsvariable `NTF_INSIGHT_RUNNER_DB`. Nur wenn die
Datenbank anderswo liegt:

```powershell
.\.venv\Scripts\python.exe .\scripts\cluster_ergebnisse_fuer_chatgpt.py --datenbank "C:\PRIVATE\ntf-insight.duckdb"
```

Diese privaten Pfade werden nicht ausgegeben oder in GitHub geloggt.

Die Konsole enthält **ausschließlich zwei Whitelist-JSON-Zeilen**:
`NTF_FREIGEGEBENE_SUMMEN_JSON=` (die bestehenden zehn
Aggregatsummen), `NTF_FREIGEGEBENER_METHODENVERGLEICH_JSON=`
(bisher separate methodische Aggregatzahlen) und den festen
Erfolgsmarker `NTF_CLUSTER_STATUS_OK_NUR_LOKAL_READ_ONLY`.
Die Kennzahlen wurden im Projekt bereits in einzelnen manuellen
GitHub-Actions-Läufen ausdrücklich freigegeben.
**Es erfolgt aber keine automatische Veröffentlichung.**
Vor dem Einfügen in einen Chat bitte selbst prüfen,
ob eine Freigabe nach den geltenden Unternehmensregeln vorliegt.

Für die **kleine Kernprüfgruppe K1** kann die Ausgabe nach einer
**separaten internen Freigabe** um eine dritte Zeile erweitert werden:

```powershell
.\.venv\Scripts\python.exe .\scripts\cluster_ergebnisse_fuer_chatgpt.py --k1-zahlen-nach-freigabe
```

`NTF_K1_NUMERISCHE_DETAILS_NACH_FREIGABE_JSON=` enthält
**nur Ganzzahlen und boolesche Werte**, etwa:
QEC-Fälle, unterschiedliche FINs **nur als Anzahl**,
Anzahl der gemeinsamen ECU:DTC-Muster, davon CPC3,
Mindestpaarähnlichkeit in Promille,
Vorhandensein einer vollständigen Zugehörigkeit zu einem
Leaf-Cluster und Anzahl der Überschneidungen.
Es enthält **keine** originalen ECU-/DTC-Schlüssel,
FINs, QEC-IDs, SSL-Endbefundtexte,
Pfade, Laborberichte oder individualisierbare Clusterlisten.

**Auch Kennzahlen über nur drei Fahrzeuge können intern
vertraulich sein!** Die K1-Option ist daher nicht automatisch aktiv,
wird nicht in GitHub Actions ausgelöst und darf nicht ohne
einschlägige interne Freigabe geteilt werden.

Weder Skript noch CI schreiben Originaldaten in den
Repository-Checkout, GitHub Actions, Artefakte oder Chat.
Es werden keine Berichte auf die Platte exportiert.
Das Skript gibt auch im Fehlerfall nur eine generische Meldung aus.

## So kannst du die GUI dazu kurz beschreiben

Nach Vergleich der Konsole mit der lokalen GUI kannst du zusätzlich
**ohne FINs/IDs und ohne konkrete DTCs** schreiben:

- Clusterzahlen gleich wie in der GUI? **Ja / Nein**
- Fünf Kernprüfgruppen sichtbar? **Ja / Nein / andere Anzahl**
- K1 lässt sich anwählen und erscheinen darunter Fälle? **Ja / Nein**
- 2D und 3D bedienbar, insbesondere Auswahl und Zoom? **Ja / Nein**
- Sonstige GUI-Probleme **ohne** screenshot mit Originaldaten beschreiben

Die Kernprüfgruppe `K1` hat **keine zeitübergreifend stabile
Identität**: Bei veränderten Daten oder Schwellen kann sie aus anderen
Fällen bestehen. Aus der reinen DTC-Ähnlichkeit lässt sich weder
NTF noch eine Lieferantenursache oder ein Wiederauftreten nach Tausch
sicher ableiten.

## Datensicherheit

Eine rohe GUI-Tabelle, Screenshot mit FIN, JSON aus
`runner-analysen\NTF_Lauf_*` oder CSV wie
`pilot_fachpruefung_FIN_SSL_NICHT_HOCHLADEN.csv`
**niemals ungeprüft weitergeben**.
Nur die explizit zulässigen, manuell geprüften Konsolenzeilen
sind zur Weitergabe vorgesehen.
