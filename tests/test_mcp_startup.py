"""Auto-start uses fictional app data and a substituted launcher, never the installed app."""
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from lxml import html
from test_mcp_access import BUYER, OTHER, call, configure, decide, grant, invoice_args
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from werkzeug.serving import make_server

import app as m
import desktop
import mcp_connection as connection
import mcp_server
from mcp_app import publish_endpoint


@pytest.fixture
def startup(client, monkeypatch):
    token = grant(client)
    location = m.BASE / "mcp-endpoint.json"
    monkeypatch.setenv("ERECHNUNG_MCP_TOKEN", token)
    monkeypatch.setenv("ERECHNUNG_MCP_ENDPOINT_FILE", str(location))
    monkeypatch.setenv("ERECHNUNG_MCP", "1")
    monkeypatch.setenv("ERECHNUNG_MCP_AUTOSTART", "1")
    monkeypatch.delenv("ERECHNUNG_TEST_MODE", raising=False)
    servers = []
    threads = []
    def launch():
        server = make_server("127.0.0.1", 0, m.app, threaded=True)
        publish_endpoint(m, f"http://127.0.0.1:{server.server_port}")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(connection, "launch_app", launch)
    yield token, location, servers
    for server, thread in zip(servers, threads, strict=True):
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_start_preserves_issuer_scopes_and_approval(client, startup):
    token, _, servers = startup
    # Initialize the native validator on pytest's main thread, where its cached
    # processor is also finalized; the actual requests below use HTTP workers.
    assert call(token, "check_invoice", **invoice_args())["ok"]
    assert mcp_server.app_call("list_issuers", {})["issuers"][0]["id"] == "default"
    assert not mcp_server.app_call("get_issuer", {"issuer": OTHER})["ok"]
    for operation, arguments in [
        ("create_invoice", invoice_args()),
        ("save_customer", {"issuer": "default", "buyer": {**BUYER, "city": "Hamburg"}}),
        ("delete_customer", {"issuer": "default", "name": BUYER["name"]}),
    ]:
        pending = mcp_server.app_call(operation, arguments)
        assert pending["status"] == "approval_required", pending
        assert not list(m.OUTPUT_DIR.glob("*.pdf"))
        assert json.loads(m.CUSTOMERS_FILE.read_text())[0] == BUYER
        assert decide(client, pending["request_id"], "deny").status_code == 303
    assert len(servers) == 1


@pytest.mark.parametrize("state", ["disabled", "revoked", "read_only", "feature_off"])
def test_start_cannot_restore_or_expand_permissions(client, startup, monkeypatch, state):
    token, _, servers = startup
    if state == "disabled":
        configure(client, "disable")
    elif state == "revoked":
        identifier = m.app.extensions["mcp_access"].authenticate(token, m.DATA_DIR)["id"]
        configure(client, "revoke", connection=identifier)
    elif state == "read_only":
        monkeypatch.setenv("ERECHNUNG_MCP_TOKEN", grant(client, writable=False))
    else:
        monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    before = (m.BASE / "agent_access.json").read_bytes()
    result = mcp_server.app_call("delete_customer", {"issuer": "default", "name": BUYER["name"]})
    assert not result["ok"] and result.get("status") != "approval_required"
    assert (m.BASE / "agent_access.json").read_bytes() == before
    assert json.loads(m.CUSTOMERS_FILE.read_text())[0] == BUYER
    assert not m.app.extensions["mcp_access"].pending
    # Even a running app with its feature flag off must not be replaced.
    assert not mcp_server.app_call("delete_customer", {"issuer": "default", "name": BUYER["name"]})["ok"]
    assert len(servers) == 1


def test_parallel_connections_start_only_one_instance(startup):
    _, _, servers = startup
    barrier = threading.Barrier(4)
    def connect(_):
        barrier.wait()
        return connection.ensure_app()
    with ThreadPoolExecutor(max_workers=4) as pool:
        urls = list(pool.map(connect, range(4)))
    assert len(set(urls)) == 1 and len(servers) == 1


def test_stale_port_is_replaced_before_any_mutation(startup):
    _, location, servers = startup
    closed = make_server("127.0.0.1", 0, m.app)
    location.write_text(json.dumps({"url": f"http://127.0.0.1:{closed.server_port}"}))
    closed.server_close()
    assert mcp_server.app_call("list_issuers", {})["ok"]
    assert len(servers) == 1


