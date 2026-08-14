from PySide6.QtWidgets import (
    QApplication,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsEllipseItem,
    QGraphicsTextItem,
    QGraphicsItem,
    QMenu,
    QMessageBox,
    QToolTip,
    QLabel,
)
from PySide6.QtGui import QPixmap, QPen, QColor, QPolygonF, QBrush, QFont, QCursor, QIcon, QPainter
from PySide6.QtCore import Qt, QPoint, QPointF, Signal, QLineF, QTimer, QEvent
import math
import numpy as np
import cv2

from core.vehicle_model_settings import load_vehicle_model_settings
from core.vehicle_presets import (
    ensure_vehicle_preset,
    STANDARD_VEHICLE_TYPES,
    STANDARD_VEHICLE_TYPE_SET,
)
from core.marker_presets import (
    DEFAULT_MARKER_TYPE,
    STANDARD_MARKER_TYPES,
    STANDARD_MARKER_TYPE_SET,
    ensure_marker_preset,
    next_marker_id,
)
from utils.vehicle_identity import ensure_vehicle_ids, next_vehicle_id
from gui.vehicle_size_dialog import VehicleSizeDialog
from gui.lane_width_dialog import LaneWidthDialog
from gui.motion_path_editor import MotionPathEditorMixin
from gui.motion_path_utils import ensure_motion_fields
from utils.vehicle_appearance import (
    COLOR_MODE_AUTO,
    COLOR_MODE_GRAB,
    COLOR_MODE_NATIVE,
    DEFAULT_PPM,
    default_color_sample_point,
    ensure_vehicle_color_modes,
    get_vehicle_color_mode,
    set_vehicle_color_mode,
)

HANDLE_RADIUS = 12.0
MARKER_RADIUS = 18.0
SELECTION_OVERLAY_Z = 80
SELECTION_OVERLAY_COLOR = QColor(220, 0, 0)
SELECTION_OVERLAY_WIDTH = 3.0
SELECTION_BREATH_INTERVAL_MS = 80
SELECTION_BREATH_PHASE_STEP = 0.32
LANE_OVERLAP_THRESHOLD_PX = 10.0
# Enlarge non-draggable hit zone so polygon does not start a body-drag when aiming at handles
HANDLE_BLOCK_SLACK = 6.0
# Degrees per wheel notch when rotating selected vehicle (Qt angleDelta is typically ±120 per step)
VEHICLE_WHEEL_ROTATE_DEG = 2.0
# Lane alignment needs finer wheel control than vehicle heading adjustment.
LANE_WHEEL_ROTATE_DEG = 0.4
LANE_PEN_WIDTH = 12
LANE_LABEL_OFFSET = 18.0
# ALT+wheel zoom relative to the fit-to-view scale.
ZOOM_FACTOR_PER_STEP = 1.15
ZOOM_MIN_RELATIVE = 0.25
ZOOM_MAX_RELATIVE = 12.0
# Left/Right arrow keys step the heading indicator (direction_offset) by one quarter turn
# relative to its current position, independent of the OBB angle. Right = clockwise on screen,
# Left = counter-clockwise. Up/Down are intentionally not bound: an "absolute" snap requires
# knowing which way is visually "up" for a given box, which is ambiguous once the box is rotated,
# so only relative stepping is exposed to the user.
DIRECTION_STEP_KEYS = {
    Qt.Key_Right: 90.0,
    Qt.Key_Left: -90.0,
}
# Cab/cargo dual paint (matches GLB 05/06/07 split types).
SPLIT_COLOR_VEHICLE_TYPES = frozenset(
    {"大型罐式货车", "大型厢式货车", "牵引车及挂车"}
)
EYEDROPPER_BLINK_INTERVAL_MS = 90
EYEDROPPER_TARGET_LABELS = {
    "body_color": "车身/车头",
    "cargo_color": "车尾",
}
_COLOR_KEY_TO_REGION = {
    "body_color": "body",
    "cargo_color": "cargo",
}
_COLOR_MODE_LABELS = {
    COLOR_MODE_GRAB: "抓取颜色",
    COLOR_MODE_AUTO: "自动颜色",
    COLOR_MODE_NATIVE: "原生颜色",
}


def _lane_pen(is_solid=True):
    pen = QPen(Qt.green, LANE_PEN_WIDTH)
    pen.setCapStyle(Qt.FlatCap)
    if not is_solid:
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([2.0, 2.0])
    return pen


def _is_solid_lane_index(index, total):
    if total <= 0:
        return True
    return index == 0 or index == 1 or index == total - 1


def _vehicle_tooltip_text(veh):
    vehicle_id = str(veh.get("vehicle_id", "") or "未编号")
    cn = str(veh.get("class_name", ""))
    conf = float(veh.get("confidence", 0.0))
    pt = str(veh.get("preset_type", "小客车"))
    return f"车辆ID: {vehicle_id}\n识别类型: {cn}\n置信度: {conf:.2f}\n标准车型: {pt}"


def _marker_tooltip_text(marker):
    marker_id = str(marker.get("marker_id", "") or "未编号")
    marker_type = str(marker.get("marker_type", DEFAULT_MARKER_TYPE))
    return f"标记物ID: {marker_id}\n标记物类型: {marker_type}"


