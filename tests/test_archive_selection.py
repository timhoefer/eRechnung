"""Mixed issuer archives must keep every file action and CSV row unambiguous."""
import csv
import io
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from helpers import confirmed_post
from lxml import html
from werkzeug.datastructures import MultiDict

import app as m

YEAR = date.today().year
COMPANY = "b" * 32
RETIRED = "c" * 32
FILE = f"Rechnung_{YEAR}-001.pdf"


@pytest.fixture
def archive(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(m, "BASE", root)
    monkeypatch.setattr(m, "DATA_DIR", root)
    monkeypatch.setattr(m, "SELLER_FILE", root / "seller.json")
    monkeypatch.setattr(m, "OUTPUT_DIR", root / "output")
    monkeypatch.setattr(m, "CUSTOMERS_FILE", root / "customers.json")
    monkeypatch.setattr(m, "CONFIG_FILE", root / "config.json")
    monkeypatch.setattr(m, "drafthorse_version_info", lambda: {})
    folders = {}
    for identity, label, deleted in [("default", "Studio", False), (COMPANY, "=Company", False), (RETIRED, "Retired", True)]:
        folder = root if identity == "default" else root / "issuers" / identity
        (folder / "output").mkdir(parents=True)
        seller = {"name": label, "profile_label": label, "country": "DE", "_deleted": deleted}
        (folder / "seller.json").write_text(json.dumps(seller))
        folders[identity] = folder / "output"
        quarter = 1 if identity == "default" else 3
        (folder / "output" / FILE).write_bytes(identity.encode())
        (folder / "output" / FILE).with_suffix(".json").write_text(json.dumps({
            "issuer_id": identity, "seller": seller, "buyer": {"name": label + " customer"},
            "invoice": {"number": f"{YEAR}-001", "issue_date": f"{YEAR}-0{quarter * 3}-15", "tax_treatment": "de_19"},
            "items": [{"description": "Test", "quantity": "1", "unit_price": "100"}],
        }))
    old = folders["default"] / "Rechnung_OLD.pdf"
    old.write_bytes(b"old")
    old.with_suffix(".json").write_text(json.dumps({"invoice": {"number": "OLD", "issue_date": f"{YEAR-1}-12-20"}, "items": [], "buyer": {}}))
    orphan = folders["default"] / "legacy.pdf"
    orphan.write_bytes(b"no accounting data")
    return m.app.test_client(), folders


@pytest.mark.parametrize("endpoint", ["/settings/panel", "/validate"])
def test_all_issuers_groups_years_and_retired_actions(archive, endpoint):
    client, _ = archive
    page = html.fromstring(client.get(endpoint + "?issuer=all").data)
    assert page.get_element_by_id("archive-issuer-select").value == "all"
    assert page.get_element_by_id("archive-year-select").value == str(YEAR)
    rows = page.xpath('//tr[contains(@class,"arch-row")]')
    assert len(rows) == 4 and "OLD" not in [r.xpath('.//span[@class="arch-id"]/text()')[0] for r in rows]
    assert page.xpath('//input[@data-archive-entry and @disabled]')
    for row in rows:
        issuer = parse_qs(urlparse(row.get("data-view-url")).query)["issuer"][0]
        assert client.get(row.get("data-view-url")).data in {issuer.encode(), b"no accounting data"}
        for url in row.xpath('.//@href | .//@data-url | .//form/@action'):
            assert parse_qs(urlparse(url).query)["issuer"] == [issuer]
        if issuer == RETIRED:
            assert not row.xpath('.//button[contains(@class,"js-delete")]')
            assert len(row.xpath('.//a[contains(@href,"correction_source=")]')) == 2
    old = html.fromstring(client.get(endpoint, query_string={"issuer": "all", "year": YEAR - 1}).data)
    assert old.xpath('//span[@class="arch-id"]/text()') == ["OLD"]
    every = html.fromstring(client.get(endpoint + "?issuer=all&year=all").data)
    assert len(every.xpath('//tr[contains(@class,"arch-row")]')) == 5


def selected(client, pairs, issuer="all"):
    return client.post("/export/csv", query_string={"issuer": issuer},
                       data=MultiDict(("entry", json.dumps(pair)) for pair in pairs))


@pytest.mark.parametrize("lang,delimiter,issuer_header", [("de", ";", "Aussteller"), ("en", ",", "Issuer")])
def test_csv_exact_selection_with_identical_filenames_and_formula_safe_issuer(archive, lang, delimiter, issuer_header):
    client, folders = archive
    client.set_cookie("lang", lang)
    before = {str(p): p.read_bytes() for directory in folders.values() for p in directory.iterdir()}
    response = selected(client, [("default", FILE), (COMPANY, FILE), (COMPANY, FILE)])
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=delimiter))
    assert len(rows) == 2
    assert {row[issuer_header] for row in rows} == {"Studio", "'=Company"}
    assert {str(p): p.read_bytes() for directory in folders.values() for p in directory.iterdir()} == before


@pytest.mark.parametrize("pairs", [[], [("all", FILE)], [("default", "../secret.pdf")], [("default", "legacy.pdf")], [("default", "missing.pdf")], ["bad"], [["default", 1]], [["f" * 32, FILE]]])
def test_csv_rejects_invalid_or_unavailable_selection(archive, pairs):
    client, _ = archive
    assert selected(client, pairs).status_code in {400, 409}


def test_single_issuer_export_cannot_include_another_profile(archive):
    client, _ = archive
    assert selected(client, [(COMPANY, FILE)], "default").status_code == 400
    response = selected(client, [("default", FILE)], "default")
    assert response.status_code == 200 and "Aussteller" not in response.data.decode()


def test_row_delete_does_not_touch_equal_filename_of_other_issuers(archive):
    client, folders = archive
    response = confirmed_post(client, f"/archive/delete?issuer={COMPANY}", data={"filename": FILE})
    assert response.status_code in {200, 302}
    assert not (folders[COMPANY] / FILE).exists()
    assert (folders["default"] / FILE).exists() and (folders[RETIRED] / FILE).exists()


@pytest.mark.parametrize("endpoint", ["/generate", "/archive/delete", "/settings/autosave"])
def test_all_filter_cannot_be_used_as_write_identity(archive, endpoint):
    client, _ = archive
    assert client.post(endpoint + "?issuer=all", data={"filename": FILE}).status_code == 400


def test_checking_a_row_keeps_all_filter_but_validates_exact_issuer(archive, monkeypatch):
    client, _ = archive
    seen = []
    monkeypatch.setattr(m, "extract_xml_from_pdf", lambda raw: seen.append(raw))
    page = html.fromstring(client.get("/settings/panel?issuer=all&year=all&sort=number").data)
    form = next(f for f in page.xpath('//form[@class="check-file-form"]') if COMPANY in f.action)
    response = client.post(form.action, data=dict(form.form_values()))
    assert response.status_code == 200 and seen == [COMPANY.encode()]
    result = html.fromstring(response.data)
    assert result.get_element_by_id("archive-issuer-select").value == "all"
    assert result.get_element_by_id("archive-year-select").value == "all"


def test_selected_export_rejects_sidecar_symlink(archive, tmp_path):
    client, folders = archive
    sidecar = (folders[COMPANY] / FILE).with_suffix(".json")
    outside = tmp_path / "outside.json"
    outside.write_bytes(sidecar.read_bytes())
    sidecar.unlink()
    sidecar.symlink_to(outside)
    assert selected(client, [(COMPANY, FILE)]).status_code == 409
