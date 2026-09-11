from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QCheckBox, QHBoxLayout, QLabel

class VolumeMeter(QWidget):
    """Custom volume meter widget displaying audio level in decibels (-96dB to 0dB)."""

    def __init__(self, label: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.label = label
        self.db_level = -96.0
        self.peak_level = -96.0
        self.min_db = -60.0  # Decibel range to display
        self.max_db = 0.0
        
        # Peak decay timer
        self.decay_timer = QTimer(self)
        self.decay_timer.timeout.connect(self._decay_peak)
        self.decay_timer.start(50)  # 20 FPS decay updates
        
        self.setMinimumHeight(24)

    def set_level(self, db: float) -> None:
        """Set the current decibel level."""
        self.db_level = max(self.min_db, min(self.max_db, db))
        if self.db_level > self.peak_level:
            self.peak_level = self.db_level
        self.update()

    def _decay_peak(self) -> None:
        """Slowly decay the peak level marker."""
        if self.peak_level > self.min_db:
            # Drop by 0.5 dB per tick
            self.peak_level = max(self.min_db, self.peak_level - 0.5)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Draw background track
        track_color = QColor(45, 45, 45)
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, width, height, 4, 4)
        
        # Calculate percentage filled
        range_db = self.max_db - self.min_db
        fill_ratio = (self.db_level - self.min_db) / range_db
        fill_ratio = max(0.0, min(1.0, fill_ratio))
        fill_width = int(width * fill_ratio)
        
        if fill_width > 0:
            # Draw gradient bar (Green -> Yellow -> Red)
            gradient = QLinearGradient(0, 0, width, 0)
            gradient.setColorAt(0.0, QColor(46, 204, 113))   # Green
            gradient.setColorAt(0.7, QColor(241, 196, 15))   # Yellow
            gradient.setColorAt(0.9, QColor(231, 76, 60))    # Red
            
            painter.setBrush(QBrush(gradient))
            painter.drawRoundedRect(0, 0, fill_width, height, 4, 4)
            
        # Draw Peak Marker
        peak_ratio = (self.peak_level - self.min_db) / range_db
        peak_ratio = max(0.0, min(1.0, peak_ratio))
        peak_x = int(width * peak_ratio)
        
        if peak_x > 0:
            painter.setPen(QPen(QColor(255, 255, 255, 180), 2))
            painter.drawLine(peak_x, 2, peak_x, height - 2)
            
        # Draw text overlay
        painter.setPen(QColor(255, 255, 255))
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
        painter.drawText(8, height // 2 + 4, label_text)


class TagSelector(QWidget):
    """Dynamic list of tags retrieved from the Speakr server."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tags_data: List[Dict[str, Any]] = []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)

    def set_tags(self, tags: List[Dict[str, Any]]) -> None:
        """Populate the list with tags."""
        self.list_widget.clear()
        self.tags_data = tags
        
        for tag in tags:
            tag_id = tag.get("id")
            name = tag.get("name", "Unnamed Tag")
            color_hex = tag.get("color", "#7f8c8d")
            
            # Create list item
            item = QListWidgetItem(self.list_widget)
            self.list_widget.addItem(item)
            
            # Create container widget
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(6, 4, 6, 4)
            container_layout.setSpacing(8)
            
            # Checkbox
            checkbox = QCheckBox(name)
            checkbox.setProperty("tag_id", tag_id)
            container_layout.addWidget(checkbox)
            
            # Color badge
            badge = QLabel()
            badge.setFixedSize(12, 12)
            badge.setStyleSheet(f"background-color: {color_hex}; border-radius: 6px; border: 1px solid #454545;")
            container_layout.addWidget(badge)
            
            # Stretch spacer
            container_layout.addStretch()
            
            # Set size and insert widget
            container.setLayout(container_layout)
            item.setSizeHint(container.sizeHint())
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

    def clear_selection(self) -> None:
        """Unchecks all tags."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            if widget:
                checkbox = widget.findChild(QCheckBox)
                if checkbox:
                    checkbox.setChecked(False)
