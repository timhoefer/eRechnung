"""Untrusted draft handoff: explicit selection, no persistence until normal export."""
import copy
import io
import json
import re
from datetime import date, timedelta

import pytest
from lxml import html
from werkzeug.datastructures import MultiDict

import app as appmod
from invoice_draft import MAX_BYTES, DraftError, parse_draft

PROPOSAL = {
    "format": "erechnung-draft", "schema_version": 1, "customer": "Example Client",
    "invoice": {"currency": "EUR", "language": "en", "service_start": "2026-11-01",
                "service_end": "2026-11-30"},
    "items": [{"description": "Design retainer", "quantity": "15", "unit": "DAY", "unit_price": "800"},
              {"description": "Workshop", "quantity": "1", "unit": "LS", "unit_price": "100.50",
               "item_start": "2026-11-05", "item_end": "2026-11-05"}],
}
SELLER = {
    "name": "Example Studio", "address_line": "Teststr. 1", "postcode": "10829",
    "city": "Berlin", "country": "DE", "vat_id": "DE123456789",
    "email": "example@example.org", "phone": "+493012345678",
    "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
    "last_invoice_number": f"{date.today().year}-010",
}
BUYER = {"name": "Example Client", "address_line": "Teststr. 2", "postcode": "10115",
         "city": "Berlin", "country": "DE", "email": "client@example.org",
         "reference": "ORDER-1", "payment_term_days": "30"}
OTHER = "a" * 32


