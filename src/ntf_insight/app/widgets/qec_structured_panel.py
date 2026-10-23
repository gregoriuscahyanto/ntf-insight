"""QEC-Originalbefund nach FIN/Referenz mit CPC3-/Tauschkontext anzeigen.

Alle Aussagen bleiben als Quellbeobachtungen gekennzeichnet. Aus QEC-Freitext
werden weder Lieferantenverursachung noch NTF-Entscheidungen abgeleitet.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.acquisition.qec_archive import local_qec_archive
from ntf_insight.analysis.diagnostic_observations import unique_diagnostic_observations
from ntf_insight.analysis.recurrence import relative_to_replacement
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.ingestion.qec_json import QEC_SECTIONS
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


class QECStructuredPanel(QWidget):
    """View source-identical QEC text, fields and tables for exactly one case."""

    def __init__(
        self,
        knowledge: SourceKnowledgeStore | None,
        *,
        data_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.knowledge = knowledge
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self._records: list[dict] = []
        self._sections: dict[str, str] = {}
        self._truncated = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel("QEC-Befundbericht · strukturierte Originaldaten", objectName="CardTitle"))
        self.status = QLabel(objectName="PageSubtitle")
        self.metadata = QLabel(objectName="PageSubtitle")
        self.context = QLabel(objectName="PageSubtitle")
        self.note = QLabel(
            "QEC ist eine Schadteil-/Prozessquelle, kein CPC3-Diagnosemesswert. "
            "Eine Aussage zur Lieferantenverursachung oder zum NTF ist nur nach "
            "fachlicher Prüfung mit DTC-Zeitreihe und Tauschereignis zulässig.",
            objectName="PageSubtitle",
        )
        for label in (self.status, self.metadata, self.context, self.note):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)

        filters = QHBoxLayout()
        self.section_filter = QComboBox()
        self.section_filter.addItem("Alle QEC-Reiter", None)
        for section in QEC_SECTIONS:
            self.section_filter.addItem(section, section)
        self.section_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.section_filter, 2)
        self.type_filter = QComboBox()
        for title, category in (
            ("Alle Einträge", None),
            ("Formularfelder", "qec_field"),
            ("Tabellenzeilen", "qec_table_row"),
            ("Dateianhänge (Verweise)", "qec_attachment"),
        ):
            self.type_filter.addItem(title, category)
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.type_filter, 1)
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("In den QEC-Feldern und Tabellen suchen …")
        self.text_filter.setClearButtonEnabled(True)
        self.text_filter.textChanged.connect(self._apply_filters)
        filters.addWidget(self.text_filter, 2)
        layout.addLayout(filters)

        self.table_model = SimpleTableModel((
            "QEC-Reiter", "Typ", "Feld / Bezeichnung", "Originalwert / Inhalt", "Quellfundstelle",
        ))
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setMinimumHeight(120)
        self.table.setMaximumHeight(275)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.count = QLabel(objectName="PageSubtitle")
        self.count.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.count)

        layout.addWidget(QLabel("Sichtbarer Originaltext des gewählten QEC-Reiters", objectName="CardTitle"))
        self.original_text = QPlainTextEdit()
        self.original_text.setReadOnly(True)
        self.original_text.setMinimumHeight(80)
        self.original_text.setMaximumHeight(135)
        self.original_text.setPlaceholderText("Wähle einen QEC-Reiter für den Originaltext.")
        layout.addWidget(self.original_text)
        self.clear()

    def clear(self) -> None:
        self._records = []
        self._sections = {}
        self._truncated = False
        self.status.setText("QEC-Erfassungsstand: Kein Fall ausgewählt.")
        self.metadata.setText("Keine QEC-Quelle zugeordnet.")
        self.context.setText("CPC3-DTC- und Pumpentauschdaten werden nur für einen ausgewählten Fall gezeigt.")
        self.table_model.set_rows([])
        self.count.setText("0 Einträge")
        self.original_text.clear()
        self.section_filter.setEnabled(False)
        self.type_filter.setEnabled(False)
        self.text_filter.setEnabled(False)

    @staticmethod
    def _cpc3_context(case) -> str:
        observations = [
            entry.event for entry in unique_diagnostic_observations(case.diagnostics)
            if entry.event.ecu.strip().upper().startswith("CPC3")
        ]
        codes = {entry.dtc_code.strip().upper() for entry in observations}
        replacement = case.investigated_replacement()
        if replacement is None:
            return (
                f"CPC3: {len(observations)} DTC-Beobachtung(en), "
                f"{len(codes)} verschiedene Codes. Pumpentauschanker fehlt; "
                "ein Vorher-/Nachher-Abgleich ist nicht möglich."
            )
        pre = [
            event for event in observations
            if relative_to_replacement(event, replacement) == "pre"
        ]
        post = [
            event for event in observations
            if relative_to_replacement(event, replacement) == "post"
        ]
        unknown = len(observations) - len(pre) - len(post)
        repeated = {
            entry.dtc_code.strip().upper() for entry in pre
        } & {
            entry.dtc_code.strip().upper() for entry in post
        }
        repeated_text = ", ".join(sorted(repeated)) if repeated else "nicht belegt"
        return (
            f"CPC3: {len(pre)} Beobachtung(en) vor / {len(post)} nach dem "
            f"Tausch am {replacement.occurred_at:%d.%m.%Y} "
            f"({unknown} zeitlich nicht zuordenbar). "
            f"Identische CPC3-DTCs beidseits beobachtet: {repeated_text}. "
            "Fehlende DTC-Beobachtungen beweisen keine Fehlerfreiheit; "
            "die fachliche Wiederkehrbewertung steht separat."
        )

    def show_case(self, case) -> None:
        self.clear()
        if case is None:
            return
        self.context.setText(self._cpc3_context(case))
        fin = str(case.vin or "").strip().upper()
        reference = str(getattr(case, "qec_reference", "") or "").strip()
        if not reference:
            self.status.setText("QEC-Erfassungsstand: Keine QEC-Referenz für diesen Fall.")
            return
        self.status.setText(f"QEC-Erfassungsstand: Nicht erfasst · FIN {fin} · Referenz {reference}")
        if self.knowledge is None:
            self.metadata.setText("Kein lokaler strukturierter QEC-Speicher verfügbar.")
            return
        report = self.knowledge.qec_report_for_case(
            fin, reference,
            part_number=str(getattr(case, "qec_part_number", "") or ""),
        )
        if report is None:
            exists = (
                self.data_dir is not None
                and local_qec_archive(self.data_dir / "qec", fin, reference) is not None
            )
            self.metadata.setText(
                "qec.json liegt lokal vor, wurde aber noch nicht strukturiert "
                "eingelesen. Unter Datenquellen: »Bereits heruntergeladene "
                "QEC-Berichte einlesen«."
                if exists
                else "Kein strukturierter QEC-Bericht für diese FIN und Referenz vorhanden."
            )
            return

        metadata = report["metadata"]
        self.status.setText(
            f"QEC-Erfassungsstand: {report['status']} · FIN {fin} · Referenz {reference}"
        )
        missing = metadata.get("missing_sections") or []
        stale = metadata.get("stale_sections") or []
        extra = []
        if missing:
            extra.append("fehlende Reiter: " + ", ".join(missing))
        if stale:
            extra.append("ältere Reiter: " + ", ".join(stale))
        if report.get("reason"):
            extra.append(report["reason"])
        self.metadata.setText(
            f"Sachnummer: {metadata.get('part_number') or '—'} · "
            f"Abruf: {metadata.get('downloaded_at_utc') or 'unbekannt'} · "
            f"Reiter: {metadata.get('fresh_sections', 0)}/5 frisch · "
            f"Versionen: {report['versions']} · "
            f"Original-SHA-256: {report['source_sha256'][:16]}…"
            + (" · " + " · ".join(extra) if extra else "")
        )
        self._records = report["records"]
        self._sections = {
            str(item["data"].get("bereich")): str(item["data"].get("sichtbarer_text") or "")
            for item in self._records if item["category"] == "qec_section"
        }
        self._truncated = bool(report["truncated"])
        allowed = bool(self._records)
        self.section_filter.setEnabled(allowed)
        self.type_filter.setEnabled(allowed)
        self.text_filter.setEnabled(allowed)
        self._apply_filters()

    @staticmethod
    def _row_for_record(item: dict) -> tuple[str, str, str, str, str] | None:
        kind = item["category"]
        data = item["data"]
        if kind == "qec_section":
            return None
        section = str(data.get("bereich") or "Anhänge")
        label = str(item.get("label") or "")
        location = str(item["source_location"])
        if kind == "qec_field":
            raw = str(data.get("wert") or "")
            chosen = str(data.get("auswahltext") or "")
            value = f"{chosen} (Rohwert: {raw})" if chosen and chosen != raw else raw
            return section, "Formular", label, value or "—", location
        if kind == "qec_table_row":
            cells = [str(cell.get("text") or "") for cell in data.get("zellen", [])]
            return section, "Tabelle", label, " | ".join(cells), location
        if kind == "qec_attachment":
            return section, "Datei", label, str(data.get("datei") or ""), location
        return None

    def _apply_filters(self, *_args) -> None:
        section = self.section_filter.currentData()
        category = self.type_filter.currentData()
        query = self.text_filter.text().strip().casefold()
        rows = []
        for item in self._records:
            if section is not None and item["data"].get("bereich") != section:
                continue
            if category is not None and item["category"] != category:
                continue
            row = self._row_for_record(item)
            if row is None:
                continue
            if query and not any(query in str(cell).casefold() for cell in row):
                continue
            rows.append(row)
        self.table_model.set_rows(rows)
        count_note = (
            " · Weitere Daten vorhanden; nur ein begrenzter Auszug wurde geladen."
            if self._truncated else ""
        )
        self.count.setText(f"{len(rows)} Quellzeilen angezeigt{count_note}")
        if section is None:
            self.original_text.setPlainText("Bitte einen einzelnen QEC-Reiter auswählen.")
        else:
            original = self._sections.get(section, "")
            self.original_text.setPlainText(
                original[:20_000] + ("\n[…] Originaltext gekürzt." if len(original) > 20_000 else "")
                if original else "Kein Originaltext für diesen Reiter gespeichert."
            )
