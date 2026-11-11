"""Only explicit, current UI saves change grants; existing tokens enforce them."""
from copy import deepcopy

import pytest
from lxml import html
from werkzeug.datastructures import MultiDict

import app as m
from mcp_access import Access, AccessError
from test_mcp_access import BUYER, OTHER, add_other, call, configure, csrf, disable, grant, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_connection_names import edit_form, rename
from test_mcp_customer_scope import PRIVATE, scoped_grant, seed_archive
from test_mcp_key_rotation import setup_form, configured_token


def permissions(client, identifier, **changes):
    form = edit_form(client, identifier, "permissions")
    fields = MultiDict(form.form_values())
    for key, value in changes.items():
        fields.setlist(key, value if isinstance(value, list) else [value])
    return client.post(form.action, data=fields)


@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("writable", [False, True])
@pytest.mark.parametrize("mode", ["none", "selected", "all"])
def test_edit_form_reflects_current_grant_and_unchanged_confirmation_preserves_it(client, active, writable, mode):
    token = scoped_grant(client, mode=mode, writable=writable)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    if not active:
        configure(client, "pause", connection=identifier)
    before, data_before = access.load(), snapshot()
    form = edit_form(client, identifier, "permissions")
    assert form.fields["customer_mode"] == mode
    assert bool(form.xpath('.//input[@name="write" and @checked]')) == writable
    assert bool(form.xpath('.//input[@name="customers" and @checked]')) == (mode == "selected")
    assert client.get("/agents").status_code == 200  # leaving the GET has no effect
    assert access.load() == before and snapshot() == data_before
    response = permissions(client, identifier)
    assert response.status_code == 200
    assert access.load() == before and snapshot() == data_before
    assert call(token, "list_customers")["ok"] == active


