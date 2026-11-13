"""The MCP archive must retain scopes and approvals after the 1.3 archive update."""
import base64
import json
from datetime import date

import pytest
from confirmation_helpers import OTHER, add_other
from test_mcp_access import BUYER, call, decide, grant, invoice_args, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_customer_scope import PRIVATE, finalize, scoped_grant, seed_archive, selected_args

import app as m


@pytest.mark.parametrize("mode", ["all", "selected", "none"])
def test_archive_listing_covers_all_years_without_expanding_scope(client, mode):
    token = scoped_grant(client, mode=mode)
    customers = call(token, "list_customers")["customers"]
    identity = customers[0].get("customer_id") if customers else None
    filenames = []
    for label, issue_date in [("CURRENT", date.today().isoformat()),
                              ("OLD", f"{date.today().year - 1}-03-01"), ("UNDATED", None)]:
        filename = seed_archive(label, BUYER, identity)
        path = (m.OUTPUT_DIR / filename).with_suffix(".json")
        data = json.loads(path.read_text())
        data["invoice"]["issue_date"] = issue_date
        path.write_text(json.dumps(data))
        filenames.append(filename)
    private = seed_archive("PRIVATE", PRIVATE)
    directory = add_other() / "output"
    (directory / "Rechnung_OTHER.pdf").write_bytes(b"Other issuer's invoice")
    before = snapshot()
    result = call(token, "list_invoices", issuer="default")
    expected = [*filenames, private] if mode == "all" else filenames if mode == "selected" else []
    assert result["ok"] and {row["filename"] for row in result["invoices"]} == set(expected)
    # Unknown dates must not expose -Infinity, which is not a JSON number.
    json.dumps(result, allow_nan=False)
    assert not call(token, "list_invoices", issuer=OTHER)["ok"]
    assert snapshot() == before


@pytest.mark.parametrize("scoped", [False, True])
def test_xml_only_archive_reads_status_and_requires_deletion_approval(client, scoped):
    token = scoped_grant(client) if scoped else grant(client)
    arguments = selected_args(token) if scoped else invoice_args()
    arguments["invoice"]["profile"] = "xrechnung"
    pdf = m.OUTPUT_DIR / finalize(client, token, arguments)
    xml = pdf.with_suffix(".xml")
    original = xml.read_bytes()
    pdf.unlink()  # Fictional fixture: only the XRechnung XML and snapshot remain.
    before = snapshot()
    rows = call(token, "list_invoices", issuer="default")["invoices"]
    assert len(rows) == 1 and rows[0]["filename"] == xml.name
    assert rows[0]["validation"]["state"] == "valid"
    assert call(token, "get_invoice", issuer="default", filename=xml.name)["ok"]
    downloaded = call(token, "get_invoice_file", issuer="default", filename=xml.name, format="xml")
    assert downloaded["ok"] and base64.b64decode(downloaded["base64"]) == original
    assert not call(token, "get_invoice_file", issuer="default", filename=xml.name, format="pdf")["ok"]
    assert snapshot() == before

    pending = call(token, "delete_invoice", issuer="default", filename=xml.name)
    assert pending["status"] == "approval_required" and snapshot() == before
    assert decide(client, pending["request_id"], "deny").status_code == 303
    assert snapshot() == before
    pending = call(token, "delete_invoice", issuer="default", filename=xml.name)
    xml.write_bytes(original + b"\n")
    changed = snapshot()
    assert call(token, "list_invoices", issuer="default")["invoices"][0]["validation"]["state"] == "file_changed"
    assert decide(client, pending["request_id"]).status_code == 303
    outcome = call(token, "request_status", request_id=pending["request_id"])
    assert outcome["status"] == "failed" and snapshot() == changed
    renewed = outcome["result"]
    assert renewed["status"] == "approval_required"
    assert decide(client, renewed["request_id"]).status_code == 303
    assert not xml.exists() and not xml.with_suffix(".json").exists()
    assert not m.validation_status.receipt_path(xml).exists()


@pytest.mark.parametrize("mode", ["selected", "none"])
def test_ungranted_xml_only_invoice_remains_inaccessible(client, mode):
    token = scoped_grant(client, mode=mode)
    filename = seed_archive("PRIVATE", PRIVATE)
    pdf = m.OUTPUT_DIR / filename
    xml = pdf.with_suffix(".xml")
    xml.write_bytes(b"private invoice XML")
    pdf.unlink()
    before = snapshot()
    assert call(token, "list_invoices", issuer="default")["invoices"] == []
    for operation in ("get_invoice", "delete_invoice"):
        assert not call(token, operation, issuer="default", filename=xml.name)["ok"]
    assert not call(token, "get_invoice_file", issuer="default", filename=xml.name, format="xml")["ok"]
    assert not m.app.extensions["mcp_access"].pending
    assert snapshot() == before
