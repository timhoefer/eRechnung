"""Per-operation policies cannot bypass scope, approval, or archive integrity."""

import pytest
from lxml import html
from test_mcp_access import (
    BUYER,
    OTHER,
    add_other,
    call,
    configure,
    csrf,
    decide,
    grant,
    invoice_args,
    snapshot,
)
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_connection_names import edit_form
from test_mcp_permission_editing import permissions
from werkzeug.datastructures import MultiDict

import app as m
from mcp_access import DESTRUCTIVE, WRITE_OPERATIONS, AccessError, permission, validate_permissions
from mcp_contract import TOOLS


def policy_grant(client, *, client_approvals=False, **policies):
    token = grant(client)
    identifier = m.app.extensions["mcp_access"].authenticate(token, m.DATA_DIR)["id"]
    fields = {"permission_" + op: policies.get(op, "deny") for op in WRITE_OPERATIONS}
    assert permissions(client, identifier, **fields, client_approvals="yes" if client_approvals else "no").status_code == 200
    return token


def arguments(operation):
    return {
        "save_customer": {"issuer": "default", "buyer": {**BUYER, "city": "Hamburg"}},
        "save_customer_items": {"issuer": "default", "buyer": BUYER, "items": invoice_args()["items"]},
        "save_issuer": {"issuer": "default", "seller_revision": m.seller_revision(m.load_seller()), "changes": {"city": "Hamburg"}},
        "create_invoice": invoice_args(),
        "delete_customer": {"issuer": "default", "name": BUYER["name"]},
        "delete_invoice": {"issuer": "default", "filename": "Rechnung_TEST.pdf"},
        "deactivate_issuer": {"issuer": "default"},
        "restore_issuer": {"issuer": "default"},
    }[operation]


def test_policies_cover_every_write_tool():
    assert set(WRITE_OPERATIONS) == {op for op, spec in TOOLS.items() if spec["write"]}


@pytest.mark.parametrize("lang", ["de", "en"])
def test_new_connection_denies_destructive_actions_and_asks_for_other_changes(client, lang):
    client.set_cookie("lang", lang)
    configure(client, "enable", consent="yes")
    page = html.fromstring(client.get("/agents").data)
    form, = page.xpath('//form[input[@name="action" and @value="connect"]]')
    fields = MultiDict(form.form_values())
    assert fields["permission_policy"] == "1" and fields["client_approvals"] == "no"
    expected = dict.fromkeys(WRITE_OPERATIONS, "confirm")
    expected.update(deactivate_issuer="deny", delete_customer="deny", delete_invoice="deny")
    for op in WRITE_OPERATIONS:
        assert fields["permission_" + op] == expected[op]
        values = form.xpath(f'.//select[@name="permission_{op}"]/option/@value')
        assert set(values) == ({"deny", "confirm"} if op in DESTRUCTIVE else {"deny", "confirm", "allow"})
        selected, = form.xpath(f'.//select[@name="permission_{op}"]/option[@selected]')
        assert ("empfohlen" if lang == "de" else "recommended") in selected.text
    assert client.post(form.action, data=fields).status_code == 200
    connection, = m.app.extensions["mcp_access"].load()["connections"].values()
    assert connection["permissions"] == expected
    assert connection["writable"] is True


@pytest.mark.parametrize("operation", WRITE_OPERATIONS)
def test_denied_operations_do_not_mutate_or_create_approval_requests(client, operation):
    token = policy_grant(client, **{op: "confirm" for op in WRITE_OPERATIONS if op != operation})
    before = snapshot()
    result = call(token, operation, **arguments(operation))
    assert not result["ok"] and "not permitted" in result["message"]
    assert snapshot() == before and not m.app.extensions["mcp_access"].pending


@pytest.mark.parametrize("operation", ["save_customer", "save_customer_items", "save_issuer"])
@pytest.mark.parametrize("policy", ["allow", "confirm"])
def test_edits_follow_policy_and_confirmed_edits_execute_only_once(client, operation, policy):
    token = policy_grant(client, **{operation: policy})
    before = snapshot()
    result = call(token, operation, **arguments(operation))
    if policy == "confirm":
        assert result["status"] == "approval_required" and snapshot() == before
        assert decide(client, result["request_id"]).status_code == 303
        assert call(token, "request_status", request_id=result["request_id"])["status"] == "completed"
        after = snapshot()
        assert client.post("/agents/requests/" + result["request_id"], data={"csrf": csrf(client), "decision": "approve"}).status_code == 409
        assert snapshot() == after
    else:
        assert result["ok"], result
        assert not m.app.extensions["mcp_access"].pending
    assert snapshot() != before


@pytest.mark.parametrize("policy", ["allow", "confirm"])
def test_new_customer_obeys_policy(client, policy):
    token = policy_grant(client, save_customer=policy)
    before = snapshot()
    result = call(token, "save_customer", issuer="default", buyer={**BUYER, "name": "New client"})
    if policy == "confirm":
        assert result["status"] == "approval_required" and snapshot() == before
        assert decide(client, result["request_id"]).status_code == 303
    else:
        assert result["ok"]
    assert any(c["name"] == "New client" for c in m.load_customers())


@pytest.mark.parametrize("policy", ["deny", "confirm", "allow"])
def test_saving_items_cannot_bypass_new_customer_permission(client, policy):
    token = policy_grant(client, save_customer_items="allow", save_customer=policy)
    args = arguments("save_customer_items")
    args["buyer"] = {**BUYER, "name": "New client"}
    before = snapshot()
    result = call(token, "save_customer_items", **args)
    if policy == "deny":
        assert not result["ok"] and snapshot() == before
        assert not m.app.extensions["mcp_access"].pending
    elif policy == "confirm":
        assert result["status"] == "approval_required" and snapshot() == before
        assert decide(client, result["request_id"]).status_code == 303
        assert any(c["name"] == "New client" for c in m.load_customers())
    else:
        assert result["ok"] and snapshot() != before


