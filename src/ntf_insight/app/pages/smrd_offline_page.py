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
        runtime_dir: Path | None = None, ecu: str | None = None,
        vendor_modes: tuple[str, ...] = ("ECU", "DTCSXML"),
    ) -> None:
        super().__init__()
        self.operation = operation
        self.smrd = smrd
        self.xml_files = xml_files
        self.bundle = bundle
        self.data_dir = data_dir
        self.remember = remember
        self.runtime_dir = runtime_dir
        self.ecu = ecu
        self.vendor_modes = vendor_modes

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
            elif self.operation == "smrd2xml":
                from ntf_insight.smrd.smrd2xml_runner import run_smrd2xml

                assert self.smrd is not None
                result = run_smrd2xml(
                    self.smrd, runtime_dir=self.runtime_dir,
                    data_dir=self.data_dir, ecu=self.ecu,
                    modes=self.vendor_modes, remember=self.remember,
                )
                self.completed.emit({"operation": "smrd2xml", "result": result})
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
            "Zwei Offline-Wege: Ohne Herstellerprogramm werden SMR-D-Metadaten "
            "und vorhandene XML-Referenzen verarbeitet (lizenzfrei). "
            "Optional kannst du dein lokal installiertes Smrd2Xml.exe direkt "
            "starten und dessen echte XML-Ausgaben übernehmen. "
            "Das Herstellerprogramm kann eine gültige lokale DTS-Lizenz benötigen; "
            "NTF Insight umgeht keine Lizenzprüfung.",
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

        root.addWidget(QLabel(
            "Optionaler Originalkonverter: Smrd2Xml.exe", objectName="CardTitle"
        ))
        runtime_row = QHBoxLayout()
        self.vendor_runtime = QLineEdit(str(self.library.root / "runtime" / "SMRxView"))
        self.vendor_runtime.setPlaceholderText("Lokaler SMRxView-Ordner mit Smrd2Xml.exe")
        self.pick_vendor_runtime = QPushButton("Laufzeit wählen")
        runtime_row.addWidget(self.vendor_runtime, 1)
        runtime_row.addWidget(self.pick_vendor_runtime)
        root.addLayout(runtime_row)

        options_row = QHBoxLayout()
        options_row.addWidget(QLabel("ECU:"))
        self.ecu_name = QLineEdit()
        self.ecu_name.setPlaceholderText("ECU-Name, z.B. CPC3")
        self.ecu_name.setMaximumWidth(190)
        options_row.addWidget(self.ecu_name)
        self.export_ecu = QCheckBox("ECU/XML")
        self.export_ecu.setChecked(True)
        self.export_dtcs = QCheckBox("DTCSXML")
        self.export_dtcs.setChecked(True)
        self.export_compar = QCheckBox("COMPAR")
        self.export_canmodel = QCheckBox("CANMODEL")
        for choice in (self.export_ecu, self.export_dtcs, self.export_compar, self.export_canmodel):
            options_row.addWidget(choice)
        options_row.addStretch(1)
        root.addLayout(options_row)
        vendor_row = QHBoxLayout()
        self.vendor_button = QPushButton("Smrd2Xml.exe lokal ausführen")
        self.vendor_note = QLabel(
            "Keine Internetverbindung erforderlich; BaseSystem-Lizenz ggf. trotzdem erforderlich."
        )
        self.vendor_note.setWordWrap(True)
        vendor_row.addWidget(self.vendor_button)
        vendor_row.addWidget(self.vendor_note, 1)
        root.addLayout(vendor_row)

        commands = QHBoxLayout()
        self.convert_button = QPushButton("Offline konvertieren")
        self.import_button = QPushButton("Referenzen in lokale DuckDB importieren")
        self.import_button.setEnabled(False)
        commands.addWidget(self.convert_button)
        commands.addWidget(self.import_button)
        commands.addStretch(1)
        root.addLayout(commands)

        self.status = QLabel(
            "Metadatenmodus: ohne DTS/Lizenz. Smrd2Xml-Programm: ggf. DTS-Lizenz notwendig."
        )
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
        self.vendor_button.clicked.connect(self._run_vendor)
        self.pick_vendor_runtime.clicked.connect(self._choose_vendor_runtime)
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
            self._autofill_ecu(entries[0]["path"])
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
            self._autofill_ecu(Path(chosen))
            self._bundle = None
            self._result = None
            self.import_button.setEnabled(False)

    def _autofill_ecu(self, path: Path) -> None:
        from ntf_insight.smrd.smrd2xml_runner import guess_ecu_name

        try:
            self.ecu_name.setText(guess_ecu_name(path))
        except ValueError:
            self.ecu_name.clear()

    def _choose_vendor_runtime(self) -> None:
        location = QFileDialog.getExistingDirectory(
            self, "Ordner mit Smrd2Xml.exe wählen", self.vendor_runtime.text(),
        )
        if location:
            self.vendor_runtime.setText(location)

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
            self.convert_button, self.vendor_button, self.pick_vendor_runtime,
            self.export_ecu, self.export_dtcs, self.export_compar,
            self.export_canmodel, self.ecu_name,
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
        self.status.setText(
            "Lokale Verarbeitung läuft. NTF Insight nutzt kein Netzwerk; "
            "das Verhalten des externen Konverters kann nicht garantiert werden."
        )
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

    def _run_vendor(self) -> None:
        path = Path(self.smrd_path.text().strip())
        if not path.is_file() or path.suffix.casefold() != ".smr-d":
            self.status.setText("Bitte zuerst eine vorhandene SMR-D-Datei wählen.")
            return
        runtime = Path(self.vendor_runtime.text().strip())
        if not (runtime / "Smrd2Xml.exe").is_file():
            self.status.setText(
                "Smrd2Xml.exe fehlt im gewählten Laufzeitordner. "
                "Es wird nichts ausgeführt."
            )
            return
        modes = tuple(
            name for name, checkbox in (
                ("ECU", self.export_ecu),
                ("DTCSXML", self.export_dtcs),
                ("COMPAR", self.export_compar),
                ("CANMODEL", self.export_canmodel),
            ) if checkbox.isChecked()
        )
        if not modes:
            self.status.setText("Bitte mindestens einen Smrd2Xml-Modus wählen.")
            return
        self._bundle = None
        self._result = None
        self.import_button.setEnabled(False)
        self._start(
            "smrd2xml", smrd=path, runtime_dir=runtime,
            ecu=self.ecu_name.text().strip() or None, vendor_modes=modes,
            remember=self.remember_links.isChecked(),
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
        if operation in ("convert", "smrd2xml"):
            self._result = result
            self._bundle = Path(result["bundle"]) if result.get("bundle") else None
            self.details.setPlainText(json.dumps(
                result, ensure_ascii=False, indent=2,
            ))
            if operation == "smrd2xml":
                if result.get("total_references"):
                    self.status.setText(
                        f"Smrd2Xml.exe: {result['total_references']} XML-Referenzen "
                        "erfasst. Kein Import durchgeführt; Datenherkunft siehe Bericht."
                    )
                else:
                    self.status.setText(
                        "Smrd2Xml.exe beendet, jedoch kein indexierbares XML gefunden. "
                        "Bitte Konverter-Logs und Lizenz-/Modusausgabe prüfen."
                    )
            elif not result.get("total_references"):
                self.status.setText(
                    "Nur SMR-D-Containerdaten ausgelesen. Für DTC-Referenzen "
                    "bitte lokale XML-Dateien auswählen; binärer Payload nicht decodiert."
                )
            else:
                self.status.setText(
                    f"{result['total_references']} belegte Referenzen lokal "
                    "gebündelt. Native SMR-D-DTC-Decodierung: Nein."
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
