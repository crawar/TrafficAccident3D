"""Canvas crop overlay and expanded workspace for ImageViewer."""

from __future__ import annotations

from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsItem
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtCore import Qt, QPointF, QRectF, QLineF

CROP_MIN_PX = 64.0
CROP_MIN_FRAC = 0.08
CROP_PAGE_PAD_FRAC = 0.08
CROP_HANDLE_HIT_PX = 16.0
CROP_BORDER_COLOR = QColor("#2dd4bf")
CROP_HANDLE_FILL = QColor("#f0fdfa")
BOARD_COLOR = QColor("#0b1220")
DIM_COLOR = QColor(0, 0, 0, 128)

HANDLE_TL, HANDLE_TR, HANDLE_BR, HANDLE_BL = 0, 1, 2, 3
HANDLE_T, HANDLE_R, HANDLE_B, HANDLE_L = 4, 5, 6, 7
CROP_HANDLE_CURSORS = (
    Qt.SizeFDiagCursor,
    Qt.SizeBDiagCursor,
    Qt.SizeFDiagCursor,
    Qt.SizeBDiagCursor,
    Qt.SizeVerCursor,
    Qt.SizeHorCursor,
    Qt.SizeVerCursor,
    Qt.SizeHorCursor,
)
_MOVE_LEFT = {HANDLE_TL, HANDLE_BL, HANDLE_L}
_MOVE_RIGHT = {HANDLE_TR, HANDLE_BR, HANDLE_R}
_MOVE_TOP = {HANDLE_TL, HANDLE_TR, HANDLE_T}
_MOVE_BOTTOM = {HANDLE_BL, HANDLE_BR, HANDLE_B}


