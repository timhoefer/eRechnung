"""CSV must reflect the archived invoice, not stale accounting sidecars."""
import copy
import csv
import io
import json
import os
import shutil
from decimal import Decimal

import pytest
from helpers import pdf_with_xml
from lxml import html
from test_archive_storage import setup as setup

import app as m
import invoice_archive as archive
from zugferd import TAX_TREATMENTS, build_xml


@pytest.fixture
def invoice(setup):
    root, data = setup
    data["buyer"].update(address_line="Testweg 1", postcode="10115", city="Berlin")
    xml = build_xml(data)
    result = archive.archive_invoice(data, pdf_with_xml(xml), xml, root / "output", root / "seller.json")
    document = root / "output" / result["filename"]
    return m.app.test_client(), document, data


def export(client, document, method="selection"):
    if method == "selection":
        return client.post("/export/csv", json={"entries": [["default", document.name]]})
    query = {"file": document.name} if method == "single" else {"from": "2026-01-01", "to": "2026-12-31"}
    return client.get("/export/csv", query_string=query, headers={"X-Requested-With": "fetch"})


@pytest.mark.parametrize("method", ["selection", "single"])
def test_old_archive_cannot_export_same_named_invoice_from_changed_folder(invoice, tmp_path, monkeypatch, method):
    client, document, data = invoice
    page = html.fromstring(client.get("/settings/panel").data)
    url = (page.get_element_by_id("archive-selection").get("action") if method == "selection"
           else page.xpath('//a[@role="menuitem" and text()="CSV"]/@href')[0])
    target = tmp_path / "other-folder"
    shutil.copytree(m.DATA_DIR, target)
    data["items"][0]["unit_price"] = "200"
    other = target / "output" / document.name
    other.write_bytes(pdf_with_xml(build_xml(data)))
    other.with_suffix(".json").write_text(json.dumps(data))
    for name, value in {"DATA_DIR": target, "OUTPUT_DIR": target / "output",
                        "SELLER_FILE": target / "seller.json", "CUSTOMERS_FILE": target / "customers.json"}.items():
        monkeypatch.setattr(m, name, value)
    response = (client.post(url, json={"entries": [["default", document.name]]}) if method == "selection"
                else client.get(url, headers={"X-Requested-With": "fetch"}))
    assert response.status_code == 409
    assert "Datenordner" in response.json["message"]


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("format", ["pdf", "xml", "xrechnung-pair"])
def test_unchanged_invoices_export_without_validation_status(invoice, legacy, format):
    client, document, data = invoice
    if format != "pdf":
        data["invoice"]["profile"] = "xrechnung"
        document.with_suffix(".xml").write_bytes(build_xml(data))
        document.with_suffix(".json").write_text(json.dumps(data))
        if format == "xml":
            document.unlink()
            document = document.with_suffix(".xml")
    if legacy:
        stored = json.loads(document.with_suffix(".json").read_bytes())
        stored.pop("_archive", None)
        document.with_suffix(".json").write_text(json.dumps(stored))
    before = {p.name: p.read_bytes() for p in document.parent.iterdir()}
    response = export(client, document)
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 1 and rows[0]["Brutto"] == "119,00"
    assert {p.name: p.read_bytes() for p in document.parent.iterdir()} == before


@pytest.mark.parametrize("field,value", [
    ("number", "OTHER"), ("issue_date", "2026-10-08"), ("currency", "USD"),
    ("doc_type", "381"), ("ref_number", "ORIGINAL"), ("tax_treatment", "de_7"),
    ("buyer_name", "Other Customer"), ("buyer_country", "FR"), ("unit_price", "900"),
])
@pytest.mark.parametrize("method", ["selection", "single", "range"])
def test_changed_xml_aborts_entire_export(invoice, field, value, method):
    client, document, data = invoice
    changed = copy.deepcopy(data)
    if field.startswith("buyer_"):
        changed["buyer"][field[6:]] = value
    elif field == "unit_price":
        changed["items"][0][field] = value
    else:
        changed["invoice"][field] = value
    document.write_bytes(pdf_with_xml(build_xml(changed)))
    response = export(client, document, method)
    assert response.status_code == 409 and "stimmen nicht" in response.json["message"]
    assert not list(document.parent.glob("*.csv"))


