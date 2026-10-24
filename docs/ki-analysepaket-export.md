# KI-Analysepaket für fallübergreifende NTF-Clusterung

## Zwei verschiedene Exportzwecke

| Export | Im Paket | Zweck |
|---|---|---|
| **Gesamtstand** (`.ntfbackup`) | DuckDB und vollständige Rohdateien | Privater Datentransfer zwischen zugelassenen Rechnern |
| **KI-Analysepaket** (`.zip`) | Strukturierte Daten, Excel-Überblick und Methodik | Kompaktes Analyse-/Clusterinput-Paket |
| **Technische Grundlagen** (separate ZIP) | Netzwerktopologie, Setzbedingungen, ECU-Nachrichten, CDD, Kühlungsschema und HW-Update-Historie | Sachliche Ergänzung, nicht aus NTF-Insight erzeugt |

Die KI-Analyse-ZIP ist **kein** vollständiges Backup. Sie enthält **keine**
QuickTest-PDFs, QEC-/TIPS-Rohdateien, Anhänge, SMR-D-XML/JSON oder Originalpfade.
Bereits extrahierte Daten sind zur fallbezogenen Analyse als Tabellen verfügbar.

## Bedienung

Unter **Datenquellen**:

1. **Lightweight KI-Analysepaket als ZIP exportieren…** auswählen.
2. **QEC-/TIPS-Originalfreitext beifügen** ist standardmäßig deaktiviert.
3. ZIP in einem zulässigen lokalen Ordner speichern.
4. Die App erzeugt **zwei getrennte Dateien**:
   - `NTF-Insight-KI-Analyse-….zip` = KI-Analysepaket
   - `NTF-Insight-KI-Analyse-…_NICHT_HOCHLADEN_ZUORDNUNG.csv`
     = **private Zuordnung** der Pseudonyme zu echten FINs, Fällen,
       QEC-Referenzen und Teilenummern. **Niemals hochladen.**
5. Prüfen, ob eine Freigabe zur Weitergabe der strukturierten technischen
   Daten an den vorgesehenen Dienst besteht. Pseudonymisierung ist
   **keine** garantierte Anonymisierung.

## ZIP-Struktur

| Datei | Zweck |
|---|---|
| `Auswertung.xlsx` | Übersicht, Fallliste, Falldaten, Belege, Methodik – an die bisherige QEC-Excel-Struktur angelehnt |
| `cluster_input.csv` | **Explizite Vor-Tausch-Cluster-Eingaben**, ohne NTF-, Lieferanten- oder Nach-Tausch-Ergebnisse |
| `fahrzeuge.csv` | Eine Zeile je pseudonymisierter FIN, auch ohne QEC-Fall |
| `faelle.csv` | Fälle mit Fall-ID, Fahrzeug-ID, QEC-Verfügbarkeit und Quellenabdeckung |
| `fallmerkmale.csv` | Fallkontext **inklusive Nach-Tausch-Daten** – nur für spätere Validierung, nicht ungeprüft als Cluster-Matrix |
| `quicktests.csv` | Eine Zeile pro eingelesenem QuickTest (ohne PDF-Rohtext) |
| `quicktest_fallbezug.csv` | Vor-/Nach-/gleichdatiger oder unbekannter Bezug zwischen QuickTest und Pumpentausch |
| `dtc_beobachtungen.csv` | ECU, DTC-Code, Status, Häufigkeit und QuickTest-Pseudonym |
| `ecu_staende.csv` | Software-/Hardwarestände aus QuickTests, soweit technisch sicher als Code darstellbar |
| `qec_berichte.csv` | QEC-JSON-Berichte, Verknüpfung mit Fällen, Reiter-Vollständigkeit und Befundumfang |
| `qec_felder.csv` | QEC-Felder/Tabellen: Reiter, Feldtyp und technisch eindeutige Ja/Nein-/Zahlenwerte |
| `tips.csv` | Verknüpfte TIPS-Beobachtungen und Verfügbarkeit von Beschwerde/Werkstatt/Maßnahme |
| `smrd_bestand.csv` | SMR-D-Quelleninventar, **keine vorgetäuschte SMR-D-Feature-Extraktion** |
| `bewertungen_NICHT_CLUSTER.csv` | Fachlich bewertete Ursachen/Lieferantenbefunde: ausschließlich nach dem Clustering ansehen |
| `autoexport_diagnosen.csv` | ECU:DTC-Diagnosezeilen aller importierten AutoExport-FINs; Zeit, Kilometer, ECU-SW-/HW-Versionen und Quelle |
| `autoexport_fallbezug.csv` | Explizite Vor-/Nach-/unklare Zeitlage jeder AutoExport-Diagnose je Fall |
| `werkstatt_historie.csv` | AutoExport-Werkstatt- und Claimdaten; originale Beanstandungs-/Maßnahmentexte nur bei Freitext-Opt-in |
| `autoexport_tips.csv` | Auch bisher unverbundene TIPS-Rohvorgänge mit vorsichtigen Fallkandidaten; Freitext nur Opt-in |
| `pumpentausch_historie.csv` | Dokumentierte Tauschereignisse, pseudonymisierte Teile-/Lieferanten-/Serien- und Chargenkennungen |
| `fall_ereignisse.csv` | Lokal vorhandene Diagnose-, Reparatur-, ECU- und Software-Ereignisse, getrennt von AutoExport-Rohzeilen |
| `ecu_versionshistorie.csv` | Fahrzeug-/Fallbezogene Hardware-/Softwarebeobachtungen aus AutoExport und Fallereignissen |
| `diagnose_qualitaet.csv` | Abdeckung mit Vor-/Nachtests, fehlenden Tests und positiven AutoExport-Beobachtungen |
| `lieferantenbefunde_NICHT_CLUSTER.csv` | Bereits im Fallmodell vorhandene Lieferantenbefunde – nur nach dem Clustering für die Ursachenprüfung |
| `lieferantenquellen_bestand_NICHT_CLUSTER.csv` | Inventar separat gespeicherter Lieferantenquellen, keine Originalbytes |
| `methodik.csv`, `README.txt`, `manifest.json` | Interpretation, Datenlücken, Version und Integritätsangaben |

