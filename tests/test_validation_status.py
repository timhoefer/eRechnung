"""A saved check belongs to exact document bytes, issuer and validation rules."""
import io
import json
import os

import pytest
from helpers import confirmed_post
from lxml import html
from test_archive_selection import COMPANY, FILE
from test_archive_selection import archive as archive

import app as m
import validation_status as status
import zugferd


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.setattr(m, "validation_ruleset", lambda: "rules-1")
    monkeypatch.setattr(m, "extract_xml_from_pdf", lambda raw: b"<invoice/>")
    monkeypatch.setattr(m, "validate_xml_bytes", lambda raw: (True, []))
    monkeypatch.setattr(m, "validate_schematron", lambda raw: {
        "available": True, "ok": True, "errors": [], "warnings": [], "error": None,
    })


@pytest.mark.parametrize("endpoint", ["/settings/panel", "/validate"])
def test_manual_check_is_scoped_and_does_not_change_invoice_data(archive, validator, endpoint):
    client, folders = archive
    original = {p: p.read_bytes() for folder in folders.values() for p in folder.iterdir()}
    response = client.post(endpoint + f"?issuer={COMPANY}&archive=all", data={"filename": FILE})
    assert response.status_code == 200
    page = html.fromstring(response.data)
    icons = page.xpath('//span[@class="arch-validation valid"]')
    assert len(icons) == 1 and FILE in icons[0].get("title")
    assert page.xpath('//details[@class="row-menu"]//form[@class="check-file-form"]')
    assert not page.xpath('//td[@class="arch-actions"]/form[@class="check-file-form"]')
    assert status.read(folders[COMPANY] / FILE, "rules-1")["state"] == "valid"
    assert status.read(folders["default"] / FILE, "rules-1") is None
    assert all(p.read_bytes() == raw for p, raw in original.items())


def test_upload_with_same_filename_does_not_mark_archive(archive, validator):
    client, folders = archive
    response = client.post("/settings/panel", data={"file": (io.BytesIO(b"<invoice/>"), FILE)})
    assert response.status_code == 200
    assert status.read(folders["default"] / FILE, "rules-1") is None


def test_rules_and_file_changes_need_recheck(archive, validator, monkeypatch):
    client, folders = archive
    path = folders["default"] / FILE
    client.post("/settings/panel", data={"filename": FILE})
    original_stat = path.stat()
    path.write_bytes(b"changed")  # Same length; restored mtime must not hide edits.
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert status.read(path, "rules-1")["state"] == "file_changed"
    client.post("/settings/panel", data={"filename": FILE})
    assert status.read(path, "rules-1")["state"] == "valid"
    monkeypatch.setattr(m, "validation_ruleset", lambda: "rules-2")
    assert status.read(path, "rules-2")["state"] == "rules_changed"
    client.post("/settings/panel", data={"filename": FILE})
    assert status.read(path, "rules-2")["state"] == "valid"
    os.utime(path, None)  # Timestamp-only changes do not invalidate equal bytes.
    assert status.read(path, "rules-2")["state"] == "valid"


@pytest.mark.parametrize("available,ok,error,expected", [
    (True, False, None, "invalid"), (False, None, None, "unavailable"),
    (True, False, "Validator failed", "unavailable"),
])
def test_failed_and_incomplete_checks_replace_previous_success(archive, validator, monkeypatch,
                                                               available, ok, error, expected):
    client, folders = archive
    path = folders["default"] / FILE
    client.post("/settings/panel", data={"filename": FILE})
    monkeypatch.setattr(m, "validate_schematron", lambda raw: {
        "available": available, "ok": ok, "errors": [], "warnings": [], "error": error,
    })
    client.post("/settings/panel", data={"filename": FILE})
    assert status.read(path, "rules-1")["state"] == expected


@pytest.mark.parametrize("change", ["file", "rules"])
def test_change_during_validation_never_records_success(archive, validator, monkeypatch, change):
    client, folders = archive
    path = folders["default"] / FILE
    def validate(raw):
        if change == "file":
            path.write_bytes(b"external change")
        else:
            monkeypatch.setattr(m, "validation_ruleset", lambda: "rules-2")
        return True, []
    monkeypatch.setattr(m, "validate_xml_bytes", validate)
    client.post("/settings/panel", data={"filename": FILE})
    assert status.read(path, "rules-1") is None


