"""Run a real SDK client against the stdio process and the isolated app."""
import asyncio
import json
import sys
import threading

import pytest
from flask import request
from mcp import Client
from mcp.client.stdio import StdioServerParameters
from test_mcp_access import BUYER, call, configure, decide, disable, grant
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_customer_scope import PRIVATE, scoped_grant, seed_archive
from test_mcp_key_rotation import configured_token, setup_form
from werkzeug.serving import make_server

import app as m
import mcp_server
from mcp_app import publish_endpoint
from mcp_contract import TOOLS


@pytest.mark.parametrize("entrypoint", ["mcp_server.py", "desktop.py"])
@pytest.mark.parametrize("customer_mode", ["all", "selected"])
def test_real_stdio_client_discovery_scopes_approval_and_revocation(client, entrypoint, customer_mode, monkeypatch):
    readiness = []
    def observe_start():
        if request.path == "/agents/status":
            readiness.append(True)
    monkeypatch.setitem(m.app.before_request_funcs, None, [*m.app.before_request_funcs[None], observe_start])
    credential = scoped_grant(client) if customer_mode == "selected" else grant(client)
    m._write_json(m.CUSTOMERS_FILE, [*m.load_customers(), PRIVATE])
    original_customers = m.load_customers()
    filename = seed_archive("UNDATED", BUYER, original_customers[0].get("_customer_id"))
    sidecar = (m.OUTPUT_DIR / filename).with_suffix(".json")
    archived = json.loads(sidecar.read_text())
    archived["invoice"]["issue_date"] = None
    sidecar.write_text(json.dumps(archived))
    server = make_server("127.0.0.1", 0, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    publish_endpoint(m, f"http://127.0.0.1:{server.server_port}")
    # Exercise real MCP initialization/reuse, but make any unexpected cold start
    # fail instead of launching the developer's production data from the repo.
    wrapper = """import runpy, sys, mcp_connection
def unexpected_start():
    raise OSError('The test app is already running; no real launcher is allowed')
mcp_connection.launch_app = unexpected_start
mcp_connection.autostart_enabled = lambda: True
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    params = StdioServerParameters(command=sys.executable,
        args=["-c", wrapper, str(m.RESOURCE_BASE / entrypoint), *(["--mcp"] if entrypoint == "desktop.py" else [])],
        env={"ERECHNUNG_MCP_TOKEN": credential, "ERECHNUNG_MCP_ENDPOINT_FILE": str(m.BASE / "mcp-endpoint.json"),
             "ERECHNUNG_MCP": "1", "ERECHNUNG_MCP_AUTOSTART": "1", "ERECHNUNG_TEST_MODE": "1"})

    async def scenario():
        async with Client(params, read_timeout_seconds=20) as agent:
            assert readiness, "App readiness must be checked during MCP initialization."
            tools = (await agent.list_tools()).tools
            assert {t.name for t in tools} == set(TOOLS)
            assert not any("approve" in t.name for t in tools)
            result = await agent.call_tool("list_issuers", {})
            assert result.structured_content["issuers"][0]["id"] == "default"
            customers = (await agent.call_tool("list_customers", {})).structured_content["customers"]
            archive = await agent.call_tool("list_invoices", {"issuer": "default"})
            assert not archive.is_error
            assert [row["filename"] for row in archive.structured_content["invoices"]] == [filename]
            json.dumps(archive.structured_content, allow_nan=False)
            deletion = {"issuer": "default", "name": BUYER["name"]}
            if customer_mode == "selected":
                assert len(customers) == 1 and customers[0]["name"] == BUYER["name"]
                deletion["customer_id"] = customers[0]["customer_id"]
                denied = await agent.call_tool("delete_customer", {**deletion, "name": PRIVATE["name"]})
                assert not denied.structured_content["ok"]
            pending = await agent.call_tool("delete_customer", deletion)
            data = pending.structured_content
            assert not pending.is_error and data["status"] == "approval_required"
            assert json.loads(m.CUSTOMERS_FILE.read_text()) == original_customers
            connection_id = m.app.extensions["mcp_access"].authenticate(credential, m.DATA_DIR)["id"]
            assert configure(client, "pause", connection=connection_id).status_code == 200
            refused = await agent.call_tool("list_customers", {})
            assert refused.is_error and not refused.structured_content["ok"]
            assert configure(client, "resume", connection=connection_id).status_code == 200
            assert (await agent.call_tool("list_customers", {})).structured_content["ok"]
            assert not (await agent.call_tool("request_status", {"request_id": data["request_id"]})).structured_content["ok"]
            pending = await agent.call_tool("delete_customer", deletion)
            assert pending.structured_content["request_id"] != data["request_id"]
            data = pending.structured_content
            assert decide(client, data["request_id"]).status_code == 303
            status = await agent.call_tool("request_status", {"request_id": data["request_id"]})
            assert status.structured_content["status"] == "completed"
            assert m.load_customers() == [PRIVATE]
            if customer_mode == "selected":
                assert PRIVATE["name"] not in json.dumps(status.structured_content)
            disable(client)
            refused = await agent.call_tool("list_customers", {})
            assert refused.is_error and not refused.structured_content["ok"]
    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_real_stdio_clients_must_replace_renewed_key_and_keep_customer_scope(client):
    credential = scoped_grant(client)
    m._write_json(m.CUSTOMERS_FILE, [*m.load_customers(), PRIVATE])
    identifier = m.app.extensions["mcp_access"].authenticate(credential, m.DATA_DIR)["id"]
    server = make_server("127.0.0.1", 0, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    params = StdioServerParameters(command=sys.executable, args=[str(m.RESOURCE_BASE / "mcp_server.py")],
        env={"ERECHNUNG_MCP_TOKEN": credential, "ERECHNUNG_MCP_URL": f"http://127.0.0.1:{server.server_port}",
             "ERECHNUNG_TEST_MODE": "1", "ERECHNUNG_MCP_AUTOSTART": "0"})

    async def scenario():
        async with Client(params, read_timeout_seconds=20) as old:
            customers = (await old.call_tool("list_customers", {})).structured_content["customers"]
            target, fields = setup_form(client, identifier)
            token = configured_token(client.post(target, data=fields))
            rejected = await old.call_tool("list_customers", {})
            assert rejected.is_error and not rejected.structured_content["ok"]
            updated = params.model_copy(update={"env": {**params.env, "ERECHNUNG_MCP_TOKEN": token}})
            async with Client(updated, read_timeout_seconds=20) as new:
                result = (await new.call_tool("list_customers", {})).structured_content
                assert result["customers"] == customers and len(customers) == 1
                refused = await new.call_tool("delete_customer", {"issuer": "default", "name": PRIVATE["name"],
                                                                 "customer_id": customers[0]["customer_id"]})
                assert not refused.structured_content["ok"]
                pending = await new.call_tool("delete_customer", {"issuer": "default", "name": BUYER["name"],
                                                                 "customer_id": customers[0]["customer_id"]})
                assert pending.structured_content["status"] == "approval_required"
                assert len(m.load_customers()) == 2
    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("url", ["https://example.org", "http://example.org", "http://localhost:5000",
                                 "http://127.0.0.1:5000@evil.example", "http://127.0.0.1:5000/other",
                                 "file:///tmp/invoices", "http://127.0.0.1:5000?redirect=1"])
def test_bridge_rejects_nonlocal_or_ambiguous_endpoints(monkeypatch, url):
    monkeypatch.delenv("ERECHNUNG_MCP_ENDPOINT_FILE", raising=False)
    monkeypatch.setenv("ERECHNUNG_MCP_URL", url)
    monkeypatch.setenv("ERECHNUNG_MCP_TOKEN", "secret")
    def forbidden(*args, **kwargs):
        pytest.fail("Untrusted URL must not reach the network")
    monkeypatch.setattr(mcp_server, "build_opener", forbidden)
    assert not mcp_server.app_call("list_customers", {})["ok"]


def test_app_origin_cookie_and_missing_credential_are_rejected(client):
    credential = grant(client)
    for extra in [{"Origin": "http://127.0.0.1:5001"}, {"Cookie": "session=fake"}]:
        with m.app.test_client(use_cookies=False) as api:
            result = api.post("/agents/call", json={"tool": "list_customers", "arguments": {}},
                              headers={"Authorization": "Bearer " + credential, **extra})
            assert result.status_code == 403
    assert client.post("/agents/call", json={}).status_code in (401, 403)


def test_bridge_only_loads_endpoint_file_and_protocol_code(tmp_path, monkeypatch):
    # Even a source desktop launch in bridge mode must not initialize app storage.
    async def discover():
        params = StdioServerParameters(command=sys.executable, args=[str(m.RESOURCE_BASE / "desktop.py"), "--mcp"],
                                      env={"ERECHNUNG_TEST_MODE": "1", "TMPDIR": str(tmp_path)})
        async with Client(params, read_timeout_seconds=20) as agent:
            assert (await agent.list_tools()).tools
    asyncio.run(discover())
    assert not list(tmp_path.glob("erechnung-*"))


@pytest.mark.parametrize("path", ["../secret.pdf", "/tmp/secret.pdf", "..\\secret.pdf"])
def test_file_tools_do_not_accept_paths(client, path):
    credential = grant(client)
    for tool in ["get_invoice", "delete_invoice"]:
        assert not call(credential, tool, issuer="default", filename=path)["ok"]


def test_no_redirect_and_proxy_use(monkeypatch):
    # The bridge must not forward a bearer credential to a redirect target.
    assert mcp_server.NoRedirect().redirect_request(None, None, 302, "", {}, "http://evil.example") is None
    monkeypatch.delenv("ERECHNUNG_MCP_ENDPOINT_FILE", raising=False)
    monkeypatch.setenv("ERECHNUNG_MCP_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("ERECHNUNG_MCP_TOKEN", "test")
    recorded = []
    def opener(*handlers):
        recorded.extend(handlers)
        raise OSError()
    monkeypatch.setattr(mcp_server, "build_opener", opener)
    assert not mcp_server.app_call("list_issuers", {})["ok"]
    assert recorded[0].proxies == {}


def test_permission_settings_live_outside_invoice_folder(client):
    grant(client)
    assert (m.BASE / "agent_access.json").exists()
    assert not (m.DATA_DIR / "agent_access.json").exists()


def test_configuration_does_not_include_process_environment_secrets(client, monkeypatch):
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-appear")
    grant(client)
    assert "must-not-appear" not in client.get("/agents").text
