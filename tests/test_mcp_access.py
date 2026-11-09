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


def grant(client, *, issuers=None, writable=True, name="Example agent"):
    assert configure(client, "enable", consent="yes").status_code == 200
    response = configure(client, "connect", name=name, issuers=issuers or ["default"], write="yes" if writable else "")
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
        configure(client, "revoke", connection=access.pending[identifier]["connection"]["id"])
    elif cause == "disable":
        configure(client, "disable")
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