@pytest.mark.parametrize("status, body", [
    ("404 Not Found", b"Not eRechnung"),
    ("200 OK", b'{"service":"different app"}'),
    ("200 OK", b"<html>Another service</html>"),
    ("302 Found", b""),
])
def test_reused_port_starts_app_without_disclosing_credentials_or_skipping_approval(startup, status, body):
    _, location, servers = startup
    grants = (m.BASE / "agent_access.json").read_bytes()
    received = []
    def unrelated(environ, start_response):
        received.append((environ["REQUEST_METHOD"], environ["PATH_INFO"], environ.get("HTTP_AUTHORIZATION")))
        start_response(status, [("Content-Type", "application/json"),
                                ("Location", "http://127.0.0.1:9/do-not-follow")])
        return [body]
    server = make_server("127.0.0.1", 0, unrelated)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    location.write_text(json.dumps({"url": f"http://127.0.0.1:{server.server_port}"}))
    try:
        assert mcp_server.app_call("list_issuers", {})["ok"]
        assert received and all(item == ("GET", "/agents/status", None) for item in received)
        assert len(servers) == 1 and servers[0].server_port != server.server_port
        pending = mcp_server.app_call("delete_customer", {"issuer": "default", "name": BUYER["name"]})
        assert pending["status"] == "approval_required"
        assert json.loads(m.CUSTOMERS_FILE.read_text())[0] == BUYER
        assert (m.BASE / "agent_access.json").read_bytes() == grants
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("entrypoint", [desktop, m], ids=["desktop", "source"])
@pytest.mark.parametrize("automatic_first", [False, True], ids=["manual-first", "automatic-first"])
def test_manual_and_automatic_start_share_one_window(client, monkeypatch, entrypoint, automatic_first):
    import webbrowser

    import werkzeug.serving

    m.BASE.mkdir()
    opened = threading.Event()
    close = threading.Event()
    windows = []
    def show(*args, **kwargs):
        windows.append(True)
        opened.set()
        assert close.wait(5)
    monkeypatch.setattr(desktop, "_show_app", show)
    monkeypatch.setattr(m.app, "run", show)
    monkeypatch.setattr(werkzeug.serving, "make_server",
                        lambda *a, **kw: SimpleNamespace(server_port=12345, serve_forever=show))
    monkeypatch.setattr(webbrowser, "open", lambda *a: None)
    monkeypatch.setenv("FLASK_DEBUG", "0")
    monkeypatch.setattr(sys, "argv", ["eRechnung", *(["--mcp-start"] if automatic_first else [])])
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(entrypoint.main)
        try:
            assert opened.wait(5)
            monkeypatch.setattr(sys, "argv", ["eRechnung", *([] if automatic_first else ["--mcp-start"])])
            entrypoint.main()
            assert windows == [True]
        finally:
            close.set()
        running.result(timeout=5)


@pytest.mark.parametrize("state", ["enabled", "disabled", "revoked", "read_only", "feature_off"])
def test_bridge_waits_for_manual_start_without_changing_permissions(client, startup, monkeypatch, state):
    token, _, servers = startup
    if state == "disabled":
        configure(client, "disable")
    elif state == "revoked":
        identifier = m.app.extensions["mcp_access"].authenticate(token, m.DATA_DIR)["id"]
        configure(client, "revoke", connection=identifier)
    elif state == "read_only":
        monkeypatch.setenv("ERECHNUNG_MCP_TOKEN", grant(client, writable=False))
    elif state == "feature_off":
        monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    grants = (m.BASE / "agent_access.json").read_bytes()
    publish_manual = connection.launch_app
    exited = threading.Event()
    def poll():
        exited.set()
        return 0
    monkeypatch.setattr(connection, "launch_app", lambda: SimpleNamespace(poll=poll))
    with connection.app_instance(m.BASE) as acquired, ThreadPoolExecutor(max_workers=1) as pool:
        assert acquired
        pending = pool.submit(mcp_server.app_call, "delete_customer", {"issuer": "default", "name": BUYER["name"]})
        assert exited.wait(5)
        publish_manual()
        result = pending.result(timeout=5)
        if state == "enabled":
            assert result["status"] == "approval_required"
        else:
            assert not result["ok"] and result.get("status") != "approval_required"
            assert not m.app.extensions["mcp_access"].pending
    assert len(servers) == 1
    assert json.loads(m.CUSTOMERS_FILE.read_text())[0] == BUYER
    assert (m.BASE / "agent_access.json").read_bytes() == grants


def test_start_failure_is_controlled_and_does_not_write_permissions(startup, monkeypatch):
    _, _, servers = startup
    before = (m.BASE / "agent_access.json").read_bytes()
    monkeypatch.setattr(connection, "launch_app", lambda: SimpleNamespace(poll=lambda: 1))
    result = mcp_server.app_call("list_issuers", {})
    assert not result["ok"] and result["error"] == "connection_failed"
    assert not servers and (m.BASE / "agent_access.json").read_bytes() == before