**Erweiterung ab Paketversion 3:** Der Export umfasst nun auch FINs, die nur in
AutoExport-Quellen vorkommen. Die zusätzlichen Diagnosezeilen werden nicht als
vollständige QuickTests interpretiert. Insbesondere fehlt bei AutoExport-DTC-only-Quellen
der Beleg eines tatsächlich DTC-freien Nachtests. Die zusätzlichen
`*_NICHT_CLUSTER.csv`-Dateien bleiben strikt außerhalb der Clusterfeatures.

**Fallzuordnung:** `fahrzeug_id` verknüpft unabhängige QuickTests und QEC
mit ihren Fahrzeugen. `fall_id` identifiziert den Schadteilfall.
`quicktest_fallbezug.csv` klassifiziert den zeitlichen Bezug eines Tests
zu jedem Fall getrennt. Dadurch können mehrere Schadteilfälle derselben
FIN unabhängig voneinander betrachtet werden.

**Zusätzliche technische Merkmale aus AutoExport:** Nur
`autoexport_diagnosen.csv` mit `autoexport_fallbezug.csv` und
`lage_zum_pumpentausch=vor_tausch` als technische DTC-Clustermerkmale
verwenden. Lieferantenbefunde, Austausch-, Werkstatt- und Softwaremaßnahmen
sind nachgelagerte Kontexte; dokumentierte ECU-Zustände können nach
zeitlicher und fachlicher Prüfung als technische Merkmale verwendet werden.
Gleichdatige AutoExport-Beobachtungen bleiben konservativ `zeitlich_unklar`.

**Clustergrundlage:** `cluster_input.csv` und DTCs aus tatsächlich vor dem Tausch liegenden
QuickTests. Spätere DTCs helfen, die Wiederkehr zu bewerten, aber dürfen
keine unbekannte technische Vor-Tausch-Ursache vorwegnehmen. QEC-Funde,
Lieferantenbewertungen, NTF-Labels und Nachanalysen sind zunächst
**Kontext / Hypothesenprüfung**, nicht Cluster-Labels oder Eingangsfeatures.
Fehlende Diagnosedaten sind ausdrücklich keine Fehlerfreiheit.

**Unvollständige Quellen:** Wenn keine geparsten QuickTests, QEC-JSONs oder
zugeordneten TIPS vorhanden sind, bleibt dies sichtbar. SMR-D wird
derzeit als Originaldatei erkannt und im Bestand gezählt; manuell
als SMR-D klassifizierte XML-/JSON-Quellen können ebenfalls inventarisiert
werden. Ohne
kompatiblen Parser stehen noch keine SMR-D-XML-/JSON-Merkmale zur Verfügung.
Für SMR-D v3 müssen zunächst **freigegebene anonymisierte** Beispieldateien
und eine Formatbeschreibung vorliegen.

