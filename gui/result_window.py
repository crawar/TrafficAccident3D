import os
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QMessageBox,
    QLabel,
    QCheckBox,
    QProgressDialog,
    QProgressBar,
    QToolTip,
    QFrame,
    QSizePolicy,
    QWidget,
    QButtonGroup,
)
from PySide6.QtCore import Qt, QUrl, QTimer, QThread, Signal, QEvent
from PySide6.QtGui import QDesktopServices, QCursor

from gui.app_styles import (
    ADD_BTN_ACTIVE_STYLE,
    BOARD_WINDOW_QSS,
    CACHE_BTN_FLASH_QSS,
    HISTORY_BTN_STYLE,
    LEFT_HINT_COL_W,
    PRIMARY_BTN_STYLE,
    RIGHT_TOOL_COL_W,
    SAVE_EDIT_BTN_STYLE,
    STATUS_PANEL_ERROR_QSS,
    STATUS_PANEL_IDLE_QSS,
    STATUS_PANEL_SUCCESS_QSS,
)
from gui.image_viewer import ImageViewer
from gui.accident_brief_panel import AccidentBriefPanel
from utils.ai_settings import ai_enabled
from utils.annotation_history import save_annotation, annotation_fingerprint
from utils.html_generator import generate_html
from utils.liability_ai import build_liability_context, request_liability_analysis
from utils.measurement_save_server import start_measurement_save_server