class VehiclePolygonItem(QGraphicsPolygonItem):
    """Vehicle OBB polygon; drag body to translate (updates data dict)."""

    def __init__(self, viewer, polygon, veh_data):
        super().__init__(polygon)
        self._viewer = viewer
        self._veh = veh_data
        self._moving = False
        self._press_scene = None
        self._start_center = None
        self.setAcceptHoverEvents(True)

    def mousePressEvent(self, event):
        if getattr(self._viewer, "motion_mode", False):
            # Path-edit: vehicles do not accept clicks (points go through to the view).
            if getattr(self._viewer, "_path_edit_active", False):
                event.ignore()
                return
            # Motion page: select only, never drag the box.
            if event.button() == Qt.LeftButton:
                super().mousePressEvent(event)
                event.accept()
            else:
                super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            sp = event.scenePos()
            if self._viewer._scene_pos_on_vehicle_resize_handle(self, sp):
                super().mousePressEvent(event)
                event.accept()
                return
            self._moving = True
            self._press_scene = sp
            self._start_center = (self._veh["x_center"], self._veh["y_center"])
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            event.accept()

    def mouseMoveEvent(self, event):
        if getattr(self._viewer, "motion_mode", False):
            return
        if self._moving and self._press_scene is not None:
            delta = event.scenePos() - self._press_scene
            self._veh["x_center"] = self._start_center[0] + delta.x()
            self._veh["y_center"] = self._start_center[1] + delta.y()
            self._viewer._refresh_vehicle_polygon(self)
            self._viewer._reposition_handles(self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._moving = False
            self._press_scene = None
            self._start_center = None
        super().mouseReleaseEvent(event)


class VehicleResizeHandle(QGraphicsEllipseItem):
    """Corner handle for resizing OBB."""

    def __init__(self, viewer, vehicle_item, corner_index):
        r = HANDLE_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._viewer = viewer
        self._vehicle_item = vehicle_item
        self._corner_index = corner_index
        self._dragging = False
        self.setBrush(QBrush(QColor(255, 220, 0)))
        self.setPen(QPen(Qt.black, 1))
        self.setZValue(50)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsEllipseItem.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)
        self.setCursor(Qt.SizeFDiagCursor)

    def mousePressEvent(self, event):
        if getattr(self._viewer, "motion_mode", False):
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.grabMouse()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._viewer._resize_vehicle_at_corner(
                self._vehicle_item, self._corner_index, event.scenePos()
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.ungrabMouse()
        super().mouseReleaseEvent(event)


class MarkerCircleItem(QGraphicsEllipseItem):
    """Editor marker circle; drag body to move the marker center."""

    def __init__(self, viewer, marker_data):
        r = MARKER_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self._viewer = viewer
        self._marker = marker_data
        self._moving = False
        self._press_scene = None
        self._start_center = None
        self.setAcceptHoverEvents(True)
        self.setBrush(QBrush(QColor(255, 193, 7, 150)))
        self.setPen(QPen(QColor(183, 28, 28), 3))
        self.setZValue(35)
        self.setToolTip(_marker_tooltip_text(marker_data))
        self.setPos(float(marker_data["x_center"]), float(marker_data["y_center"]))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._moving = True
            self._press_scene = event.scenePos()
            self._start_center = (
                float(self._marker["x_center"]),
                float(self._marker["y_center"]),
            )
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            event.accept()

    def mouseMoveEvent(self, event):
        if self._moving and self._press_scene is not None:
            delta = event.scenePos() - self._press_scene
            self._marker["x_center"] = self._start_center[0] + delta.x()
            self._marker["y_center"] = self._start_center[1] + delta.y()
            self.setPos(float(self._marker["x_center"]), float(self._marker["y_center"]))
            self._viewer._refresh_marker_name_label(self)
            self._viewer._sync_selection_overlay(self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._moving = False
            self._press_scene = None
            self._start_center = None
        super().mouseReleaseEvent(event)


class ImageViewer(MotionPathEditorMixin, QGraphicsView):
    vehicle_selection_changed = Signal(object)
    # Emits how many vehicles are currently selected (0, 1, or more with Ctrl multi-select),
    # so the host window can show/hide the direction-key hint text.
    vehicle_selection_count_changed = Signal(int)
    # Emitted after vehicles / lanes / markers are added or removed.
    objects_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(self.renderHints() | self.renderHints().Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        self.image_item = None
        self.items_data = {}

        self.draw_mode = False
        self.add_vehicle_mode = False
        self.marker_mode = False
        self.lane_draw_enabled = False
        self.marker_add_enabled = False
        self.drawing = False
        self.current_line = None
        self.start_point = None
        self.base_vector = None
        self.line_spacing = None

        self._add_rect_preview = None
        self._add_rect_start = None
        self._add_drawing = False

        self._handle_map = {}
        self._front_arrow_map = {}
        self._vehicle_label_map = {}
        self._marker_label_map = {}
        self._panning = False
        self._pan_anchor = QPointF()
        self._pan_moved = False
        self._pan_button = None
        self._space_down = False
        self._fit_scale = 1.0

        self._drag_lane = False
        self._lane_drag_index = None
        self._lane_drag_press_scene = None
        self._lane_drag_start_lines = None
        self._lane_drag_n = None
        self._lane_drag_O = None
        self._lane_drag_ux = None
        self._lane_drag_uy = None
        self._lane_label_map = {}
        # Per-image override: (lane_width, emergency_width). None => use modeling defaults.
        self._lane_width_override = None
        self._auto_fit_image = True

        self.show_all_objects = True
        self.case_mode = False

        # Eyedropper: "body_color" | "cargo_color" | None
        self._eyedropper_target = None
        self._eyedropper_vehicle = None
        self._eyedropper_blink_on = False
        self._eyedropper_timer = QTimer(self)
        self._eyedropper_timer.setInterval(EYEDROPPER_BLINK_INTERVAL_MS)
        self._eyedropper_timer.timeout.connect(self._tick_eyedropper_blink)
        self._eyedropper_hint = QLabel(self)
        self._eyedropper_hint.setAlignment(Qt.AlignCenter)
        self._eyedropper_hint.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._eyedropper_hint.hide()

        self._selection_overlay_map = {}
        self._breath_phase = 0.0
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(SELECTION_BREATH_INTERVAL_MS)
        self._breath_timer.timeout.connect(self._tick_breath)

        self._init_motion_path_state()

        self.setFocusPolicy(Qt.StrongFocus)
        self.scene.selectionChanged.connect(self._on_selection_changed)
        # Catch Alt+wheel on the viewport: on Windows, Alt often fails to appear
        # in QWheelEvent.modifiers(), and some events only reach the viewport.
        self.viewport().installEventFilter(self)

    def _fit_image_to_view(self):
        if self._auto_fit_image and self.image_item is not None:
            self.fitInView(self.image_item, Qt.KeepAspectRatio)
            self._fit_scale = max(self.transform().m11(), 1e-9)
            self._refresh_all_overlay_labels()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_image_to_view()
        self._layout_eyedropper_hint()

    def _current_view_scale(self):
        return max(abs(self.transform().m11()), 1e-9)

    def _view_overflows_image(self):
        if self.image_item is None:
            return False
        hs = self.horizontalScrollBar()
        vs = self.verticalScrollBar()
        if hs.maximum() > 0 or vs.maximum() > 0:
            return True
        if self._fit_scale <= 0:
            return False
        return self._current_view_scale() > self._fit_scale * 1.02

    def _has_selected_editable_object(self):
        for item in self.scene.selectedItems():
            if item in self.items_data:
                return True
            if getattr(item, "_vehicle_item", None) is not None:
                return True
            if self._vehicle_item_from_front_arrow(item) is not None:
                return True
        return False

    def _alt_is_held(self, event=None):
        """Windows often omits Alt from QWheelEvent.modifiers(); query real key state."""
        mods = QApplication.keyboardModifiers()
        if event is not None:
            mods |= event.modifiers()
        return bool(mods & Qt.AltModifier)

    def _wheel_delta_y(self, event):
        delta = event.angleDelta()
        if delta.y() != 0:
            return delta.y()
        # Some devices / Alt combinations report horizontal delta only.
        return delta.x()

    def _zoom_at_view_pos(self, view_pos, zoom_in):
        if self.image_item is None:
            return
        if self._auto_fit_image:
            self._fit_scale = max(abs(self.transform().m11()), 1e-9)
            self._auto_fit_image = False
        factor = ZOOM_FACTOR_PER_STEP if zoom_in else (1.0 / ZOOM_FACTOR_PER_STEP)
        current = self._current_view_scale()
        target = current * factor
        min_scale = self._fit_scale * ZOOM_MIN_RELATIVE
        max_scale = self._fit_scale * ZOOM_MAX_RELATIVE
        if target < min_scale:
            factor = min_scale / current if current > 1e-12 else 1.0
        elif target > max_scale:
            factor = max_scale / current if current > 1e-12 else 1.0
        if abs(factor - 1.0) < 1e-6:
            return

        if isinstance(view_pos, QPointF):
            view_pos = view_pos.toPoint()
        elif not isinstance(view_pos, QPoint):
            view_pos = QPoint(int(view_pos.x()), int(view_pos.y()))

        # Keep the scene point under the cursor stable via scrollbars.
        # (scale+translate fights fitInView scrollbar centering on Windows.)
        scene_pos = self.mapToScene(view_pos)
        self.scale(factor, factor)
        mapped = self.mapFromScene(scene_pos)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + (mapped.x() - view_pos.x())
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + (mapped.y() - view_pos.y())
        )
        self._refresh_all_overlay_labels()

    def _try_alt_zoom(self, event):
        """Return True if Alt-zoom consumed the wheel event.

        Alt means zoom intentionally, so it wins over selection rotate.
        """
        if not self._alt_is_held(event):
            return False
        dy = self._wheel_delta_y(event)
        if dy == 0:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self._zoom_at_view_pos(pos, zoom_in=dy > 0)
        event.accept()
        return True

    def eventFilter(self, watched, event):
        if watched is self.viewport() and event.type() == QEvent.Type.Wheel:
            if self._try_alt_zoom(event):
                return True
        return super().eventFilter(watched, event)

    def _label_pos_for_anchor(self, anchor, rect, align="top_center"):
        """Place an ItemIgnoresTransformations label so its visual corner/center
        sits at the given scene anchor using screen-pixel offsets."""
        view_pt = self.mapFromScene(anchor)
        if align == "top_center":
            top_left = QPointF(
                view_pt.x() - rect.width() * 0.5,
                view_pt.y() - rect.height(),
            )
        elif align == "bottom_left":
            # YOLO-style: label sits just above the box, left edges flush.
            top_left = QPointF(view_pt.x(), view_pt.y() - rect.height())
        else:
            top_left = QPointF(
                view_pt.x() - rect.width() * 0.5,
                view_pt.y() - rect.height() * 0.5,
            )
        return self.mapToScene(top_left.toPoint())

    def _refresh_all_overlay_labels(self):
        for vehicle_item in list(self._vehicle_label_map.keys()):
            self._refresh_vehicle_id_label(vehicle_item)
        for marker_item in list(self._marker_label_map.keys()):
            self._refresh_marker_name_label(marker_item)
        self._refresh_lane_labels()
        if hasattr(self, "_refresh_path_duration_labels"):
            self._refresh_path_duration_labels()

    def _emit_objects_changed(self):
        self.objects_changed.emit()

    def _configure_observation_item(self, item):
        """Labels / arrows / path overlays: visible only, never capture mouse."""
        if item is None:
            return
        # Never reconfigure business objects (vehicles / lanes / markers).
        if item in self.items_data:
            return
        item.setAcceptedMouseButtons(Qt.NoButton)
        item.setAcceptHoverEvents(False)
        item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        item.setFlag(QGraphicsItem.ItemIsFocusable, False)

    def _is_observation_overlay(self, item):
        """True for decorative graphics that must never block hit-testing."""
        if item is None:
            return False
        # Business objects are never observation overlays.
        if item in self.items_data:
            return False
        if isinstance(item, VehicleResizeHandle):
            return False
        if item in self._lane_label_map.values():
            return True
        if item in self._vehicle_label_map.values():
            return True
        if item in self._marker_label_map.values():
            return True
        if item in self._front_arrow_map.values():
            return True
        if item in self._selection_overlay_map.values():
            return True
        if getattr(self, "_path_duration_label", None) is item:
            return True
        if item in getattr(self, "_path_point_items", []):
            return True
        if item in getattr(self, "_path_drive_label_items", []):
            return True
        if item in getattr(self, "_path_line_items", []):
            return True
        for overlay in (getattr(self, "_finished_path_overlays", None) or {}).values():
            if item is overlay.get("duration_label") or item is overlay.get("center_line"):
                return True
            if item in (overlay.get("points") or []) or item in (overlay.get("lines") or []):
                return True
            if item in (overlay.get("drive_labels") or []):
                return True
        return False

    def _editable_item_at_view_pos(self, view_pos):
        """Topmost current-layer business object under the cursor.

        Skips observation overlays and foreign-layer objects so 「显示全部图层」
        is visual-only and never blocks the active layer's mouse ops.
        """
        if self.case_mode:
            return None
        current = self._current_mode_type()
        if current is None:
            return None
        for it in self.items(view_pos):
            if isinstance(it, VehicleResizeHandle):
                vitem = it._vehicle_item
                if (
                    current == "vehicle"
                    and vitem in self.items_data
                    and self.items_data[vitem]["type"] == "vehicle"
                ):
                    return vitem
                continue
            if self._is_observation_overlay(it):
                continue
            if it not in self.items_data:
                continue
            # Foreign layers: display only — keep searching underneath.
            if self.items_data[it]["type"] != current:
                continue
            return it
        return None

    def _scene_pos_on_blank_image(self, scene_pos):
        """True when the point is on the pixmap and not on an interactive current-layer item."""
        if self.image_item is None:
            return False
        current = self._current_mode_type()
        items = self.scene.items(scene_pos)
        for it in items:
            if it is self.image_item:
                continue
            if self._is_observation_overlay(it):
                continue
            if it is self._add_rect_preview or it is self.current_line:
                continue
            if it in self.items_data:
                # Foreign layers are display-only and must not block pan / layer-A mouse.
                if self.case_mode or current is None or self.items_data[it]["type"] != current:
                    continue
                return False
            if getattr(it, "_vehicle_item", None) is not None:
                if current == "vehicle":
                    return False
                continue
            if isinstance(
                it,
                (
                    QGraphicsPolygonItem,
                    QGraphicsEllipseItem,
                    QGraphicsLineItem,
                    QGraphicsRectItem,
                ),
            ):
                # Ignore non-interactive leftovers; only block on real input-accepting items.
                if it.acceptedMouseButtons() == Qt.NoButton:
                    continue
                if it.zValue() >= 1:
                    return False
        local = self.image_item.mapFromScene(scene_pos)
        br = self.image_item.boundingRect()
        return br.contains(local)

    def _begin_pan(self, view_pos, button=None):
        self._panning = True
        self._pan_moved = False
        self._pan_button = button
        self._pan_anchor = view_pos
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _end_pan(self):
        was_moved = self._pan_moved
        pan_button = self._pan_button
        self._panning = False
        self._pan_moved = False
        self._pan_button = None
        self.viewport().unsetCursor()
        if pan_button == Qt.LeftButton and not was_moved:
            self.scene.clearSelection()
            self._on_selection_changed()

    def _apply_vehicle_pointer_block_for_draw_mode(self, block):
        buttons = Qt.NoButton if block else (Qt.LeftButton | Qt.RightButton | Qt.MiddleButton)
        for item, info in self.items_data.items():
            if info["type"] != "vehicle":
                continue
            item.setAcceptedMouseButtons(buttons)
            item.setAcceptHoverEvents(not block)
            item.setFlag(QGraphicsItem.ItemIsSelectable, not block)

    def _set_lane_interaction_enabled(self, enabled):
        buttons = (Qt.LeftButton | Qt.RightButton | Qt.MiddleButton) if enabled else Qt.NoButton
        for item, info in self.items_data.items():
            if info["type"] != "lane":
                continue
            item.setAcceptedMouseButtons(buttons)
            item.setAcceptHoverEvents(bool(enabled))
            item.setFlag(QGraphicsItem.ItemIsSelectable, enabled)
            if not enabled:
                item.setSelected(False)

    def _set_marker_interaction_enabled(self, enabled):
        buttons = (Qt.LeftButton | Qt.RightButton | Qt.MiddleButton) if enabled else Qt.NoButton
        for item, info in self.items_data.items():
            if info["type"] != "marker":
                continue
            item.setAcceptedMouseButtons(buttons)
            item.setAcceptHoverEvents(bool(enabled))
            item.setFlag(QGraphicsItem.ItemIsSelectable, enabled)
            if not enabled:
                item.setSelected(False)

    def _sync_layer_interactions(self):
        """Only the active dropdown layer accepts mouse; other layers are visual-only."""
        if self.case_mode:
            self._apply_vehicle_pointer_block_for_draw_mode(True)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(False)
            return
        if self.motion_mode:
            path_edit = bool(getattr(self, "_path_edit_active", False))
            self._apply_vehicle_pointer_block_for_draw_mode(path_edit)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(False)
            return
        current = self._current_mode_type()
        self._apply_vehicle_pointer_block_for_draw_mode(current != "vehicle")
        self._set_lane_interaction_enabled(current == "lane")
        self._set_marker_interaction_enabled(current == "marker")

    def set_draw_mode(self, enabled):
        self.draw_mode = enabled
        if enabled:
            if self.motion_mode:
                self.set_motion_mode(False)
            self.add_vehicle_mode = False
            self.marker_mode = False
            self.marker_add_enabled = False
            self._add_drawing = False
            if self._add_rect_preview:
                self.scene.removeItem(self._add_rect_preview)
                self._add_rect_preview = None
            self._add_rect_start = None
            self._reset_lane_drag_state()
            self.setDragMode(QGraphicsView.NoDrag)
            self.unsetCursor()
            self.scene.clearSelection()
            self._clear_all_handles()
            self._apply_vehicle_pointer_block_for_draw_mode(True)
            self._set_lane_interaction_enabled(True)
            self._set_marker_interaction_enabled(False)
            self._raise_lane_items_above_vehicles()
        else:
            self.lane_draw_enabled = False
            self.drawing = False
            self.current_line = None
            self._reset_lane_drag_state()
            self._set_lane_interaction_enabled(False)
            if not self.motion_mode and not self.case_mode:
                self._apply_vehicle_pointer_block_for_draw_mode(False)
            self._restore_lane_item_z()
            self.setCursor(Qt.ArrowCursor)
        self._apply_type_visibility()

    def set_lane_draw_enabled(self, enabled):
        if not self.draw_mode:
            self.lane_draw_enabled = False
            self.unsetCursor()
            return
        self.lane_draw_enabled = bool(enabled)
        if self.lane_draw_enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.drawing = False
            self.current_line = None
            self.unsetCursor()

    def _raise_lane_items_above_vehicles(self):
        for item, info in self.items_data.items():
            if info["type"] == "lane":
                item.setZValue(5)

    def _restore_lane_item_z(self):
        for item, info in self.items_data.items():
            if info["type"] == "lane":
                item.setZValue(0)

    def _ordered_lane_items(self):
        return [
            it
            for it, data in self.items_data.items()
            if data["type"] == "lane"
        ]

    def _is_last_lane_item(self, item):
        lanes = self._ordered_lane_items()
        return bool(lanes) and lanes[-1] is item

    def _pick_lane_under_cursor(self, viewport_pos):
        for it in self.items(viewport_pos):
            if self._is_observation_overlay(it):
                continue
            if it not in self.items_data:
                continue
            if self.items_data[it]["type"] == "lane":
                return it
        return None

    def _reset_lane_drag_state(self):
        self._drag_lane = False
        self._lane_drag_index = None
        self._lane_drag_press_scene = None
        self._lane_drag_start_lines = None
        self._lane_drag_n = None
        self._lane_drag_O = None
        self._lane_drag_ux = None
        self._lane_drag_uy = None

    def _refresh_lane_labels(self):
        lanes = self._ordered_lane_items()
        live_lanes = set(lanes)
        for lane_item, label in list(self._lane_label_map.items()):
            if lane_item not in live_lanes:
                self.scene.removeItem(label)
                del self._lane_label_map[lane_item]

        for idx, lane_item in enumerate(lanes, start=1):
            label = self._lane_label_map.get(lane_item)
            if label is None:
                label = QGraphicsTextItem()
                font = QFont()
                font.setPointSize(14)
                font.setBold(True)
                label.setFont(font)
                label.setDefaultTextColor(QColor(Qt.green))
                self._configure_observation_item(label)
                label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                label.setZValue(60)
                self.scene.addItem(label)
                self._lane_label_map[lane_item] = label

            label.setDefaultTextColor(QColor(Qt.green))
            label.setPlainText(str(idx))
            line = lane_item.line()
            dx, dy = line.dx(), line.dy()
            length = math.hypot(dx, dy)
            if length > 1e-9:
                nx, ny = -dy / length, dx / length
            else:
                nx, ny = 0.0, -1.0
            mx = (line.x1() + line.x2()) * 0.5 + nx * LANE_LABEL_OFFSET
            my = (line.y1() + line.y2()) * 0.5 + ny * LANE_LABEL_OFFSET
            rect = label.boundingRect()
            label.setPos(
                self._label_pos_for_anchor(QPointF(mx, my), rect, align="center")
            )
        self._apply_lane_styles()

    def _apply_lane_styles(self):
        lanes = self._ordered_lane_items()
        total = len(lanes)
        for idx, lane_item in enumerate(lanes):
            is_solid = _is_solid_lane_index(idx, total)
            lane_item.setPen(_lane_pen(is_solid))

    def _image_bounds_wh(self):
        if self.image_item is None:
            return 1, 1
        r = self.image_item.boundingRect()
        return max(1, int(r.width())), max(1, int(r.height()))

    def _extend_line_to_image_bounds(self, x1, y1, x2, y2):
        w, h = self._image_bounds_wh()
        dx = x2 - x1
        dy = y2 - y1
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            return 0.0, 0.0, float(w), float(h)
        ux, uy = dx / ln, dy / ln
        cx, cy = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        span = max(w, h, 400) * 4
        ax = int(round(cx - ux * span))
        ay = int(round(cy - uy * span))
        bx = int(round(cx + ux * span))
        by = int(round(cy + uy * span))
        p1 = [ax, ay]
        p2 = [bx, by]
        ok, p1, p2 = cv2.clipLine((0, 0, w, h), p1, p2)
        if not ok:
            return (
                float(max(0, min(x1, w))),
                float(max(0, min(y1, h))),
                float(max(0, min(x2, w))),
                float(max(0, min(y2, h))),
            )
        return float(p1[0]), float(p1[1]), float(p2[0]), float(p2[1])

    def _is_overlapping_existing_lane(self, x1, y1, x2, y2, threshold=LANE_OVERLAP_THRESHOLD_PX):
        mx = (x1 + x2) * 0.5
        my = (y1 + y2) * 0.5
        for it, info in self.items_data.items():
            if info["type"] != "lane":
                continue
            existing = it.line()
            dx = existing.dx()
            dy = existing.dy()
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            ux, uy = dx / length, dy / length
            nx, ny = -uy, ux
            d = abs((mx - existing.x1()) * nx + (my - existing.y1()) * ny)
            if d < threshold:
                return True
        return False

    def _sync_lane_data_from_item(self, item):
        l = item.line()
        self.items_data[item]["data"] = {
            "x1": l.x1(),
            "y1": l.y1(),
            "x2": l.x2(),
            "y2": l.y2(),
        }

    @staticmethod
    def _read_lane_width_settings():
        settings = load_vehicle_model_settings()
        lane_width = max(float(settings.get("laneWidth", 3.75)), 1e-6)
        emergency_width = max(float(settings.get("emergencyLaneWidth", 3.0)), 1e-6)
        return lane_width, emergency_width

    def _lane_width_settings(self):
        if self._lane_width_override is not None:
            return self._lane_width_override
        return self._read_lane_width_settings()

    def set_lane_width_override(self, lane_width, emergency_lane_width):
        self._lane_width_override = (
            max(float(lane_width), 1e-6),
            max(float(emergency_lane_width), 1e-6),
        )

    def get_lane_width_settings_for_cache(self):
        """Return override dict for annotation cache, or None if using globals."""
        if self._lane_width_override is None:
            return None
        lane_width, emergency_width = self._lane_width_override
        return {
            "laneWidth": float(lane_width),
            "emergencyLaneWidth": float(emergency_width),
        }

    def apply_lane_width_settings_from_cache(self, settings):
        if not isinstance(settings, dict):
            self._lane_width_override = None
            return
        try:
            lane_width = float(settings.get("laneWidth"))
            emergency_width = float(settings.get("emergencyLaneWidth"))
        except (TypeError, ValueError):
            self._lane_width_override = None
            return
        if lane_width <= 0 or emergency_width <= 0:
            self._lane_width_override = None
            return
        self._lane_width_override = (lane_width, emergency_width)

    def _lane_logical_offset(self, lane_index):
        if lane_index <= 0:
            return 0.0
        lane_width, emergency_width = self._lane_width_settings()
        return emergency_width + (lane_index - 1) * lane_width

    def _lane_offset_from_emergency_spacing(self, lane_index, emergency_spacing_px):
        if lane_index <= 0:
            return 0.0
        _, emergency_width = self._lane_width_settings()
        scale = float(emergency_spacing_px) / emergency_width
        return self._lane_logical_offset(lane_index) * scale

    def _nearest_lane_snap_distance(self, dist, emergency_spacing_px, max_extra=8):
        if emergency_spacing_px <= 0:
            return dist
        lanes = self._ordered_lane_items()
        _, emergency_width = self._lane_width_settings()
        scale = float(emergency_spacing_px) / emergency_width
        max_index = max(len(lanes) + max_extra, 2)
        candidates = [0.0]
        for idx in range(1, max_index + 1):
            offset = self._lane_logical_offset(idx) * scale
            candidates.append(offset)
            candidates.append(-offset)
        return min(candidates, key=lambda candidate: abs(candidate - dist))

    def _prepare_lane_drag_geometry(self, lane_item, press_scene):
        lanes = self._ordered_lane_items()
        if lane_item not in lanes:
            return False
        lane_index = lanes.index(lane_item)
        L0 = lanes[0].line()
        ox = (L0.x1() + L0.x2()) * 0.5
        oy = (L0.y1() + L0.y2()) * 0.5
        dx, dy = L0.dx(), L0.dy()
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            return False
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy, ux
        if len(lanes) >= 2:
            l1 = lanes[1].line()
            mx = (l1.x1() + l1.x2()) * 0.5
            my = (l1.y1() + l1.y2()) * 0.5
            if (mx - ox) * nx + (my - oy) * ny < 0:
                nx, ny = -nx, -ny
        self._lane_drag_O = (ox, oy)
        self._lane_drag_n = (nx, ny)
        self._lane_drag_ux = ux
        self._lane_drag_uy = uy
        self._lane_drag_index = lane_index
        self._lane_drag_press_scene = press_scene
        self._lane_drag_start_lines = [lane.line() for lane in lanes]
        return True

    def _relayout_parallel_lanes_from_emergency_spacing(self, spacing_px):
        lanes = self._ordered_lane_items()
        if (
            len(lanes) < 2
            or self._lane_drag_O is None
            or self._lane_drag_n is None
        ):
            return
        ox, oy = self._lane_drag_O
        nx, ny = self._lane_drag_n
        ux, uy = self._lane_drag_ux, self._lane_drag_uy
        emergency_spacing_px = max(float(spacing_px), 2.0)
        for j in range(1, len(lanes)):
            item = lanes[j]
            offset = self._lane_offset_from_emergency_spacing(j, emergency_spacing_px)
            px = ox + offset * nx
            py = oy + offset * ny
            x1, y1, x2, y2 = self._extend_line_to_image_bounds(
                px, py, px + ux, py + uy
            )
            item.setLine(x1, y1, x2, y2)
            self._sync_lane_data_from_item(item)
        self.update_line_constraints()
        self._sync_all_lane_overlays()

    def _translate_lanes_from_drag_start(self, dx, dy):
        lanes = self._ordered_lane_items()
        if not self._lane_drag_start_lines:
            return
        for item, start_line in zip(lanes, self._lane_drag_start_lines):
            x1, y1, x2, y2 = self._extend_line_to_image_bounds(
                start_line.x1() + dx,
                start_line.y1() + dy,
                start_line.x2() + dx,
                start_line.y2() + dy,
            )
            item.setLine(x1, y1, x2, y2)
            self._sync_lane_data_from_item(item)
        self.update_line_constraints()
        self._sync_all_lane_overlays()

    def _rotate_lanes(self, angle_delta):
        lanes = self._ordered_lane_items()
        if not lanes:
            return

        mids = []
        for item in lanes:
            line = item.line()
            mids.append(
                (
                    (line.x1() + line.x2()) * 0.5,
                    (line.y1() + line.y2()) * 0.5,
                )
            )
        pivot_x = sum(p[0] for p in mids) / len(mids)
        pivot_y = sum(p[1] for p in mids) / len(mids)
        cos_a = math.cos(angle_delta)
        sin_a = math.sin(angle_delta)

        for item, (mx, my) in zip(lanes, mids):
            line = item.line()
            dx, dy = line.dx(), line.dy()
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            ux = dx / length
            uy = dy / length
            rmx = pivot_x + (mx - pivot_x) * cos_a - (my - pivot_y) * sin_a
            rmy = pivot_y + (mx - pivot_x) * sin_a + (my - pivot_y) * cos_a
            rux = ux * cos_a - uy * sin_a
            ruy = ux * sin_a + uy * cos_a
            x1, y1, x2, y2 = self._extend_line_to_image_bounds(
                rmx, rmy, rmx + rux, rmy + ruy
            )
            item.setLine(x1, y1, x2, y2)
            self._sync_lane_data_from_item(item)
        self.update_line_constraints()
        self._sync_all_lane_overlays()

    def set_add_vehicle_mode(self, enabled):
        self.add_vehicle_mode = enabled
        if enabled:
            self.draw_mode = False
            self.marker_mode = False
            self.drawing = False
            self.current_line = None
            self._reset_lane_drag_state()
            self.setDragMode(QGraphicsView.NoDrag)
            self.setCursor(Qt.CrossCursor)
            self.scene.clearSelection()
            self._clear_all_handles()
            self._apply_vehicle_pointer_block_for_draw_mode(False)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(False)
            self._restore_lane_item_z()
        else:
            self._add_drawing = False
            if self._add_rect_preview:
                self.scene.removeItem(self._add_rect_preview)
                self._add_rect_preview = None
            self._add_rect_start = None
            self.unsetCursor()

    def set_marker_mode(self, enabled):
        self.marker_mode = enabled
        if enabled:
            if self.motion_mode:
                self.set_motion_mode(False)
            self.draw_mode = False
            self.add_vehicle_mode = False
            self.lane_draw_enabled = False
            self.drawing = False
            self.current_line = None
            self._add_drawing = False
            if self._add_rect_preview:
                self.scene.removeItem(self._add_rect_preview)
                self._add_rect_preview = None
            self._add_rect_start = None
            self._reset_lane_drag_state()
            self.setDragMode(QGraphicsView.NoDrag)
            self.unsetCursor()
            self.scene.clearSelection()
            self._clear_all_handles()
            self._apply_vehicle_pointer_block_for_draw_mode(True)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(True)
            self._restore_lane_item_z()
        else:
            self.marker_add_enabled = False
            self._set_marker_interaction_enabled(False)
            if not self.motion_mode and not self.case_mode and not self.draw_mode:
                self._apply_vehicle_pointer_block_for_draw_mode(False)
            self.unsetCursor()
        self._apply_type_visibility()

    def set_marker_add_enabled(self, enabled):
        if not self.marker_mode:
            self.marker_add_enabled = False
            self.unsetCursor()
            return
        self.marker_add_enabled = bool(enabled)
        if self.marker_add_enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.unsetCursor()

    def _current_mode_type(self):
        """Which item type the active page edits; None for pages with no matching type (e.g. 事故案情)."""
        if self.case_mode:
            return None
        if self.motion_mode:
            return "vehicle"
        if self.draw_mode:
            return "lane"
        if self.marker_mode:
            return "marker"
        return "vehicle"

    def _apply_type_visibility(self):
        """Show only the current page's object type unless show_all_objects is on.

        事故案情页没有对应的对象类型(current_type 为 None),但用户需要看到全部车辆/
        标记物/标线信息才能写出准确的案情描述,因此该页强制按"全部显示"处理,
        与 show_all_objects 勾选框的实际状态无关。
        运动页强制显示车辆（无论勾选与否）；车道/标记仍跟随 show_all_objects。
        「显示全部图层」仅影响可见性；跨图层对象始终不可选、不挡鼠标。
        """
        if self.motion_mode:
            self._apply_type_visibility_motion()
            self._sync_layer_interactions()
            return
        current_type = self._current_mode_type()
        show_all = self.show_all_objects or self.case_mode
        for item, info in self.items_data.items():
            item.setVisible(show_all or info["type"] == current_type)
        for vehicle_item, arrow in self._front_arrow_map.items():
            arrow.setVisible(vehicle_item.isVisible())
        for vehicle_item, label in self._vehicle_label_map.items():
            label.setVisible(vehicle_item.isVisible())
        for marker_item, label in self._marker_label_map.items():
            label.setVisible(marker_item.isVisible())
        for lane_item, label in self._lane_label_map.items():
            label.setVisible(lane_item.isVisible())
        if hasattr(self, "_sync_finished_path_overlays"):
            self._sync_finished_path_overlays()
        self._sync_layer_interactions()

    def set_show_all_objects(self, enabled):
        self.show_all_objects = bool(enabled)
        self._apply_type_visibility()

    def set_case_mode(self, enabled):
        """事故案情页没有可编辑的对象类型: 禁止选中车辆/车道/标记物,不管 show_all_objects 是否勾选。"""
        self.case_mode = bool(enabled)
        if self.case_mode:
            if self.motion_mode:
                self.set_motion_mode(False)
            self.scene.clearSelection()
            self._clear_all_handles()
            self._apply_vehicle_pointer_block_for_draw_mode(True)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(False)
        self._apply_type_visibility()

    def update_line_constraints(self):
        lanes = [item for item, data in self.items_data.items() if data["type"] == "lane"]
        if len(lanes) == 0:
            self.base_vector = None
            self.line_spacing = None
        elif len(lanes) == 1:
            line = lanes[0].line()
            dx = line.dx()
            dy = line.dy()
            length = np.hypot(dx, dy)
            if length > 0:
                self.base_vector = (dx / length, dy / length)
            self.line_spacing = None
        elif len(lanes) >= 2:
            line1 = lanes[0].line()
            line2 = lanes[1].line()

            dx = line1.dx()
            dy = line1.dy()
            length = np.hypot(dx, dy)
            if length > 0:
                self.base_vector = (dx / length, dy / length)

                nx, ny = -self.base_vector[1], self.base_vector[0]
                p2 = line2.p1()
                p1 = line1.p1()
                self.line_spacing = abs((p2.x() - p1.x()) * nx + (p2.y() - p1.y()) * ny)
        self._refresh_lane_labels()

    def _topmost_vehicle_at(self, scene_pos):
        """Prefer handles/vehicle over pixmap; ignore observation overlays."""
        for it in self.scene.items(scene_pos):
            if self._is_observation_overlay(it):
                continue
            if it in self.items_data and self.items_data[it]["type"] == "vehicle":
                return it
            if isinstance(it, VehicleResizeHandle):
                return it._vehicle_item
        return None

    def _topmost_marker_at(self, scene_pos):
        for it in self.scene.items(scene_pos):
            if self._is_observation_overlay(it):
                continue
            if it in self.items_data and self.items_data[it]["type"] == "marker":
                return it
        return None

    def _cancel_eyedropper(self):
        self._eyedropper_target = None
        self._eyedropper_vehicle = None
        self._eyedropper_blink_on = False
        self._eyedropper_timer.stop()
        self._eyedropper_hint.hide()
        self.unsetCursor()
        QToolTip.hideText()

    def _start_eyedropper(self, veh, target_key):
        self._eyedropper_vehicle = veh
        self._eyedropper_target = target_key
        self._eyedropper_blink_on = True
        label = EYEDROPPER_TARGET_LABELS.get(target_key, "颜色")
        self._eyedropper_hint.setText(
            f"吸管取色中（{label}）· 左键吸取 · 右键/Esc 取消"
        )
        self._eyedropper_hint.adjustSize()
        self._eyedropper_hint.resize(
            max(self._eyedropper_hint.width() + 24, 280),
            max(self._eyedropper_hint.height() + 10, 32),
        )
        self._layout_eyedropper_hint()
        self._eyedropper_hint.show()
        self._eyedropper_hint.raise_()
        self._apply_eyedropper_visual()
        self._eyedropper_timer.start()

    def _layout_eyedropper_hint(self):
        hint = getattr(self, "_eyedropper_hint", None)
        if hint is None or hint.isHidden():
            return
        hint.move(max(8, (self.viewport().width() - hint.width()) // 2), 10)

    def _build_eyedropper_cursor(self, phase_on):
        size = 44
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        accent = QColor(255, 32, 32) if phase_on else QColor(0, 230, 255)
        cross = QColor(255, 240, 0) if phase_on else QColor(255, 0, 220)
        cx = cy = size // 2
        painter.setPen(QPen(accent, 3))
        painter.setBrush(QBrush(QColor(accent.red(), accent.green(), accent.blue(), 70)))
        painter.drawEllipse(cx - 14, cy - 14, 28, 28)
        if phase_on:
            painter.setBrush(QBrush(cross))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(cx - 5, cy - 5, 10, 10)
        painter.setPen(QPen(cross, 2))
        painter.drawLine(cx, 1, cx, cy - 16)
        painter.drawLine(cx, cy + 16, cx, size - 2)
        painter.drawLine(1, cy, cx - 16, cy)
        painter.drawLine(cx + 16, cy, size - 2, cy)
        painter.end()
        return QCursor(pm, cx, cy)

    def _apply_eyedropper_visual(self):
        on = self._eyedropper_blink_on
        self.setCursor(self._build_eyedropper_cursor(on))
        if on:
            self._eyedropper_hint.setStyleSheet(
                "QLabel {"
                " background-color: rgba(220, 30, 30, 220);"
                " color: #fff;"
                " font-size: 14px;"
                " font-weight: bold;"
                " padding: 6px 14px;"
                " border-radius: 4px;"
                " border: 2px solid #ffe082;"
                "}"
            )
        else:
            self._eyedropper_hint.setStyleSheet(
                "QLabel {"
                " background-color: rgba(0, 150, 190, 220);"
                " color: #fff;"
                " font-size: 14px;"
                " font-weight: bold;"
                " padding: 6px 14px;"
                " border-radius: 4px;"
                " border: 2px solid #e1f5fe;"
                "}"
            )

    def _tick_eyedropper_blink(self):
        if not self._eyedropper_target:
            self._eyedropper_timer.stop()
            return
        self._eyedropper_blink_on = not self._eyedropper_blink_on
        self._apply_eyedropper_visual()

    def _estimate_ppm(self):
        """Pixels-per-meter from emergency-lane spacing (same basis as 3D export)."""
        _, emergency_width = self._lane_width_settings()
        spacing = self.line_spacing
        if spacing is not None and float(spacing) > 1e-6 and emergency_width > 1e-6:
            return float(spacing) / float(emergency_width)
        return DEFAULT_PPM

    def _sample_image_color_at_scene_xy(self, x, y, radius=2):
        """Sample the underlying pixmap at scene/image coordinates."""
        if self.image_item is None:
            return None
        pixmap = self.image_item.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        image = pixmap.toImage()
        ix = int(round(float(x)))
        iy = int(round(float(y)))
        if ix < 0 or iy < 0 or ix >= image.width() or iy >= image.height():
            return None
        r = max(0, int(radius))
        if r <= 0:
            color = image.pixelColor(ix, iy)
            return f"#{color.red():02X}{color.green():02X}{color.blue():02X}"
        # Tiny neighborhood average so JPEG noise does not flip the default swatch.
        r_sum = g_sum = b_sum = 0
        count = 0
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                sx = ix + dx
                sy = iy + dy
                if sx < 0 or sy < 0 or sx >= image.width() or sy >= image.height():
                    continue
                c = image.pixelColor(sx, sy)
                r_sum += c.red()
                g_sum += c.green()
                b_sum += c.blue()
                count += 1
        if count <= 0:
            return None
        return f"#{round(r_sum / count):02X}{round(g_sum / count):02X}{round(b_sum / count):02X}"

    def _default_vehicle_color(self, veh, color_key):
        region = _COLOR_KEY_TO_REGION.get(color_key)
        if region is None:
            return None
        point = default_color_sample_point(veh, region, self._estimate_ppm())
        if point is None:
            return None
        return self._sample_image_color_at_scene_xy(point[0], point[1], radius=2)

    def _normalize_display_hex(self, value):
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        if not text.startswith("#"):
            text = "#" + text
        if len(text) != 7:
            return None
        return text.upper()

    def _resolve_vehicle_display_color(self, veh, color_key):
        """
        Color shown in the \"当前颜色\" row for the active mode.

        Returns (hex_or_none, caption_suffix).
        Native mode has no hex; auto resamples from the current box.
        """
        mode = get_vehicle_color_mode(veh, color_key)
        if mode == COLOR_MODE_NATIVE:
            return None, "GLB原色"
        if mode == COLOR_MODE_GRAB:
            grabbed = self._normalize_display_hex(veh.get(color_key))
            if grabbed:
                return grabbed, ""
            return None, "未抓取"
        # auto: always follow the recognition box
        sampled = self._default_vehicle_color(veh, color_key)
        if sampled:
            return sampled, ""
        return None, "未设置"

    @staticmethod
    def _color_swatch_icon(hex_color, size=18):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        if hex_color:
            painter.setBrush(QBrush(QColor(hex_color)))
            painter.setPen(QPen(QColor(40, 40, 40), 1))
            painter.drawRect(1, 1, size - 3, size - 3)
        else:
            painter.setBrush(QBrush(QColor(210, 210, 210)))
            painter.setPen(QPen(QColor(110, 110, 110), 1))
            painter.drawRect(1, 1, size - 3, size - 3)
            painter.setPen(QPen(QColor(170, 50, 50), 2))
            painter.drawLine(3, 3, size - 4, size - 4)
        painter.end()
        # "当前颜色" is a disabled informational action. Qt otherwise
        # auto-generates a gray disabled icon, hiding the actual sampled color.
        icon = QIcon()
        icon.addPixmap(pm, QIcon.Normal, QIcon.Off)
        icon.addPixmap(pm, QIcon.Disabled, QIcon.Off)
        return icon

    def _add_vehicle_color_submenu(self, menu, title, veh, color_key):
        """
        Hover submenu: current color + mutually exclusive mode rows.
        Returns list of (action, mode, color_key).
        """
        sub = menu.addMenu(title)
        mode = get_vehicle_color_mode(veh, color_key)
        current, caption = self._resolve_vehicle_display_color(veh, color_key)
        if current:
            current_text = f"当前颜色  {current}"
        else:
            current_text = f"当前颜色  {caption}"
        current_action = sub.addAction(self._color_swatch_icon(current), current_text)
        current_action.setEnabled(False)

        actions = []
        for mode_id, label in (
            (COLOR_MODE_GRAB, _COLOR_MODE_LABELS[COLOR_MODE_GRAB]),
            (COLOR_MODE_AUTO, _COLOR_MODE_LABELS[COLOR_MODE_AUTO]),
            (COLOR_MODE_NATIVE, _COLOR_MODE_LABELS[COLOR_MODE_NATIVE]),
        ):
            action = sub.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == mode_id)
            actions.append((action, mode_id, color_key))
        return actions

    def _sample_image_color_at_view_pos(self, view_pos):
        """Sample the underlying pixmap pixel (ignores overlay pens/fills)."""
        if self.image_item is None:
            return None
        scene_pos = self.mapToScene(view_pos)
        local = self.image_item.mapFromScene(scene_pos)
        return self._sample_image_color_at_scene_xy(local.x(), local.y(), radius=0)

    def mousePressEvent(self, event):
        if self._eyedropper_target and event.button() == Qt.LeftButton:
            hex_color = self._sample_image_color_at_view_pos(event.pos())
            if hex_color and self._eyedropper_vehicle is not None:
                self._eyedropper_vehicle[self._eyedropper_target] = hex_color
                set_vehicle_color_mode(
                    self._eyedropper_vehicle,
                    self._eyedropper_target,
                    COLOR_MODE_GRAB,
                )
            self._cancel_eyedropper()
            event.accept()
            return
        if self._eyedropper_target and event.button() == Qt.RightButton:
            self._cancel_eyedropper()
            event.accept()
            return

        if self.motion_mode and self._path_edit_active and event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            # Space + blank (when zoomed): pan. Otherwise always place a path point,
            # including on vehicle bodies (vehicles are non-interactive while editing).
            if (
                self._space_down
                and self._view_overflows_image()
                and self._scene_pos_on_blank_image(scene_pos)
            ):
                self._begin_pan(event.pos(), button=Qt.LeftButton)
                event.accept()
                return
            self._try_add_path_point(scene_pos.x(), scene_pos.y())
            event.accept()
            return

        if self.motion_mode and event.button() == Qt.RightButton and self._path_edit_active:
            # Finish path on any right-click (vehicles are locked during path edit).
            self._finish_path_edit()
            event.accept()
            return

        if self.draw_mode and event.button() == Qt.LeftButton:
            lane_hit = self._pick_lane_under_cursor(event.pos())
            if lane_hit is not None:
                scene_pos = self.mapToScene(event.pos())
                self.scene.clearSelection()
                lane_hit.setSelected(True)
                if self._prepare_lane_drag_geometry(lane_hit, scene_pos):
                    self._drag_lane = True
                    self.viewport().grabMouse()
                    event.accept()
                    return
            if not self.lane_draw_enabled:
                scene_pos = self.mapToScene(event.pos())
                if self._view_overflows_image() and self._scene_pos_on_blank_image(
                    scene_pos
                ):
                    self._begin_pan(event.pos(), button=Qt.LeftButton)
                    event.accept()
                    return
                super().mousePressEvent(event)
                return
            scene_pos = self.mapToScene(event.pos())
            self.start_point = scene_pos
            self.current_line = self.scene.addLine(
                scene_pos.x(),
                scene_pos.y(),
                scene_pos.x(),
                scene_pos.y(),
                _lane_pen(),
            )
            self.current_line.setZValue(5 if self.draw_mode else 0)
            self.drawing = True
            return

        if self.add_vehicle_mode and event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            self._add_rect_start = scene_pos
            self._add_drawing = True
            if self._add_rect_preview:
                self.scene.removeItem(self._add_rect_preview)
                self._add_rect_preview = None
            self._add_rect_preview = self.scene.addRect(
                scene_pos.x(),
                scene_pos.y(),
                0,
                0,
                QPen(QColor(0, 120, 255), 2, Qt.DashLine),
                QBrush(QColor(0, 120, 255, 40)),
            )
            self._add_rect_preview.setZValue(20)
            return

        if event.button() == Qt.MiddleButton:
            self._begin_pan(event.pos(), button=Qt.MiddleButton)
            event.accept()
            return

        if event.button() == Qt.LeftButton and self._space_down:
            scene_pos = self.mapToScene(event.pos())
            vhit = self._topmost_vehicle_at(scene_pos)
            if vhit is None:
                self._begin_pan(event.pos(), button=Qt.LeftButton)
                event.accept()
                return

        if (
            event.button() == Qt.LeftButton
            and not self._space_down
            and not self.add_vehicle_mode
            and not (self.draw_mode and self.lane_draw_enabled)
            and not (self.marker_mode and self.marker_add_enabled)
            and not self.drawing
            and not self._add_drawing
            and self._view_overflows_image()
        ):
            scene_pos = self.mapToScene(event.pos())
            if self._scene_pos_on_blank_image(scene_pos):
                self._begin_pan(event.pos(), button=Qt.LeftButton)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.draw_mode and self._drag_lane and self._lane_drag_O is not None:
            scene_pos = self.mapToScene(event.pos())
            if self._lane_drag_index == 0 and self._lane_drag_press_scene is not None:
                dx = scene_pos.x() - self._lane_drag_press_scene.x()
                dy = scene_pos.y() - self._lane_drag_press_scene.y()
                self._translate_lanes_from_drag_start(dx, dy)
            else:
                ox, oy = self._lane_drag_O
                nx, ny = self._lane_drag_n
                idx = max(int(self._lane_drag_index or 1), 1)
                projected = (scene_pos.x() - ox) * nx + (scene_pos.y() - oy) * ny
                lane_width, emergency_width = self._lane_width_settings()
                logical_offset = emergency_width + (idx - 1) * lane_width
                scale = projected / logical_offset if logical_offset > 0 else 1.0
                self._relayout_parallel_lanes_from_emergency_spacing(scale * emergency_width)
            event.accept()
            return

        if self.draw_mode and self.drawing and self.current_line:
            scene_pos = self.mapToScene(event.pos())

            if self.base_vector is None:
                self.current_line.setLine(
                    self.start_point.x(),
                    self.start_point.y(),
                    scene_pos.x(),
                    scene_pos.y(),
                )
            else:
                vx = scene_pos.x() - self.start_point.x()
                vy = scene_pos.y() - self.start_point.y()
                proj_len = vx * self.base_vector[0] + vy * self.base_vector[1]
                end_x = self.start_point.x() + proj_len * self.base_vector[0]
                end_y = self.start_point.y() + proj_len * self.base_vector[1]

                if self.line_spacing is not None:
                    pass

                self.current_line.setLine(
                    self.start_point.x(), self.start_point.y(), end_x, end_y
                )
            return

        if self.add_vehicle_mode and self._add_drawing and self._add_rect_preview and self._add_rect_start:
            scene_pos = self.mapToScene(event.pos())
            x0, y0 = self._add_rect_start.x(), self._add_rect_start.y()
            x1, y1 = scene_pos.x(), scene_pos.y()
            rx = min(x0, x1)
            ry = min(y0, y1)
            rw = abs(x1 - x0)
            rh = abs(y1 - y0)
            self._add_rect_preview.setRect(rx, ry, rw, rh)
            return

        if self._panning:
            delta = event.pos() - self._pan_anchor
            if abs(delta.x()) > 0 or abs(delta.y()) > 0:
                self._pan_moved = True
            self._pan_anchor = event.pos()
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(hs.value() - delta.x())
            vs.setValue(vs.value() - delta.y())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.draw_mode and event.button() == Qt.LeftButton and self._drag_lane:
            self._reset_lane_drag_state()
            self.viewport().releaseMouse()
            event.accept()
            return

        if self.draw_mode and event.button() == Qt.LeftButton and self.drawing:
            self.drawing = False
            if self.current_line:
                line = self.current_line.line()
                if line.length() < 10:
                    self.scene.removeItem(self.current_line)
                else:
                    if self.line_spacing is not None and self.base_vector is not None:
                        lanes = [
                            item
                            for item, data in self.items_data.items()
                            if data["type"] == "lane"
                        ]
                        if lanes:
                            ref_line = lanes[0].line()
                            p1 = ref_line.p1()
                            nx, ny = -self.base_vector[1], self.base_vector[0]

                            curr_mid_x = (line.p1().x() + line.p2().x()) / 2
                            curr_mid_y = (line.p1().y() + line.p2().y()) / 2

                            dist = (curr_mid_x - p1.x()) * nx + (curr_mid_y - p1.y()) * ny

                            snap_dist = self._nearest_lane_snap_distance(
                                dist, self.line_spacing
                            )

                            offset_dist = snap_dist - dist
                            shift_x = offset_dist * nx
                            shift_y = offset_dist * ny

                            line.translate(shift_x, shift_y)
                            self.current_line.setLine(line)

                    l = self.current_line.line()
                    ex1, ey1, ex2, ey2 = self._extend_line_to_image_bounds(
                        l.x1(), l.y1(), l.x2(), l.y2()
                    )
                    if self._is_overlapping_existing_lane(ex1, ey1, ex2, ey2):
                        self.scene.removeItem(self.current_line)
                        self.current_line = None
                        QMessageBox.warning(
                            self,
                            "无法画线",
                            "新画的车道线与已有车道线重叠，已取消本次画线。",
                        )
                        return
                    self.current_line.setLine(ex1, ey1, ex2, ey2)
                    self.current_line.setPen(_lane_pen())
                    self.current_line.setZValue(5 if self.draw_mode else 0)
                    data = {
                        "x1": ex1,
                        "y1": ey1,
                        "x2": ex2,
                        "y2": ey2,
                    }
                    self.current_line.setAcceptedMouseButtons(Qt.AllButtons)
                    self.current_line.setFlag(QGraphicsLineItem.ItemIsSelectable, self.draw_mode)
                    self.current_line.setToolTip("点击右键或按 Delete 删除车道线")
                    self.items_data[self.current_line] = {"type": "lane", "data": data}

                    self.update_line_constraints()
                    self._emit_objects_changed()
            self.current_line = None
            return

        if self.add_vehicle_mode and event.button() == Qt.LeftButton and self._add_drawing:
            self._add_drawing = False
            if self._add_rect_preview:
                r = self._add_rect_preview.rect()
                self.scene.removeItem(self._add_rect_preview)
                self._add_rect_preview = None
                if r.width() >= 10 and r.height() >= 10:
                    cx = r.x() + r.width() / 2.0
                    cy = r.y() + r.height() / 2.0
                    veh = {
                        "vehicle_id": next_vehicle_id(self._vehicle_data_list()),
                        "class_id": -1,
                        "class_name": "manual",
                        "confidence": 1.0,
                        "x_center": float(cx),
                        "y_center": float(cy),
                        "width": float(r.width()),
                        "height": float(r.height()),
                        "angle": 0.0,
                        "preset_type": "小客车",
                    }
                    ensure_vehicle_preset(veh)
                    ensure_vehicle_color_modes(veh)
                    ensure_motion_fields(veh)
                    poly = self._polygon_from_veh(veh)
                    poly_item = VehiclePolygonItem(self, poly, veh)
                    poly_item.setPen(QPen(Qt.red, 2))
                    poly_item.setBrush(QColor(255, 0, 0, 50))
                    poly_item.setFlag(QGraphicsPolygonItem.ItemIsSelectable, True)
                    poly_item.setZValue(1)
                    poly_item.setToolTip(_vehicle_tooltip_text(veh))
                    self.scene.addItem(poly_item)
                    self.items_data[poly_item] = {"type": "vehicle", "data": veh}
                    self._add_vehicle_front_arrow(poly_item)
                    self._add_vehicle_id_label(poly_item)
                    self.scene.clearSelection()
                    poly_item.setSelected(True)
                    self._emit_objects_changed()
            self._add_rect_start = None
            return

        # End pan before marker-mode early returns; otherwise blank-click pan on the
        # marker page (non-add mode) would stick with a closed-hand cursor forever.
        if event.button() == Qt.MiddleButton and self._panning:
            self._end_pan()
            event.accept()
            return
        if event.button() == Qt.LeftButton and self._panning:
            self._end_pan()
            event.accept()
            return

        if self.marker_mode and event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            marker_hit = self._topmost_marker_at(scene_pos)
            if marker_hit is not None:
                super().mouseReleaseEvent(event)
                return
            if not self.marker_add_enabled:
                super().mouseReleaseEvent(event)
                return
            marker = {
                "marker_id": next_marker_id(self._marker_data_list()),
                "marker_type": DEFAULT_MARKER_TYPE,
                "x_center": float(scene_pos.x()),
                "y_center": float(scene_pos.y()),
            }
            item = self._add_marker_item(marker)
            self.scene.clearSelection()
            item.setSelected(True)
            self._emit_objects_changed()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def _polygon_from_veh(self, veh):
        x, y, w, h, r = (
            veh["x_center"],
            veh["y_center"],
            veh["width"],
            veh["height"],
            veh["angle"],
        )
        rect = ((x, y), (w, h), np.degrees(r))
        box = cv2.boxPoints(rect)
        polygon = QPolygonF()
        for pt in box:
            polygon.append(QPointF(float(pt[0]), float(pt[1])))
        return polygon

    def load_image_and_data(self, image_path, vehicles, lanes, markers=None):
        self.scene.clear()
        self.items_data.clear()
        self._clear_all_handles()
        self._front_arrow_map.clear()
        self._vehicle_label_map.clear()
        self._marker_label_map.clear()
        self._lane_label_map.clear()
        self._selection_overlay_map.clear()
        if self._breath_timer.isActive():
            self._breath_timer.stop()
        self._reset_lane_drag_state()

        pixmap = QPixmap(image_path)
        self.image_item = self.scene.addPixmap(pixmap)
        self.image_item.setZValue(-1)
        self.image_item.setAcceptedMouseButtons(Qt.NoButton)

        for lane in lanes:
            x1, y1, x2, y2 = self._extend_line_to_image_bounds(
                lane["x1"], lane["y1"], lane["x2"], lane["y2"]
            )
            lane = {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
            line = self.scene.addLine(
                lane["x1"], lane["y1"], lane["x2"], lane["y2"], _lane_pen()
            )
            line.setAcceptedMouseButtons(Qt.AllButtons if self.draw_mode else Qt.NoButton)
            line.setFlag(QGraphicsLineItem.ItemIsSelectable, self.draw_mode)
            line.setToolTip("点击右键或按 Delete 删除车道线")
            self.items_data[line] = {"type": "lane", "data": lane}

        ensure_vehicle_ids(vehicles)
        for veh in vehicles:
            ensure_vehicle_preset(veh)
            ensure_vehicle_color_modes(veh)
            ensure_motion_fields(veh)
            poly = self._polygon_from_veh(veh)
            poly_item = VehiclePolygonItem(self, poly, veh)
            poly_item.setPen(QPen(Qt.red, 2))
            poly_item.setBrush(QColor(255, 0, 0, 50))
            poly_item.setFlag(QGraphicsPolygonItem.ItemIsSelectable, True)
            poly_item.setToolTip(_vehicle_tooltip_text(veh))
            poly_item.setZValue(1)
            self.scene.addItem(poly_item)
            self.items_data[poly_item] = {"type": "vehicle", "data": veh}
            self._add_vehicle_front_arrow(poly_item)
            self._add_vehicle_id_label(poly_item)

        for marker in markers or []:
            ensure_marker_preset(marker)
            marker.setdefault("marker_id", next_marker_id(self._marker_data_list()))
            marker["x_center"] = float(marker.get("x_center", 0.0))
            marker["y_center"] = float(marker.get("y_center", 0.0))
            self._add_marker_item(marker)

        self._set_marker_interaction_enabled(self.marker_mode)
        self._auto_fit_image = True
        self._fit_image_to_view()
        self.update_line_constraints()
        self._apply_type_visibility()
        self._emit_objects_changed()

    def contextMenuEvent(self, event):
        if self.motion_mode and self._path_edit_active:
            # Right-click ends path drawing (including when over a vehicle body).
            self._finish_path_edit()
            event.accept()
            return

        # Walk through observation overlays / foreign layers to the active-layer item.
        item = self._editable_item_at_view_pos(event.pos())
        if item and item in self.items_data:
            info = self.items_data[item]
            # 只允许对当前页面对应类型的对象弹出右键菜单,即便「显示全部图层」
            # 勾选后其他类型的对象也可见,也不允许跨页面选中/编辑它们。
            if info["type"] != self._current_mode_type():
                return
            if self.motion_mode and info["type"] == "vehicle":
                menu = QMenu(self)
                path_action = menu.addAction("设置路径")
                speed_action = menu.addAction("设置速度")
                action = menu.exec(event.globalPos())
                if action == path_action:
                    self._begin_path_edit(item)
                elif action == speed_action:
                    self._open_motion_speed_dialog(info["data"])
                return
            menu = QMenu(self)
            resize_action = None
            color_menu_actions = []  # (action, mode, color_key)
            if info["type"] == "vehicle":
                type_menu = menu.addMenu("设置标准车型")
                for t in STANDARD_VEHICLE_TYPES:
                    type_menu.addAction(t)
                resize_action = menu.addAction("调整尺寸")
                preset_type = str(info["data"].get("preset_type", "") or "")
                if preset_type in SPLIT_COLOR_VEHICLE_TYPES:
                    color_entries = [
                        ("设置车头颜色", "body_color"),
                        ("设置车尾颜色", "cargo_color"),
                    ]
                else:
                    color_entries = [("设置颜色", "body_color")]
                for title, color_key in color_entries:
                    color_menu_actions.extend(
                        self._add_vehicle_color_submenu(
                            menu, title, info["data"], color_key
                        )
                    )
                menu.addSeparator()
            if info["type"] == "marker":
                type_menu = menu.addMenu("设置标记物类型")
                for t in STANDARD_MARKER_TYPES:
                    type_menu.addAction(t)
                menu.addSeparator()
            del_action = menu.addAction("删除此对象")
            action = menu.exec(event.globalPos())
            if action is None:
                return
            if action == resize_action:
                self._open_vehicle_size_dialog(item, info["data"])
                return
            for color_action, mode_id, color_key in color_menu_actions:
                if action != color_action:
                    continue
                set_vehicle_color_mode(info["data"], color_key, mode_id)
                if mode_id == COLOR_MODE_GRAB:
                    self._start_eyedropper(info["data"], color_key)
                return
            if (
                info["type"] == "vehicle"
                and action.text() in STANDARD_VEHICLE_TYPE_SET
            ):
                info["data"]["preset_type"] = action.text()
                ensure_vehicle_color_modes(info["data"])
                item.setToolTip(_vehicle_tooltip_text(info["data"]))
                self._update_vehicle_front_arrow_tooltip(item)
                self._refresh_vehicle_id_label(item)
                if item.isSelected():
                    self.vehicle_selection_changed.emit(info["data"])
                return
            if (
                info["type"] == "marker"
                and action.text() in STANDARD_MARKER_TYPE_SET
            ):
                info["data"]["marker_type"] = action.text()
                item.setToolTip(_marker_tooltip_text(info["data"]))
                self._refresh_marker_name_label(item)
                return
            if action == del_action:
                if info["type"] == "lane" and not self._is_last_lane_item(item):
                    QMessageBox.information(
                        self,
                        "无法删除",
                        "为保证车道编号顺序，只能从最后一根车道线开始删除。请先删除编号最大的车道线。",
                    )
                    item.setSelected(False)
                    return
                if info["type"] == "vehicle":
                    self._remove_vehicle_handles(item)
                    self._remove_vehicle_front_arrow(item)
                    self._remove_vehicle_id_label(item)
                elif info["type"] == "marker":
                    self._remove_marker_name_label(item)
                self._remove_selection_overlay(item)
                self.scene.removeItem(item)
                del self.items_data[item]
                self.update_line_constraints()
                self._on_selection_changed()
                self._emit_objects_changed()
            return

        # Blank area (or non-editable overlay): in road-line mode, allow
        # per-image lane / emergency-lane width override.
        if self.draw_mode and not self.case_mode:
            menu = QMenu(self)
            width_action = menu.addAction("设置车道宽 / 应急车道宽")
            action = menu.exec(event.globalPos())
            if action == width_action:
                self._open_lane_width_dialog()
            return

        if self.motion_mode and self._path_edit_active:
            self._finish_path_edit()
            return

    def _clear_all_lanes(self):
        lane_items = [
            item
            for item, info in list(self.items_data.items())
            if info["type"] == "lane"
        ]
        for item in lane_items:
            label = self._lane_label_map.pop(item, None)
            if label is not None:
                self.scene.removeItem(label)
            self._remove_selection_overlay(item)
            self.scene.removeItem(item)
            del self.items_data[item]
        self._reset_lane_drag_state()
        self.update_line_constraints()
        self._refresh_lane_labels()
        self._on_selection_changed()
        self._emit_objects_changed()

    def _open_lane_width_dialog(self):
        current_lane, current_emergency = self._lane_width_settings()
        dialog = LaneWidthDialog(
            lane_width=current_lane,
            emergency_lane_width=current_emergency,
            parent=self,
        )
        if dialog.exec() != LaneWidthDialog.Accepted:
            return
        result = dialog.result_widths
        if not result:
            return
        lane_width, emergency_width = result
        had_lanes = any(
            info["type"] == "lane" for info in self.items_data.values()
        )
        self.set_lane_width_override(lane_width, emergency_width)
        if had_lanes:
            self._clear_all_lanes()
            QMessageBox.information(
                self,
                "已更新本图车道宽",
                "本图车道宽与应急车道宽已更新，已删除全部已规划车道线。"
                "请重新规划车道线。该设置不会影响建模预览中的通用设置。",
            )
        else:
            QMessageBox.information(
                self,
                "已更新本图车道宽",
                "本图车道宽与应急车道宽已更新。请规划车道线。"
                "该设置不会影响建模预览中的通用设置。",
            )

    def _open_vehicle_size_dialog(self, vehicle_item, veh):
        preset_type = str(veh.get("preset_type", "") or "小客车")
        body_hex, _ = self._resolve_vehicle_display_color(veh, "body_color")
        cargo_hex = None
        if preset_type in SPLIT_COLOR_VEHICLE_TYPES:
            cargo_hex, _ = self._resolve_vehicle_display_color(veh, "cargo_color")
        dialog = VehicleSizeDialog(
            veh.get("vehicle_id", ""),
            preset_type,
            custom_size=veh.get("custom_size"),
            parent=self,
            body_color=body_hex,
            cargo_color=cargo_hex,
        )
        if dialog.exec() != VehicleSizeDialog.Accepted:
            return
        if dialog.result_size is None:
            veh.pop("custom_size", None)
        else:
            veh["custom_size"] = dialog.result_size

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._eyedropper_target:
            self._cancel_eyedropper()
            event.accept()
            return
        if event.key() == Qt.Key_Space:
            self._space_down = True
            event.accept()
            return
        if self.motion_mode and self._path_edit_active and (
            event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace
        ):
            if self._delete_breathing_path_point():
                event.accept()
                return
        if self.motion_mode and (
            event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace
        ):
            # Motion page: never delete vehicles.
            event.accept()
            return
        if self.motion_mode and event.key() in DIRECTION_STEP_KEYS:
            event.accept()
            return
        if event.key() in DIRECTION_STEP_KEYS:
            selected_vehicles = [
                item
                for item in self.scene.selectedItems()
                if item in self.items_data and self.items_data[item]["type"] == "vehicle"
            ]
            if selected_vehicles:
                step = DIRECTION_STEP_KEYS[event.key()]
                for item in selected_vehicles:
                    veh = self.items_data[item]["data"]
                    current = float(veh.get("direction_offset", 0.0))
                    veh["direction_offset"] = (current + step) % 360.0
                    self._refresh_vehicle_front_arrow(item)
                    self._update_vehicle_front_arrow_tooltip(item)
                event.accept()
                return
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            selected_items = list(self.scene.selectedItems())
            blocked_lane = False
            for item in selected_items:
                if item not in self.items_data:
                    continue
                if (
                    self.items_data[item]["type"] == "lane"
                    and not self._is_last_lane_item(item)
                ):
                    blocked_lane = True
                    item.setSelected(False)
            if blocked_lane:
                QMessageBox.information(
                    self,
                    "无法删除",
                    "为保证车道编号顺序，只能从最后一根车道线开始删除。请先删除编号最大的车道线。",
                )
                event.accept()
                return
            for item in selected_items:
                if item in self.items_data:
                    if self.items_data[item]["type"] == "vehicle":
                        self._remove_vehicle_handles(item)
                        self._remove_vehicle_front_arrow(item)
                        self._remove_vehicle_id_label(item)
                    elif self.items_data[item]["type"] == "marker":
                        self._remove_marker_name_label(item)
                    self._remove_selection_overlay(item)
                    self.scene.removeItem(item)
                    del self.items_data[item]
            self.update_line_constraints()
            self._on_selection_changed()
            self._emit_objects_changed()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._space_down = False
            if self._panning:
                self._end_pan()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def wheelEvent(self, event):
        # Viewport eventFilter usually handles Alt-zoom first; keep this as fallback
        # when the event reaches the view directly.
        if self._try_alt_zoom(event):
            return

        if self.draw_mode:
            selected_lanes = [
                item
                for item in self.scene.selectedItems()
                if item in self.items_data and self.items_data[item]["type"] == "lane"
            ]
            if selected_lanes:
                dy = event.angleDelta().y()
                if dy == 0:
                    super().wheelEvent(event)
                    return
                angle_delta = np.radians(LANE_WHEEL_ROTATE_DEG) * (dy / 120.0)
                self._rotate_lanes(angle_delta)
                event.accept()
                return
            super().wheelEvent(event)
            return

        if self.motion_mode:
            if (
                getattr(self, "_path_edit_active", False)
                and hasattr(self, "_toggle_breathing_path_drive")
            ):
                dy = event.angleDelta().y()
                if dy != 0 and self._toggle_breathing_path_drive():
                    event.accept()
                    return
            super().wheelEvent(event)
            return

        selected_items = self.scene.selectedItems()
        vehicle_items = [
            item
            for item in selected_items
            if item in self.items_data and self.items_data[item]["type"] == "vehicle"
        ]

        if vehicle_items:
            dy = event.angleDelta().y()
            if dy == 0:
                super().wheelEvent(event)
                return
            angle_delta = np.radians(VEHICLE_WHEEL_ROTATE_DEG) * (dy / 120.0)
            for item in vehicle_items:
                veh = self.items_data[item]["data"]
                veh["angle"] += angle_delta
                self._refresh_vehicle_polygon(item)
                self._reposition_handles(item)
            event.accept()
            return

        super().wheelEvent(event)

    def update_vehicle_tooltip_by_data(self, veh):
        for item, info in self.items_data.items():
            if info["type"] == "vehicle" and info["data"] is veh:
                item.setToolTip(_vehicle_tooltip_text(veh))
                self._update_vehicle_front_arrow_tooltip(item)
                self._refresh_vehicle_id_label(item)
                return

    def get_confirmed_data(self):
        final_vehicles = []
        final_lanes = []
        final_markers = []

        for item, info in self.items_data.items():
            if info["type"] == "vehicle":
                ensure_vehicle_color_modes(info["data"])
                ensure_motion_fields(info["data"])
                final_vehicles.append(info["data"])
            elif info["type"] == "lane":
                final_lanes.append(info["data"])
            elif info["type"] == "marker":
                final_markers.append(info["data"])

        return final_vehicles, final_lanes, final_markers

    def _refresh_vehicle_polygon(self, item):
        veh = self.items_data[item]["data"]
        item.setPolygon(self._polygon_from_veh(veh))
        self._refresh_vehicle_front_arrow(item)
        self._refresh_vehicle_id_label(item)
        self._sync_selection_overlay(item)

    def _vehicle_data_list(self):
        return [
            info["data"]
            for info in self.items_data.values()
            if info["type"] == "vehicle"
        ]

    def _marker_data_list(self):
        return [
            info["data"]
            for info in self.items_data.values()
            if info["type"] == "marker"
        ]

    def _add_marker_item(self, marker):
        ensure_marker_preset(marker)
        marker_item = MarkerCircleItem(self, marker)
        marker_item.setAcceptedMouseButtons(Qt.AllButtons if self.marker_mode else Qt.NoButton)
        marker_item.setFlag(QGraphicsEllipseItem.ItemIsSelectable, self.marker_mode)
        self.scene.addItem(marker_item)
        self.items_data[marker_item] = {"type": "marker", "data": marker}
        self._add_marker_name_label(marker_item)
        return marker_item

    def _marker_name_anchor_point(self, marker_item):
        pos = marker_item.pos()
        return QPointF(pos.x(), pos.y() - MARKER_RADIUS - 6.0)

    def _add_marker_name_label(self, marker_item):
        if marker_item not in self.items_data:
            return
        label = QGraphicsTextItem()
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        label.setFont(font)
        label.setDefaultTextColor(QColor(255, 235, 59))
        self._configure_observation_item(label)
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        label.setZValue(40)
        self.scene.addItem(label)
        self._marker_label_map[marker_item] = label
        self._refresh_marker_name_label(marker_item)
        label.setVisible(marker_item.isVisible())

    def _refresh_marker_name_label(self, marker_item):
        label = self._marker_label_map.get(marker_item)
        if label is None or marker_item not in self.items_data:
            return
        marker = self.items_data[marker_item]["data"]
        marker_type = str(marker.get("marker_type", DEFAULT_MARKER_TYPE) or DEFAULT_MARKER_TYPE)
        label.setPlainText(marker_type)
        anchor = self._marker_name_anchor_point(marker_item)
        rect = label.boundingRect()
        label.setPos(self._label_pos_for_anchor(anchor, rect, align="top_center"))

    def _remove_marker_name_label(self, marker_item):
        label = self._marker_label_map.pop(marker_item, None)
        if label is not None:
            self.scene.removeItem(label)

    def _vehicle_id_anchor_point(self, vehicle_item):
        """Axis-aligned top-left of the recognition box (YOLO-style label anchor)."""
        polygon = vehicle_item.polygon()
        if polygon.isEmpty():
            return QPointF(0, 0)
        min_x = min(point.x() for point in polygon)
        min_y = min(point.y() for point in polygon)
        return QPointF(min_x, min_y)

    def _add_vehicle_id_label(self, vehicle_item):
        if vehicle_item not in self.items_data:
            return
        label = QGraphicsTextItem()
        font = QFont()
        font.setPointSize(6)
        font.setBold(True)
        label.setFont(font)
        label.setDefaultTextColor(QColor(255, 235, 59))
        self._configure_observation_item(label)
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        label.setZValue(40)
        self.scene.addItem(label)
        self._vehicle_label_map[vehicle_item] = label
        self._refresh_vehicle_id_label(vehicle_item)

    def _refresh_vehicle_id_label(self, vehicle_item):
        label = self._vehicle_label_map.get(vehicle_item)
        if label is None or vehicle_item not in self.items_data:
            return
        veh = self.items_data[vehicle_item]["data"]
        vehicle_id = str(veh.get("vehicle_id", "") or "未编号")
        preset_type = str(veh.get("preset_type", "") or "")
        if preset_type:
            label.setPlainText(f"{vehicle_id}({preset_type})")
        else:
            label.setPlainText(vehicle_id)
        font = label.font()
        font.setPointSize(6)
        font.setBold(True)
        label.setFont(font)
        anchor = self._vehicle_id_anchor_point(vehicle_item)
        rect = label.boundingRect()
        label.setPos(self._label_pos_for_anchor(anchor, rect, align="bottom_left"))

    def _remove_vehicle_id_label(self, vehicle_item):
        label = self._vehicle_label_map.pop(vehicle_item, None)
        if label is not None:
            self.scene.removeItem(label)

    def _vehicle_front_arrow_polygon(self, veh):
        cx = float(veh["x_center"])
        cy = float(veh["y_center"])
        width = max(float(veh["width"]), 1.0)
        height = max(float(veh["height"]), 1.0)
        theta = float(veh["angle"]) + math.radians(float(veh.get("direction_offset", 0.0)))

        dx, dy = -math.sin(theta), math.cos(theta)
        px, py = -dy, dx

        arrow_len = max(24.0, min(height * 0.72, 160.0))
        head_len = max(12.0, min(arrow_len * 0.34, 34.0))
        shaft_w = max(6.0, min(width * 0.14, 18.0))
        head_w = max(shaft_w * 2.4, min(width * 0.38, 46.0))

        base_x = cx - dx * arrow_len * 0.45
        base_y = cy - dy * arrow_len * 0.45
        tip_x = cx + dx * arrow_len * 0.55
        tip_y = cy + dy * arrow_len * 0.55
        head_base_x = tip_x - dx * head_len
        head_base_y = tip_y - dy * head_len

        pts = [
            (base_x + px * shaft_w * 0.5, base_y + py * shaft_w * 0.5),
            (head_base_x + px * shaft_w * 0.5, head_base_y + py * shaft_w * 0.5),
            (head_base_x + px * head_w * 0.5, head_base_y + py * head_w * 0.5),
            (tip_x, tip_y),
            (head_base_x - px * head_w * 0.5, head_base_y - py * head_w * 0.5),
            (head_base_x - px * shaft_w * 0.5, head_base_y - py * shaft_w * 0.5),
            (base_x - px * shaft_w * 0.5, base_y - py * shaft_w * 0.5),
        ]

        polygon = QPolygonF()
        for x, y in pts:
            polygon.append(QPointF(float(x), float(y)))
        return polygon

    def _add_vehicle_front_arrow(self, vehicle_item):
        arrow = QGraphicsPolygonItem()
        arrow.setPen(QPen(Qt.black, 2))
        arrow.setBrush(QBrush(QColor(255, 235, 0, 230)))
        arrow.setZValue(30)
        self._configure_observation_item(arrow)
        self.scene.addItem(arrow)
        self._front_arrow_map[vehicle_item] = arrow
        self._refresh_vehicle_front_arrow(vehicle_item)
        self._update_vehicle_front_arrow_tooltip(vehicle_item)

    def _refresh_vehicle_front_arrow(self, vehicle_item):
        arrow = self._front_arrow_map.get(vehicle_item)
        if arrow is None or vehicle_item not in self.items_data:
            return
        veh = self.items_data[vehicle_item]["data"]
        arrow.setPolygon(self._vehicle_front_arrow_polygon(veh))

    def _update_vehicle_front_arrow_tooltip(self, vehicle_item):
        arrow = self._front_arrow_map.get(vehicle_item)
        if arrow is None or vehicle_item not in self.items_data:
            return
        veh = self.items_data[vehicle_item]["data"]
        arrow.setToolTip(_vehicle_tooltip_text(veh))

    def _remove_vehicle_front_arrow(self, vehicle_item):
        arrow = self._front_arrow_map.pop(vehicle_item, None)
        if arrow is not None:
            self.scene.removeItem(arrow)

    def _vehicle_item_from_front_arrow(self, arrow_item):
        for vehicle_item, arrow in self._front_arrow_map.items():
            if arrow is arrow_item:
                return vehicle_item
        return None

    def _corner_points_list(self, vehicle_item):
        veh = self.items_data[vehicle_item]["data"]
        x, y, w, h, r = (
            veh["x_center"],
            veh["y_center"],
            veh["width"],
            veh["height"],
            veh["angle"],
        )
        rect = ((x, y), (w, h), np.degrees(r))
        box = cv2.boxPoints(rect)
        return [QPointF(float(p[0]), float(p[1])) for p in box]

    def _scene_pos_on_vehicle_resize_handle(self, vehicle_item, scene_pos):
        if vehicle_item not in self._handle_map:
            return False
        hit_r = HANDLE_RADIUS + HANDLE_BLOCK_SLACK
        for h in self._handle_map[vehicle_item]:
            if QLineF(h.pos(), scene_pos).length() <= hit_r:
                return True
        return False

    def _resize_vehicle_at_corner(self, vehicle_item, corner_index, scene_pos):
        """
        Drag one corner toward/away from the fixed opposite corner, keeping current angle.
        (minAreaRect on 3 old corners + new point cannot shrink — those corners still span the old AABB.)
        """
        corners = self._corner_points_list(vehicle_item)
        opp = (corner_index + 2) % 4
        O = corners[opp]
        P = scene_pos
        veh = self.items_data[vehicle_item]["data"]
        theta = float(veh["angle"])
        c, s = math.cos(theta), math.sin(theta)
        e1 = np.array([c, s], dtype=np.float64)
        e2 = np.array([-s, c], dtype=np.float64)
        d = np.array([P.x() - O.x(), P.y() - O.y()], dtype=np.float64)
        half_d = d / 2.0
        A = np.column_stack([e1, e2])
        try:
            ab = np.linalg.solve(A, half_d)
        except np.linalg.LinAlgError:
            return
        a, b = float(ab[0]), float(ab[1])
        w = 2.0 * abs(a)
        h = 2.0 * abs(b)
        cx = (P.x() + O.x()) / 2.0
        cy = (P.y() + O.y()) / 2.0
        veh["x_center"] = cx
        veh["y_center"] = cy
        veh["width"] = max(w, 1.0)
        veh["height"] = max(h, 1.0)
        self._refresh_vehicle_polygon(vehicle_item)
        self._reposition_handles(vehicle_item)

    def _clear_all_handles(self):
        for vitem, handles in list(self._handle_map.items()):
            for h in handles:
                self.scene.removeItem(h)
        self._handle_map.clear()

    def _remove_vehicle_handles(self, vehicle_item):
        if vehicle_item in self._handle_map:
            for h in self._handle_map[vehicle_item]:
                self.scene.removeItem(h)
            del self._handle_map[vehicle_item]

    def _reposition_handles(self, vehicle_item):
        if vehicle_item not in self._handle_map:
            return
        corners = self._corner_points_list(vehicle_item)
        for i, h in enumerate(self._handle_map[vehicle_item]):
            h.setPos(corners[i])

    def _on_selection_changed(self):
        self._clear_all_handles()
        self._refresh_selection_overlays()
        sel = [
            i
            for i in self.scene.selectedItems()
            if i in self.items_data and self.items_data[i]["type"] == "vehicle"
        ]
        self.vehicle_selection_count_changed.emit(len(sel))
        if len(sel) == 1:
            vitem = sel[0]
            veh_data = self.items_data[vitem]["data"]
            if not self.motion_mode:
                corners = self._corner_points_list(vitem)
                handles = []
                for i in range(4):
                    hi = VehicleResizeHandle(self, vitem, i)
                    hi.setPos(corners[i])
                    self.scene.addItem(hi)
                    handles.append(hi)
                self._handle_map[vitem] = handles
            self.vehicle_selection_changed.emit(veh_data)
            self._show_vehicle_tooltip_immediately(vitem, veh_data)
        else:
            QToolTip.hideText()
            self.vehicle_selection_changed.emit(None)

    def _make_selection_overlay_pen(self, alpha):
        color = QColor(SELECTION_OVERLAY_COLOR)
        color.setAlpha(max(0, min(255, int(alpha))))
        pen = QPen(color, SELECTION_OVERLAY_WIDTH, Qt.DashLine)
        pen.setCapStyle(Qt.FlatCap)
        pen.setJoinStyle(Qt.MiterJoin)
        return pen

    def _build_overlay_for_item(self, target_item):
        info = self.items_data.get(target_item)
        if info is None:
            return None
        item_type = info["type"]
        pen = self._make_selection_overlay_pen(255)
        if item_type == "vehicle":
            overlay = QGraphicsPolygonItem()
            overlay.setPolygon(target_item.polygon())
            overlay.setBrush(Qt.NoBrush)
        elif item_type == "lane":
            line = target_item.line()
            overlay = QGraphicsLineItem(line)
        elif item_type == "marker":
            r = MARKER_RADIUS + 4.0
            overlay = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            overlay.setBrush(Qt.NoBrush)
            overlay.setPos(
                float(info["data"].get("x_center", 0.0)),
                float(info["data"].get("y_center", 0.0)),
            )
        else:
            return None
        overlay.setPen(pen)
        overlay.setZValue(SELECTION_OVERLAY_Z)
        self._configure_observation_item(overlay)
        self.scene.addItem(overlay)
        return overlay

    def _sync_selection_overlay(self, target_item):
        overlay = self._selection_overlay_map.get(target_item)
        if overlay is None or target_item not in self.items_data:
            return
        item_type = self.items_data[target_item]["type"]
        if item_type == "vehicle" and isinstance(overlay, QGraphicsPolygonItem):
            overlay.setPolygon(target_item.polygon())
        elif item_type == "lane" and isinstance(overlay, QGraphicsLineItem):
            overlay.setLine(target_item.line())
        elif item_type == "marker" and isinstance(overlay, QGraphicsEllipseItem):
            data = self.items_data[target_item]["data"]
            overlay.setPos(
                float(data.get("x_center", 0.0)),
                float(data.get("y_center", 0.0)),
            )

    def _sync_all_lane_overlays(self):
        for item, info in self.items_data.items():
            if info["type"] == "lane" and item in self._selection_overlay_map:
                self._sync_selection_overlay(item)

    def _remove_selection_overlay(self, target_item):
        overlay = self._selection_overlay_map.pop(target_item, None)
        if overlay is not None:
            self.scene.removeItem(overlay)
        if not self._selection_overlay_map and self._breath_timer.isActive():
            self._breath_timer.stop()

    def _clear_selection_overlays(self):
        for overlay in list(self._selection_overlay_map.values()):
            self.scene.removeItem(overlay)
        self._selection_overlay_map.clear()
        if self._breath_timer.isActive():
            self._breath_timer.stop()

    def _refresh_selection_overlays(self):
        selected = [i for i in self.scene.selectedItems() if i in self.items_data]
        selected_set = set(selected)
        for target_item in list(self._selection_overlay_map.keys()):
            if target_item not in selected_set:
                overlay = self._selection_overlay_map.pop(target_item)
                self.scene.removeItem(overlay)
        for target_item in selected:
            if target_item in self._selection_overlay_map:
                continue
            overlay = self._build_overlay_for_item(target_item)
            if overlay is not None:
                self._selection_overlay_map[target_item] = overlay
        if self._selection_overlay_map:
            if not self._breath_timer.isActive():
                self._breath_timer.start()
            self._apply_breath_to_overlays()
        else:
            if self._breath_timer.isActive():
                self._breath_timer.stop()

    def _apply_breath_to_overlays(self):
        alpha = int(150 + 105 * (0.5 + 0.5 * math.sin(self._breath_phase)))
        dash_offset = (self._breath_phase * 2.0) % 16.0
        pen = self._make_selection_overlay_pen(alpha)
        pen.setDashOffset(dash_offset)
        for overlay in self._selection_overlay_map.values():
            overlay.setPen(pen)

    def _tick_breath(self):
        if not self._selection_overlay_map:
            self._breath_timer.stop()
            return
        self._breath_phase += SELECTION_BREATH_PHASE_STEP
        if self._breath_phase > 1e6:
            self._breath_phase = 0.0
        self._apply_breath_to_overlays()

    def _show_vehicle_tooltip_immediately(self, vehicle_item, veh_data):
        """选中车辆时立即弹出提示文字，避免必须悬停等待。"""
        tooltip_text = _vehicle_tooltip_text(veh_data)
        bounding = vehicle_item.boundingRect()
        scene_top_center = vehicle_item.mapToScene(
            QPointF(bounding.center().x(), bounding.top())
        )
        view_pt = self.mapFromScene(scene_top_center)
        global_pt = self.viewport().mapToGlobal(view_pt)
        QToolTip.showText(global_pt, tooltip_text, self.viewport())
