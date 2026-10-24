"""Kompakte, nicht scrollende Startseite für den QEC-zu-Cluster-Workflow."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ntf_insight.components.registry import list_component_profiles
from ntf_insight.storage.workflow_progress import (
    WorkflowProgressStore, WorkflowProgress, normalize_part_number,
)


class WorkflowPage(QWidget):
    """Übersicht: Klick auf Station öffnet existierende Funktionsseite."""

    navigate = Signal(str, str)
    action_requested = Signal(str)

    # Jede Station hat ein eigenes Navigationsziel im vorhandenen Arbeitsbereich.
    STEPS = (
        ("QEC-FIN-Liste", "Kohorte & Sachnummer", "sources", "qec_list"),
        ("QEC-Befundung", "Berichte abrufen", "cases", "qec_reports"),
        ("NTF-Entscheidung", "NTF / Kein NTF / Offen", "sources", "qec_decision"),
        ("CPC3 / Diagnosen", "TP · QuickTest · TIPS", "cases", "quicktests"),
        ("Clusteranalyse", "Muster & Wiederkehr", "cases", "cluster"),
        ("Auswertung", "Bericht & ChatGPT", "sources", "chatgpt"),
    )

    def __init__(self, progress_store: WorkflowProgressStore, *, qec_store=None,
                 repository=None, quicktests=None, mode="local") -> None:
        super().__init__()
        self.progress_store = progress_store
        self.qec_store = qec_store
        self.repository = repository
        self.quicktests = quicktests
        self.mode = mode
        self.profile_id, part = progress_store.current_context()
        self.state = progress_store.load(self.profile_id, part)
        self.setObjectName("WorkflowPage")

        shell = QVBoxLayout(self)
        shell.setContentsMargins(24, 18, 24, 18)
        shell.setSpacing(12)
        top = QHBoxLayout()
        title = QLabel("NTF · Analyseworkflow", objectName="PageTitle")
        top.addWidget(title)
        top.addStretch()
        self.profile = QComboBox()
        self.profile.setAccessibleName("Bauteilprofil")
        for item in list_component_profiles():
            label = "Kühlmittelpumpe" if item.profile_id == "coolant_pump" else (
                "HV-Batterie" if item.profile_id == "hv_battery" else item.display_name
            )
            self.profile.addItem(label, item.profile_id)
        index = self.profile.findData(self.profile_id)
        if index >= 0:
            self.profile.setCurrentIndex(index)
        self.profile.currentIndexChanged.connect(self._change_context)
        top.addWidget(self.profile)
        self.part_number = QLineEdit(part)
        self.part_number.setPlaceholderText("Sachnummer · alle")
        self.part_number.setMaximumWidth(235)
        self.part_number.setAccessibleName("Frei eingebbare Sachnummer")
        self.part_number.editingFinished.connect(self._change_context)
        top.addWidget(self.part_number)
        shell.addLayout(top)

        self.subtitle = QLabel("QEC → NTF-Prüfung → Diagnose → Cluster → Ergebnis")
        self.subtitle.setObjectName("PageSubtitle")
        shell.addWidget(self.subtitle)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("CardTitle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(True)
        shell.addWidget(self.progress_label)
        shell.addWidget(self.progress)

        self.cards: list[QPushButton] = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, (name, detail, page, tab) in enumerate(self.STEPS):
            button = QPushButton()
            button.setObjectName("WorkflowStep")
            button.setProperty("workflowState", "pending")
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(108)
            button.setMaximumHeight(132)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"Schritt {index + 1}: {name}")
            button.clicked.connect(lambda _checked=False, n=index: self._open_step(n))
            self.cards.append(button)
            grid.addWidget(button, index // 3, index % 3)
        shell.addLayout(grid)
        self.step_hint = QLabel(objectName="PageSubtitle")
        shell.addWidget(self.step_hint)
        shell.addStretch(1)

        decision_row = QHBoxLayout()
        self.decision_label = QLabel()
        self.decision_label.setObjectName("PageSubtitle")
        decision_row.addWidget(self.decision_label, 1)
        self.review_button = QPushButton("Schritt geprüft")
        self.review_button.clicked.connect(self._review)
        decision_row.addWidget(self.review_button)
        shell.addLayout(decision_row)

        actions = QHBoxLayout()
        self.previous_button = QPushButton("← Zurück")
        self.previous_button.clicked.connect(lambda: self._move(-1))
        actions.addWidget(self.previous_button)
        self.next_button = QPushButton("Weiter →")
        self.next_button.clicked.connect(lambda: self._move(1))
        actions.addWidget(self.next_button)
        self.pause_button = QPushButton("Pausieren")
        self.pause_button.clicked.connect(self._toggle_pause)
        actions.addWidget(self.pause_button)
        shell.addLayout(actions)

        tools = QGridLayout()
        tools.setHorizontalSpacing(9)
        tools.setVerticalSpacing(9)
        self.tool_buttons = {}
        for n, (key, title) in enumerate((
            ("self_import", "Eigene Dateien importieren"),
            ("qec", "QEC / NTF bewerten"),
            ("pc_export", "PC-Export"),
            ("pc_import", "PC-Import"),
            ("ai_export", "ChatGPT-Paket exportieren"),
            ("ai_import", "ChatGPT-Ergebnis importieren"),
            ("cancel_import", "Import abbrechen"),
            ("resume_import", "Import fortsetzen"),
        )):
            button = QPushButton(title)
            button.setObjectName("WorkflowAction")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, action=key: self.action_requested.emit(action))
            tools.addWidget(button, n // 3, n % 3)
            self.tool_buttons[key] = button
        shell.addLayout(tools)
        self.note = QLabel()
        self.note.setObjectName("PageSubtitle")
        shell.addWidget(self.note)
        self.refresh()

    def _change_context(self) -> None:
        profile_id = self.profile.currentData()
        if not profile_id:
            return
        try:
            part = normalize_part_number(self.part_number.text())
        except ValueError:
            self.note.setText("Sachnummer zu lang oder ungültig.")
            return
        self.part_number.setText(part)
        self.profile_id = profile_id
        self.progress_store.select_context(profile_id, part)
        self.state = self.progress_store.load(profile_id, part)
        self.refresh()

    def _save(self) -> None:
        self.progress_store.save(self.profile_id, self.part_number.text(), self.state)
        self.refresh()

    def _open_step(self, index: int) -> None:
        if self.state.paused:
            return
        self.state = replace(self.state, step=index)
        self._save()
        _, _, page, tab = self.STEPS[index]
        self.navigate.emit(page, tab)

    def _move(self, delta: int) -> None:
        if self.state.paused:
            return
        target = max(0, min(len(self.STEPS) - 1, self.state.step + delta))
        if target != self.state.step:
            self._open_step(target)

    def _toggle_pause(self) -> None:
        self.state = replace(self.state, paused=not self.state.paused)
        self._save()

    def _review(self) -> None:
        step = self.state.step
        if self.state.paused or step not in (4, 5):
            return
        reviewed = set(self.state.reviewed_steps)
        if step in reviewed:
            reviewed.remove(step)
        else:
            reviewed.add(step)
        self.state = replace(self.state, reviewed_steps=tuple(sorted(reviewed)))
        self._save()

    def _qec_statistics(self) -> dict:
        if self.qec_store is None:
            return {}
        try:
            rows = self.qec_store.rows(self.progress_store.store.path.parent / "qec")
            part = normalize_part_number(self.part_number.text())
            if part:
                rows = [r for r in rows if normalize_part_number(r["part_number"]) == part]
            return self.qec_store.summarize_rows(rows)
        except (OSError, ValueError):
            return {}

    def refresh(self) -> None:
        stats = self._qec_statistics()
        total = stats.get("fins", 0)
        completed = [
            bool(total),
            bool(total and stats.get("downloaded", 0) >= total),
            bool(stats.get("cases") and stats.get("open", 0) == 0),
            bool(stats.get("with_tp", 0)) or bool(
                self.quicktests and self.quicktests.statistics().get("reports", 0)
            ),
            4 in self.state.reviewed_steps,
            5 in self.state.reviewed_steps,
        ]
        self.progress.setValue(round(sum(completed) * 100 / len(completed)))
        self.progress_label.setText(
            f"Schritt {self.state.step + 1} von 6 · {self.STEPS[self.state.step][0]}"
        )
        counts = [
            f"{total} FINs",
            f"{stats.get('downloaded', 0)}/{total} Berichte",
            f"{stats.get('ntf', 0)} NTF · {stats.get('not_ntf', 0)} kein NTF",
            f"{stats.get('with_tp', 0)} TP-FINs",
            "Fachliche Prüfung" if not completed[4] else "Geprüft",
            "Fachliche Prüfung" if not completed[5] else "Geprüft",
        ]
        for i, button in enumerate(self.cards):
            state = "done" if completed[i] else "pending"
            if i == self.state.step:
                state = "active"
            if self.state.paused and i == self.state.step:
                state = "paused"
            button.setProperty("workflowState", state)
            # Dynamische Statusfarben stammen aus dem zentralen Hell-/Dunkel-Theme.
            button.style().unpolish(button)
            button.style().polish(button)
            lamp = "●" if state == "active" else "✓" if state == "done" else (
                "Ⅱ" if state == "paused" else "○"
            )
            button.setText(
                f"{lamp}   {i + 1:02d}  {self.STEPS[i][0]}\n"
                f"       {counts[i]}\n"
                "       ↗ Arbeitsbereich öffnen"
            )
            button.setEnabled(not self.state.paused)
            button.setToolTip(
                f"{self.STEPS[i][1]} – Anklicken öffnet direkt die passende Funktion."
            )
        self.step_hint.setText(
            f"Aktuell: {self.STEPS[self.state.step][0]} · "
            "Kachel oder Weiter anklicken, um den Arbeitsschritt zu öffnen."
        )
        self.decision_label.setText(
            f"NTF {stats.get('ntf', 0)} · Kein NTF {stats.get('not_ntf', 0)}"
            f" · Offen {stats.get('open', 0)}  |  "
            "Lieferantenverantwortung nur mit Belegen"
        )
        self.previous_button.setEnabled(not self.state.paused and self.state.step > 0)
        self.next_button.setEnabled(not self.state.paused and self.state.step < 5)
        self.review_button.setVisible(self.state.step in (4, 5))
        self.review_button.setEnabled(not self.state.paused)
        self.review_button.setText(
            "Prüfung zurücknehmen" if self.state.step in self.state.reviewed_steps
            else "Schritt geprüft"
        )
        self.pause_button.setText("Fortsetzen" if self.state.paused else "Pausieren")
        self.note.setText(
            "Pausiert · Bearbeitungsstand lokal gesichert." if self.state.paused
            else "● Aktuell   ✓ Vorhanden/geprüft   ○ Offen · "
                 "Quellenstatus und fachliche Bestätigung getrennt"
        )
