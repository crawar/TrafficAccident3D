"""Helpers for injecting shared Three.js model scripts into HTML."""

from utils.marker_model_style import inject_marker_model_script
from utils.vehicle_model_style import inject_vehicle_model_script


def inject_scene_model_scripts(html_content: str, vehicle_types=None) -> str:
    """Inject vehicle and marker model scripts in a fixed order.

    `vehicle_types` is forwarded to `inject_vehicle_model_script` so only the
    GLB models actually used in this scene get embedded; pass None to embed
    every known vehicle type (used by the all-types preview dialog).
    """
    html_content = inject_vehicle_model_script(html_content, vehicle_types)
    return inject_marker_model_script(html_content)
