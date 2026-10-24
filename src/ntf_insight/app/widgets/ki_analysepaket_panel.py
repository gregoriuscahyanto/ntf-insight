"""GUI für den zweistufigen KI-Analyseexport und geprüften ChatGPT-Rückimport."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

import duckdb
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPlainTextEdit, QPushButton, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.ingestion.service import SourceImportService
from ntf_insight.reporting.chatgpt_exchange import (
    ChatGPTAnalyseStore, MAX_JSON_SIZE,
)
from ntf_insight.reporting.ki_analysepaket import export_ki_analysepaket


class KIAnalyseWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        service: SourceImportService,
        path: Path,
        *,
        mit_freitext: bool,
        mit_qec_originalen: bool = False,
        selected_fins: set[str] | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.path = Path(path)
        self.mit_freitext = mit_freitext
        self.mit_qec_originalen = mit_qec_originalen
        self.selected_fins = selected_fins

    def run(self) -> None:
        try:
            result = export_ki_analysepaket(
                self.service, self.path, mit_freitext=self.mit_freitext,
                mit_qec_originalen=self.mit_qec_originalen,
                progress=self.progress.emit,
                selected_fins=self.selected_fins,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(result)


class ChatGPTImportWorker(QThread):
    progress = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self, service: SourceImportService, path: Path,
        *, private_csv: Path | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.path = Path(path)
        self.private_csv = private_csv

    def run(self) -> None:
        try:
            result = ChatGPTAnalyseStore(self.service.store).import_file(
                self.path, private_csv=self.private_csv,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.completed.emit(result)


class KIAnalysepaketPanel(QWidget):
    """Default: structured pseudonyms. Raw QEC documents are explicitly opt-in."""

    transfer_busy = Signal(bool)
    analysis_updated = Signal()
    first_package_export_started = Signal(object)
    first_package_exported = Signal(object)
    export_options_requested = Signal()
    export_progress = Signal(str)
    export_failed = Signal(str)
    export_finished = Signal()
    analysis_imported = Signal(object)
    analysis_import_started = Signal(str)
    analysis_import_progress = Signal(str)
    analysis_import_failed = Signal(str)
    analysis_import_finished = Signal()

    def __init__(
        self, service: SourceImportService, *, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.analysis_store = ChatGPTAnalyseStore(service.store)
        self.worker: KIAnalyseWorker | None = None
        self.import_worker: ChatGPTImportWorker | None = None
        self._guard: Callable[[], bool] | None = None
        self._next_workflow_fins: set[str] | None = None
        self._use_shared_export_dialog = False
        self._visible: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.addWidget(QLabel(
            "KI-Analysepaket · ChatGPT-Austausch und geprüfter Rückimport",
            objectName="CardTitle",
        ))
        description = QLabel(
            "Erstellt EINE ZIP mit verknüpften QEC-Befundmerkmalen, "
            "QuickTest-/CPC3-DTCs, AutoExport-Diagnosehistorie, Werkstatt- und "
            "TIPS-Abdeckung sowie Fall- und Zeitbezug "
            "und einer Excel-Übersicht. Original-PDFs, QEC-JSONs und "
            "Anhänge sind nur bei ausdrücklicher Auswahl enthalten. "
            "Die echte FIN-/QEC-Zuordnung bleibt ausschließlich lokal.",
            objectName="PageSubtitle",
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.include_text = QCheckBox(
            "QEC-/TIPS-/Werkstatt-/Lieferanten-Freitexte beifügen (vertraulich)",
        )
        self.include_text.setToolTip(
            "Nur nach interner Freigabe wählen. Erweitert auch AutoExport-"
            "Werkstatttexte, DTC-Klartexte und Lieferantenbefundnotizen. "
            "Freitext ist NICHT automatisch anonymisiert und kann FINs, "
            "Personen und geschützte Angaben enthalten."
        )
        self.include_text.setChecked(False)
        layout.addWidget(self.include_text)

        self.include_qec_originale = QCheckBox(
            "Vollständige QEC-Befundungsdokumente und Anhänge beifügen "
            "(Originale, vertraulich)",
        )
        self.include_qec_originale.setToolTip(
            "Nimmt optional die unveränderten qec.json mit allen fünf Reitern "
            "und zugehörige PDF-/Bild-/Office-Anhänge in die Analyse-ZIP. "
            "Diese enthalten oft echte FINs, Seriennummern und vertrauliche Daten. "
            "Kein automatisches Anonymisieren, keine automatische Freigabe. "
            "Maximal 1 GiB Originalbytes und 5.000 Dateien pro ZIP."
        )
        self.include_qec_originale.setChecked(False)
        layout.addWidget(self.include_qec_originale)

        row = QHBoxLayout()
        self.export_button = QPushButton(
            "Lightweight KI-Analysepaket als ZIP exportieren…"
        )
        self.export_button.setToolTip(
            "CSV-Clusterdateien und Excel-Übersicht, vollständige einheitliche "
            "ChatGPT-Ergebnisvorlage, lokale private Pseudonymzuordnung."
        )
        self.export_button.clicked.connect(self._request_export)
        row.addWidget(self.export_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.status = QLabel(
            "Standard ohne fachliche Freitexte, reale FINs und Originaldateien. "
            "Freigegebene Originalberichte können bewusst ergänzt werden; "
            "ein ZIP mit Originalen ist NICHT anonymisiert. "
            "Kein automatischer Upload.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        layout.addWidget(QLabel(
            "ChatGPT-Ergebnisse wieder in die App übernehmen",
            objectName="CardTitle",
        ))
        hint = QLabel(
            "Das Analyse-ZIP enthält chatgpt_ergebnis_vorlage.json und "
            "chatgpt_ergebnis_schema.json. ChatGPT kann damit eine "
            "chatgpt_ergebnis.json zurückgeben. Beim Import werden Paket-ID, "
            "Fallpseudonyme und Belegverweise geprüft. Ergebnisse bleiben "
            "von fachlichen Entscheidungen GETRENNT und zunächst ungeprüft.",
            objectName="PageSubtitle",
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        import_row = QHBoxLayout()
        self.import_button = QPushButton("ChatGPT-Auswertung als JSON importieren…")
        self.import_button.clicked.connect(self._import_result)
        import_row.addWidget(self.import_button)
        self.review_confirm = QPushButton("Markierten Vorschlag als geprüft bestätigen")
        self.review_confirm.clicked.connect(lambda: self._review("Bestätigt"))
        import_row.addWidget(self.review_confirm)
        self.review_reject = QPushButton("Markierten Vorschlag ablehnen")
        self.review_reject.clicked.connect(lambda: self._review("Abgelehnt"))
        import_row.addWidget(self.review_reject)
        layout.addLayout(import_row)

        self.review_model = SimpleTableModel((
            "Analyse", "Fall-ID (lokal)", "Cluster",
            "NTF-Hypothese", "Ursachenhypothese", "Prüfstatus",
        ))
        self.review_table = QTableView()
        self.review_table.setModel(self.review_model)
        self.review_table.setMinimumHeight(135)
        self.review_table.setMaximumHeight(245)
        self.review_table.setAlternatingRowColors(True)
        self.review_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.review_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.review_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.review_table.verticalHeader().setVisible(False)
        self.review_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.review_table.horizontalHeader().setStretchLastSection(True)
        self.review_table.selectionModel().selectionChanged.connect(
            lambda *_args: self._review_enabled(),
        )
        layout.addWidget(self.review_table)
        self.review_details = QPlainTextEdit()
        self.review_details.setReadOnly(True)
        self.review_details.setMinimumHeight(80)
        self.review_details.setMaximumHeight(155)
        self.review_details.setPlaceholderText(
            "Eine importierte ChatGPT-Fallanalyse auswählen, um alle "
            "Begründungen, Prüfgrenzen, Empfehlungen und Belege zu lesen."
        )
        layout.addWidget(self.review_details)
        self.review_note = QLabel(
            "Review-Status ändert nur den Prüfvermerk der ChatGPT-Analyse. "
            "QEC-Entscheidung, Lieferantenursache und bestehende Fallbewertung "
            "werden ausdrücklich NICHT überschrieben.",
            objectName="PageSubtitle",
        )
        self.review_note.setWordWrap(True)
        layout.addWidget(self.review_note)
        self._refresh_imports()

    def set_guard(self, guard: Callable[[], bool]) -> None:
        self._guard = guard

    def _can_start(self) -> bool:
        if self.worker is not None or self.import_worker is not None:
            return False
        if self._guard is not None and not self._guard():
            QMessageBox.warning(
                self, "Analysefunktion derzeit nicht möglich",
                "Bitte zuerst laufende Downloads, Imports und "
                "Gesamtstand-Transfers abschließen.",
            )
            return False
        return True

    def _confirm_confidential(
        self, *, originals: bool, text: bool,
        parent: QWidget | None = None,
    ) -> bool:
        if not (originals or text):
            return True
        relevant = (
            "vollständige QEC-Originalberichte und Anhänge SOWIE "
            "QEC-/TIPS-/Werkstatt-/Lieferanten-Freitexte"
            if originals and text else
            "vollständige QEC-Originalberichte UND Anhänge" if originals else
            "QEC-/TIPS-/Werkstatt-/Lieferanten-Freitexte"
        )
        reply = QMessageBox.warning(
            parent or self, "Freigabe erforderlich · nicht anonymisierte Analyseinhalte",
            "Du möchtest " + relevant + " in eine ZIP-Datei übernehmen.\n\n"
            "Die Inhalte können echte FINs, Seriennummern, Namen und "
            "vertrauliche Mercedes-Benz-Befunde enthalten. "
            "Die Dateinamen werden neutralisiert, nicht aber die Inhalte. "
            "Die ZIP ist nicht verschlüsselt und es erfolgt KEINE "
            "automatische Anonymisierung oder externe Übertragung.\n\n"
            "Die Datei nur nach Unternehmensfreigabe extern teilen. "
            "Vertrauliche Originale wirklich lokal exportieren?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def prepare_workflow_cohort(self, fins: set[str]) -> None:
        """Einmaliger FIN-Filter für den nächsten Workflow-ZIP-Export."""
        self._next_workflow_fins = set(fins)

    def _request_export(self) -> None:
        """MainWindow owns the shared export card, standalone panel stays usable."""
        if self._use_shared_export_dialog:
            self.export_options_requested.emit()
        else:
            self._export()

    def use_shared_export_dialog(self) -> None:
        self._use_shared_export_dialog = True
        # Keine zwei widersprüchlichen Auswahlsätze; nur die Auswahl im
        # Popup gilt. Beim isolierten Panel bleiben die alten Optionen nutzbar.
        self.include_text.hide()
        self.include_qec_originale.hide()

    def _export(self) -> None:
        """Standalone fallback used by isolated source-panel dialogs."""
        if not self._can_start():
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "KI-Analysepaket für Fallclusterung erstellen",
            str(Path.home() / (
                "NTF-Insight-KI-Analyse-" + datetime.now().strftime("%Y%m%d-%H%M") + ".zip"
            )),
            "NTF KI-Analysepaket (*.zip)",
        )
        if not filename:
            return
        self.start_export(
            Path(filename),
            mit_freitext=self.include_text.isChecked(),
            mit_qec_originalen=self.include_qec_originale.isChecked(),
        )

    def start_export(
        self, destination: Path, *,
        mit_freitext: bool = False,
        mit_qec_originalen: bool = False,
        confirmation_parent: QWidget | None = None,
    ) -> bool:
        """Explicit selection from the modal dialog, never an implicit opt-in."""
        if not self._can_start():
            return False
        if not self._confirm_confidential(
            originals=mit_qec_originalen, text=mit_freitext,
            parent=confirmation_parent,
        ):
            return False
        destination = Path(destination)
        if destination.suffix.lower() != ".zip":
            destination = destination.with_suffix(".zip")
        mapping = destination.with_name(
            destination.stem + "_NICHT_HOCHLADEN_ZUORDNUNG.csv"
        )
        if destination.exists() or mapping.exists():
            QMessageBox.warning(
                self, "Analyse-Ziel bereits vorhanden",
                "ZIP oder private Pseudonymzuordnung existiert bereits. "
                "Bitte einen neuen Namen wählen; die Zuordnung wird nicht ersetzt.",
            )
            return False
        selected = self._next_workflow_fins
        self._next_workflow_fins = None
        self.worker = KIAnalyseWorker(
            self.service, destination,
            mit_freitext=mit_freitext,
            mit_qec_originalen=mit_qec_originalen,
            selected_fins=selected,
        )
        self.worker.progress.connect(self.status.setText)
        self.worker.progress.connect(self.export_progress.emit)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.export_button.setEnabled(False)
        self.import_button.setEnabled(False)
        self.include_text.setEnabled(False)
        self.include_qec_originale.setEnabled(False)
        self.status.setText("Versioniertes KI-Analysepaket wird lokal erstellt …")
        self.first_package_export_started.emit(destination)
        self.transfer_busy.emit(True)
        self.worker.start()
        return True

    def _completed(self, result) -> None:
        extra = (
            f" · {result.qec_originale} QEC-Originaldateien"
            if result.qec_originale else ""
        )
        gap = (
            f" · {result.fehlende_qec_originale} fehlende Belege, im ZIP dokumentiert"
            if result.fehlende_qec_originale else ""
        )
        self.status.setText(
            f"KI-Analysepaket bereit: {result.pfad.name} · "
            f"{result.faelle} Fälle, {result.fahrzeuge} Fahrzeuge, "
            f"{result.quicktests} QuickTests, {result.dtcs} DTC-Beobachtungen, "
            f"{result.qec_berichte} QEC-Berichte{extra}{gap}. "
            "Vor jeder Weitergabe Freigabe und ZIP-Inhalte prüfen. "
            f"Die lokale Datei {result.private_zuordnung.name} "
            "mit echten FIN-/Fall-Zuordnungen niemals hochladen."
        )
        self.first_package_exported.emit(result)

    def _failed(self, message: str) -> None:
        self.status.setText("KI-Analyseexport fehlgeschlagen: " + message)
        self.export_failed.emit(message)

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self.export_button.setEnabled(True)
        self.import_button.setEnabled(True)
        self.include_text.setEnabled(True)
        self.include_qec_originale.setEnabled(True)
        self.transfer_busy.emit(False)
        self.export_finished.emit()

    def _import_result(self) -> None:
        if not self._can_start():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "ChatGPT-Ergebnis im NTF-Insight-JSON-Vertrag wählen",
            str(Path.home()), "NTF ChatGPT-Auswertung (*.json)",
        )
        if not filename:
            return
        self.import_from_path(Path(filename))

    def import_from_path(self, path: Path) -> bool:
        """Ergebnis ohne zweiten Dateidialog importieren; Fehler sichtbar melden."""
        if not self._can_start():
            return False
        path = Path(path)
        try:
            if not path.is_file() or path.stat().st_size > MAX_JSON_SIZE:
                self._import_failed("JSON-Datei fehlt oder ist zu groß.")
                return False
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            paket_id = payload["paket_id"]
            self.analysis_store._mapping(paket_id, None)
            mapping_path = None
        except (OSError, UnicodeError, duckdb.Error, KeyError, ValueError, TypeError) as exc:
            # Nur bei tatsächlich fehlender DB-Zuordnung lokale CSV anbieten.
            # Die private Datei darf niemals extern hochgeladen werden.
            if "Paketzuordnung nicht" not in str(exc):
                self._import_failed(str(exc))
                return False
            mapping_file, _ = QFileDialog.getOpenFileName(
                self, "Lokale NICHT_HOCHLADEN-Zuordnung auswählen",
                str(Path.home()), "Private Paketzuordnung (*.csv)",
            )
            if not mapping_file:
                self._import_failed(
                    "Lokale Pseudonymzuordnung wurde nicht ausgewählt. "
                    "Es wurden keine Fälle geändert."
                )
                return False
            mapping_path = Path(mapping_file)

        self.import_worker = ChatGPTImportWorker(
            self.service, path, private_csv=mapping_path,
        )
        self.import_worker.progress.connect(self._import_progress)
        self.import_worker.completed.connect(self._import_completed)
        self.import_worker.failed.connect(self._import_failed)
        self.import_worker.finished.connect(self._import_finished)
        self.import_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status.setText("ChatGPT-Ergebnis und lokale Fallzuordnung prüfen …")
        self.analysis_import_started.emit(path.name)
        self.transfer_busy.emit(True)
        self.import_worker.start()
        return True

    def _import_progress(self, message: str) -> None:
        self.status.setText(message)
        self.analysis_import_progress.emit(message)

    def _import_completed(self, result: dict) -> None:
        suffix = " (bereits identisch importiert)" if result["bereits_importiert"] else ""
        self.status.setText(
            f"ChatGPT-Analyse {result['analyse_id']} lokal gespeichert: "
            f"{result['faelle']} Fälle, {result['cluster']} Cluster{suffix}. "
            "Vorschläge bleiben separat und bis zur fachlichen Prüfung offen."
        )
        self._refresh_imports()
        self.analysis_updated.emit()
        self.analysis_imported.emit(result)

    def _import_failed(self, message: str) -> None:
        self.status.setText("ChatGPT-Rückimport abgebrochen: " + message)
        self.analysis_import_failed.emit(message)

    def _import_finished(self) -> None:
        worker, self.import_worker = self.import_worker, None
        if worker is not None:
            worker.deleteLater()
        self.import_button.setEnabled(True)
        self.export_button.setEnabled(True)
        self.transfer_busy.emit(False)
        self.analysis_import_finished.emit()

    def _refresh_imports(self) -> None:
        self._visible = self.analysis_store.list_case_findings(limit=2000)
        self.review_model.set_rows([
            (
                item["analyse_id"], item["case_id"], item["cluster_id"] or "—",
                item["bewertung"].get("ntf_bewertung") or "Nicht bewertet",
                str(item["bewertung"].get("ursachenhypothese") or "")[:240],
                item["review_status"],
            )
            for item in self._visible
        ])
        self._review_enabled()

    def _review_enabled(self) -> None:
        active = (
            self.review_table.selectionModel().selectedRows()
            if self.review_table.selectionModel() else []
        )
        enabled = bool(active) and self.worker is None and self.import_worker is None
        self.review_confirm.setEnabled(enabled)
        self.review_reject.setEnabled(enabled)
        if enabled and len(active) == 1 and active[0].row() < len(self._visible):
            finding = self._visible[active[0].row()]
            self.review_details.setPlainText(
                json.dumps(finding["bewertung"], ensure_ascii=False, indent=2)[:20000]
            )
        else:
            self.review_details.clear()

    def _review(self, status: str) -> None:
        if not self._can_start():
            return
        selected = self.review_table.selectionModel().selectedRows()
        if len(selected) != 1:
            return
        row = selected[0].row()
        if row >= len(self._visible):
            return
        finding = self._visible[row]
        prompt = (
            f"ChatGPT-Vorschlag für Fall {finding['case_id']} "
            f"als {status.lower()} markieren?\n\n"
            "Dies ist nur ein Prüfvermerk. Die eigentliche Fallbewertung, "
            "der QEC-Status und Lieferantenangaben bleiben unverändert."
        )
        answer = QMessageBox.question(
            self, "Externen Analysevorschlag prüfen", prompt,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.analysis_store.set_review_status(
            finding["analyse_id"], finding["case_id"], status,
        )
        self._refresh_imports()
        self.review_note.setText(
            f"Prüfvermerk {status} lokal gespeichert. "
            "Keine automatische Änderung von NTF- oder Lieferantenentscheidungen."
        )
