from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
import os

from utils.app_paths import app_path


class ExampleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("上传提示")
        self.resize(820, 460)
        self.setWindowModality(Qt.ApplicationModal)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        tip = QLabel("请确认图像为俯拍后再上传。以下为错误与正确示例：")
        tip.setWordWrap(True)
        tip.setAlignment(Qt.AlignCenter)
        tip.setStyleSheet("font-size: 13px; color: #333;")
        root.addWidget(tip)

        layout = QHBoxLayout()

        left_layout = QVBoxLayout()
        left_img = QLabel()
        left_img.setAlignment(Qt.AlignCenter)
        example1 = app_path("Example1.jpeg")
        if os.path.exists(example1):
            pixmap = QPixmap(example1).scaled(
                350, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            left_img.setPixmap(pixmap)
        elif os.path.exists("Example1.jpeg"):
            pixmap = QPixmap("Example1.jpeg").scaled(
                350, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            left_img.setPixmap(pixmap)
        else:
            left_img.setText("找不到 Example1.jpeg")

        left_text = QLabel("错误图片示例")
        left_text.setAlignment(Qt.AlignCenter)
        left_text.setStyleSheet("color: red; font-size: 16px; font-weight: bold;")

        left_layout.addWidget(left_img)
        left_layout.addWidget(left_text)

        right_layout = QVBoxLayout()
        right_img = QLabel()
        right_img.setAlignment(Qt.AlignCenter)
        example2 = app_path("Example2.png")
        if os.path.exists(example2):
            pixmap = QPixmap(example2).scaled(
                350, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            right_img.setPixmap(pixmap)
        elif os.path.exists("Example2.png"):
            pixmap = QPixmap("Example2.png").scaled(
                350, 350, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            right_img.setPixmap(pixmap)
        else:
            right_img.setText("找不到 Example2.png")

        right_text = QLabel("正确图片示例")
        right_text.setAlignment(Qt.AlignCenter)
        right_text.setStyleSheet("color: green; font-size: 16px; font-weight: bold;")

        right_layout.addWidget(right_img)
        right_layout.addWidget(right_text)

        layout.addLayout(left_layout)
        layout.addLayout(right_layout)
        root.addLayout(layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self
        )
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if ok_btn is not None:
            ok_btn.setText("确认")
            ok_btn.setAutoDefault(False)
            ok_btn.setDefault(True)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
            cancel_btn.setAutoDefault(False)
            cancel_btn.setDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
