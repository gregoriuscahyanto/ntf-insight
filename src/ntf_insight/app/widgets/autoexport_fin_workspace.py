"""German local-only AutoExport FIN grouping, separate from QEC/NTF clustering.

The imported AutoExport may hold thousands of vehicles without a documented
pump replacement. A diagnostic pattern is NOT a failed pump or NTF finding.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QTableView, QVBoxLayout, QWidget,
)

from ntf_insight.analysis.autoexport_fin_patterns import (
    FinPatternResult, cluster_autoexport_fins,
)
from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.app.widgets.fin_pattern_bar_chart import FinPatternBarChart
from ntf_insight.domain.case import NTFCase
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


# Ensure QThreads survive window rebuilds after a new source import.
_ACTIVE_FIN_TASKS: set[QThread] = set()


class _FinPatternTask(QThread):
    calculated = Signal(object)
    failed = Signal(str)
    phase = Signal(str)

    def __init__(
        self,
        source: SourceKnowledgeStore,
        linked: dict[str, tuple[str, ...]],
        pump_swap_dates: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.linked = linked
        self.pump_swap_dates = pump_swap_dates

    def run(self) -> None:
        try:
            self.phase.emit(
                "Lese eindeutige FINs und ECU:DTC-Muster aus dem lokalen AutoExport …"
            )
            fins, patterns, labels = self.source.autoexport_fin_dtc_signatures(
                pump_swap_dates=self.pump_swap_dates
            )
            self.phase.emit(
                "Bilde Diagnosegruppen aus FIN-Merkmalen – "
                "ohne quadratischen Fahrzeugpaarvergleich …"
            )
            result = cluster_autoexport_fins(
                fins, patterns, labels, self.linked,
            )
            self.calculated.emit(result)
        except (ValueError, RuntimeError) as exc:
            # Explicit, non-sensitive validation errors only.
            self.failed.emit(str(exc))
        except Exception:
            # Unexpected SQL/driver exceptions may include local FINs/paths.
            self.failed.emit(
                "Die lokale FIN-Analyse konnte nicht abgeschlossen werden. "
                "Bitte den Import und die Datenbank prüfen."
            )


def _table(
    headers: tuple[str, ...], widths: tuple[int, ...],
    height: int,
) -> tuple[QTableView, SimpleTableModel]:
    model = SimpleTableModel(headers, [])
    view = QTableView()
    view.setModel(model)
    view.setMinimumHeight(height)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.verticalHeader().setVisible(False)
    for index, width in enumerate(widths):
        view.setColumnWidth(index, width)
    view.horizontalHeader().setStretchLastSection(True)
    return view, model


class AutoExportFinWorkspace(QWidget):
    """Scalable VIN-wide diagnosis exploration; no NTF claim is fabricated."""

    fin_requested = Signal(str)

    def __init__(
        self,
        source: SourceKnowledgeStore | None,
        cases: list[NTFCase],
        population_metrics: dict[str, int] | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.population_metrics = population_metrics or {}
        case_ids: dict[str, list[str]] = defaultdict(list)
        for case in cases:
            case_ids[case.vin].append(case.case_id)
        self._linked = {
            fin: tuple(sorted(set(ids))) for fin, ids in case_ids.items()
        }
        # Only explicitly imported QEC coolant-pump replacement dates.
        # RepairDt in AutoExport is a generic workshop visit, NEVER a
        # verified pump swap. Multiple cases: earliest pump date per FIN.
        self._pump_swap_dates: dict[str, str] = {}
        for case in cases:
            if not case.qec_reference or case.component_profile_id != "coolant_pump":
                continue
            replacement = case.investigated_replacement()
            if replacement is None:
                continue
            value = replacement.occurred_at.date().isoformat()
            old = self._pump_swap_dates.get(case.vin)
            if old is None or value < old:
                self._pump_swap_dates[case.vin] = value
        self._analysis_scoped_to_pump = False
        self.result: FinPatternResult | None = None
        self._task: _FinPatternTask | None = None
        self._selected_fin: str | None = None
        self._shown_members: list[str] = []

        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        main.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        body = QVBoxLayout(content)
        body.setContentsMargins(22, 18, 22, 25)
        body.setSpacing(12)

        body.addWidget(QLabel(
            "Alle AutoExport-FINs · Diagnosemuster", objectName="PageTitle",
        ))
        lead = QLabel(
            "Hier werden Fahrzeuge mit vorhandenen DTC-Daten untersucht, "
            "auch wenn KEIN QEC-Schadteilfall vorliegt. "
            "Die gesamte verfügbare DTC-Historie wird betrachtet. "
            "Ohne einen belegten Pumpentausch ist dies ausdrücklich "
            "KEINE Vor-Tausch-Pumpenanalyse und KEIN NTF-Nachweis.",
            objectName="PageSubtitle",
        )
        lead.setWordWrap(True)
        body.addWidget(lead)

        metrics = self.population_metrics
        self.population_note = QLabel(
            f"Lokal importiert: {metrics.get('autoexport_unique_fins', 0):,} "
            f"unterschiedliche FINs · "
            f"{metrics.get('autoexport_dtc_fins', 0):,} FINs mit DTC-Zeilen. "
            f"{len(cases):,} QEC-Fälle bleiben separat ausgewertet.".replace(",", "."),
            objectName="PageSubtitle",
        )
        self.population_note.setWordWrap(True)
        body.addWidget(self.population_note)

        self.only_pump_swap = QCheckBox(
            "Nur FINs mit QEC-Rep.-Datum zur Pumpe (nur frühere DTCs)"
        )
        self.only_pump_swap.setToolTip(
            "Opt-in: nur QEC-Kühlmittelpumpenfälle mit gültigem Rep.-Datum. "
            "Diagnosen am selben Tag, danach oder ohne Datum gelten nicht als "
            "sicher vor dem Pumpentausch. AutoExport RepairDt genügt nicht."
        )
        self.only_pump_swap.toggled.connect(self._scope_changed)
        body.addWidget(self.only_pump_swap)
        self.scope_note = QLabel(
            f"Aktuell {len(self._pump_swap_dates):,} FINs mit dokumentiertem "
            "QEC-Pumpentauschdatum im lokalen QEC-Bestand. "
            "Das Datum ist der dokumentierte QEC-Reparaturanker, "
            "keine unabhängige Bestätigung eines erfolgreichen Tauschs. "
            "Ohne Haken bleiben alle importierten AutoExport-FINs "
            "für die allgemeine Diagnosemustersuche verfügbar.",
            objectName="PageSubtitle",
        )
        self.scope_note.setWordWrap(True)
        body.addWidget(self.scope_note)
        start_row = QHBoxLayout()
        self.start_button = QPushButton("AutoExport-FINs nach Diagnosemustern gruppieren")
        self.start_button.setObjectName("ClusterStartButton")
        self.start_button.setEnabled(source is not None)
        self.start_button.clicked.connect(self.run_analysis)
        start_row.addWidget(self.start_button)
        start_row.addStretch(1)
        body.addLayout(start_row)

        self.status = QLabel(
            "Bereit. Die Analyse liest ausschließlich lokale, "
            "bereits importierte AutoExport-Daten.",
            objectName="PageSubtitle",
        )
        self.status.setWordWrap(True)
        body.addWidget(self.status)

        kpis = QHBoxLayout()
        self.number_labels = {}
        for key, title in (
            ("total", "FINs im AutoExport"),
            ("dtc", "FINs mit DTC"),
            ("assigned", "FINs in Mustergruppen"),
            ("unassigned", "Mit DTC, ohne Gruppe"),
            ("missing", "FINs ohne DTC"),
            ("groups", "Mustergruppen"),
        ):
            card = QFrame()
            card.setObjectName("Card")
            stack = QVBoxLayout(card)
            stack.setContentsMargins(10, 10, 10, 10)
            label = QLabel(title, objectName="CardTitle")
            label.setWordWrap(True)
            stack.addWidget(label)
            value = QLabel("–", objectName="CardValue")
            stack.addWidget(value)
            self.number_labels[key] = value
            kpis.addWidget(card, 1)
        body.addLayout(kpis)

        body.addWidget(QLabel(
            "Größte Fahrzeug-Diagnosemuster", objectName="CardTitle",
        ))
        chart_info = QLabel(
            "Die Balken zeigen die 14 größten Gruppen. "
            "Alle Gruppen und FINs stehen in den Tabellen. "
            "Klick auf einen Balken wählt die Gruppe aus.",
            objectName="PageSubtitle",
        )
        chart_info.setWordWrap(True)
        body.addWidget(chart_info)
        self.chart = FinPatternBarChart()
        self.chart.group_picked.connect(self.select_group)
        body.addWidget(self.chart)

        self.group_table, self.group_model = _table(
            ("Gruppe", "FINs", "Davon FINs mit QEC", "Median Ähnlichkeit",
             "Häufigster ECU:DTC"),
            (75, 100, 165, 165, 380),
            245,
        )
        self.group_table.selectionModel().currentRowChanged.connect(
            self._group_changed
        )
        body.addWidget(QLabel("Mustergruppe auswählen", objectName="CardTitle"))
        body.addWidget(self.group_table)

        self.explanation = QLabel(
            "Nach der Berechnung eine Gruppe auswählen.",
            objectName="PageSubtitle",
        )
        self.explanation.setWordWrap(True)
        self.explanation.setTextFormat(Qt.TextFormat.PlainText)
        self.explanation.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body.addWidget(self.explanation)

        search = QHBoxLayout()
        search.addWidget(QLabel("FIN suchen:"))
        self.fin_search = QLineEdit()
        self.fin_search.setPlaceholderText(
            "FIN aus dem AutoExport – auch ohne QEC-Fall"
        )
        self.fin_search.returnPressed.connect(self.find_fin)
        search.addWidget(self.fin_search, 1)
        self.find_button = QPushButton("FIN finden")
        self.find_button.clicked.connect(self.find_fin)
        search.addWidget(self.find_button)
        body.addLayout(search)
        self.fin_status = QLabel(objectName="PageSubtitle")
        self.fin_status.setWordWrap(True)
        body.addWidget(self.fin_status)

        body.addWidget(QLabel(
            "FINs in der ausgewählten Mustergruppe", objectName="CardTitle",
        ))
        self.fin_table, self.fin_model = _table(
            ("FIN", "Eindeutige ECU:DTC", "Ähnlichkeit zum Muster",
             "Zugeordnete QEC-Fälle"),
            (195, 165, 190, 200),
            280,
        )
        self.fin_table.selectionModel().currentRowChanged.connect(
            self._fin_changed
        )
        self.fin_table.doubleClicked.connect(self.open_fin)
        body.addWidget(self.fin_table)

        self.open_button = QPushButton(
            "Ausgewählte FIN in AutoExport-Gesamthistorie öffnen"
        )
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_fin)
        body.addWidget(self.open_button)
        end = QLabel(
            "Wichtig: Eine Gruppe bedeutet nur ähnliche gespeicherte "
            "ECU:DTC-Muster. Die Zuordnung ist experimentell und nicht "
            "auf technische Pumpenursachen kalibriert. "
            "Die Prozentzahl ist ein Cosinus-Ähnlichkeitsindex, "
            "keine Fehlerwahrscheinlichkeit. "
            "Ein QEC-Bezug bedeutet lediglich dieselbe FIN.",
            objectName="PageSubtitle",
        )
        end.setWordWrap(True)
        body.addWidget(end)

    def _scope_changed(self, checked: bool) -> None:
        if self.result is not None:
            self.result = None
            self.group_model.set_rows([])
            self.fin_model.set_rows([])
            self.chart.set_groups(())
            for value in self.number_labels.values():
                value.setText("–")
            self.explanation.setText(
                "Datenumfang verändert. Analyse bitte erneut starten."
            )
        self.status.setText(
            "Modus Pumpentausch: nur QEC-FINs mit Rep.-Datum "
            "und Diagnosen an früheren Kalendertagen."
            if checked else
            "Modus Alle FINs: gesamte AutoExport-DTC-Historie, "
            "nicht auf Pumpentausch begrenzt."
        )

    def run_analysis(self) -> None:
        if self.source is None:
            self.status.setText("Keine lokale AutoExport-Datenbank verfügbar.")
            return
        if self._task is not None and self._task.isRunning():
            return
        self.start_button.setEnabled(False)
        self.group_model.set_rows([])
        self.fin_model.set_rows([])
        self.result = None
        self.chart.set_groups(())
        for value in self.number_labels.values():
            value.setText("–")
        self._analysis_scoped_to_pump = self.only_pump_swap.isChecked()
        self.only_pump_swap.setEnabled(False)
        task = _FinPatternTask(
            self.source, self._linked,
            self._pump_swap_dates if self._analysis_scoped_to_pump else None,
        )
        self._task = task
        _ACTIVE_FIN_TASKS.add(task)
        task.calculated.connect(self._receive)
        task.failed.connect(self._failed)
        task.phase.connect(self.status.setText)
        task.finished.connect(lambda: _ACTIVE_FIN_TASKS.discard(task))
        task.finished.connect(task.deleteLater)
        task.start()

    def _receive(self, result: FinPatternResult) -> None:
        self._task = None
        self.result = result
        self.start_button.setEnabled(True)
        self.only_pump_swap.setEnabled(True)
        stats = {
            "total": result.total_fins,
            "dtc": result.dtc_fins,
            "assigned": result.assigned_fins,
            "unassigned": len(result.unassigned_fins),
            "missing": len(result.no_dtc_fins),
            "groups": len(result.groups),
        }
        assert (
            stats["assigned"] + stats["unassigned"] + stats["missing"]
            == stats["total"]
        )
        for key, count in stats.items():
            self.number_labels[key].setText(f"{count:,}".replace(",", "."))
        scope = (
            "QEC-Pumpentausch-FINs mit DTCs vor dem Austausch"
            if self._analysis_scoped_to_pump else
            "Alle importierten AutoExport-FINs ohne Pumpentausch-Zeitfilter"
        )
        self.status.setText(
            f"FIN-Musteranalyse abgeschlossen ({scope}). "
            f"{result.initial_group_count} anfängliche Suchbereiche; "
            f"{len(result.groups)} tatsächlich ausgewiesene Mustergruppen. "
            "Nicht gruppierte Fahrzeuge bleiben separat sichtbar."
        )
        self.group_model.set_rows([
            (
                f"G{group.group_id}", group.fin_count, group.qec_fin_count,
                f"{group.median_similarity:.1%}",
                (
                    f"{group.common_faults[0][0]}:{group.common_faults[0][1]}"
                    if group.common_faults else "Kein wiederkehrender DTC"
                ),
            )
            for group in result.groups
        ])
        self.chart.set_groups(result.groups)
        self.explanation.setText(
            "Gruppe wählen, um häufig gemeinsame Fehlercodes "
            "und alle zugehörigen FINs zu sehen."
        )
        if result.groups:
            self.group_table.selectRow(0)
        else:
            self.explanation.setText(
                "Mit der experimentellen Mindestähnlichkeit wurden "
                "keine ausreichend großen Fahrzeugmuster erkannt. "
                "Das ist keine Aussage über Pumpendefekte."
            )

    def _failed(self, message: str) -> None:
        self._task = None
        self.start_button.setEnabled(self.source is not None)
        self.only_pump_swap.setEnabled(True)
        self.status.setText("FIN-Clusteranalyse nicht möglich: " + message)

    def select_group(self, group_id: int) -> None:
        if self.result is None:
            return
        for i, group in enumerate(self.result.groups):
            if group.group_id == group_id:
                self.group_table.selectRow(i)
                return

    def _group_changed(self, index, _previous) -> None:
        if self.result is None or not index.isValid():
            return
        group = self.result.groups[index.row()]
        self.chart.set_selected(group.group_id)
        self._shown_members = [fin for fin, _ in group.members]
        self.fin_model.set_rows([
            (
                fin,
                self.result.code_counts.get(fin, 0),
                f"{similarity:.1%}",
                len(self.result.qec_links.get(fin, ())),
            )
            for fin, similarity in group.members
        ])
        self._selected_fin = None
        self.open_button.setEnabled(False)
        lines = [
            f"Warum sind {group.fin_count} FINs in Mustergruppe "
            f"G{group.group_id}?",
            "Die App erkennt ähnliche Kombinationen bereits "
            "gespeicherter Steuergerät-Fehlercodes (ECU:DTC). "
            "Folgende Codes wurden in mehreren Fahrzeugen dieser "
            "Gruppe beobachtet (pro FIN höchstens einmal gezählt):",
        ]
        if not group.common_faults:
            lines.append(
                "Kein einzelner ECU:DTC tritt wiederholt auf. "
                "Diese Gruppe braucht besondere fachliche Prüfung."
            )
        else:
            for ecu, dtc, count, label in group.common_faults:
                desc = f" – {label}" if label else ""
                lines.append(
                    f"• {ecu}:{dtc}{desc}: {count} von {group.fin_count} FINs"
                )
        scope_explanation = (
            "Es werden ausschließlich DTCs von Tagen VOR dem belegten "
            "QEC-Pumpentausch berücksichtigt. Ein gemeinsamer Code "
            "beweist trotzdem weder Defekt noch Tauschwirksamkeit."
            if self._analysis_scoped_to_pump else
            "Es wurde hier nicht geprüft, ob die DTCs vor einem "
            "Pumpentausch auftraten. Bekannte QEC-FINs werden nur "
            "als Verknüpfung gekennzeichnet."
        )
        lines.append(
            "Diese Häufigkeiten und der Ähnlichkeitsindex sind "
            "kein Beleg für einen gemeinsamen Kühlmittelpumpenfehler. "
            + scope_explanation
        )
        self.explanation.setText("\n\n".join(lines))

    def _fin_changed(self, index, _previous) -> None:
        if not index.isValid() or index.row() >= len(self._shown_members):
            return
        self._selected_fin = self._shown_members[index.row()]
        self.open_button.setEnabled(True)

    def find_fin(self) -> bool:
        if self.result is None:
            self.fin_status.setText(
                "Bitte zuerst die AutoExport-FIN-Analyse starten."
            )
            return False
        fin = self.fin_search.text().strip().upper()
        if not fin:
            self.fin_status.setText("Bitte eine FIN eingeben.")
            return False
        group = self.result.group_for(fin)
        if group is not None:
            self.select_group(group.group_id)
            for i, found in enumerate(self._shown_members):
                if found == fin:
                    self.fin_table.selectRow(i)
                    self.fin_table.scrollTo(self.fin_model.index(i, 0))
                    break
            self.fin_status.setText(
                f"FIN in Mustergruppe G{group.group_id} gefunden. "
                "Ein Pumpendefekt ist damit nicht bewiesen."
            )
            return True
        if fin in self.result.no_dtc_fins:
            self.fin_status.setText(
                "FIN im AutoExport vorhanden, aber ohne importierte "
                "DTC-Beobachtung. Keine Diagnosemuster-Zuordnung möglich."
            )
        elif fin in self.result.unassigned_fins:
            self.fin_status.setText(
                "FIN hat DTC-Daten, erfüllt aber nicht die "
                "experimentellen Mustergruppen-Kriterien."
            )
        else:
            self.fin_status.setText(
                "Diese FIN ist in den aktuell importierten "
                "AutoExport-Daten nicht vorhanden."
            )
            return False
        self._selected_fin = fin
        self.open_button.setEnabled(True)
        return True

    def open_fin(self, *_args) -> None:
        if self._selected_fin:
            self.fin_requested.emit(self._selected_fin)
