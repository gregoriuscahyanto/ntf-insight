"""German-language local source knowledge explorer.

CDD services and production Part History are shared reference knowledge:
they are never treated as events on a specific vehicle without evidence.
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ntf_insight.app.models.simple_table_model import SimpleTableModel
from ntf_insight.storage.source_knowledge_store import SourceKnowledgeStore


class SourceKnowledgePage(QWidget):
    CATEGORY_CHOICES = (
        ("Alle strukturierten Quellen", None),
        ("SMR-D · DTC-Referenzen (XML)", "smrd_xml_dtc"),
        ("SMR-D · ECU und Varianten", "smrd_xml_ecu"),
        ("SMR-D · Services", "smrd_xml_service"),
        ("SMR-D · Parameter", "smrd_xml_parameter"),
        ("SMR-D · SDGs", "smrd_xml_sdg"),
        ("CDD · Diagnoseservices", "cdd_service"),
        ("Part History · Produktionsänderungen", "part_change"),
        ("QEC · alle Tabellenzeilen", "qec_row"),
        ("AutoExport · DTC-Export", "autoexport_dtc"),
        ("AutoExport · Werkstatt / Claim", "autoexport_repair"),
        ("AutoExport · TIPS-Fall", "autoexport_tips"),
        ("AutoExport · Aggregat", "autoexport_aggregate"),
        ("AutoExport · andere", "autoexport_other"),
        ("Lieferanten-Analysebericht · Originaltext", "supplier_analysis_page"),
    )

    def __init__(self, store: SourceKnowledgeStore) -> None:
        super().__init__()
        self.store = store
        self.offset = 0
        self.rows: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 20)
        layout.setSpacing(12)
        layout.addWidget(QLabel("Quellenwissen", objectName="PageTitle"))

        description = QLabel(
            "Strukturierte Inhalte aus Candela CDD, Part History, QEC und "
            "AutoExport. Die Daten bleiben lokal. CDD-Services und "
            "Produktionsänderungen gelten nicht automatisch für eine FIN; "
            "SMR-D-Trigger und bestätigte Fehlerursachen werden daraus nicht abgeleitet.",
            objectName="PageSubtitle",
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        controls = QHBoxLayout()
        self.category = QComboBox()
        for label, value in self.CATEGORY_CHOICES:
            self.category.addItem(label, value)
        self.category.setMinimumWidth(270)
        controls.addWidget(self.category)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Quelle, Referenz, FIN, DTC oder Beschreibung suchen …")
        self.search.setClearButtonEnabled(True)
        controls.addWidget(self.search, 1)
        layout.addLayout(controls)

        self.overview = QLabel(objectName="PageSubtitle")
        self.overview.setWordWrap(True)
        layout.addWidget(self.overview)

        self.table_model = SimpleTableModel(
            ("Typ", "Referenz / Qualifier", "Kurzbeschreibung", "FIN", "Fundstelle", "SHA-256")
        )
        self.table = QTableView()
        self.table.setModel(self.table_model)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((150, 190, 320, 165, 200, 130)):
            self.table.setColumnWidth(column, width)
        layout.addWidget(self.table, 3)

        paging = QHBoxLayout()
        self.previous = QPushButton("Vorherige 200")
        self.next = QPushButton("Nächste 200")
        self.page_status = QLabel(objectName="PageSubtitle")
        paging.addWidget(self.previous)
        paging.addWidget(self.next)
        paging.addWidget(self.page_status)
        paging.addStretch()
        layout.addLayout(paging)

        layout.addWidget(QLabel("Vollständiger Datensatz und Quellenbezug", objectName="CardTitle"))
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText(
            "Eine Zeile auswählen: alle importierten Quellfelder und die Herkunft werden angezeigt."
        )
        layout.addWidget(self.detail, 2)

        self.category.currentIndexChanged.connect(self._reset)
        self.search.textChanged.connect(self._reset)
        self.previous.clicked.connect(self._previous_page)
        self.next.clicked.connect(self._next_page)
        self.table.clicked.connect(self._show_detail)
        self._load()

    def _reset(self) -> None:
        self.offset = 0
        self._load()

    def _previous_page(self) -> None:
        self.offset = max(0, self.offset - 200)
        self._load()

    def _next_page(self) -> None:
        if len(self.rows) >= 200:
            self.offset += 200
            self._load()

    def _load(self) -> None:
        kind = self.category.currentData()
        term = self.search.text().strip() or None
        self.rows = self.store.list_rows(
            category=kind,
            search=term,
            limit=200,
            offset=self.offset,
        )
        self.table_model.set_rows([
            (
                record["category"],
                record["reference"] or "—",
                record["label"] or "—",
                record["fin"] or "—",
                record["source_location"],
                record["source_sha256"][:12] + "…",
            )
            for record in self.rows
        ])
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(len(self.rows) == 200)
        if self.rows:
            self.page_status.setText(
                f"Zeilen {self.offset + 1}–{self.offset + len(self.rows)}"
                + (" · weitere ggf. vorhanden" if len(self.rows) == 200 else "")
            )
        else:
            self.page_status.setText(
                "Noch keine entsprechenden Referenzdaten vorhanden."
            )
        totals = self.store.summary()
        self.overview.setText(
            f"CDD: {totals.get('candela_services', 0)} Services · "
            f"Part History: {totals.get('part_history', 0)} Änderungen · "
            f"QEC: {totals.get('qec_details', 0)} Tabellenzeilen · "
            f"AutoExport (DTC/Werkstatt/TIPS): {totals.get('autoexport_rows', 0)} Datenzeilen · "
            f"Aggregate: {totals.get('autoexport_summary', 0)} · "
            f"Analysebericht-Seiten: {totals.get('supplier_analysis_document', 0)}"
        )
        self.detail.clear()

    def _show_detail(self, index) -> None:
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return
        record = self.rows[index.row()]
        content = {
            "Quellentyp": record["category"],
            "Quelle (SHA-256)": record["source_sha256"],
            "Fundstelle": record["source_location"],
            "FIN (nur sofern in der Quelle vorhanden)": record["fin"],
            "Referenz": record["reference"],
            "Alle Quellfelder": record["data"],
        }
        self.detail.setPlainText(
            json.dumps(content, ensure_ascii=False, indent=2, default=str)
        )
