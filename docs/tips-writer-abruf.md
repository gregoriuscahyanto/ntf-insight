# TIPS Writer – automatischer Fallabruf mit Playwright

## Grundlage

Ausgewertet: TIPS Writer Anleitung.zip (PDF- und PPTX-Anleitung sowie
gespeicherte HTML-Ansichten von Fallliste, FIN-Suche und Falldetails).
Die Originaldateien enthalten vertrauliche TIPS-/Fahrzeuginformationen und
werden **nicht** im GitHub-Repository gespeichert.

Startseite laut Anleitung:
https://xentry.mercedes-benz.com/tips-writer/home/topics/search

## Bedienung in NTF Insight

Unter **Fälle / FIN → FIN / Fallanalyse** gibt es zusätzlich zu QuickTest und
QEC den Bereich **TIPS-Writer-Fälle für Fälle / FIN** mit drei Tasten:

- **Alle TIPS-Fälle herunterladen/aktualisieren**
- **TIPS-Fälle für ausgewählte FINs herunterladen/aktualisieren**
- **Abbrechen**

Die Auswahl verwendet **dieselben persistenten Fall-Checkboxen** wie
QuickTest, QEC und der FIN-ZIP-Export. Zwei Fälle derselben FIN führen zu
**einer FIN-Suche**, danach werden alle gefundenen TIPS-Fälle dieser FIN
bearbeitet. Ein aktiver Tabellenfilter beeinflusst die Auswahl nicht.

Gemeinsam genutzte SSO-Benutzer-ID und Passwort stammen aus der bestehenden
Anmeldung und dem sicheren Betriebssystem-Tresor. Es wird **kein weiteres
Passwort** gespeichert. TIPS benutzt ein eigenes Edge-Profil und wartet
auf eine gegebenenfalls erforderliche manuelle PING-ID-Bestätigung.

## CLI: 17-stellige FIN oder TIPS-Fallnummer

Die CLI `ntf-insight-tips` akzeptiert eine TXT mit einer Kennung
pro Zeile. Erlaubt sind **vollständige 17-stellige FINs** oder
**numerische TIPS-Fallnummern (4–16 Ziffern)**. Beides darf in einer
Datei gemischt stehen. Die Unterscheidung erfolgt automatisch; führende
Nullen bleiben unverändert:

```text
WDD12345678901234
01234567
00001234
```

```powershell
ntf-insight-tips --eingabe ".\FIN-Liste.txt"
ntf-insight-tips --eingabe ".\TIPS-Fallnummern.txt"
```

Beim direkten Abruf über eine **Fallnummer** sucht der Downloader
ebenfalls über die TIPS-Suchleiste, aktiviert den Reiter **„Fälle“** und
nimmt ausschließlich die Ergebniszeile mit **exakt dieser Fallnummer**.
Er benötigt eine gültige 17-stellige FIN in der Trefferzeile und
verifiziert nach dem Öffnen des Falls **Fallnummer und FIN erneut**
im Detailkopf. Eine fehlende, andere oder mehrdeutige FIN ist ein
Abruffehler; der Downloader legt keinen Bericht unter einer geratenen
FIN ab. Die reguläre Fall-JSON liegt unter
`tips_writer/<FIN>/fall_<Fallnummer>/tips.json`; für
Fallnummern-Suchen wird zusätzlich
`tips_writer/_fallnummern/fall_<Fallnummer>/abrufstatus.json`
geschrieben. Die GUI arbeitet weiterhin mit FINs und bleibt unverändert.

Im parallelen Sammelabruf kann TIPS eine *eigene* Fallnummern-TXT erhalten,
während die anderen fünf Quellen die Haupt-FIN-Liste verwenden:

```powershell
ntf-insight-beschaffung --eingabe ".\FIN-Liste.txt" --tips-eingabe ".\TIPS-Fallnummern.txt" --quellen alle --parallel 6
```

Bei `--quellen tips` darf die Hauptdatei unter
`--eingabe` auch eine reine Fallnummernliste sein.

## Automatisierter Ablauf

1. TIPS Writer im sichtbaren Microsoft Edge öffnen; SSO/PING ID abwarten.
2. Den laut Anleitung gegebenenfalls erscheinenden Dialog
   „Alles akzeptieren“ bestätigen.
3. Die vollständige **17-stellige FIN** (GUI/CLI) oder eine
   **numerische TIPS-Fallnummer** (nur CLI) in die Suche mit dem
   CSS-Selektor tn-c-search input.xy-c-search-input eingeben und den
   direkt benachbarten Knopf **Suchen** betätigen.
4. Den **Fälle**-Registerreiter aktivieren, nicht Themen/TPRs.
5. Alle Ergebniszeilen einschließlich Folgeseiten auswerten; bei einer
   FIN-Suche nur volle FIN-Gleichheit, bei einer Fallnummern-Suche nur
   **exakt gleiche Fallnummern mit gültiger 17-stelliger FIN** zulassen.
