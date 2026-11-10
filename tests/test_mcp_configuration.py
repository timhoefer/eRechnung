"""Both configuration views expose the same exact one-time setup values."""
import json
import sys

import pytest
from lxml import html
from test_mcp_access import BUYER, call, configure, csrf, grant
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_key_rotation import setup_form

import app as m


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("renew", [False, True])
@pytest.mark.parametrize("frozen", [False, True])
def test_individual_values_match_json_after_creation_and_renewal(client, monkeypatch, language, renew, frozen):
    client.set_cookie("lang", language)
    monkeypatch.setattr(m, "FROZEN", frozen)
    command = '/Applications/Test & "Example".app/Contents/MacOS/eRechnung'
    monkeypatch.setattr(sys, "executable", command)
    endpoint = '/tmp/Test & "Example"/mcp-endpoint.json'
    monkeypatch.setitem(m.app.config, "MCP_ENDPOINT_FILE", endpoint)
    if renew:
        old = grant(client)
        identifier = m.app.extensions["mcp_access"].authenticate(old, m.DATA_DIR)["id"]
        target, fields = setup_form(client, identifier)
        result = client.post(target, data=fields)
    else:
        configure(client, "enable", consent="yes")
        result = configure(client, "connect", name="Test agent", issuers=["default"], customer_mode="none")
    assert result.status_code == 200
    page = html.fromstring(result.data)
    server = json.loads(page.get_element_by_id("mcp-configuration").text)["mcpServers"]["erechnung"]
    assert server["command"] == command
    assert server["env"]["ERECHNUNG_MCP_ENDPOINT_FILE"] == endpoint
    assert page.get_element_by_id("configuration-command").value == command
    arguments = page.xpath('//input[starts-with(@id, "configuration-argument-")]/@value')
    assert arguments == server["args"]
    variables = page.xpath('//input[starts-with(@id, "configuration-env-")]')
    assert {page.get_element_by_id(field.get("id") + "-label").text: field.value for field in variables} == server["env"]
    assert all(field.get("readonly") is not None and field.get("autocomplete") == "off" for field in variables)
    for button in page.xpath('//button[@data-copy-target]'):
        assert page.get_element_by_id(button.get("data-copy-target")) is not None
    token = server["env"]["ERECHNUNG_MCP_TOKEN"]
    if not renew:
        assert page.get_element_by_id("agent-setup-dialog").get("open") is not None
        views = json.loads(page.get_element_by_id("agent-setup-initial").text)
        assert set(views) == {"de", "en"}
        for fragment in views.values():
            initial_config = html.fromstring(fragment).get_element_by_id("mcp-configuration").text
            assert json.loads(initial_config)["mcpServers"]["erechnung"] == server
    assert token not in client.get("/agents").text
    assert token not in (m.BASE / "agent_access.json").read_text()
    assert result.headers["Cache-Control"] == "no-store"


def test_dialog_views_do_not_rotate_until_explicit_confirmation(client):
    old = grant(client)
    access = m.app.extensions["mcp_access"]
    identifier = access.authenticate(old, m.DATA_DIR)["id"]
    target = f"/agents/connections/{identifier}/setup"
    headers = {"X-Requested-With": "fetch"}
    before = access.load()
    response = client.get(target, headers=headers)
    assert response.status_code == 200
    assert access.load() == before
    fields_by_language = []
    for language, content in response.json["views"].items():
        assert old not in content
        form, = html.fromstring(content).xpath('//form')
        fields_by_language.append(dict(form.form_values()))
        assert form.action.startswith(target)
        assert "erneuern" in content if language == "de" else "Renew credential?" in content
    assert fields_by_language[0] == fields_by_language[1]
    result = client.post(target, data=fields_by_language[0], headers=headers)
    assert result.status_code == 200
    tokens = []
    for content in result.json["views"].values():
        page = html.fromstring(content)
        server = json.loads(page.get_element_by_id("mcp-configuration").text)["mcpServers"]["erechnung"]
        tokens.append(server["env"]["ERECHNUNG_MCP_TOKEN"])
        assert not page.xpath('//form')
    assert tokens[0] == tokens[1] and tokens[0] != old
    assert not call(old, "list_customers")["ok"]
    assert call(tokens[0], "list_customers")["ok"]
    assert result.headers["Cache-Control"] == "no-store"
    assert tokens[0] not in (m.BASE / "agent_access.json").read_text()
    stale = client.post(target, data=fields_by_language[0], headers=headers)
    assert stale.status_code == 409
    assert tokens[0] not in stale.text
    assert call(tokens[0], "list_customers")["ok"]


def test_language_switch_changes_only_cookie_not_access_or_pending_actions(client):
    token = grant(client)
    pending = call(token, "delete_customer", issuer="default", name=BUYER["name"])
    assert pending["status"] == "approval_required"
    access = m.app.extensions["mcp_access"]
    before = access.load()
    pending_before = dict(access.pending)
    for language in ["en", "de"]:
        response = client.post("/agents/language", data={"csrf": csrf(client), "language": language})
        assert response.status_code == 200 and response.json == {"language": language}
        assert client.get_cookie("lang").value == language
        assert response.headers["Cache-Control"] == "no-store"
        assert access.load() == before and access.pending == pending_before
        assert call(token, "list_customers")["ok"]
    # The normal page switch returns to the connections page, never to the last POST.
    response = client.get("/setlang/en?next=/agents", headers={"Referer": "http://localhost/agents/settings"})
    assert response.status_code == 302 and response.location == "/agents"
    assert access.load() == before


@pytest.mark.parametrize("invalid", ["csrf", "origin", "bearer", "language", "feature_off"])
def test_dialog_language_endpoint_respects_ui_guards(client, monkeypatch, invalid):
    token = grant(client)
    state = m.app.extensions["mcp_access"].load()
    fields = {"csrf": csrf(client), "language": "en"}
    headers = {}
    if invalid == "csrf":
        fields.pop("csrf")
    elif invalid == "origin":
        headers["Origin"] = "https://example.org"
    elif invalid == "bearer":
        headers["Authorization"] = "Bearer " + token
    elif invalid == "language":
        fields["language"] = "unsupported"
    else:
        monkeypatch.setitem(m.app.config, "MCP_FEATURE", False)
    assert client.post("/agents/language", data=fields, headers=headers).status_code in (400, 403, 404)
    assert not client.get_cookie("lang")
    assert m.app.extensions["mcp_access"].load() == state
