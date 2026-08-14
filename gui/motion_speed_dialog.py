from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)


class MotionSpeedDialog(QDialog):
    def __init__(self, vehicle_id="", speed_kmh=80.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置速度")
        self.setModal(True)
        self.result_speed_kmh = None

        layout = QVBoxLayout(self)
        tip = QLabel(
            f"为车辆 {vehicle_id or ''} 设置行驶速度（公里/小时）。\n"
            "该速度用于多车相对快慢；实际 3D 播放会再乘以系统「动画设置」中的执行速度。"
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(1.0, 300.0)
        self.speed_spin.setDecimals(1)
        self.speed_spin.setSingleStep(5.0)
        self.speed_spin.setSuffix(" km/h")
        self.speed_spin.setValue(float(speed_kmh) if speed_kmh else 80.0)
        form.addRow("车速", self.speed_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if ok_btn is not None:
            ok_btn.setText("确定")
            ok_btn.setAutoDefault(False)
            ok_btn.setDefault(False)
        if cancel_btn is not None:
            cancel_btn.setText("取消")
            cancel_btn.setAutoDefault(False)
            cancel_btn.setDefault(False)
        layout.addWidget(buttons)

    def _on_accept(self):
        self.result_speed_kmh = float(self.speed_spin.value())
        self.accept()
