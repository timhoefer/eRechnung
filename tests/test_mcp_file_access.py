"""Customer file grants remain bound to archived bytes, even after revalidation."""
import base64
import json
from pathlib import Path

import pytest
from test_mcp_access import BUYER, call, grant, invoice_args, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access
from test_mcp_customer_scope import PRIVATE, finalize, scoped_grant, seed_archive, selected_args

import app as m


@pytest.mark.parametrize("profile,file_format,xml_only", [
    ("en16931", "pdf", False), ("en16931", "xml", False),
    ("xrechnung", "pdf", False), ("xrechnung", "xml", False), ("xrechnung", "xml", True),
])
def test_replaced_customer_file_stays_denied_after_revalidation(client, profile, file_format, xml_only):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    limited = scoped_grant(client)
    allowed_args = selected_args(limited)
    allowed_args["invoice"].update(number="TEST-ALLOWED", profile=profile)
    filename = finalize(client, limited, allowed_args)
    full = grant(client)
    private_args = invoice_args()
    private_args["invoice"].update(number="TEST-PRIVATE", profile=profile)
    private_args["buyer"] = {k: v for k, v in PRIVATE.items() if k != "items"}
    private_filename = finalize(client, full, private_args)
    if xml_only:
        (m.OUTPUT_DIR / filename).unlink()
        (m.OUTPUT_DIR / private_filename).unlink()
        filename = Path(filename).with_suffix(".xml").name
        private_filename = Path(private_filename).with_suffix(".xml").name
    limited = scoped_grant(client, writable=False)

    def download(token, name=filename):
        return call(token, "get_invoice_file", issuer="default", filename=name, format=file_format)

    initial = download(limited)
    assert initial["ok"]
    assert not download(limited, private_filename)["ok"]
    suffix = ".xml" if profile == "xrechnung" and file_format == "xml" else ".pdf"
    document = (m.OUTPUT_DIR / filename).with_suffix(suffix)
    original = document.read_bytes()
    sidecar = document.with_suffix(".json").read_bytes()
    document.write_bytes((m.OUTPUT_DIR / private_filename).with_suffix(suffix).read_bytes())
    before = snapshot()
    denied = download(limited)
    assert not denied["ok"] and "base64" not in denied
    assert snapshot() == before

    # Technical validity is not permission to disclose another customer's data.
    assert client.post("/settings/panel", data={"issuer": "default", "filename": document.name}).status_code == 200
    # XRechnung's PDF is only a visual companion and contains no invoice XML.
    expected_status = "invalid" if profile == "xrechnung" and file_format == "pdf" else "valid"
    assert m.validation_status.read(document, m.validation_ruleset(), profile)["state"] == expected_status
    before = snapshot()
    denied = download(limited)
    assert not denied["ok"] and "base64" not in denied
    assert snapshot() == before
    assert document.with_suffix(".json").read_bytes() == sidecar
    # Full-customer grants may still inspect changed documents.
    foreign = download(full)
    assert foreign["ok"] and foreign["base64"] != initial["base64"]

    # A byte-identical replacement is still the same authorized document.
    replacement = document.with_suffix(".replacement")
    replacement.write_bytes(original)
    replacement.replace(document)
    assert download(limited) == initial


@pytest.mark.parametrize("receipt", [None, {}, [], {"sha256": None}, {"sha256": []}, {"sha256": {}}])
def test_missing_or_malformed_archive_receipt_denies_scoped_download(client, receipt):
    limited = scoped_grant(client, writable=False)
    identity = selected_args(limited)["customer_id"]
    filename = seed_archive("LEGACY", BUYER, identity)
    sidecar = (m.OUTPUT_DIR / filename).with_suffix(".json")
    original = json.loads(sidecar.read_text())
    if receipt is None:
        original.pop("_archive")
    else:
        original["_archive"] = receipt
    sidecar.write_text(json.dumps(original))
    full = grant(client, writable=False)
    before = snapshot()
    denied = call(limited, "get_invoice_file", issuer="default", filename=filename, format="pdf")
    assert not denied["ok"] and "base64" not in denied
    assert call(full, "get_invoice_file", issuer="default", filename=filename, format="pdf")["ok"]
    assert snapshot() == before


def test_download_checks_the_bytes_returned_not_a_second_file_read(client, monkeypatch):
    token = scoped_grant(client, writable=False)
    filename = seed_archive("READ-ONCE", BUYER, selected_args(token)["customer_id"])
    document = m.OUTPUT_DIR / filename
    original = document.read_bytes()
    read_bytes = Path.read_bytes
    reads = []

    def replace_after_read(path):
        content = read_bytes(path)
        if path == document:
            reads.append(True)
            path.write_bytes(b"other customer's externally replaced document")
        return content

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)
    result = call(token, "get_invoice_file", issuer="default", filename=filename, format="pdf")
    assert result["ok"] and base64.b64decode(result["base64"]) == original
    assert reads == [True]
    assert not call(token, "get_invoice_file", issuer="default", filename=filename, format="pdf")["ok"]
