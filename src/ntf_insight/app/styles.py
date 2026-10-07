"""Central Qt stylesheet for the desktop application."""

APP_STYLESHEET = r"""
QMainWindow, QWidget#AppRoot {
    background: #f5f7fb;
    color: #172033;
    font-family: "Segoe UI", "Inter", "Arial";
    font-size: 14px;
}

QFrame#Sidebar {
    background: #111827;
    border: none;
}

QLabel#BrandTitle {
    color: #ffffff;
    font-size: 20px;
    font-weight: 700;
}

QLabel#BrandSubtitle {
    color: #9ca3af;
    font-size: 12px;
}

QPushButton#NavButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #cbd5e1;
    padding: 11px 14px;
    text-align: left;
}

QPushButton#NavButton:hover {
    background: #1f2937;
    color: #ffffff;
}

QPushButton#NavButton:checked {
    background: #263449;
    color: #ffffff;
    font-weight: 600;
}

QLabel#PageTitle {
    color: #111827;
    font-size: 28px;
    font-weight: 700;
}

QLabel#PageSubtitle {
    color: #6b7280;
    font-size: 13px;
}

QFrame#Card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
}

QLabel#CardTitle {
    color: #6b7280;
    font-size: 12px;
    font-weight: 600;
}

QLabel#CardValue {
    color: #111827;
    font-size: 26px;
    font-weight: 700;
}

QLabel#CardSubtitle {
    color: #9ca3af;
    font-size: 11px;
}

QLineEdit {
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 8px;
    padding: 9px 11px;
}

QLineEdit:focus {
    border: 1px solid #64748b;
}

QTableView, QTableWidget {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e5e7eb;
    border-radius: 10px;
    gridline-color: #eef2f7;
    selection-background-color: #e2e8f0;
    selection-color: #111827;
}

QHeaderView::section {
    background: #f8fafc;
    color: #475569;
    border: none;
    border-bottom: 1px solid #e5e7eb;
    padding: 9px;
    font-weight: 600;
}
"""
