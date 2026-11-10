"""Standalone XML and creation dates survive archive lifecycle operations."""
import csv
import io
import json
import os
from datetime import datetime

import pytest
from helpers import confirmed_post
from lxml import html
from test_archive_selection import COMPANY, FILE, RETIRED, YEAR, selected
from test_archive_selection import archive as archive
from test_archive_storage import publish
from test_archive_storage import setup as setup
from test_validation_status import validator as validator

import app as m
import invoice_archive as storage
import validation_status
from zugferd import extract_xml_from_pdf


def xml_only(folder, *, sidecar=True):
    pdf = folder / FILE
    xml = pdf.with_suffix(".xml")
    xml.write_bytes(extract_xml_from_pdf(pdf.read_bytes()))
    pdf.unlink()
    if not sidecar:
        xml.with_suffix(".json").unlink()
    return xml


@pytest.mark.parametrize("endpoint", ["/settings/panel", "/validate"])
def test_xml_only_is_listed_checked_exported_and_offered_as_correction(archive, validator, endpoint):
    client, folders = archive
    document = xml_only(folders[COMPANY])
    # Another issuer's PDF with the same invoice number must remain independent.
    response = client.post(endpoint + f"?issuer={COMPANY}&archive=all", data={"filename": document.name})
    page = html.fromstring(response.data)
    row = page.xpath('//tr[@data-view-url=$url]', url=f"/view/{document.name}?issuer={COMPANY}")[0]
    assert row.get("data-preview-type") == "xml"
    assert row.xpath('.//span[@class="arch-validation valid"]')
    assert validation_status.read(document, "rules-1")["state"] == "valid"
    assert row.xpath('.//form[@class="check-file-form"]/input/@value') == [document.name]
    response = selected(client, [(COMPANY, document.name), ("default", FILE)])
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2 and {r["Aussteller"] for r in rows} == {"Studio", "'=Company"}
    retired = xml_only(folders[RETIRED])
    with m.app.test_request_context():
        assert m.correction_original(retired.name, issuer=RETIRED)["issuer_id"] == RETIRED


def test_xml_without_sidecar_is_discoverable_but_not_exportable(archive):
    client, folders = archive
    document = xml_only(folders["default"], sidecar=False)
    page = html.fromstring(client.get("/settings/panel?year=unknown").data)
    row = page.xpath('//tr[@data-view-url=$url]', url=f"/view/{document.name}?issuer=default")[0]
    assert row.xpath('.//input[@data-archive-entry and @disabled]')
    assert row.xpath('.//td[@class="arch-date"]/text()') == ["Unbekannt"]
    assert document.name in storage.archived_number_files(folders["default"])[f"{YEAR}-001"]
    with m.app.test_request_context():
        assert f"{YEAR}-001" in m.used_invoice_numbers()
    assert selected(client, [("default", document.name)]).status_code == 409


def test_pdf_xml_pair_is_one_row_and_one_csv_record(archive):
    client, folders = archive
    xml = (folders["default"] / FILE).with_suffix(".xml")
    xml.write_bytes(b"<invoice/>")
    documents = storage.archive_documents(folders["default"])
    assert xml not in documents and folders["default"] / FILE in documents
    response = selected(client, [("default", FILE), ("default", xml.name)])
    assert response.status_code == 200
    assert len(response.data.decode("utf-8-sig").splitlines()) == 2
    assert client.get(f"/export/csv?file={xml.name}").data.decode("utf-8-sig").count(f"{YEAR}-001") == 1


def test_incomplete_transaction_xml_does_not_appear_as_standalone(archive):
    client, folders = archive
    document = xml_only(folders["default"])
    pending = folders["default"] / ".archive-pending"
    pending.mkdir()
    (pending / document.name).write_bytes(document.read_bytes())
    assert document not in storage.archive_documents(folders["default"])
    assert selected(client, [("default", document.name)]).status_code == 409


def test_transaction_starting_during_scan_does_not_expose_partial_invoice(archive, monkeypatch):
    _, folders = archive
    folder = folders["default"]
    pdf = folder / FILE
    pdf.unlink()
    document = pdf.with_suffix(".xml")
    original_glob = storage.Path.glob

    def start_transaction(path, pattern):
        if path == folder and pattern == "*":
            pending = folder / ".archive-pending"
            pending.mkdir()
            (pending / document.name).write_bytes(b"<invoice/>")
            document.write_bytes(b"<invoice/>")
        return original_glob(path, pattern)

    monkeypatch.setattr(storage.Path, "glob", start_transaction)
    assert document not in storage.archive_documents(folder)


