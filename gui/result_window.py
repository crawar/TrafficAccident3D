import os

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QMessageBox,
    QLabel,
    QComboBox,
    QCheckBox,
    QProgressDialog,
    QProgressBar,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
)
from PySide6.QtCore import Qt, QUrl, QTimer, QThread, Signal, QEvent
from PySide6.QtGui import QDesktopServices, QColor, QPalette, QCursor
from gui.image_viewer import ImageViewer
from gui.accident_brief_panel import AccidentBriefPanel
from utils.ai_settings import ai_liability_enabled, ai_request_config
from utils.annotation_history import save_annotation, annotation_fingerprint
from utils.html_generator import generate_html
from utils.liability_ai import build_liability_context, request_liability_analysis
from utils.measurement_save_server import start_measurement_save_server

CASE_BRIEF_MODE_LABEL = "事故案情"
MOTION_MODE_LABEL = "运动"
REQUIRED_MODE_LABELS = ("车辆", "道路线")
_GENERATE_ENABLED_STYLE = (
    "font-size: 16px; font-weight: bold; background-color: #4CAF50; color: white;"
)
_GENERATE_DISABLED_STYLE = (
    "font-size: 16px; font-weight: bold; background-color: #9e9e9e; color: #eeeeee;"
)
_AI_DISABLED_TOOLTIP = "请先在系统设置中开启AI分析责任"
_SHORTCUTS_HELP_TEXT = (
    "【视图缩放与平移】\n"
    "· Alt + 滚轮上：放大图片（缩小可视范围）\n"
    "· Alt + 滚轮下：缩小图片（扩大可视范围）\n"
    "· 图片显示不全时，左键按住空白处拖动：抓握平移（拳头光标）\n"
    "· 中键拖曳：平移视图\n"
    "· 空格 + 空白处左键拖曳：平移视图\n"
    "\n"
    "【选择与编辑】\n"
    "· Ctrl + 点击：多选车辆\n"
    "· 选中车辆 / 道路线后滚轮：旋转\n"
    "· 选中车辆后 ← / →：旋转方向标识\n"
    "· Delete 或右键菜单：删除选中对象\n"
    "· 点击「新增」后拖拽 / 单击：新增当前模式下的对象\n"
    "\n"
    "【运动路径】\n"
    "· 右键车辆：「设置路径」/「设置速度」\n"
    "· 路径绘制中左键空白处加点；右键空白处结束并连到车心\n"
    "· Delete：删除当前呼吸中的路径点（仅可从后往前删）\n"
    "· 路径绘制中滚轮：切换当前呼吸点前进(G)/倒退(F)\n"
    "· 预估超过 30 秒的路径呈红色\n"
    "\n"
    "【其它】\n"
    "· 「显示全部图层」：同时显示车辆、道路线、标记物与运动路径（仅观察，不可跨图层操作）\n"
    "· 「识别确认」：需至少有一辆车和一条道路线\n"
)


def _edit_mode_key(text):
    raw = str(text or "").strip()
    while raw.startswith("*"):
        raw = raw[1:].strip()
    return raw


class RequiredModeDelegate(QStyledItemDelegate):
    def __init__(self, required_rows, parent=None):
        super().__init__(parent)
        self.required_rows = set(required_rows)

    def paint(self, painter, option, index):
        if index.row() in self.required_rows:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.palette.setColor(QPalette.ColorRole.Text, QColor(220, 0, 0))
            opt.palette.setColor(
                QPalette.ColorRole.HighlightedText, QColor(255, 80, 80)
            )
            super().paint(painter, opt, index)
            return
        super().paint(painter, option, index)