def test_start_timeout_is_bounded(startup, monkeypatch):
    ticks = iter([0, 0, connection.START_TIMEOUT + 1])
    monkeypatch.setattr(connection.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(connection, "launch_app", lambda: SimpleNamespace(poll=lambda: None))
    result = mcp_server.app_call("list_issuers", {})
    assert result["error"] == "connection_failed" and result["reason"] == "TimeoutError"


@pytest.mark.parametrize("change", [
    {"ERECHNUNG_MCP_TOKEN": ""}, {"ERECHNUNG_MCP_AUTOSTART": "0"},
    {"ERECHNUNG_MCP": "0"}, {"ERECHNUNG_TEST_MODE": "1"}, {"ERECHNUNG_MCP_ENDPOINT_FILE": ""},
])
def test_missing_start_permission_or_test_mode_never_launches(startup, monkeypatch, change):
    for key, value in change.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("ERECHNUNG_MCP_URL", raising=False)
    assert not mcp_server.app_call("list_issuers", {})["ok"]
    assert not startup[2]


@pytest.mark.parametrize("frozen", [False, True])
def test_launcher_uses_own_code_and_detaches_protocol_streams(monkeypatch, frozen):
    captured = {}
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setenv("ERECHNUNG_MCP", "1")
    monkeypatch.setenv("ERECHNUNG_MCP_TOKEN", "must-not-be-inherited")
    monkeypatch.setenv("ERECHNUNG_MCP_ENDPOINT_FILE", "untrusted-command")
    monkeypatch.setenv("FLASK_DEBUG", "1")
    monkeypatch.setattr(connection.subprocess, "Popen", lambda command, **kwargs: captured.update(command=command, **kwargs))
    connection.launch_app()
    assert captured["command"] == [sys.executable, *([] if frozen else [str(Path(connection.__file__).with_name("app.py"))]), "--mcp-start"]
    assert captured["start_new_session"] is True
    assert all(captured[key] == subprocess.DEVNULL for key in ("stdin", "stdout", "stderr"))
    assert captured["env"]["ERECHNUNG_MCP"] == "1"
    assert captured["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert captured["env"]["FLASK_DEBUG"] == "0"
    assert not any(k.startswith("ERECHNUNG_MCP_") for k in captured["env"])


def test_generated_configuration_includes_start_but_test_configuration_does_not(client, monkeypatch):
    configure(client, "enable", consent="yes")
    publish_endpoint(m, "http://127.0.0.1:1")
    for test_mode in [False, True]:
        monkeypatch.setattr(m, "TEST_MODE", test_mode)
        response = configure(client, "connect", name="Test agent", issuers=["default"])
        config = json.loads(html.fromstring(response.data).get_element_by_id("mcp-configuration").text)
        env = config["mcpServers"]["erechnung"]["env"]
        assert env["ERECHNUNG_MCP"] == "1"
        if test_mode:
            assert env["ERECHNUNG_TEST_MODE"] == "1" and "ERECHNUNG_MCP_AUTOSTART" not in env
        else:
            assert env["ERECHNUNG_MCP_AUTOSTART"] == "1"


def test_readiness_is_available_without_access_and_contains_no_data(client, monkeypatch):
    monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    m.BASE.mkdir()
    publish_endpoint(m, "http://127.0.0.1:1")
    result = client.get("/agents/status")
    assert result.json == {"service": "eRechnung", "mcp_enabled": False}
    assert "Set-Cookie" not in result.headers
    assert client.get("/agents").status_code == 404
    assert not (m.BASE / "agent_access.json").exists()


def test_ambiguous_post_failure_is_never_retried(startup, monkeypatch):
    sent = []
    def fail_after_send(*args, **kwargs):
        sent.append(1)
        raise OSError("Response lost")
    monkeypatch.setattr(mcp_server, "build_opener", lambda *args: SimpleNamespace(open=fail_after_send))
    result = mcp_server.app_call("delete_customer", {"issuer": "default", "name": BUYER["name"]})
    assert not result["ok"] and sent == [1]
    assert not m.app.extensions["mcp_access"].pending


def test_instance_lock_prevents_second_window_even_after_start_timeout(tmp_path):
    script = "from pathlib import Path; from mcp_connection import app_instance; "
    script += "ctx = app_instance(Path(__import__('sys').argv[1])); "
    script += "print(ctx.__enter__()); ctx.__exit__(None, None, None)"
    with connection.app_instance(tmp_path) as acquired:
        assert acquired
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, check=True)
        assert result.stdout.strip() == "False"
    with connection.app_instance(tmp_path) as acquired:
        assert acquired


def test_manual_start_remains_available_on_platform_without_autostart(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with connection.app_instance(tmp_path) as acquired:
        assert acquired
    assert not list(tmp_path.iterdir())


def test_real_source_app_start_stays_isolated_and_requires_opt_in():
    from scripts.check_mcp_bundle import check_app_start
    # Avoid opening the developer's browser; the normal app HTTP server is real.
    check_app_start([sys.executable, str(m.RESOURCE_BASE / "app.py")], browser="/usr/bin/true")