@pytest.mark.parametrize("endpoint", ["/view/", "/archive/preview/"])
def test_xml_preview_is_inert_original_text_and_download_keeps_original_bytes(archive, endpoint):
    client, folders = archive
    document = xml_only(folders["default"])
    raw = b'<?xml-stylesheet href="https://example.com/leak"?><invoice><script>alert(1)</script></invoice>'
    document.write_bytes(raw)
    response = client.get(endpoint + document.name)
    assert response.status_code == 200 and response.mimetype == "text/html"
    page = html.fromstring(response.data)
    assert not page.xpath("//script | //iframe | //img | //link")
    assert page.xpath("//pre/text()") == [raw.decode()]
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert client.get("/download/" + document.name).data == raw


def test_xml_delete_still_requires_confirmation_and_stays_within_issuer(archive, validator):
    client, folders = archive
    document = xml_only(folders[COMPANY])
    client.post(f"/settings/panel?issuer={COMPANY}", data={"filename": document.name})
    original = document.read_bytes()
    response = client.post(f"/archive/delete?issuer={COMPANY}", data={"filename": document.name})
    assert response.status_code == 428 and document.read_bytes() == original
    response = confirmed_post(client, f"/archive/delete?issuer={COMPANY}", data={"filename": document.name})
    assert response.status_code == 302
    assert not document.exists() and not document.with_suffix(".json").exists()
    assert not validation_status.receipt_path(document).exists()
    assert (folders["default"] / FILE).exists()


def test_linked_xml_is_not_an_archive_entry_or_preview_or_export_source(archive, tmp_path):
    client, folders = archive
    outside = tmp_path / "outside.xml"
    outside.write_text("<private/>")
    link = folders["default"] / "linked.xml"
    link.symlink_to(outside)
    assert link not in storage.archive_documents(folders["default"])
    assert client.get("/archive/preview/linked.xml").status_code == 404
    assert selected(client, [("default", link.name)]).status_code == 409


def test_archive_time_is_written_once_and_preserved_by_identical_retry(setup):
    source, data = setup
    first = publish(source, data)
    document = source / "output" / first["filename"]
    sidecar = document.with_suffix(".json")
    original = sidecar.read_bytes()
    stored_time = json.loads(original)["_archive"]["created_at"]
    assert datetime.fromisoformat(stored_time).tzinfo is not None
    os.utime(document, (10, 10))
    assert publish(source, data)["reused"]
    assert sidecar.read_bytes() == original


def test_external_file_changes_do_not_change_archive_date_order_or_period(archive, validator):
    client, folders = archive
    for identity, day in [("default", 1), (COMPANY, 2)]:
        document = folders[identity] / FILE
        sidecar = document.with_suffix(".json")
        data = json.loads(sidecar.read_text())
        data["_archive"] = {"created_at": f"2026-02-0{day}T12:00:00+00:00"}
        sidecar.write_text(json.dumps(data))

    def snapshot():
        page = html.fromstring(client.get("/settings/panel?issuer=all&sort=created&year=all").data)
        return [(r.get("data-view-url"), r.xpath('.//td[@class="arch-date"]/text()'),
                 r.xpath('.//td[@class="arch-date"]/@title'), r.xpath('.//input/@data-quarter'))
                for r in page.xpath('//tr[contains(@class,"arch-row")]')]

    before = snapshot()
    document = folders["default"] / FILE
    document.write_bytes(b"externally edited")
    os.utime(document, (2000000000, 2000000000))
    client.post("/settings/panel", data={"filename": FILE})
    assert snapshot() == before


@pytest.mark.parametrize("receipt", [None, {}, {"created_at": "broken"}, {"created_at": []}, {"created_at": "9999-12-31T23:59:59-23:59"}])
def test_legacy_or_invalid_archive_time_uses_labelled_invoice_date_without_writing(archive, receipt):
    client, folders = archive
    document = folders["default"] / FILE
    sidecar = document.with_suffix(".json")
    data = json.loads(sidecar.read_text())
    data["_archive"] = receipt
    sidecar.write_text(json.dumps(data))
    original = sidecar.read_bytes()
    page = html.fromstring(client.get("/settings/panel").data)
    cell = page.xpath('//tr[@data-view-url=$url]/td[@class="arch-date"]', url=f"/view/{FILE}?issuer=default")[0]
    assert cell.text_content() == f"{YEAR}-03-15 *"
    assert cell.get("title").startswith("Rechnungsdatum")
    assert sidecar.read_bytes() == original
