"""Assistant-specific setup must not change the access granted by the user."""
import pytest
from lxml import html
from test_mcp_access import BUYER, OTHER, add_other, call, configure, decide, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_customer_scope import PRIVATE
from test_mcp_key_rotation import configured_token, setup_form
from werkzeug.datastructures import MultiDict

import app as m
from mcp_access import DESTRUCTIVE, WRITE_OPERATIONS, digest


def onboarding(client):
    page = html.fromstring(client.get("/agents").data)
    form, = page.xpath('//form[@data-agent-onboarding]')
    return form, MultiDict(form.form_values())


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("assistant,name", [("chatgpt", "ChatGPT"), ("codex", "Codex"), ("claude", "Claude"), ("other", None)])
def test_assistant_choice_preserves_safe_defaults_and_one_time_configuration(client, language, assistant, name):
    client.set_cookie("lang", language)
    assert configure(client, "enable", consent="yes").status_code == 200
    access = m.app.extensions["mcp_access"]
    form, fields = onboarding(client)
    assert not access.load()["connections"]
    assert form.xpath('.//input[@name="assistant"]/@value') == ["chatgpt", "codex", "claude", "other"]
    assert fields["customer_mode"] == "none" and fields["client_approvals"] == "no"
    assert fields["issuers"] == "default"
    before = snapshot()
    fields["assistant"] = assistant
    response = client.post(form.action, data=fields)
    assert response.status_code == 200
    token = configured_token(response)
    connection = access.authenticate(token, m.DATA_DIR)
    assert connection["name"] == (name or ("Meine Verbindung" if language == "de" else "My connection"))
    assert connection.get("assistant", "other") == assistant
    assert connection["permissions"] == {op: "deny" if op in DESTRUCTIVE else "confirm" for op in WRITE_OPERATIONS}
    assert not connection.get("client_approvals")
    assert call(token, "list_customers")["customers"] == []
    assert not call(token, "delete_customer", issuer="default", name=BUYER["name"])["ok"]
    assert snapshot() == before
    page = html.fromstring(response.data)
    assert page.xpath('//*[@id="agent-setup-dialog"]//*[@aria-current="step"]/@data-setup-step') == ["3"]
    assert page.get_element_by_id("configuration-tabs").get("data-initial-tab") == (
        "configuration-values-tab" if assistant in {"chatgpt", "codex"} else "configuration-json-tab")
    assert token not in access.path().read_text()
    assert token not in client.get("/agents").text
    assert token not in client.get("/settings/panel").text

    # Recovering setup later retains both the selected guide and all access limits.
    target, renewal = setup_form(client, connection["id"])
    replacement = configured_token(client.post(target, data=renewal))
    assert access.authenticate(replacement, m.DATA_DIR) == {**connection, "token_hash": digest(replacement)}
    assert not call(token, "list_customers")["ok"]


@pytest.mark.parametrize("assistant", ["chatgpt", "codex", "claude", "other"])
def test_onboarding_keeps_customer_scope_and_destructive_confirmation(client, assistant):
    add_other()
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    configure(client, "enable", consent="yes")
    form, fields = onboarding(client)
    key, = form.xpath('.//label[span[text()="Example Client"]]/input/@value')
    for field, value in dict(assistant=assistant, issuers="default", customer_mode="selected", customers=key,
                             permission_delete_customer="confirm").items():
        fields[field] = value
    token = configured_token(client.post(form.action, data=fields))
    access = m.app.extensions["mcp_access"]
    assert not call(token, "get_issuer", issuer=OTHER)["ok"]
    customer, = call(token, "list_customers")["customers"]
    assert customer["name"] == BUYER["name"]
    before = snapshot()
    assert not call(token, "delete_customer", issuer="default", name=PRIVATE["name"])["ok"]
    assert not access.pending
    args = {"issuer": "default", "name": BUYER["name"], "customer_id": customer["customer_id"]}
    pending = call(token, "delete_customer", **args)
    assert pending["status"] == "approval_required" and snapshot() == before
    assert decide(client, pending["request_id"], "deny").status_code == 303
    assert snapshot() == before
    pending = call(token, "delete_customer", **args)
    assert snapshot() == before
    assert decide(client, pending["request_id"]).status_code == 303
    assert [buyer["name"] for buyer in m.load_customers()] == [PRIVATE["name"]]


def test_invalid_assistant_or_disabled_opt_in_creates_no_access(client):
    configure(client, "enable", consent="yes")
    form, fields = onboarding(client)
    access = m.app.extensions["mcp_access"]
    before, data_before = access.load(), snapshot()
    fields["assistant"] = "unrecognized"
    assert client.post(form.action, data=fields).status_code == 400
    assert access.load() == before and snapshot() == data_before
    access.save({"enabled": False, "connections": {}})
    fields["assistant"] = "codex"
    assert client.post(form.action, data=fields).status_code == 403
    assert not access.load()["connections"] and snapshot() == data_before
