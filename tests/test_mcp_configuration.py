"""Both configuration views expose the same exact one-time setup values."""
import json
import sys

import pytest
from lxml import html
from test_mcp_access import client as client
from test_mcp_access import configure, grant
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
    assert token not in client.get("/agents").text
    assert token not in (m.BASE / "agent_access.json").read_text()
    assert result.headers["Cache-Control"] == "no-store"
