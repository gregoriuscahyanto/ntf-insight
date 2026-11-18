"""Kleines, eigenstaendiges Fenster zum Start der vorhandenen Datenabruf-CLIs."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.acquisition.beschaffung_cli import _befehl
from ntf_insight.acquisition.output_paths import ausgabe_in_gruppe, sicherer_listenname
from ntf_insight.app.fonts import resolve_fonts
from ntf_insight.app.settings import AppPaths
from ntf_insight.app.scraper_optionen import DATEI_AUSGABEN, extra_argumente
from ntf_insight.app.dialogs.scraper_optionen_dialog import ScraperOptionenDialog


# Feste CLI-Kennungen: keine freie Shell- oder Kommandoeingabe durch die GUI.
QUELLEN: tuple[tuple[str, str], ...] = (
    ("qec", "QEC · Befundungsberichte"),
    ("quicktests", "Diagnosis Viewer · QuickTests"),
    ("tips", "XENTRY · TIPS Writer"),
    ("wem", "Diagnosis Viewer · WEM"),
    ("sa-codes", "VeDoc · Fahrzeugcodes"),
    ("dcdc223", "VeDoc · Hardwarehistorie (DCDC223)"),
)
QUELLEN_NAMEN = dict(QUELLEN)


def abruf_befehl(
    quelle: str, eingabe: Path, *, qec_benennung: str = "",
    optionen: Mapping[str, Any] | None = None,
) -> tuple[list[str], Path]:
    """Direktaufruf der bestehenden Einzel-CLI, ohne Shell oder zweiten Wrapper-Prozess.

    Ausgaben werden bewusst im privaten Benutzerprofil statt im Git-Repository abgelegt.
    """
    if quelle not in QUELLEN_NAMEN:
        raise ValueError("Unbekannte Datenquelle.")
    eingabe = Path(eingabe).expanduser().resolve()
    if not eingabe.is_file() or eingabe.suffix.casefold() != ".txt":
        raise ValueError("Bitte eine vorhandene TXT-Datei auswählen.")
    if quelle != "qec" and qec_benennung.strip():
        raise ValueError("Ein Benennungsfilter ist nur bei QEC möglich.")

    werte = dict(optionen or {})
    if qec_benennung.strip():
        if "benennung" in werte and werte["benennung"] != qec_benennung.strip():
            raise ValueError("QEC-Benennung wurde widersprüchlich angegeben.")
        werte["benennung"] = qec_benennung.strip()
    zusatz, eigener_ausgabeort = extra_argumente(quelle, werte)
    basis = AppPaths.default().data_dir / "abrufe" / sicherer_listenname(eingabe)
    # Fuer frei waehlbare Hardwareobjekte einen neutralen VeDoc-Ordner nutzen.
    historie_anders = quelle == "dcdc223" and (
        str(werte.get("objekt") or "DCDC223") != "DCDC223"
        or str(werte.get("attribut") or "Seriennummer") != "Seriennummer"
    )
    zielquelle = "vedoc-historie" if historie_anders else quelle
    ziel = eigener_ausgabeort or ausgabe_in_gruppe(basis, zielquelle)
    if ziel == eingabe:
        raise ValueError("Eingabe- und Ausgabedatei dürfen nicht identisch sein.")
    if werte.get("profil"):
        profil = Path(str(werte["profil"])).expanduser().resolve()
        zielordner = ziel.parent if quelle in DATEI_AUSGABEN else ziel
        if profil == zielordner or profil in zielordner.parents or zielordner in profil.parents:
            raise ValueError("Edge-Profil und Ausgabeordner müssen getrennt sein.")
    befehl = _befehl(quelle, eingabe, ziel, manuell=False)
    befehl.extend(zusatz)
    # Mit pythonw.exe gestartete Wheel-GUIs benoetigen fuer CLI-Stdout python.exe.
    python = Path(befehl[0])
    if os.name == "nt" and python.name.casefold() == "pythonw.exe":
        befehl[0] = str(python.with_name("python.exe"))
    return befehl, eigener_ausgabeort or basis


class ScraperFenster(QWidget):
    """Eine FIN-Liste und je ein Button fuer eine vorhandene Web-Datenquelle."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ScraperFenster")
        self.setWindowTitle("NTF Insight | Datenabruf")
        self.setMinimumSize(580, 445)
        self.resize(670, 485)
        self._datei: Path | None = None
        self._prozess: QProcess | None = None
        self._aktive_quelle = ""
        self._ausgabeordner: Path | None = None
        self._prozessausgabe = ""
        self._abbruch = False
        self._qec_benennung = ""  # Kompatibler Kurzstatus für den QEC-Suchbegriff.
        self._optionen_je_quelle: dict[str, dict[str, Any]] = {}
        self._aktive_optionen: dict[str, Any] = {}

        self.setStyleSheet("""
            QWidget#ScraperFenster { background: #f5f5f5; color: #171717; }
            QLabel { color: #171717; background: transparent; }
            QLabel#Titel { font-size: 23px; font-weight: 700; }
            QLabel#Untertitel { color: #535353; font-size: 13px; }
            QLabel#Dateiname { color: #393939; font-size: 13px; }
            QLabel#Status { color: #393939; font-size: 13px; }
            QPushButton {
                color: #171717; background: #ffffff; border: 1px solid #b9b9b9;
                border-radius: 7px; padding: 12px 15px; text-align: left;
                min-height: 25px;
            }
            QPushButton:hover { background: #ebebeb; border-color: #868686; }
            QPushButton:focus { border: 2px solid #616161; }
            QPushButton#DateiButton { background: #202020; color: #ffffff; border-color: #202020; }
            QPushButton#DateiButton:hover { background: #424242; }
            QPushButton#AbbruchButton { background: #ededed; }
            QPushButton:disabled { color: #767676; background: #e9e9e9; border-color: #dddddd; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 25, 26, 25)
        layout.setSpacing(13)

        titel = QLabel("NTF INSIGHT")
        titel.setObjectName("Titel")
        titel.setFont(QFont(resolve_fonts().heading_family, 18))
        layout.addWidget(titel)
        untertitel = QLabel("Datenabruf · Kühlmittelpumpe")
        untertitel.setObjectName("Untertitel")
        layout.addWidget(untertitel)
        layout.addSpacing(7)

        self.datei_button = QPushButton("TXT-Datei auswählen …")
        self.datei_button.setObjectName("DateiButton")
        self.datei_button.clicked.connect(self.datei_auswaehlen)
        layout.addWidget(self.datei_button)

        self.dateiname_label = QLabel("Noch keine TXT-Datei ausgewählt")
        self.dateiname_label.setObjectName("Dateiname")
        self.dateiname_label.setWordWrap(True)
        layout.addWidget(self.dateiname_label)
        layout.addSpacing(9)

        beschriftung = QLabel("Webscraper starten")
        layout.addWidget(beschriftung)
        quellen_layout = QGridLayout()
        quellen_layout.setHorizontalSpacing(11)
        quellen_layout.setVerticalSpacing(11)
        self.quellen_buttons: dict[str, QPushButton] = {}
        for index, (kennung, name) in enumerate(QUELLEN):
            button = QPushButton(name)
            button.setObjectName("QuellenButton")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, q=kennung: self.scraper_starten(q))
            quellen_layout.addWidget(button, index // 2, index % 2)
            self.quellen_buttons[kennung] = button
        layout.addLayout(quellen_layout)
        layout.addStretch(1)

        self.abbruch_button = QPushButton("Laufenden Abruf abbrechen")
        self.abbruch_button.setObjectName("AbbruchButton")
        self.abbruch_button.setEnabled(False)
        self.abbruch_button.clicked.connect(self.abruf_abbrechen)
        layout.addWidget(self.abbruch_button)
        self.status_label = QLabel("Bereit · Zuerst eine TXT-Datei wählen")
        self.status_label.setObjectName("Status")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

    def _buttons_aktualisieren(self, *, laeuft: bool) -> None:
        self.datei_button.setEnabled(not laeuft)
        for button in self.quellen_buttons.values():
            button.setEnabled(self._datei is not None and not laeuft)
        self.abbruch_button.setEnabled(laeuft)

    def datei_auswaehlen(self) -> None:
        pfad, _ = QFileDialog.getOpenFileName(
            self, "FIN-/TIPS-TXT-Datei auswählen", str(Path.home()), "Textdateien (*.txt)"
        )
        if not pfad:
            return
        datei = Path(pfad)
        if not datei.is_file() or datei.suffix.casefold() != ".txt":
            QMessageBox.warning(self, "Ungültige Datei", "Bitte eine vorhandene TXT-Datei auswählen.")
            return
        self._datei = datei.resolve()
        self.dateiname_label.setText(self._datei.name)
        self.status_label.setText("Datei gewählt · Jetzt einen Webscraper starten")
        self._buttons_aktualisieren(laeuft=False)

    def scraper_starten(self, quelle: str) -> None:
        if self._prozess is not None:
            return  # Keine doppelte Ausfuehrung mit denselben Edge-Profilen.
        if self._datei is None:
            QMessageBox.information(self, "TXT-Datei fehlt", "Bitte zuerst eine TXT-Datei wählen.")
            return
        dialog = ScraperOptionenDialog(
            quelle, QUELLEN_NAMEN[quelle], self._optionen_je_quelle.get(quelle), self,
        )
        if not dialog.exec():
            return
        optionen = dialog.werte()
        try:
            befehl, basis = abruf_befehl(
                quelle, self._datei, optionen=optionen,
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Abruf nicht möglich", str(exc))
            return

        self._optionen_je_quelle[quelle] = optionen
        self._aktive_optionen = optionen
        if quelle == "qec":
            self._qec_benennung = str(optionen.get("benennung", ""))
        self._aktive_quelle = quelle
        self._ausgabeordner = basis
        self._prozessausgabe = ""
        self._abbruch = False
        prozess = QProcess(self)
        prozess.setProcessChannelMode(QProcess.MergedChannels)
        umgebung = QProcessEnvironment.systemEnvironment()
        umgebung.insert("PYTHONIOENCODING", "utf-8")
        umgebung.insert("PYTHONUNBUFFERED", "1")
        prozess.setProcessEnvironment(umgebung)
        prozess.setProgram(befehl[0])
        prozess.setArguments(befehl[1:])
        prozess.readyReadStandardOutput.connect(self._ausgabe_lesen)
        prozess.errorOccurred.connect(self._prozessfehler)
        prozess.finished.connect(self._prozess_beendet)
        self._prozess = prozess
        self._buttons_aktualisieren(laeuft=True)
        suchfilter = (
            f" · Benennung: {self._qec_benennung or 'Kühlmittelpumpe (Standard)'}"
            f" · Anhänge: {optionen.get('anhaenge', 'referenz')}"
            if quelle == "qec" else ""
        )
        self.status_label.setText(
            f"{QUELLEN_NAMEN[quelle]}{suchfilter} läuft · "
            "SSO/PING ID ggf. in Edge bestätigen"
        )
        prozess.start()

    def _ausgabe_lesen(self) -> None:
        if self._prozess is None:
            return
        text = bytes(self._prozess.readAllStandardOutput()).decode("utf-8", errors="replace")
        # Nur im Arbeitsspeicher und begrenzt; keine vertraulichen FINs in Logdateien.
        self._prozessausgabe = (self._prozessausgabe + text)[-4000:]

    def abruf_abbrechen(self) -> None:
        if self._prozess is None:
            return
        self._abbruch = True
        self.status_label.setText("Abruf wird beendet · Bereits gespeicherte Dateien bleiben erhalten")
        self._prozess.kill()

    def _aufräumen(self) -> None:
        prozess = self._prozess
        self._prozess = None
        self._buttons_aktualisieren(laeuft=False)
        if prozess is not None:
            prozess.deleteLater()

    def _prozessfehler(self, fehler: QProcess.ProcessError) -> None:
        if fehler != QProcess.FailedToStart or self._prozess is None:
            return
        meldung = self._prozess.errorString()
        self._aufräumen()
        self.status_label.setText("Start fehlgeschlagen")
        QMessageBox.critical(self, "Webscraper konnte nicht starten", meldung)

    def _prozess_beendet(self, code: int, status: QProcess.ExitStatus) -> None:
        self._ausgabe_lesen()
        quelle = QUELLEN_NAMEN.get(self._aktive_quelle, self._aktive_quelle)
        ausgabe = self._ausgabeordner
        abgebrochen = self._abbruch
        fehlertext = "\n".join(self._prozessausgabe.strip().splitlines()[-4:])[-600:]
        self._aufräumen()
        if abgebrochen:
            self.status_label.setText(f"{quelle}: abgebrochen · Bereits geladene Dateien bleiben erhalten")
        elif code == 0 and status == QProcess.NormalExit:
            self.status_label.setText(f"{quelle}: abgeschlossen · Ablage: {ausgabe}")
        else:
            self.status_label.setText(f"{quelle}: Fehler (Exitcode {code})")
            hinweis = f"{quelle} konnte nicht vollständig abgeschlossen werden."
            if fehlertext:
                hinweis += f"\n\nLetzte CLI-Meldungen:\n{fehlertext}"
            QMessageBox.warning(self, "Abruf fehlgeschlagen", hinweis)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._prozess is None:
            event.accept()
            return
        auswahl = QMessageBox.question(
            self, "Abruf läuft", "Den laufenden Abruf abbrechen und das Fenster schließen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if auswahl != QMessageBox.Yes:
            event.ignore()
            return
        self._abbruch = True
        self._prozess.kill()
        self._prozess.waitForFinished(2000)
        event.accept()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NTF Insight – Datenabruf")
    app.setOrganizationName("NTF Insight")
    app.setStyle("Fusion")
    schriften = resolve_fonts()
    app.setFont(QFont(schriften.body_family, 10))
    fenster = ScraperFenster()
    fenster.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
