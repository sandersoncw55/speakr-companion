from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QStyle

from core.config import get_app_icon

def create_badged_icon(state: str = "ready") -> QIcon:
    """Renders the base app icon with a status dot indicator in the bottom-right corner."""
    base_icon = get_app_icon()
    pixmap = base_icon.pixmap(32, 32)
    if pixmap.isNull():
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Color mapping
    state_colors = {
        "ready": QColor(46, 204, 113),      # Green
        "recording": QColor(231, 76, 60),    # Red
        "paused": QColor(241, 196, 15),      # Yellow
        "cooldown": QColor(230, 126, 34)     # Orange
    }
    dot_color = state_colors.get(state.lower(), QColor(46, 204, 113))

    # Draw badge in bottom right
    painter.setPen(QPen(QColor(30, 30, 30), 1.5))
    painter.setBrush(QBrush(dot_color))
    painter.drawEllipse(QRectF(19, 19, 11, 11))
    painter.end()

    return QIcon(pixmap)

class SystemTrayManager(QSystemTrayIcon):
    """Manages system tray icon, context menu, and desktop notifications."""

    def __init__(self, main_window, parent=None):
        icon = create_badged_icon("ready")
        super().__init__(icon, parent)
        self.setIcon(icon)
        
        self.main_window = main_window
        self.current_state = "ready"
        self.setToolTip("Speakr Windows Companion - Ready")
        
        # Context Menu
        self.menu = QMenu()
        self._init_menu()
        self.setContextMenu(self.menu)
        
        # Double click to restore window
        self.activated.connect(self._on_tray_activated)

    def _init_menu(self) -> None:
        # Restore action
        self.restore_action = QAction("Open Dashboard", self)
        self.restore_action.triggered.connect(self._show_window)
        self.menu.addAction(self.restore_action)
        
        self.menu.addSeparator()
        
        # Toggle Recording action
        self.record_action = QAction("Start Manual Record", self)
        self.record_action.triggered.connect(self._toggle_recording)
        self.menu.addAction(self.record_action)
        
        # Enable Auto-Record toggle
        self.auto_record_action = QAction("Auto-Record Enabled", self)
        self.auto_record_action.setCheckable(True)
        self.auto_record_action.setChecked(self.main_window.settings.auto_record_enabled)
        self.auto_record_action.triggered.connect(self._toggle_auto_record)
        self.menu.addAction(self.auto_record_action)
        
        self.menu.addSeparator()
        
        # Exit action
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self._quit_app)
        self.menu.addAction(self.exit_action)

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # Single click / double click triggers
            self._show_window()

    def _show_window(self) -> None:
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _toggle_recording(self) -> None:
        self.main_window._toggle_recording()
        self.update_menu_state()

    def _toggle_auto_record(self, checked: bool) -> None:
        self.main_window.auto_record_chk.setChecked(checked)

    def update_menu_state(self) -> None:
        """Update context menu text/checkmarks based on recording state."""
        # 1. Update Manual Recording action text
        if self.main_window.recorder.is_recording:
            self.record_action.setText("Stop Manual Record")
        else:
            self.record_action.setText("Start Manual Record")
            
        # 2. Update Auto Record checkbox state
        self.auto_record_action.setChecked(self.main_window.settings.auto_record_enabled)

    def set_state(self, state: str, details: str = "") -> None:
        """Updates the dynamic icon badge and tooltip based on state (ready, recording, paused, cooldown)."""
        self.current_state = state.lower()
        self.setIcon(create_badged_icon(self.current_state))
        
        detail_text = f" - {details}" if details else ""
        if self.current_state == "recording":
            self.setToolTip(f"Speakr Companion - Recording{detail_text}")
        elif self.current_state == "paused":
            self.setToolTip(f"Speakr Companion - Paused{detail_text}")
        elif self.current_state == "cooldown":
            self.setToolTip(f"Speakr Companion - Cooldown{detail_text}")
        else:
            self.setToolTip("Speakr Companion - Ready")
        self.update_menu_state()

    def show_notification(self, title: str, message: str, is_error: bool = False) -> None:
        """Displays Windows 11 system notification balloon."""
        icon_type = QSystemTrayIcon.MessageIcon.Information
        if is_error:
            icon_type = QSystemTrayIcon.MessageIcon.Warning
            
        self.showMessage(
            title,
            message,
            icon_type,
            5000  # display duration milliseconds
        )

    def _quit_app(self) -> None:
        """Properly close background threads and terminate application."""
        # Bypass MainWindow's closeEvent minimize-to-tray logic
        self.main_window.monitor.stop()
        self.main_window.recorder.terminate()
        QApplication.quit()