@pytest.mark.parametrize("format", ["pdf", "xml"])
@pytest.mark.parametrize("changed_source", ["xml", "json"])
@pytest.mark.parametrize("start,end", [("2026-07-01", "2026-09-30"), ("2026-10-01", "2026-12-31")])
def test_date_range_checks_dates_before_including_or_excluding_invoices(invoice, format, changed_source, start, end):
    client, document, data = invoice
    if format == "xml":
        document.unlink()
        document = document.with_suffix(".xml")
        data["invoice"]["profile"] = "xrechnung"
    original = copy.deepcopy(data)
    data["invoice"]["issue_date"] = "2026-09-30"
    xml = build_xml(data if changed_source == "xml" else original)
    document.write_bytes(pdf_with_xml(xml) if format == "pdf" else xml)
    document.with_suffix(".json").write_text(json.dumps(data if changed_source == "json" else original))

    response = client.get("/export/csv", query_string={"from": start, "to": end},
                          headers={"X-Requested-With": "fetch"})

    assert response.status_code == 409 and "stimmen nicht" in response.json["message"]
    assert response.mimetype != "text/csv"


@pytest.mark.parametrize("start,end,count", [
    ("2026-07-01", "2026-09-30", 0),
    ("2026-10-07", "2026-10-07", 1),
    ("2026-10-08", "2026-12-31", 0),
])
def test_consistent_invoice_date_range_is_inclusive(invoice, start, end, count):
    client, _, _ = invoice
    response = client.get("/export/csv", query_string={"from": start, "to": end})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == count
    if rows:
        assert rows[0]["Datum"] == "2026-10-07"


def test_excluded_invoice_is_rechecked_before_date_range_export(invoice, monkeypatch):
    client, document, data = invoice
    original = m.verify_csv_source

    def move_into_range_after_check(*args):
        snapshots = original(*args)
        data["invoice"]["issue_date"] = "2026-09-30"
        document.write_bytes(pdf_with_xml(build_xml(data)))
        document.with_suffix(".json").write_text(json.dumps(data))
        return snapshots

    monkeypatch.setattr(m, "verify_csv_source", move_into_range_after_check)
    response = client.get("/export/csv?from=2026-07-01&to=2026-09-30",
                          headers={"X-Requested-With": "fetch"})
    assert response.status_code == 409 and "während" in response.json["message"]


@pytest.mark.parametrize("broken", ["missing-xml", "corrupt-pdf", "corrupt-xml", "doctype", "duplicate-total", "nonfinite"])
def test_unreadable_or_ambiguous_documents_never_fall_back_to_json(invoice, broken):
    client, document, data = invoice
    xml = build_xml(data)
    if broken == "missing-xml":
        content = pdf_with_xml(None)
    elif broken == "corrupt-pdf":
        content = b"%PDF-broken"
    else:
        if broken == "corrupt-xml":
            xml = b"<bad>"
        elif broken == "doctype":
            xml = xml.replace(b"?>", b'?>\n<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]>', 1)
        elif broken == "duplicate-total":
            xml = xml.replace(b"<ram:GrandTotalAmount>119.00</ram:GrandTotalAmount>",
                              b"<ram:GrandTotalAmount>119.00</ram:GrandTotalAmount>" * 2)
        else:
            xml = xml.replace(b">119.00<", b">NaN<")
        content = pdf_with_xml(xml)
    document.write_bytes(content)
    response = export(client, document)
    assert response.status_code == 409 and "nicht mit" in response.json["message"]


