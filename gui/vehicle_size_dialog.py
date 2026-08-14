import copy
import json
import os

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.vehicle_model_settings import (
    DEFAULT_VEHICLE_SPECS,
    VEHICLE_SPEC_KEYS,
    load_vehicle_model_settings,
)
from core.vehicle_presets import STANDARD_VEHICLE_TYPES
from gui.vehicle_preview_dialog import FIELD_LABELS, VehiclePreviewDialog, preview_html_path


def _default_spec_for_type(preset_type):
    settings = load_vehicle_model_settings()
    base = settings.get("vehicleSpecs", {}).get(preset_type)
    if not isinstance(base, dict):
        base = DEFAULT_VEHICLE_SPECS.get(preset_type, DEFAULT_VEHICLE_SPECS["小客车"])
    return {
        "width": float(base.get("width", 1.8) or 1.8),
        "length": float(base.get("length", 4.3) or 4.3),
        "height": float(base.get("height", 1.6) or 1.6),
        "wheelRadius": float(base.get("wheelRadius", 0.3) or 0.3),
        "wheels": [float(v) for v in (base.get("wheels") or [1.25, -1.25])],
    }


def _merge_custom_size(preset_type, custom_size):
    merged = _default_spec_for_type(preset_type)
    if not isinstance(custom_size, dict):
        return merged
    for key in ("width", "length", "height", "wheelRadius"):
        try:
            value = float(custom_size.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            merged[key] = value
    wheels = custom_size.get("wheels")
    if isinstance(wheels, list) and wheels:
        parsed = []
        for item in wheels:
            try:
                parsed.append(float(item))
            except (TypeError, ValueError):
                continue
        if parsed:
            merged["wheels"] = parsed
    return merged


def _safe_dialog_parent(parent):
    """Return a parent that will not nest this dialog under another QDialog.

    ResultWindow is itself a QDialog shown with exec(). Nesting another
    QDialog (especially one with QWebEngineView) under it can finish the
    parent's event loop when the child closes, making the editor disappear.
    """
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


class VehicleSizeDialog(QDialog):
    """Per-vehicle size editor with live Three.js preview.

    Layout mirrors the modeling preview (preview on top, fields below), but
    omits lane / emergency-lane widths. Values are temporary for this image's
    vehicle instance and travel with the annotation cache via ``custom_size``.
    """

    def __init__(
        self,
        vehicle_id,
        preset_type,
        custom_size=None,
        parent=None,
        body_color=None,
        cargo_color=None,
    ):
        super().__init__(_safe_dialog_parent(parent))
        self.setWindowTitle(f"调整尺寸 - {vehicle_id or '未编号'}")
        self.setWindowModality(Qt.ApplicationModal)
        self.setWindowFlags(
            Qt.Dialog
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowCloseButtonHint
        )
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(720, 760)

        self._preset_type = preset_type if preset_type in STANDARD_VEHICLE_TYPES else "小客车"
        self._default_spec = _default_spec_for_type(self._preset_type)
        self._spec = _merge_custom_size(self._preset_type, custom_size)
        self._result_size = None
        self._reset_requested = False
        self._body_color = body_color
        self._cargo_color = cargo_color

        self._web_view = None
        self._web_loaded = False
        self._loading_fields = False
        self._field_edits = {}
        self._show_mapping = True
        self._preview_index = STANDARD_VEHICLE_TYPES.index(self._preset_type)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        tip = QLabel(
            f"标准车型「{self._preset_type}」——以下设置仅针对本图的这一台车，"
            "会随识别缓存保存，不会改动建模预览中的通用设置。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #444;")
        layout.addWidget(tip)

        path = preview_html_path()
        if not os.path.isfile(path):
            layout.addWidget(QLabel(f"未找到预览文件:\n{path}"))
        else:
            try:
                from PySide6.QtWebEngineCore import QWebEngineSettings
                from PySide6.QtWebEngineWidgets import QWebEngineView

                view = QWebEngineView(self)
                self._web_view = view
                s = view.settings()
                s.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
                    True,
                )
                s.setAttribute(
                    QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls,
                    True,
                )
                view.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
                )
                view.setMinimumHeight(220)
                view.setMaximumHeight(330)
                view.loadFinished.connect(self._on_web_load_finished)
                rendered_path = VehiclePreviewDialog._write_external_preview(path)
                view.load(QUrl.fromLocalFile(os.path.abspath(rendered_path)))
                layout.addWidget(view, stretch=1)
            except ImportError:
                tip_web = QLabel(
                    "未安装 PySide6-WebEngine，无法内嵌预览。仍可调整下方尺寸数值。"
                )
                tip_web.setWordWrap(True)
                layout.addWidget(tip_web)

        settings_frame = QFrame()
        settings_frame.setFrameShape(QFrame.Shape.StyledPanel)
        settings_layout = QVBoxLayout(settings_frame)
        settings_layout.setContentsMargins(10, 8, 10, 8)
        settings_layout.setSpacing(8)

        name_row = QHBoxLayout()
        name_label = QLabel(self._preset_type)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 14px; color: #333; font-weight: bold;")
        name_row.addWidget(name_label, stretch=1)
        settings_layout.addLayout(name_row)

        mapping_row = QHBoxLayout()
        self._show_mapping_check = QCheckBox("显示映射")
        self._show_mapping_check.setChecked(True)
        self._show_mapping_check.toggled.connect(self._on_show_mapping_toggled)
        mapping_row.addWidget(self._show_mapping_check)
        mapping_row.addStretch(1)
        settings_layout.addLayout(mapping_row)

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
        reset_btn = QPushButton("恢复默认")
        reset_btn.setAutoDefault(False)
        reset_btn.setDefault(False)
        reset_btn.clicked.connect(self._reset_to_default)
        ok_btn = QPushButton("确定")
        ok_btn.setAutoDefault(False)
        ok_btn.setDefault(False)
        ok_btn.clicked.connect(self._accept_custom)
        cancel_btn = QPushButton("取消")
        cancel_btn.setAutoDefault(False)
        cancel_btn.setDefault(False)
        cancel_btn.clicked.connect(self.reject)
        action_row.addWidget(reset_btn)
        action_row.addStretch(1)
        action_row.addWidget(ok_btn)
        action_row.addWidget(cancel_btn)
        settings_layout.addLayout(action_row)

        layout.addWidget(settings_frame, stretch=1)
        self._load_fields()
        self._set_controls_enabled(False)

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

    def _load_fields(self):
        self._loading_fields = True
        self._field_edits = {}
        while self._fields_grid.count():
            item = self._fields_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        keys = [k for k in VEHICLE_SPEC_KEYS if k in self._default_spec]
        for idx, key in enumerate(keys):
            row = idx // 2
            col = (idx % 2) * 2
            label = QLabel(FIELD_LABELS.get(key, key))
            if key == "wheels":
                edit = QLineEdit()
                edit.setText(
                    ", ".join(self._format_number(v) for v in self._spec.get(key, []))
                )
            else:
                edit = self._make_number_edit()
                edit.setText(self._format_number(self._spec[key]))
            edit.textChanged.connect(self._on_fields_changed)
            self._field_edits[key] = edit
            self._fields_grid.addWidget(label, row, col)
            self._fields_grid.addWidget(edit, row, col + 1)

        self._fields_grid.setColumnStretch(1, 1)
        self._fields_grid.setColumnStretch(3, 1)
        self._loading_fields = False

    def _set_controls_enabled(self, enabled):
        self._show_mapping_check.setEnabled(enabled or self._web_view is None)
        for edit in self._field_edits.values():
            edit.setEnabled(True)

    def _apply_fields_to_spec(self):
        spec = copy.deepcopy(self._spec)
        for key, edit in self._field_edits.items():
            text = edit.text().strip()
            if key == "wheels":
                wheels = []
                for item in text.replace("，", ",").split(","):
                    item = item.strip()
                    if item:
                        wheels.append(float(item))
                if not wheels:
                    return False
                spec[key] = wheels
                continue
            value = float(text)
            if value <= 0:
                return False
            spec[key] = value
        self._spec = spec
        return True

    def _on_fields_changed(self):
        if self._loading_fields:
            return
        try:
            ok = self._apply_fields_to_spec()
        except ValueError:
            return
        if ok:
            self._send_preview_update()

    def _on_show_mapping_toggled(self, checked):
        self._show_mapping = bool(checked)
        if self._loading_fields or not self._web_loaded or not self._web_view:
            return
        js = (
            "window.setShowVehicleMapping && "
            f"window.setShowVehicleMapping({str(bool(checked)).lower()})"
        )
        self._web_view.page().runJavaScript(js)

    def _on_web_load_finished(self, ok):
        self._web_loaded = bool(ok)
        self._set_controls_enabled(bool(ok and self._web_view))
        if ok and self._web_view:
            self._send_preview_update()

    def _send_preview_update(self):
        if not (self._web_view and self._web_loaded):
            return
        # Preview mutates only the temporary page's VEHICLE_SPECS; global
        # modeling settings files are never written from this dialog.
        settings = load_vehicle_model_settings()
        lane_width = float(settings["laneWidth"])
        emergency_lane_width = float(settings["emergencyLaneWidth"])
        outline_width = float(settings.get("outlineWidth", 2.5))
        preview_spec = {
            "kind": DEFAULT_VEHICLE_SPECS.get(self._preset_type, {}).get(
                "kind", "passenger"
            ),
            **self._spec,
        }
        spec_json = json.dumps(preview_spec, ensure_ascii=False)
        type_json = json.dumps(self._preset_type, ensure_ascii=False)
        show_mapping = "true" if self._show_mapping else "false"
        body_json = json.dumps(self._body_color, ensure_ascii=False)
        cargo_json = json.dumps(self._cargo_color, ensure_ascii=False)
        # Set paint first so rebuildVehicle (inside updateVehicleSpecs) picks it up.
        js = (
            "window.previewPaintColors = {"
            f"color: {body_json}, cargoColor: {cargo_json}"
            "};"
            "window.updateVehicleSpecs && "
            f"window.updateVehicleSpecs({type_json}, {spec_json}, {lane_width}, "
            f"{emergency_lane_width}, {outline_width}, {self._preview_index}, "
            f"{show_mapping})"
        )
        self._web_view.page().runJavaScript(js)

    def _teardown_web_view(self):
        """Detach WebEngine before closing so parent dialogs are not closed with it."""
        if self._web_view is None:
            return
        view = self._web_view
        self._web_view = None
        self._web_loaded = False
        try:
            view.loadFinished.disconnect(self._on_web_load_finished)
        except (TypeError, RuntimeError):
            pass
        view.setParent(None)
        view.deleteLater()

    def done(self, result):
        self._teardown_web_view()
        super().done(result)

    def _reset_to_default(self):
        self._reset_requested = True
        self._result_size = None
        self.done(QDialog.Accepted)

    def _accept_custom(self):
        try:
            if not self._apply_fields_to_spec():
                QMessageBox.warning(self, "无法保存", "请输入大于 0 的有效数值。")
                return
        except ValueError:
            QMessageBox.warning(self, "无法保存", "轮位置必须是数字，并用逗号分隔。")
            return
        self._reset_requested = False
        self._result_size = {
            "width": float(self._spec["width"]),
            "length": float(self._spec["length"]),
            "height": float(self._spec["height"]),
            "wheelRadius": float(self._spec["wheelRadius"]),
            "wheels": [float(v) for v in self._spec["wheels"]],
        }
        self.done(QDialog.Accepted)

    @property
    def result_size(self):
        """Full custom spec dict, or None if restored to the type default."""
        return self._result_size
