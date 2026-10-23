"""Air-gapped SMR-D workspace; no Softing runtime or network dependency."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.smrd.library import SmrdLocalLibrary


class _OfflineTask(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self, operation: str, *, smrd: Path | None = None,
        xml_files: list[Path] | None = None, bundle: Path | None = None,
        data_dir: Path, remember: bool = False,
    ) -> None:
        super().__init__()
        self.operation = operation
        self.smrd = smrd
        self.xml_files = xml_files
        self.bundle = bundle
        self.data_dir = data_dir
        self.remember = remember

    def run(self) -> None:
        try:
            if self.operation == "convert":
                from ntf_insight.smrd.offline_convert import offline_convert

                assert self.smrd is not None
                result = offline_convert(
                    self.smrd, xml_files=self.xml_files,
                    data_dir=self.data_dir, remember=self.remember,
                )
                self.completed.emit({"operation": "convert", "result": result})
            else:
                from ntf_insight.smrd.offline_convert import import_offline_bundle

                assert self.bundle is not None
                count = import_offline_bundle(self.bundle, data_dir=self.data_dir)
                self.completed.emit({
                    "operation": "import",
                    "result": {"imported_references": count},
                })
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class SmrdOfflinePage(QWidget):
    """Offline container metadata and existing XML reference conversion."""

    references_imported = Signal()

    def __init__(self, data_dir: Path) -> None:
        super().__init__()
        self.data_dir = Path(data_dir)
        self.library = SmrdLocalLibrary(data_dir=self.data_dir)
        self._worker: _OfflineTask | None = None
        self._bundle: Path | None = None
        self._result: dict | None = None
        self._selected_xml: list[Path] | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(12)
        root.addWidget(QLabel("SMR-D · Offline", objectName="PageTitle"))

        explain = QLabel(
            "Komplett lokal, ohne Softing-DTS, Lizenz oder Internet. "
            "Die SMR-D-Metadaten sind direkt lesbar. Für DTCs, Services und "
            "SDGs müssen bereits vorhandene lokale XML-Referenzexporte "
            "zugeordnet werden. Geschützte SMR-D-Binärdaten werden nicht "
            "entschlüsselt; keine DTC-Auslösebedingungen werden erfunden.",
            objectName="PageSubtitle",
        )
        explain.setWordWrap(True)
        root.addWidget(explain)

        root.addWidget(QLabel("Lokale Originaldatei (.smr-d)", objectName="CardTitle"))
        file_row = QHBoxLayout()
        self.smrd_path = QLineEdit()
        self.smrd_path.setPlaceholderText(
            "Datei unter .ntf-insight/smrd/originale auswählen …"
        )
        self.pick_smrd = QPushButton("SMR-D wählen")
        self.refresh_smrd = QPushButton("Originale erkennen")
        file_row.addWidget(self.smrd_path, 1)
        file_row.addWidget(self.pick_smrd)
        file_row.addWidget(self.refresh_smrd)
        root.addLayout(file_row)

        root.addWidget(QLabel("Vorhandene XML-Referenzen (optional)", objectName="CardTitle"))
        xml_row = QHBoxLayout()
        self.xml_status = QLabel("Noch keine XML-Dateien ausgewählt; gespeicherte Links verwenden")
        self.xml_status.setWordWrap(True)
        self.pick_xml = QPushButton("XML-Dateien wählen")
        self.clear_xml = QPushButton("Verknüpfung verwenden")
        xml_row.addWidget(self.xml_status, 1)
        xml_row.addWidget(self.pick_xml)
        xml_row.addWidget(self.clear_xml)
        root.addLayout(xml_row)

        self.remember_links = QCheckBox(
            "XML-Dateien lokal der SMR-D-Prüfsumme zuordnen (für spätere Offline-Läufe)"
        )
        self.remember_links.setChecked(True)
        root.addWidget(self.remember_links)

        commands = QHBoxLayout()
        self.convert_button = QPushButton("Offline konvertieren")
        self.import_button = QPushButton("Referenzen in lokale DuckDB importieren")
        self.import_button.setEnabled(False)
        commands.addWidget(self.convert_button)
        commands.addWidget(self.import_button)
        commands.addStretch(1)
        root.addLayout(commands)

        self.status = QLabel("Bereit: kein Internet und keine Softing-Lizenz notwendig.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(
            "Hier stehen Abdeckung, Referenzzahlen, SHA-256 und Hinweise zur Herkunft."
        )
        root.addWidget(self.details, 1)

        self.pick_smrd.clicked.connect(self._choose_smrd)
        self.refresh_smrd.clicked.connect(self._autofill_smrd)
        self.pick_xml.clicked.connect(self._choose_xml)
        self.clear_xml.clicked.connect(self._clear_xml)
        self.convert_button.clicked.connect(self._convert)
        self.import_button.clicked.connect(self._import_bundle)
        self._autofill_smrd()

    def _autofill_smrd(self) -> None:
        try:
            entries = self.library.list_smrd()
        except (ValueError, OSError) as exc:
            self.status.setText(f"SMR-D-Ordner nicht lesbar: {exc}")
            return
        if entries and not self.smrd_path.text().strip():
            self.smrd_path.setText(str(entries[0]["path"]))
        self.status.setText(f"{len(entries)} Original-SMR-D-Datei(en) lokal erkannt.")

    def _choose_smrd(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Lokale SMR-D-Datei wählen",
            str(self.library.originals),
            "SMR-D-Dateien (*.smr-d);;Alle Dateien (*)",
        )
        if chosen:
            self.smrd_path.setText(chosen)
            self._bundle = None
            self._result = None
            self.import_button.setEnabled(False)

    def _choose_xml(self) -> None:
        chosen, _ = QFileDialog.getOpenFileNames(
            self,
            "Bereits vorhandene lokale XML-Referenzen wählen",
            str(self.library.exports),
            "XML-Referenzen (*.xml)",
        )
        if chosen:
            self._selected_xml = [Path(p) for p in chosen]
            self.xml_status.setText(
                f"{len(self._selected_xml)} XML-Datei(en): "
                + ", ".join(p.name for p in self._selected_xml[:5])
            )
            self.import_button.setEnabled(False)

    def _clear_xml(self) -> None:
        self._selected_xml = None
        self.xml_status.setText(
            "Keine neue XML-Auswahl; vorhandene SHA-256-Zuordnung verwenden"
        )
        self.import_button.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        for button in (
            self.pick_smrd, self.refresh_smrd, self.pick_xml, self.clear_xml,
            self.convert_button,
        ):
            button.setEnabled(not busy)
        self.import_button.setEnabled(
            not busy and self._bundle is not None
            and self._result is not None
            and self._result.get("total_references", 0) > 0
        )

    def _start(self, operation: str, **arguments) -> None:
        if self._worker is not None:
            return
        worker = _OfflineTask(operation, data_dir=self.data_dir, **arguments)
        self._worker = worker
        self._set_busy(True)
        self.status.setText("Lokale Verarbeitung läuft. Kein Netzwerkzugriff.")
        worker.completed.connect(self._completed)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _convert(self) -> None:
        path = Path(self.smrd_path.text().strip())
        if not path.is_file() or path.suffix.casefold() != ".smr-d":
            self.status.setText("Bitte eine vorhandene lokale .smr-d-Datei wählen.")
            return
        self._bundle = None
        self._result = None
        self.import_button.setEnabled(False)
        self._start(
            "convert", smrd=path, xml_files=self._selected_xml,
            remember=self.remember_links.isChecked() and bool(self._selected_xml),
        )

    def _import_bundle(self) -> None:
        if self._bundle is None or self._result is None:
            return
        if not self._result.get("total_references"):
            self.status.setText("Nur Metadaten vorhanden; nichts zu importieren.")
            return
        self._start("import", bundle=self._bundle)

    def _completed(self, message: object) -> None:
        if not isinstance(message, dict):
            return
        operation = message.get("operation")
        result = message.get("result", {})
        if not isinstance(result, dict):
            return
        if operation == "convert":
            self._result = result
            self._bundle = Path(result["bundle"])
            self.details.setPlainText(json.dumps(
                result, ensure_ascii=False, indent=2,
            ))
            if not result.get("total_references"):
                self.status.setText(
                    "Nur SMR-D-Containerdaten ausgelesen. Für DTC-Referenzen "
                    "bitte lokale XML-Dateien auswählen; binärer Payload nicht decodiert."
                )
            else:
                self.status.setText(
                    f"{result['total_references']} belegte Referenzen lokal "
                    f"gebündelt. Native SMR-D-DTC-Decodierung: Nein."
                )
        else:
            self.status.setText(
                f"{result.get('imported_references', 0)} XML-Referenzen als "
                "Quellenwissen in der lokalen Datenbank gespeichert."
            )
            self.references_imported.emit()

    def _failed(self, error: str) -> None:
        self.status.setText("Offline-Vorgang fehlgeschlagen: " + error)
        self.details.appendPlainText(error)

    def _worker_finished(self) -> None:
        self._worker = None
        self._set_busy(False)
