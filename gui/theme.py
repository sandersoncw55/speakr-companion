"""Theme definitions, color tokens, and QSS stylesheets for Speakr Companion.

Supports:
- Cyber-Studio Dark Mode (Obsidian charcoal, electric cyan, lavender purple, coral red)
- Studio Clean Light Mode (Off-white, pure white cards, cerulean cyan, royal violet)
"""

from typing import Dict, Any

DARK_PALETTE = {
    "name": "dark",
    "bg_window": "#0e1015",
    "bg_surface": "#181b22",
    "bg_input": "#12151c",
    "bg_hover": "#252b36",
    "border_subtle": "#2a2e39",
    "border_medium": "#333a48",
    "border_focus": "#38bdf8",
    "text_primary": "#f1f5f9",
    "text_secondary": "#cbd5e1",
    "text_muted": "#94a3b8",
    "accent_cyan": "#22d3ee",
    "accent_cyan_hover": "#38bdf8",
    "accent_purple": "#c084fc",
    "accent_purple_hover": "#d8b4fe",
    "accent_coral": "#fb7185",
    "accent_coral_bg": "#3f141e",
    "accent_indigo": "#818cf8",
    "accent_indigo_bg": "#1e1b4b",
    "accent_emerald": "#10b981",
    "accent_emerald_bg": "#064e3b",
    "meter_mic_start": "#06b6d4",
    "meter_mic_end": "#22d3ee",
    "meter_mic_peak": "#67e8f9",
    "meter_sys_start": "#a855f7",
    "meter_sys_end": "#c084fc",
    "meter_sys_peak": "#e9d5ff",
    "meter_track": "#12151c",
    "meter_track_border": "#2a2e39",
}

LIGHT_PALETTE = {
    "name": "light",
    "bg_window": "#f8fafc",
    "bg_surface": "#ffffff",
    "bg_input": "#ffffff",
    "bg_hover": "#f1f5f9",
    "border_subtle": "#e2e8f0",
    "border_medium": "#cbd5e1",
    "border_focus": "#0284c7",
    "text_primary": "#0f172a",
    "text_secondary": "#334155",
    "text_muted": "#64748b",
    "accent_cyan": "#0284c7",
    "accent_cyan_hover": "#0369a1",
    "accent_purple": "#7c3aed",
    "accent_purple_hover": "#6d28d9",
    "accent_coral": "#e11d48",
    "accent_coral_bg": "#ffe4e6",
    "accent_indigo": "#4f46e5",
    "accent_indigo_bg": "#e0e7ff",
    "accent_emerald": "#059669",
    "accent_emerald_bg": "#d1fae5",
    "meter_mic_start": "#0284c7",
    "meter_mic_end": "#38bdf8",
    "meter_mic_peak": "#0369a1",
    "meter_sys_start": "#7c3aed",
    "meter_sys_end": "#a855f7",
    "meter_sys_peak": "#581c87",
    "meter_track": "#f1f5f9",
    "meter_track_border": "#cbd5e1",
}


def get_theme_palette(theme: str = "dark") -> Dict[str, Any]:
    """Retrieve color tokens dictionary for given theme name."""
    if str(theme).lower() == "light":
        return LIGHT_PALETTE
    return DARK_PALETTE


