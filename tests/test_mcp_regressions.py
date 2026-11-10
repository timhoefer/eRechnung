"""Regression cases found while reviewing opt-in and explicit MCP approvals."""
import base64
import json

import pytest
from confirmation_helpers import BUYER, SELLER, add_other, snapshot
from lxml import html
from test_mcp_access import call, decide, grant, invoice_args
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access

import app as m


@pytest.mark.parametrize("action", ["opt_in", "approve_deletion"])
@pytest.mark.parametrize("session_state", ["absent", "unrelated", "empty", "wrong", "non_ascii"])
def test_invalid_session_cannot_enable_or_approve(client, action, session_state):
    if action == "approve_deletion":
        token = grant(client)
        identifier = call(token, "delete_customer", issuer="default", name=BUYER["name"])["request_id"]
        path, fields = "/agents/requests/" + identifier, {"decision": "approve"}
    else:
        path, fields = "/agents/settings", {"action": "enable", "consent": "yes"}
    before = snapshot()
    access = m.app.extensions["mcp_access"]
    grants_before = access.load()
    with m.app.test_client() as fresh_browser:
        if session_state != "absent":
            with fresh_browser.session_transaction() as session:
                if session_state == "unrelated":
                    session["unrelated"] = "value"
                else:
                    session["mcp_csrf"] = "" if session_state == "empty" else "expected-token"
        supplied = "" if session_state == "empty" else "ä" if session_state == "non_ascii" else "invalid"
        response = fresh_browser.post(path, data={**fields, "csrf": supplied})
    assert response.status_code == 403
    assert access.load() == grants_before
    assert snapshot() == before
    if action == "approve_deletion":
        assert call(token, "request_status", request_id=identifier)["status"] == "pending"
        # A legitimate review remains usable after the rejected attempt.
        assert decide(client, identifier).status_code == 303
        assert json.loads(m.CUSTOMERS_FILE.read_text()) == []


@pytest.mark.parametrize("document_type", ["381", "384"])
@pytest.mark.parametrize("source_changed", [False, True])
@pytest.mark.parametrize("source_format", ["pdf", "xml"])
def test_correction_review_matches_effective_archived_invoice(client, document_type, source_changed, source_format):
    token = grant(client)
    arguments = invoice_args()
    if source_format == "xml":
        arguments["invoice"]["profile"] = "xrechnung"
    original = call(token, "create_invoice", **arguments)
    assert decide(client, original["request_id"]).status_code == 303
    filename = call(token, "request_status", request_id=original["request_id"])["result"]["filename"]
    if source_format == "xml":
        pdf = m.OUTPUT_DIR / filename
        pdf.unlink()
        filename = pdf.with_suffix(".xml").name
    add_other()
    retired = call(token, "deactivate_issuer", issuer="default")
    assert decide(client, retired["request_id"]).status_code == 303
    arguments["seller_revision"] = call(token, "get_issuer", issuer="default")["revision"]
    arguments["correction_source"] = filename
    arguments["invoice"].update(number="TEST-2", doc_type=document_type,
                                ref_number="UNRELATED-999", ref_date="2000-01-01")
    pending = call(token, "create_invoice", **arguments)
    assert pending["status"] == "approval_required"
    page = html.fromstring(client.get("/agents/requests/" + pending["request_id"]).data)
    shown = page.xpath('//dl[contains(@class,"agent-fields")]/dd/text()')
    assert "UNRELATED-999" not in page.text_content()
    assert "2000-01-01" not in page.text_content()
    assert "TEST-1" in shown
    assert SELLER["iban"] in shown
    if source_changed:
        # A changed original must cause another review of the newly derived values.
        sidecar = (m.OUTPUT_DIR / filename).with_suffix(".json")
        changed = json.loads(sidecar.read_text())
        changed["invoice"].update(number="TEST-CHANGED", issue_date="2000-02-02")
        sidecar.write_text(json.dumps(changed))
        before = snapshot()
        assert decide(client, pending["request_id"]).status_code == 303
        status = call(token, "request_status", request_id=pending["request_id"])
        assert status["status"] == "failed"
        pending = status["result"]
        assert pending["status"] == "approval_required"
        assert snapshot() == before
        page = html.fromstring(client.get("/agents/requests/" + pending["request_id"]).data)
        shown = page.xpath('//dl[contains(@class,"agent-fields")]/dd/text()')
        assert "TEST-CHANGED" in shown and "2000-02-02" in shown
    assert decide(client, pending["request_id"]).status_code == 303
    assert call(token, "request_status", request_id=pending["request_id"])["status"] == "completed"
    saved = json.loads((m.OUTPUT_DIR / "Rechnung_TEST-2.json").read_text())
    assert saved["invoice"]["ref_number"] in shown
    assert saved["invoice"]["ref_date"] in shown


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
def test_xml_download_is_the_archived_original(client, monkeypatch, profile):
    token = grant(client)
    arguments = invoice_args()
    arguments["invoice"]["profile"] = profile
    pending = call(token, "create_invoice", **arguments)
    assert pending["status"] == "approval_required", pending
    assert decide(client, pending["request_id"]).status_code == 303
    result = call(token, "request_status", request_id=pending["request_id"])
    assert result["status"] == "completed", result
    pdf = m.OUTPUT_DIR / result["result"]["filename"]
    expected = pdf.with_suffix(".xml").read_bytes() if profile == "xrechnung" else m.extract_xml_from_pdf(pdf.read_bytes())
    assert expected
    if profile == "en16931":
        # A stray companion file must not override the XML embedded in a ZUGFeRD PDF.
        pdf.with_suffix(".xml").write_bytes(b"not the embedded invoice")
    m.SELLER_FILE.write_text(json.dumps({**SELLER, "city": "Hamburg"}))
    def no_regeneration(*args, **kwargs):
        pytest.fail("An archived download must never regenerate XML")
    monkeypatch.setattr(m, "build_xml", no_regeneration)
    before = snapshot()
    downloaded = call(token, "get_invoice_file", issuer="default", filename=pdf.name, format="xml")
    assert downloaded["ok"], downloaded
    assert downloaded["filename"] == pdf.with_suffix(".xml").name
    assert downloaded["mime_type"] == "application/xml"
    assert base64.b64decode(downloaded["base64"]) == expected
    assert snapshot() == before


@pytest.mark.parametrize("pdf_kind", ["no_xml", "broken", "oversized"])
def test_embedded_xml_unavailable_returns_error_without_writes(client, pdf_kind):
    token = grant(client)
    args = invoice_args()
    pdf = m.OUTPUT_DIR / "Rechnung_TEST-1.pdf"
    if pdf_kind == "no_xml":
        pdf.write_bytes(m.render_html_pdf("<html><body>Preview only</body></html>"))
    elif pdf_kind == "broken":
        pdf.write_bytes(b"not a PDF")
    else:
        with pdf.open("wb") as file:
            file.truncate(20_000_001)
    pdf.with_suffix(".json").write_text(json.dumps({
        "issuer_id": "default", "seller": SELLER, "invoice": args["invoice"],
        "buyer": BUYER, "items": args["items"],
    }))
    before = snapshot()
    result = call(token, "get_invoice_file", issuer="default", filename=pdf.name, format="xml")
    assert not result["ok"] and result["error"] == "rejected"
    assert "base64" not in result
    assert snapshot() == before
