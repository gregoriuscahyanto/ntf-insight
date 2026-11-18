"""Kompakter Einstellungsdialog fuer jeweils einen der sechs Webscraper."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.scraper_optionen import (
    DATEI_AUSGABEN, QUELLEN_OPTIONEN, CliOption, extra_argumente,
)


class ScraperOptionenDialog(QDialog):
    """Nur bekannte Schalter zulassen und vor dem CLI-Start pruefen."""

    def __init__(
        self,
        quelle: str,
        quellname: str,
        vorbelegung: Mapping[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if quelle not in QUELLEN_OPTIONEN:
            raise ValueError("Unbekannte Datenquelle.")
        self.quelle = quelle
        self.felder: dict[str, QWidget] = {}
        self.setWindowTitle(f"NTF Insight | {quellname} – Einstellungen")
        self.setMinimumWidth(580)
        self.resize(660, min(760, 240 + 53 * len(QUELLEN_OPTIONEN[quelle])))
        self.setStyleSheet("""
            QDialog { background: #f5f5f5; color: #171717; }
            QLabel, QCheckBox { color: #171717; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: white; color: #171717; border: 1px solid #b9b9b9;
                border-radius: 5px; padding: 6px; min-height: 22px;
            }
            QLineEdit:focus, QComboBox:focus { border: 2px solid #555555; }
            QPushButton { color: #171717; background: white;
                border: 1px solid #b9b9b9; border-radius: 6px;
                padding: 8px 12px; min-height: 22px; }
            QPushButton:hover { background: #eaeaea; }
            QPushButton#StartButton { color: white; background: #202020;
                border-color: #202020; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)

        titel = QLabel(quellname)
        titel.setStyleSheet("font-size: 19px; font-weight: 700;")
        layout.addWidget(titel)
        beschreibung = QLabel(
            "Optionale CLI-Parameter festlegen. Unveränderte Einstellungen "
            "verwenden weiterhin die bisherigen Standardwerte."
        )
        beschreibung.setWordWrap(True)
        layout.addWidget(beschreibung)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inhalt = QWidget()
        formular = QFormLayout(inhalt)
        formular.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        formular.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        formular.setHorizontalSpacing(18)
        formular.setVerticalSpacing(12)
        vor = dict(vorbelegung or {})
        for spec in QUELLEN_OPTIONEN[quelle]:
            kontrolle = self._feld(spec, vor.get(spec.name, spec.standard))
            self.felder[spec.name] = kontrolle
            if spec.typ == "bool":
                formular.addRow("", kontrolle)
            elif spec.typ in {"directory", "output"}:
                container = QWidget()
                zeile = QHBoxLayout(container)
                zeile.setContentsMargins(0, 0, 0, 0)
                zeile.setSpacing(6)
                zeile.addWidget(kontrolle, stretch=1)
                knopf = QPushButton("…")
                knopf.setToolTip("Pfad auswählen")
                knopf.setMaximumWidth(40)
                knopf.clicked.connect(
                    lambda _checked=False, option=spec: self._pfad_waehlen(option)
                )
                zeile.addWidget(knopf)
                formular.addRow(spec.titel + ":", container)
            else:
                formular.addRow(spec.titel + ":", kontrolle)
        scroll.setWidget(inhalt)
        layout.addWidget(scroll, stretch=1)

        hinweis = QLabel(
            "Passwortabfrage per Terminal ist hier nicht verfügbar. "
            "Verwende den Betriebssystem-Tresor oder die Anmeldung in Edge."
        )
        hinweis.setStyleSheet("color: #555555; font-size: 12px;")
        hinweis.setWordWrap(True)
        layout.addWidget(hinweis)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Abruf starten")
        buttons.button(QDialogButtonBox.Ok).setObjectName("StartButton")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._pruefen_und_starten)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _feld(self, spec: CliOption, wert: Any) -> QWidget:
        if spec.typ == "bool":
            widget = QCheckBox(spec.titel)
            widget.setChecked(bool(wert))
        elif spec.typ == "choice":
            widget = QComboBox()
            for code, anzeige in spec.auswahl:
                widget.addItem(anzeige, code)
            index = widget.findData(wert)
            widget.setCurrentIndex(index if index >= 0 else 0)
        elif spec.typ == "int":
            widget = QSpinBox()
            widget.setRange(int(spec.minimum or 0), int(spec.maximum or 999999))
            widget.setValue(int(wert))
        elif spec.typ == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(2)
            widget.setSingleStep(0.25)
            widget.setRange(
                float(spec.minimum if spec.minimum is not None else 0),
                float(spec.maximum if spec.maximum is not None else 999999),
            )
            widget.setValue(float(wert))
        else:
            widget = QLineEdit(str(wert))
            widget.setMaxLength(500)
            if spec.typ in {"directory", "output"}:
                widget.setPlaceholderText("Standardablage verwenden")
            elif spec.name == "benennung":
                widget.setPlaceholderText("z. B. DCDC, DCDC223, DC/DC")
        if spec.hilfe:
            widget.setToolTip(spec.hilfe)
        return widget

    def _pfad_waehlen(self, spec: CliOption) -> None:
        feld = self.felder[spec.name]
        assert isinstance(feld, QLineEdit)
        if spec.typ == "output" and self.quelle in DATEI_AUSGABEN:
            pfad, _ = QFileDialog.getSaveFileName(
                self, "JSON-Ausgabe festlegen", feld.text(), "JSON-Dateien (*.json)"
            )
        else:
            pfad = QFileDialog.getExistingDirectory(
                self, "Ausgabe-/Profilordner auswählen", feld.text()
            )
        if pfad:
            feld.setText(pfad)

    def werte(self) -> dict[str, Any]:
        """Aktuelle Feldwerte, ohne Passwoerter oder beliebige CLI-Tokens."""
        werte: dict[str, Any] = {}
        for spec in QUELLEN_OPTIONEN[self.quelle]:
            feld = self.felder[spec.name]
            if isinstance(feld, QCheckBox):
                wert = feld.isChecked()
            elif isinstance(feld, QComboBox):
                wert = feld.currentData()
            elif isinstance(feld, (QSpinBox, QDoubleSpinBox)):
                wert = feld.value()
            else:
                assert isinstance(feld, QLineEdit)
                wert = feld.text().strip()
            werte[spec.name] = wert
        return werte

    def _pruefen_und_starten(self) -> None:
        try:
            extra_argumente(self.quelle, self.werte())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Ungültige Einstellung", str(exc))
            return
        self.accept()
