"""Global dark slate theme and visual styling for Speakr Companion.

Palette:
- Background Dark: #0b0f19
- Surface / Cards: #1e293b
- Inputs / Panes: #0f172a
- Borders: #334155, #475569
- Primary Accent (Sky Blue): #38bdf8 / #0284c7
- Emerald Green (Record / Success / Active): #059669 / #10b981
- Amber (Pause / Warning): #d97706 / #f59e0b
- Crimson (Stop / Delete / Error): #dc2626 / #ef4444
- Purple / Lavender (Participant / Accents): #a78bfa / #8b5cf6
- Text Primary: #f8fafc
- Text Secondary: #cbd5e1
- Text Muted: #94a3b8
"""

GLOBAL_APP_STYLESHEET = """
/* --- Base Window & Central Widget --- */
QMainWindow, QWidget#centralWidget {
    background-color: #0b0f19;
    color: #f8fafc;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}

QWidget {
    color: #f8fafc;
}

/* --- Dialogs --- */
QDialog {
    background-color: #0b0f19;
    color: #f8fafc;
}

QMessageBox {
    background-color: #0f172a;
    color: #f8fafc;
}

QMessageBox QLabel {
    color: #f8fafc;
    font-size: 12px;
}

/* --- Frames & Cards --- */
QFrame#card, QFrame#staticControlBar {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
}

/* --- Group Boxes --- */
QGroupBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    margin-top: 18px;
    padding-top: 14px;
    padding-bottom: 8px;
    padding-left: 8px;
    padding-right: 8px;
    font-weight: bold;
    font-size: 12px;
    color: #38bdf8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 2px 8px;
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 4px;
    color: #38bdf8;
}

/* --- Tabs --- */
QTabWidget::pane {
    border: 1px solid #334155;
    background-color: #0b0f19;
    border-radius: 6px;
    top: -1px;
}

QTabBar::tab {
    background-color: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 2px;
    font-size: 12px;
    font-weight: 600;
}

QTabBar::tab:hover {
    background-color: #334155;
    color: #f8fafc;
}

QTabBar::tab:selected {
    background-color: #0f172a;
    color: #38bdf8;
    border-color: #334155;
    border-bottom: 2px solid #38bdf8;
}

/* --- Buttons --- */
QPushButton {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #334155;
    border-color: #64748b;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton:disabled {
    background-color: #1e293b;
    color: #64748b;
    border-color: #334155;
}

/* --- Input Fields --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {
    border: 1px solid #38bdf8;
}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {
    background-color: #1e293b;
    color: #64748b;
    border-color: #334155;
}

/* --- Combo Boxes --- */
QComboBox {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
    min-height: 18px;
}

QComboBox:hover {
    border-color: #475569;
}

QComboBox:focus {
    border: 1px solid #38bdf8;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 22px;
    border-left: 1px solid #334155;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
    background-color: #1e293b;
}

QComboBox QAbstractItemView {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    padding: 4px;
    outline: none;
}

/* --- Tables & Lists --- */
QTableWidget, QListWidget, QListView, QTableView {
    background-color: #0f172a;
    color: #f8fafc;
    border: 1px solid #334155;
    border-radius: 4px;
    gridline-color: #1e293b;
    outline: none;
}

QTableWidget::item, QListWidget::item {
    padding: 4px 6px;
    border-bottom: 1px solid #1e293b;
}

QTableWidget::item:selected, QListWidget::item:selected {
    background-color: #1e293b;
    color: #38bdf8;
}

QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #334155;
    border-bottom: 1px solid #334155;
    font-weight: bold;
    font-size: 11px;
}

/* --- ScrollBars --- */
QScrollBar:vertical {
    background: #0f172a;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #334155;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background: #0f172a;
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background: #334155;
    min-width: 20px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #475569;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* --- CheckBoxes & RadioButtons --- */
QCheckBox, QRadioButton {
    color: #f8fafc;
    font-size: 12px;
    spacing: 6px;
}

QCheckBox::indicator, QRadioButton::indicator {
    width: 16px;
    height: 16px;
    background-color: #0f172a;
    border: 1px solid #475569;
    border-radius: 3px;
}

QRadioButton::indicator {
    border-radius: 8px;
}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {
    border-color: #38bdf8;
}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
}

/* --- Splitter Handles --- */
QSplitter::handle {
    background-color: #334155;
    border-radius: 2px;
}

QSplitter::handle:hover {
    background-color: #38bdf8;
}

/* --- Status Bar --- */
QStatusBar {
    background-color: #0f172a;
    color: #94a3b8;
    border-top: 1px solid #1e293b;
    font-size: 11px;
}
"""
