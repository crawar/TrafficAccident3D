from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)


class _DragBar(QFrame):
    """Title bar strip that lets the user drag the floating panel around."""

    def __init__(self, panel, title):
        super().__init__(panel)
        self._panel = panel
        self._drag_offset = None
        self.setCursor(Qt.SizeAllCursor)
        self.setStyleSheet(
            "background-color: #37474f; border-top-left-radius: 6px; border-top-right-radius: 6px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        label = QLabel(title)
        label.setStyleSheet("color: white; font-weight: bold;")
        layout.addWidget(label)
        layout.addStretch(1)
        hint = QLabel("按住拖动")
        hint.setStyleSheet("color: #cfd8dc;")
        layout.addWidget(hint)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self._panel.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self._panel.move(event.globalPos() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = None
        super().mouseReleaseEvent(event)


class AccidentBriefPanel(QFrame):
    """Draggable floating panel for entering a brief accident narrative.

    Not a modal dialog: it floats above the image viewer so the user can drag
    it aside instead of it blocking the recognition image area.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            "QFrame { background-color: #fafafa; border: 1px solid #37474f; border-radius: 6px; }"
        )
        self.resize(380, 260)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(_DragBar(self, "简要事故案情"))

        body = QVBoxLayout()
        body.setContentsMargins(10, 8, 10, 10)

        tip = QLabel(
            "该案情会作为提示词发送给 AI 辅助责任分析，可拖动本窗口标题栏以免遮盖识别图像。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #555555;")
        body.addWidget(tip)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setStyleSheet(
            "QPlainTextEdit {"
            " color: #111111;"
            " background-color: #ffffff;"
            " border: 1px solid #cfd8dc;"
            " border-radius: 4px;"
            " selection-background-color: #90caf9;"
            " selection-color: #111111;"
            "}"
        )
        self.text_edit.setPlaceholderText(
            "请输入简要事故案情，建议用车辆ID指代对应车辆，例如：\n"
            "A1沿快车道直行时，B2从应急车道逆向变道进入快车道，两车发生碰撞。"
        )
        body.addWidget(self.text_edit, stretch=1)

        layout.addLayout(body)

    def text(self):
        return self.text_edit.toPlainText()

    def set_text(self, text):
        self.text_edit.setPlainText(text or "")
