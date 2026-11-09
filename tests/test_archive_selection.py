"""Mixed issuer archives must keep every file action and CSV row unambiguous."""
import csv
import io
import json
import os
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
def test_all_issuers_years_and_retired_actions(archive, endpoint):
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


@pytest.mark.parametrize("sort,expected", [
    ("created", ["default", RETIRED, COMPANY]),
    ("number", [RETIRED, "default", COMPANY]),
    ("customer", [COMPANY, RETIRED, "default"]),
])
def test_sort_spans_quarters_and_quarter_controls_stay_in_selection(archive, sort, expected):
    client, folders = archive
    for identity, number, modified in [("default", "010", 300), (COMPANY, "07", 100), (RETIRED, "011", 200)]:
        pdf = folders[identity] / FILE
        data = json.loads(pdf.with_suffix(".json").read_text())
        data["invoice"]["number"] = f"{YEAR}-{number}"
        pdf.with_suffix(".json").write_text(json.dumps(data))
        os.utime(pdf, (modified, modified))
    page = html.fromstring(client.get("/settings/panel", query_string={"issuer": "all", "sort": sort}).data)
    rows = page.xpath('//tr[contains(@class,"arch-row")]')
    actual = [json.loads(row.xpath('.//input[@data-archive-entry]/@value')[0])[0]
              for row in rows if not row.xpath('.//input[@data-archive-entry and @disabled]')]
    assert actual == expected
    assert not page.xpath('//table[@class="archive"]/tbody/tr/th')
    controls = page.xpath('//form[@id="archive-selection" and @hidden]//input[@data-archive-quarter]')
    keys = {control.get("data-archive-quarter") for control in controls}
    assert {f"{YEAR}-Q1", f"{YEAR}-Q3"} <= keys
    assert all(row.xpath('.//input[@data-archive-entry]/@data-quarter')[0] in keys for row in rows)


def selected(client, pairs, issuer="all"):
    return client.post("/export/csv", query_string={"issuer": issuer}, json={"entries": pairs})


@pytest.mark.parametrize("count", [1001, 10000])
def test_large_csv_selection_exports_every_invoice(archive, count):
    client, folders = archive
    template = json.loads((folders["default"] / FILE).with_suffix(".json").read_text())
    pairs = []
    for n in range(count):
        identity = "default" if n % 2 == 0 else COMPANY
        number = f"BULK-{n:05d}"
        pdf = folders[identity] / f"Rechnung_{number}.pdf"
        pdf.write_bytes(b"fixture")
        template["issuer_id"] = identity
        template["invoice"]["number"] = number
        pdf.with_suffix(".json").write_text(json.dumps(template))
        pairs.append((identity, pdf.name))
    response = selected(client, pairs)
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.data.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == count
    assert {(row["Aussteller"], row["Nummer"]) for row in rows} == {
        ("Studio" if n % 2 == 0 else "'=Company", f"BULK-{n:05d}") for n in range(count)
    }


def test_form_csv_selection_remains_supported(archive):
    client, _ = archive
    response = client.post("/export/csv?issuer=all", content_type="multipart/form-data",
                           data=MultiDict([("entry", json.dumps(["default", FILE]))]))
    assert response.status_code == 200
    assert len(response.data.decode("utf-8-sig").splitlines()) == 2


@pytest.mark.parametrize("payload", [None, [], {}, {"entries": "bad"}, {"entries": [["default"]]},
                                     {"entries": [["default", FILE]] * 10001}])
