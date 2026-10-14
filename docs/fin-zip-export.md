# ZIP-Export pro FIN

## Bedienung

In **Fälle / FIN → FIN / Fallanalyse**, unterhalb des QEC-Abrufs, stehen
zwei Schaltflächen:

- **Alle FINs als ZIP exportieren** — jede eindeutige FIN der vollständigen
  Falltabelle (auch bei aktivem Suchfilter).
- **Ausgewählte FINs als ZIP exportieren** — nutzt **dieselben Checkboxen**
  wie QuickTest und QEC. Mehrere Fälle mit derselben FIN ergeben ein ZIP.
  Die Auswahl bleibt bei Sortierung und Filterung erhalten.

Nach Auswahl des lokalen Zielordners läuft die ZIP-Erstellung im Hintergrund.
Eine Statuszeile meldet Fortschritt, Anzahl erstellter ZIPs und Zielordner.
FINs ohne Dateien werden übersprungen, nicht als scheinbar erfolgreiche leere
Archive dargestellt.

ZIP-Dateiname: FIN_NTF-Export.zip; bei bereits vorhandenen Exporten wird _2,
_3 usw. ergänzt, statt die vorhandene Datei zu überschreiben.

## Struktur pro FIN-ZIP

    FIN_NTF-Export.zip
      export_manifest.json
      quicktests/
        kurztest_1.pdf
        kurztest_2.pdf
      qec/
        ref_022301658/
          qec.json
          anhaenge/
            1603327_bericht.pdf
        ref_022301659/
          qec.json
          anhaenge/
            1580627_bericht.pdf
      tips/                       # zukünftig, falls lokal vorhanden
        tips.json
        dateien/
          foto.jpg
          bericht.pdf

**Tatsächliche lokale Quellordner:**

- QuickTests: data_dir/quicktests/FIN/ — alle dort vorhandenen PDFs, nicht
  nur die des letzten Abrufversuchs.
- QEC: data_dir/qec/FIN/ref_Referenz/ — pro Referenz qec.json und die
  PDFs im Unterordner anhaenge. Mehrere Referenzen derselben FIN werden
  gemeinsam in dieses FIN-ZIP übernommen.
- TIPS (für zukünftige Downloads): data_dir/tips/FIN/ — später abgelegte
  JSONs und Dateien werden automatisch berücksichtigt.

TIPS-Dateiendungen: .json, .pdf, .jpg, .jpeg, .png, .tif, .tiff, .bmp,
.gif, .webp, .doc, .docx, .xls, .xlsx, .csv, .txt, .eml, .msg.
Andere Formate, ausführbare Dateien und temporäre Dateien werden nicht
automatisch exportiert. **Die ZIP-Tasten laden noch keine TIPS-Daten herunter.**

QEC-Referenzen ohne lesbare qec.json oder mit abweichender vollständiger FIN
bzw. Referenznummer werden inklusive ihrer Anhänge ausgelassen. Ältere
QEC-HTML-Seiten und laeufe-Ordner werden nicht automatisch umgewandelt.

## Exportmanifest und Sicherheit

Jede ZIP enthält eine export_manifest.json mit:

- schema_version, fin, export_utc
- dateien: relative Pfade, Kategorie, Größe, SHA-256-Prüfsumme
- anzahl: quicktests, qec_json, qec_pdfs, tips_json, tips_dateien
- fehlende_quellen und hinweise zu nicht vorhandenen / ausgelassenen Daten

**Kein Netzwerkabruf:** Es werden nur vorhandene Dateien aus der lokalen
NTF-Insight-Ablage übernommen. Browserprofile, Cookies, Passwörter und
Datenbanken werden nicht exportiert. Dateipfade können das jeweilige FIN-
Quellverzeichnis nicht verlassen. Symbolische Links sind ausgeschlossen.
Das ZIP wird erst nach vollständigem Schreiben am Zielort veröffentlicht.

Die ZIP-Dateien enthalten unter Umständen personenbezogene FINs und interne
Befundungsberichte. Sie dürfen nicht versehentlich in öffentliche
GitHub-Repositories oder GitHub-CI-Artefakte hochgeladen werden.

## Tests

Synthetische Tests prüfen den Export aller PDFs, mehrere QEC-Referenzen,
noch fehlende TIPS-Daten, zukünftige TIPS-JSON/Bilder, den Dateifilter,
widersprüchliche FINs/Referenzen, ZIP-Pfade und wiederholte Exporte sowie die
gemeinsame Fall-Checkbox-Auswahl in der GUI.