@pytest.mark.parametrize("new_customer", [False, True])
@pytest.mark.parametrize("policy", ["deny", "confirm", "allow"])
def test_invoice_creation_obeys_implicit_customer_permission(client, policy, new_customer):
    token = policy_grant(client, create_invoice="allow", save_customer=policy)
    args = invoice_args()
    args["buyer"] = {**BUYER, "city": "Hamburg", **({"name": "New client"} if new_customer else {})}
    before = snapshot()
    result = call(token, "create_invoice", **args)
    if policy == "deny":
        assert not result["ok"] and snapshot() == before
        assert not m.app.extensions["mcp_access"].pending
        return
    if policy == "confirm":
        assert result["status"] == "approval_required" and snapshot() == before
        assert decide(client, result["request_id"]).status_code == 303
        assert call(token, "request_status", request_id=result["request_id"])["status"] == "completed"
    else:
        assert result["ok"], result
    assert list(m.OUTPUT_DIR.glob("*.pdf"))
    assert any(c["city"] == "Hamburg" for c in m.load_customers())


def test_allowed_invoice_retains_validation_and_duplicate_protection(client):
    token = policy_grant(client, create_invoice="allow", save_customer="allow")
    args = invoice_args()
    assert call(token, "create_invoice", **args)["ok"]
    before = snapshot()
    args["seller_revision"] = m.seller_revision(m.load_seller())
    args["items"][0]["unit_price"] = "999"
    assert not call(token, "create_invoice", **args)["ok"]
    assert snapshot() == before
    args["invoice"]["number"] = "TEST-INVALID"
    args["buyer"] = {**BUYER, "country": "INVALID"}
    assert not call(token, "create_invoice", **args)["ok"]
    assert snapshot() == before


@pytest.mark.parametrize("operation", sorted(DESTRUCTIVE))
@pytest.mark.parametrize("bad_value", ["allow", [], None, True])
def test_forged_destructive_allow_and_malformed_policies_fail_closed(client, operation, bad_value):
    policies = {op: "deny" for op in WRITE_OPERATIONS}
    policies[operation] = bad_value
    with pytest.raises(AccessError):
        validate_permissions(policies)
    assert permission({"writable": True, "permissions": policies}, operation) == "deny"
    token = policy_grant(client)
    access = m.app.extensions["mcp_access"]
    connection = access.authenticate(token, m.DATA_DIR)
    before = access.load()
    assert permissions(client, connection["id"], **{"permission_" + operation: "allow"}).status_code == 403
    assert access.load() == before


def test_explicit_save_migrates_legacy_without_automatic_expansion(client):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    old = access.authenticate(token, m.DATA_DIR)
    edit_form(client, old["id"], "permissions")
    assert access.authenticate(token, m.DATA_DIR) == old
    assert "permissions" not in old and permission(old, "create_invoice") == "legacy"
    assert permissions(client, old["id"]).status_code == 200
    current = access.authenticate(token, m.DATA_DIR)
    assert current["token_hash"] == old["token_hash"]
    assert current["permissions"] == {op: "allow" if op == "restore_issuer" else "confirm" for op in WRITE_OPERATIONS}
    # An old form cannot silently discard granular policies.
    form = edit_form(client, old["id"], "permissions")
    fields = MultiDict(form.form_values())
    fields.pop("permission_policy")
    fields["write"] = "yes"
    assert client.post(form.action, data=fields).status_code == 400
    assert access.authenticate(token, m.DATA_DIR) == current


@pytest.mark.parametrize("policy", ["allow", "confirm"])
def test_restoring_issuer_obeys_policy_without_resetting_number(client, policy):
    add_other()
    token = policy_grant(client, restore_issuer=policy)
    seller = m.load_seller()
    m._write_json(m.SELLER_FILE, {**seller, "_deleted": True})
    before = snapshot()
    result = call(token, "restore_issuer", issuer="default")
    if policy == "confirm":
        assert result["status"] == "approval_required" and snapshot() == before
        assert decide(client, result["request_id"]).status_code == 303
    else:
        assert result["ok"], result
    assert not m.load_seller().get("_deleted")
    assert m.load_seller()["last_invoice_number"] == seller["last_invoice_number"]


def test_scope_and_opt_in_still_limit_standing_permissions(client, monkeypatch):
    add_other()
    token = policy_grant(client, save_customer="allow", save_issuer="allow")
    before = snapshot()
    args = arguments("save_issuer")
    assert not call(token, "save_issuer", **{**args, "issuer": OTHER})["ok"]
    assert not call(token, "save_issuer", **{**args, "seller_revision": "stale"})["ok"]
    assert snapshot() == before
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    assert permissions(client, identifier, customer_mode="none").status_code == 200
    assert not call(token, "save_customer", **arguments("save_customer"))["ok"]
    configure(client, "pause", connection=identifier)
    assert not call(token, "save_issuer", **args)["ok"]
    configure(client, "resume", connection=identifier)
    monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    with m.app.test_client(use_cookies=False) as api:
        assert api.post("/agents/call", json={"tool": "save_issuer", "arguments": args}, headers={"Authorization": "Bearer " + token}).status_code == 404
    assert snapshot() == before