class LiabilityAnalysisThread(QThread):
    finished = Signal(object, object)
    error = Signal(str)

    def __init__(
        self,
        image_path,
        vehicles,
        lanes,
        ai_settings,
        accident_brief="",
        lane_width_settings=None,
        markers=None,
    ):
        super().__init__()
        self.image_path = image_path
        self.vehicles = vehicles
        self.lanes = lanes
        self.ai_settings = dict(ai_settings or {})
        self.accident_brief = accident_brief or ""
        self.lane_width_settings = lane_width_settings
        self.markers = markers or []

    def run(self):
        try:
            liability_context = build_liability_context(
                self.image_path,
                self.vehicles,
                self.lanes,
                self.accident_brief,
                lane_width_settings=self.lane_width_settings,
                markers=self.markers,
            )
            ai_analysis = request_liability_analysis(self.ai_settings, liability_context)
            self.finished.emit(ai_analysis, liability_context)
        except Exception as exc:
            self.error.emit(str(exc))


class ResultWindow(QDialog):
    def __init__(
        self,
        image_path,
        vehicles,
        parent=None,
        lanes=None,
        markers=None,
        cached_annotation=None,
        ai_settings=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("结果确认与编辑")

        screen = parent.screen() if parent else QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(int(available.width() * 0.8), int(available.height() * 0.8))
        self.move(available.center() - self.rect().center())

        self.image_path = image_path
        self.vehicles = vehicles
        self.lanes = lanes or []
        self.markers = markers or []
        self.cached_annotation = cached_annotation or {}
        self.ai_settings = dict(ai_settings or {})
        self.progress_dialog = None
        self.ai_thread = None
        self._selected_veh = None
        self._base_hint_text = ""
        self._add_btn_flow_step = 0
        self._add_btn_flow_timer = QTimer(self)
        self._add_btn_flow_timer.setInterval(140)
        self._add_btn_flow_timer.timeout.connect(self._update_add_vehicle_button_flow)
        self._initial_accident_brief = str(
            self.cached_annotation.get("accident_brief", "") or ""
        )
        self._accident_panel_positioned = False

        self.init_ui()

    def accident_brief_text(self):
        if hasattr(self, "accident_panel"):
            return self.accident_panel.text()
        return self._initial_accident_brief

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)

        self.toolbar_layout = QHBoxLayout()

        self.mode_label = QLabel("编辑模式:")
        self.toolbar_layout.addWidget(self.mode_label)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(
            ["*车辆", "*道路线", "标记物", MOTION_MODE_LABEL, CASE_BRIEF_MODE_LABEL]
        )
        self._mode_delegate = RequiredModeDelegate({0, 1}, self.mode_combo)
        self.mode_combo.setItemDelegate(self._mode_delegate)
        self.mode_combo.currentTextChanged.connect(self.on_edit_mode_changed)
        self.toolbar_layout.addWidget(self.mode_combo)

        self.add_vehicle_btn = QPushButton("新增")
        self.add_vehicle_btn.setAutoDefault(False)
        self.add_vehicle_btn.setDefault(False)
        self.add_vehicle_btn.setCheckable(True)
        self.add_vehicle_btn.clicked.connect(self.on_add_toggled)
        self.toolbar_layout.addWidget(self.add_vehicle_btn)
        self._set_add_vehicle_button_idle_style()
        self._refresh_add_button_text()

        self.show_all_checkbox = QCheckBox("显示全部图层")
        self.show_all_checkbox.setChecked(True)
        self.show_all_checkbox.toggled.connect(self.on_show_all_toggled)
        self.toolbar_layout.addWidget(self.show_all_checkbox)

        self.run_ai_checkbox = QCheckBox("本次启用AI分析")
        # This is intentionally session-only. The persistent AI setting only
        # supplies the initial state each time this window is opened.
        system_ai_enabled = bool(
            self.ai_settings.get("enableLiabilityAnalysis", False)
        )
        self.run_ai_checkbox.setChecked(system_ai_enabled)
        if not system_ai_enabled:
            self.run_ai_checkbox.setChecked(False)
            self.run_ai_checkbox.setEnabled(False)
            self.run_ai_checkbox.setToolTip(_AI_DISABLED_TOOLTIP)
        self.run_ai_checkbox.installEventFilter(self)
        self.toolbar_layout.addWidget(self.run_ai_checkbox)

        self.cache_only_btn = QPushButton("仅缓存")
        self.cache_only_btn.setAutoDefault(False)
        self.cache_only_btn.setDefault(False)
        self.cache_only_btn.clicked.connect(self.on_cache_only)
        self.toolbar_layout.addWidget(self.cache_only_btn)

        self.toolbar_layout.addStretch(1)

        self.shortcuts_btn = QPushButton("快捷键")
        self.shortcuts_btn.setAutoDefault(False)
        self.shortcuts_btn.setDefault(False)
        self.shortcuts_btn.clicked.connect(self.on_show_shortcuts)
        self.toolbar_layout.addWidget(self.shortcuts_btn)
        self._shortcuts_blink_on = False
        self._shortcuts_blink_timer = QTimer(self)
        self._shortcuts_blink_timer.setInterval(500)
        self._shortcuts_blink_timer.timeout.connect(self._tick_shortcuts_blink)
        self._shortcuts_blink_timer.start()
        self._update_shortcuts_btn_style()

        self.main_layout.addLayout(self.toolbar_layout)

        self.viewer = ImageViewer()
        self.viewer.vehicle_selection_changed.connect(self.on_vehicle_selection_changed)
        self.viewer.vehicle_selection_count_changed.connect(
            self.on_vehicle_selection_count_changed
        )
        self.viewer.objects_changed.connect(self._refresh_generate_enabled)
        self.main_layout.addWidget(self.viewer, stretch=1)

        self.viewer.apply_lane_width_settings_from_cache(
            self.cached_annotation.get("lane_width_settings")
        )
        self.viewer.load_image_and_data(
            self.image_path, self.vehicles, self.lanes, self.markers
        )
        self.viewer.set_show_all_objects(True)

        self.accident_panel = AccidentBriefPanel(self)
        self.accident_panel.set_text(self._initial_accident_brief)
        self.accident_panel.hide()

        self.generate_btn = QPushButton("识别确认")
        self.generate_btn.setFixedSize(200, 50)
        # Inside a QDialog, autoDefault buttons can steal Enter from nested
        # dialogs and close/trigger this window unexpectedly.
        self.generate_btn.setAutoDefault(False)
        self.generate_btn.setDefault(False)
        self.generate_btn.setStyleSheet(_GENERATE_ENABLED_STYLE)
        self.generate_btn.clicked.connect(self.on_generate)
        self.generate_btn.installEventFilter(self)

        self.generate_layout = QHBoxLayout()
        self.generate_layout.addStretch(1)
        self.generate_layout.addWidget(self.generate_btn)
        self.generate_layout.addStretch(1)
        self.main_layout.addLayout(self.generate_layout)

        self.hint_label = QLabel()
        self._set_default_hint()
        self.hint_label.setStyleSheet("color: #d32f2f; font-weight: bold;")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.hint_label)

        self._refresh_generate_enabled()
        self._update_mode_combo_style()

    def eventFilter(self, obj, event):
        # init_ui may deliver events after run_ai_checkbox installs this filter
        # but before generate_btn exists; guard both targets.
        if (
            hasattr(self, "run_ai_checkbox")
            and obj is self.run_ai_checkbox
            and not self.run_ai_checkbox.isEnabled()
        ):
            if event.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                QToolTip.showText(
                    QCursor.pos(), _AI_DISABLED_TOOLTIP, self.run_ai_checkbox
                )
        if (
            hasattr(self, "generate_btn")
            and obj is self.generate_btn
            and not self.generate_btn.isEnabled()
        ):
            tip = self.generate_btn.toolTip()
            if tip and event.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
                QToolTip.showText(QCursor.pos(), tip, self.generate_btn)
        return super().eventFilter(obj, event)

    def on_show_shortcuts(self):
        QMessageBox.information(self, "快捷键说明", _SHORTCUTS_HELP_TEXT)

    def _tick_shortcuts_blink(self):
        self._shortcuts_blink_on = not self._shortcuts_blink_on
        self._update_shortcuts_btn_style()

    def _update_shortcuts_btn_style(self):
        color = "#d32f2f" if self._shortcuts_blink_on else "#222222"
        self.shortcuts_btn.setStyleSheet(
            "QPushButton {"
            f"color: {color};"
            "font-weight: bold;"
            "padding: 6px 12px;"
            "}"
        )

    def _update_mode_combo_style(self):
        key = _edit_mode_key(self.mode_combo.currentText())
        if key in REQUIRED_MODE_LABELS:
            self.mode_combo.setStyleSheet(
                "QComboBox { color: #d32f2f; font-weight: bold; }"
            )
        else:
            self.mode_combo.setStyleSheet("")

    def _refresh_generate_enabled(self):
        if not hasattr(self, "generate_btn"):
            return
        vehicles, lanes, _markers = self.viewer.get_confirmed_data()
        has_vehicle = bool(vehicles)
        has_lane = bool(lanes)
        enabled = has_vehicle and has_lane
        # Keep disabled while AI analysis is in progress.
        if self.ai_thread is not None and self.ai_thread.isRunning():
            return
        self.generate_btn.setEnabled(enabled)
        if enabled:
            self.generate_btn.setStyleSheet(_GENERATE_ENABLED_STYLE)
            self.generate_btn.setToolTip("")
        else:
            self.generate_btn.setStyleSheet(_GENERATE_DISABLED_STYLE)
            if not has_vehicle and not has_lane:
                tip = "请先添加至少一辆车和一条道路线后再识别确认"
            elif not has_vehicle:
                tip = "请先添加至少一辆车（必填）后再识别确认"
            else:
                tip = "请先添加至少一条道路线（必填）后再识别确认"
            self.generate_btn.setToolTip(tip)

    # 车辆选中期间会临时显示方向键提示,因此普通提示需要先存到 _base_hint_text,
    # 取消选中后再恢复,而不是直接写 hint_label。
    def _set_hint(self, text):
        self._base_hint_text = text
        self.hint_label.setText(text)

    def _set_default_hint(self):
        self._set_hint(
            "车辆: 选中车辆后可拖拽移动、拖黄色角点缩放、滚轮旋转；点击「新增」后拖拽可新增选框。"
            "Alt+滚轮缩放；图片放大后可左键拖空白处平移；中键或空格+空白处左键也可平移。"
        )

    def _set_add_vehicle_hint(self):
        self._set_hint(
            "新增: 在图像上按住左键拖拽生成选框；新增后可继续拖拽添加多个，完成后再次点击「退出新增」退出。"
        )

    def _set_draw_hint(self):
        self._set_hint(
            "道路线: 拖动已有车道线可调整整组平行间距，选中车道线后滚轮可旋转整组线，右键或 Delete 可删除最后一根车道线。"
            "若要新增车道线，请点击「新增」后再拖拽绘制。"
            "Alt+滚轮缩放；图片放大后可左键拖空白处平移。"
        )

    def _set_add_lane_hint(self):
        self._set_hint(
            "新增: 在图像上按住左键拖拽绘制车道线，可连续画多根；完成后再次点击「退出新增」退出。"
        )

    def _set_marker_hint(self):
        self._set_hint(
            "标记物: 拖动已有标记可移动，右键可设置为安全椎桶、成年人或导向牌，选中后按 Delete 删除。"
            "若要新增标记物，请点击「新增」后再左键单击。"
            "Alt+滚轮缩放；图片放大后可左键拖空白处平移。"
        )

    def _set_add_marker_hint(self):
        self._set_hint(
            "新增: 在图像上左键单击添加圆形标记，可连续添加多个；完成后再次点击「退出新增」退出。"
        )

    def _current_add_label(self):
        return ("新增对象", "退出新增")

    def _refresh_add_button_text(self):
        idle, active = self._current_add_label()
        self.add_vehicle_btn.setText(active if self.add_vehicle_btn.isChecked() else idle)

    def _set_add_vehicle_button_idle_style(self):
        self.add_vehicle_btn.setStyleSheet(
            "QPushButton { padding: 6px 14px; font-weight: bold; }"
            "QPushButton:disabled { color: #888888; }"
        )

    def _set_add_vehicle_button_text(self, active):
        idle, active_text = self._current_add_label()
        self.add_vehicle_btn.setText(active_text if active else idle)

    def _start_add_vehicle_button_flow(self):
        self._add_btn_flow_step = 0
        self._update_add_vehicle_button_flow()
        self._add_btn_flow_timer.start()

    def _stop_add_vehicle_button_flow(self):
        self._add_btn_flow_timer.stop()
        self._set_add_vehicle_button_idle_style()
        self._set_add_vehicle_button_text(False)

    def _update_add_vehicle_button_flow(self):
        colors = [
            ("#fff59d", "#ff6d00"),
            ("#ffe082", "#ff1744"),
            ("#ffcc80", "#7c4dff"),
            ("#fff176", "#00b0ff"),
            ("#ffe57f", "#00c853"),
            ("#fff59d", "#ff6d00"),
        ]
        c1, c2 = colors[self._add_btn_flow_step % len(colors)]
        self._add_btn_flow_step += 1
        self.add_vehicle_btn.setStyleSheet(
            "QPushButton {"
            "padding: 6px 14px;"
            "font-weight: bold;"
            "color: #111111;"
            "border: 3px solid %s;"
            "border-radius: 8px;"
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 %s, stop:0.45 #ffffff, stop:1 %s);"
            "}"
            "QPushButton:pressed { background-color: #ffd54f; }" % (c2, c1, c2)
        )

    def on_vehicle_selection_changed(self, veh):
        self._selected_veh = veh

    def on_vehicle_selection_count_changed(self, count):
        if not hasattr(self, "hint_label"):
            # load_image_and_data() during init_ui() may clear the scene before
            # hint_label exists yet; nothing to update in that case.
            return
        if count > 0:
            self.hint_label.setText(
                "方向标识: 已选中车辆(可 Ctrl 多选)，按 ← 逆时针旋转方向标识一格，"
                "按 → 顺时针旋转一格，不改变识别框的角度和大小。"
            )
        else:
            self.hint_label.setText(self._base_hint_text)

    def on_show_all_toggled(self, checked):
        self.viewer.set_show_all_objects(checked)

    def on_cache_only(self):
        final_vehicles, final_lanes, final_markers = self.viewer.get_confirmed_data()
        accident_brief = self.accident_brief_text()
        lane_width_settings = self.viewer.get_lane_width_settings_for_cache()
        persisted_ai_analysis = self.cached_annotation.get("ai_analysis")
        persisted_liability_context = self.cached_annotation.get("liability_context")
        persisted_html_path = self.cached_annotation.get("generated_html_path", "")
        try:
            save_annotation(
                self.image_path,
                final_vehicles,
                final_lanes,
                final_markers,
                ai_analysis=persisted_ai_analysis,
                liability_context=persisted_liability_context,
                generated_html_path=persisted_html_path,
                accident_brief=accident_brief,
                lane_width_settings=lane_width_settings,
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"缓存失败: {str(e)}")
            return
        self.cached_annotation = {
            "vehicles": final_vehicles,
            "lanes": final_lanes,
            "markers": final_markers,
            "data_fingerprint": annotation_fingerprint(
                final_vehicles,
                final_lanes,
                final_markers,
                accident_brief,
                lane_width_settings,
            ),
            "ai_analysis": persisted_ai_analysis,
            "liability_context": persisted_liability_context,
            "generated_html_path": persisted_html_path,
            "accident_brief": accident_brief,
            "lane_width_settings": lane_width_settings,
        }
        self.hint_label.setText(
            "已缓存当前识别结果（含单独车辆尺寸、本图车道宽、事故案情与运动路径），尚未生成建模。"
            "可继续修改后再次点击「仅缓存」或「识别确认」。"
        )

    def on_edit_mode_changed(self, text):
        self.add_vehicle_btn.setChecked(False)
        self._stop_add_vehicle_button_flow()
        self.viewer.set_add_vehicle_mode(False)
        self.viewer.set_lane_draw_enabled(False)
        self.viewer.set_marker_add_enabled(False)

        mode_key = _edit_mode_key(text)
        is_case_mode = mode_key == CASE_BRIEF_MODE_LABEL
        is_motion_mode = mode_key == MOTION_MODE_LABEL
        self.add_vehicle_btn.setEnabled(not is_case_mode and not is_motion_mode)
        self._update_mode_combo_style()

        if is_case_mode:
            self.viewer.set_motion_mode(False)
            self.viewer.set_draw_mode(False)
            self.viewer.set_marker_mode(False)
            self._selected_veh = None
            self._show_accident_panel()
            self._set_case_hint()
            # 事故案情页需要展示全部图层才方便用户用车辆ID描述案情,
            # 这里只做视觉勾选+禁用,不改变 show_all_checkbox 的真实勾选状态,
            # 离开该页时会恢复,不影响用户在其他页面原本的显示设置。
            self.show_all_checkbox.blockSignals(True)
            self.show_all_checkbox.setChecked(True)
            self.show_all_checkbox.blockSignals(False)
            self.show_all_checkbox.setEnabled(False)
        else:
            self.show_all_checkbox.setEnabled(True)
            self.show_all_checkbox.blockSignals(True)
            self.show_all_checkbox.setChecked(self.viewer.show_all_objects)
            self.show_all_checkbox.blockSignals(False)
            self._hide_accident_panel()
            if mode_key == "道路线":
                self.viewer.set_motion_mode(False)
                self.viewer.set_marker_mode(False)
                self.viewer.set_draw_mode(True)
                self._selected_veh = None
                self._set_draw_hint()
            elif mode_key == "标记物":
                self.viewer.set_motion_mode(False)
                self.viewer.set_draw_mode(False)
                self.viewer.set_marker_mode(True)
                self._selected_veh = None
                self._set_marker_hint()
            elif is_motion_mode:
                self.viewer.set_draw_mode(False)
                self.viewer.set_marker_mode(False)
                self.viewer.set_motion_mode(True)
                self._selected_veh = None
                self._set_motion_hint()
            else:
                self.viewer.set_motion_mode(False)
                self.viewer.set_draw_mode(False)
                self.viewer.set_marker_mode(False)
                self._set_default_hint()
        # set_case_mode 必须放在 set_draw_mode/set_marker_mode 之后调用,
        # 否则事故案情页会被后续的 mode setter 重新打开车辆/车道/标记物的可选中状态。
        self.viewer.set_case_mode(is_case_mode)
        self._refresh_add_button_text()

    def _set_motion_hint(self):
        self._set_hint(
            "运动: 仅可选中车辆。右键车辆可「设置路径」或「设置速度」。"
            "路径绘制时左键加点、右键空白结束；Delete 删除当前呼吸点；"
            "滚轮切换呼吸点前进(G)/倒退(F)。"
            "本页强制显示车辆框；车道/标记仍跟随「显示全部图层」。"
        )

    def _show_accident_panel(self):
        if not self._accident_panel_positioned:
            self.accident_panel.move(self.width() - self.accident_panel.width() - 30, 90)
            self._accident_panel_positioned = True
        self.accident_panel.show()
        self.accident_panel.raise_()

    def _hide_accident_panel(self):
        self.accident_panel.hide()

    def _set_case_hint(self):
        self._set_hint(
            "事故案情: 在浮动窗口中输入简要事故案情，建议用车辆ID指代车辆，"
            "该内容会作为提示词发送给 AI 辅助责任分析。可拖动浮窗标题栏以免遮盖识别图像。"
        )

    def on_add_toggled(self, checked):
        mode = _edit_mode_key(self.mode_combo.currentText())
        if mode in (CASE_BRIEF_MODE_LABEL, MOTION_MODE_LABEL):
            self.add_vehicle_btn.setChecked(False)
            return
        if mode == "道路线":
            self.viewer.set_lane_draw_enabled(checked)
            if checked:
                self._start_add_vehicle_button_flow()
                self._set_add_vehicle_button_text(True)
                self._set_add_lane_hint()
            else:
                self._stop_add_vehicle_button_flow()
                self._set_draw_hint()
            return
        if mode == "标记物":
            self.viewer.set_marker_add_enabled(checked)
            if checked:
                self._start_add_vehicle_button_flow()
                self._set_add_vehicle_button_text(True)
                self._set_add_marker_hint()
            else:
                self._stop_add_vehicle_button_flow()
                self._set_marker_hint()
            return
        self.viewer.set_draw_mode(False)
        self.viewer.set_marker_mode(False)
        self.viewer.set_add_vehicle_mode(checked)
        if checked:
            self._selected_veh = None
            self._set_add_vehicle_button_text(True)
            self._start_add_vehicle_button_flow()
            self._set_add_vehicle_hint()
        else:
            self._stop_add_vehicle_button_flow()
            self._set_default_hint()

    def on_generate(self):
        final_vehicles, final_lanes, final_markers = self.viewer.get_confirmed_data()
        if not final_vehicles or not final_lanes:
            self._refresh_generate_enabled()
            return

        current_fingerprint = annotation_fingerprint(
            final_vehicles,
            final_lanes,
            final_markers,
            self.accident_brief_text(),
            self.viewer.get_lane_width_settings_for_cache(),
        )
        force_regenerate_ai = bool(
            self.ai_settings.get("regenerateLiabilityEachTime", True)
        )
        current_request_config = ai_request_config(self.ai_settings)
        cached_ai_analysis = None
        cached_liability_context = None
        if self.cached_annotation.get("data_fingerprint") == current_fingerprint:
            maybe_cached_ai = self.cached_annotation.get("ai_analysis")
            if (
                isinstance(maybe_cached_ai, dict)
                and maybe_cached_ai.get("requestConfig") == current_request_config
            ):
                cached_ai_analysis = maybe_cached_ai
                cached_liability_context = self.cached_annotation.get(
                    "liability_context"
                )

        # The per-window checkbox is the final switch for this generation.
        # Force only the enable flag on a temporary copy so a checked local
        # switch can run AI even when the persistent enable setting is off;
        # API key, URL and model validation still use the normal rules.
        effective_ai_settings = dict(self.ai_settings)
        effective_ai_settings["enableLiabilityAnalysis"] = True
        run_ai_this_time = (
            self.run_ai_checkbox.isChecked()
            and ai_liability_enabled(effective_ai_settings)
        )

        if run_ai_this_time:
            if (
                (not force_regenerate_ai)
                and cached_ai_analysis
                and cached_liability_context
            ):
                self._finish_generate(
                    final_vehicles,
                    final_lanes,
                    final_markers,
                    cached_ai_analysis,
                    cached_liability_context,
                    persist_ai_analysis=cached_ai_analysis,
                    persist_liability_context=cached_liability_context,
                )
                return
            if not force_regenerate_ai:
                try:
                    self._finish_generate(
                        final_vehicles,
                        final_lanes,
                        final_markers,
                        None,
                        None,
                        persist_ai_analysis=None,
                        persist_liability_context=None,
                    )
                except Exception as e:
                    QMessageBox.critical(self, "错误", f"生成或保存失败: {str(e)}")
                return

            self.generate_btn.setEnabled(False)
            self.progress_dialog = QProgressDialog(
                "建模数据准备中",
                None,
                0,
                0,
                self,
            )
            self.progress_dialog.setWindowTitle("准备中")
            self.progress_dialog.setCancelButton(None)
            self.progress_dialog.setWindowModality(Qt.WindowModal)
            self.progress_dialog.setMinimumDuration(0)
            self._polish_progress_dialog()
            self.progress_dialog.show()
            self.ai_thread = LiabilityAnalysisThread(
                self.image_path,
                final_vehicles,
                final_lanes,
                self.ai_settings,
                accident_brief=self.accident_brief_text(),
                lane_width_settings=self.viewer.get_lane_width_settings_for_cache(),
                markers=final_markers,
            )
            self.ai_thread.finished.connect(
                lambda ai_analysis, liability_context: self._on_ai_finished(
                    final_vehicles,
                    final_lanes,
                    final_markers,
                    ai_analysis,
                    liability_context,
                )
            )
            self.ai_thread.error.connect(
                lambda err_msg: self._on_ai_error(
                    final_vehicles,
                    final_lanes,
                    final_markers,
                    err_msg,
                )
            )
            self.ai_thread.start()
            return

        try:
            self._finish_generate(
                final_vehicles,
                final_lanes,
                final_markers,
                None,
                None,
                persist_ai_analysis=cached_ai_analysis,
                persist_liability_context=cached_liability_context,
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成或保存失败: {str(e)}")

    def _close_progress_dialog(self):
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
            self.progress_dialog = None
        self._refresh_generate_enabled()

    def _polish_progress_dialog(self):
        if self.progress_dialog is None:
            return
        self.progress_dialog.setFixedSize(360, 180)
        self.progress_dialog.setStyleSheet(
            "QProgressDialog QLabel {"
            "font-size: 18px;"
            "font-weight: bold;"
            "padding: 12px 10px 8px 10px;"
            "qproperty-alignment: AlignCenter;"
            "}"
            "QProgressBar {"
            "min-height: 10px;"
            "max-height: 10px;"
            "margin: 10px 36px 24px 36px;"
            "border: none;"
            "border-radius: 5px;"
            "background: #d9d9d9;"
            "text-align: center;"
            "}"
            "QProgressBar::chunk {"
            "border-radius: 5px;"
            "background: #2fb3ff;"
            "}"
        )
        label = self.progress_dialog.findChild(QLabel)
        if label is not None:
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(True)
        progress_bar = self.progress_dialog.findChild(QProgressBar)
        if progress_bar is not None:
            progress_bar.setAlignment(Qt.AlignCenter)

    def _on_ai_finished(
        self, final_vehicles, final_lanes, final_markers, ai_analysis, liability_context
    ):
        self._close_progress_dialog()
        try:
            self._finish_generate(
                final_vehicles,
                final_lanes,
                final_markers,
                ai_analysis,
                liability_context,
                persist_ai_analysis=ai_analysis,
                persist_liability_context=liability_context,
            )
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"生成或保存失败: {str(exc)}")

    def _on_ai_error(self, final_vehicles, final_lanes, final_markers, err_msg):
        self._close_progress_dialog()
        QMessageBox.warning(
            self,
            "AI划责失败",
            f"责任分析失败: {err_msg}\n\n将按未启用 AI 模式继续生成 HTML 模型。",
        )
        try:
            self._finish_generate(
                final_vehicles,
                final_lanes,
                final_markers,
                None,
                None,
                persist_ai_analysis=None,
                persist_liability_context=None,
            )
        except Exception as exc:
            QMessageBox.critical(self, "错误", f"生成或保存失败: {str(exc)}")

    def _finish_generate(
        self,
        final_vehicles,
        final_lanes,
        final_markers,
        html_ai_analysis,
        html_liability_context,
        persist_ai_analysis=None,
        persist_liability_context=None,
    ):
        save_url = start_measurement_save_server()
        lane_width_settings = self.viewer.get_lane_width_settings_for_cache()
        html_path = generate_html(
            self.image_path,
            final_vehicles,
            final_lanes,
            final_markers,
            save_measurements_url=save_url,
            ai_analysis=html_ai_analysis,
            liability_context=html_liability_context,
            lane_width_settings=lane_width_settings,
        )
        accident_brief = self.accident_brief_text()
        save_annotation(
            self.image_path,
            final_vehicles,
            final_lanes,
            final_markers,
            ai_analysis=persist_ai_analysis,
            liability_context=persist_liability_context,
            generated_html_path=html_path,
            accident_brief=accident_brief,
            lane_width_settings=lane_width_settings,
        )
        self.cached_annotation = {
            "vehicles": final_vehicles,
            "lanes": final_lanes,
            "markers": final_markers,
            "data_fingerprint": annotation_fingerprint(
                final_vehicles,
                final_lanes,
                final_markers,
                accident_brief,
                lane_width_settings,
            ),
            "ai_analysis": persist_ai_analysis,
            "liability_context": persist_liability_context,
            "generated_html_path": html_path,
            "accident_brief": accident_brief,
            "lane_width_settings": lane_width_settings,
        }
        QDesktopServices.openUrl(QUrl.fromLocalFile(html_path))
        base = os.path.basename(html_path)
        self.hint_label.setText(
            f"已生成并打开: {base}。可继续修改后再次点击「识别确认」。"
        )
