from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from utils.ai_settings import load_ai_settings, save_ai_settings


class AiSettingsPanel(QWidget):
    """Reusable AI connection form (used by system settings tab / dialog)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_settings = load_ai_settings()
        self._init_ui()
        self._load_form()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tip = QLabel(
            "可在这里配置责任分析的 API 密钥、请求地址、模型、思考模式和请求参数。"
            "未勾选或关键字段为空时，不会发起 AI 请求。"
            "（自定义提示词请在「系统设置 → AI提示词」中设置。）"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setSpacing(12)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("请输入 DeepSeek API 密钥")
        form.addRow("API密钥", self.api_key_edit)

        self.request_url_edit = QLineEdit()
        self.request_url_edit.setPlaceholderText(
            "例如: https://api.deepseek.com/chat/completions"
        )
        form.addRow("请求地址", self.request_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("例如: deepseek-v4-pro")
        form.addRow("模型名称", self.model_edit)

        self.reasoning_effort_combo = QComboBox()
        self.reasoning_effort_combo.addItem("默认", "")
        self.reasoning_effort_combo.addItem("低", "low")
        self.reasoning_effort_combo.addItem("中", "medium")
        self.reasoning_effort_combo.addItem("高", "high")
        form.addRow("推理强度", self.reasoning_effort_combo)

        self.thinking_mode_combo = QComboBox()
        self.thinking_mode_combo.addItem("默认", "default")
        self.thinking_mode_combo.addItem("开启思考", "enabled")
        self.thinking_mode_combo.addItem("关闭思考", "disabled")
        form.addRow("思考模式", self.thinking_mode_combo)

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setDecimals(2)
        form.addRow("Temperature", self.temperature_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(10, 600)
        self.timeout_spin.setSingleStep(10)
        self.timeout_spin.setSuffix(" 秒")
        form.addRow("超时时间", self.timeout_spin)

        self.enable_checkbox = QCheckBox("启用AI分析责任")
        form.addRow("", self.enable_checkbox)

        self.regen_each_time_checkbox = QCheckBox("每次重新生成事故责任")
        self.regen_each_time_checkbox.setToolTip(
            "勾选时忽略相同标注的历史 AI 缓存，每次识别确认都重新请求接口。"
        )
        form.addRow("", self.regen_each_time_checkbox)
        layout.addLayout(form)

        self.enable_checkbox.toggled.connect(self._apply_enable_state)

    def _apply_enable_state(self):
        on = self.enable_checkbox.isChecked()
        for w in (
            self.api_key_edit,
            self.request_url_edit,
            self.model_edit,
            self.reasoning_effort_combo,
            self.thinking_mode_combo,
            self.temperature_spin,
            self.timeout_spin,
            self.regen_each_time_checkbox,
        ):
            w.setEnabled(on)

    def _load_form(self):
        self.api_key_edit.setText(self._saved_settings.get("deepseekApiKey", ""))
        self.request_url_edit.setText(self._saved_settings.get("requestUrl", ""))
        self.model_edit.setText(self._saved_settings.get("model", ""))
        self._set_combo_value(
            self.reasoning_effort_combo,
            self._saved_settings.get("reasoningEffort", ""),
        )
        self._set_combo_value(
            self.thinking_mode_combo,
            self._saved_settings.get("thinkingMode", "default"),
        )
        self.temperature_spin.setValue(
            float(self._saved_settings.get("temperature", 0.1))
        )
        self.timeout_spin.setValue(
            int(self._saved_settings.get("requestTimeoutSec", 120))
        )
        self.enable_checkbox.setChecked(
            bool(self._saved_settings.get("enableLiabilityAnalysis", False))
        )
        self.regen_each_time_checkbox.setChecked(
            bool(self._saved_settings.get("regenerateLiabilityEachTime", True))
        )
        self._apply_enable_state()

    @staticmethod
    def _set_combo_value(combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def collect_settings(self):
        return {
            "deepseekApiKey": self.api_key_edit.text().strip(),
            "requestUrl": self.request_url_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "reasoningEffort": self.reasoning_effort_combo.currentData(),
            "thinkingMode": self.thinking_mode_combo.currentData(),
            "temperature": self.temperature_spin.value(),
            "requestTimeoutSec": self.timeout_spin.value(),
            "enableLiabilityAnalysis": self.enable_checkbox.isChecked(),
            "regenerateLiabilityEachTime": self.regen_each_time_checkbox.isChecked(),
        }

    def validate_settings(self, settings, parent_widget=None):
        parent = parent_widget or self
        if settings["enableLiabilityAnalysis"] and not settings["deepseekApiKey"]:
            QMessageBox.warning(parent, "提示", "启用 AI 智能划责前，请先填写 API 密钥。")
            return False
        if settings["enableLiabilityAnalysis"] and not settings["requestUrl"]:
            QMessageBox.warning(parent, "提示", "启用 AI 智能划责前，请先填写请求地址。")
            return False
        if settings["enableLiabilityAnalysis"] and not settings["model"]:
            QMessageBox.warning(parent, "提示", "启用 AI 智能划责前，请先填写模型名称。")
            return False
        if settings["requestUrl"] and not (
            settings["requestUrl"].startswith("http://")
            or settings["requestUrl"].startswith("https://")
        ):
            QMessageBox.warning(parent, "提示", "请求地址必须以 http:// 或 https:// 开头。")
            return False
        return True

    def save_settings(self, parent_widget=None):
        settings = self.collect_settings()
        if not self.validate_settings(settings, parent_widget=parent_widget):
            return None
        self._saved_settings = save_ai_settings(settings)
        return dict(self._saved_settings)

    @property
    def saved_settings(self):
        return dict(self._saved_settings)


class AiSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI连接")
        self.resize(660, 420)
        layout = QVBoxLayout(self)
        self.panel = AiSettingsPanel(self)
        layout.addWidget(self.panel)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_and_accept(self):
        if self.panel.save_settings(parent_widget=self) is None:
            return
        self.accept()

    @property
    def saved_settings(self):
        return self.panel.saved_settings
