from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.ai_expert_settings_dialog import AiExpertSettingsPanel
from gui.ai_prompt_dialog import AiPromptPanel
from gui.ai_settings_dialog import AiSettingsPanel
from utils.animation_settings import (
    DEFAULT_PLAYBACK_SPEED_FACTOR,
    MAX_PLAYBACK_SPEED_FACTOR,
    MIN_PLAYBACK_SPEED_FACTOR,
    load_animation_settings,
    save_animation_settings,
)
from utils.measurement_port_settings import (
    DEFAULT_MEASUREMENT_SAVE_PORT,
    default_measurement_port_settings,
    load_measurement_port_settings,
    save_measurement_port_settings,
)
from utils.measurement_save_server import (
    get_current_listen_port,
    probe_port_available,
    restart_measurement_save_server,
)
from utils.recognition_settings import (
    list_yolo_model_files,
    load_recognition_settings,
    save_recognition_settings,
)


class RecognitionSettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_settings = load_recognition_settings()
        self._init_ui()
        self._load_form()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        tip = QLabel(
            "选择识别所用的 YOLO 模型（来自 downloads 目录中的 .pt 文件）。"
            "该设置会在上传图片并开始识别时生效。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setSpacing(12)

        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(280)
        form.addRow("YOLO模型", self.model_combo)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setAutoDefault(False)
        self.save_btn.setDefault(False)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    def _populate_models(self):
        models = list_yolo_model_files()
        current = self.model_combo.currentText()
        self.model_combo.clear()
        if not models:
            self.model_combo.addItem("未找到模型")
            self.model_combo.setEnabled(False)
            self.save_btn.setEnabled(False)
            return
        self.model_combo.setEnabled(True)
        self.save_btn.setEnabled(True)
        for name in models:
            self.model_combo.addItem(name)
        preferred = current or self._saved_settings.get("modelFile", "")
        if preferred:
            index = self.model_combo.findText(preferred)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
                return
        for i in range(self.model_combo.count()):
            if "obb" not in self.model_combo.itemText(i).lower():
                self.model_combo.setCurrentIndex(i)
                return

    def _load_form(self):
        self._saved_settings = load_recognition_settings()
        self._populate_models()

    def save_settings(self):
        if not self.model_combo.isEnabled():
            QMessageBox.warning(self, "提示", "未找到可用的 YOLO 模型。")
            return None
        model_file = self.model_combo.currentText().strip()
        if not model_file or model_file == "未找到模型":
            QMessageBox.warning(self, "提示", "请选择有效的 YOLO 模型。")
            return None
        self._saved_settings = save_recognition_settings({"modelFile": model_file})
        return dict(self._saved_settings)

    def _on_save(self):
        result = self.save_settings()
        if result is None:
            return
        parent = self.window()
        if hasattr(parent, "recognitionSettingsSaved"):
            parent.recognitionSettingsSaved(result)
        QMessageBox.information(self, "保存", f"识别模型已保存为：{result['modelFile']}")

    @property
    def saved_settings(self):
        return dict(self._saved_settings)


class PortSettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._load_form()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        tip = QLabel(
            "测量保存服务监听本机端口。勾选「静默随机端口」时沿用程序自动选端口逻辑；"
            "取消勾选后可固定端口，避免与其他程序冲突。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.silent_random_checkbox = QCheckBox("静默随机端口")
        self.silent_random_checkbox.setToolTip(
            "勾选后由程序自动选择可用端口（含历史别名与随机回退）；"
            "取消勾选后仅使用下方指定端口。"
        )
        self.silent_random_checkbox.toggled.connect(self._apply_silent_state)
        layout.addWidget(self.silent_random_checkbox)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("端口"))
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(DEFAULT_MEASUREMENT_SAVE_PORT)
        port_row.addWidget(self.port_spin, 1)

        self.test_btn = QPushButton("测试")
        self.test_btn.setAutoDefault(False)
        self.test_btn.setDefault(False)
        self.test_btn.clicked.connect(self._on_test)
        port_row.addWidget(self.test_btn)
        layout.addLayout(port_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color: #555; font-size: 12px;")
        layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setAutoDefault(False)
        self.save_btn.setDefault(False)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        self.restore_btn = QPushButton("恢复默认")
        self.restore_btn.setAutoDefault(False)
        self.restore_btn.setDefault(False)
        self.restore_btn.clicked.connect(self._on_restore_default)
        btn_row.addWidget(self.restore_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        layout.addStretch(1)

    def _load_form(self):
        settings = load_measurement_port_settings()
        self.silent_random_checkbox.blockSignals(True)
        self.silent_random_checkbox.setChecked(bool(settings.get("silentRandom", True)))
        self.silent_random_checkbox.blockSignals(False)
        self.port_spin.setValue(int(settings.get("port", DEFAULT_MEASUREMENT_SAVE_PORT)))
        self._apply_silent_state()
        listen = get_current_listen_port()
        if listen is not None:
            self.status_label.setText(f"当前服务监听端口：{listen}")
        else:
            self.status_label.setText("当前服务未成功监听")

    def _apply_silent_state(self):
        silent = self.silent_random_checkbox.isChecked()
        self.port_spin.setEnabled(not silent)
        # Test still useful in silent mode to show current listen port availability.
        self.test_btn.setEnabled(True)

    def collect_settings(self):
        return {
            "silentRandom": self.silent_random_checkbox.isChecked(),
            "port": int(self.port_spin.value()),
        }

    def _on_test(self):
        if self.silent_random_checkbox.isChecked():
            listen = get_current_listen_port()
            if listen is None:
                QMessageBox.warning(self, "测试", "当前未监听任何端口。")
                return
            ok, message = probe_port_available(listen, treat_self_as_ok=True)
            icon = QMessageBox.Information if ok else QMessageBox.Warning
            QMessageBox(icon, "测试", message, QMessageBox.Ok, self).exec()
            return

        port = int(self.port_spin.value())
        ok, message = probe_port_available(port, treat_self_as_ok=True)
        icon = QMessageBox.Information if ok else QMessageBox.Warning
        QMessageBox(icon, "测试", message, QMessageBox.Ok, self).exec()

    def _on_save(self):
        settings = save_measurement_port_settings(self.collect_settings())
        restart_measurement_save_server()
        self._load_form()
        listen = get_current_listen_port()
        if settings.get("silentRandom", True):
            QMessageBox.information(
                self,
                "保存",
                f"已保存（静默随机）。当前监听端口：{listen if listen else '未知'}",
            )
        elif listen is not None:
            QMessageBox.information(self, "保存", f"已保存。当前监听端口：{listen}")
        else:
            QMessageBox.warning(
                self,
                "保存",
                f"已保存固定端口 {settings['port']}，但该端口被占用，服务未能启动。"
                "请更换端口后重新保存。",
            )
        parent = self.window()
        if hasattr(parent, "portSettingsSaved"):
            parent.portSettingsSaved()

    def _on_restore_default(self):
        defaults = default_measurement_port_settings()
        self.silent_random_checkbox.blockSignals(True)
        self.silent_random_checkbox.setChecked(True)
        self.silent_random_checkbox.blockSignals(False)
        self.port_spin.setValue(int(defaults["port"]))
        self._apply_silent_state()
        save_measurement_port_settings(defaults)
        restart_measurement_save_server()
        self._load_form()
        QMessageBox.information(self, "恢复默认", "已恢复为静默随机端口（默认 8765）。")
        parent = self.window()
        if hasattr(parent, "portSettingsSaved"):
            parent.portSettingsSaved()


class AnimationSettingsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_settings = load_animation_settings()
        self._init_ui()
        self._load_form()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        tip = QLabel(
            "运动播放执行速度：实际 3D 车速 = 车辆设定公里/小时 × 本系数。"
            f"默认 {DEFAULT_PLAYBACK_SPEED_FACTOR}（十分之一），范围 "
            f"{MIN_PLAYBACK_SPEED_FACTOR}–{MAX_PLAYBACK_SPEED_FACTOR}。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setSpacing(12)

        self.factor_spin = QDoubleSpinBox()
        self.factor_spin.setRange(MIN_PLAYBACK_SPEED_FACTOR, MAX_PLAYBACK_SPEED_FACTOR)
        self.factor_spin.setDecimals(3)
        self.factor_spin.setSingleStep(0.01)
        self.factor_spin.setMinimumWidth(160)
        form.addRow("执行速度", self.factor_spin)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("保存")
        self.save_btn.setAutoDefault(False)
        self.save_btn.setDefault(False)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)
        layout.addStretch(1)

    def _load_form(self):
        self._saved_settings = load_animation_settings()
        self.factor_spin.setValue(
            float(
                self._saved_settings.get(
                    "playbackSpeedFactor", DEFAULT_PLAYBACK_SPEED_FACTOR
                )
            )
        )

    def save_settings(self):
        self._saved_settings = save_animation_settings(
            {"playbackSpeedFactor": float(self.factor_spin.value())}
        )
        return dict(self._saved_settings)

    def _on_save(self):
        self.save_settings()
        QMessageBox.information(self, "保存", "动画设置已保存。")


class SystemSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("系统设置")
        self.resize(700, 520)
        self.setWindowModality(Qt.ApplicationModal)
        self._saved_ai_settings = None
        self._saved_recognition_settings = None
        self._port_changed = False

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.recognition_panel = RecognitionSettingsPanel(self)
        self.ai_panel = AiSettingsPanel(self)
        self.prompt_panel = AiPromptPanel(self)
        self.expert_panel = AiExpertSettingsPanel(self)
        self.port_panel = PortSettingsPanel(self)
        self.animation_panel = AnimationSettingsPanel(self)
        self.tabs.addTab(self.recognition_panel, "识别设置")
        self.tabs.addTab(self.ai_panel, "AI连接")
        self.tabs.addTab(self.prompt_panel, "AI提示词")
        self.tabs.addTab(self.expert_panel, "AI专家设置")
        self.tabs.addTab(self.port_panel, "端口设置")
        self.tabs.addTab(self.animation_panel, "动画设置")
        layout.addWidget(self.tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        close_btn = buttons.button(QDialogButtonBox.Close)
        if close_btn is not None:
            close_btn.setAutoDefault(False)
            close_btn.setDefault(False)
            close_btn.setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        # Save AI tabs when closing if user edited them via a dedicated Save on each tab?
        # Port panel has its own Save. For AI tabs, add a bottom Save for current tab content.
        self.save_all_btn = QPushButton("保存当前页")
        self.save_all_btn.setAutoDefault(False)
        self.save_all_btn.setDefault(False)
        self.save_all_btn.clicked.connect(self._save_current_tab)
        buttons.addButton(self.save_all_btn, QDialogButtonBox.ActionRole)
        layout.addWidget(buttons)

    def portSettingsSaved(self):
        self._port_changed = True

    def recognitionSettingsSaved(self, settings):
        self._saved_recognition_settings = dict(settings or {})

    def _save_current_tab(self):
        index = self.tabs.currentIndex()
        if index == 0:
            result = self.recognition_panel.save_settings()
            if result is None:
                return
            self._saved_recognition_settings = result
            QMessageBox.information(
                self, "保存", f"识别模型已保存为：{result['modelFile']}"
            )
        elif index == 1:
            result = self.ai_panel.save_settings(parent_widget=self)
            if result is None:
                return
            self._saved_ai_settings = result
            QMessageBox.information(self, "保存", "AI连接设置已保存。")
        elif index == 2:
            self.prompt_panel.save_prompt()
            QMessageBox.information(self, "保存", "AI提示词已保存。")
        elif index == 3:
            result = self.expert_panel.save_settings()
            if result is None:
                return
            QMessageBox.information(self, "保存", "AI专家设置已保存。")
        elif index == 4:
            self.port_panel._on_save()
        elif index == 5:
            self.animation_panel.save_settings()
            QMessageBox.information(self, "保存", "动画设置已保存。")

    @property
    def saved_ai_settings(self):
        return self._saved_ai_settings

    @property
    def saved_recognition_settings(self):
        return self._saved_recognition_settings

    @property
    def port_changed(self):
        return self._port_changed
