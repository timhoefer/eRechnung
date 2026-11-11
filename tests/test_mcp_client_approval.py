"""Real client elicitation and the private, one-shot decision transport."""
import asyncio
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from mcp import Client, types
from mcp.client.stdio import StdioServerParameters
from test_mcp_access import BUYER, call, configure, decide, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_key_rotation import configured_token, setup_form
from test_mcp_operation_permissions import policy_grant
from test_mcp_permission_editing import permissions
from werkzeug.serving import make_server

import app as m
import mcp_server


@pytest.fixture
def transport(client):
    server = make_server("127.0.0.1", 0, m.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def params(token):
        return StdioServerParameters(command=sys.executable, args=[str(m.RESOURCE_BASE / "mcp_server.py")],
            env={"ERECHNUNG_MCP_TOKEN": token, "ERECHNUNG_MCP_URL": f"http://127.0.0.1:{server.server_port}",
                 "ERECHNUNG_TEST_MODE": "1", "ERECHNUNG_MCP_AUTOSTART": "0"})
    try:
        yield params
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("action,content,status", [
    ("accept", {"confirm": True}, "completed"),
    ("accept", {"confirm": False}, "denied"),
    ("accept", {}, "denied"),
    ("decline", None, "denied"),
    ("cancel", None, "cancelled"),
])
def test_real_sdk_approval_denial_and_cancel(client, transport, action, content, status, mode):
    token = policy_grant(client, client_approvals=True, save_customer="confirm")
    before = snapshot()
    dialogs = []
    async def answer(context, params):
        dialogs.append(params)
        assert snapshot() == before  # no mutation while the dialog is visible
        assert "Example agent" in params.message and BUYER["email"] in params.message
        assert "new@example.com" in params.message
        assert "nonce" not in params.message and "fingerprint" not in params.message
        assert params.requested_schema["required"] == ["confirm"]
        assert "default" not in params.requested_schema["properties"]["confirm"]
        return types.ElicitResult(action=action, content=content)
    async def scenario():
        async with Client(transport(token), read_timeout_seconds=20, elicitation_callback=answer, mode=mode) as agent:
            tools = (await agent.list_tools()).tools
            assert not any("approve" in t.name or "permission" in t.name for t in tools)
            result = await agent.call_tool("save_customer", {"issuer": "default", "buyer": {**BUYER, "email": "new@example.com"}})
            data = result.structured_content
            assert data["status"] == status, data
            assert bool(data["ok"]) == (status == "completed")
            assert "_client_approval" not in json.dumps(data) and "nonce" not in json.dumps(data)
            queried = (await agent.call_tool("request_status", {"request_id": data["request_id"]})).structured_content
            assert queried["status"] == status and "nonce" not in json.dumps(queried)
            # A model cannot put confirmation or policy changes in tool arguments.
            forged = await agent.call_tool("save_customer", {"issuer": "default", "buyer": BUYER, "approve": True})
            assert forged.is_error
    asyncio.run(scenario())
    assert len(dialogs) == 1
    if status == "completed":
        assert m.load_customers()[0]["email"] == "new@example.com"
    else:
        assert snapshot() == before


@pytest.mark.parametrize("client_support,opted_in", [(False, True), (True, False)])
def test_unsupported_or_unselected_client_confirmation_falls_back_to_app(client, transport, client_support, opted_in):
    token = policy_grant(client, client_approvals=opted_in, delete_customer="confirm")
    before = snapshot()
    async def unexpected(context, params):
        pytest.fail("This connection must use the app fallback")
    async def scenario():
        kwargs = {"elicitation_callback": unexpected} if client_support else {}
        async with Client(transport(token), read_timeout_seconds=20, **kwargs) as agent:
            data = (await agent.call_tool("delete_customer", {"issuer": "default", "name": BUYER["name"]})).structured_content
            assert data["status"] == "approval_required", data
            if not client_support and opted_in:
                assert data["client_confirmation_error"] == "unsupported"
            assert "nonce" not in json.dumps(data) and "_client_approval" not in json.dumps(data)
            assert snapshot() == before
            assert decide(client, data["request_id"], "deny").status_code == 303
    asyncio.run(scenario())
    assert snapshot() == before


@pytest.mark.parametrize("change", ["data", "permissions", "pause", "renew", "revoke", "expire", "app_denial"])
def test_changes_during_dialog_cannot_execute_old_approval(client, transport, change):
    token = policy_grant(client, client_approvals=True, save_customer="confirm")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    expected = dict(BUYER)
    async def answer(context, params):
        request_id, = [key for key, value in access.pending.items() if value["status"] == "pending"]
        if change == "data":
            expected["email"] = "edited-in-app@example.com"
            m._write_json(m.CUSTOMERS_FILE, [expected])
        elif change == "permissions":
            assert permissions(client, identifier, permission_save_customer="allow").status_code == 200
        elif change == "pause":
            configure(client, "pause", connection=identifier)
        elif change == "renew":
            url, fields = setup_form(client, identifier)
            configured_token(client.post(url, data=fields))
        elif change == "revoke":
            configure(client, "revoke", connection=identifier, confirm="yes")
        elif change == "expire":
            access.pending[request_id]["expires"] = time.monotonic() - 1
        else:
            assert decide(client, request_id, "deny").status_code == 303
        return types.ElicitResult(action="accept", content={"confirm": True})
    async def scenario():
        async with Client(transport(token), read_timeout_seconds=20, elicitation_callback=answer) as agent:
            result = await agent.call_tool("save_customer", {"issuer": "default", "buyer": {**BUYER, "email": "must-not-apply@example.com"}})
            assert not result.structured_content["ok"], result
            assert "nonce" not in json.dumps(result.structured_content)
    asyncio.run(scenario())
    assert m.load_customers() == [expected]


def private_decision(token, payload, **headers):
    with m.app.test_client(use_cookies=False) as api:
        return api.post("/agents/client-decision", json=payload, headers={"Authorization": "Bearer " + token, **headers})


def test_private_decision_is_bound_to_connection_nonce_operation_and_consumed_once(client):
    token = policy_grant(client, client_approvals=True, delete_customer="confirm")
    other = policy_grant(client, client_approvals=True, delete_customer="confirm")
    request = call(token, "delete_customer", issuer="default", name=BUYER["name"])
    payload = {"request_id": request["request_id"], "nonce": request["_client_approval"]["nonce"], "decision": "approve"}
    before = snapshot()
    assert private_decision(other, payload).status_code == 403
    assert private_decision(token, {**payload, "nonce": "wrong"}).status_code == 403
    assert private_decision(token, {**payload, "arguments": {}}).status_code == 400
    assert private_decision(token, payload, Origin="http://localhost").status_code == 403
    assert private_decision(token, payload, Cookie="session=fake").status_code == 403
    assert snapshot() == before
    result = private_decision(token, payload)
    assert result.status_code == 200 and result.json["status"] == "completed"
    assert m.load_customers() == []
    after = snapshot()
    assert private_decision(token, payload).status_code in (403, 409)
    assert snapshot() == after


@pytest.mark.parametrize("failure", ["unsupported", "error", "timeout"])
def test_bridge_dialog_failure_never_fabricates_approval(monkeypatch, failure):
    async def failed(**kwargs):
        raise TimeoutError() if failure == "timeout" else RuntimeError("No dialog")
    context = SimpleNamespace(request_id="test", protocol_version="2025-11-25", session=SimpleNamespace(
        client_capabilities=types.ClientCapabilities(
            elicitation=None if failure == "unsupported" else types.ElicitationCapability(form=types.FormElicitationCapability())),
        elicit_form=failed))
    pending = {"ok": False, "status": "approval_required", "request_id": "test"}
    private = {"nonce": "secret-test-nonce", "connection": "Test", "review": {"title": "Delete test customer"}}
    monkeypatch.setattr(mcp_server, "app_call", lambda *args: {**pending, "_client_approval": private})
    def forbidden(*args):
        pytest.fail("No affirmative response: must not send a decision")
    monkeypatch.setattr(mcp_server, "app_request", forbidden)
    result = asyncio.run(mcp_server.call_tool(context, types.CallToolRequestParams(name="delete_customer", arguments={})))
    data = result.structured_content
    assert all(data[key] == value for key, value in pending.items())
    assert data["approval_location"] == "app"
    assert data["client_confirmation_error"] == ("dialog_failed" if failure == "error" else failure)
    assert "request_status" in data["message"]
    assert "No dialog" not in data["message"]
    assert "secret-test-nonce" not in result.model_dump_json()


@pytest.mark.parametrize("capabilities,expected", [
    (None, False), ({}, False), ({"elicitation": {}}, True),
    ({"elicitation": {"form": {}}}, True),
    ({"elicitation": {"url": {}}}, False),
    ({"elicitation": {"form": {}, "url": {}}}, True),
])
def test_form_support_respects_legacy_and_url_only_clients(capabilities, expected):
    session = SimpleNamespace(client_capabilities=(
        types.ClientCapabilities.model_validate(capabilities) if capabilities is not None else None))
    assert mcp_server.supports_confirmation_form(session) is expected


def test_unanswered_dialog_is_cancelled_without_sending_a_decision(monkeypatch):
    async def scenario():
        cancelled = asyncio.Event()
        async def unanswered(**kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        context = SimpleNamespace(request_id="test", protocol_version="2025-11-25", session=SimpleNamespace(
            client_capabilities=types.ClientCapabilities(elicitation=types.ElicitationCapability()),
            elicit_form=unanswered))
        result = await mcp_server.client_approval(context, types.CallToolRequestParams(name="save_customer"),
            {"ok": False, "status": "approval_required", "request_id": "test"},
            {"connection": "Test", "nonce": "private", "review": {"title": "Save customer"}})
        assert cancelled.is_set()
        assert result["client_confirmation_error"] == "timeout"
        assert result["status"] == "approval_required" and not result["ok"]
    monkeypatch.setattr(mcp_server, "CLIENT_CONFIRMATION_TIMEOUT", 0.01)
    def forbidden(*args):
        pytest.fail("Timeout must not turn into consent")
    monkeypatch.setattr(mcp_server, "app_request", forbidden)
    asyncio.run(scenario())


def test_app_section_is_visible_only_with_pending_requests(client):
    token = policy_grant(client, delete_customer="confirm")
    assert b'id="agent-approvals-title"' not in client.get("/agents").data
    assert b'id="agent-requests-refresh"' in client.get("/agents").data
    result = call(token, "delete_customer", issuer="default", name=BUYER["name"])
    assert b'id="agent-approvals-title"' in client.get("/agents").data
    decide(client, result["request_id"], "deny")
    assert b'id="agent-approvals-title"' not in client.get("/agents").data


@pytest.mark.parametrize("change", ["arguments", "name", "state", "expiry", "missing_response", "decline", "accept"])
def test_modern_continuation_is_bound_consumed_and_never_reexecutes_tool(monkeypatch, change):
    mcp_server._client_reviews.clear()
    pending = {"ok": False, "status": "approval_required", "request_id": "request"}
    private = {"nonce": "private-test-nonce", "connection": "Test", "review": {"title": "Delete test"}}
    params = types.CallToolRequestParams(name="delete_customer", arguments={"issuer": "default", "name": "Test"})
    context = SimpleNamespace(protocol_version="2026-07-28", session=SimpleNamespace(
        client_capabilities=types.ClientCapabilities(elicitation=types.ElicitationCapability(form=types.FormElicitationCapability()))))
    initial = asyncio.run(mcp_server.client_approval(context, params, pending, private))
    assert isinstance(initial, types.InputRequiredResult)
    assert "private-test-nonce" not in initial.model_dump_json()
    resumed = params.model_copy(update={"request_state": initial.request_state,
        "input_responses": {"approval": types.ElicitResult(action="accept", content={"confirm": True})}})
    if change == "arguments":
        resumed.arguments = {"issuer": "default", "name": "Someone else"}
    elif change == "name":
        resumed.name = "save_customer"
    elif change == "state":
        resumed.request_state = "forged"
    elif change == "expiry":
        mcp_server._client_reviews[initial.request_state]["expires"] = time.monotonic() - 1
    elif change == "missing_response":
        resumed.input_responses = None
    elif change == "decline":
        resumed.input_responses = {"approval": types.ElicitResult(action="decline")}
    sent = []
    def send(path, data):
        sent.append((path, data))
        return {"ok": data["decision"] == "approve", "status": "completed" if data["decision"] == "approve" else "denied"}
    monkeypatch.setattr(mcp_server, "app_request", send)
    def forbidden(*args):
        pytest.fail("A continuation must not execute the original tool again")
    monkeypatch.setattr(mcp_server, "app_call", forbidden)
    result = asyncio.run(mcp_server.call_tool(context, resumed))
    if change in {"accept", "decline"}:
        assert len(sent) == 1 and result.structured_content["status"] == ("completed" if change == "accept" else "denied")
        assert sent[0][1]["request_id"] == "request" and sent[0][1]["nonce"] == private["nonce"]
    else:
        assert not sent and not result.structured_content["ok"]
    count = len(sent)
    replay = asyncio.run(mcp_server.call_tool(context, resumed))
    assert not replay.structured_content["ok"] and len(sent) == count
    mcp_server._client_reviews.clear()
