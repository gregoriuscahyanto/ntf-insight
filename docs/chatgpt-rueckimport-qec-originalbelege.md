# NTF-Auswertung mit ChatGPT: standardisierter Export und Rückimport

**Versioniertes Austauschformat:** \`ntf-insight-chatgpt-rueckgabe\`, \`schema_version: 1\`.

## Was in der bisherigen App fehlte

Der erste Lightweight-Export enthielt nur strukturierte QEC-Felder und
vorbereitete CSVs. Die originalen QEC-Befundberichte und deren Anhänge
waren ausdrücklich **nicht** enthalten. Ebenso fehlte ein verbindliches,
maschinenlesbares Ergebnisformat für die Rückgabe von ChatGPT an die App.

Diese Ergänzung führt die folgenden separaten Funktionen ein:

1. **KI-Analysepaket als ZIP exportieren**: mit \`paket_id\`,
   \`CHATGPT_ANWEISUNG.txt\`, \`chatgpt_ergebnis_vorlage.json\` und
   \`chatgpt_ergebnis_schema.json\`. Alle Fall-/QT-/QEC-Pseudonyme sind
   innerhalb eines Pakets eindeutig. Das Schlüsseldokument
   \`*_NICHT_HOCHLADEN_ZUORDNUNG.csv\` wird außerhalb der ZIP gespeichert.
   Die zugehörigen Pseudonymzuordnungen liegen **zusätzlich in DuckDB**,
   damit sie über das bestehende \`.ntfbackup\` zum zweiten PC gelangen.
2. **Option: vollständige QEC-Befundungsdokumente und Anhänge**:
   nicht standardmäßig aktiv. Die ZIP enthält dann zusätzlich
   \`qec_originale/Q00001/qec.json\`, \`anlage_0001.pdf\` usw.,
   \`belegindex.csv\` (QEC-ID, Datei, SHA-256) und
   \`vollstaendigkeit.json\` mit fehlenden/älteren Belegständen.
   Nur echte, zugeordneten QEC-Berichten gehörende Dokumente werden
   ergänzt. Das ursprüngliche qec.json bewahrt **alle fünf Reiter,
   die Originaltexte, Formularfelder und Tabellen**. Reiter, die aus
   älteren Abrufen übernommen wurden, bleiben darin gekennzeichnet.
   PDF/Bild/Office-Anhänge werden **nicht automatisch geparst**.
3. **ChatGPT-Auswertung als JSON importieren**:
   Die App prüft Format, \`paket_id\`, fallbezogene Pseudonyme,
   Cluster-Mitgliedschaft und Belegreferenzen. Bei anderem Rechner kann
   die lokale private Zuordnungs-CSV bei Bedarf **nur in der App**
   ausgewählt werden (nicht hochladen).
4. **Fachliche Prüfung**:
   Ergebnisse stehen in getrennten
   \`chatgpt_imports\`, \`chatgpt_cluster\` und
   \`chatgpt_fallanalysen\`-Tabellen. In Datenquellen können
   externe Vorschläge *als geprüft bestätigt* oder *abgelehnt* werden.
   In der FIN-/Fallanalyse wird der aktuellste Vorschlag inklusive
   Review-Status angezeigt. Es wird **keine bestehende QEC-/NTF-Entscheidung,
   kein Lieferantenbefund und keine manuelle Revision überschrieben**.

## Beispiel für den standardisierten ChatGPT-Ergebnisvertrag

Die Paketkennung und echten Fallpseudonyme stammen *ausschließlich*
aus der ZIP-Vorlage. Dieses Beispiel ist fiktiv:

\`\`\`json
{
  "format": "ntf-insight-chatgpt-rueckgabe",
  "schema_version": 1,
  "paket_id": "0123456789abcdef0123456789abcdef",
  "analyse_id": "Analyse-0123456789ab-01",
  "clustermethode": "DTC-Ähnlichkeit auf Beobachtungen vor Pumpentausch",
  "verwendete_merkmale": ["CPC3-DTC-Muster vor Tausch"],
  "unsicherheiten": ["Keine Diagnosesitzung nach Tausch für F0001"],
  "cluster": [
    {
      "cluster_id": "C01",
      "titel": "Ansteuerung / Versorgung – Hypothese",
      "fall_ids": ["F0001"],
      "technische_hypothese": "Versorgungsumfeld untersuchen",
      "sicherheit": "Niedrig",
      "belege": []
    }
  ],
  "faelle": [
    {
      "fall_id": "F0001",
      "cluster_id": "C01",
      "ntf_bewertung": "NTF fraglich",
      "prioritaet": "P1",
      "befund": "Messung vor Tausch auffällig",
      "verursachungsbereich": "Nicht zuordenbar",
      "sicherheit_zuordnung": "Offen",
      "begruendung_zuordnung": "Keine eindeutige Prüfung des Gegensteckers",
      "begruendung_ntf": "QEC-Dokument ist ohne Anschlussprüfung nicht ausreichend",
      "ursachenhypothese": "Elektrische Versorgung prüfen",
      "klaerung_durch": "Werkstatt und QEC",
      "naechster_schritt": "Ansteuersignal im eingebauten Zustand prüfen",
      "pruefungen_grenzen": "Keine Quellmessdaten nach Tausch",
      "weitere_auffaelligkeiten": "",
      "sicherheit_bewertung": "Mittel",
      "themen": ["Ansteuerung", "Diagnosedatenlücke"],
      "belege": [
        {
          "quelle": "qec_felder",
          "quelle_id": "Q00001",
          "fundstelle": "QF0123 / Reiter WE-Daten",
          "aussage": "Der QEC-Originalwert ist fachlich zu prüfen",
          "belegstatus": "Nicht verifiziert"
        }
      ]
    }
  ]
}
\`\`\`

Alle übrigen Felder sind in \`chatgpt_ergebnis_schema.json\` dokumentiert.
Die App akzeptiert nur exakt definierte Kategorien und begrenzte
Freitextgrößen. Ungültige, doppelte oder nicht zuordenbare Fälle, fremde
QEC-/QuickTest-Pseudonyme und widersprüchliche Clusterzuordnungen führen
zu **vollständigem Importabbruch** (keine Teilübernahme).

Die Felder folgen der bisherigen QEC-Auswertung
\`NTF_Auswertung_QEC_2026-10-20.xlsx\`: *Fallliste, Falldaten, Belege,
Methodik*, insbesondere *NTF-Bewertung, Priorität, Befund,
Verursachungsbereich (Hypothese), Sicherheit Zuordnung,
Begründung Zuordnung, Begründung NTF, Ursachenhypothese, Klärung durch,
Nächster Schritt, Prüfungen und Grenzen, Weitere Auffälligkeiten,
Sicherheit Bewertung, Themen*.

## Sicherheit, Belegvollständigkeit und Datenqualität

- **Standard ohne Originale**: technisch strukturierter Export mit
  Pseudonymen und ohne QEC-/TIPS-Freitext. Auch dieses Paket enthält
  potentiell vertrauliche technische Diagnosedaten.
- **QEC-Originale ausdrücklich anhaken**: Die ZIP enthält echte
  \`qec.json\`-Inhalte und Anhänge. **Neutralisierte Namen machen die
  Inhalte nicht anonym.** Originale können FIN, Schadteilnummern,
  Seriennummern, Lieferanten- und Kundendaten enthalten. Eine klare
  GUI-Warnung und ein zusätzlicher Bestätigungsschritt sind nötig.
- Nur auf dem Rechner vorhandene und **mit FIN, QEC-Referenz und
  SHA-256 übereinstimmende** Quellen werden exportiert. Fehlende
  Originale oder alte Versionen werden in der ZIP inventarisiert.
  Bei einer alten QEC-JSON ohne aktuellen lokalen Anhangsstand wird
  kein vermeintlich zugehöriges Fremddokument beigefügt.
- Grenzen gegen sehr große Datenpakete: **5.000 Dateien**, insgesamt
  maximal **1 GiB Originalbytes**, einzelne Anhänge maximal 80 MiB.
  Beim Überschreiten erfolgt keine stillschweigende unvollständige ZIP;
  der Export wird abgebrochen.
- Original-Dateinamen, lokale Verzeichnisse, Dateisystem-Zeitstempel und
  private Zuordnungen werden nicht als ZIP-Pfade übernommen.
  **Original-Inhalte** werden bewusst bytegetreu belassen.
- Weder ChatGPT noch die App dürfen aus einer supplierseitigen
  Stellungnahme ohne weitere technische Prüfung eine kausale
  Lieferantenverursachung behaupten.
- Die KI-Rückgabe erhält einen Herkunftsnachweis über SHA-256, Paket-ID
  und Analyse-ID. Wiederholter identischer Import ist möglich, abweichende
  Ergebnisse unter derselben Analyse-ID werden nicht still überschrieben.
- Das gewohnte \`.ntfbackup\` transportiert DuckDB inklusive neuer
  Rückgaben, Prüfvermerken und Analysepaket-Zuordnungen zwischen PCs.

**Vor einem Upload:** interne Unternehmensrichtlinien beachten,
Daten klassifizieren, Berechtigung klären und erforderlichenfalls
wirklich anonymisieren. Ein pseudonymisiertes Analysepaket ist
nicht automatisch zur externen Verarbeitung freigegeben. Insbesondere
mit QEC-Originalen und TIPS-Freitexten darf ein externes Hochladen
nicht ohne entsprechende Freigabe erfolgen.

## Clusterung ohne Ergebnis-Leakage

Die primäre Clustergrundlage bleibt
\`cluster_input.csv\` plus ausschließlich
\`quicktest_fallbezug.csv\` mit \`vor_tausch\` und zugehörige
\`dtc_beobachtungen.csv\`. Nach-Tausch-Ergebnisse,
lieferantenseitige Endbefunde sowie QEC-/NTF-Bewertungen dienen der
**nachgelagerten Mechanismusprüfung**. Seltene Muster und
nicht beobachtete Fehlermeldungen erlauben keine Kausalaussage.

**Technische Referenzen** wie Topologie, ECU-Nachrichtenliste,
CDD, Setzbedingungen, Kühlungsschema und HW-Update-Liste können als
zweite, eigenständig freigegebene und bereinigte ZIP hinzukommen;
Referenz-Belege in der Ergebnisdatei brauchen dafür eine nachvollziehbare
\`fundstelle\`, werden aber von der App nicht automatisch bestätigt.
