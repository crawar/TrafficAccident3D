from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from utils.ai_settings import (
    DEFAULT_DEEPSEEK_BASE_URL,
    load_ai_settings,
    probe_ai_connection,
    save_ai_settings,
)

DEEPSEEK_API_DOCS_URL = "https://api-docs.deepseek.com/zh-cn/"


class ConnectionTestThread(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = dict(settings or {})

    def run(self):
        try:
            self.finished_ok.emit(probe_ai_connection(self.settings))
        except Exception as exc:
            self.failed.emit(str(exc))


class AiSettingsPanel(QWidget):
    """Reusable AI connection form (used by system settings tab / dialog)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_settings = load_ai_settings()
        self._test_thread = None
        self._init_ui()
        self._load_form()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tip = QLabel(
            "请按 DeepSeek 开发文档的 OpenAI 兼容参数填写："
            "api_key、base_url（https://api.deepseek.com）、model。"
            "不要填写 Anthropic 的 base_url，也不要带 /chat/completions。"
            "「启用AI」是总开关，关闭后责任分析、事故复核、知识库精炼等都不会请求 AI。"
            "（自定义提示词请在「系统设置 → AI提示词」中设置。）"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        docs_row = QHBoxLayout()
        self.docs_btn = QPushButton("查看 DeepSeek 开发文档")
        self.docs_btn.setAutoDefault(False)
        self.docs_btn.setDefault(False)
        self.docs_btn.setToolTip(DEEPSEEK_API_DOCS_URL)
        self.docs_btn.clicked.connect(self._open_deepseek_docs)
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setAutoDefault(False)
        self.test_btn.setDefault(False)
        self.test_btn.setToolTip("用当前填写的 api_key、base_url、model 发送一次短请求。")
        self.test_btn.clicked.connect(self._on_test_connection)
        docs_row.addWidget(self.docs_btn)
        docs_row.addWidget(self.test_btn)
        docs_row.addStretch(1)
        layout.addLayout(docs_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setSpacing(12)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("文档中的 api_key")
        form.addRow("API密钥 (api_key)", self.api_key_edit)

        self.request_url_edit = QLineEdit()
        self.request_url_edit.setPlaceholderText(DEFAULT_DEEPSEEK_BASE_URL)
        self.request_url_edit.setToolTip(
            "请填写文档中的 base_url (OpenAI)，例如 %s" % DEFAULT_DEEPSEEK_BASE_URL
        )
        form.addRow("请求地址 (base_url)", self.request_url_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("deepseek-v4-pro 或 deepseek-v4-flash")
        form.addRow("模型名称 (model)", self.model_edit)

        self.thinking_combo = QComboBox()
        self.thinking_combo.addItem("无", "none")
        self.thinking_combo.addItem("低", "low")
        self.thinking_combo.addItem("中", "medium")
        self.thinking_combo.addItem("高", "high")
        self.thinking_combo.setToolTip(
            "无：关闭思考，直接回答。"
            "低 / 中 / 高：开启思考，并设置推理强度。"
        )
        form.addRow("思考模式", self.thinking_combo)

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

        self.enable_checkbox = QCheckBox("启用AI")
        self.enable_checkbox.setToolTip(
            "总开关。关闭后责任分析、事故复核、知识库精炼、专家发言都不会请求 AI。"
        )
        form.addRow("", self.enable_checkbox)
        layout.addLayout(form)

        self.enable_checkbox.toggled.connect(self._apply_enable_state)

    @staticmethod
    def _open_deepseek_docs():
        QDesktopServices.openUrl(QUrl(DEEPSEEK_API_DOCS_URL))

    def _apply_enable_state(self):
        on = self.enable_checkbox.isChecked()
        testing = self._test_thread is not None and self._test_thread.isRunning()
        for w in (
            self.api_key_edit,
            self.request_url_edit,
            self.model_edit,
            self.thinking_combo,
            self.temperature_spin,
            self.timeout_spin,
        ):
            w.setEnabled(on and not testing)
        self.test_btn.setEnabled(on and not testing)

    def _load_form(self):
        self.api_key_edit.setText(self._saved_settings.get("deepseekApiKey", ""))
        self.request_url_edit.setText(self._saved_settings.get("requestUrl", ""))
        self.model_edit.setText(self._saved_settings.get("model", ""))
        self._set_combo_value(
            self.thinking_combo,
            self._saved_settings.get("thinkingLevel", "high"),
        )
        self.temperature_spin.setValue(
            float(self._saved_settings.get("temperature", 0.1))
        )
        self.timeout_spin.setValue(
            int(self._saved_settings.get("requestTimeoutSec", 120))
        )
        self.enable_checkbox.setChecked(bool(self._saved_settings.get("enableAI", False)))
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
            "thinkingLevel": self.thinking_combo.currentData(),
            "temperature": self.temperature_spin.value(),
            "requestTimeoutSec": self.timeout_spin.value(),
            "enableAI": self.enable_checkbox.isChecked(),
        }

    def validate_settings(self, settings, parent_widget=None, require_connection=False):
        parent = parent_widget or self
        need_fields = bool(settings["enableAI"] or require_connection)
        if need_fields and not settings["deepseekApiKey"]:
            QMessageBox.warning(
                parent, "提示", "启用 AI 前，请先填写 API 密钥 (api_key)。"
            )
            return False
        if need_fields and not settings["requestUrl"]:
            QMessageBox.warning(
                parent, "提示", "启用 AI 前，请先填写请求地址 (base_url)。"
            )
            return False
        if need_fields and not settings["model"]:
            QMessageBox.warning(
                parent, "提示", "启用 AI 前，请先填写模型名称 (model)。"
            )
            return False
        if settings["requestUrl"] and not (
            settings["requestUrl"].startswith("http://")
            or settings["requestUrl"].startswith("https://")
        ):
            QMessageBox.warning(
                parent, "提示", "请求地址 (base_url) 必须以 http:// 或 https:// 开头。"
            )
            return False
        url_lower = settings["requestUrl"].rstrip("/").lower()
        if url_lower.endswith("/anthropic") or "/anthropic/" in url_lower:
            QMessageBox.warning(
                parent,
                "提示",
                "请填写文档中的 OpenAI base_url（https://api.deepseek.com），"
                "不要填写 Anthropic 的地址。",
            )
            return False
        if "/chat/completions" in url_lower:
            QMessageBox.warning(
                parent,
                "提示",
                "请填写文档中的 base_url（https://api.deepseek.com），"
                "不要带 /chat/completions。程序会自动补上该路径。",
            )
            return False
        return True

    def _on_test_connection(self):
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        settings = self.collect_settings()
        if not self.validate_settings(settings, require_connection=True):
            return
        self._test_thread = ConnectionTestThread(settings, parent=self)
        self._test_thread.finished_ok.connect(self._on_test_ok)
        self._test_thread.failed.connect(self._on_test_failed)
        self._test_thread.finished.connect(self._on_test_thread_finished)
        self.test_btn.setText("测试中…")
        self._apply_enable_state()
        self._test_thread.start()

    def _on_test_ok(self, result):
        info = result if isinstance(result, dict) else {}
        lines = [
            "连接成功。",
            "实际请求：%s" % (info.get("url") or ""),
            "模型：%s" % (info.get("model") or ""),
        ]
        preview = str(info.get("preview") or "").strip()
        if preview:
            lines.append("回复预览：%s" % preview)
        QMessageBox.information(self, "测试连接", "\n".join(lines))

    def _on_test_failed(self, message):
        QMessageBox.warning(self, "测试连接失败", str(message or "未知错误"))

    def _on_test_thread_finished(self):
        self.test_btn.setText("测试连接")
        self._test_thread = None
        self._apply_enable_state()

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
        self.resize(660, 460)
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