def parse(proposal):
    raw = proposal if isinstance(proposal, bytes) else json.dumps(proposal).encode()
    return parse_draft(raw, units={u[0] for u in appmod.UNITS}, treatments=set(appmod.TAX_TREATMENTS))


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "output").mkdir()
    monkeypatch.setattr(appmod, "BASE", tmp_path / "app")
    monkeypatch.setattr(appmod, "DATA_DIR", root)
    monkeypatch.setattr(appmod, "SELLER_FILE", root / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", root / "customers.json")
    monkeypatch.setattr(appmod, "OUTPUT_DIR", root / "output")
    monkeypatch.setattr(appmod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setitem(appmod.app.config, "DRAFT_IMPORT_ENABLED", True)
    appmod.SELLER_FILE.write_text(json.dumps(SELLER))
    appmod.CUSTOMERS_FILE.write_text(json.dumps([BUYER]))
    return appmod.app.test_client()


def upload(client, proposal=PROPOSAL):
    return client.post("/drafts/import", data={
        "draft_file": (io.BytesIO(json.dumps(proposal).encode()), "proposal.json"),
    })


def open_draft(client, proposal=PROPOSAL, **choices):
    return client.post("/drafts/open", data={
        "draft": json.dumps(proposal), "issuer": "default",
        "customer_choice": "saved:Example Client", **choices,
    })


def submitted(response):
    return json.loads(re.search(r"window.SUBMITTED_FORM = (.*);", response.text)[1])


def snapshot():
    return {p.relative_to(appmod.DATA_DIR).as_posix(): p.read_bytes()
            for p in appmod.DATA_DIR.rglob("*") if p.is_file()}


def add_other(*, deleted=False):
    directory = appmod.DATA_DIR / "issuers" / OTHER
    directory.mkdir(parents=True)
    (directory / "output").mkdir()
    (directory / "seller.json").write_text(json.dumps({
        **SELLER, "name": "Other Company", "profile_label": "Company",
        "last_invoice_number": f"{date.today().year}-020", "_deleted": deleted,
    }))
    return directory


def test_feature_is_hidden_and_routes_disabled(client, monkeypatch):
    monkeypatch.setitem(appmod.app.config, "DRAFT_IMPORT_ENABLED", False)
    assert "/drafts/import" not in client.get("/").text
    assert client.get("/drafts/import").status_code == 404
    assert upload(client).status_code == 404
    assert open_draft(client).status_code == 404


def test_import_link_preserves_existing_invoice_tab(client):
    page = html.fromstring(client.get("/").data)
    link = page.xpath('//a[contains(@href, "/drafts/import")]')[0]
    assert link.get("target") == "_blank" and link.get("rel") == "noopener"


def test_import_only_prepares_form_and_never_persists(client, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Import must not create a PDF, XML or write app data")
    for name in ("build_pdf", "build_xml", "_write_json"):
        monkeypatch.setattr(appmod, name, unexpected)
    before = snapshot()
    response = upload(client)
    assert response.status_code == 200
    page = html.fromstring(response.data)
    assert page.xpath('//select[@name="customer_choice"]/option[@selected]/@value') == ["saved:Example Client"]
    response = open_draft(client)
    assert response.status_code == 200
    fields = submitted(response)
    assert fields["description"] == ["Design retainer", "Workshop"]
    assert fields["quantity"] == ["15", "1"]
    assert fields["unit_price"] == ["800", "100.50"]
    assert fields["service_start"] == ["2026-11-01"]
    assert fields["item_end"] == ["", "2026-11-05"]
    assert fields["buyer_address_line"] == [BUYER["address_line"]]
    assert fields["due_date"] == [(date.today() + timedelta(days=30)).isoformat()]
    assert "number" not in fields and "bank_account" not in fields
    page = html.fromstring(response.data)
    assert page.get_element_by_id("invoice-number").get("value") == f"{date.today().year}-011"
    assert not page.xpath('//*[@id="export-conflict"]')
    assert page.get_element_by_id("master-data").get("open") is None
    assert page.get_element_by_id("generate-btn").get("disabled") is not None
    assert snapshot() == before


def test_multiple_issuers_require_choice_and_use_own_number(client):
    add_other()
    page = html.fromstring(upload(client).data)
    assert not page.xpath('//select[@name="issuer"]/option[@selected]')
    assert open_draft(client, issuer="").status_code == 400
    response = open_draft(client, issuer=OTHER)
    page = html.fromstring(response.data)
    assert page.get_element_by_id("invoice-number").get("value") == f"{date.today().year}-021"
    assert submitted(response)["issuer"] == [OTHER]
    assert page.xpath('//*[@id="invoice-form"]/@action') == [f"/generate?issuer={OTHER}"]


def test_retired_issuer_cannot_receive_draft(client):
    add_other(deleted=True)
    page = html.fromstring(upload(client).data)
    assert OTHER not in page.xpath('//select[@name="issuer"]/option/@value')
    assert open_draft(client, issuer=OTHER).status_code == 410


def test_customer_selection_is_explicit_and_uses_current_saved_data(client):
    proposal = {**PROPOSAL, "customer": "Unknown customer"}
    page = html.fromstring(upload(client, proposal).data)
    assert not page.xpath('//select[@name="customer_choice"]/option[@selected]')
    assert open_draft(client, customer_choice="").status_code == 400
    assert open_draft(client, customer_choice="saved:Missing").status_code == 400
    appmod.CUSTOMERS_FILE.write_text(json.dumps([{**BUYER, "address_line": "New address"}]))
    assert submitted(open_draft(client))["buyer_address_line"] == ["New address"]
    fields = submitted(open_draft(client, proposal, customer_choice="new"))
    assert fields["buyer_name"] == ["Unknown customer"]
    assert fields["buyer_address_line"] == [""]
    assert "Unknown customer" not in appmod.CUSTOMERS_FILE.read_text()


def test_ambiguous_names_are_not_silently_resolved(client):
    appmod.CUSTOMERS_FILE.write_text(json.dumps([BUYER, BUYER]))
    page = html.fromstring(upload(client).data)
    assert not page.xpath('//select[@name="customer_choice"]/option[@selected]')
    assert open_draft(client).status_code == 400


def test_script_text_remains_literal_and_hidden_json_roundtrips(client):
    proposal = copy.deepcopy(PROPOSAL)
    proposal["items"][0]["description"] = '</textarea><script>alert("test")</script>'
    page = html.fromstring(upload(client, proposal).data)
    assert not page.xpath('//script[contains(text(), "alert(")]')
    encoded = page.xpath('//textarea[@name="draft"]/text()')[0]
    assert json.loads(encoded) == parse(proposal)
    response = open_draft(client, proposal)
    assert submitted(response)["description"][0] == proposal["items"][0]["description"]
    assert '<script>alert("test")</script>' not in response.text


@pytest.mark.parametrize("path,value", [
    (("seller",), {"iban": "DE-malicious"}),
    (("issuer_id",), OTHER), (("data_scope",), "/tmp/elsewhere"),
    (("invoice", "number"), "2026-999"), (("invoice", "bank_account"), "DE-malicious"),
    (("invoice", "doc_type"), "381"), (("invoice", "discount"), "10"),
    (("items", 0, "unit_price"), "1,000"), (("items", 0, "quantity"), True),
    (("items", 0, "unit_price"), 800), (("items", 0, "unit_price"), "NaN"),
    (("items", 0, "unit_price"), "1e1000"), (("items", 0, "unit_price"), "-5"),
    (("items", 0, "quantity"), "0"), (("items", 0, "unit"), "days"),
    (("items", 1, "quantity"), "2"), (("items", 0, "description"), ""),
    (("items",), []), (("items",), [PROPOSAL["items"][0]] * 101),
    (("invoice", "issue_date"), "2026-02-30"), (("invoice", "issue_date"), "20261101"),
    (("invoice", "service_end"), "2026-10-01"), (("invoice", "language"), []),
    (("invoice", "tax_treatment"), "invented"), (("invoice", "profile"), "other"),
    (("invoice", "currency"), "eur"), (("invoice", "note"), "bad\u0000note"),
    (("items", 0, "description"), "bad\ud800text"),
    (("schema_version",), True), (("schema_version",), 2), (("format",), "other"),
])
def test_malformed_or_privileged_content_is_rejected(client, path, value):
    proposal = copy.deepcopy(PROPOSAL)
    target = proposal
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    before = snapshot()
    with pytest.raises(DraftError):
        parse(proposal)
    assert upload(client, proposal).status_code == 400
    assert open_draft(client, proposal).status_code == 400
    assert snapshot() == before


@pytest.mark.parametrize("raw", [b"[]", b"null", b"\xff", b'{"a":1,"a":2}',
                                b"[" * 2000, b" " * (MAX_BYTES + 1)])
def test_invalid_json_and_resource_limits(client, raw):
    with pytest.raises(DraftError):
        parse(raw)
    assert client.post("/drafts/import", data={
        "draft_file": (io.BytesIO(raw), "proposal.json"),
    }).status_code == 400


@pytest.mark.parametrize("name", ["invoice-draft.json", "invoice-draft-discount-prepaid.json"])
def test_documented_example_uses_supported_contract(client, name):
    from pathlib import Path
    example = Path(__file__).parents[1] / "docs" / "examples" / name
    proposal = parse(example.read_bytes())
    assert proposal["format"] == "erechnung-draft"
    assert upload(client, proposal).status_code == 200
    assert open_draft(client, proposal).status_code == 200


def test_import_rejects_cross_site_posts(client):
    assert client.post("/drafts/open", headers={"Origin": "https://untrusted.example"}, data={
        "draft": json.dumps(PROPOSAL), "issuer": "default", "customer_choice": "new",
    }).status_code == 403


def test_live_preview_fonts_resolve_from_nested_import_url(client):
    response = client.post("/preview-html", data={"description": "Test", "unit_price": "100"},
                           headers={"Referer": "http://localhost/drafts/open"})
    page = html.fromstring(response.data)
    assert page.xpath('//base/@href') == ["/"]
    assert client.get("/static/fonts/IBMPlexSans-400.woff2").status_code == 200


def test_imported_form_keeps_stale_seller_protection(client):
    response = open_draft(client)
    page = html.fromstring(response.data)
    revision = page.xpath('//*[@id="invoice-form"]/input[@name="seller_revision"]/@value')[0]
    appmod.SELLER_FILE.write_text(json.dumps({**SELLER, "address_line": "Changed elsewhere"}))
    fields = submitted(response)
    fields.update(seller_revision=[revision], number=[f"{date.today().year}-011"],
                  issue_date=[date.today().isoformat()])
    response = client.post("/generate", data=MultiDict((k, v) for k, vs in fields.items() for v in vs))
    assert response.status_code == 409
    assert html.fromstring(response.data).xpath('//*[@id="export-conflict"]')
    assert not list(appmod.OUTPUT_DIR.iterdir())


def test_explicit_generation_uses_normal_archive_and_embeds_xml(client):
    # Exercise the final human action separately: import itself must not do this.
    from zugferd import extract_xml_from_pdf
    proposal = copy.deepcopy(PROPOSAL)
    proposal["invoice"].update(issue_date=date.today().isoformat(), tax_treatment="de_19")
    response = open_draft(client, proposal)
    page = html.fromstring(response.data)
    fields = submitted(response)
    fields.update(number=[f"{date.today().year}-011"], seller_revision=page.xpath(
        '//*[@id="invoice-form"]/input[@name="seller_revision"]/@value'))
    response = client.post("/generate", data=MultiDict((k, v) for k, vs in fields.items() for v in vs))
    assert response.status_code == 200
    pdf = appmod.OUTPUT_DIR / f"Rechnung_{date.today().year}-011.pdf"
    xml = extract_xml_from_pdf(pdf.read_bytes())
    assert xml and b"Design retainer" in xml
    assert appmod.validate_xml_bytes(xml)[0]
    assert appmod.validate_schematron(xml)["ok"]
    archived = json.loads(pdf.with_suffix(".json").read_text())
    assert archived["items"][0]["quantity"] == "15"
    assert archived["seller"]["iban"] == SELLER["iban"]

def discounted_proposal(*, line_type="pct", overall_type="abs", prepaid="100"):
    draft = copy.deepcopy(PROPOSAL)
    draft["items"] = [
        {"description": "Design", "quantity": "2", "unit": "DAY", "unit_price": "100",
         "item_discount": "10" if line_type == "pct" else "20", "item_discount_type": line_type,
         "item_discount_reason": "Loyalty"},
        {"description": "Workshop", "quantity": "1", "unit": "LS", "unit_price": "50",
         "item_discount": "5", "item_discount_type": "abs", "item_discount_reason": "Bundle"},
    ]
    draft["invoice"].update(
        discount="25" if overall_type == "abs" else "20", discount_type=overall_type,
        discount_reason="Project discount", prepaid=prepaid, prepaid_ref="Paid invoice EX-001",
        tax_treatment="de_19", issue_date=date.today().isoformat(),
    )
    return draft


def test_discount_and_prepaid_visible_at_review_and_preserved_without_writes(client):
    proposal = discounted_proposal()
    before = snapshot()
    response = upload(client, proposal)
    text = html.fromstring(response.data).text_content()
    for value in ("10 %", "5 EUR", "25 EUR", "100 EUR", "Loyalty", "Project discount", "Paid invoice EX-001"):
        assert value in text
    fields = submitted(open_draft(client, proposal))
    assert fields["item_discount"] == ["10", "5"]
    assert fields["item_discount_type"] == ["pct", "abs"]
    assert fields["item_discount_reason"] == ["Loyalty", "Bundle"]
    for name in ("discount", "discount_type", "discount_reason", "prepaid", "prepaid_ref"):
        assert fields[name] == [proposal["invoice"][name]]
    assert snapshot() == before


@pytest.mark.parametrize("section,field,value", [
    ("invoice", "discount", "-1"), ("invoice", "discount", True),
    ("invoice", "discount_type", "eur"), ("invoice", "discount_type", []),
    ("invoice", "discount_reason", "x" * 501),
    ("invoice", "discount_reason", "\ud800"),
    ("invoice", "prepaid", "-1"), ("invoice", "prepaid", 100),
    ("invoice", "prepaid", "100,50"), ("invoice", "prepaid", "NaN"),
    ("invoice", "prepaid", "1.001"), ("invoice", "prepaid_ref", []),
    ("invoice", "prepaid_ref", "x" * 501),
    ("item", "item_discount", "NaN"), ("item", "item_discount", "-1"),
    ("item", "item_discount_type", {}), ("item", "item_discount_type", "percent"),
    ("item", "item_discount_reason", "x" * 501),
])
def test_invalid_discount_and_prepaid_fields_rejected(client, section, field, value):
    proposal = discounted_proposal()
    target = proposal["invoice"] if section == "invoice" else proposal["items"][0]
    target[field] = value
    before = snapshot()
    with pytest.raises(DraftError):
        parse(proposal)
    assert upload(client, proposal).status_code == 400
    assert open_draft(client, proposal).status_code == 400
    assert snapshot() == before


@pytest.mark.parametrize("section,remove", [
    ("invoice", "discount_type"), ("invoice", "discount"),
    ("invoice", "prepaid"), ("invoice", "tax_treatment"),
    ("item", "item_discount_type"), ("item", "item_discount"),
])
def test_partial_financial_fields_require_clarification(client, section, remove):
    proposal = discounted_proposal()
    target = proposal["invoice"] if section == "invoice" else proposal["items"][0]
    del target[remove]
    assert upload(client, proposal).status_code == 400
    assert open_draft(client, proposal).status_code == 400


@pytest.mark.parametrize("section,changes", [
    ("item", {"item_discount_type": "pct", "item_discount": "100.000001"}),
    ("item", {"item_discount_type": "abs", "item_discount": "200.01"}),
    ("item", {"item_discount_type": "abs", "item_discount": "1.001"}),
    ("invoice", {"discount_type": "pct", "discount": "100.01"}),
    ("invoice", {"discount_type": "abs", "discount": "225.01"}),
    ("invoice", {"discount_type": "abs", "discount": "1.001"}),
    ("invoice", {"prepaid": "238.01"}),
    # Prepaid must fit the total AFTER both line and overall discounts.
    ("invoice", {"discount_type": "pct", "discount": "100", "prepaid": "0.01"}),
])
def test_amounts_never_silently_clipped_on_import(client, section, changes):
    proposal = discounted_proposal()
    target = proposal["invoice"] if section == "invoice" else proposal["items"][0]
    target.update(changes)
    before = snapshot()
    assert upload(client, proposal).status_code == 400
    assert open_draft(client, proposal).status_code == 400
    assert snapshot() == before


@pytest.mark.parametrize("changes", [
    {"discount": "0", "discount_type": "abs", "prepaid": "0"},
    {"discount": "100", "discount_type": "pct", "prepaid": "0"},
    {"discount": "225", "discount_type": "abs", "prepaid": "0"},
    {"prepaid": "238.00"},
])
def test_zero_full_discount_and_fully_paid_boundaries(client, changes):
    proposal = discounted_proposal()
    proposal["invoice"].update(changes)
    assert upload(client, proposal).status_code == 200
    assert open_draft(client, proposal).status_code == 200


@pytest.mark.parametrize("doc_type", ["381", "384", "386"])
def test_adjustments_and_new_prepayment_invoices_stay_outside_import(client, doc_type):
    proposal = discounted_proposal()
    proposal["invoice"]["doc_type"] = doc_type
    assert open_draft(client, proposal).status_code == 400


def test_optional_line_discount_defaults_remain_editable(client):
    proposal = discounted_proposal()
    proposal["items"].append(copy.deepcopy(PROPOSAL["items"][0]))
    fields = submitted(open_draft(client, proposal))
    assert fields["item_discount"] == ["10", "5", "0"]
    assert fields["item_discount_type"] == ["pct", "abs", "pct"]
    assert fields["item_discount_reason"] == ["Loyalty", "Bundle", ""]


@pytest.mark.parametrize("line_type", ["pct", "abs"])
@pytest.mark.parametrize("overall_type,basis,tax,grand,due", [
    ("abs", "200.00", "38.00", "238.00", "138.00"),
    ("pct", "180.00", "34.20", "214.20", "114.20"),
])
@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
def test_discount_prepaid_roundtrip_pdf_xml_archive(client, line_type, overall_type, basis, tax, grand, due, profile):
    from lxml import etree
    from pypdf import PdfReader

    proposal = discounted_proposal(line_type=line_type, overall_type=overall_type)
    proposal["invoice"]["profile"] = profile
    response = open_draft(client, proposal)
    fields = submitted(response)
    page = html.fromstring(response.data)
    fields.update(number=[f"{date.today().year}-011"], seller_revision=page.xpath(
        '//*[@id="invoice-form"]/input[@name="seller_revision"]/@value'))
    response = client.post("/generate", data=MultiDict((k, v) for k, vs in fields.items() for v in vs))
    assert response.status_code == 200
    pdf = appmod.OUTPUT_DIR / f"Rechnung_{date.today().year}-011.pdf"
    xml = (pdf.with_suffix(".xml").read_bytes() if profile == "xrechnung"
           else appmod.extract_xml_from_pdf(pdf.read_bytes()))
    assert xml and appmod.validate_xml_bytes(xml)[0]
    assert appmod.validate_schematron(xml)["ok"]
    doc = etree.fromstring(xml)
    totals = doc.xpath('//*[local-name()="SpecifiedTradeSettlementHeaderMonetarySummation"]')[0]
    for name, expected in {
        "LineTotalAmount": "225.00", "TaxBasisTotalAmount": basis, "TaxTotalAmount": tax,
        "GrandTotalAmount": grand, "TotalPrepaidAmount": "100.00", "DuePayableAmount": due,
    }.items():
        assert totals.xpath(f'./*[local-name()="{name}"]/text()') == [expected]
    assert doc.xpath('//*[local-name()="SpecifiedTradeAllowanceCharge"]/*[local-name()="Reason"]/text()') == [
        "Loyalty", "Bundle", "Project discount",
    ]
    assert doc.xpath('//*[local-name()="ExchangedDocument"]/*[local-name()="TypeCode"]/text()') == ["380"]
    text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    for expected in ("Loyalty", "Project discount", "Paid invoice EX-001", due, "100.00"):
        assert expected in text
    sidecar = json.loads(pdf.with_suffix(".json").read_text())
    for key in ("discount", "discount_type", "discount_reason", "prepaid", "prepaid_ref"):
        assert sidecar["invoice"][key] == proposal["invoice"][key]
    assert sidecar["items"][0]["item_discount_type"] == line_type
