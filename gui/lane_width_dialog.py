from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.vehicle_model_settings import (
    DEFAULT_EMERGENCY_LANE_WIDTH,
    DEFAULT_LANE_WIDTH,
    load_vehicle_model_settings,
)


def _safe_dialog_parent(parent):
    """Avoid nesting under ResultWindow so child accept does not close it."""
    if parent is None:
        return None
    host = parent
    top = parent.window() if hasattr(parent, "window") else parent
    if isinstance(top, QDialog):
        host = top.parentWidget()
    elif isinstance(parent, QDialog):
        host = parent.parentWidget()
    while host is not None and isinstance(host, QDialog):
        host = host.parentWidget()
    return host


class LaneWidthDialog(QDialog):
    """Per-image lane / emergency-lane width editor (road-line mode).

    Settings apply only to the current image's annotation cache and never write
    the modeling-preview global defaults. Accepting clears all planned lanes so
    the user must re-plan them with the new spacing.
    """

    def __init__(self, lane_width=None, emergency_lane_width=None, parent=None):
        super().__init__(_safe_dialog_parent(parent))
        self.setWindowTitle("本图车道宽设置")
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(420)
        self._result = None

        settings = load_vehicle_model_settings()
        initial_lane = (
            float(lane_width)
            if lane_width is not None
            else float(settings.get("laneWidth", DEFAULT_LANE_WIDTH))
        )
        initial_emergency = (
            float(emergency_lane_width)
            if emergency_lane_width is not None
            else float(
                settings.get("emergencyLaneWidth", DEFAULT_EMERGENCY_LANE_WIDTH)
            )
        )

        layout = QVBoxLayout(self)
        tip = QLabel(
            "重设本图的车道宽、应急车道宽，不会影响建模预览中的通用设置。"
            "设置完毕后需要重新规划车道线；确认后将删除本图已规划的全部车道线。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #444;")
        layout.addWidget(tip)

        form = QFormLayout()
        self._lane_edit = self._make_number_edit(initial_lane)
        self._emergency_edit = self._make_number_edit(initial_emergency)
        form.addRow("车道宽 (m):", self._lane_edit)
        form.addRow("应急车道宽 (m):", self._emergency_edit)
        layout.addLayout(form)

        row = QHBoxLayout()
        row.addStretch(1)
        ok_btn = QPushButton("确定")
        ok_btn.setAutoDefault(False)
        ok_btn.setDefault(False)
        ok_btn.clicked.connect(self._accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)
        row.addWidget(ok_btn)
        row.addWidget(cancel_btn)
        layout.addLayout(row)

    @staticmethod
    def _make_number_edit(value):
        edit = QLineEdit()
        validator = QDoubleValidator(0.001, 1000.0, 3, edit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        edit.setValidator(validator)
        edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        text = f"{float(value):.3f}".rstrip("0").rstrip(".")
        edit.setText(text)
        return edit

    def _accept(self):
        try:
            lane_width = float(self._lane_edit.text())
            emergency_width = float(self._emergency_edit.text())
        except ValueError:
            QMessageBox.warning(self, "无法保存", "请输入有效数值。")
            return
        if lane_width <= 0 or emergency_width <= 0:
            QMessageBox.warning(self, "无法保存", "车道宽与应急车道宽必须大于 0。")
            return
        self._result = (lane_width, emergency_width)
        self.accept()

    @property
    def result_widths(self):
        """(lane_width, emergency_lane_width) or None if cancelled."""
        return self._result
