import os
import json

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.vehicle_model_settings import (
    DEFAULT_VEHICLE_SPECS,
    DEFAULT_MARKER_SPECS,
    VEHICLE_SPEC_KEYS,
    load_vehicle_model_settings,
    reset_vehicle_model_settings,
    save_as_default_vehicle_model_settings,
    save_vehicle_model_settings,
)
from core.vehicle_presets import STANDARD_VEHICLE_TYPES
from core.marker_presets import STANDARD_MARKER_TYPES
from utils.app_paths import app_path
from utils.scene_model_injection import inject_scene_model_scripts


FIELD_LABELS = {
    "width": "车宽",
    "length": "车长",
    "height": "车高",
    "wheelRadius": "轮半径",
    "wheels": "轮位置",
    "radius": "半径",
    "emissionInterval": "发射间隔(秒)",
}


def preview_html_path():
    return app_path("templates", "vehicle_model_preview.html")


class VehiclePreviewDialog(QDialog):
    """Embedded Three.js single-vehicle preview; prev/next via runJavaScript."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("车辆建模预览")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.resize(720, 760)

        self._web_view = None
        self._index = 0
        self._items = (
            [("vehicle", t) for t in STANDARD_VEHICLE_TYPES]
            + [("marker", t) for t in STANDARD_MARKER_TYPES]
        )
        self._n = len(self._items)
        self._settings = load_vehicle_model_settings()
        self._field_edits = {}
        self._loading_fields = False
        self._web_loaded = False
        self._save_btn = None
        self._reset_btn = None
        self._show_mapping = True

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        path = preview_html_path()

        if not os.path.isfile(path):
            layout.addWidget(QLabel(f"未找到预览文件:\n{path}"))
            btn = QPushButton("关闭")
            btn.clicked.connect(self.accept)
            layout.addWidget(btn)
            return

        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            from PySide6.QtWebEngineWidgets import QWebEngineView

            view = QWebEngineView(self)
            self._web_view = view
            s = view.settings()
            s.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
            )
            s.setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
            )
            view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            view.setMinimumHeight(220)
            view.setMaximumHeight(330)
            view.loadFinished.connect(self._on_web_load_finished)
            # Embeds all 8 vehicle GLB models as base64, which comfortably exceeds
            # QWebEngineView.setHtml()'s hard 2MB content limit (it converts the
            # content to a data: URL and silently fails loadFinished(false) past
            # that size). Writing to a real file and loading it via a file:// URL
            # has no such limit.
            rendered_path = self._write_external_preview(path)
            view.load(QUrl.fromLocalFile(os.path.abspath(rendered_path)))
            layout.addWidget(view, stretch=1)
        except ImportError:
            tip = QLabel(
                "未安装 PySide6-WebEngine，无法内嵌预览。\n"
                "可在本项目目录执行: pip install PySide6-WebEngine -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
                "或点击下方按钮用系统浏览器打开（需联网加载 Three.js CDN）。\n"
                "浏览器地址可追加 ?idx=0 切换车辆和标记物。"
            )
            tip.setWordWrap(True)
            layout.addWidget(tip)
            row = QHBoxLayout()
            open_btn = QPushButton("在浏览器中打开")
            open_btn.clicked.connect(lambda: self._open_external(path))
            row.addWidget(open_btn)
            row.addStretch()
            layout.addLayout(row)

        settings_frame = QFrame()
        settings_frame.setFrameShape(QFrame.Shape.StyledPanel)
        settings_layout = QVBoxLayout(settings_frame)
        settings_layout.setContentsMargins(10, 8, 10, 8)
        settings_layout.setSpacing(8)

        nav = QHBoxLayout()
        nav.setSpacing(14)
        nav_btn_style = """
            QPushButton {
                font-size: 16px;
                font-weight: bold;
                color: #222;
                padding: 10px 22px;
                border-radius: 8px;
                border: 1px solid #8a8a8a;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #ffffff, stop:1 #d3d3d3);
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #f7f7f7, stop:1 #c7d7ee);
            }
            QPushButton:pressed {
                padding-top: 12px;
                padding-bottom: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                            stop:0 #b9c9df, stop:1 #eef3fb);
                border: 1px solid #5f7897;
            }
            QPushButton:disabled {
                color: #888;
                background: #e5e5e5;
                border: 1px solid #c0c0c0;
            }
        """
        self._prev_btn = QPushButton("上一个")
        self._prev_btn.setToolTip("上一台车型")
        self._prev_btn.setMinimumSize(130, 46)
        self._prev_btn.setEnabled(False)
        self._prev_btn.setStyleSheet(nav_btn_style)
        self._prev_btn.clicked.connect(self._go_prev)
        nav.addWidget(self._prev_btn)

        self._name_label = QLabel()
        self._name_label.setAlignment(Qt.AlignCenter)
        self._name_label.setWordWrap(True)
        self._name_label.setStyleSheet("font-size: 14px; color: #333;")
        nav.addWidget(self._name_label, stretch=1)

        self._next_btn = QPushButton("下一个")
        self._next_btn.setToolTip("下一台车型")
        self._next_btn.setMinimumSize(130, 46)
        self._next_btn.setEnabled(False)
        self._next_btn.setStyleSheet(nav_btn_style)
        self._next_btn.clicked.connect(self._go_next)
        nav.addWidget(self._next_btn)

        settings_layout.addLayout(nav)

        self._lane_edit = self._make_number_edit()
        self._lane_edit.textChanged.connect(self._on_fields_changed)
        self._emergency_lane_edit = self._make_number_edit()
        self._emergency_lane_edit.textChanged.connect(self._on_fields_changed)
        self._show_mapping_check = QCheckBox("显示映射")
        self._show_mapping_check.setChecked(True)
        self._show_mapping_check.toggled.connect(self._on_show_mapping_toggled)
        lane_row = QHBoxLayout()
        lane_row.addWidget(QLabel("车道宽"))
        lane_row.addWidget(self._lane_edit, stretch=1)
        lane_row.addWidget(QLabel("应急车道宽"))
        lane_row.addWidget(self._emergency_lane_edit, stretch=1)
        lane_row.addWidget(self._show_mapping_check)
        lane_row.addStretch(1)
        settings_layout.addLayout(lane_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._fields_body = QWidget()
        self._fields_grid = QGridLayout(self._fields_body)
        self._fields_grid.setContentsMargins(0, 0, 0, 0)
        self._fields_grid.setHorizontalSpacing(12)
        self._fields_grid.setVerticalSpacing(6)
        self._scroll.setWidget(self._fields_body)
        settings_layout.addWidget(self._scroll, stretch=1)

        action_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        self._save_btn = save_btn
        save_btn.clicked.connect(self._save_settings)
        reset_btn = QPushButton("恢复默认")
        self._reset_btn = reset_btn
        reset_btn.clicked.connect(self._reset_defaults)
        set_default_btn = QPushButton("设为默认")
        self._set_default_btn = set_default_btn
        set_default_btn.clicked.connect(self._set_as_defaults)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        action_row.addWidget(reset_btn)
        action_row.addWidget(set_default_btn)
        action_row.addStretch(1)
        action_row.addWidget(save_btn)
        action_row.addWidget(close_btn)
        settings_layout.addLayout(action_row)

        layout.addWidget(settings_frame, stretch=1)

        self._update_label_only()
        self._load_current_fields()
        self._set_preview_controls_enabled(False)

    def _update_label_only(self):
        if self._n <= 0:
            self._name_label.setText("")
            return
        _, name = self._items[self._index]
        self._name_label.setText(f"{name}\n{self._index + 1} / {self._n}")

    def _on_web_load_finished(self, ok):
        self._web_loaded = bool(ok)
        self._set_preview_controls_enabled(bool(ok and self._web_view))
        if ok and self._web_view:
            self._send_current_preview_update()
        self._update_label_only()

    def _apply_index(self, idx):
        if not self._web_loaded:
            return
        self._index = ((idx % self._n) + self._n) % self._n
        self._update_label_only()
        self._load_current_fields()
        self._send_current_preview_update()

    def _go_prev(self):
        self._apply_index(self._index - 1)

    def _go_next(self):
        self._apply_index(self._index + 1)

    @staticmethod
    def _make_number_edit():
        edit = QLineEdit()
        validator = QDoubleValidator(0.001, 1000.0, 3, edit)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        edit.setValidator(validator)
        edit.setMaximumWidth(92)
        edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        return edit

    @staticmethod
    def _format_number(value):
        return f"{float(value):.3f}".rstrip("0").rstrip(".")

    def _current_vehicle_type(self):
        return self._items[self._index][1]

    def _current_item_kind(self):
        return self._items[self._index][0]

    @staticmethod
    def _visible_keys(spec):
        if spec.get("kind") == "scatteredDebris":
            return [k for k in ("radius", "emissionInterval") if k in spec]
        if spec.get("kind") == "impactSphere":
            return [k for k in ("radius", "height", "emissionInterval") if k in spec]
        if spec.get("kind") in {"trafficCone", "adult", "guideSign"}:
            return [k for k in ("length", "width", "height") if k in spec]
        # All vehicle kinds: unified LWH + wheel radius + wheel Z positions.
        if "wheelRadius" in spec or "wheels" in spec:
            return [k for k in VEHICLE_SPEC_KEYS if k in spec]
        return [k for k in spec if k != "kind"]

    def _clear_fields_grid(self):
        while self._fields_grid.count():
            item = self._fields_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _set_preview_controls_enabled(self, enabled):
        if hasattr(self, "_prev_btn"):
            self._prev_btn.setEnabled(enabled)
        if hasattr(self, "_next_btn"):
            self._next_btn.setEnabled(enabled)
        if hasattr(self, "_lane_edit"):
            self._lane_edit.setEnabled(enabled)
        if hasattr(self, "_emergency_lane_edit"):
            self._emergency_lane_edit.setEnabled(enabled)
        if hasattr(self, "_show_mapping_check"):
            self._show_mapping_check.setEnabled(enabled)
        for edit in self._field_edits.values():
            edit.setEnabled(enabled)
        if self._save_btn is not None:
            self._save_btn.setEnabled(enabled)
        if self._reset_btn is not None:
            self._reset_btn.setEnabled(enabled)
        if getattr(self, "_set_default_btn", None) is not None:
            self._set_default_btn.setEnabled(enabled)

    def _load_current_fields(self):
        item_type = self._current_vehicle_type()
        item_kind = self._current_item_kind()
        spec_group = "markerSpecs" if item_kind == "marker" else "vehicleSpecs"
        default_group = DEFAULT_MARKER_SPECS if item_kind == "marker" else DEFAULT_VEHICLE_SPECS
        spec = self._settings[spec_group][item_type]

        self._loading_fields = True
        self._field_edits = {}
        self._clear_fields_grid()
        self._lane_edit.setText(self._format_number(self._settings["laneWidth"]))
        self._emergency_lane_edit.setText(
            self._format_number(self._settings["emergencyLaneWidth"])
        )
        self._show_mapping_check.setChecked(self._show_mapping)

        keys = self._visible_keys(default_group[item_type])
        for idx, key in enumerate(keys):
            row = idx // 2
            col = (idx % 2) * 2
            label = QLabel(FIELD_LABELS.get(key, key))
            if key == "wheels":
                edit = QLineEdit()
                edit.setText(", ".join(self._format_number(v) for v in spec.get(key, [])))
            else:
                edit = self._make_number_edit()
                edit.setText(self._format_number(spec[key]))
            edit.textChanged.connect(self._on_fields_changed)
            edit.setEnabled(self._web_loaded)
            self._field_edits[key] = edit
            self._fields_grid.addWidget(label, row, col)
            self._fields_grid.addWidget(edit, row, col + 1)

        self._fields_grid.setColumnStretch(1, 1)
        self._fields_grid.setColumnStretch(3, 1)
        self._loading_fields = False
        self._set_preview_controls_enabled(self._web_loaded)

    def _apply_fields_to_settings(self):
        item_type = self._current_vehicle_type()
        item_kind = self._current_item_kind()
        spec_group = "markerSpecs" if item_kind == "marker" else "vehicleSpecs"
        spec = self._settings[spec_group][item_type]
        try:
            lane_width = float(self._lane_edit.text())
            emergency_lane_width = float(self._emergency_lane_edit.text())
        except ValueError:
            return False
        if lane_width <= 0 or emergency_lane_width <= 0:
            return False
        self._settings["laneWidth"] = lane_width
        self._settings["emergencyLaneWidth"] = emergency_lane_width
        self._show_mapping = self._show_mapping_check.isChecked()

        for key, edit in self._field_edits.items():
            text = edit.text().strip()
            if key == "wheels":
                wheels = []
                for item in text.replace("，", ",").split(","):
                    item = item.strip()
                    if item:
                        wheels.append(float(item))
                if wheels:
                    spec[key] = wheels
                continue
            value = float(text)
            if value <= 0:
                return False
            spec[key] = value
        return True

    def _on_fields_changed(self):
        if self._loading_fields or not self._web_loaded:
            return
        try:
            ok = self._apply_fields_to_settings()
        except ValueError:
            return
        if ok:
            self._send_current_preview_update()

    def _on_show_mapping_toggled(self, checked):
        self._show_mapping = bool(checked)
        if self._loading_fields or not self._web_loaded:
            return
        if self._web_view:
            js = (
                "window.setShowVehicleMapping && "
                f"window.setShowVehicleMapping({str(bool(checked)).lower()})"
            )
            self._web_view.page().runJavaScript(js)

    def _send_current_preview_update(self):
        if not (self._web_view and self._web_loaded):
            return
        vehicle_type = self._current_vehicle_type()
        spec_group = (
            "markerSpecs" if self._current_item_kind() == "marker" else "vehicleSpecs"
        )
        spec_json = json.dumps(
            self._settings[spec_group][vehicle_type], ensure_ascii=False
        )
        type_json = json.dumps(vehicle_type, ensure_ascii=False)
        lane_width = float(self._settings["laneWidth"])
        emergency_lane_width = float(self._settings["emergencyLaneWidth"])
        show_mapping = "true" if self._show_mapping else "false"
        # outlineWidth kept for marker edge scripts; UI no longer edits it.
        outline_width = float(self._settings.get("outlineWidth", 2.5))
        js = (
            "window.updateVehicleSpecs && "
            f"window.updateVehicleSpecs({type_json}, {spec_json}, {lane_width}, "
            f"{emergency_lane_width}, {outline_width}, {self._index}, {show_mapping})"
        )
        self._web_view.page().runJavaScript(js)

    def _save_settings(self):
        try:
            if not self._apply_fields_to_settings():
                QMessageBox.warning(self, "保存失败", "请输入大于 0 的有效数值。")
                return
            save_vehicle_model_settings(self._settings)
        except ValueError:
            QMessageBox.warning(self, "保存失败", "轮位置必须是数字，并用逗号分隔。")
            return
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"无法写入设置文件: {exc}")
            return
        QMessageBox.information(self, "保存成功", "车辆建模设置已保存。")

    def _reset_defaults(self):
        self._settings = reset_vehicle_model_settings()
        self._show_mapping = True
        self._load_current_fields()
        self._send_current_preview_update()
        QMessageBox.information(
            self,
            "已恢复默认",
            "已恢复默认车辆建模尺寸、车道宽和应急车道宽。",
        )

    def _set_as_defaults(self):
        try:
            if not self._apply_fields_to_settings():
                QMessageBox.warning(self, "设为默认失败", "请输入大于 0 的有效数值。")
                return
            self._settings = save_as_default_vehicle_model_settings(self._settings)
        except ValueError:
            QMessageBox.warning(self, "设为默认失败", "轮位置必须是数字，并用逗号分隔。")
            return
        except OSError as exc:
            QMessageBox.critical(self, "设为默认失败", f"无法写入默认设置文件: {exc}")
            return
        QMessageBox.information(
            self,
            "已设为默认",
            "当前建模尺寸、轮位置、车道宽和应急车道宽已设为默认。"
            "之后点击“恢复默认”将回到这组数值。",
        )

    @staticmethod
    def _render_preview_html(path):
        with open(path, "r", encoding="utf-8") as f:
            return inject_scene_model_scripts(f.read())

    @staticmethod
    def _write_external_preview(path):
        rendered = VehiclePreviewDialog._render_preview_html(path)
        out_dir = app_path("history")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "vehicle_model_preview.html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        return out_path

    @staticmethod
    def _open_external(path):
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.abspath(VehiclePreviewDialog._write_external_preview(path)))
        )


def open_vehicle_preview(parent=None):
    VehiclePreviewDialog(parent).exec()