6. Jede geprüfte Fallzeile in Edge anklicken (gegebenenfalls doppelt).
   **Keine spekulative interne Fall-URL** konstruieren.
7. Fallkopf und die zehn dokumentierten Registerkarten erfassen:
   **Erstanfrage**, **Betriebsdaten**, **Fahrzeugdaten**, **Symptom**,
   **Kommunikation**, **Anhänge**, **Funktionsgruppe**,
   **Steuergerät/FC**, **Zustandsdaten**, **Inspektor / Notizen**.
8. Die sichtbare Anhangliste unter **Anhänge** speichern. Bei Dateien
   alle Tabellenzeilen auswählen und den Downloadknopf mit der Klasse
   xy-i-download anklicken. Der Browser-Download oder sein ZIP wird lokal
   gesichert; bei ZIP werden die unterstützen Originaldateien entpackt.
9. Pro Fall genau eine lokale tips.json schreiben. Vor dem nächsten Fall
   die Suche neu öffnen, um veraltete Browserdaten nicht zu vermischen.

Es werden keine schreibenden TIPS-Aktionen auf Fälle ausgeführt:
keine Antworten, Änderungen, Abschlüsse oder Weiterleitungen. Zwischen
Klicks/Seitenwechseln erfolgt eine kurze, abbrechbare Sicherheitswartezeit.

## Lokales Speicherformat

    data_dir/
      tips/
        <FIN>/
          abrufstatus.json
          fall_<TIPS-Fallnummer>/
            tips.json
            dateien/
              <Originaldokument>.pdf
              <Bild>.jpg
              <Originaldokument>.csv
      edge-tips-writer-profile/          (nicht in FIN-ZIPs)

Die fallbezogene tips.json enthält fin, fallnummer, titel,
kopfdaten_text, suchtreffer, abgerufen_am_utc, abschnitte,
anhangliste, dateien (relative Pfade, Größe, SHA-256),
hinweise und fehler.

**Vollstaendige Reiter** bedeutet nur, dass alle zehn dokumentierten
Bereiche während des aktuellen Laufs gelesen wurden; es ist keine
Garantie für dynamisch noch nicht geladene Dialoge. Fehlende Reiter
aus einem vorherigen Abruf werden nur mit der Kennzeichnung
aus_vorherigem_abruf übernommen. Vorhandene Anhänge werden nie gelöscht.

## Vorhandener FIN-ZIP-Export

Der bereits vorhandene FIN-ZIP-Export übernimmt die Dateien unter
tips/<FIN>/ rekursiv. Dadurch werden die neuen TIPS-Fall-JSONs,
PDF/JPG/CSV usw. ohne Änderungen am Exportformat in das jeweilige
FIN-ZIP aufgenommen.

## Sicherheit / offene Live-Prüfungen

- Automatische SSO-Eingaben nur für die exakte HTTPS-Domain
  login.mercedes-benz.com.
- Die TIPS-Oberfläche wird nur unter
  xentry.mercedes-benz.com/tips-writer/ bedient.
- ZIP-Anhänge werden auf Dateityp, Größe, ZIP-Pfade und Symlinks geprüft.
- **Ein Live-Test in TIPS Writer steht noch aus.** Die Anleitung zeigt
  eine Offline-HTML-Sicherung, in der die Fallzeile nicht mehr reagiert.
  Ob die echte Angular-Zeile per einfachem oder Doppelklick geöffnet
  werden kann, muss im berechtigten Unternehmensnetz bestätigt werden.
- Ob die TIPS-Gesamtsuche **numerische Fallnummern** serverseitig akzeptiert
  und die korrekte Falltabelle liefert, ist ebenfalls erst im berechtigten
  Unternehmensnetz überprüfbar. Die Offline-Tests bestätigen nur die
  exakte und FIN-sichere Auswertung der gerenderten Ergebnisse.
- Auch das tatsächliche Downloadformat der Anhang-Schaltfläche ist in
  der Anleitung nicht eindeutig belegt; der Code behandelt Browser-
  Downloads und ZIP-Archive. Bei Problemen bitte nur **anonymisierte**
  Ablaufprotokolle schicken.
- Keine echten FINs, TIPS-Dokumente, Browserprofile oder Kennwörter
  in GitHub oder CI hochladen.

## Testkonzept

Synthetische Tests prüfen vollständige FIN-Zuordnung, Fall- und
Anhangtabellen, zehn Reiter, PDF/ZIP-Anhänge, ZIP-Path-Traversal,
Domänengrenzen für SSO, lokale Fallzuordnung, Folgeabruf und die
gemeinsame GUI-Checkbox-Auswahl.