def test_invalid_json_selection_is_rejected(archive, payload):
    client, _ = archive
    response = client.post("/export/csv?issuer=all", data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 400


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


@pytest.fixture
def shared_export(archive, monkeypatch):
    client, _ = archive
    monkeypatch.setitem(m.app.config, "DESKTOP", True)
    monkeypatch.setattr(m.sys, "platform", "darwin")
    monkeypatch.setattr(m, "reveal_in_finder", lambda path: None)
    response = selected(client, [("default", FILE), (COMPANY, FILE)])
    assert response.status_code == 200 and response.json["ok"]
    path = m.DATA_DIR / "exports" / response.json["name"]
    return path, path.read_bytes()


@pytest.mark.parametrize("existing_copy", [False, True])
def test_data_move_preserves_shared_csv_exports(shared_export, tmp_path, existing_copy):
    path, content = shared_export
    old = m.DATA_DIR
    target = tmp_path / "moved"
    if existing_copy:
        (target / "exports").mkdir(parents=True)
        (target / "exports" / path.name).write_bytes(content)
    assert m.set_data_dir(str(target)) == (True, "data_dir_ok")
    assert m.DATA_DIR == target
    assert (target / "exports" / path.name).read_bytes() == content
    assert not path.exists()
    assert not (old / "seller.json").exists()
    assert (target / "issuers" / COMPANY / "output" / FILE).is_file()


def test_export_conflict_keeps_both_files_and_active_folder(shared_export, tmp_path):
    path, content = shared_export
    old = m.DATA_DIR
    target = tmp_path / "conflict"
    (target / "exports").mkdir(parents=True)
    other = target / "exports" / path.name
    other.write_bytes(b"different export")
    assert m.set_data_dir(str(target)) == (False, "data_dir_err_export_conflict")
    assert m.DATA_DIR == old
    assert path.read_bytes() == content
    assert other.read_bytes() == b"different export"
    assert not (target / "seller.json").exists()
    assert not m.CONFIG_FILE.exists()


@pytest.mark.parametrize("failure", ["copy", "config"])
def test_failed_export_move_keeps_originals(shared_export, tmp_path, monkeypatch, failure):
    import shutil

    path, content = shared_export
    old = m.DATA_DIR
    target = tmp_path / "failed"
    original_copy = shutil.copy2
    original_write = m._write_json

    def copy(src, dst):
        if src == path:
            raise OSError("disk full")
        return original_copy(src, dst)

    def write(path, data):
        if path == m.CONFIG_FILE:
            raise OSError("read only")
        return original_write(path, data)

    monkeypatch.setattr(shutil, "copy2", copy if failure == "copy" else original_copy)
    monkeypatch.setattr(m, "_write_json", write if failure == "config" else original_write)
    assert m.set_data_dir(str(target)) == (False, "data_dir_err_write" if failure == "copy" else "data_dir_err_save")
    assert m.DATA_DIR == old
    assert path.read_bytes() == content
    assert m.SELLER_FILE.is_file()
    assert not m.CONFIG_FILE.exists()


@pytest.mark.parametrize("linked", ["source_folder", "target_folder", "target_file"])
def test_export_move_rejects_linked_paths(shared_export, tmp_path, linked):
    path, content = shared_export
    old = m.DATA_DIR
    target = tmp_path / "linked"
    outside = tmp_path / "outside"
    outside.mkdir()
    if linked == "source_folder":
        path.parent.rename(outside / "exports")
        path.parent.symlink_to(outside / "exports", target_is_directory=True)
    else:
        target.mkdir()
        if linked == "target_folder":
            (target / "exports").symlink_to(outside, target_is_directory=True)
        else:
            (target / "exports").mkdir()
            (outside / path.name).write_bytes(content)
            (target / "exports" / path.name).symlink_to(outside / path.name)
    before = {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()}
    assert m.set_data_dir(str(target)) == (False, "data_dir_err_write")
    assert m.DATA_DIR == old
    assert path.read_bytes() == content
    assert {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()} == before


def test_export_folder_cannot_become_data_root(shared_export):
    path, content = shared_export
    old = m.DATA_DIR
    assert m.set_data_dir(str(path.parent)) == (False, "data_dir_err_nested")
    assert m.DATA_DIR == old and path.read_bytes() == content


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST"])
def test_desktop_export_waits_for_data_folder_move(shared_export, tmp_path, monkeypatch, method):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    old = m.DATA_DIR
    target = tmp_path / "concurrent"
    moving, release, exporting = Event(), Event(), Event()
    original_move = m._set_data_dir

    def delayed_move(raw):
        moving.set()
        assert release.wait(timeout=5)
        return original_move(raw)

    def export():
        exporting.set()
        with m.app.test_client() as client:
            if method == "POST":
                return selected(client, [("default", FILE), (COMPANY, FILE)])
            return client.open("/export/csv?issuer=all", method=method)

    monkeypatch.setattr(m, "_set_data_dir", delayed_move)
    with ThreadPoolExecutor(max_workers=2) as pool:
        move = pool.submit(m.set_data_dir, str(target))
        assert moving.wait(timeout=5)
        export_request = pool.submit(export)
        try:
            assert exporting.wait(timeout=5)
            with pytest.raises(TimeoutError):
                export_request.result(timeout=0.1)
        finally:
            release.set()
        assert move.result(timeout=5) == (True, "data_dir_ok")
        response = export_request.result(timeout=5)
    assert response.status_code == 200
    if method != "HEAD":
        assert response.json["ok"]
        assert (target / "exports" / response.json["name"]).is_file()
    assert not list((old / "exports").glob("*.csv"))
    assert len(list((target / "exports").glob("*.csv"))) == 2
