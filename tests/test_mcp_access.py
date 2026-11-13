"""Exercise real opt-in, scoped credentials and app-only approvals with fictional data."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from confirmation_helpers import BUYER, OTHER, SELLER, add_other, snapshot
from confirmation_helpers import client as client
from lxml import html

import app as m
from mcp_access import Access, AccessError


@pytest.fixture(autouse=True)
def fresh_access(monkeypatch):
    monkeypatch.setitem(m.app.config, "MCP_FEATURE", True)
    monkeypatch.delitem(m.app.config, "MCP_ENDPOINT_FILE", raising=False)
    m.app.extensions["mcp_access"].pending.clear()


def csrf(client):
    page = html.fromstring(client.get("/agents").data)
    return page.xpath('//input[@name="csrf"]/@value')[0]


def configure(client, action, **fields):
    return client.post("/agents/settings", data={"csrf": csrf(client), "action": action, **fields})


def disable(client):
    review = configure(client, "disable")
    form, = html.fromstring(review.data).xpath('//form[input[@name="action" and @value="disable"]]')
    return client.post(form.action, data=dict(form.form_values()))


def grant(client, *, issuers=None, writable=True, name="Example agent"):
    assert configure(client, "enable", consent="yes").status_code == 200
    response = configure(client, "connect", name=name, issuers=issuers or ["default"], write="yes" if writable else "", customer_mode="all")
    assert response.status_code == 200
    config = json.loads(html.fromstring(response.data).get_element_by_id("mcp-configuration").text)
    return config["mcpServers"]["erechnung"]["env"]["ERECHNUNG_MCP_TOKEN"]


def call(token, operation, **arguments):
    with m.app.test_client(use_cookies=False) as api:
        response = api.post("/agents/call", json={"tool": operation, "arguments": arguments},
                            headers={"Authorization": "Bearer " + token})
    assert response.is_json, (response.status_code, response.text[:100])
    return response.json


def decide(client, identifier, decision="approve"):
    page = html.fromstring(client.get("/agents/requests/" + identifier).data)
    return client.post("/agents/requests/" + identifier, data={
        "csrf": page.xpath('//input[@name="csrf"]/@value')[0], "decision": decision,
    })


def invoice_args():
    return {"issuer": "default", "seller_revision": m.seller_revision(m.load_seller()),
            "invoice": {"number": "TEST-1", "issue_date": date.today().isoformat(),
                        "language": "de", "currency": "EUR", "profile": "en16931", "tax_treatment": "de_19"},
            "buyer": BUYER, "items": [{"description": "Design", "quantity": "2", "unit": "DAY", "unit_price": "100"}]}


def test_flag_and_opt_in_are_required(client, monkeypatch):
    monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    assert client.get("/agents").status_code == 404
    assert client.post("/agents/call", json={}).status_code == 404
    assert b"/agents" not in client.get("/settings/panel").data
    monkeypatch.setitem(m.app.config, "MCP_FEATURE", True)
    before = snapshot()
    assert configure(client, "enable").status_code == 400
    assert not call("x" * 43, "list_customers")["ok"]
    assert snapshot() == before
    assert not (m.BASE / "agent_access.json").exists()


def test_opt_in_form_csrf_and_bearer_cannot_manage_access(client):
    token = csrf(client)
    assert client.post("/agents/settings", data={"action": "enable", "consent": "yes"}).status_code == 403
    assert client.post("/agents/settings", data={"csrf": token, "action": "enable", "consent": "yes"},
                       headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403
    credential = grant(client)
    assert client.get("/agents", headers={"Authorization": "Bearer " + credential}).status_code == 403
    assert client.post("/agents/settings", data={"csrf": token, "action": "enable", "consent": "yes"},
                       headers={"Authorization": "Bearer " + credential}).status_code == 403


@pytest.mark.parametrize("language", ["de", "en"])
def test_opt_in_switch_submits_consent_and_revokes_grants(client, language):
    client.set_cookie("lang", language)
    access = m.app.extensions["mcp_access"]
    before = snapshot()

    def switch_form(response, enabled):
        assert response.status_code == 200
        page = html.fromstring(response.data)
        switch, = page.xpath('//button[@role="switch" and @aria-labelledby="agent-access-label"]')
        assert switch.get("aria-checked") == ("true" if enabled else "false")
        for identifier in (switch.get("aria-labelledby") + " " + switch.get("aria-describedby")).split():
            assert page.get_element_by_id(identifier).text_content().strip()
        return switch.xpath('ancestor::form')[0]

    off = switch_form(client.get("/agents"), False)
    assert not (m.BASE / "agent_access.json").exists()
    # Submit the actual UI form, without adding consent or CSRF in the test.
    enable_fields = dict(off.form_values())
    switch_form(client.post(off.action, data=enable_fields), True)
    assert access.load() == {"enabled": True, "connections": {}}
    # Retrying a submission must set the requested state, never flip it back.
    switch_form(client.post(off.action, data=enable_fields), True)

    credential = grant(client)
    pending = call(credential, "delete_customer", issuer="default", name=BUYER["name"])
    assert pending["status"] == "approval_required"
    on = switch_form(client.get("/agents"), True)
    disable_fields = dict(on.form_values())
    grants_before = access.load()
    review = client.post(on.action, data=disable_fields)
    assert review.status_code == 200
    page = html.fromstring(review.data)
    assert "Example agent" in page.text_content()
    assert access.load() == grants_before
    assert call(credential, "request_status", request_id=pending["request_id"])["status"] == "pending"
    cancel, = page.xpath('//a/@href')
    switch_form(client.get(cancel), True)
    assert access.load() == grants_before
    confirm_form, = page.xpath('//form')
    disable_fields = dict(confirm_form.form_values())
    switch_form(client.post(confirm_form.action, data=disable_fields), False)
    switch_form(client.post(confirm_form.action, data=disable_fields), False)
    assert access.load() == {"enabled": False, "connections": {}}
    assert not access.pending
    assert not call(credential, "list_customers")["ok"]

    off = switch_form(client.get("/agents"), False)
    switch_form(client.post(off.action, data=dict(off.form_values())), True)
    assert access.load() == {"enabled": True, "connections": {}}
    assert not call(credential, "list_customers")["ok"]
    assert client.post("/agents/requests/" + pending["request_id"],
                       data={"csrf": csrf(client), "decision": "approve"}).status_code == 403
    assert snapshot() == before


@pytest.mark.parametrize("change", ["new_connection", "paused", "reenabled"])
def test_global_disable_rechecks_connections_before_confirming(client, change):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    review = configure(client, "disable")
    form, = html.fromstring(review.data).xpath('//form')
    fields = dict(form.form_values())
    if change == "new_connection":
        grant(client, name="Second agent")
    elif change == "paused":
        configure(client, "pause", connection=identifier)
    else:
        assert disable(client).status_code == 200
        grant(client, name="New grant after re-enabling")
    before = access.load()
    response = client.post(form.action, data=fields)
    assert response.status_code == 409
    assert access.load() == before
    page = html.fromstring(response.data)
    assert all(c["name"] in page.text_content() for c in before["connections"].values())
    updated_form, = page.xpath('//form')
    assert client.post(updated_form.action, data=dict(updated_form.form_values())).status_code == 200
    assert access.load() == {"enabled": False, "connections": {}}


def test_global_disable_cannot_skip_review_with_confirmation_flag(client):
    grant(client)
    access = m.app.extensions["mcp_access"]
    before = access.load()
    assert configure(client, "disable", confirm="yes").status_code == 409
    assert configure(client, "disable", confirm="yes", revision="stale").status_code == 409
    assert access.load() == before


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("legacy", [False, True])
def test_connection_switch_preserves_grant_but_discards_old_requests(client, language, legacy):
    client.set_cookie("lang", language)
    first, second = grant(client), grant(client, name="Second agent")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(first, m.DATA_DIR)["id"]
    if legacy:
        state = access.load()
        del state["connections"][identifier]["active"]
        access.save(state)
    original = access.authenticate(first, m.DATA_DIR).copy()
    first_request = call(first, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
    second_request = call(second, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
    before = snapshot()

    def form_for(response, active):
        page = html.fromstring(response.data)
        form, = page.xpath('//form[input[@name="connection" and @value=$id]'
                            ' and .//button[@role="switch"]]', id=identifier)
        switch, = form.xpath('.//button[@role="switch"]')
        assert switch.get("aria-checked") == str(active).lower()
        assert original["name"] in switch.get("aria-label")
        assert page.get_element_by_id(switch.get("aria-describedby")).text_content().strip()
        return form

    on = form_for(client.get("/agents"), True)
    fields = dict(on.form_values())
    off = form_for(client.post(on.action, data=fields), False)
    form_for(client.post(on.action, data=fields), False)  # Retry must not reactivate.
    assert access.load()["connections"][identifier] == {**original, "active": False}
    reloaded = Access(access.path, access.write)
    with pytest.raises(AccessError):
        reloaded.authenticate(first, m.DATA_DIR)
    assert not call(first, "list_customers")["ok"]
    assert not call(first, "save_customer", issuer="default", buyer={**BUYER, "name": "New customer"})["ok"]
    assert first_request not in access.pending
    assert call(second, "request_status", request_id=second_request)["status"] == "pending"
    assert call(second, "list_customers")["ok"]
    assert client.post("/agents/requests/" + first_request,
                       data={"csrf": csrf(client), "decision": "approve"}).status_code == 403

    fields = dict(off.form_values())
    form_for(client.post(off.action, data=fields), True)
    form_for(client.post(off.action, data=fields), True)
    assert access.authenticate(first, m.DATA_DIR) == {**original, "active": True}
    assert reloaded.authenticate(first, m.DATA_DIR) == {**original, "active": True}
    assert call(first, "list_customers")["ok"]
    assert not call(first, "get_issuer", issuer=OTHER)["ok"]
    assert not call(first, "request_status", request_id=first_request)["ok"]
    assert client.post("/agents/requests/" + first_request,
                       data={"csrf": csrf(client), "decision": "approve"}).status_code == 403
    new_request = call(first, "delete_customer", issuer="default", name=BUYER["name"])
    assert new_request["status"] == "approval_required" and new_request["request_id"] != first_request
    assert snapshot() == before


@pytest.mark.parametrize("language", ["de", "en"])
def test_connection_deletion_requires_confirmation_and_cannot_be_resumed(client, language):
    client.set_cookie("lang", language)
    credential, other = grant(client), grant(client, name="Other agent")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    pending = call(credential, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
    before = snapshot()
    state = access.load()
    page = html.fromstring(client.get("/agents").data)
    delete_form, = page.xpath('//form[input[@name="action" and @value="revoke"]'
                              ' and input[@name="connection" and @value=$id]]', id=identifier)
    review = client.post(delete_form.action, data=dict(delete_form.form_values()))
    assert review.status_code == 200
    assert access.load() == state
    assert call(credential, "request_status", request_id=pending)["status"] == "pending"
    confirmation = html.fromstring(review.data)
    assert state["connections"][identifier]["name"] in confirmation.text_content()
    cancel, = confirmation.xpath('//a/@href')
    assert client.get(cancel).status_code == 200
    assert access.load() == state
    final_form, = confirmation.xpath('//form')
    assert client.post(final_form.action, data=dict(final_form.form_values())).status_code == 200
    assert identifier not in access.load()["connections"] and pending not in access.pending
    assert not call(credential, "list_customers")["ok"]
    assert call(other, "list_customers")["ok"]
    assert configure(client, "resume", connection=identifier).status_code == 403
    assert configure(client, "pause", connection=identifier).status_code == 403
    assert client.post("/agents/requests/" + pending,
                       data={"csrf": csrf(client), "decision": "approve"}).status_code == 403
    assert snapshot() == before


def test_resume_preserves_read_only_scope_and_cannot_restore_global_revocation(client, monkeypatch, tmp_path):
    credential = grant(client, writable=False)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    assert configure(client, "pause", connection=identifier).status_code == 200
    assert configure(client, "resume", connection=identifier).status_code == 200
    assert not call(credential, "delete_customer", issuer="default", name=BUYER["name"])["ok"]
    with monkeypatch.context() as changed:
        changed.setattr(m, "DATA_DIR", tmp_path / "another")
        m.DATA_DIR.mkdir()
        assert configure(client, "pause", connection=identifier).status_code == 200
        assert configure(client, "resume", connection=identifier).status_code == 200
        assert not call(credential, "list_customers")["ok"]
    assert configure(client, "pause", connection=identifier).status_code == 200
    assert disable(client).status_code == 200
    assert configure(client, "resume", connection=identifier).status_code == 403
    assert configure(client, "enable", consent="yes").status_code == 200
    assert configure(client, "resume", connection=identifier).status_code == 403
    assert not call(credential, "list_customers")["ok"]


@pytest.mark.parametrize("action", ["pause", "resume", "revoke", "disable"])
def test_connection_controls_require_ui_session_and_reject_bearer(client, action):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    state = access.load()
    fields = {"action": action, "connection": identifier, "confirm": "yes"}
    assert client.post("/agents/settings", data=fields).status_code == 403
    fields["csrf"] = csrf(client)
    for headers in [{"Origin": "https://example.org"}, {"Authorization": "Bearer " + credential}]:
        assert client.post("/agents/settings", data=fields, headers=headers).status_code == 403
    assert not call(credential, action, connection=identifier)["ok"]
    assert access.load() == state


def test_browser_forms_preserve_same_origin_and_reject_opaque_origins(client):
    page = client.get("/agents")
    # no-referrer would make real browser form POSTs carry Origin: null.
    assert page.headers["Referrer-Policy"] == "same-origin"
    fields = {"csrf": csrf(client), "action": "enable", "consent": "yes"}
    assert client.post("/agents/settings", data=fields, headers={"Origin": "null"}).status_code == 403
    assert client.post("/agents/settings", data=fields, headers={"Origin": "http://localhost"}).status_code == 200


@pytest.mark.parametrize("target", ["customers", "archive"])
def test_linked_data_cannot_escape_the_granted_folder(client, tmp_path, target):
    token = grant(client)
    external = tmp_path / "outside.json"
    external.write_text(json.dumps([{**BUYER, "name": "Private outside customer"}]))
    if target == "customers":
        m.CUSTOMERS_FILE.unlink()
        m.CUSTOMERS_FILE.symlink_to(external)
        result = call(token, "list_customers")
    else:
        (m.OUTPUT_DIR / "Rechnung_OUTSIDE.json").symlink_to(external)
        result = call(token, "list_invoices", issuer="default")
    assert not result["ok"]
    assert "Private outside customer" not in json.dumps(result)


def test_credentials_are_private_and_issuer_scope_is_enforced(client):
    add_other()
    token = grant(client)
    assert token not in (m.BASE / "agent_access.json").read_text()
    assert (m.BASE / "agent_access.json").stat().st_mode & 0o777 == 0o600
    page = client.get("/agents")
    assert token not in page.text and page.headers["Cache-Control"] == "no-store"
    assert [p["id"] for p in call(token, "list_issuers")["issuers"]] == ["default"]
    for operation in ["get_issuer", "list_invoices", "next_number", "deactivate_issuer", "restore_issuer"]:
        assert not call(token, operation, issuer=OTHER)["ok"]
    assert call(token, "get_issuer", issuer="default")["seller"]["name"] == SELLER["name"]
    assert call(token, "list_customers")["customers"][0]["name"] == BUYER["name"]


@pytest.mark.parametrize("operation", ["delete_customer", "save_customer", "save_issuer", "create_invoice"])
def test_read_only_grants_cannot_request_writes(client, operation):
    token = grant(client, writable=False)
    arguments = {
        "delete_customer": {"issuer": "default", "name": BUYER["name"]},
        "save_customer": {"issuer": "default", "buyer": BUYER},
        "save_issuer": {"issuer": "default", "seller_revision": m.seller_revision(m.load_seller()), "changes": {"city": "Hamburg"}},
        "create_invoice": invoice_args(),
    }[operation]
    before = snapshot()
    assert not call(token, operation, **arguments)["ok"]
    assert not m.app.extensions["mcp_access"].pending
    assert snapshot() == before


@pytest.mark.parametrize("operation", ["delete_customer", "save_customer", "save_customer_items", "save_issuer", "delete_invoice", "deactivate_issuer"])
def test_destructive_changes_wait_for_app_approval(client, operation):
    add_other()
    if operation == "delete_invoice":
        for suffix in ["pdf", "xml", "json", "csv"]:
            (m.OUTPUT_DIR / ("Rechnung_TEST." + suffix)).write_text("original")
    if operation == "save_customer_items":
        m.CUSTOMERS_FILE.write_text(json.dumps([{**BUYER, "items": [{"description": "Old item"}]}]))
    token = grant(client)
    arguments = {
        "delete_customer": {"issuer": "default", "name": BUYER["name"]},
        "save_customer": {"issuer": "default", "buyer": {**BUYER, "city": "Hamburg"}},
        "save_customer_items": {"issuer": "default", "buyer": BUYER, "items": invoice_args()["items"]},
        "save_issuer": {"issuer": "default", "seller_revision": m.seller_revision(m.load_seller()), "changes": {"city": "Hamburg"}},
        "delete_invoice": {"issuer": "default", "filename": "Rechnung_TEST.pdf"},
        "deactivate_issuer": {"issuer": "default"},
    }[operation]
    before = snapshot()
    pending = call(token, operation, **arguments)
    assert pending["status"] == "approval_required", pending
    assert "fingerprint" not in json.dumps(pending) and "token" not in json.dumps(pending)
    review = client.get("/agents/requests/" + pending["request_id"])
    assert SELLER["name"] in review.text and "Rechnungsaussteller" in review.text
    assert snapshot() == before
    assert call(token, operation, **arguments)["request_id"] == pending["request_id"]
    assert not call(token, operation, **arguments, confirmed=True)["ok"]
    assert not call(token, "approve", request_id=pending["request_id"])["ok"]
    assert decide(client, pending["request_id"]).status_code == 303
    assert call(token, "request_status", request_id=pending["request_id"])["status"] == "completed"
    assert snapshot() != before
    assert client.post("/agents/requests/" + pending["request_id"],
                       data={"csrf": csrf(client), "decision": "approve"}).status_code == 409


@pytest.mark.parametrize("cause", ["deny", "expire", "revoke", "disable", "directory", "restart"])
def test_cancelled_or_revoked_approvals_cannot_execute(client, monkeypatch, tmp_path, cause):
    token = grant(client)
    pending = call(token, "delete_customer", issuer="default", name=BUYER["name"])
    before = snapshot()
    access = m.app.extensions["mcp_access"]
    identifier = pending["request_id"]
    if cause == "deny":
        assert decide(client, identifier, "deny").status_code == 303
    elif cause == "expire":
        access.pending[identifier]["expires"] = time.monotonic() - 1
    elif cause == "revoke":
        configure(client, "revoke", connection=access.pending[identifier]["connection"]["id"], confirm="yes")
    elif cause == "disable":
        disable(client)
        configure(client, "enable", consent="yes")
        assert not call(token, "list_customers")["ok"]
    elif cause == "directory":
        monkeypatch.setattr(m, "DATA_DIR", tmp_path / "another")
        m.DATA_DIR.mkdir()
    else:
        access.pending.clear()
    response = client.post("/agents/requests/" + identifier, data={"csrf": csrf(client), "decision": "approve"})
    assert response.status_code in (403, 409)
    if cause != "directory":
        assert snapshot() == before
    assert json.loads(m.CUSTOMERS_FILE.read_text())[0] == BUYER


def test_changed_data_requires_new_review_and_does_not_execute(client):
    token = grant(client)
    arguments = {"issuer": "default", "buyer": {**BUYER, "city": "Hamburg"}}
    pending = call(token, "save_customer", **arguments)
    m.CUSTOMERS_FILE.write_text(json.dumps([{**BUYER, "city": "Munich"}]))
    before = snapshot()
    assert decide(client, pending["request_id"]).status_code == 303
    result = call(token, "request_status", request_id=pending["request_id"])
    assert result["status"] == "failed"
    replacement = result["result"]
    assert replacement["status"] == "approval_required"
    assert replacement["request_id"] != pending["request_id"]
    assert snapshot() == before
    assert decide(client, replacement["request_id"]).status_code == 303
    assert json.loads(m.CUSTOMERS_FILE.read_text())[0]["city"] == "Hamburg"


def test_connections_cannot_read_each_others_requests(client):
    first, second = grant(client), grant(client, name="Second agent")
    request_id = call(first, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
    assert not call(second, "request_status", request_id=request_id)["ok"]
    page = client.get("/agents/requests/" + request_id)
    token = html.fromstring(page.data).xpath('//input[@name="csrf"]/@value')[0]
    assert client.post("/agents/requests/" + request_id, data={"csrf": token, "decision": "approve"},
                       headers={"Authorization": "Bearer " + first}).status_code == 403


def test_parallel_retry_creates_one_pending_request(client):
    token = grant(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(token, "delete_customer", issuer="default", name=BUYER["name"]), range(2)))
    assert results[0]["request_id"] == results[1]["request_id"]
    assert len(m.app.extensions["mcp_access"].pending) == 1


def test_invoice_check_preview_and_explicit_finalization(client):
    from zugferd import extract_xml_from_pdf
    token = grant(client)
    arguments = invoice_args()
    before = snapshot()
    checked = call(token, "check_invoice", **arguments)
    assert checked["ok"], checked
    preview = call(token, "preview_invoice", **arguments)
    assert preview["ok"] and preview["base64"]
    pending = call(token, "create_invoice", **arguments)
    assert pending["status"] == "approval_required", pending
    assert snapshot() == before
    assert decide(client, pending["request_id"]).status_code == 303
    result = call(token, "request_status", request_id=pending["request_id"])
    assert result["status"] == "completed", result
    pdf = m.OUTPUT_DIR / result["result"]["filename"]
    xml = extract_xml_from_pdf(pdf.read_bytes())
    assert xml and m.validate_xml_bytes(xml)[0] and m.validate_schematron(xml)["ok"]
    assert len(call(token, "list_invoices", issuer="default")["invoices"]) == 1
    assert call(token, "get_invoice", issuer="default", filename=pdf.name)["invoice"]["items"][0]["quantity"] == "2"


@pytest.mark.parametrize("bad", ["١٢", "1.٢", "１２", "1e6", "NaN", "-1"])
def test_bad_amounts_do_not_reach_render_or_confirmation(client, monkeypatch, bad):
    token = grant(client)
    def unexpected(*args, **kwargs):
        pytest.fail("Malformed data must not reach rendering")
    monkeypatch.setattr(m, "_assemble", unexpected)
    arguments = invoice_args()
    arguments["items"][0]["quantity"] = bad
    before = snapshot()
    assert not call(token, "create_invoice", **arguments)["ok"]
    assert snapshot() == before
    assert not m.app.extensions["mcp_access"].pending


def test_request_text_is_escaped_in_approval_page(client):
    token = grant(client)
    request_id = call(token, "save_customer", issuer="default", buyer={**BUYER, "city": "<script>alert(1)</script>"})["request_id"]
    page = html.fromstring(client.get("/agents/requests/" + request_id).data)
    assert not page.xpath('//script[contains(text(), "alert(1)")]')
    assert "<script>alert(1)</script>" in page.text_content()


@pytest.mark.parametrize("document_type", ["381", "384"])
def test_retired_issuer_corrections_use_existing_identity(client, document_type):
    token = grant(client)
    arguments = invoice_args()
    original = call(token, "create_invoice", **arguments)
    assert decide(client, original["request_id"]).status_code == 303
    filename = call(token, "request_status", request_id=original["request_id"])["result"]["filename"]
    add_other()
    retired = call(token, "deactivate_issuer", issuer="default")
    assert decide(client, retired["request_id"]).status_code == 303
    assert not call(token, "create_invoice", **arguments)["ok"]
    arguments["seller_revision"] = call(token, "get_issuer", issuer="default")["revision"]
    arguments["correction_source"] = filename
    arguments["invoice"].update(number="TEST-2", doc_type=document_type)
    pending = call(token, "create_invoice", **arguments)
    assert pending["status"] == "approval_required", pending
    assert decide(client, pending["request_id"]).status_code == 303
    result = call(token, "request_status", request_id=pending["request_id"])
    assert result["status"] == "completed", result
    saved = json.loads((m.OUTPUT_DIR / "Rechnung_TEST-2.json").read_text())
    assert saved["issuer_id"] == "default"
    assert saved["invoice"]["ref_number"] == "TEST-1"
    assert call(token, "restore_issuer", issuer="default")["ok"]
    assert not m.load_seller().get("_deleted")


@pytest.mark.parametrize("change", [
    {"discount": "10"}, {"discount": "0.001", "discount_type": "abs"},
    {"discount": "201", "discount_type": "abs"}, {"prepaid": "239"}, {"prepaid": "0.001"},
    {"doc_type": "381"}, {"issue_date": ""}, {"service_start": "2026-11-01"},
])
def test_ambiguous_or_clipped_values_are_rejected_before_approval(client, change):
    token = grant(client)
    arguments = invoice_args()
    arguments["invoice"].update(change)
    before = snapshot()
    result = call(token, "create_invoice", **arguments)
    assert not result["ok"] and result.get("status") != "approval_required", result
    assert snapshot() == before


def test_partial_issuer_edit_preserves_hidden_tax_number(client):
    m.SELLER_FILE.write_text(json.dumps({**SELLER, "show_tax_number": False}))
    token = grant(client)
    pending = call(token, "save_issuer", issuer="default", seller_revision=m.seller_revision(m.load_seller()), changes={"city": "Hamburg"})
    assert decide(client, pending["request_id"]).status_code == 303
    assert m.load_seller()["city"] == "Hamburg"
    assert m.load_seller()["show_tax_number"] is False


def test_pending_requests_are_bounded_and_expire(client, monkeypatch):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    monkeypatch.setattr(access, "limit", 2)
    for city in ["Hamburg", "Munich"]:
        assert call(token, "save_customer", issuer="default", buyer={**BUYER, "city": city})["status"] == "approval_required"
    assert not call(token, "save_customer", issuer="default", buyer={**BUYER, "city": "Paris"})["ok"]
    assert len(access.pending) == 2


def test_corrupt_grants_fail_closed(client):
    token = grant(client)
    (m.BASE / "agent_access.json").write_text("corrupted")
    assert not call(token, "list_customers")["ok"]


def test_new_issuers_are_not_automatically_granted(client):
    token = grant(client)
    add_other()
    assert not call(token, "get_issuer", issuer=OTHER)["ok"]


def test_tampered_approval_fields_cannot_change_original_request(client):
    token = grant(client)
    pending = call(token, "save_customer", issuer="default", buyer={**BUYER, "city": "Hamburg"})
    response = client.post("/agents/requests/" + pending["request_id"], data={
        "csrf": csrf(client), "decision": "approve", "buyer_city": "Paris", "issuer": OTHER,
    })
    assert response.status_code == 303
    assert json.loads(m.CUSTOMERS_FILE.read_text())[0]["city"] == "Hamburg"


@pytest.mark.parametrize("language", ["de", "en"])
def test_settings_opt_in_preserves_approval_and_updates_disclaimer(client, language):
    client.set_cookie("lang", language)
    access = m.app.extensions["mcp_access"]
    headers = {"X-Requested-With": "fetch"}
    local = m.translate(language)["disclaimer_local"]
    notice = m.translate(language)["disclaimer_agent"]

    def controls(response):
        page = html.fromstring(response)
        form, = page.xpath('//form[contains(@class,"agent-access-form")]')
        return form, dict(form.form_values())

    before = snapshot()
    assert local in html.fromstring(client.get("/").data).get_element_by_id("disclaimer-text").text
    form, fields = controls(client.get("/settings/panel").data)
    assert fields["consent"] == "yes" and fields["return_to"] == "settings"
    enabled = client.post(form.action, data=fields, headers=headers)
    assert enabled.status_code == 200
    assert notice in enabled.json["disclaimer"] and local not in enabled.json["disclaimer"]
    assert access.load() == {"enabled": True, "connections": {}}
    assert notice in html.fromstring(client.get("/").data).get_element_by_id("disclaimer-text").text
    assert b'agent_access.js' in client.get("/validate").data

    credential = grant(client)
    pending = call(credential, "delete_customer", issuer="default", name=BUYER["name"])
    form, fields = controls(client.get("/settings/panel").data)
    review = client.post(form.action, data=fields, headers=headers)
    assert review.status_code == 200 and "confirmation" in review.json
    assert access.load()["enabled"]
    assert call(credential, "request_status", request_id=pending["request_id"])["status"] == "pending"
    confirmation = html.fromstring(review.json["confirmation"])
    assert confirmation.xpath('//button[@data-agent-cancel and @type="button"]')
    confirm, confirm_fields = controls(review.json["confirmation"])
    # Another tab changes the connection after the warning was shown.
    configure(client, "connect", name="Second connection", issuers=["default"], customer_mode="all")
    stale = client.post(confirm.action, data=confirm_fields, headers=headers)
    assert stale.status_code == 409 and "Second connection" in stale.json["confirmation"]
    assert access.load()["enabled"] and len(access.load()["connections"]) == 2
    confirm, confirm_fields = controls(stale.json["confirmation"])
    disabled = client.post(confirm.action, data=confirm_fields, headers=headers)
    assert disabled.status_code == 200
    assert local in disabled.json["disclaimer"] and notice not in disabled.json["disclaimer"]
    assert access.load() == {"enabled": False, "connections": {}}
    assert not access.pending and not call(credential, "list_customers")["ok"]
    assert snapshot() == before


def test_settings_opt_in_keeps_csrf_origin_and_bearer_guards(client):
    page = html.fromstring(client.get("/settings/panel").data)
    form, = page.xpath('//form[contains(@class,"agent-access-form")]')
    fields = dict(form.form_values())
    headers = {"X-Requested-With": "fetch"}
    for changes, extra_headers, status in [
        ({"csrf": ""}, {}, 403), ({"consent": ""}, {}, 400),
        ({}, {"Origin": "https://example.com"}, 403),
        ({}, {"Authorization": "Bearer untrusted"}, 403),
    ]:
        assert client.post(form.action, data={**fields, **changes}, headers={**headers, **extra_headers}).status_code == status
        assert not m.app.extensions["mcp_access"].load()["enabled"]
    assert client.post(form.action, data=fields).status_code == 302  # no-JS full-page fallback
    assert client.get("/validate").status_code == 200


def test_new_connection_dialog_has_no_implicit_grant_and_groups_actions(client):
    add_other()
    credential = grant(client)
    before = m.app.extensions["mcp_access"].load()
    page = html.fromstring(client.get("/agents").data)
    trigger = page.get_element_by_id("agent-connection-add")
    assert trigger.get("type") == "button" and trigger.get("aria-haspopup") == "dialog"
    dialog = page.get_element_by_id(trigger.get("aria-controls"))
    assert dialog.tag == "dialog" and "open" not in dialog.attrib
    form, = dialog.xpath('.//form')
    values = dict(form.form_values())
    assert values.get("customer_mode") == "selected" and "customers" not in values
    assert "issuers" not in values and "write" not in values
    assert len(form.xpath('.//input[@name="issuers" and @type="checkbox"]')) == 2
    for cancel in dialog.xpath('.//button[@data-close-connection]'):
        assert cancel.get("type") == "button"
    setup, = page.xpath('//a[contains(@href,"/setup")]')
    assert setup.getparent().xpath('.//form[input[@name="action" and @value="revoke"]]')
    assert m.app.extensions["mcp_access"].load() == before
    assert call(credential, "list_customers")["ok"]


def test_agent_back_link_opens_settings(client):
    page = html.fromstring(client.get("/agents").data)
    back, = page.xpath('//a[contains(@href,"#agent-access-card")]/@href')
    response = client.get(back)
    assert response.status_code == 200
    assert back.endswith("#agent-access-card")


@pytest.mark.parametrize("sole_issuer", ["default", OTHER])
@pytest.mark.parametrize("language", ["de", "en"])
def test_single_active_issuer_is_used_without_a_selector_and_never_retargeted(client, sole_issuer, language):
    client.set_cookie("lang", language)
    root = m.DATA_DIR
    add_other(deleted=sole_issuer == "default")
    if sole_issuer == OTHER:
        m._write_json(root / "seller.json", {**SELLER, "_deleted": True})
    assert configure(client, "enable", consent="yes").status_code == 200
    page = html.fromstring(client.get("/agents").data)
    form, = page.get_element_by_id("agent-connection-dialog").xpath('.//form')
    assert not form.xpath('.//input[@name="issuers" and @type="checkbox"]')
    values = {**dict(form.form_values()), "name": "Sole issuer connection", "customer_mode": "all"}
    assert values["issuers"] == sole_issuer
    response = client.post(form.action, data=values)
    assert response.status_code == 200
    access = m.app.extensions["mcp_access"]
    assert [c["issuers"] for c in access.load()["connections"].values()] == [[sole_issuer]]

    # A stale form must not silently switch to a different default issuer.
    m._write_json(root / "seller.json", {**SELLER, "_deleted": sole_issuer == "default"})
    m._write_json(root / "issuers" / OTHER / "seller.json", {**SELLER, "_deleted": sole_issuer == OTHER})
    before = access.load()
    assert client.post(form.action, data=values).status_code == 400
    assert access.load() == before


@pytest.mark.parametrize("language", ["de", "en"])
def test_new_connections_exclude_inactive_issuers_and_reject_stale_forms(client, language):
    client.set_cookie("lang", language)
    add_other()
    existing = grant(client, issuers=[OTHER])
    page = html.fromstring(client.get("/agents").data)
    form, = page.get_element_by_id("agent-connection-dialog").xpath('.//form')
    assert OTHER in form.xpath('.//input[@name="issuers"]/@value')
    stale = {**dict(form.form_values()), "name": "New connection", "issuers": OTHER, "customer_mode": "all"}
    seller_file = m.DATA_DIR / "issuers" / OTHER / "seller.json"
    seller = json.loads(seller_file.read_text())
    seller["_deleted"] = True
    m._write_json(seller_file, seller)
    page = html.fromstring(client.get("/agents").data)
    assert page.get_element_by_id("agent-connection-dialog").xpath('.//input[@name="issuers"]/@value') == ["default"]
    before = m.app.extensions["mcp_access"].load()
    assert client.post(form.action, data=stale).status_code == 400
    assert m.app.extensions["mcp_access"].load() == before
    # Existing grants keep their archive access for corrections and history.
    assert call(existing, "list_invoices", issuer=OTHER)["ok"]
    seller["_deleted"] = False
    m._write_json(seller_file, seller)
    assert client.post(form.action, data=stale).status_code == 200


def test_agent_back_link_uses_active_profile_after_deactivation(client):
    add_other()
    seller = m.load_seller()
    seller["_deleted"] = True
    m._write_json(m.SELLER_FILE, seller)
    page = html.fromstring(client.get("/agents?issuer=default").data)
    back, = page.xpath('//a[contains(@href,"#agent-access-card")]/@href')
    assert f"issuer={OTHER}" in back
    response = client.get(back)
    assert response.status_code == 200
    assert back.endswith("#agent-access-card")


def test_unreadable_agent_settings_do_not_block_normal_invoicing(client):
    path = m.BASE / "agent_access.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("invalid-json")
    assert client.get("/").status_code == 200
    page = html.fromstring(client.get("/settings/panel").data)
    switch, = page.xpath('//button[@role="switch"]')
    assert "disabled" in switch.attrib
    assert page.get_element_by_id("agent-access-card").xpath('.//p[@role="alert" and not(@hidden)]')
    assert not call("x" * 43, "list_customers")["ok"]
    assert path.read_text() == "invalid-json"


@pytest.mark.parametrize("language", ["de", "en"])
def test_inline_settings_show_setup_state_and_manage_connections(client, language):
    client.set_cookie("lang", language)
    headers = {"X-Requested-With": "fetch"}
    access = m.app.extensions["mcp_access"]

    def update(action, **fields):
        return client.post("/agents/settings", headers=headers, data={
            "csrf": csrf(client), "return_to": "settings", "action": action, **fields,
        })

    before = snapshot()
    enabled = update("enable", consent="yes")
    assert enabled.status_code == 200
    page = html.fromstring(enabled.json["management"])
    assert page.get_element_by_id("agent-connection-add").text.strip() == (
        "Assistent verbinden" if language == "de" else "Connect assistant")
    assert not access.load()["connections"]
    assert snapshot() == before
    created = update("connect", name="Fictional connection", issuers=["default"], write="yes", customer_mode="all")
    assert created.status_code == 200
    page = html.fromstring(created.json["management"])
    config = json.loads(page.get_element_by_id("mcp-configuration").text)
    token = config["mcpServers"]["erechnung"]["env"]["ERECHNUNG_MCP_TOKEN"]
    connection = access.authenticate(token, m.DATA_DIR)
    assert not page.get_element_by_id("agent-setup-dialog").xpath('.//*[@data-setup-language]')
    for form in page.xpath('//form'):
        assert form.xpath('./input[@name="return_to" and @value="settings"]')
    for endpoint in ("/settings/panel", "/validate", "/agents/panel"):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert token not in response.text
        assert "Fictional connection" in response.text
    assert update("pause", connection=connection["id"]).status_code == 200
    assert not call(token, "list_customers")["ok"]
    assert update("resume", connection=connection["id"]).status_code == 200
    assert call(token, "list_customers")["ok"]
    review = update("revoke", connection=connection["id"])
    assert review.status_code == 200 and "confirmation" in review.json
    assert call(token, "list_customers")["ok"]
    form, = html.fromstring(review.json["confirmation"]).xpath('//form')
    removed = client.post(form.action, headers=headers, data=dict(form.form_values()))
    assert removed.status_code == 200
    assert not access.load()["connections"]
    assert not call(token, "list_customers")["ok"]


@pytest.mark.parametrize("decision", ["approve", "deny"])
def test_inline_action_review_still_requires_exact_explicit_decision(client, decision):
    token = grant(client)
    pending = call(token, "save_customer", issuer="default", buyer={**BUYER, "city": "Hamburg"})
    endpoint = "/agents/requests/" + pending["request_id"]
    before = snapshot()
    headers = {"X-Requested-With": "fetch"}
    review = client.get(endpoint, headers=headers)
    assert review.status_code == 200 and not review.json["decided"]
    assert "Hamburg" in review.json["confirmation"]
    assert snapshot() == before
    fields = {"csrf": csrf(client), "return_to": "settings"}
    assert client.post(endpoint, headers=headers, data=fields).status_code == 400
    assert client.post(endpoint, headers=headers, data={"decision": decision}).status_code == 403
    for extra in ({"Origin": "https://other.example"}, {"Authorization": "Bearer " + token}):
        assert client.post(endpoint, headers={**headers, **extra}, data={**fields, "decision": decision}).status_code == 403
    assert snapshot() == before
    result = client.post(endpoint, headers=headers, data={**fields, "decision": decision})
    assert result.status_code == 200 and result.json["decided"]
    assert not html.fromstring(result.json["confirmation"]).xpath('//button[@name="decision"]')
    assert (snapshot() != before) == (decision == "approve")
    after = snapshot()
    assert client.post(endpoint, headers=headers, data={**fields, "decision": decision}).status_code == 409
    assert snapshot() == after


def test_settings_fragment_read_does_not_require_agent_csrf_on_unrelated_form_posts(client, monkeypatch):
    # A file-validation POST must still render Settings without an MCP CSRF field.
    monkeypatch.setattr(m, "_localized_validation", lambda: None)
    assert client.post("/settings/panel", data={}).status_code == 200
    assert client.post("/validate", data={}).status_code == 200
    assert client.get("/agents/panel", headers={"Authorization": "Bearer " + "x" * 43}).status_code == 403
    monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    assert client.get("/agents/panel").status_code == 404
