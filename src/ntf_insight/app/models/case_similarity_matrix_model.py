"""Qt heatmap for explainable diagnostic similarity between FIN/case pairs."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from ntf_insight.analysis.case_clustering import CaseMatch


class CaseSimilarityMatrixModel(QAbstractTableModel):
    """Percentages and neutral, contrast-safe shading; no inferred root cause."""

    def __init__(self, case_ids: list[str], matches: tuple[CaseMatch, ...]) -> None:
        super().__init__()
        self.case_ids = list(case_ids)
        self.pairs = {
            frozenset((item.left_case_id, item.right_case_id)): item
            for item in matches
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.case_ids)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.case_ids)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        left = self.case_ids[index.row()]
        right = self.case_ids[index.column()]
        diagonal = left == right
        pair = self.pairs.get(frozenset((left, right))) if not diagonal else None

        app = QApplication.instance()
        dark = app is not None and app.property("ntfTheme") == "dark"

        if role == Qt.ItemDataRole.DisplayRole:
            if diagonal:
                return "—"
            return f"{pair.score:.0%}" if pair is not None and pair.score is not None else "k. A."

        if role == Qt.ItemDataRole.ToolTipRole:
            if diagonal:
                return "Dies ist derselbe Fall."
            if pair is None or pair.score is None:
                return pair.reason if pair is not None else "Keine Vergleichsdaten vorhanden."
            return (
                f"{left} ↔ {right}\n"
                f"Diagnostische Ähnlichkeit: {pair.score:.1%}\n"
                f"Abdeckung der Merkmale: {pair.coverage:.0%}\n"
                f"{pair.reason}\n"
                "Reparaturerfolg ist kein Ähnlichkeitsmerkmal."
            )

        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter

        if role == Qt.ItemDataRole.BackgroundRole:
            if diagonal:
                return QColor("#e2e5e9" if not dark else "#343a40")
            if pair is None or pair.score is None:
                return QColor("#f5f6f8" if not dark else "#242930")
            shade = int(246 - pair.score * 188) if not dark else int(32 + pair.score * 58)
            return QColor(shade, shade, shade) if not dark else QColor(shade, shade, shade)

        if role == Qt.ItemDataRole.ForegroundRole:
            if diagonal:
                return QColor("#4b5563" if not dark else "#e5e7eb")
            if pair is None or pair.score is None:
                return QColor("#6b7280" if not dark else "#cbd5e1")
            return QColor("#ffffff" if (not dark and pair.score >= 0.70) else
                          "#ffffff" if (dark and pair.score >= 0.65) else
                          "#111827" if not dark else "#f9fafb")

        return None

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if 0 <= section < len(self.case_ids):
            return self.case_ids[section]
        return None
