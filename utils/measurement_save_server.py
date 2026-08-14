import json
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from utils.app_paths import app_base_dir, app_path
from utils.html_generator import (
    save_measurement_html,
    suggest_save_file_name_base,
    validate_save_file_name_base,
)
from utils.measurement_port_settings import (
    DEFAULT_MEASUREMENT_SAVE_PORT,
    load_measurement_port_settings,
    save_url_for_port,
)


_server = None
_thread = None
_alias_servers = []
_alias_threads = []
_save_url = ""
_bind_ok = False
_configured_port_busy = False
_lock = threading.Lock()


class MeasurementSaveHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _project_root():
    return app_base_dir()


def _history_dir():
    return app_path("history")


def _normalize_source_path(source_path):
    if not source_path:
        return ""
    source_path = str(source_path)
    if source_path.startswith("file:"):
        parsed = urlparse(source_path)
        source_path = unquote(parsed.path)
        if os.name == "nt" and source_path.startswith("/") and len(source_path) >= 3 and source_path[2] == ":":
            source_path = source_path[1:]
    return os.path.abspath(source_path)


def _is_allowed_html_path(source_path):
    source_abs = os.path.realpath(_normalize_source_path(source_path))
    history_abs = os.path.realpath(_history_dir())
    source_norm = os.path.normcase(source_abs)
    history_norm = os.path.normcase(history_abs)
    try:
        if os.path.commonpath([history_norm, source_norm]) != history_norm:
            return False
    except ValueError:
        return False
    return source_norm.endswith(".html")