def get_theme_stylesheet(theme: str = "dark") -> str:
    """Generate complete QSS stylesheet string for the requested theme."""
    p = get_theme_palette(theme)
    is_light = (p["name"] == "light")
    
    return f"""
/* ==========================================================================
   Speakr Windows Companion - {p['name'].upper()} THEME
   ========================================================================== */

/* --- Base Window & Central Widget --- */
QMainWindow, QWidget#centralWidget {{
    background-color: {p['bg_window']};
    color: {p['text_primary']};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 12px;
}}

QWidget {{
    color: {p['text_primary']};
}}

/* --- Dialogs --- */
QDialog {{
    background-color: {p['bg_window']};
    color: {p['text_primary']};
}}

QMessageBox {{
    background-color: {p['bg_surface']};
    color: {p['text_primary']};
}}

QMessageBox QLabel {{
    color: {p['text_primary']};
    font-size: 12px;
}}

/* --- Frames & Static Header Cards --- */
QFrame#card, QFrame#staticControlBar {{
    background-color: {p['bg_surface']};
    border: 1px solid {p['border_subtle']};
    border-radius: 6px;
}}

/* --- Group Boxes --- */
QGroupBox {{
    background-color: {p['bg_surface']};
    border: 1px solid {p['border_subtle']};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    padding-bottom: 8px;
    padding-left: 8px;
    padding-right: 8px;
    font-weight: bold;
    font-size: 12px;
    color: {p['accent_cyan']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 2px 8px;
    background-color: {p['bg_input']};
    border: 1px solid {p['border_subtle']};
    border-radius: 4px;
    color: {p['accent_cyan']};
}}

/* --- Tabs --- */
QTabWidget::pane {{
    border: 1px solid {p['border_subtle']};
    background-color: {p['bg_window']};
    border-radius: 6px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: {p['bg_surface']};
    color: {p['text_muted']};
    border: 1px solid {p['border_subtle']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 2px;
    font-size: 12px;
    font-weight: 600;
}}

QTabBar::tab:hover {{
    background-color: {p['bg_hover']};
    color: {p['text_primary']};
}}

QTabBar::tab:selected {{
    background-color: {p['bg_input'] if not is_light else '#ffffff'};
    color: {p['accent_cyan']};
    border-color: {p['border_medium']};
    border-bottom: 2px solid {p['accent_indigo'] if is_light else p['accent_cyan']};
}}

/* --- Buttons --- */
QPushButton {{
    background-color: {p['bg_surface'] if is_light else '#1f242e'};
    color: {p['text_primary']};
    border: 1px solid {p['border_medium']};
    border-radius: 4px;
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {p['bg_hover'] if is_light else '#2c3342'};
    border-color: {p['border_focus']};
}}

QPushButton:pressed {{
    background-color: {'#e2e8f0' if is_light else '#141820'};
}}

QPushButton:disabled {{
    background-color: {p['bg_window']};
    color: {p['text_muted']};
    border-color: {p['border_subtle']};
}}

/* --- Input Fields --- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox {{
    background-color: {p['bg_input']};
    color: {p['text_primary']};
    border: 1px solid {p['border_medium'] if is_light else p['border_subtle']};
    border-radius: 4px;
    padding: 5px 8px;
    font-size: 12px;
    selection-background-color: {p['accent_cyan']};
    selection-color: {'#ffffff' if not is_light else '#ffffff'};
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
    border: 1px solid {p['border_focus']};
}}

QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    background-color: {p['bg_window']};
    color: {p['text_muted']};
    border-color: {p['border_subtle']};
}}

/* --- Combo Boxes --- */
QComboBox {{
    background-color: {p['bg_input']};
    color: {p['text_primary']};
    border: 1px solid {p['border_medium'] if is_light else p['border_subtle']};
    border-radius: 4px;
    padding: 5px 28px 5px 8px;
    font-size: 12px;
    min-height: 20px;
}}

QComboBox:hover {{
    border-color: {p['border_focus']};
}}

QComboBox:focus {{
    border: 1px solid {p['border_focus']};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {p['border_subtle']};
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
    background-color: {p['bg_surface']};
}}

QComboBox QAbstractItemView {{
    background-color: {p['bg_input']};
    color: {p['text_primary']};
    border: 1px solid {p['border_medium']};
    selection-background-color: {'#e0f2fe' if is_light else '#1e293b'};
    selection-color: {p['accent_cyan']};
    padding: 4px;
    outline: none;
}}

/* --- Tables & Lists --- */
QTableWidget, QListWidget, QListView, QTableView {{
    background-color: {p['bg_input']};
    color: {p['text_primary']};
    border: 1px solid {p['border_subtle']};
    border-radius: 4px;
    gridline-color: {p['border_subtle']};
    outline: none;
}}

QTableWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid {p['border_subtle']};
}}

QTableWidget::item:selected {{
    background-color: {'#e0f2fe' if is_light else '#1e293b'};
    color: {p['accent_cyan']};
}}

QHeaderView::section {{
    background-color: {p['bg_surface']};
    color: {p['text_muted']};
    padding: 6px 8px;
    border: none;
    border-right: 1px solid {p['border_subtle']};
    border-bottom: 1px solid {p['border_subtle']};
    font-weight: bold;
    font-size: 11px;
}}

/* --- ScrollBars --- */
QScrollBar:vertical, QAbstractScrollArea QScrollBar:vertical {{
    background: {p['bg_window']};
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical, QAbstractScrollArea QScrollBar::handle:vertical {{
    background: {p['border_medium']};
    min-height: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover, QAbstractScrollArea QScrollBar::handle:vertical:hover {{
    background: {p['text_muted']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal, QAbstractScrollArea QScrollBar:horizontal {{
    background: {p['bg_window']};
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal, QAbstractScrollArea QScrollBar::handle:horizontal {{
    background: {p['border_medium']};
    min-width: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover, QAbstractScrollArea QScrollBar::handle:horizontal:hover {{
    background: {p['text_muted']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* --- CheckBoxes & RadioButtons --- */
QCheckBox, QRadioButton {{
    color: {p['text_primary']};
    font-size: 12px;
    spacing: 8px;
    padding: 2px 4px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    background-color: {p['bg_input']};
    border: 1px solid {p['border_medium']};
    border-radius: 3px;
    margin-left: 2px;
}}

QRadioButton::indicator {{
    border-radius: 8px;
}}

QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p['border_focus']};
}}

QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: {p['accent_cyan']};
    border-color: {p['accent_cyan']};
}}

/* --- Splitter Handles --- */
QSplitter::handle {{
    background-color: {p['border_subtle']};
    border-radius: 2px;
}}

QSplitter::handle:hover {{
    background-color: {p['border_focus']};
}}

/* --- Status Bar --- */
QStatusBar {{
    background-color: {p['bg_input']};
    color: {p['text_muted']};
    border-top: 1px solid {p['border_subtle']};
    font-size: 11px;
}}
"""

# Backwards compatibility export
GLOBAL_APP_STYLESHEET = get_theme_stylesheet("dark")
