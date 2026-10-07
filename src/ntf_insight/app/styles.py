"""Central light/dark Qt stylesheets with explicit readable contrast."""

from __future__ import annotations


def stylesheet_for(
    theme: str,
    body_font: str = "Segoe UI",
    heading_font: str | None = None,
) -> str:
    """Return a fully explicit high-contrast stylesheet for light or dark mode."""
    heading_font = heading_font or body_font
    heading_key = heading_font.casefold()
    corporate_a_heading = "corpo a" in heading_key or "corporate a" in heading_key
    heading_weight = 400 if corporate_a_heading else 700
    dark = theme.casefold() == "dark"

    if dark:
        p = {
            "bg": "#111827",
            "surface": "#1f2937",
            "surface_alt": "#182233",
            "text": "#f9fafb",
            "muted": "#cbd5e1",
            "subtle": "#94a3b8",
            "border": "#374151",
            "input_bg": "#0f172a",
            "selection": "#3a3f45",
            "selection_text": "#ffffff",
            "hover": "#2b2f33",
            "sidebar": "#090f1a",
            "sidebar_hover": "#1f2327",
            "sidebar_checked": "#34393f",
        }
    else:
        p = {
            "bg": "#f5f7fb",
            "surface": "#ffffff",
            "surface_alt": "#f8fafc",
            "text": "#111827",
            "muted": "#4b5563",
            "subtle": "#6b7280",
            "border": "#d1d5db",
            "input_bg": "#ffffff",
            "selection": "#e5e7eb",
            "selection_text": "#111827",
            "hover": "#eef0f2",
            "sidebar": "#111827",
            "sidebar_hover": "#202428",
            "sidebar_checked": "#33383d",
        }

    return f"""
QMainWindow, QWidget {{
    background-color: {p["bg"]};
    color: {p["text"]};
    font-family: "{body_font}";
    font-size: 14px;
}}

QWidget#AppRoot {{
    background-color: {p["bg"]};
    color: {p["text"]};
}}

QLabel {{
    color: {p["text"]};
    background: transparent;
}}

QFrame#Sidebar {{
    background-color: {p["sidebar"]};
    border: none;
    border-right: 1px solid #4b5055;
}}

QLabel#BrandTitle {{
    color: #ffffff;
    font-family: "{heading_font}";
    font-size: 20px;
    font-weight: {heading_weight};
}}

QLabel#BrandSubtitle {{
    color: #cbd5e1;
    font-size: 12px;
}}

QPushButton#NavButton {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #e5e7eb;
    padding: 11px 14px;
    text-align: left;
}}

QPushButton#NavButton:hover {{
    background-color: {p["sidebar_hover"]};
    color: #ffffff;
}}

QPushButton#NavButton:checked {{
    background-color: {p["sidebar_checked"]};
    color: #ffffff;
    font-weight: 600;
}}

QLabel#PageTitle {{
    color: {p["text"]};
    font-family: "{heading_font}";
    font-size: 28px;
    font-weight: {heading_weight};
}}

QLabel#PageSubtitle {{
    color: {p["muted"]};
    font-size: 13px;
}}

QFrame#Card {{
    background-color: {p["surface"]};
    border: 1px solid {p["border"]};
    border-radius: 12px;
}}

QLabel#CardTitle {{
    color: {p["muted"]};
    font-size: 12px;
    font-weight: 600;
}}

QLabel#CardValue {{
    color: {p["text"]};
    font-size: 26px;
    font-weight: 700;
}}

QLabel#CardSubtitle {{
    color: {p["subtle"]};
    font-size: 11px;
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
    background-color: {p["input_bg"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {p["selection"]};
    selection-color: {p["selection_text"]};
}}

QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid #64748b;
}}

QComboBox QAbstractItemView {{
    background-color: {p["surface"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    selection-background-color: {p["selection"]};
    selection-color: {p["selection_text"]};
}}

QPushButton {{
    background-color: {p["surface"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 8px;
    padding: 8px 12px;
}}

QPushButton:hover {{
    background-color: {p["hover"]};
}}

QPushButton:disabled {{
    color: {p["subtle"]};
}}

QTableView, QTableWidget {{
    background-color: {p["surface"]};
    alternate-background-color: {p["surface_alt"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
    gridline-color: {p["border"]};
    selection-background-color: {p["selection"]};
    selection-color: {p["selection_text"]};
}}

QTableView::item, QTableWidget::item {{
    color: {p["text"]};
    padding: 4px;
}}

QTableView::item:selected, QTableWidget::item:selected {{
    background-color: {p["selection"]};
    color: {p["selection_text"]};
}}

QHeaderView::section {{
    background-color: {p["surface_alt"]};
    color: {p["text"]};
    border: none;
    border-bottom: 1px solid {p["border"]};
    padding: 9px;
    font-weight: 600;
}}

QMenu {{
    background-color: {p["surface"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
}}

QMenu::item:selected {{
    background-color: {p["selection"]};
    color: {p["selection_text"]};
}}

QToolTip {{
    background-color: {p["surface"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
}}


QFrame#DropZone {{
    background-color: {p["surface"]};
    border: 2px dashed {p["border"]};
    border-radius: 12px;
}}

QFrame#DropZone[dragActive="true"] {{
    background-color: {p["surface_alt"]};
    border: 2px solid #73777c;
}}

QLabel#DropZoneTitle {{
    color: {p["text"]};
    font-size: 16px;
    font-weight: 600;
}}

QLabel#DropZoneHint {{
    color: {p["muted"]};
    font-size: 12px;
}}

QLabel#EmptyState {{
    background-color: {p["surface"]};
    color: {p["muted"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
    padding: 24px;
}}

QTabWidget::pane {{
    background-color: {p["surface"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
}}

QTabBar::tab {{
    background-color: {p["surface_alt"]};
    color: {p["muted"]};
    border: 1px solid {p["border"]};
    border-bottom: none;
    padding: 9px 16px;
}}

QTabBar::tab:selected {{
    background-color: {p["surface"]};
    color: {p["text"]};
}}

QGraphicsView#ClusterGraph {{
    background-color: {p["surface"]};
    color: {p["text"]};
    border: 1px solid {p["border"]};
    border-radius: 10px;
}}


QScrollBar:vertical, QScrollBar:horizontal {{
    background: {p["bg"]};
    border: none;
}}

QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p["border"]};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
"""


LIGHT_STYLESHEET = stylesheet_for("light")
DARK_STYLESHEET = stylesheet_for("dark")
