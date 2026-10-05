from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, QTimer, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QCheckBox, QHBoxLayout, QLabel
from gui.theme import get_theme_palette

class VolumeMeter(QWidget):
    """Custom volume meter widget displaying audio level in decibels (-60dB to 0dB) with theme awareness."""

    def __init__(self, label: str = "", channel_type: str = "default", theme: str = "dark", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.label = label
        self.channel_type = channel_type.lower()  # 'mic', 'system', or 'default'
        self.theme = theme
        self.db_level = -96.0
        self.peak_level = -96.0
        self.min_db = -60.0  # Decibel range to display
        self.max_db = 0.0
        
        # Peak decay timer
        self.decay_timer = QTimer(self)
        self.decay_timer.timeout.connect(self._decay_peak)
        self.decay_timer.start(50)  # 20 FPS decay updates
        
        self.setMinimumHeight(28)

    def set_theme(self, theme: str) -> None:
        """Update current color theme and redraw."""
        self.theme = theme
        self.update()

    def set_level(self, db: float) -> None:
        """Set the current decibel level."""
        self.db_level = max(self.min_db, min(self.max_db, db))
        if self.db_level > self.peak_level:
            self.peak_level = self.db_level
        self.update()

    def _decay_peak(self) -> None:
        """Slowly decay the peak level marker."""
        if self.peak_level > self.min_db:
            self.peak_level = max(self.min_db, self.peak_level - 0.5)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        p = get_theme_palette(self.theme)
        
        # Draw background track
        track_color = QColor(p["meter_track"])
        painter.setBrush(QBrush(track_color))
        painter.setPen(QPen(QColor(p["meter_track_border"]), 1))
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 4, 4)
        
        # Calculate percentage filled
        range_db = self.max_db - self.min_db
        fill_ratio = (self.db_level - self.min_db) / range_db
        fill_ratio = max(0.0, min(1.0, fill_ratio))
        fill_width = int((width - 2) * fill_ratio)
        
        if fill_width > 0:
            gradient = QLinearGradient(0, 0, width, 0)
            if "mic" in self.channel_type or "mic" in self.label.lower():
                # Channel 1: Electric / Cerulean Cyan
                gradient.setColorAt(0.0, QColor(p["meter_mic_start"]))
                gradient.setColorAt(1.0, QColor(p["meter_mic_end"]))
            elif "sys" in self.channel_type or "speaker" in self.channel_type or "loopback" in self.label.lower() or "speaker" in self.label.lower():
                # Channel 2: Soft Lavender / Royal Violet
                gradient.setColorAt(0.0, QColor(p["meter_sys_start"]))
                gradient.setColorAt(1.0, QColor(p["meter_sys_end"]))
            else:
                # Default multi-stop meter
                gradient.setColorAt(0.0, QColor(p["accent_emerald"]))
                gradient.setColorAt(0.7, QColor(245, 158, 11))
                gradient.setColorAt(0.95, QColor(p["accent_coral"]))
            
            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(1, 1, fill_width, height - 2, 3, 3)
            
        # Draw Peak Marker
        peak_ratio = (self.peak_level - self.min_db) / range_db
        peak_ratio = max(0.0, min(1.0, peak_ratio))
        peak_x = int((width - 2) * peak_ratio)
        
        if peak_x > 0:
            if "mic" in self.channel_type or "mic" in self.label.lower():
                peak_color = QColor(p["meter_mic_peak"])
            elif "sys" in self.channel_type or "speaker" in self.channel_type or "loopback" in self.label.lower() or "speaker" in self.label.lower():
                peak_color = QColor(p["meter_sys_peak"])
            else:
                peak_color = QColor(255, 255, 255, 220)
                
            painter.setPen(QPen(peak_color, 2))
            painter.drawLine(peak_x, 2, peak_x, height - 2)
            
        # Draw text overlay
        painter.setPen(QColor(p["text_primary"]))
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        
        # Display label with context-aware quiet / idle indicators
        if self.db_level > self.min_db:
            label_text = f"{self.label}: {self.db_level:.1f} dB"
        else:
            label_lower = self.label.lower()
            if "mic" in label_lower:
                label_text = f"{self.label}: Idle (Listening...)"
            elif "speaker" in label_lower or "loopback" in label_lower:
                label_text = f"{self.label}: Idle (Silent)"
            else:
                label_text = f"{self.label}: Idle / Standby"
        painter.drawText(10, height // 2 + 4, label_text)


class TagSelector(QWidget):
    """Dynamic list of tags retrieved from the Speakr server."""

    def __init__(self, theme: str = "dark", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.theme = theme
        self.tags_data: List[Dict[str, Any]] = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        """Update styling for current theme."""
        self.theme = theme
        p = get_theme_palette(theme)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {p['bg_input']};
                border: 1px solid {p['border_subtle']};
                border-radius: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 0px;
                margin: 0px;
                border-bottom: 1px solid {p['border_subtle']};
            }}
            QListWidget::item:hover {{
                background-color: {p['bg_hover']};
            }}
        """)
        # Refresh existing tag items styling
        if self.tags_data:
            self.set_tags(self.tags_data)

    def set_tags(self, tags: List[Dict[str, Any]]) -> None:
        """Populate the list with tags."""
        self.list_widget.clear()
        self.tags_data = tags
        p = get_theme_palette(self.theme)
        
        for tag in tags:
            tag_id = tag.get("id")
            name = tag.get("name", "Unnamed Tag")
            color_hex = tag.get("color", "#7f8c8d")
            
            # Create container widget
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(12, 4, 12, 4)
            container_layout.setSpacing(10)
            
            # Checkbox
            checkbox = QCheckBox(name)
            checkbox.setProperty("tag_id", tag_id)
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: {p['text_primary']};
                    font-size: 12px;
                    spacing: 8px;
                    padding-left: 2px;
                }}
                QCheckBox::indicator {{
                    width: 16px;
                    height: 16px;
                    background-color: {p['bg_input']};
                    border: 1px solid {p['border_medium']};
                    border-radius: 3px;
                }}
                QCheckBox::indicator:hover {{
                    border-color: {p['border_focus']};
                }}
                QCheckBox::indicator:checked {{
                    background-color: {p['accent_cyan']};
                    border-color: {p['accent_cyan']};
                }}
            """)
            container_layout.addWidget(checkbox)
            
            # Color badge
            badge = QLabel()
            badge.setFixedSize(12, 12)
            badge.setStyleSheet(f"background-color: {color_hex}; border-radius: 6px; border: 1px solid {p['border_medium']};")
            container_layout.addWidget(badge)
            
            container_layout.addStretch()
            container.setLayout(container_layout)
            
            # Add item with generous 32px height to avoid clipping
            item = QListWidgetItem(self.list_widget)
            item.setSizeHint(QSize(max(200, container.sizeHint().width()), 32))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, container)

    def selected_tag_ids(self) -> List[int]:
        """Returns the list of currently selected tag IDs."""
        selected_ids = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    tag_id = checkbox.property("tag_id")
                    if tag_id is not None:
                        selected_ids.append(int(tag_id))
        return selected_ids

    def selected_tag_names(self) -> List[str]:
        """Returns the list of currently selected tag names."""
        names = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox and checkbox.isChecked():
                    names.append(checkbox.text().strip())
        return names

    def clear_selection(self) -> None:
        """Unchecks all tags."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)
