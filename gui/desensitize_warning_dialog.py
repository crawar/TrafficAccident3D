# -*- coding: utf-8 -*-
"""Shared countdown warning before uploading documents that may contain personal data."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from gui.app_styles import PRIMARY_BTN_STYLE, PRIMARY_CONTROL_H


COUNTDOWN_SEC = 5
WARNING_TEXT = (
    "请确保您的文件已经经过脱敏处理，保障信息安全。"
    "如果没有，可以在主窗口“离线脱敏”功能中先脱敏"
)


class DesensitizeWarningDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("信息安全提示")
        self.setModal(True)
        self.setMinimumWidth(460)
        self.setWindowFlags(
            Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint
        )
        self.setWindowModality(Qt.ApplicationModal)
        self._left = COUNTDOWN_SEC
        self._allow_close = False
        self.setStyleSheet(
            """
            QDialog {
                background-color: #0f172a;
                color: #e2e8f0;
            }
            QDialog QLabel {
                background: transparent;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(18)

        warning = QLabel(WARNING_TEXT)
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color: #fecaca; font-size: 15px; font-weight: 700; line-height: 140%;"
        )
        layout.addWidget(warning)

        self.ok_btn = QPushButton("确定（%d）" % self._left)
        self.ok_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        self.ok_btn.setMinimumHeight(PRIMARY_CONTROL_H)
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setEnabled(False)
        self.ok_btn.setAutoDefault(False)
        self.ok_btn.setDefault(False)
        self.ok_btn.clicked.connect(self._on_confirm)
        layout.addWidget(self.ok_btn)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(1000)

    def _on_tick(self):
        self._left -= 1
        if self._left <= 0:
            self._timer.stop()
            self.ok_btn.setEnabled(True)
            self.ok_btn.setText("确定")
            return
        self.ok_btn.setText("确定（%d）" % self._left)

    def _on_confirm(self):
        self._allow_close = True
        if self._timer.isActive():
            self._timer.stop()
        self.accept()

    def reject(self):
        return

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Escape, Qt.Key_Cancel):
            event.ignore()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._allow_close:
            event.ignore()
            return
        if self._timer.isActive():
            self._timer.stop()
        super().closeEvent(event)
