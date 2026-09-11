import sys
import os
import ctypes
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from core.config import Settings, get_app_icon
from core.recorder import AudioRecorder
from core.uploader import AudioUploader
from gui.main_window import MainWindow
from gui.tray_icon import SystemTrayManager

def main():
    # Set explicit AppUserModelID so Windows taskbar displays our custom icon
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("speakr.companion.windows.1.0")
    except Exception:
        pass

    # Windows 10/11 high DPI scaling compatibility
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setWindowIcon(get_app_icon())
    
    # Ensure app doesn't exit when main window is hidden (minimized to tray)
    app.setQuitOnLastWindowClosed(False)

    # Initialize Core Components
    settings = Settings()
    from core.storage import RecordingsManager
    storage = RecordingsManager(settings)
    recorder = AudioRecorder()
    uploader = AudioUploader(settings, storage)
    
    # Initialize Main Dashboard Window
    main_window = MainWindow(settings, recorder, uploader, storage)
    
    # Initialize System Tray Manager
    tray_manager = SystemTrayManager(main_window, app)
    main_window.tray_manager = tray_manager
    tray_manager.show()

    # Wrap status callbacks to trigger Windows system notifications from background uploader
    base_uploader_callback = uploader.status_callback
    
    def status_callback_wrapper(message: str, success: bool):
        # Trigger default GUI logging
        main_window._handle_status_update(message, success)
        
        # Trigger tray menu sync
        tray_manager.update_menu_state()
        
        # Trigger Windows 11 system notification bubble
        if not success:
            tray_manager.show_notification(
                title="Speakr Companion - Error",
                message=message,
                is_error=True
            )
        elif "Successfully" in message or "Copied" in message:
            tray_manager.show_notification(
                title="Speakr Companion - Ingestion Complete",
                message=message,
                is_error=False
            )

    uploader.status_callback = status_callback_wrapper

    # Hook recorder events to update tray icon menu state (toggling manual record text)
    base_recorder_start = recorder.start_recording
    base_recorder_stop = recorder.stop_recording

    def start_rec_wrapper(*args, **kwargs):
        base_recorder_start(*args, **kwargs)
        tray_manager.update_menu_state()
        tray_manager.show_notification(
            title="Recording Started",
            message=f"Capturing active session..."
        )

    def stop_rec_wrapper(*args, **kwargs):
        base_recorder_stop(*args, **kwargs)
        tray_manager.update_menu_state()

    recorder.start_recording = start_rec_wrapper
    recorder.stop_recording = stop_rec_wrapper

    # Show dashboard window on initial launch
    main_window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
