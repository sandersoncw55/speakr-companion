import os
from typing import Optional, List, Dict, Any
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QIcon, QPainter, QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QButtonGroup
)
from gui.theme import get_theme_palette
from core.config import get_resource_path


class SidebarNavButton(QPushButton):
    """Modern icon + label navigation button with active left pill indicator and notification badge."""

    def __init__(self, icon_target: str, text: str, page_id: str, badge_text: str = "", theme: str = "dark", parent=None):
        super().__init__(parent)
        self.page_id = page_id
        self.icon_target = icon_target
        self.label_text = text
        self.badge_text = badge_text
        self.theme = theme
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(56)
        self.setMinimumWidth(72)
        self.setMaximumWidth(84)

        self._setup_ui()
        self.set_theme(theme)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignCenter)

        # Top row: icon and optional badge
        top_box = QHBoxLayout()
        top_box.setContentsMargins(0, 0, 0, 0)
        top_box.setSpacing(4)
        top_box.setAlignment(Qt.AlignCenter)

        self.icon_lbl = QLabel()
        self.icon_lbl.setAlignment(Qt.AlignCenter)
        self.icon_lbl.setStyleSheet("background: transparent; border: none;")

        # Resolve icon from SVG path or emoji
        icon_path = get_resource_path(self.icon_target) if self.icon_target.endswith(".svg") or self.icon_target.endswith(".png") else self.icon_target
        if os.path.exists(icon_path):
            pix = QIcon(icon_path).pixmap(22, 22)
            self.icon_lbl.setPixmap(pix)
            self.icon_lbl.setFixedSize(22, 22)
        else:
            self.icon_lbl.setText(self.icon_target)
            self.icon_lbl.setStyleSheet("font-size: 18px; background: transparent; border: none;")

        top_box.addWidget(self.icon_lbl)

        self.badge_lbl = QLabel(self.badge_text)
        self.badge_lbl.setAlignment(Qt.AlignCenter)
        self.badge_lbl.setFixedSize(16, 16)
        self.badge_lbl.setStyleSheet("""
            QLabel {
                background-color: #ef4444;
                color: #ffffff;
                font-size: 9px;
                font-weight: bold;
                border-radius: 8px;
            }
        """)
        self.badge_lbl.setVisible(bool(self.badge_text))
        top_box.addWidget(self.badge_lbl)

        layout.addLayout(top_box)

        # Label text
        self.text_lbl = QLabel(self.label_text)
        self.text_lbl.setAlignment(Qt.AlignCenter)
        self.text_lbl.setStyleSheet("font-size: 10px; font-weight: 600; background: transparent; border: none;")
        layout.addWidget(self.text_lbl)

    def set_badge(self, text: str):
        self.badge_text = text
        self.badge_lbl.setText(text)
        self.badge_lbl.setVisible(bool(text))

    def set_theme(self, theme: str):
        self.theme = theme
        p = get_theme_palette(theme)
        is_light = (theme == "light")

        active_bg = "#e0f2fe" if is_light else "#1e293b"
        active_border = "#0284c7" if is_light else "#38bdf8"
        active_text = "#0284c7" if is_light else "#38bdf8"
        hover_bg = p['bg_hover']
        idle_text = p['text_muted']

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 8px;
                margin: 2px 4px;
            }}
            QPushButton:hover {{
                background-color: {hover_bg};
            }}
            QPushButton:checked {{
                background-color: {active_bg};
                border-left: 3px solid {active_border};
            }}
        """)
        self.text_lbl.setStyleSheet(f"font-size: 10px; font-weight: 600; color: {active_text if self.isChecked() else idle_text}; background: transparent;")


class VerticalSidebar(QWidget):
    """Vertical sidebar navigation matching the modern macOS Companion layout."""

    page_selected = Signal(str)
    page_changed = page_selected
    settings_requested = Signal()
    open_portal_requested = Signal()

    def __init__(self, theme: str = "dark", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedWidth(80)
        self._buttons: Dict[str, SidebarNavButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._setup_ui()
        self.set_theme(theme)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        # App Brand Mark / Audio Soundwave Icon
        self.brand_icon = QLabel()
        self.brand_icon.setAlignment(Qt.AlignCenter)
        app_icon_file = get_resource_path("app_icon.png")
        if os.path.exists(app_icon_file):
            pix = QPixmap(app_icon_file).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.brand_icon.setPixmap(pix)
            self.brand_icon.setFixedSize(36, 36)
        else:
            self.brand_icon.setText("🌊")
            self.brand_icon.setStyleSheet("font-size: 24px; padding-bottom: 6px; background: transparent;")
        layout.addWidget(self.brand_icon, alignment=Qt.AlignHCenter)

        # Divider line
        div1 = QFrame()
        div1.setFrameShape(QFrame.HLine)
        div1.setFixedHeight(1)
        layout.addWidget(div1)

        # Primary Tabs: Meetings, On this PC, Record
        self.btn_meetings = SidebarNavButton("resources/icons/meetings.svg", "Meetings", "meetings", theme=self.theme, parent=self)
        self.btn_history = SidebarNavButton("resources/icons/history.svg", "On this PC", "history", theme=self.theme, parent=self)
        self.btn_record = SidebarNavButton("resources/icons/record.svg", "Record", "record", theme=self.theme, parent=self)

        for btn in (self.btn_meetings, self.btn_history, self.btn_record):
            self._buttons[btn.page_id] = btn
            self._button_group.addButton(btn)
            btn.clicked.connect(self._on_btn_clicked)
            layout.addWidget(btn)

        layout.addStretch(1)

        # Divider line before bottom utilities
        div2 = QFrame()
        div2.setFrameShape(QFrame.HLine)
        div2.setFixedHeight(1)
        layout.addWidget(div2)

        # Bottom Utilities: Settings and Speakr Web Portal
        settings_icon_path = get_resource_path("resources/icons/settings.svg")
        self.btn_settings = QPushButton()
        self.btn_settings.setToolTip("Settings & Preferences")
        if os.path.exists(settings_icon_path):
            self.btn_settings.setIcon(QIcon(settings_icon_path))
            self.btn_settings.setIconSize(QSize(20, 20))
            self.btn_settings.setText("Settings")
        else:
            self.btn_settings.setText("⚙️\nSettings")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.setFixedHeight(48)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.btn_settings)

        portal_icon_path = get_resource_path("resources/icons/portal.svg")
        self.btn_portal = QPushButton()
        self.btn_portal.setToolTip("Open Speakr Web Portal")
        if os.path.exists(portal_icon_path):
            self.btn_portal.setIcon(QIcon(portal_icon_path))
            self.btn_portal.setIconSize(QSize(20, 20))
            self.btn_portal.setText("Speakr")
        else:
            self.btn_portal.setText("↗\nSpeakr")
        self.btn_portal.setCursor(Qt.PointingHandCursor)
        self.btn_portal.setFixedHeight(48)
        self.btn_portal.clicked.connect(self.open_portal_requested.emit)
        layout.addWidget(self.btn_portal)

    def _on_btn_clicked(self):
        sender = self.sender()
        if isinstance(sender, SidebarNavButton):
            self.set_current_page(sender.page_id)
            self.page_selected.emit(sender.page_id)

    def set_current_page(self, page_id: str):
        for pid, btn in self._buttons.items():
            btn.setChecked(pid == page_id)
            btn.set_theme(self.theme)

    @property
    def nav_buttons(self) -> Dict[str, SidebarNavButton]:
        return self._buttons

    @property
    def current_page(self) -> str:
        for pid, btn in self._buttons.items():
            if btn.isChecked():
                return pid
        return ""

    @property
    def history_badge(self) -> QLabel:
        return self.btn_history.badge_lbl

    def update_history_badge(self, count: int) -> None:
        self.set_history_badge(count)

    def set_history_badge(self, count: int):
        self.btn_history.set_badge(str(count) if count > 0 else "")

    def set_theme(self, theme: str):
        self.theme = theme
        p = get_theme_palette(theme)
        is_light = (theme == "light")

        bg_bar = "#f1f5f9" if is_light else "#0b0d13"
        border_col = p['border_subtle']

        self.setStyleSheet(f"""
            VerticalSidebar {{
                background-color: {bg_bar};
                border-right: 1px solid {border_col};
            }}
            QFrame {{
                background-color: {border_col};
                border: none;
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: 6px;
                color: {p['text_muted']};
                font-size: 10px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {p['bg_hover']};
                color: {p['text_primary']};
            }}
        """)

        for btn in self._buttons.values():
            btn.set_theme(theme)
