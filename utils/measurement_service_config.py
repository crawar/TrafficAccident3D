from utils.measurement_port_settings import (
    DEFAULT_MEASUREMENT_SAVE_PORT,
    load_measurement_port_settings,
    save_url_for_port,
)

# Backward-compatible defaults (preferred / factory port).
MEASUREMENT_SAVE_PORT = DEFAULT_MEASUREMENT_SAVE_PORT
MEASUREMENT_SAVE_BASE_URL = f"http://127.0.0.1:{MEASUREMENT_SAVE_PORT}"
MEASUREMENT_SAVE_URL = f"{MEASUREMENT_SAVE_BASE_URL}/save-measurements"
MEASUREMENT_HEALTH_URL = f"{MEASUREMENT_SAVE_BASE_URL}/health"


def configured_measurement_save_port():
    settings = load_measurement_port_settings()
    if settings.get("silentRandom", True):
        return DEFAULT_MEASUREMENT_SAVE_PORT
    return int(settings.get("port", DEFAULT_MEASUREMENT_SAVE_PORT))


def configured_measurement_save_url():
    return save_url_for_port(configured_measurement_save_port())