def test_xrechnung_checks_xml_even_when_it_is_missing(archive, validator):
    client, folders = archive
    pdf = folders["default"] / FILE
    sidecar = pdf.with_suffix(".json")
    data = json.loads(sidecar.read_text())
    data["invoice"]["profile"] = "xrechnung"
    sidecar.write_text(json.dumps(data))
    xml = pdf.with_suffix(".xml")
    xml.write_bytes(b"<invoice/>")
    client.post("/settings/panel", data={"filename": xml.name})
    xml.unlink()
    page = html.fromstring(client.get("/settings/panel").data)
    assert page.xpath('//span[@class="arch-validation file_changed"]')
    assert xml.name in page.xpath('//form[@class="check-file-form"]/input/@value')
    assert "Datei nicht gefunden" in client.post("/settings/panel", data={"filename": xml.name}).text


def test_validation_receipts_move_with_archive_and_delete_with_exact_issuer(archive, validator, tmp_path):
    client, folders = archive
    for identity in ("default", COMPANY):
        client.post(f"/settings/panel?issuer={identity}", data={"filename": FILE})
    target = tmp_path / "moved"
    assert m.set_data_dir(str(target)) == (True, "data_dir_ok")
    company_pdf = target / "issuers" / COMPANY / "output" / FILE
    assert status.read(company_pdf, "rules-1")["state"] == "valid"
    assert not status.receipt_path(folders[COMPANY] / FILE).exists()
    response = confirmed_post(client, f"/archive/delete?issuer={COMPANY}", data={"filename": FILE})
    assert response.status_code in (200, 302)
    assert not status.receipt_path(company_pdf).exists()
    assert status.read(target / "output" / FILE, "rules-1")["state"] == "valid"


@pytest.mark.parametrize("raw", ["broken", "[]", '{"version":1,"status":[]}'])
def test_corrupt_receipt_is_ignored(tmp_path, raw):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"pdf")
    status.receipt_path(path).write_text(raw)
    assert status.read(path, "rules") is None


def test_linked_receipt_is_not_read_or_overwritten(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"pdf")
    outside = tmp_path / "outside"
    outside.write_text("preserve")
    status.receipt_path(path).symlink_to(outside)
    assert status.read(path, "rules") is None
    with pytest.raises(OSError):
        status.save(path, b"pdf", "rules", "valid")
    assert outside.read_text() == "preserve"


def test_rules_fingerprint_tracks_schema_dependencies_and_business_rules(tmp_path, monkeypatch):
    schema = tmp_path / "schema"
    schema.mkdir()
    root = schema / "main.xsd"
    root.write_text("root")
    (schema / "types").mkdir()
    imported = schema / "types" / "common.xsd"
    imported.write_text("types")
    rules = tmp_path / "rules"
    rules.mkdir()
    for name in (zugferd._SCH_EN16931, zugferd._SCH_XRECHNUNG):
        (rules / name).write_text(name)
    monkeypatch.setattr(zugferd, "_xsd_path", lambda: str(root))
    monkeypatch.setattr(zugferd, "_schematron_dir", lambda: str(rules))
    first = zugferd.validation_ruleset()
    assert first and first == zugferd.validation_ruleset()
    imported.write_text("changed types")
    second = zugferd.validation_ruleset()
    assert second != first
    (rules / zugferd._SCH_XRECHNUNG).write_text("changed rules")
    assert zugferd.validation_ruleset() != second
    root.unlink()
    assert zugferd.validation_ruleset() is None


def test_recheck_recompiles_changed_schematron(tmp_path):
    path = tmp_path / "test.xsl"
    stylesheet = '''<xsl:stylesheet version="2.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
        xmlns:svrl="http://purl.oclc.org/dsdl/svrl"><xsl:template match="/">
        <svrl:schematron-output>{}</svrl:schematron-output></xsl:template></xsl:stylesheet>'''
    path.write_text(stylesheet.format(""))
    assert zugferd._run_schematron(str(path), b"<invoice/>") == ([], [])
    path.write_text(stylesheet.format('<svrl:failed-assert id="TEST"><svrl:text>Changed</svrl:text></svrl:failed-assert>'))
    errors, _ = zugferd._run_schematron(str(path), b"<invoice/>")
    assert errors and "Changed" in errors[0]
