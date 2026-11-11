"""Connection labels are optional metadata, never a new grant or approval."""
from copy import deepcopy

import pytest
from lxml import html
from test_mcp_access import BUYER, OTHER, call, configure, decide, disable, grant, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_customer_scope import scoped_grant

import app as m


def edit_form(client, identifier, action="rename"):
    response = client.get(f"/agents/connections/{identifier}/setup")
    assert response.status_code == 200
    form, = html.fromstring(response.data).xpath(f'//form[input[@name="action" and @value="{action}"]]')
    return form


def rename(client, identifier, name):
    form = edit_form(client, identifier)
    return client.post(form.action, data={**dict(form.form_values()), "name": name})


@pytest.mark.parametrize("language, expected", [("de", "Meine Verbindung"), ("en", "My connection")])
@pytest.mark.parametrize("name", [None, "", "  \t  "])
def test_empty_connection_name_uses_localized_default(client, language, expected, name):
    client.set_cookie("lang", language)
    assert configure(client, "enable", consent="yes").status_code == 200
    page = html.fromstring(client.get("/agents").data)
    form, = page.get_element_by_id("agent-connection-dialog").xpath('.//form')
    field, = form.xpath('.//input[@name="name"]')
    assert "required" not in field.attrib and field.get("placeholder") == expected
    fields = dict(form.form_values())
    if name is None:
        fields.pop("name", None)
    else:
        fields["name"] = name
    response = client.post(form.action, data=fields)
    assert response.status_code == 200
    connection, = m.app.extensions["mcp_access"].load()["connections"].values()
    assert connection["name"] == expected
    assert connection["issuers"] == ["default"] and connection["writable"]
    assert set(connection["permissions"].values()) == {"confirm"}


@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("writable", [True, False])
def test_rename_changes_only_label_and_preserves_credentials_and_scopes(client, active, writable):
    token = scoped_grant(client, mode="selected", writable=writable)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    if not active:
        configure(client, "pause", connection=identifier)
    before = deepcopy(access.load())
    data_before = snapshot()
    form = edit_form(client, identifier)
    fields = {**dict(form.form_values()), "name": "  New <label>  ",
              "issuers": OTHER, "write": "yes", "customer_mode": "all", "active": "true"}
    response = client.post(form.action, data=fields, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200
    before["connections"][identifier]["name"] = "New <label>"
    assert access.load() == before and snapshot() == data_before
    assert "New &lt;label&gt;" in response.json["views"]["de"]
    assert call(token, "list_customers")["ok"] == active
    assert not call(token, "get_issuer", issuer=OTHER)["ok"]


def test_rename_keeps_requests_bound_to_same_grant_without_approving_or_extending_them(client):
    token, other = grant(client), grant(client, name="Other")
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    args = {"issuer": "default", "buyer": {**BUYER, "city": "Hamburg"}}
    request_id = call(token, "save_customer", **args)["request_id"]
    before = deepcopy(access.pending[request_id])
    data_before = snapshot()
    assert rename(client, identifier, "New name").status_code == 200
    before["connection"]["name"] = "New name"
    assert access.pending[request_id] == before
    assert snapshot() == data_before
    assert call(token, "request_status", request_id=request_id)["status"] == "pending"
    assert not call(other, "request_status", request_id=request_id)["ok"]
    assert call(token, "save_customer", **args)["request_id"] == request_id
    assert decide(client, request_id).status_code == 303
    assert call(token, "request_status", request_id=request_id)["status"] == "completed"


def test_rename_does_not_reauthorize_stale_request_snapshots(client):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    request_id = call(token, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
    before = deepcopy(access.pending[request_id])
    state = access.load()
    state["connections"][identifier]["writable"] = False
    access.save(state)
    assert rename(client, identifier, "Read only").status_code == 200
    assert access.pending[request_id] == before
    assert decide(client, request_id).status_code == 403


def test_rename_validation_and_revocation(client):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(token, m.DATA_DIR)["id"]
    before = access.load()
    assert configure(client, "connect", issuers="default", name="x" * 81).status_code == 400
    assert rename(client, identifier, "x" * 81).status_code == 400
    assert access.load() == before
    client.set_cookie("lang", "de")
    assert rename(client, identifier, " ").status_code == 200
    assert access.authenticate(token, m.DATA_DIR)["name"] == "Meine Verbindung"
    fields = {**dict(edit_form(client, identifier).form_values()), "name": "Name"}
    assert client.post("/agents/connections/missing/setup", data=fields).status_code == 403
    assert disable(client).status_code == 200
    assert client.post(f"/agents/connections/{identifier}/setup", data=fields).status_code == 403
    configure(client, "enable", consent="yes")
    assert client.post(f"/agents/connections/{identifier}/setup", data=fields).status_code == 403
    assert not access.load()["connections"]
