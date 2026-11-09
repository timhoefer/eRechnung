"""Recover lost MCP configurations without widening or reviving any grant."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from lxml import html
from test_mcp_access import BUYER, OTHER, add_other, call, configure, csrf, disable, grant, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_customer_scope import scoped_grant

import app as m
from mcp_access import Access, AccessError, digest


def setup_form(client, identifier):
    page = client.get(f"/agents/connections/{identifier}/setup")
    assert page.status_code == 200
    form, = html.fromstring(page.data).xpath('//form')
    return form.action, dict(form.form_values())


def configured_token(response):
    configuration = html.fromstring(response.data).get_element_by_id("mcp-configuration").text
    return json.loads(configuration)["mcpServers"]["erechnung"]["env"]["ERECHNUNG_MCP_TOKEN"]


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("writable", [False, True])
@pytest.mark.parametrize("customer_mode", ["none", "selected", "all"])
def test_renewal_preserves_exact_grant_and_does_not_store_plaintext(client, language, active, writable, customer_mode):
    client.set_cookie("lang", language)
    token = scoped_grant(client, mode=customer_mode, writable=writable)
    other_token = grant(client, name="Unaffected agent")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    if not active:
        assert configure(client, "pause", connection=identifier).status_code == 200
    before = access.load()
    invoice_data = snapshot()
    target, fields = setup_form(client, identifier)
    # Viewing and cancelling setup do not change either credential or data.
    assert client.get("/agents").status_code == 200
    assert access.load() == before
    fields.update(issuers=OTHER, customer_mode="all", write="yes", active="true")
    result = client.post(target, data=fields)
    assert result.status_code == 200
    replacement = configured_token(result)
    assert replacement != token
    expected = json.loads(json.dumps(before))
    expected["connections"][identifier]["token_hash"] = digest(replacement)
    assert access.load() == expected
    assert snapshot() == invoice_data
    assert not call(token, "list_customers")["ok"]
    assert call(other_token, "list_customers")["ok"]
    assert call(replacement, "list_customers")["ok"] is active
    # A new Access instance models an app restart: the old key remains revoked.
    restarted = Access(access.path, access.write)
    with pytest.raises(AccessError):
        restarted.authenticate(token, m.DATA_DIR)
    if active:
        assert restarted.authenticate(replacement, m.DATA_DIR) == expected["connections"][identifier]
    else:
        with pytest.raises(AccessError):
            restarted.authenticate(replacement, m.DATA_DIR)
        configure(client, "resume", connection=identifier)
        assert call(replacement, "list_customers")["ok"]
        assert not call(token, "list_customers")["ok"]
    assert token not in (m.BASE / "agent_access.json").read_text()
    assert replacement not in (m.BASE / "agent_access.json").read_text()
    assert replacement not in client.get(target).text
    assert replacement not in client.get("/agents").text
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["X-Frame-Options"] == "DENY"


def test_card_has_setup_link_and_warning_is_non_mutating(client):
    credential = grant(client, name="<script>fictional</script>")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    state = access.load()
    page = html.fromstring(client.get("/agents").data)
    link, = page.xpath('//a[contains(@href, "/connections/")]/@href')
    response = client.get(link)
    confirmation = html.fromstring(response.data)
    assert identifier in link
    assert "Der bisherige Schlüssel wird sofort ungültig" in confirmation.text_content()
    assert "Aussteller, Kundenfreigaben, Rechte" in confirmation.text_content()
    assert "<script>fictional</script>" in confirmation.text_content()
    assert not confirmation.xpath('//script[contains(text(), "fictional")]')
    assert credential not in response.text and state["connections"][identifier]["token_hash"] not in response.text
    assert client.get(confirmation.xpath('//a/@href')[0]).status_code == 200
    assert access.load() == state


def test_renewal_discards_only_its_requests_and_retains_required_confirmations(client):
    credential = scoped_grant(client)
    other = grant(client, name="Other agent")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    customer = call(credential, "list_customers")["customers"][0]
    args = {"issuer": "default", "name": BUYER["name"], "customer_id": customer["customer_id"]}
    pending = call(credential, "delete_customer", **args)["request_id"]
    other_pending = call(other, "delete_customer", **args)["request_id"]
    before = snapshot()
    target, fields = setup_form(client, identifier)
    replacement = configured_token(client.post(target, data=fields))
    assert pending not in access.pending and other_pending in access.pending
    assert not call(credential, "request_status", request_id=pending)["ok"]
    assert not call(replacement, "request_status", request_id=pending)["ok"]
    assert client.post("/agents/requests/" + pending, data={"csrf": csrf(client), "decision": "approve"}).status_code == 403
    assert call(other, "request_status", request_id=other_pending)["status"] == "pending"
    new_request = call(replacement, "delete_customer", **args)
    assert new_request["status"] == "approval_required" and new_request["request_id"] != pending
    assert snapshot() == before


@pytest.mark.parametrize("change", ["renewed", "paused", "customer_scope", "issuer_scope", "readonly"])
def test_stale_confirmation_does_not_replace_the_current_key(client, change):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    target, fields = setup_form(client, identifier)
    current = credential
    if change == "renewed":
        current = configured_token(client.post(target, data=fields))
    elif change == "paused":
        configure(client, "pause", connection=identifier)
    else:
        state = access.load()
        connection = state["connections"][identifier]
        if change == "customer_scope":
            connection.update(customer_mode="none", customer_ids=[])
        elif change == "issuer_scope":
            add_other()
            connection["issuers"] = [OTHER]
        else:
            connection["writable"] = False
        access.save(state)
    before = access.load()
    result = client.post(target, data=fields)
    assert result.status_code == 409
    assert "Die Verbindung wurde inzwischen geändert" in result.text
    assert current not in result.text
    assert access.load() == before
    assert access.load()["connections"][identifier]["token_hash"] == digest(current)


@pytest.mark.parametrize("change", ["revoked", "disabled", "reenabled", "folder", "feature_off"])
def test_unavailable_connection_cannot_be_recreated_by_old_setup(client, monkeypatch, tmp_path, change):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    target, fields = setup_form(client, identifier)
    if change == "revoked":
        configure(client, "revoke", connection=identifier, confirm="yes")
    elif change in {"disabled", "reenabled"}:
        disable(client)
        if change == "reenabled":
            grant(client, name="New connection")
    elif change == "folder":
        monkeypatch.setattr(m, "DATA_DIR", tmp_path / "new-folder")
        m.DATA_DIR.mkdir()
    else:
        monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    before = access.load()
    assert client.get(target).status_code in (403, 404)
    assert client.post(target, data=fields).status_code in (403, 404)
    assert access.load() == before


@pytest.mark.parametrize("problem", ["csrf_missing", "csrf_wrong", "origin", "null_origin", "bearer", "unconfirmed", "no_revision"])
def test_rotation_cannot_bypass_ui_guards_or_review(client, problem):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    target, fields = setup_form(client, identifier)
    before = access.load()
    headers = {}
    if problem == "csrf_missing":
        fields.pop("csrf")
    elif problem == "csrf_wrong":
        fields["csrf"] = "wrong"
    elif problem in {"origin", "null_origin"}:
        headers["Origin"] = "https://example.org" if problem == "origin" else "null"
    elif problem == "bearer":
        headers["Authorization"] = "Bearer " + credential
    elif problem == "unconfirmed":
        fields.pop("confirm")
    else:
        fields.pop("revision")
    assert client.post(target, data=fields, headers=headers).status_code in (403, 409)
    assert access.load() == before
    assert call(credential, "list_customers")["ok"]
    assert client.get(target, headers={"Authorization": "Bearer " + credential}).status_code == 403
    assert not call(credential, "renew", connection=identifier)["ok"]


def test_parallel_confirmation_creates_only_one_new_key(client):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    target, fields = setup_form(client, identifier)
    cookie = client.get_cookie("session")
    def submit(_):
        with m.app.test_client() as window:
            window.set_cookie("session", cookie.value)
            return window.post(target, data=fields)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    token = configured_token(next(r for r in responses if r.status_code == 200))
    assert call(token, "list_customers")["ok"] and not call(credential, "list_customers")["ok"]


def test_renewal_preserves_legacy_defaults(client):
    credential = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(credential, m.DATA_DIR)["id"]
    state = access.load()
    for key in ("active", "customer_mode", "customer_ids"):
        del state["connections"][identifier][key]
    access.save(state)
    target, fields = setup_form(client, identifier)
    replacement = configured_token(client.post(target, data=fields))
    state["connections"][identifier]["token_hash"] = digest(replacement)
    assert access.load() == state
    assert call(replacement, "list_customers")["customers"][0]["name"] == BUYER["name"]