def _finite_positive(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:
        return None
    return number


def normalize_canvas_crop(raw):
    if not isinstance(raw, dict):
        return None
    try:
        x = float(raw.get("x"))
        y = float(raw.get("y"))
    except (TypeError, ValueError):
        return None
    if x != x or y != y:
        return None
    width = _finite_positive(raw.get("width"))
    height = _finite_positive(raw.get("height"))
    size = _finite_positive(raw.get("size"))
    if width is None or height is None:
        if size is None:
            return None
        width = size
        height = size
    return {"x": x, "y": y, "width": width, "height": height}


def default_canvas_crop(img_w, img_h):
    width = max(1.0, float(img_w))
    height = max(1.0, float(img_h))
    size = min(width, height)
    return {
        "x": (width - size) / 2.0,
        "y": (height - size) / 2.0,
        "width": size,
        "height": size,
    }


def _min_crop_wh(img_w, img_h):
    width = max(1.0, float(img_w))
    height = max(1.0, float(img_h))
    short_side = min(width, height)
    min_size = max(CROP_MIN_PX, short_side * CROP_MIN_FRAC)
    return min(min_size, width), min(min_size, height)


def clamp_canvas_crop(crop, img_w, img_h):
    width = max(1.0, float(img_w))
    height = max(1.0, float(img_h))
    parsed = normalize_canvas_crop(crop)
    if parsed is None:
        return default_canvas_crop(width, height)
    min_w, min_h = _min_crop_wh(width, height)
    crop_w = min(max(parsed["width"], min_w), width)
    crop_h = min(max(parsed["height"], min_h), height)
    x = min(max(parsed["x"], 0.0), width - crop_w)
    y = min(max(parsed["y"], 0.0), height - crop_h)
    return {"x": x, "y": y, "width": crop_w, "height": crop_h}


def crop_rect_from_dict(crop):
    return QRectF(
        float(crop["x"]),
        float(crop["y"]),
        float(crop["width"]),
        float(crop["height"]),
    )


def workspace_rect_from_crop(crop):
    crop_w = float(crop["width"])
    crop_h = float(crop["height"])
    pad = min(crop_w, crop_h) / 2.0
    return QRectF(
        float(crop["x"]) - pad,
        float(crop["y"]) - pad,
        crop_w + 2.0 * pad,
        crop_h + 2.0 * pad,
    )


def crop_page_scene_rect(img_w, img_h):
    width = max(1.0, float(img_w))
    height = max(1.0, float(img_h))
    pad = min(width, height) * CROP_PAGE_PAD_FRAC
    return QRectF(-pad, -pad, width + 2.0 * pad, height + 2.0 * pad)


def edit_page_fit_rect(crop):
    hole = crop_rect_from_dict(crop)
    pad = min(hole.width(), hole.height()) * CROP_PAGE_PAD_FRAC
    return hole.adjusted(-pad, -pad, pad, pad)


def edit_page_scene_rect(crop, img_w, img_h):
    image = QRectF(0.0, 0.0, max(1.0, float(img_w)), max(1.0, float(img_h)))
    return workspace_rect_from_crop(crop).united(image)


def _hole_surround_rects(outer, hole):
    rects = [
        QRectF(outer.left(), outer.top(), outer.width(), hole.top() - outer.top()),
        QRectF(
            outer.left(),
            hole.bottom(),
            outer.width(),
            outer.bottom() - hole.bottom(),
        ),
        QRectF(outer.left(), hole.top(), hole.left() - outer.left(), hole.height()),
        QRectF(
            hole.right(),
            hole.top(),
            outer.right() - hole.right(),
            hole.height(),
        ),
    ]
    return [r for r in rects if r.width() > 0.5 and r.height() > 0.5]


class CanvasCropMixin:
    def _init_canvas_crop_state(self):
        self.canvas_crop_mode = False
        self._canvas_crop = None
        self._crop_mask_items = []
        self._crop_border_item = None
        self._crop_handles = []
        self._workspace_board_item = None
        self._crop_panning = False
        self._crop_grab_offset = None
        self._crop_resize_handle = None
        self._crop_resize_start = None

    def _clear_crop_overlay_refs(self):
        self._crop_mask_items = []
        self._crop_border_item = None
        self._crop_handles = []
        self._workspace_board_item = None
        self._crop_panning = False
        self._crop_grab_offset = None
        self._crop_resize_handle = None
        self._crop_resize_start = None

    def _ensure_canvas_crop(self):
        img_w, img_h = self._image_bounds_wh()
        self._canvas_crop = clamp_canvas_crop(self._canvas_crop, img_w, img_h)
        return self._canvas_crop

    def get_canvas_crop(self):
        crop = self._ensure_canvas_crop()
        return {
            "x": float(crop["x"]),
            "y": float(crop["y"]),
            "width": float(crop["width"]),
            "height": float(crop["height"]),
        }

    def set_canvas_crop(self, crop, refit=False):
        img_w, img_h = self._image_bounds_wh()
        self._canvas_crop = clamp_canvas_crop(crop, img_w, img_h)
        self._sync_crop_visuals()
        if refit:
            self._auto_fit_image = True
            self._fit_image_to_view()
        if hasattr(self, "_emit_hint_context"):
            self._emit_hint_context()

    def reset_canvas_crop(self):
        img_w, img_h = self._image_bounds_wh()
        self.set_canvas_crop(default_canvas_crop(img_w, img_h), refit=True)

    def _crop_center(self):
        crop = self._ensure_canvas_crop()
        return QPointF(
            crop["x"] + crop["width"] / 2.0,
            crop["y"] + crop["height"] / 2.0,
        )

    def _workspace_rect(self):
        return workspace_rect_from_crop(self._ensure_canvas_crop())

    def _crop_rect(self):
        return crop_rect_from_dict(self._ensure_canvas_crop())

    def _crop_page_scene_rect(self):
        img_w, img_h = self._image_bounds_wh()
        return crop_page_scene_rect(img_w, img_h)

    def _edit_page_fit_rect(self):
        return edit_page_fit_rect(self._ensure_canvas_crop())

    def _edit_page_scene_rect(self):
        img_w, img_h = self._image_bounds_wh()
        return edit_page_scene_rect(self._ensure_canvas_crop(), img_w, img_h)

    def _point_in_workspace(self, x, y):
        return self._workspace_rect().contains(float(x), float(y))

    def _clamp_point_to_workspace(self, x, y):
        rect = self._workspace_rect()
        return (
            min(max(float(x), rect.left()), rect.right()),
            min(max(float(y), rect.top()), rect.bottom()),
        )

    def _item_in_workspace(self, item, info):
        rect = self._workspace_rect()
        data = info.get("data") or {}
        kind = info.get("type")
        if kind in ("vehicle", "marker"):
            return rect.contains(
                float(data.get("x_center", 0.0)),
                float(data.get("y_center", 0.0)),
            )
        if kind == "lane":
            line = item.line()
            box = QRectF(line.p1(), line.p2()).normalized().adjusted(-2, -2, 2, 2)
            return rect.intersects(box)
        return True

    def set_canvas_crop_mode(self, enabled):
        enabled = bool(enabled)
        if enabled:
            if getattr(self, "motion_mode", False):
                self.set_motion_mode(False)
            self.case_mode = False
            self.draw_mode = False
            self.marker_mode = False
            self.add_vehicle_mode = False
            self.lane_draw_enabled = False
            self.marker_add_enabled = False
            self.drawing = False
            self.current_line = None
            self._add_drawing = False
            if self._add_rect_preview:
                self.scene.removeItem(self._add_rect_preview)
                self._add_rect_preview = None
            self._reset_lane_drag_state()
            self.scene.clearSelection()
            self._clear_all_handles()
            self._apply_vehicle_pointer_block_for_draw_mode(True)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(False)
            self.unsetCursor()
        self.canvas_crop_mode = enabled
        self._sync_crop_visuals()
        self._auto_fit_image = True
        self._fit_image_to_view()
        self._apply_type_visibility()
        if hasattr(self, "_emit_hint_context"):
            self._emit_hint_context()

    def _ensure_crop_overlay_items(self):
        if self.image_item is None:
            return
        if self._workspace_board_item is None:
            board = QGraphicsRectItem()
            board.setBrush(QBrush(BOARD_COLOR))
            board.setPen(QPen(Qt.NoPen))
            board.setZValue(-3)
            board.setAcceptedMouseButtons(Qt.NoButton)
            self.scene.addItem(board)
            self._workspace_board_item = board
        if not self._crop_mask_items:
            for _ in range(4):
                item = QGraphicsRectItem()
                item.setPen(QPen(Qt.NoPen))
                item.setZValue(-0.5)
                item.setAcceptedMouseButtons(Qt.NoButton)
                self.scene.addItem(item)
                self._crop_mask_items.append(item)
        if self._crop_border_item is None:
            border = QGraphicsRectItem()
            border.setBrush(QBrush(Qt.NoBrush))
            border.setZValue(90)
            border.setAcceptedMouseButtons(Qt.NoButton)
            self.scene.addItem(border)
            self._crop_border_item = border
        if len(self._crop_handles) != 8:
            for handle in self._crop_handles:
                if handle.scene() is self.scene:
                    self.scene.removeItem(handle)
            self._crop_handles = []
            for _ in range(8):
                handle = QGraphicsRectItem(-6, -6, 12, 12)
                handle.setBrush(QBrush(CROP_HANDLE_FILL))
                handle.setPen(QPen(CROP_BORDER_COLOR, 1.5))
                handle.setZValue(91)
                handle.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
                handle.setAcceptedMouseButtons(Qt.NoButton)
                self.scene.addItem(handle)
                self._crop_handles.append(handle)

    def _sync_crop_visuals(self):
        if self.image_item is None:
            return
        self._ensure_crop_overlay_items()
        crop = self._ensure_canvas_crop()
        hole = crop_rect_from_dict(crop)
        img_w, img_h = self._image_bounds_wh()
        image_rect = QRectF(0, 0, img_w, img_h)
        padded = crop_page_scene_rect(img_w, img_h)
        edit_scene = edit_page_scene_rect(crop, img_w, img_h)
        if self._workspace_board_item is not None:
            self._workspace_board_item.setRect(
                padded if self.canvas_crop_mode else edit_scene
            )
            self._workspace_board_item.setVisible(True)
        surround = _hole_surround_rects(image_rect, hole)
        brush = QBrush(DIM_COLOR)
        for index, item in enumerate(self._crop_mask_items):
            if index < len(surround):
                item.setRect(surround[index])
                item.setBrush(brush)
                item.setVisible(True)
            else:
                item.setVisible(False)
        if self._crop_border_item is not None:
            self._crop_border_item.setRect(hole)
            width = 2.5 if self.canvas_crop_mode else 1.5
            self._crop_border_item.setPen(QPen(CROP_BORDER_COLOR, width))
            self._crop_border_item.setVisible(True)
        mid_x = hole.center().x()
        mid_y = hole.center().y()
        positions = [
            hole.topLeft(),
            hole.topRight(),
            hole.bottomRight(),
            hole.bottomLeft(),
            QPointF(mid_x, hole.top()),
            QPointF(hole.right(), mid_y),
            QPointF(mid_x, hole.bottom()),
            QPointF(hole.left(), mid_y),
        ]
        for handle, pos in zip(self._crop_handles, positions):
            handle.setPos(pos)
            handle.setVisible(self.canvas_crop_mode)
        if self.canvas_crop_mode:
            self.scene.setSceneRect(padded)
        else:
            self.scene.setSceneRect(edit_scene)

    def _is_crop_overlay_item(self, item):
        if item is None:
            return False
        if item is self._workspace_board_item or item is self._crop_border_item:
            return True
        if item in self._crop_mask_items or item in self._crop_handles:
            return True
        return False

    def _crop_handle_index_at_view(self, view_pos):
        if not self.canvas_crop_mode:
            return None
        for index, handle in enumerate(self._crop_handles):
            mapped = self.mapFromScene(handle.scenePos())
            if QLineF(QPointF(view_pos), QPointF(mapped)).length() <= CROP_HANDLE_HIT_PX:
                return index
        return None

    def _crop_cursor_for_handle(self, handle):
        if handle is None or handle < 0 or handle >= len(CROP_HANDLE_CURSORS):
            return Qt.OpenHandCursor
        return CROP_HANDLE_CURSORS[handle]

    def _update_crop_cursor(self, view_pos):
        if not self.canvas_crop_mode:
            return
        if self._crop_resize_handle is not None:
            self.viewport().setCursor(self._crop_cursor_for_handle(self._crop_resize_handle))
            return
        if self._crop_panning:
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        handle = self._crop_handle_index_at_view(view_pos)
        if handle is not None:
            self.viewport().setCursor(self._crop_cursor_for_handle(handle))
        else:
            self.viewport().setCursor(Qt.OpenHandCursor)

    def _apply_crop(self, crop):
        img_w, img_h = self._image_bounds_wh()
        self._canvas_crop = clamp_canvas_crop(crop, img_w, img_h)
        self._sync_crop_visuals()

    def _resized_crop_from_handle(self, handle, scene_pos):
        start = self._crop_resize_start or self._ensure_canvas_crop()
        img_w, img_h = self._image_bounds_wh()
        min_w, min_h = _min_crop_wh(img_w, img_h)
        left = float(start["x"])
        top = float(start["y"])
        right = left + float(start["width"])
        bottom = top + float(start["height"])
        x = min(max(float(scene_pos.x()), 0.0), img_w)
        y = min(max(float(scene_pos.y()), 0.0), img_h)
        if handle in _MOVE_LEFT:
            left = min(x, right - min_w)
        if handle in _MOVE_RIGHT:
            right = max(x, left + min_w)
        if handle in _MOVE_TOP:
            top = min(y, bottom - min_h)
        if handle in _MOVE_BOTTOM:
            bottom = max(y, top + min_h)
        return {
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }

    def _handle_crop_press(self, event):
        if not self.canvas_crop_mode or event.button() != Qt.LeftButton:
            return False
        handle = self._crop_handle_index_at_view(event.pos())
        if handle is not None:
            self._crop_resize_handle = handle
            self._crop_resize_start = dict(self._ensure_canvas_crop())
            self.viewport().setCursor(self._crop_cursor_for_handle(handle))
        else:
            crop = self._ensure_canvas_crop()
            scene_pos = self.mapToScene(event.pos())
            self._crop_panning = True
            self._crop_grab_offset = QPointF(
                scene_pos.x() - crop["x"],
                scene_pos.y() - crop["y"],
            )
            self.viewport().setCursor(Qt.ClosedHandCursor)
        event.accept()
        return True

    def _handle_crop_move(self, event):
        if not self.canvas_crop_mode:
            return False
        if self._crop_resize_handle is not None:
            scene_pos = self.mapToScene(event.pos())
            self._apply_crop(
                self._resized_crop_from_handle(self._crop_resize_handle, scene_pos)
            )
            event.accept()
            return True
        if self._crop_panning and self._crop_grab_offset is not None:
            scene_pos = self.mapToScene(event.pos())
            crop = dict(self._ensure_canvas_crop())
            crop["x"] = scene_pos.x() - self._crop_grab_offset.x()
            crop["y"] = scene_pos.y() - self._crop_grab_offset.y()
            self._apply_crop(crop)
            event.accept()
            return True
        self._update_crop_cursor(event.pos())
        return False

    def _handle_crop_release(self, event):
        if not self.canvas_crop_mode:
            return False
        if event.button() != Qt.LeftButton:
            return False
        if self._crop_panning or self._crop_resize_handle is not None:
            self._crop_panning = False
            self._crop_grab_offset = None
            self._crop_resize_handle = None
            self._crop_resize_start = None
            self._update_crop_cursor(event.pos())
            if hasattr(self, "_emit_hint_context"):
                self._emit_hint_context()
            event.accept()
            return True
        return False
