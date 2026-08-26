"""Mixin: motion-path drawing overlay for ImageViewer."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsTextItem,
    QMessageBox,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtCore import Qt, QPointF, QTimer

from gui.motion_path_utils import (
    MAX_MOTION_PATH_POINTS,
    MOTION_DRIVE_FORWARD,
    MOTION_DRIVE_REVERSE,
    MOTION_WARN_DURATION_S,
    ensure_motion_fields,
    estimate_motion_duration_s,
    motion_speed_kmh,
    normalize_drive_mode,
    normalize_motion_path,
    path_color_for_duration,
)
from gui.motion_speed_dialog import MotionSpeedDialog
from utils.animation_settings import playback_speed_factor

MOTION_POINT_Z = 60
MOTION_LINE_Z = 55
MOTION_DURATION_LABEL_Z = 62
MOTION_DRIVE_LABEL_Z = 61
MOTION_BREATH_INTERVAL_MS = 80
MOTION_DASH_INTERVAL_MS = 40
MOTION_POINT_RADIUS = 9.0
MOTION_DURATION_LABEL_COLOR = QColor(40, 120, 255)
MOTION_DRIVE_LABEL_COLOR = QColor(20, 20, 20)


class MotionPathEditorMixin:
    def _init_motion_path_state(self):
        self.motion_mode = False
        self._path_edit_vehicle_item = None
        self._path_edit_active = False
        self._path_edit_points = []  # working list while editing
        self._path_point_items = []
        self._path_drive_label_items = []  # G/F text inside path points
        self._path_line_items = []
        self._path_center_line = None
        self._path_duration_label = None  # edit-mode duration at vehicle center
        self._path_breath_index = -1
        self._path_breath_phase = 0.0
        self._path_dash_offset = 0.0
        # vehicle_id -> {"points": [...], "lines": [...], "center_line": ..., "duration_label": ...}
        self._finished_path_overlays = {}
        self._path_breath_timer = QTimer(self)
        self._path_breath_timer.setInterval(MOTION_BREATH_INTERVAL_MS)
        self._path_breath_timer.timeout.connect(self._tick_path_breath)
        self._path_dash_timer = QTimer(self)
        self._path_dash_timer.setInterval(MOTION_DASH_INTERVAL_MS)
        self._path_dash_timer.timeout.connect(self._tick_path_dash)

    def set_motion_mode(self, enabled):
        enabled = bool(enabled)
        if self.motion_mode == enabled:
            if enabled:
                self._apply_type_visibility()
            return
        if self._path_edit_active:
            self._cancel_path_edit(save=False)
        self.motion_mode = enabled
        if enabled:
            self.case_mode = False
            self.draw_mode = False
            self.marker_mode = False
            self.add_vehicle_mode = False
            self.lane_draw_enabled = False
            self.marker_add_enabled = False
            self.scene.clearSelection()
            self._clear_all_handles()
            self._apply_vehicle_pointer_block_for_draw_mode(False)
            self._set_lane_interaction_enabled(False)
            self._set_marker_interaction_enabled(False)
        # Path overlays follow motion page or「显示全部图层」; sync in visibility.
        self._apply_type_visibility()

    def _should_show_path_overlays(self):
        """Paths show on the motion page, or when show-all / case page shows everything."""
        return bool(self.motion_mode or self.show_all_objects or self.case_mode)

    def _sync_finished_path_overlays(self):
        if self._should_show_path_overlays():
            self._rebuild_all_finished_path_overlays()
        else:
            self._clear_all_finished_path_overlays()

    def _apply_type_visibility_motion(self):
        """Called from _apply_type_visibility when motion_mode is on."""
        show_all = self.show_all_objects
        for item, info in self.items_data.items():
            in_ws = self._item_in_workspace(item, info)
            if info["type"] == "vehicle":
                item.setVisible(in_ws)
            else:
                item.setVisible(show_all and in_ws)
        for vehicle_item, arrow in self._front_arrow_map.items():
            arrow.setVisible(vehicle_item.isVisible())
        for vehicle_item, label in self._vehicle_label_map.items():
            label.setVisible(vehicle_item.isVisible())
        for marker_item, label in self._marker_label_map.items():
            label.setVisible(marker_item.isVisible())
        for lane_item, label in self._lane_label_map.items():
            label.setVisible(lane_item.isVisible())
        self._sync_finished_path_overlays()

    def _vehicle_item_for_data(self, veh):
        for item, info in self.items_data.items():
            if info["type"] == "vehicle" and info["data"] is veh:
                return item
        return None

    def _open_motion_speed_dialog(self, veh):
        ensure_motion_fields(veh)
        dialog = MotionSpeedDialog(
            vehicle_id=str(veh.get("vehicle_id", "") or ""),
            speed_kmh=motion_speed_kmh(veh),
            parent=self,
        )
        if dialog.exec() != MotionSpeedDialog.Accepted:
            return
        if dialog.result_speed_kmh is None:
            return
        veh["motion_speed_kmh"] = float(dialog.result_speed_kmh)
        self._refresh_finished_path_overlay_for_vehicle(veh)
        if self._path_edit_active and self._path_edit_vehicle_item is not None:
            if self.items_data.get(self._path_edit_vehicle_item, {}).get("data") is veh:
                self._refresh_path_edit_visuals()
        self._emit_objects_changed()

    def _begin_path_edit(self, vehicle_item):
        if vehicle_item not in self.items_data:
            return
        if self.items_data[vehicle_item]["type"] != "vehicle":
            return
        if self._path_edit_active:
            self._cancel_path_edit(save=False)
        veh = self.items_data[vehicle_item]["data"]
        ensure_motion_fields(veh)
        vid = str(veh.get("vehicle_id", "") or "")
        self._remove_finished_path_overlay(vid)
        self._path_edit_vehicle_item = vehicle_item
        self._path_edit_active = True
        self._path_edit_points = normalize_motion_path(veh.get("motion_path"))
        self._path_breath_index = len(self._path_edit_points) - 1
        self._path_breath_phase = 0.0
        self._path_dash_offset = 0.0
        self.scene.clearSelection()
        # Keep the edited vehicle highlighted, then lock all vehicles so clicks
        # pass through boxes and place path points (including on car bodies).
        vehicle_item.setSelected(True)
        self._sync_layer_interactions()
        self._clear_all_handles()
        self._rebuild_path_edit_items()
        if self._path_edit_points:
            self._path_breath_timer.start()
            self._path_dash_timer.start()
        else:
            self._path_breath_timer.stop()
            self._path_dash_timer.stop()
        if hasattr(self, "path_edit_state_changed"):
            self.path_edit_state_changed.emit(True)
        if hasattr(self, "_emit_hint_context"):
            self._emit_hint_context()

    def _cancel_path_edit(self, save=False):
        if not self._path_edit_active:
            return
        vehicle_item = self._path_edit_vehicle_item
        veh = None
        if vehicle_item is not None and vehicle_item in self.items_data:
            veh = self.items_data[vehicle_item]["data"]
        if save and veh is not None:
            points = list(self._path_edit_points)
            if points:
                veh["motion_path"] = points
            else:
                veh.pop("motion_path", None)
            ensure_motion_fields(veh)
        self._clear_path_edit_items()
        self._path_edit_active = False
        self._path_edit_vehicle_item = None
        self._path_edit_points = []
        self._path_breath_index = -1
        self._path_breath_timer.stop()
        self._path_dash_timer.stop()
        # Exit path-edit: restore vehicle pick/select on the motion page.
        if self.motion_mode:
            self._sync_layer_interactions()
        if veh is not None:
            self._refresh_finished_path_overlay_for_vehicle(veh)
            self._emit_objects_changed()
        if hasattr(self, "path_edit_state_changed"):
            self.path_edit_state_changed.emit(False)
        if hasattr(self, "_emit_hint_context"):
            self._emit_hint_context()

    def _finish_path_edit(self):
        if not self._path_edit_active:
            return
        vehicle_item = self._path_edit_vehicle_item
        if vehicle_item is None or vehicle_item not in self.items_data:
            self._cancel_path_edit(save=False)
            return
        veh = self.items_data[vehicle_item]["data"]
        points = list(self._path_edit_points)
        if not points:
            self._cancel_path_edit(save=True)
            return
        center = {"x": float(veh["x_center"]), "y": float(veh["y_center"])}
        full_points = points + [center]
        duration = estimate_motion_duration_s(
            full_points,
            motion_speed_kmh(veh),
            self._estimate_ppm(),
            playback_speed_factor(),
        )
        if duration > MOTION_WARN_DURATION_S:
            QMessageBox.information(
                self,
                "路径较长",
                f"按当前速度与动画执行倍率估算，该路径播放约 {duration:.1f} 秒（超过 30 秒），"
                "路径将显示为红色。可提高车速或缩短路径。",
            )
        self._cancel_path_edit(save=True)
        if hasattr(self, "path_edit_finished"):
            self.path_edit_finished.emit(float(duration), bool(duration > MOTION_WARN_DURATION_S))

    def _vehicle_center_point(self, veh):
        return {"x": float(veh["x_center"]), "y": float(veh["y_center"])}

    def _path_pen(self, rgb, animated=False):
        color = QColor(rgb[0], rgb[1], rgb[2], 220)
        pen = QPen(color, 3.0, Qt.CustomDashLine)
        pen.setCapStyle(Qt.RoundCap)
        pen.setDashPattern([6.0, 4.0])
        if animated:
            pen.setDashOffset(self._path_dash_offset)
        return pen

    def _path_color_for_vehicle(self, veh, points_with_center):
        duration = estimate_motion_duration_s(
            points_with_center,
            motion_speed_kmh(veh),
            self._estimate_ppm(),
            playback_speed_factor(),
        )
        return path_color_for_duration(duration)

    def _clear_path_edit_items(self):
        for item in self._path_point_items:
            self.scene.removeItem(item)
        for item in self._path_drive_label_items:
            self.scene.removeItem(item)
        for item in self._path_line_items:
            self.scene.removeItem(item)
        if self._path_center_line is not None:
            self.scene.removeItem(self._path_center_line)
        if self._path_duration_label is not None:
            self.scene.removeItem(self._path_duration_label)
        self._path_point_items = []
        self._path_drive_label_items = []
        self._path_line_items = []
        self._path_center_line = None
        self._path_duration_label = None

    def _path_duration_text(self, duration_s):
        try:
            value = float(duration_s)
        except (TypeError, ValueError):
            return "—"
        if value != value or value == float("inf") or value < 0:
            return "—"
        return f"{value:.1f}秒"

    def _make_path_duration_label(self, center, duration_s):
        label = QGraphicsTextItem(self._path_duration_text(duration_s))
        label.setDefaultTextColor(MOTION_DURATION_LABEL_COLOR)
        font = QFont(label.font())
        font.setPointSize(11)
        font.setBold(True)
        label.setFont(font)
        label.setZValue(MOTION_DURATION_LABEL_Z)
        self._configure_observation_item(label)
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.scene.addItem(label)
        self._place_path_duration_label(label, center)
        return label

    def _place_path_duration_label(self, label, center):
        if label is None or center is None:
            return
        anchor = QPointF(float(center["x"]), float(center["y"]))
        rect = label.boundingRect()
        # Slightly below vehicle center so it doesn't cover the vehicle ID label.
        view_pt = self.mapFromScene(anchor)
        top_left = QPointF(
            view_pt.x() - rect.width() * 0.5,
            view_pt.y() + 6.0,
        )
        label.setPos(self.mapToScene(top_left.toPoint()))

    def _refresh_path_duration_labels(self):
        """Reposition duration / drive labels after zoom/pan (ItemIgnoresTransformations)."""
        if self._path_duration_label is not None and self._path_edit_vehicle_item is not None:
            if self._path_edit_vehicle_item in self.items_data:
                veh = self.items_data[self._path_edit_vehicle_item]["data"]
                self._place_path_duration_label(
                    self._path_duration_label, self._vehicle_center_point(veh)
                )
        for i, label in enumerate(self._path_drive_label_items):
            if i < len(self._path_edit_points):
                pt = self._path_edit_points[i]
                self._place_path_drive_label(label, pt["x"], pt["y"])
        for overlay in self._finished_path_overlays.values():
            label = overlay.get("duration_label")
            center = overlay.get("center")
            if label is not None and center is not None:
                self._place_path_duration_label(label, center)
            drive_labels = overlay.get("drive_labels") or []
            pts = overlay.get("point_data") or []
            for i, dlabel in enumerate(drive_labels):
                if i < len(pts):
                    self._place_path_drive_label(dlabel, pts[i]["x"], pts[i]["y"])

    def _make_path_drive_label(self, x, y, drive):
        text = normalize_drive_mode(drive)
        label = QGraphicsTextItem(text)
        label.setDefaultTextColor(MOTION_DRIVE_LABEL_COLOR)
        font = QFont(label.font())
        font.setPointSize(8)
        font.setBold(True)
        label.setFont(font)
        label.setZValue(MOTION_DRIVE_LABEL_Z)
        self._configure_observation_item(label)
        label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.scene.addItem(label)
        self._place_path_drive_label(label, x, y)
        return label

    def _place_path_drive_label(self, label, x, y):
        if label is None:
            return
        rect = label.boundingRect()
        # Center the letter inside the path-point circle (screen-pixel space).
        if hasattr(self, "_label_pos_for_anchor"):
            label.setPos(
                self._label_pos_for_anchor(
                    QPointF(float(x), float(y)), rect, align="center"
                )
            )
        else:
            label.setPos(float(x) - rect.width() * 0.5, float(y) - rect.height() * 0.5)

    def _make_path_point_item(self, x, y, rgb, breathing=False, drive=MOTION_DRIVE_FORWARD):
        r = MOTION_POINT_RADIUS
        ellipse = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
        ellipse.setPos(float(x), float(y))
        alpha = 200 if not breathing else 255
        ellipse.setBrush(QBrush(QColor(rgb[0], rgb[1], rgb[2], alpha)))
        ellipse.setPen(QPen(QColor(30, 30, 30), 2))
        ellipse.setZValue(MOTION_POINT_Z)
        self._configure_observation_item(ellipse)
        ellipse.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.scene.addItem(ellipse)
        label = self._make_path_drive_label(x, y, drive)
        return ellipse, label

    def _rebuild_path_edit_items(self):
        self._clear_path_edit_items()
        if not self._path_edit_active or self._path_edit_vehicle_item is None:
            return
        veh = self.items_data[self._path_edit_vehicle_item]["data"]
        points = list(self._path_edit_points)
        center = self._vehicle_center_point(veh)
        preview = points + ([center] if points else [])
        rgb = self._path_color_for_vehicle(veh, preview) if preview else (120, 180, 255)
        for i, pt in enumerate(points):
            breathing = i == self._path_breath_index
            ellipse, drive_label = self._make_path_point_item(
                pt["x"],
                pt["y"],
                rgb,
                breathing=breathing,
                drive=pt.get("drive", MOTION_DRIVE_FORWARD),
            )
            self._path_point_items.append(ellipse)
            self._path_drive_label_items.append(drive_label)
        for i in range(1, len(points)):
            line = QGraphicsLineItem(
                points[i - 1]["x"],
                points[i - 1]["y"],
                points[i]["x"],
                points[i]["y"],
            )
            line.setPen(self._path_pen(rgb, animated=True))
            line.setZValue(MOTION_LINE_Z)
            self._configure_observation_item(line)
            self.scene.addItem(line)
            self._path_line_items.append(line)
        if points:
            duration = estimate_motion_duration_s(
                preview,
                motion_speed_kmh(veh),
                self._estimate_ppm(),
                playback_speed_factor(),
            )
            self._path_duration_label = self._make_path_duration_label(center, duration)
        self._apply_path_breath_visual()

    def _refresh_path_edit_visuals(self):
        self._rebuild_path_edit_items()

    def _try_add_path_point(self, scene_x, scene_y):
        if not self._path_edit_active:
            return False
        if len(self._path_edit_points) >= MAX_MOTION_PATH_POINTS:
            QMessageBox.information(
                self,
                "已达上限",
                f"每台车最多可添加 {MAX_MOTION_PATH_POINTS} 个路径点。",
            )
            return True
        if hasattr(self, "_clamp_point_to_workspace"):
            scene_x, scene_y = self._clamp_point_to_workspace(scene_x, scene_y)
        new_pt = {
            "x": float(scene_x),
            "y": float(scene_y),
            "drive": MOTION_DRIVE_FORWARD,
        }
        points = self._path_edit_points
        points.append(new_pt)
        self._path_breath_index = len(points) - 1
        self._path_breath_phase = 0.0
        self._rebuild_path_edit_items()
        self._path_breath_timer.start()
        self._path_dash_timer.start()
        if hasattr(self, "_emit_hint_context"):
            self._emit_hint_context()
        return True

    def finish_active_path_edit(self):
        self._finish_path_edit()

    def _toggle_breathing_path_drive(self):
        """Toggle G/F on the breathing path point (wheel while drawing)."""
        if not self._path_edit_active:
            return False
        idx = self._path_breath_index
        if idx < 0 or idx >= len(self._path_edit_points):
            return False
        pt = self._path_edit_points[idx]
        current = normalize_drive_mode(pt.get("drive"))
        pt["drive"] = (
            MOTION_DRIVE_REVERSE
            if current == MOTION_DRIVE_FORWARD
            else MOTION_DRIVE_FORWARD
        )
        # Update letter without full rebuild when possible.
        if idx < len(self._path_drive_label_items):
            label = self._path_drive_label_items[idx]
            label.setPlainText(pt["drive"])
            self._place_path_drive_label(label, pt["x"], pt["y"])
        else:
            self._rebuild_path_edit_items()
        return True

    def _delete_breathing_path_point(self):
        if not self._path_edit_active:
            return False
        if self._path_breath_index < 0 or not self._path_edit_points:
            return False
        # Only delete from the end (breathing point is always the last).
        if self._path_breath_index != len(self._path_edit_points) - 1:
            self._path_breath_index = len(self._path_edit_points) - 1
        self._path_edit_points.pop()
        self._path_breath_index = len(self._path_edit_points) - 1
        self._path_breath_phase = 0.0
        self._rebuild_path_edit_items()
        if not self._path_edit_points:
            self._path_breath_timer.stop()
            self._path_dash_timer.stop()
        return True

    def _tick_path_breath(self):
        if not self._path_edit_active or self._path_breath_index < 0:
            return
        self._path_breath_phase += 0.56
        self._apply_path_breath_visual()

    def _apply_path_breath_visual(self):
        import math

        idx = self._path_breath_index
        if idx < 0 or idx >= len(self._path_point_items):
            return
        item = self._path_point_items[idx]
        alpha = int(120 + 100 * (0.5 + 0.5 * math.sin(self._path_breath_phase)))
        brush = item.brush()
        color = brush.color()
        color.setAlpha(max(80, min(255, alpha)))
        item.setBrush(QBrush(color))

    def _tick_path_dash(self):
        if not self._path_edit_active:
            return
        self._path_dash_offset -= 1.2
        for line in self._path_line_items:
            pen = line.pen()
            pen.setDashOffset(self._path_dash_offset)
            line.setPen(pen)

    def _clear_all_finished_path_overlays(self):
        for vid in list(self._finished_path_overlays.keys()):
            self._remove_finished_path_overlay(vid)

    def _remove_finished_path_overlay(self, vehicle_id):
        overlay = self._finished_path_overlays.pop(str(vehicle_id), None)
        if not overlay:
            return
        for item in overlay.get("points", []):
            self.scene.removeItem(item)
        for item in overlay.get("drive_labels", []):
            self.scene.removeItem(item)
        for item in overlay.get("lines", []):
            self.scene.removeItem(item)
        if overlay.get("center_line") is not None:
            self.scene.removeItem(overlay["center_line"])
        if overlay.get("duration_label") is not None:
            self.scene.removeItem(overlay["duration_label"])

    def _set_finished_path_overlays_visible(self, visible):
        for overlay in self._finished_path_overlays.values():
            for item in overlay.get("points", []):
                item.setVisible(visible)
            for item in overlay.get("drive_labels", []):
                item.setVisible(visible)
            for item in overlay.get("lines", []):
                item.setVisible(visible)
            if overlay.get("center_line") is not None:
                overlay["center_line"].setVisible(visible)
            if overlay.get("duration_label") is not None:
                overlay["duration_label"].setVisible(visible)

    def _rebuild_all_finished_path_overlays(self):
        self._clear_all_finished_path_overlays()
        if not self._should_show_path_overlays():
            return
        for item, info in self.items_data.items():
            if info["type"] != "vehicle":
                continue
            self._refresh_finished_path_overlay_for_vehicle(info["data"])

    def _refresh_finished_path_overlay_for_vehicle(self, veh):
        ensure_motion_fields(veh)
        vid = str(veh.get("vehicle_id", "") or "")
        self._remove_finished_path_overlay(vid)
        if not self._should_show_path_overlays():
            return
        if self._path_edit_active and self._path_edit_vehicle_item in self.items_data:
            edit_veh = self.items_data[self._path_edit_vehicle_item]["data"]
            if edit_veh is veh:
                return
        points = normalize_motion_path(veh.get("motion_path"))
        if not points:
            return
        center = self._vehicle_center_point(veh)
        full = points + [center]
        rgb = self._path_color_for_vehicle(veh, full)
        point_items = []
        drive_labels = []
        line_items = []
        for pt in points:
            ellipse, drive_label = self._make_path_point_item(
                pt["x"],
                pt["y"],
                rgb,
                breathing=False,
                drive=pt.get("drive", MOTION_DRIVE_FORWARD),
            )
            point_items.append(ellipse)
            drive_labels.append(drive_label)
        for i in range(1, len(points)):
            line = QGraphicsLineItem(
                points[i - 1]["x"],
                points[i - 1]["y"],
                points[i]["x"],
                points[i]["y"],
            )
            line.setPen(self._path_pen(rgb, animated=False))
            line.setZValue(MOTION_LINE_Z)
            self._configure_observation_item(line)
            self.scene.addItem(line)
            line_items.append(line)
        center_line = QGraphicsLineItem(
            points[-1]["x"], points[-1]["y"], center["x"], center["y"]
        )
        center_line.setPen(self._path_pen(rgb, animated=False))
        center_line.setZValue(MOTION_LINE_Z)
        self._configure_observation_item(center_line)
        self.scene.addItem(center_line)
        duration = estimate_motion_duration_s(
            full,
            motion_speed_kmh(veh),
            self._estimate_ppm(),
            playback_speed_factor(),
        )
        duration_label = self._make_path_duration_label(center, duration)
        self._finished_path_overlays[vid] = {
            "points": point_items,
            "drive_labels": drive_labels,
            "point_data": [
                {
                    "x": float(pt["x"]),
                    "y": float(pt["y"]),
                    "drive": normalize_drive_mode(pt.get("drive")),
                }
                for pt in points
            ],
            "lines": line_items,
            "center_line": center_line,
            "duration_label": duration_label,
            "center": {"x": center["x"], "y": center["y"]},
        }
