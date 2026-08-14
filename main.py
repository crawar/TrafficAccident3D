import os
import sys

# Headless-friendly backend before ultralytics/matplotlib load via gui -> yolo imports.
os.environ.setdefault("MPLBACKEND", "Agg")

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow
from utils.measurement_save_server import start_measurement_save_server, stop_measurement_save_server


def _ensure_app_font_point_size(app: QApplication) -> None:
    """Avoid QFont::setPointSize(-1) when system font only has pixel size."""
    f = QFont(app.font())
    if f.pointSize() <= 0:
        f.setPointSize(10)
    app.setFont(f)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    _ensure_app_font_point_size(app)
    start_measurement_save_server()
    app.aboutToQuit.connect(stop_measurement_save_server)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