def test_changed_json_and_same_length_xml_are_detected(invoice):
    client, document, data = invoice
    sidecar = document.with_suffix(".json")
    stored = json.loads(sidecar.read_bytes())
    stored["items"][0]["unit_price"] = "900"
    sidecar.write_text(json.dumps(stored))
    assert export(client, document).status_code == 409
    sidecar.write_text(json.dumps(data))
    stat = document.stat()
    changed = pdf_with_xml(build_xml(data).replace(b">119.00<", b">199.00<"))
    assert len(changed) == stat.st_size
    document.write_bytes(changed)
    os.utime(document, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert export(client, document).status_code == 409


def test_cosmetic_pdf_change_with_same_xml_is_exportable(invoice):
    client, document, _ = invoice
    document.write_bytes(document.read_bytes() + b"\n% new metadata\n")
    assert export(client, document).status_code == 200


def test_valid_side_xml_cannot_replace_missing_embedded_xml(invoice):
    client, document, data = invoice
    document.write_bytes(pdf_with_xml(None))
    document.with_suffix(".xml").write_bytes(build_xml(data))
    assert export(client, document).status_code == 409


def test_successful_revalidation_does_not_approve_stale_accounting_data(invoice):
    client, document, data = invoice
    data["buyer"]["name"] = "Externally changed customer"
    document.write_bytes(pdf_with_xml(build_xml(data)))
    response = client.post("/settings/panel", data={"filename": document.name})
    assert response.status_code == 200
    assert m.validation_status.read(document, m.validation_ruleset(), "en16931")["state"] == "valid"
    assert export(client, document).status_code == 409


def test_current_calculation_changes_cannot_bypass_xml_comparison(invoice, monkeypatch):
    client, document, _ = invoice
    original = m.compute_totals
    def changed_calculation(*args):
        values = list(original(*args))
        values[-1] += Decimal("0.01")
        return values
    monkeypatch.setattr(m, "compute_totals", changed_calculation)
    assert export(client, document).status_code == 409


def test_one_conflicting_invoice_blocks_the_whole_selection(invoice):
    client, document, data = invoice
    second = document.with_name("Rechnung_OTHER.pdf")
    other = copy.deepcopy(data)
    other["invoice"]["number"] = "OTHER"
    second.write_bytes(pdf_with_xml(build_xml(other)))
    second.with_suffix(".json").write_text(json.dumps(other))
    document.write_bytes(pdf_with_xml(None))
    response = client.post("/export/csv", json={"entries": [["default", second.name], ["default", document.name]]})
    assert response.status_code == 409 and response.mimetype != "text/csv"


@pytest.mark.parametrize("treatment", TAX_TREATMENTS)
def test_all_supported_tax_treatments_export_legacy_data(invoice, treatment):
    client, document, data = invoice
    data["invoice"]["tax_treatment"] = treatment
    document.write_bytes(pdf_with_xml(build_xml(data)))
    document.with_suffix(".json").write_text(json.dumps(data))
    assert export(client, document).status_code == 200


@pytest.mark.parametrize("kind", ["xml-missing", "xml-changed", "xml-linked"])
def test_xrechnung_uses_xml_even_when_pdf_is_unchanged(invoice, kind, tmp_path):
    client, document, data = invoice
    data["invoice"]["profile"] = "xrechnung"
    document.with_suffix(".json").write_text(json.dumps(data))
    xml_path = document.with_suffix(".xml")
    if kind == "xml-changed":
        xml_path.write_bytes(build_xml(data).replace(b">119.00<", b">199.00<"))
    elif kind == "xml-linked":
        external = tmp_path / "external.xml"
        external.write_bytes(build_xml(data))
        xml_path.symlink_to(external)
    assert export(client, document).status_code == 409


@pytest.mark.parametrize("changed", ["document", "sidecar"])
def test_change_during_export_prevents_desktop_file_creation(invoice, monkeypatch, changed):
    client, document, _ = invoice
    original = m.verify_csv_source
    def replace_after_check(*args):
        snapshots = original(*args)
        target = document if changed == "document" else document.with_suffix(".json")
        target.write_bytes(target.read_bytes() + b" ")
        return snapshots
    monkeypatch.setattr(m, "verify_csv_source", replace_after_check)
    monkeypatch.setitem(m.app.config, "DESKTOP", True)
    monkeypatch.setattr(m.sys, "platform", "darwin")
    monkeypatch.setattr(m, "reveal_in_finder", lambda path: pytest.fail("No CSV may be revealed"))
    response = export(client, document)
    assert response.status_code == 409 and "während" in response.json["message"]
    assert not list(document.parent.glob("*.csv"))


def test_english_error_and_browser_fallback_are_readable(invoice):
    client, document, _ = invoice
    document.write_bytes(pdf_with_xml(None))
    client.set_cookie("lang", "en")
    assert "No CSV file was created" in export(client, document).json["message"]
    page = client.get("/export/csv", query_string={"file": document.name})
    assert page.status_code == 409 and b"CSV export cancelled" in page.data


@pytest.mark.parametrize("doc_type", ["380", "381", "384", "386"])
def test_discount_prepayment_and_credit_sign_match_original(invoice, doc_type):
    client, document, data = invoice
    data["invoice"].update(doc_type=doc_type, ref_number="OLD", discount="10", prepaid="20")
    document.write_bytes(pdf_with_xml(build_xml(data)))
    document.with_suffix(".json").write_text(json.dumps(data))
    response = export(client, document)
    assert response.status_code == 200
    row = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))[0]
    assert row["Brutto"] == ("-107,10" if doc_type == "381" else "107,10")
