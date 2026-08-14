from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils.ai_prompt import load_ai_prompt, save_ai_prompt


class AiPromptPanel(QWidget):
    """Reusable AI prompt form (used by system settings tab / dialog)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._saved_prompt = load_ai_prompt()
        self._init_ui()
        self._load_form()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        tip = QLabel(
            "在这里填写的内容会以「追加约束」的形式附加到内置责任分析提示词的要求列表末尾，"
            "不会替换内置提示词。留空表示不追加任何额外约束。\n"
            "示例：优先考虑后车未保持安全距离的责任；如无法判断则统一标记为责任待定。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "在此输入要追加给 AI 的额外责任分析约束（留空则不追加）。"
        )
        self.prompt_edit.setMinimumHeight(260)
        layout.addWidget(self.prompt_edit)

    def _load_form(self):
        self.prompt_edit.setPlainText(self._saved_prompt)

    def save_prompt(self):
        self._saved_prompt = save_ai_prompt(self.prompt_edit.toPlainText())
        return self._saved_prompt

    @property
    def saved_prompt(self):
        return self._saved_prompt


class AiPromptDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI提示词")
        self.resize(640, 460)
        layout = QVBoxLayout(self)
        self.panel = AiPromptPanel(self)
        layout.addWidget(self.panel)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, parent=self
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_and_accept(self):
        self.panel.save_prompt()
        self.accept()

    @property
    def saved_prompt(self):
        return self.panel.saved_prompt