def test_confirmed_restrictions_apply_to_existing_key_and_discard_only_its_requests(client):
    add_other()
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    token = grant(client, issuers=["default", OTHER])
    other_token = grant(client)
    access = m.app.extensions["mcp_access"]
    old = access.authenticate(token, m.DATA_DIR)
    pending = call(token, "delete_customer", issuer="default", name=PRIVATE["name"])["request_id"]
    other_pending = call(other_token, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
    other_entry = deepcopy(access.pending[other_pending])
    form = edit_form(client, old["id"], "permissions")
    fields = MultiDict(form.form_values())
    key, = form.xpath('.//label[span[text()="Example Client"]]/input/@value')
    fields.setlist("issuers", ["default"])
    fields.setlist("customer_mode", ["selected"])
    fields.setlist("customers", [key])
    fields.pop("write", None)
    # Preparing/dismissing the form cannot modify grants or invalidate requests.
    assert client.get(form.action).status_code == 200
    assert access.authenticate(token, m.DATA_DIR) == old and pending in access.pending
    response = client.post(form.action, data=fields, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200 and response.json["updated"] is True
    current = access.authenticate(token, m.DATA_DIR)
    assert current["token_hash"] == old["token_hash"] and current["active"] == old["active"]
    assert current["issuers"] == ["default"] and current["writable"] is False
    assert pending not in access.pending and access.pending[other_pending] == other_entry
    assert client.post(f"/agents/requests/{pending}", data={"csrf": csrf(client), "decision": "approve"}).status_code == 403
    assert [c["name"] for c in call(token, "list_customers")["customers"]] == [BUYER["name"]]
    assert len(call(other_token, "list_customers")["customers"]) == 2
    assert not call(token, "get_issuer", issuer=OTHER)["ok"]
    assert not call(token, "delete_customer", issuer="default", name=BUYER["name"], customer_id=current["customer_ids"][0])["ok"]
    private_file = seed_archive("PRIVATE", PRIVATE)
    assert not call(token, "get_invoice", issuer="default", filename=private_file)["ok"]
    restarted = Access(access.path, access.write)
    assert restarted.authenticate(token, m.DATA_DIR) == current
    # Removing all customer access is independent of keeping issuer read access.
    assert permissions(client, current["id"], customer_mode="none").status_code == 200
    assert call(token, "list_customers")["customers"] == []
    assert call(token, "get_issuer", issuer="default")["ok"]
    assert current["token_hash"] == access.authenticate(token, m.DATA_DIR)["token_hash"]


def test_permission_expansion_still_requires_separate_destructive_approval(client):
    token = scoped_grant(client, mode="none", writable=False)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    before = snapshot()
    assert permissions(client, identifier, customer_mode="all", write="yes").status_code == 200
    result = call(token, "delete_customer", issuer="default", name=BUYER["name"])
    assert result["status"] == "approval_required" and snapshot() == before
    # A no-op permissions save must not extend/approve/discard this request.
    pending = deepcopy(access.pending)
    assert permissions(client, identifier).status_code == 200
    assert access.pending == pending


@pytest.mark.parametrize("change", ["permissions", "rename", "pause", "renew", "disable", "revoke", "folder"])
def test_stale_editor_cannot_restore_old_permissions_or_credentials(client, monkeypatch, tmp_path, change):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    form = edit_form(client, identifier, "permissions")
    fields = MultiDict(form.form_values())
    if change == "permissions":
        assert permissions(client, identifier, customer_mode="none", write="").status_code == 200
    elif change == "rename":
        assert rename(client, identifier, "Renamed").status_code == 200
    elif change == "renew":
        target, data = setup_form(client, identifier)
        configured_token(client.post(target, data=data))
    elif change == "disable":
        disable(client)
    elif change == "revoke":
        configure(client, "revoke", connection=identifier, confirm="yes")
    elif change == "folder":
        monkeypatch.setattr(m, "DATA_DIR", tmp_path / "other")
        m.DATA_DIR.mkdir()
    else:
        configure(client, "pause", connection=identifier)
    before = access.load()
    assert client.post(form.action, data=fields).status_code in (403, 409)
    assert access.load() == before


@pytest.mark.parametrize("action", ["rename", "permissions"])
@pytest.mark.parametrize("problem", ["csrf", "origin", "bearer", "flag", "revision"])
def test_editor_requires_ui_authority_and_current_revision(client, monkeypatch, action, problem):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    form = edit_form(client, identifier, action)
    fields = MultiDict(form.form_values())
    fields["name"] = "Changed"
    fields["customer_mode"] = "none"
    headers = {}
    if problem == "csrf":
        fields.pop("csrf")
    elif problem == "origin":
        headers["Origin"] = "https://foreign.example"
    elif problem == "bearer":
        headers["Authorization"] = "Bearer " + token
    elif problem == "flag":
        monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    else:
        fields["revision"] = "old"
    before = access.load(), snapshot()
    assert client.post(form.action, data=fields, headers=headers).status_code in (403, 404, 409)
    assert (access.load(), snapshot()) == before


@pytest.mark.parametrize("problem", ["empty", "unknown", "changed", "ambiguous", "mode"])
def test_bad_customer_selection_cannot_change_existing_permissions(client, problem):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    form = edit_form(client, identifier, "permissions")
    fields = MultiDict(form.form_values())
    fields["customer_mode"] = "selected"
    keys = form.xpath('.//input[@name="customers"]/@value')
    fields.setlist("customers", keys)
    if problem == "empty": fields.setlist("customers", [])
    elif problem == "unknown": fields.setlist("customers", ["unknown"])
    elif problem == "changed": m._write_json(m.CUSTOMERS_FILE, [{**BUYER, "city": "Different"}])
    elif problem == "ambiguous": m._write_json(m.CUSTOMERS_FILE, [BUYER, BUYER])
    else: fields["customer_mode"] = "invalid"
    before = access.load(), snapshot()
    assert client.post(form.action, data=fields).status_code in (400, 403)
    assert (access.load(), snapshot()) == before


def test_archived_issuer_can_be_removed_but_not_newly_granted(client):
    add_other()
    token = grant(client, issuers=["default", OTHER])
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    seller_file = m.DATA_DIR / "issuers" / OTHER / "seller.json"
    import json
    m._write_json(seller_file, {**json.loads(seller_file.read_text()), "_deleted": True})
    form = edit_form(client, identifier, "permissions")
    assert OTHER in form.xpath('.//input[@name="issuers" and @checked]/@value')
    assert permissions(client, identifier).status_code == 200  # retain existing archive access
    assert permissions(client, identifier, issuers="default").status_code == 200
    assert not call(token, "list_invoices", issuer=OTHER)["ok"]
    form = edit_form(client, identifier, "permissions")
    assert OTHER not in form.xpath('.//input[@name="issuers"]/@value')
    before = access.load()
    assert permissions(client, identifier, issuers=["default", OTHER]).status_code == 400
    assert access.load() == before