## Originaltexte: zwei Schutzstufen

- **Standard:** Kein QEC-/TIPS-Freitext, keine FIN-/QEC-IDs,
  keine Quellnamen oder PDF-Inhalte. Technische DTC-/ECU-Codes, Softwarestände
  und Fahrzeugmerkmale sind weiterhin potenziell vertraulich.
- **Opt-in:** Originalbeschriftungen, QEC-Feldwerte und verknüpfte TIPS-Texte
  werden **unverändert** in die Tabellen geschrieben, um qualitative
  Schadensbilder zu analysieren. Dieser Modus ist **nicht anonymisiert**
  und kann FINs, Namen und vertrauliche Angaben enthalten. Die App
  verlangt vor dem lokalen Export eine Warnbestätigung.
  **Vor jedem externen Upload** sind Unternehmensfreigabe und eigenständige
  Anonymisierung erforderlich.

Die Paket-Pseudonyme werden per lokalem Zufallsschlüssel generiert und
sind **nur innerhalb eines Exports stabil**. Die private Zuordnung wird
nicht in die ZIP eingefügt. Bei wiederholten Analysepaketen können sich
die Pseudonymnummern ändern. Für langfristige Fallvergleiche müssen
die Zuordnungen intern verwaltet werden.

## Zweites Paket: technische Kontextunterlagen

Technische Referenzunterlagen, die **nicht** in NTF Insight gespeichert
sind, können nach geeigneter Bereinigung als **separate ZIP** organisiert werden:

```text
Technische_Referenzen.zip
  01_topologie/         Fahrzeugnetzwerk / ECU-Topologie
  02_setzbedingungen/   DTC-Setzbedingungen.xlsx
  03_ecu_nachrichten/   Botschaften, Signale und ECU-Zuständigkeiten
  04_cdd/               Diagnosebeschreibung / CDD-Dateien
  05_kuehlung/          Kühlkreislauf-Schema und Pumpenfunktion
  06_hw_updates/        HW-Änderungen und Serienabgrenzungen
  README.txt            Dokumentversion, Gültigkeit, Fahrzeugvarianten
```

Die Referenzunterlagen sollen nach Möglichkeit **ECU-Code, DTC-Code,
Baureihe, Teilenummer/Familie und SW-/HW-Versionen** enthalten, damit
sie mit den KI-Tabellen technisch verbunden werden können. Die gleichen
Feldnamen und Einheiten sind wichtig. Keine persönlichen Daten,
Voll-FINs, Anmeldedaten oder interne Pfade im Chat hochladen.
**Freigabe und Informationsschutz gelten auch für technische Dokumente.**

Mit beiden Paketen lässt sich eine externe Clusteranalyse durchführen.
Falls die Referenzunterlagen proprietäre Informationen enthalten, sollten
sie in einer **intern freigegebenen Analyseumgebung** statt einem
öffentlichen Chat verarbeitet werden.

## Bereits beim QEC-Abruf heruntergeladene Lieferantenbelege

Die aktivierte Checkbox **Vollständige QEC-Befundungsdokumente und Anhänge**
schließt referenzgebundene, lokal gespeicherte QEC-Anhänge ein
(`qec_originale/Q00001/anlage_0001.pdf`, `.jpg`, `.png` usw.).
Diese Belege werden bereits mit dem QEC-Downloader gespeichert und müssen nicht
erneut heruntergeladen werden. Fehlende oder ältere Anhänge erscheinen im
`qec_originale/vollstaendigkeit.json`-Nachweis. Die App parst deren
Bild-/PDF-Inhalt dadurch noch nicht automatisch.

Separat archivierte Lieferanten-Analyseberichte außerhalb eines QEC-Anhangs
werden im v3-Paket bislang nur inventarisiert. Ihre Originalbytes sind
nicht enthalten; insbesondere erfolgt **keine** spekulative FIN-/QEC-Zuordnung.
Lieferantenbefunde dürfen technisch ähnliche Vor-Tausch-Fälle nach dem Clustering
prüfen, aber keine Clustereingabe oder Kausalitätsbestätigung darstellen.