CROP_MODE_LABEL = "画布裁剪"
CASE_BRIEF_MODE_LABEL = "事故案情"
MOTION_MODE_LABEL = "运动"
EDIT_MODE_PAGES = (
    (CROP_MODE_LABEL, CROP_MODE_LABEL, False),
    ("车辆", "车辆*", True),
    ("道路线", "道路线*", True),
    ("标记物", "标记物", False),
    (MOTION_MODE_LABEL, MOTION_MODE_LABEL, False),
    (CASE_BRIEF_MODE_LABEL, CASE_BRIEF_MODE_LABEL, False),
)
_AI_DISABLED_TOOLTIP = "请先在系统设置中勾选「启用AI」并保存。"
_PREPARE_STATUS_STEPS = (
    "3D数据计算中……",
    "正在翻找知识库……",
    "正在注入事故知识……",
    "AI责任正在划定……",
    "AI专家正在思考……",
)
_GOAL_HINTS = {
    "画布裁剪": "选出最终三维场景展示的范围。打开时默认是原图短边的正方形，之后可拉成任意矩形。框外变暗，抓住框拖动或拖边角缩放，框不能超出原图。",
    "车辆": "校对每辆车的位置、朝向、车型与尺寸，保证框住真实车辆。",
    "道路线": "从应急车道外侧开始规划全部车道线：第1、2条间距是应急车道宽，之后是普通车道宽。",
    "标记物": "在现场补上锥桶、人员、导向牌、公里牌、散落物或碰撞点。",
    "运动": "为相关车辆设置事发前后的行驶路径和速度。",
    "事故案情": "用车辆ID简述经过，供AI辅助分析。可拖动浮窗以免挡住画布。",
}
_SHORTCUTS_HELP_TEXT = (
    "【画布裁剪】\n"
    "· 按住裁剪框拖动：框跟随鼠标移动\n"
    "· 拖动四角或四边：自由改变宽高（不必保持 1:1）\n"
    "· 框不能超出原图；打开时默认是原图短边居中的正方形\n"
    "\n"
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
    "· 点击「新增车辆/车道线/标记物」后拖拽 / 单击：新增当前模式下的对象\n"
    "\n"
    "【运动路径】\n"
    "· 右键车辆：「设置路径」/「设置速度」\n"
    "· 路径绘制中左键空白处加点；右键空白处或点「结束路径」结束并连到车心\n"
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
    while raw.endswith("*"):
        raw = raw[:-1].strip()
    return raw


def _next_hint_from_context(ctx):
    ctx = ctx or {}
    mode = ctx.get("mode") or "车辆"
    if mode == "画布裁剪":
        return (
            "下一步：按住裁剪框拖动，鼠标往哪框就往哪；"
            "拖四角或四边改大小（可不成正方形）。Alt+滚轮只缩放视图，不改裁剪。"
        )
    if ctx.get("add_vehicle"):
        return "下一步：在工作区内按住左键拖出车辆框；可连续添加。完成后点「完成新增」。"
    if ctx.get("add_lane"):
        lane_count = int(ctx.get("lane_count") or 0)
        if lane_count <= 0:
            return "下一步：从应急车道外侧按住左键拖出第1条线（应急车道外边界）。"
        if lane_count == 1:
            return "下一步：画第2条线。它与第1条的间距 = 应急车道宽。"
        return (
            f"下一步：继续画第{lane_count + 1}条快车道分界线。"
            "会自动平行，间距 = 普通车道宽。完成后点「完成新增」。"
        )
    if ctx.get("add_marker"):
        return "下一步：在工作区内左键单击放置标记物；可连续添加。完成后点「完成新增」。"
    if mode == "道路线":
        lane_count = int(ctx.get("lane_count") or 0)
        if ctx.get("lane_selected"):
            return (
                "已选中车道线：滚轮旋转整组；拖第1条平移整组；拖第2条改应急车道间距；"
                "Delete 只能删最后一条。也可点「设置车道宽」。"
            )
        if lane_count <= 0:
            return (
                "本页从应急车道开始。先点「设置车道宽」（可选），再点「新增车道线」，"
                "从应急车道外侧画第1条线。"
            )
        if lane_count == 1:
            return "已有第1条线。点「新增车道线」画第2条，两线间距为应急车道宽。"
        return (
            f"已有{lane_count}条线。点「新增车道线」继续画快车道；"
            "拖第1条平移整组，拖第2条改应急间距。"
        )
    if mode == "车辆":
        if ctx.get("vehicle_selected"):
            return (
                "已选中车辆：拖动移动，拖黄角缩放，滚轮旋转车框；"
                "← / → 旋转方向标识；Delete 删除。右键可改车型、尺寸和颜色。"
            )
        return (
            "下一步：单击选中车辆进行校对；或点「新增车辆」后拖出新框。"
            "Alt+滚轮缩放，空白处拖动平移。"
        )
    if mode == "标记物":
        if ctx.get("marker_selected"):
            return "已选中标记：拖动移动；右键改类型；Delete 删除。"
        return "下一步：拖动已有标记，或点「新增标记物」后左键单击放置。"
    if mode == "运动":
        if ctx.get("path_edit"):
            points = int(ctx.get("path_points") or 0)
            return (
                f"正在画路径（已有{points}点）：左键加点，滚轮切换前进G/倒退F，"
                "Delete 删最后一点。右键空白或点「结束路径」完成并连到车心。"
            )
        if ctx.get("vehicle_selected"):
            return "已选中车辆：右键选择「设置路径」或「设置速度」。本页不能拖动车框。"
        return "下一步：单击选中车辆，再右键「设置路径」或「设置速度」。"
    if mode == "事故案情":
        return "下一步：在浮窗里用车辆ID写案情，例如「车辆1追尾车辆2」。可拖标题栏挪开浮窗。"
    return "按右侧按钮选择子页，在中央画布上编辑。"


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
        canvas_crop=None,
    ):
        super().__init__()
        self.image_path = image_path
        self.vehicles = vehicles
        self.lanes = lanes
        self.ai_settings = dict(ai_settings or {})
        self.accident_brief = accident_brief or ""
        self.lane_width_settings = lane_width_settings
        self.markers = markers or []
        self.canvas_crop = canvas_crop

    def run(self):
        try:
            liability_context = build_liability_context(
                self.image_path,
                self.vehicles,
                self.lanes,
                self.accident_brief,
                lane_width_settings=self.lane_width_settings,
                markers=self.markers,
                canvas_crop=self.canvas_crop,
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
        self.setObjectName("resultBoard")
        self.setWindowTitle("结果确认与编辑")
        self.setStyleSheet(BOARD_WINDOW_QSS)

        screen = parent.screen() if parent else QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(int(available.width() * 0.92), int(available.height() * 0.9))
        self.move(available.center() - self.rect().center())

        self.image_path = image_path
        self.vehicles = vehicles
        self.lanes = lanes or []
        self.markers = markers or []
        self.cached_annotation = cached_annotation or {}
        self.ai_settings = dict(ai_settings or {})
        self.progress_dialog = None
        self.ai_thread = None
        self._ai_cancelled = False
        self._ai_request_id = 0
        self._prepare_status_steps = []
        self._prepare_status_index = 0
        self._prepare_status_timer = QTimer(self)
        self._prepare_status_timer.setInterval(5000)
        self._prepare_status_timer.timeout.connect(self._advance_prepare_status)
        self._selected_veh = None
        self._status_idle_timer = QTimer(self)
        self._status_idle_timer.setSingleShot(True)
        self._status_idle_timer.timeout.connect(self._restore_status_panel_style)
        self._initial_accident_brief = str(
            self.cached_annotation.get("accident_brief", "") or ""
        )
        self._accident_panel_positioned = False

        self.init_ui()

    def accident_brief_text(self):
        if hasattr(self, "accident_panel"):
            return self.accident_panel.text()
        return self._initial_accident_brief

    def _make_hint_panel(self, object_name, title, body_name):
        frame = QFrame()
        frame.setObjectName(object_name)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("hintTitle")
        body = QLabel()
        body.setObjectName(body_name)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(title_label)
        layout.addWidget(body, stretch=1)
        return frame, body

    def _lock_panel_to_contents(self, frame):
        layout = frame.layout()
        if layout is None:
            return
        frame.ensurePolished()
        margins = layout.contentsMargins()
        height = margins.top() + margins.bottom()
        widgets = []
        for index in range(layout.count()):
            widget = layout.itemAt(index).widget()
            if widget is None:
                continue
            widget.ensurePolished()
            widgets.append(widget)
        if widgets:
            height += sum(
                max(widget.sizeHint().height(), widget.minimumHeight())
                for widget in widgets
            )
            height += layout.spacing() * (len(widgets) - 1)
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        frame.setFixedHeight(height)

    def _style_tool_button(self, button, primary=False, save_edit=False):
        button.setAutoDefault(False)
        button.setDefault(False)
        button.setMinimumWidth(RIGHT_TOOL_COL_W - 24)
        if primary:
            button.setStyleSheet(PRIMARY_BTN_STYLE)
        elif save_edit:
            button.setStyleSheet(SAVE_EDIT_BTN_STYLE)
        else:
            button.setStyleSheet(HISTORY_BTN_STYLE)

    def init_ui(self):
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        left = QWidget()
        left.setFixedWidth(LEFT_HINT_COL_W)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.next_panel, self.next_hint_label = self._make_hint_panel(
            "hintPanel", "当前提示", "hintBody"
        )
        self.status_panel, self.status_hint_label = self._make_hint_panel(
            "statusPanel", "状态提示", "statusBody"
        )
        self.goal_panel, self.goal_hint_label = self._make_hint_panel(
            "goalPanel", "目的提示", "goalBody"
        )
        left_layout.addWidget(self.next_panel, stretch=3)
        left_layout.addWidget(self.status_panel, stretch=2)
        left_layout.addWidget(self.goal_panel, stretch=2)
        self.main_layout.addWidget(left)

        self.viewer = ImageViewer()
        self.viewer.vehicle_selection_changed.connect(self.on_vehicle_selection_changed)
        self.viewer.vehicle_selection_count_changed.connect(
            self.on_vehicle_selection_count_changed
        )
        self.viewer.objects_changed.connect(self._refresh_generate_enabled)
        self.viewer.hint_context_changed.connect(self.on_hint_context_changed)
        self.viewer.path_edit_state_changed.connect(self.on_path_edit_state_changed)
        self.viewer.path_edit_finished.connect(self.on_path_edit_finished)
        self.main_layout.addWidget(self.viewer, stretch=1)

        self.viewer.apply_lane_width_settings_from_cache(
            self.cached_annotation.get("lane_width_settings")
        )
        self.viewer.load_image_and_data(
            self.image_path,
            self.vehicles,
            self.lanes,
            self.markers,
            canvas_crop=self.cached_annotation.get("canvas_crop"),
        )
        self.viewer.set_show_all_objects(False)

        right = QWidget()
        right.setFixedWidth(RIGHT_TOOL_COL_W)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        mode_panel = QFrame()
        mode_panel.setObjectName("modeSelectPanel")
        mode_layout = QVBoxLayout(mode_panel)
        mode_layout.setContentsMargins(12, 10, 12, 12)
        mode_layout.setSpacing(6)

        mode_caption = QLabel("子编辑页")
        mode_caption.setObjectName("modeSelectCaption")
        mode_layout.addWidget(mode_caption)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self._mode_buttons = {}
        self._active_mode_key = CROP_MODE_LABEL
        for key, label, required in EDIT_MODE_PAGES:
            btn = QPushButton(label)
            btn.setObjectName("modeItem")
            btn.setCheckable(True)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFlat(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("modeKey", key)
            btn.setProperty("requiredMode", "true" if required else "false")
            btn.setFixedHeight(32)
            self.mode_group.addButton(btn)
            self._mode_buttons[key] = btn
            mode_layout.addWidget(btn)
        self._mode_buttons[CROP_MODE_LABEL].setChecked(True)
        self.mode_group.buttonClicked.connect(self._on_mode_button_clicked)
        self.mode_panel = mode_panel
        right_layout.addWidget(mode_panel, alignment=Qt.AlignTop)

        tool = QFrame()
        tool.setObjectName("toolPanel")
        tool.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        tool_layout = QVBoxLayout(tool)
        tool_layout.setContentsMargins(12, 10, 12, 10)
        tool_layout.setSpacing(6)

        self.add_vehicle_btn = QPushButton("新增车辆")
        self.add_vehicle_btn.setCheckable(True)
        self.add_vehicle_btn.clicked.connect(self.on_add_toggled)
        self._style_tool_button(self.add_vehicle_btn)
        tool_layout.addWidget(self.add_vehicle_btn)

        self.reset_crop_btn = QPushButton("重置裁剪")
        self.reset_crop_btn.clicked.connect(self.on_reset_crop)
        self._style_tool_button(self.reset_crop_btn)
        tool_layout.addWidget(self.reset_crop_btn)

        self.lane_width_btn = QPushButton("设置车道宽")
        self.lane_width_btn.clicked.connect(self.on_lane_width)
        self._style_tool_button(self.lane_width_btn)
        tool_layout.addWidget(self.lane_width_btn)

        self.finish_path_btn = QPushButton("结束路径")
        self.finish_path_btn.clicked.connect(self.on_finish_path)
        self._style_tool_button(self.finish_path_btn)
        self.finish_path_btn.setEnabled(False)
        tool_layout.addWidget(self.finish_path_btn)

        self.shortcuts_btn = QPushButton("快捷键")
        self.shortcuts_btn.clicked.connect(self.on_show_shortcuts)
        self._style_tool_button(self.shortcuts_btn)
        tool_layout.addWidget(self.shortcuts_btn)

        tool_layout.addStretch(1)
        self.tool_panel = tool
        right_layout.addWidget(tool, stretch=1)

        confirm = QFrame()
        confirm.setObjectName("confirmPanel")
        confirm_layout = QVBoxLayout(confirm)
        confirm_layout.setContentsMargins(12, 10, 12, 12)
        confirm_layout.setSpacing(8)

        self.show_all_checkbox = QCheckBox("显示全部图层")
        self.show_all_checkbox.setChecked(False)
        self.show_all_checkbox.toggled.connect(self.on_show_all_toggled)
        confirm_layout.addWidget(self.show_all_checkbox)

        self.run_ai_checkbox = QCheckBox("本次启用AI分析")
        system_ai_enabled = bool(self.ai_settings.get("enableAI", False))
        self.run_ai_checkbox.setChecked(system_ai_enabled)
        if not system_ai_enabled:
            self.run_ai_checkbox.setChecked(False)
            self.run_ai_checkbox.setEnabled(False)
            self.run_ai_checkbox.setToolTip(_AI_DISABLED_TOOLTIP)
        self.run_ai_checkbox.installEventFilter(self)
        confirm_layout.addWidget(self.run_ai_checkbox)

        self.cache_only_btn = QPushButton("保存编辑")
        self.cache_only_btn.clicked.connect(self.on_cache_only)
        self._style_tool_button(self.cache_only_btn, save_edit=True)
        confirm_layout.addWidget(self.cache_only_btn)

        self.generate_btn = QPushButton("识别确认")
        self.generate_btn.clicked.connect(self.on_generate)
        self.generate_btn.installEventFilter(self)
        self._style_tool_button(self.generate_btn, primary=True)
        confirm_layout.addWidget(self.generate_btn)

        self.confirm_panel = confirm
        right_layout.addWidget(confirm, alignment=Qt.AlignBottom)
        self.main_layout.addWidget(right)
        self._lock_panel_to_contents(self.mode_panel)
        self._lock_panel_to_contents(self.confirm_panel)

        self.accident_panel = AccidentBriefPanel(self)
        self.accident_panel.set_text(self._initial_accident_brief)
        self.accident_panel.hide()

        self._refresh_generate_enabled()
        self._refresh_mode_item_styles()
        self._refresh_mode_actions()
        self._set_status("画板已打开。请先在「画布裁剪」选定展示范围，再校对车辆与道路线。")
        self.on_edit_mode_changed(CROP_MODE_LABEL)

    def eventFilter(self, obj, event):
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.accident_panel.isVisible():
            self._place_accident_panel()

    def on_show_shortcuts(self):
        QMessageBox.information(self, "快捷键说明", _SHORTCUTS_HELP_TEXT)

    def _current_mode_key(self):
        btn = self.mode_group.checkedButton() if hasattr(self, "mode_group") else None
        if btn is None:
            return getattr(self, "_active_mode_key", CROP_MODE_LABEL)
        return _edit_mode_key(btn.property("modeKey") or btn.text())

    def _on_mode_button_clicked(self, button):
        key = _edit_mode_key(button.property("modeKey") or button.text())
        if key == getattr(self, "_active_mode_key", None):
            return
        self.on_edit_mode_changed(key)

    def _refresh_mode_item_styles(self):
        for btn in self._mode_buttons.values():
            style = btn.style()
            style.unpolish(btn)
            style.polish(btn)
            btn.update()

    def _refresh_generate_enabled(self):
        if not hasattr(self, "generate_btn"):
            return
        vehicles, lanes, _markers = self.viewer.get_confirmed_data()
        has_vehicle = bool(vehicles)
        has_lane = bool(lanes)
        enabled = has_vehicle and has_lane
        if self.ai_thread is not None and self.ai_thread.isRunning():
            return
        self.generate_btn.setEnabled(enabled)
        self.generate_btn.setStyleSheet(PRIMARY_BTN_STYLE)
        if enabled:
            self.generate_btn.setToolTip("")
        else:
            if not has_vehicle and not has_lane:
                tip = "请先添加至少一辆车和一条道路线后再识别确认"
            elif not has_vehicle:
                tip = "请先添加至少一辆车（必填）后再识别确认"
            else:
                tip = "请先添加至少一条道路线（必填）后再识别确认"
            self.generate_btn.setToolTip(tip)

    def _set_status(self, text, kind="info"):
        self.status_hint_label.setText(text)
        if kind == "success":
            self.status_panel.setStyleSheet(STATUS_PANEL_SUCCESS_QSS)
            self._status_idle_timer.start(800)
        elif kind == "error":
            self.status_panel.setStyleSheet(STATUS_PANEL_ERROR_QSS)
            self._status_idle_timer.start(1600)
        else:
            self.status_panel.setStyleSheet(STATUS_PANEL_IDLE_QSS)

    def _restore_status_panel_style(self):
        self.status_panel.setStyleSheet(STATUS_PANEL_IDLE_QSS)
        if hasattr(self, "cache_only_btn"):
            self.cache_only_btn.setStyleSheet(SAVE_EDIT_BTN_STYLE)

    def _set_goal_hint(self, text):
        self.goal_hint_label.setText(text)

    def on_hint_context_changed(self, ctx):
        self.next_hint_label.setText(_next_hint_from_context(ctx))

    def _current_add_label(self):
        mode = self._current_mode_key()
        idle = {
            "车辆": "新增车辆",
            "道路线": "新增车道线",
            "标记物": "新增标记物",
        }.get(mode, "新增对象")
        return (idle, "完成新增")

    def _refresh_add_button_text(self):
        idle, active = self._current_add_label()
        self.add_vehicle_btn.setText(active if self.add_vehicle_btn.isChecked() else idle)
        if self.add_vehicle_btn.isChecked():
            self.add_vehicle_btn.setStyleSheet(ADD_BTN_ACTIVE_STYLE)
        else:
            self.add_vehicle_btn.setStyleSheet(HISTORY_BTN_STYLE)

    def _refresh_mode_actions(self):
        mode = self._current_mode_key()
        is_crop = mode == CROP_MODE_LABEL
        is_case = mode == CASE_BRIEF_MODE_LABEL
        is_motion = mode == MOTION_MODE_LABEL
        is_lane = mode == "道路线"
        can_add = mode in ("车辆", "道路线", "标记物")
        self.add_vehicle_btn.setVisible(can_add)
        self.add_vehicle_btn.setEnabled(can_add)
        self.reset_crop_btn.setVisible(is_crop)
        self.lane_width_btn.setVisible(is_lane)
        self.finish_path_btn.setVisible(is_motion)
        self.finish_path_btn.setEnabled(
            is_motion and bool(getattr(self.viewer, "_path_edit_active", False))
        )
        if is_case:
            self.show_all_checkbox.setEnabled(False)
        else:
            self.show_all_checkbox.setEnabled(True)
        self._refresh_add_button_text()

    def on_vehicle_selection_changed(self, veh):
        self._selected_veh = veh

    def on_vehicle_selection_count_changed(self, count):
        return

    def on_show_all_toggled(self, checked):
        self.viewer.set_show_all_objects(checked)

    def on_reset_crop(self):
        self.viewer.reset_canvas_crop()
        self._set_status("已重置为原图短边居中的正方形裁剪，可再拉成任意矩形。", kind="success")

    def on_lane_width(self):
        self.viewer.open_lane_width_dialog()
        self.viewer._emit_hint_context()

    def on_finish_path(self):
        self.viewer.finish_active_path_edit()

    def on_path_edit_state_changed(self, active):
        mode = self._current_mode_key()
        self.finish_path_btn.setEnabled(mode == MOTION_MODE_LABEL and bool(active))

    def on_path_edit_finished(self, duration, too_long):
        if too_long:
            self._set_status(
                f"路径已结束，已连接到车辆中心。预估约 {duration:.1f} 秒（超过 30 秒，显示为红色）。",
                kind="success",
            )
        else:
            self._set_status(
                f"路径已结束，已连接到车辆中心。预估约 {duration:.1f} 秒。",
                kind="success",
            )

    def _persist_fields(self):
        return {
            "accident_brief": self.accident_brief_text(),
            "lane_width_settings": self.viewer.get_lane_width_settings_for_cache(),
            "canvas_crop": self.viewer.get_canvas_crop(),
        }

    def on_cache_only(self):
        final_vehicles, final_lanes, final_markers = self.viewer.get_confirmed_data()
        extra = self._persist_fields()
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
                accident_brief=extra["accident_brief"],
                lane_width_settings=extra["lane_width_settings"],
                canvas_crop=extra["canvas_crop"],
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败: {str(e)}")
            self._set_status(f"保存失败：{e}", kind="error")
            return
        self.cached_annotation = {
            "vehicles": final_vehicles,
            "lanes": final_lanes,
            "markers": final_markers,
            "data_fingerprint": annotation_fingerprint(
                final_vehicles,
                final_lanes,
                final_markers,
                extra["accident_brief"],
                extra["lane_width_settings"],
            ),
            "ai_analysis": persisted_ai_analysis,
            "liability_context": persisted_liability_context,
            "generated_html_path": persisted_html_path,
            "accident_brief": extra["accident_brief"],
            "lane_width_settings": extra["lane_width_settings"],
            "canvas_crop": extra["canvas_crop"],
        }
        stamp = datetime.now().strftime("%H:%M:%S")
        self.cache_only_btn.setStyleSheet(CACHE_BTN_FLASH_QSS)
        self._set_status(
            f"已保存编辑 {stamp}。含裁剪范围、车辆尺寸、本图车道宽、案情与运动路径，尚未生成建模。",
            kind="success",
        )

    def on_edit_mode_changed(self, text):
        self.add_vehicle_btn.setChecked(False)
        self.viewer.set_add_vehicle_mode(False)
        self.viewer.set_lane_draw_enabled(False)
        self.viewer.set_marker_add_enabled(False)

        mode_key = _edit_mode_key(text)
        is_case_mode = mode_key == CASE_BRIEF_MODE_LABEL
        is_motion_mode = mode_key == MOTION_MODE_LABEL
        is_crop_mode = mode_key == CROP_MODE_LABEL
        self._active_mode_key = mode_key
        btn = self._mode_buttons.get(mode_key)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        self._refresh_mode_item_styles()

        if is_case_mode:
            self.viewer.set_canvas_crop_mode(False)
            self.viewer.set_motion_mode(False)
            self.viewer.set_draw_mode(False)
            self.viewer.set_marker_mode(False)
            self._selected_veh = None
            self._show_accident_panel()
            self.show_all_checkbox.blockSignals(True)
            self.show_all_checkbox.setChecked(True)
            self.show_all_checkbox.blockSignals(False)
        else:
            self.show_all_checkbox.blockSignals(True)
            self.show_all_checkbox.setChecked(self.viewer.show_all_objects)
            self.show_all_checkbox.blockSignals(False)
            self._hide_accident_panel()
            if is_crop_mode:
                self.viewer.set_motion_mode(False)
                self.viewer.set_marker_mode(False)
                self.viewer.set_draw_mode(False)
                self.viewer.set_canvas_crop_mode(True)
                self._selected_veh = None
            elif mode_key == "道路线":
                self.viewer.set_canvas_crop_mode(False)
                self.viewer.set_motion_mode(False)
                self.viewer.set_marker_mode(False)
                self.viewer.set_draw_mode(True)
                self._selected_veh = None
            elif mode_key == "标记物":
                self.viewer.set_canvas_crop_mode(False)
                self.viewer.set_motion_mode(False)
                self.viewer.set_draw_mode(False)
                self.viewer.set_marker_mode(True)
                self._selected_veh = None
            elif is_motion_mode:
                self.viewer.set_canvas_crop_mode(False)
                self.viewer.set_draw_mode(False)
                self.viewer.set_marker_mode(False)
                self.viewer.set_motion_mode(True)
                self._selected_veh = None
            else:
                self.viewer.set_canvas_crop_mode(False)
                self.viewer.set_motion_mode(False)
                self.viewer.set_draw_mode(False)
                self.viewer.set_marker_mode(False)
        self.viewer.set_case_mode(is_case_mode)
        self._set_goal_hint(_GOAL_HINTS.get(mode_key, _GOAL_HINTS["车辆"]))
        self._refresh_mode_actions()
        self.viewer._emit_hint_context()

    def _place_accident_panel(self):
        vr = self.viewer.geometry()
        x = vr.right() - self.accident_panel.width() - 16
        y = vr.top() + 16
        self.accident_panel.move(max(vr.left() + 8, x), y)

    def _show_accident_panel(self):
        self._place_accident_panel()
        self._accident_panel_positioned = True
        self.accident_panel.show()
        self.accident_panel.raise_()

    def _hide_accident_panel(self):
        self.accident_panel.hide()

    def on_add_toggled(self, checked):
        mode = self._current_mode_key()
        if mode not in ("车辆", "道路线", "标记物"):
            self.add_vehicle_btn.setChecked(False)
            self._refresh_add_button_text()
            return
        if mode == "道路线":
            self.viewer.set_lane_draw_enabled(checked)
        elif mode == "标记物":
            self.viewer.set_marker_add_enabled(checked)
        else:
            self.viewer.set_draw_mode(False)
            self.viewer.set_marker_mode(False)
            self.viewer.set_add_vehicle_mode(checked)
            if checked:
                self._selected_veh = None
        self._refresh_add_button_text()
        self.viewer._emit_hint_context()

    def on_generate(self):
        final_vehicles, final_lanes, final_markers = self.viewer.get_confirmed_data()
        if not final_vehicles or not final_lanes:
            self._refresh_generate_enabled()
            return

        extra = self._persist_fields()
        run_ai_this_time = self.run_ai_checkbox.isChecked() and ai_enabled(
            self.ai_settings
        )

        if run_ai_this_time:
            self.generate_btn.setEnabled(False)
            self._ai_cancelled = False
            self._ai_request_id += 1
            request_id = self._ai_request_id
            self._open_prepare_status_dialog()
            self.ai_thread = LiabilityAnalysisThread(
                self.image_path,
                final_vehicles,
                final_lanes,
                self.ai_settings,
                accident_brief=extra["accident_brief"],
                lane_width_settings=extra["lane_width_settings"],
                markers=final_markers,
                canvas_crop=extra["canvas_crop"],
            )
            self.ai_thread.finished.connect(
                lambda ai_analysis, liability_context, rid=request_id: self._on_ai_finished(
                    final_vehicles,
                    final_lanes,
                    final_markers,
                    ai_analysis,
                    liability_context,
                    request_id=rid,
                )
            )
            self.ai_thread.error.connect(
                lambda err_msg, rid=request_id: self._on_ai_error(
                    final_vehicles,
                    final_lanes,
                    final_markers,
                    err_msg,
                    request_id=rid,
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
                persist_ai_analysis=None,
                persist_liability_context=None,
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成或保存失败: {str(e)}")

    def _open_prepare_status_dialog(self):
        self._stop_prepare_status()
        self._prepare_status_steps = list(_PREPARE_STATUS_STEPS)
        self._prepare_status_index = 0
        self.progress_dialog = QProgressDialog(
            self._prepare_status_steps[0],
            "取消",
            0,
            0,
            self,
        )
        self.progress_dialog.setWindowTitle("准备中")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.canceled.connect(self._cancel_ai_analysis)
        self._polish_progress_dialog()
        self.progress_dialog.show()
        if len(self._prepare_status_steps) > 1:
            self._prepare_status_timer.start()

    def _advance_prepare_status(self):
        if self.progress_dialog is None or not self._prepare_status_steps:
            return
        last_index = len(self._prepare_status_steps) - 1
        if self._prepare_status_index >= last_index:
            self._prepare_status_timer.stop()
            return
        self._prepare_status_index += 1
        self.progress_dialog.setLabelText(
            self._prepare_status_steps[self._prepare_status_index]
        )
        if self._prepare_status_index >= last_index:
            self._prepare_status_timer.stop()

    def _stop_prepare_status(self):
        if self._prepare_status_timer is not None:
            self._prepare_status_timer.stop()
        self._prepare_status_steps = []
        self._prepare_status_index = 0

    def _cancel_ai_analysis(self):
        if self._ai_cancelled and self.progress_dialog is None:
            return
        self._ai_cancelled = True
        self._ai_request_id += 1
        thread = self.ai_thread
        self.ai_thread = None
        if thread is not None:
            try:
                thread.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                thread.error.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._close_progress_dialog()

    def _close_progress_dialog(self):
        self._stop_prepare_status()
        dialog = self.progress_dialog
        self.progress_dialog = None
        if dialog is not None:
            try:
                dialog.canceled.disconnect(self._cancel_ai_analysis)
            except (RuntimeError, TypeError):
                pass
            dialog.close()
            dialog.deleteLater()
        self._refresh_generate_enabled()

    def _polish_progress_dialog(self):
        if self.progress_dialog is None:
            return
        self.progress_dialog.setFixedSize(360, 200)
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
        self, final_vehicles, final_lanes, final_markers, ai_analysis, liability_context,
        request_id=0,
    ):
        if self._ai_cancelled or request_id != self._ai_request_id:
            return
        self.ai_thread = None
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
        finally:
            self._close_progress_dialog()

    def _on_ai_error(self, final_vehicles, final_lanes, final_markers, err_msg, request_id=0):
        if self._ai_cancelled or request_id != self._ai_request_id:
            return
        self.ai_thread = None
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
        extra = self._persist_fields()
        html_path = generate_html(
            self.image_path,
            final_vehicles,
            final_lanes,
            final_markers,
            save_measurements_url=save_url,
            ai_analysis=html_ai_analysis,
            liability_context=html_liability_context,
            lane_width_settings=extra["lane_width_settings"],
            canvas_crop=extra["canvas_crop"],
        )
        save_annotation(
            self.image_path,
            final_vehicles,
            final_lanes,
            final_markers,
            ai_analysis=persist_ai_analysis,
            liability_context=persist_liability_context,
            generated_html_path=html_path,
            accident_brief=extra["accident_brief"],
            lane_width_settings=extra["lane_width_settings"],
            canvas_crop=extra["canvas_crop"],
        )
        self.cached_annotation = {
            "vehicles": final_vehicles,
            "lanes": final_lanes,
            "markers": final_markers,
            "data_fingerprint": annotation_fingerprint(
                final_vehicles,
                final_lanes,
                final_markers,
                extra["accident_brief"],
                extra["lane_width_settings"],
            ),
            "ai_analysis": persist_ai_analysis,
            "liability_context": persist_liability_context,
            "generated_html_path": html_path,
            "accident_brief": extra["accident_brief"],
            "lane_width_settings": extra["lane_width_settings"],
            "canvas_crop": extra["canvas_crop"],
        }
        QDesktopServices.openUrl(QUrl.fromLocalFile(html_path))
        base = os.path.basename(html_path)
        self._set_status(
            f"已生成并打开: {base}。可继续修改后再次点击「识别确认」。",
            kind="success",
        )

    def closeEvent(self, event):
        if self.ai_thread is not None and self.ai_thread.isRunning():
            self._cancel_ai_analysis()
        super().closeEvent(event)
