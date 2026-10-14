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

## Automatisierter Ablauf

1. TIPS Writer im sichtbaren Microsoft Edge öffnen; SSO/PING ID abwarten.
2. Den laut Anleitung gegebenenfalls erscheinenden Dialog
   „Alles akzeptieren“ bestätigen.
3. Die vollständige 17-stellige FIN in die Suche mit dem CSS-Selektor
   tn-c-search input.xy-c-search-input eingeben und den direkt benachbarten
   Knopf **Suchen** betätigen.
4. Den **Fälle**-Registerreiter aktivieren, nicht Themen/TPRs.
5. Alle Ergebniszeilen einschließlich Folgeseiten auswerten; nur volle
   FIN-Gleichheit und numerische TIPS-Fallnummern zulassen.
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
