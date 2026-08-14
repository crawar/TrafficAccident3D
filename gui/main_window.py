from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QLabel, QFileDialog, QProgressBar,
                               QMessageBox, QApplication,
                               QSizePolicy, QFrame)
from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
import os

from core.yolo_detector import YoloDetector
from gui.example_dialog import ExampleDialog
from gui.result_window import ResultWindow
from gui.system_settings_dialog import SystemSettingsDialog
from gui.vehicle_preview_dialog import open_vehicle_preview
from utils.ai_settings import load_ai_settings
from utils.app_paths import app_path
from utils.annotation_history import load_annotation
from utils.measurement_port_settings import rewrite_html_save_measurements_url
from utils.measurement_save_server import (
    get_current_listen_port,
    is_configured_port_busy,
)
from utils.recognition_settings import (
    models_available,
    selected_model_path,
)

PRIMARY_CONTROL_H = 50

# Visual language: slate + teal (aviation / forensic dashboard), not purple.
PRIMARY_BTN_STYLE = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 14px;
    background-color: #0f766e;
    color: #f0fdfa;
    padding: 0 16px;
    border: 1px solid #14b8a6;
}
QPushButton:hover:enabled {
    background-color: #0d9488;
    border: 1px solid #2dd4bf;
}
QPushButton:pressed:enabled {
    background-color: #115e59;
}
QPushButton:disabled {
    background-color: #334155;
    color: #94a3b8;
    border: 1px solid #475569;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)

HISTORY_BTN_STYLE = """
QPushButton {
    min-height: %dpx;
    max-height: %dpx;
    font-size: 15px;
    font-weight: 600;
    border-radius: 14px;
    background-color: #1e293b;
    color: #e2e8f0;
    padding: 0 16px;
    border: 1px solid #334155;
}
QPushButton:hover:enabled {
    background-color: #243044;
    border: 1px solid #14b8a6;
    color: #f0fdfa;
}
QPushButton:pressed:enabled {
    background-color: #0f172a;
}
QPushButton:disabled {
    background-color: #1e293b;
    color: #64748b;
    border: 1px solid #334155;
}
""" % (PRIMARY_CONTROL_H, PRIMARY_CONTROL_H)


class ProcessThread(QThread):
    finished = Signal(list, str)
    error = Signal(str)

    def __init__(self, image_path, model_path):
        super().__init__()
        self.image_path = image_path
        self.model_path = model_path

    def run(self):
        try:
            yolo = YoloDetector(self.model_path)
            vehicles = yolo.detect(self.image_path)
            self.finished.emit(vehicles, self.image_path)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("六支队通用无人机一图勘察数字模型")

        self.resize(460, 820)
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

        self.current_image_path = None
        self.vehicles = []
        self.lanes = []
        self.ai_settings = load_ai_settings()

        self.init_ui()
        self.refresh_port_warning()
        self._restore_main_actions_enabled()

    def init_ui(self):
        outer = QWidget()
        outer.setObjectName("rootBg")
        outer.setStyleSheet(
            """
            QWidget#rootBg {
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0b1220, stop:0.45 #111827, stop:1 #0f172a
                );
            }
            QWidget#rootBg QLabel {
                background: transparent;
            }
            QFrame#headerPanel {
                background-color: rgba(15, 118, 110, 0.12);
                border: 1px solid rgba(20, 184, 166, 0.28);
                border-radius: 16px;
            }
            QFrame#actionPanel, QFrame#toolPanel {
                background-color: rgba(30, 41, 59, 0.72);
                border: 1px solid #334155;
                border-radius: 16px;
            }
            QLabel#brandMark {
                color: #2dd4bf;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 2px;
            }
            QLabel#titleLabel {
                color: #f8fafc;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#subtitleLabel {
                color: #94a3b8;
                font-size: 12px;
            }
            QLabel#sectionLabel {
                color: #64748b;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#footerHint {
                color: #64748b;
                font-size: 11px;
            }
            """
        )
        self.setCentralWidget(outer)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(20, 24, 20, 24)
        outer_layout.addStretch(1)

        row = QHBoxLayout()
        row.addStretch(1)

        column = QWidget()
        column.setFixedWidth(400)
        column.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        inner = QVBoxLayout(column)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(14)

        header = QFrame()
        header.setObjectName("headerPanel")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 16, 16, 16)
        header_layout.setSpacing(6)

        brand = QLabel("DRONE SURVEY  ·  3D MODEL")
        brand.setObjectName("brandMark")
        brand.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(brand)

        title = QLabel("六支队通用无人机\n一图勘察数字模型")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        header_layout.addWidget(title)

        subtitle = QLabel("航拍识别 · 三维重建 · 测量导出")
        subtitle.setObjectName("subtitleLabel")
        subtitle.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(subtitle)
        inner.addWidget(header)

        action_panel = QFrame()
        action_panel.setObjectName("actionPanel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(14, 14, 14, 14)
        action_layout.setSpacing(10)

        action_label = QLabel("主流程")
        action_label.setObjectName("sectionLabel")
        action_layout.addWidget(action_label)

        self.upload_btn = QPushButton("上传图片")
        self.upload_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        self.upload_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.upload_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.upload_btn.setCursor(Qt.PointingHandCursor)
        self.upload_btn.clicked.connect(self.on_upload)
        action_layout.addWidget(self.upload_btn)

        self.history_btn = QPushButton("查看历史")
        self.history_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.history_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.history_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.history_btn.setCursor(Qt.PointingHandCursor)
        self.history_btn.clicked.connect(self.on_view_history)
        action_layout.addWidget(self.history_btn)

        self.progress_slot = QWidget()
        self.progress_slot.setFixedHeight(56)
        self.progress_slot.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        progress_slot_layout = QVBoxLayout(self.progress_slot)
        progress_slot_layout.setContentsMargins(0, 2, 0, 0)
        progress_slot_layout.setSpacing(6)
        self.progress_label = QLabel("图像处理中，请稍后...")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #fbbf24; background: transparent;"
        )
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                border: none;
                border-radius: 5px;
                background-color: #1e293b;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 5px;
                background-color: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0f766e, stop:1 #2dd4bf
                );
            }
            """
        )
        self.progress_widget = QWidget()
        self.progress_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.progress_layout = QVBoxLayout(self.progress_widget)
        self.progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_layout.setSpacing(6)
        self.progress_layout.addWidget(self.progress_label)
        self.progress_layout.addWidget(self.progress_bar)
        self.progress_widget.hide()
        progress_slot_layout.addWidget(self.progress_widget)
        action_layout.addWidget(self.progress_slot)
        inner.addWidget(action_panel)

        tool_panel = QFrame()
        tool_panel.setObjectName("toolPanel")
        tool_layout = QVBoxLayout(tool_panel)
        tool_layout.setContentsMargins(14, 14, 14, 14)
        tool_layout.setSpacing(10)

        tool_label = QLabel("工具与设置")
        tool_label.setObjectName("sectionLabel")
        tool_layout.addWidget(tool_label)

        self.preview_vehicle_btn = QPushButton("建模预览")
        self.preview_vehicle_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.preview_vehicle_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.preview_vehicle_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.preview_vehicle_btn.setCursor(Qt.PointingHandCursor)
        self.preview_vehicle_btn.setToolTip(
            "单车 Three.js 预览，底部三角切换车型（与导出场景同源逻辑）"
        )
        self.preview_vehicle_btn.clicked.connect(lambda: open_vehicle_preview(self))
        tool_layout.addWidget(self.preview_vehicle_btn)

        self.system_settings_btn = QPushButton("系统设置")
        self.system_settings_btn.setStyleSheet(HISTORY_BTN_STYLE)
        self.system_settings_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.system_settings_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.system_settings_btn.setCursor(Qt.PointingHandCursor)
        self.system_settings_btn.clicked.connect(self.open_system_settings)
        tool_layout.addWidget(self.system_settings_btn)

        tool_layout.addStretch(1)

        footer = QLabel("湖南交警总队 高速公路交通管理六支队@2026")
        footer.setObjectName("footerHint")
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        tool_layout.addWidget(footer)

        self.port_warning_label = QLabel("端口被占用请另行设置")
        self.port_warning_label.setAlignment(Qt.AlignCenter)
        self.port_warning_label.setWordWrap(True)
        self.port_warning_label.setStyleSheet(
            """
            color: #fecaca;
            font-size: 12px;
            font-weight: 600;
            background-color: rgba(127, 29, 29, 0.35);
            border: 1px solid rgba(248, 113, 113, 0.45);
            border-radius: 10px;
            padding: 8px 10px;
            """
        )
        self.port_warning_label.hide()
        tool_layout.addWidget(self.port_warning_label)
        inner.addWidget(tool_panel)

        # Match tool panel height to main-flow panel (includes progress slot reserve).
        pair_h = max(action_panel.sizeHint().height(), tool_panel.sizeHint().height())
        action_panel.setMinimumHeight(pair_h)
        tool_panel.setMinimumHeight(pair_h)

        row.addWidget(column)
        row.addStretch(1)
        outer_layout.addLayout(row)
        outer_layout.addStretch(1)

    def _models_available(self):
        return models_available() and bool(selected_model_path())

    def _restore_main_actions_enabled(self):
        ok = self._models_available()
        self.upload_btn.setEnabled(ok)
        self.history_btn.setEnabled(True)

    def refresh_port_warning(self):
        self.port_warning_label.setVisible(bool(is_configured_port_busy()))

    def on_upload(self):
        if not self._models_available():
            QMessageBox.warning(
                self,
                "提示",
                "未找到可用的 YOLO 模型，请先在系统设置 → 识别设置中配置。",
            )
            return

        tip = ExampleDialog(self)
        if tip.exec() != ExampleDialog.Accepted:
            return

        file_name, _ = QFileDialog.getOpenFileName(
            self, "选择图像", "", "Images (*.png *.xpm *.jpg *.jpeg *.bmp)"
        )
        if not file_name:
            return
        if not os.path.isfile(file_name):
            QMessageBox.warning(self, "提示", "所选文件不存在。")
            return
        self.current_image_path = file_name
        self.on_start_recognize()

    def on_view_history(self):
        history_dir = app_path("history")
        os.makedirs(history_dir, exist_ok=True)
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "选择历史 HTML",
            history_dir,
            "HTML (*.html)",
        )
        if not file_name:
            return
        if not os.path.isfile(file_name):
            QMessageBox.warning(self, "提示", "所选文件不存在。")
            return

        port = get_current_listen_port()
        if port is None:
            QMessageBox.warning(
                self,
                "提示",
                "测量保存服务未启动或端口被占用，请先在系统设置中调整端口。",
            )
            self.refresh_port_warning()
            return

        try:
            rewrite_html_save_measurements_url(file_name, port)
        except OSError as exc:
            QMessageBox.critical(self, "错误", f"无法更新 HTML 端口：{exc}")
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(file_name)))

    def on_start_recognize(self):
        if not self.current_image_path or not self._models_available():
            return

        cached_annotation = load_annotation(self.current_image_path)
        if cached_annotation is not None:
            result_window = ResultWindow(
                self.current_image_path,
                cached_annotation["vehicles"],
                self,
                cached_annotation["lanes"],
                markers=cached_annotation.get("markers", []),
                cached_annotation=cached_annotation,
                ai_settings=self.ai_settings,
            )
            result_window.exec()
            return

        model_path = selected_model_path()
        if not model_path:
            QMessageBox.warning(
                self,
                "提示",
                "未找到可用的 YOLO 模型，请先在系统设置 → 识别设置中配置。",
            )
            return

        self.progress_widget.show()
        self.upload_btn.setEnabled(False)
        self.history_btn.setEnabled(False)

        self.thread = ProcessThread(self.current_image_path, model_path)
        self.thread.finished.connect(self.on_process_finished)
        self.thread.error.connect(self.on_process_error)
        self.thread.start()

    def on_process_finished(self, vehicles, image_path):
        self.progress_widget.hide()
        self._restore_main_actions_enabled()
        result_window = ResultWindow(
            image_path,
            vehicles,
            self,
            cached_annotation=None,
            ai_settings=self.ai_settings,
        )
        result_window.exec()

    def on_process_error(self, err_msg):
        self.progress_widget.hide()
        self._restore_main_actions_enabled()
        QMessageBox.critical(self, "错误", f"图像处理失败: {err_msg}")

    def open_system_settings(self):
        dialog = SystemSettingsDialog(self)
        dialog.exec()
        if dialog.saved_ai_settings is not None:
            self.ai_settings = dialog.saved_ai_settings
        else:
            self.ai_settings = load_ai_settings()
        self._restore_main_actions_enabled()
        self.refresh_port_warning()
