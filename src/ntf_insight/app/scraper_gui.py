"""Kleines, eigenstaendiges Fenster zum Start der vorhandenen Datenabruf-CLIs."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
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
    ("dcdc223", "VeDoc · Hardwarehistorie"),
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
    """Mehrere Quellen parallel; pro Quelle genau ein separater CLI-Prozess."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ScraperFenster")
        self.setWindowTitle("NTF Insight | Datenabruf")
        self.setMinimumSize(620, 600)
        self.resize(735, 660)
        self._datei: Path | None = None
        self._prozesse: dict[str, QProcess] = {}
        self._laufstatus: dict[str, dict[str, Any]] = {}
        self._prozess: QProcess | None = None  # Kompatibel mit bestehender Einzelprozess-GUI.
        self._aktive_quelle = ""
        self._ausgabeordner: Path | None = None
        self._prozessausgabe = ""
        self._ausgabe_rest = ""
        self._abbruch = False
        self._qec_benennung = ""
        self._optionen_je_quelle: dict[str, dict[str, Any]] = {}

        self.setStyleSheet("""
            QWidget#ScraperFenster { background: #f5f5f5; color: #171717; }
            QLabel { color: #171717; background: transparent; }
            QLabel#Titel { font-size: 23px; font-weight: 700; }
            QLabel#Untertitel { color: #535353; font-size: 13px; }
            QLabel#Dateiname { color: #393939; font-size: 13px; }
            QLabel#Status { color: #393939; font-size: 13px; }
            QLabel#Quellenstatus { color: #444444; font-size: 12px; }
            QPushButton {
                color: #171717; background: #ffffff; border: 1px solid #b9b9b9;
                border-radius: 7px; padding: 12px 15px; text-align: left; min-height: 24px;
            }
            QPushButton:hover { background: #ebebeb; border-color: #868686; }
            QPushButton:focus { border: 2px solid #616161; }
            QPushButton#DateiButton { background: #202020; color: #ffffff; border-color: #202020; }
            QPushButton#DateiButton:hover { background: #424242; }
            QPushButton#AbbruchButton { background: #ededed; }
            QPushButton#StopButton { padding: 4px 8px; min-height: 20px; }
            QPushButton:disabled { color: #767676; background: #e9e9e9; border-color: #dddddd; }
            QSpinBox {
                color: #171717; background: white; padding: 5px;
                border: 1px solid #b9b9b9; border-radius: 5px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(11)

        titel = QLabel("NTF INSIGHT")
        titel.setObjectName("Titel")
        titel.setFont(QFont(resolve_fonts().heading_family, 18))
        layout.addWidget(titel)
        untertitel = QLabel("Datenabruf · Kühlmittelpumpe")
        untertitel.setObjectName("Untertitel")
        layout.addWidget(untertitel)
        layout.addSpacing(6)

        self.datei_button = QPushButton("TXT-Datei auswählen …")
        self.datei_button.setObjectName("DateiButton")
        self.datei_button.clicked.connect(self.datei_auswaehlen)
        layout.addWidget(self.datei_button)

        self.dateiname_label = QLabel("Noch keine TXT-Datei ausgewählt")
        self.dateiname_label.setObjectName("Dateiname")
        self.dateiname_label.setWordWrap(True)
        layout.addWidget(self.dateiname_label)

        parallel_zeile = QHBoxLayout()
        parallel_zeile.setSpacing(10)
        parallel_zeile.addWidget(QLabel("Datenquellen parallel:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setObjectName("ParallelQuellen")
        self.parallel_spin.setRange(1, len(QUELLEN))
        self.parallel_spin.setValue(2)
        self.parallel_spin.setToolTip(
            "Verschiedene Quellen gleichzeitig; innerhalb jeder Quelle bleiben FINs seriell."
        )
        self.parallel_spin.valueChanged.connect(lambda _zahl: self._buttons_aktualisieren())
        parallel_zeile.addWidget(self.parallel_spin)
        parallel_zeile.addSpacing(13)
        parallel_zeile.addWidget(QLabel("Pause nach SSO/PING-ID:"))
        self.sso_pause_spin = QSpinBox()
        self.sso_pause_spin.setObjectName("SsoPause")
        self.sso_pause_spin.setRange(30, 60)
        self.sso_pause_spin.setValue(45)
        self.sso_pause_spin.setSuffix(" s")
        self.sso_pause_spin.setToolTip(
            "Nach erfolgreicher Anmeldung mindestens diese Zeit bis zum naechsten Login."
        )
        parallel_zeile.addWidget(self.sso_pause_spin)
        parallel_zeile.addStretch(1)
        layout.addLayout(parallel_zeile)
        info = QLabel(
            "Pro Quelle maximal ein Abruf · SSO/PING-ID immer nacheinander · "
            "Abgeschlossene Daten bleiben beim Abbruch erhalten"
        )
        info.setObjectName("Untertitel")
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addSpacing(6)

        layout.addWidget(QLabel("Webscraper starten"))
        quellen_layout = QGridLayout()
        quellen_layout.setHorizontalSpacing(12)
        quellen_layout.setVerticalSpacing(12)
        self.quellen_buttons: dict[str, QPushButton] = {}
        self.quellen_status: dict[str, QLabel] = {}
        self.stop_buttons: dict[str, QPushButton] = {}
        for index, (kennung, name) in enumerate(QUELLEN):
            zelle = QWidget()
            zellen_layout = QVBoxLayout(zelle)
            zellen_layout.setContentsMargins(0, 0, 0, 0)
            zellen_layout.setSpacing(3)
            button = QPushButton(name)
            button.setObjectName("QuellenButton")
            button.setEnabled(False)
            button.clicked.connect(lambda _checked=False, q=kennung: self.scraper_starten(q))
            zellen_layout.addWidget(button)
            statuszeile = QHBoxLayout()
            statuszeile.setContentsMargins(2, 0, 2, 0)
            label = QLabel("Bereit")
            label.setObjectName("Quellenstatus")
            label.setWordWrap(True)
            label.setMinimumHeight(22)
            statuszeile.addWidget(label, 1)
            stop = QPushButton("Stop")
            stop.setObjectName("StopButton")
            stop.setEnabled(False)
            stop.clicked.connect(lambda _checked=False, q=kennung: self.abruf_abbrechen(q))
            statuszeile.addWidget(stop)
            zellen_layout.addLayout(statuszeile)
            quellen_layout.addWidget(zelle, index // 2, index % 2)
            self.quellen_buttons[kennung] = button
            self.quellen_status[kennung] = label
            self.stop_buttons[kennung] = stop
        layout.addLayout(quellen_layout)
        layout.addStretch(1)

        self.abbruch_button = QPushButton("Alle laufenden Abrufe abbrechen")
        self.abbruch_button.setObjectName("AbbruchButton")
        self.abbruch_button.setEnabled(False)
        self.abbruch_button.clicked.connect(self.alle_abbrechen)
        layout.addWidget(self.abbruch_button)
        self.status_label = QLabel("Bereit · Zuerst eine TXT-Datei wählen")
        self.status_label.setObjectName("Status")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)

    def _buttons_aktualisieren(self, *, laeuft: bool | None = None) -> None:
        # Argument nur fuer alte Aufrufer; massgeblich sind die aktiven Prozesse.
        anzahl = len(self._prozesse)
        self.datei_button.setEnabled(anzahl == 0)
        self.parallel_spin.setEnabled(anzahl == 0)
        self.sso_pause_spin.setEnabled(anzahl == 0)
        for quelle, button in self.quellen_buttons.items():
            button.setEnabled(
                self._datei is not None and quelle not in self._prozesse
                and anzahl < self.parallel_spin.value()
            )
            self.stop_buttons[quelle].setEnabled(quelle in self._prozesse)
        self.abbruch_button.setEnabled(anzahl > 0)

    def datei_auswaehlen(self) -> None:
        if self._prozesse:
            return
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
        self.status_label.setText("Datei gewählt · Jetzt einen oder mehrere Webscraper starten")
        self._buttons_aktualisieren()

    def scraper_starten(self, quelle: str) -> None:
        if quelle in self._prozesse or len(self._prozesse) >= self.parallel_spin.value():
            return
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
            befehl, basis = abruf_befehl(quelle, self._datei, optionen=optionen)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Abruf nicht möglich", str(exc))
            return

        self._optionen_je_quelle[quelle] = optionen
        if quelle == "qec":
            self._qec_benennung = str(optionen.get("benennung", ""))
        self._aktive_quelle = quelle
        self._ausgabeordner = basis
        self._prozessausgabe = ""
        self._ausgabe_rest = ""
        self._abbruch = False
        self._laufstatus[quelle] = {
            "ablage": basis, "text": "", "rest": "", "abbruch": False, "fortschritt": "",
        }
        prozess = QProcess(self)
        prozess.setProcessChannelMode(QProcess.MergedChannels)
        umgebung = QProcessEnvironment.systemEnvironment()
        umgebung.insert("PYTHONIOENCODING", "utf-8")
        umgebung.insert("PYTHONUNBUFFERED", "1")
        umgebung.insert("NTF_SSO_PAUSE_S", str(self.sso_pause_spin.value()))
        prozess.setProcessEnvironment(umgebung)
        prozess.setProgram(befehl[0])
        prozess.setArguments(befehl[1:])
        prozess.readyReadStandardOutput.connect(
            lambda q=quelle: self._ausgabe_lesen(q)
        )
        prozess.errorOccurred.connect(
            lambda fehler, q=quelle: self._prozessfehler(q, fehler)
        )
        prozess.finished.connect(
            lambda code, status, q=quelle: self._prozess_beendet(q, code, status)
        )
        self._prozesse[quelle] = prozess
        self._prozess = prozess
        self.quellen_status[quelle].setText("Startet · FIN-Fortschritt wird ermittelt")
        qec_infos = (
            f" · Benennung: {self._qec_benennung or 'Kühlmittelpumpe (Standard)'}"
            f" · Anhänge: {optionen.get('anhaenge', 'referenz')}"
            if quelle == "qec" else ""
        )
        self.status_label.setText(
            f"{QUELLEN_NAMEN[quelle]}{qec_infos} läuft · "
            f"{len(self._prozesse)}/{self.parallel_spin.value()} Quellen aktiv · "
            f"SSO-Abstand {self.sso_pause_spin.value()}s"
        )
        self._buttons_aktualisieren()
        prozess.start()

    @staticmethod
    def _zeile_bereinigen(text: str) -> str:
        """Keine vollstaendigen FINs im Uebersichtsfenster anzeigen."""
        text = " ".join(text.split())
        return re.sub(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{14,17}(?![A-Z0-9])",
                      "FIN [verdeckt]", text, flags=re.I)[-260:]

    def _ausgabe_lesen(self, quelle: str | None = None) -> None:
        if quelle is None:
            # Historischer Einzelprozess-Test; neue Signalverbindungen
            # nennen immer ihre Quelle.
            prozess = self._prozess
            lauf = None
        else:
            prozess = self._prozesse.get(quelle)
            lauf = self._laufstatus.get(quelle)
        if prozess is None:
            return
        text = bytes(prozess.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not text:
            return
        self._prozessausgabe = (self._prozessausgabe + text)[-4000:]
        if lauf is None:
            self._ausgabe_rest += text
            zeilen = self._ausgabe_rest.split("\n")
            self._ausgabe_rest = zeilen.pop()[-500:]
        else:
            lauf["text"] = (lauf["text"] + text)[-4000:]
            lauf["rest"] += text
            zeilen = lauf["rest"].split("\n")
            lauf["rest"] = zeilen.pop()[-500:]
        for zeile in zeilen:
            zeile = zeile.strip()
            if not zeile:
                continue
            # Einheitliches FIN-Format aus allen Quell-CLIs.
            match = re.search(r"\b(?:FIN(?:-Fortschritt)?|Ziel)\s*:?\s*(\d+)/(\d+)\b",
                              zeile, flags=re.I)
            if match is None:
                match = re.search(r"\[(\d+)/(\d+)\s+FIN\]", zeile)
            if lauf is not None and match is not None:
                einheit = "Ziel" if re.search(r"\bZiel\s+\d+/", zeile, re.I) else "FIN"
                lauf["fortschritt"] = f"{einheit} {match.group(1)}/{match.group(2)} · "
            nachricht = self._zeile_bereinigen(zeile)
            if lauf is not None and not lauf["abbruch"]:
                self.quellen_status[quelle].setText(
                    (lauf["fortschritt"] + nachricht)[-355:]
                )
                self.status_label.setText(
                    f"{QUELLEN_NAMEN[quelle]} · {lauf['fortschritt']}{nachricht}"
                )
            elif lauf is None and not self._abbruch:
                name = QUELLEN_NAMEN.get(self._aktive_quelle, self._aktive_quelle)
                self.status_label.setText(f"{name} · {nachricht}")

    def abruf_abbrechen(self, quelle: str | None = None) -> None:
        if quelle is None:
            self.alle_abbrechen()
            return
        prozess = self._prozesse.get(quelle)
        if prozess is None:
            return
        self._laufstatus[quelle]["abbruch"] = True
        self.quellen_status[quelle].setText("Abbruch angefordert · Gespeicherte Dateien bleiben")
        prozess.kill()

    def alle_abbrechen(self) -> None:
        for quelle in list(self._prozesse):
            self.abruf_abbrechen(quelle)

    def _aufräumen(self, quelle: str | None = None) -> None:
        if quelle is None:
            quelle = next(
                (q for q, p in self._prozesse.items() if p is self._prozess), None
            )
        prozess = self._prozesse.pop(quelle, None) if quelle else self._prozess
        if quelle:
            self._laufstatus.pop(quelle, None)
        self._prozess = next(iter(self._prozesse.values()), None)
        self._buttons_aktualisieren()
        if prozess is not None:
            prozess.deleteLater()

    def _prozessfehler(self, quelle: str, fehler: QProcess.ProcessError) -> None:
        prozess = self._prozesse.get(quelle)
        if prozess is None or fehler != QProcess.FailedToStart:
            return
        meldung = prozess.errorString()
        self._aufräumen(quelle)
        self.quellen_status[quelle].setText("Start fehlgeschlagen")
        self.status_label.setText(f"{QUELLEN_NAMEN[quelle]}: Start fehlgeschlagen")
        QMessageBox.critical(self, "Webscraper konnte nicht starten", meldung)

    def _prozess_beendet(
        self, quelle: str, code: int, status: QProcess.ExitStatus,
    ) -> None:
        if quelle not in self._prozesse:
            return
        self._ausgabe_lesen(quelle)
        lauf = self._laufstatus[quelle]
        abgebrochen = bool(lauf["abbruch"])
        fehlertext = "\n".join(lauf["text"].strip().splitlines()[-4:])[-600:]
        ablage = lauf["ablage"]
        fortschritt = lauf["fortschritt"]
        self._aufräumen(quelle)
        if abgebrochen:
            meldung = "abgebrochen · Bereits gespeicherte Daten bleiben erhalten"
        elif code == 0 and status == QProcess.NormalExit:
            meldung = f"abgeschlossen · Ablage: {ablage}"
        else:
            meldung = f"Fehler (Exitcode {code})"
            hinweis = f"{QUELLEN_NAMEN[quelle]} konnte nicht vollständig abgeschlossen werden."
            if fehlertext:
                hinweis += f"\n\nLetzte CLI-Meldungen:\n{fehlertext}"
            QMessageBox.warning(self, "Abruf fehlgeschlagen", hinweis)
        self.quellen_status[quelle].setText(f"{fortschritt}{meldung}")
        self.status_label.setText(f"{QUELLEN_NAMEN[quelle]}: {fortschritt}{meldung}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._prozesse:
            event.accept()
            return
        auswahl = QMessageBox.question(
            self, "Abrufe laufen",
            "Alle laufenden Abrufe abbrechen und das Fenster schließen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if auswahl != QMessageBox.Yes:
            event.ignore()
            return
        self.alle_abbrechen()
        for prozess in list(self._prozesse.values()):
            prozess.waitForFinished(2000)
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
