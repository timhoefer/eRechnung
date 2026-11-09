"""Connect to, or open, this installation. No invoice or permission-file access."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

START_TIMEOUT = 15


@contextmanager
def app_instance(base):
    """Share one UI/server between manual and automatic starts of this installation."""
    if sys.platform not in {"darwin", "linux"}:
        # Auto-start is unavailable here; preserve the existing manual entrypoint.
        yield True
        return
    import fcntl

    fd = os.open(base / ".mcp-instance.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint():
    value = os.environ.get("ERECHNUNG_MCP_URL", "")
    location = os.environ.get("ERECHNUNG_MCP_ENDPOINT_FILE")
    if location:
        value = json.loads(Path(location).read_text())["url"]
    parsed = urlparse(value)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.username or parsed.password or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment):
        raise ValueError("Use the local connection configuration supplied by eRechnung.")
    return value.rstrip("/")


def autostart_enabled():
    # Test-mode instances own ephemeral data and must never reopen production data.
    return (os.environ.get("ERECHNUNG_MCP_AUTOSTART") == "1"
            and os.environ.get("ERECHNUNG_MCP") == "1"
            and os.environ.get("ERECHNUNG_TEST_MODE") != "1"
            and bool(os.environ.get("ERECHNUNG_MCP_TOKEN"))
            and bool(os.environ.get("ERECHNUNG_MCP_ENDPOINT_FILE"))
            and sys.platform in {"darwin", "linux"})


def ready_endpoint():
    try:
        url = endpoint()
    except FileNotFoundError:
        return None
    try:
        # No credential is sent to a stale or unrelated port during discovery.
        with build_opener(ProxyHandler({}), NoRedirect()).open(url + "/agents/status", timeout=1) as response:
            status = json.loads(response.read(4097))
        if not isinstance(status, dict) or status.get("service") != "eRechnung":
            return None
        # An app with the feature disabled is still running. Never replace it.
        return url
    except HTTPError as exc:
        exc.close()
        return None
    except (URLError, HTTPException, OSError, ValueError):
        # The old port may now host another service (including non-HTTP data).
        # Only discovery failed: never send credentials or a tool call there.
        return None


def launch_app():
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().with_name("app.py")))
    command.append("--mcp-start")
    env = {key: value for key, value in os.environ.items() if not key.startswith("ERECHNUNG_MCP_")}
    # A separate app instance may outlive the bridge (PyInstaller restart contract).
    env.update(PYINSTALLER_RESET_ENVIRONMENT="1", FLASK_DEBUG="0")
    return subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)


def ensure_app():
    if not autostart_enabled():
        return endpoint()
    url = ready_endpoint()
    if url:
        return url
    import fcntl

    # Different agents share this short startup lock, not an app-data lock.
    location = Path(os.environ["ERECHNUNG_MCP_ENDPOINT_FILE"])
    lock_path = location.with_name(".mcp-start.lock")
    deadline = time.monotonic() + START_TIMEOUT
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a+b") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another connection is still starting eRechnung.") from None
                time.sleep(0.1)
        url = ready_endpoint()
        if url:
            return url
        child = launch_app()
        while time.monotonic() < deadline:
            url = ready_endpoint()
            if url:
                return url
            if child.poll() is not None:
                # A simultaneous manual start may own the instance lock before
                # publishing its endpoint. The redundant child exits in that case;
                # keep waiting for the owner instead of reporting a failed start.
                with app_instance(location.parent) as acquired:
                    if acquired:
                        raise OSError("eRechnung could not be started.")
            time.sleep(0.1)
    raise TimeoutError("eRechnung did not become ready in time.")