def _history_save_ports():
    ports = set()
    history_dir = _history_dir()
    if not os.path.isdir(history_dir):
        return ports

    for name in os.listdir(history_dir):
        if not name.lower().endswith(".html"):
            continue
        path = os.path.join(history_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            continue
        for match in re.findall(r"http://127\.0\.0\.1:(\d+)/save-measurements", content):
            ports.add(int(match))
    return ports


def _bind_server(port, handler_class):
    server = MeasurementSaveHTTPServer(("127.0.0.1", port), handler_class)
    server.daemon_threads = True
    return server


def _make_handler_class():
    class MeasurementSaveHandler(BaseHTTPRequestHandler):
        def _send_cors_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Connection", "close")

        def _send_json(self, status_code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path not in ("/", "/health"):
                self._send_json(404, {"error": "Not found"})
                return
            self._send_json(200, {"ok": True})

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/save-measurements":
                self._send_json(404, {"error": "Not found"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 1024 * 1024:
                    self._send_json(400, {"error": "Invalid request size"})
                    return

                raw_body = self.rfile.read(content_length)
                payload = json.loads(raw_body.decode("utf-8"))
                source_html_path = _normalize_source_path(payload.get("sourceHtmlPath", ""))
                measurements = payload.get("measurements", [])
                file_name_base = payload.get("fileNameBase", None)
                overwrite = bool(payload.get("overwrite", False))
                target_html_path = payload.get("targetHtmlPath", None)

                if not isinstance(measurements, list):
                    self._send_json(400, {"error": "Invalid measurements"})
                    return
                if not source_html_path or not _is_allowed_html_path(source_html_path):
                    self._send_json(400, {"error": "Invalid source HTML path"})
                    return
                if not os.path.exists(source_html_path):
                    self._send_json(404, {"error": "Source HTML path does not exist"})
                    return

                if target_html_path:
                    target_html_path = _normalize_source_path(target_html_path)
                    if not _is_allowed_html_path(target_html_path):
                        self._send_json(400, {"error": "Invalid target HTML path"})
                        return

                if file_name_base is not None:
                    ok, message, cleaned = validate_save_file_name_base(file_name_base)
                    if not ok:
                        self._send_json(400, {"error": message})
                        return
                    file_name_base = cleaned
                else:
                    file_name_base = suggest_save_file_name_base(source_html_path)

                saved = save_measurement_html(
                    source_html_path,
                    measurements,
                    save_measurements_url=_save_url,
                    file_name_base=file_name_base,
                    overwrite=overwrite,
                    history_dir=_history_dir(),
                    target_html_path=target_html_path if overwrite else None,
                )
                if isinstance(saved, dict) and saved.get("needsOverwrite"):
                    self._send_json(
                        409,
                        {
                            "needsOverwrite": True,
                            "path": saved.get("path", ""),
                            "fileName": saved.get("fileName", ""),
                            "error": "File already exists",
                        },
                    )
                    return
                self._send_json(200, {"path": saved})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})

        def log_message(self, format, *args):
            return

    return MeasurementSaveHandler


def _start_alias_servers(handler_class, primary_port):
    global _alias_servers, _alias_threads
    _alias_servers = []
    _alias_threads = []
    for port in sorted(_history_save_ports()):
        if port == primary_port:
            continue
        try:
            alias_server = _bind_server(port, handler_class)
        except OSError:
            continue
        alias_thread = threading.Thread(target=alias_server.serve_forever, daemon=True)
        alias_thread.start()
        _alias_servers.append(alias_server)
        _alias_threads.append(alias_thread)


def start_measurement_save_server():
    """Start the local measurement-save HTTP server.

    Returns the active save URL string (may be empty if fixed-port bind failed).
    """
    global _server, _thread, _alias_servers, _alias_threads, _save_url
    global _bind_ok, _configured_port_busy

    with _lock:
        if _server is not None:
            return _save_url

        settings = load_measurement_port_settings()
        silent_random = bool(settings.get("silentRandom", True))
        configured_port = int(settings.get("port", DEFAULT_MEASUREMENT_SAVE_PORT))
        handler_class = _make_handler_class()

        _bind_ok = False
        _configured_port_busy = False
        _save_url = ""
        _alias_servers = []
        _alias_threads = []

        if silent_random:
            preferred_ports = [DEFAULT_MEASUREMENT_SAVE_PORT] + sorted(
                _history_save_ports()
            )
            for port in preferred_ports:
                try:
                    _server = _bind_server(port, handler_class)
                    break
                except OSError:
                    continue
            if _server is None:
                _server = _bind_server(0, handler_class)
            _save_url = save_url_for_port(_server.server_port)
            _bind_ok = True
            _thread = threading.Thread(target=_server.serve_forever, daemon=True)
            _thread.start()
            _start_alias_servers(handler_class, _server.server_port)
            return _save_url

        # Fixed port mode: bind only the user-configured port.
        try:
            _server = _bind_server(configured_port, handler_class)
        except OSError:
            _server = None
            _configured_port_busy = True
            _bind_ok = False
            _save_url = save_url_for_port(configured_port)
            return _save_url

        _save_url = save_url_for_port(_server.server_port)
        _bind_ok = True
        _configured_port_busy = False
        _thread = threading.Thread(target=_server.serve_forever, daemon=True)
        _thread.start()
        return _save_url


def stop_measurement_save_server():
    global _server, _thread, _alias_servers, _alias_threads, _save_url
    global _bind_ok, _configured_port_busy
    with _lock:
        servers = [_server] + list(_alias_servers)
        threads = [_thread] + list(_alias_threads)
        _server = None
        _thread = None
        _alias_servers = []
        _alias_threads = []
        _save_url = ""
        _bind_ok = False
        _configured_port_busy = False

    for server in servers:
        if server is None:
            continue
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
    for thread in threads:
        if thread is not None:
            thread.join(timeout=1)


def restart_measurement_save_server():
    stop_measurement_save_server()
    return start_measurement_save_server()


def get_current_save_url():
    with _lock:
        return _save_url


def get_current_listen_port():
    with _lock:
        if _server is not None and _bind_ok:
            return int(_server.server_port)
        return None


def get_preferred_save_url():
    with _lock:
        if _save_url:
            return _save_url
    return save_url_for_port(
        int(load_measurement_port_settings().get("port", DEFAULT_MEASUREMENT_SAVE_PORT))
    )


def is_measurement_server_bound():
    with _lock:
        return bool(_bind_ok and _server is not None)


def is_configured_port_busy():
    """True when fixed-port mode failed because the configured port is taken."""
    settings = load_measurement_port_settings()
    if settings.get("silentRandom", True):
        return False
    with _lock:
        return bool(_configured_port_busy)


def probe_port_available(port, treat_self_as_ok=True):
    """Return (ok, message) for whether *port* can be used.

    If this process already listens on *port*, reports ok when treat_self_as_ok.
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False, "端口无效"
    if port < 1 or port > 65535:
        return False, "端口需在 1–65535"

    current = get_current_listen_port()
    if treat_self_as_ok and current is not None and current == port and is_measurement_server_bound():
        return True, f"端口 {port} 已被本程序占用（可用）"

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False, f"端口 {port} 已被占用"
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return True, f"端口 {port} 可用"
