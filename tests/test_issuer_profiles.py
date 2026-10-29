"""Issuer isolation, legacy data compatibility and real PDF/XML round trips."""
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from lxml import html

import app as appmod

YEAR = date.today().year
SELLER = {
    "name": "Freelance Example", "country": "DE", "city": "Berlin",
    "postcode": "10829", "address_line": "Teststr. 1", "vat_id": "DE123456789",
    "email": "example@example.org", "phone": "+493012345678",
    "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
    "bank_name": "Testbank", "account_name": "Freelance Example",
    "last_invoice_number": f"{YEAR}-010",
}
FORM = {
    "number": f"{YEAR}-011", "issue_date": f"{YEAR}-10-01", "due_date": f"{YEAR}-10-15",
    "description": "Design", "quantity": "1", "unit": "C62", "unit_price": "100",
    "tax_treatment": "de_19", "language": "en", "buyer_name": "Example Client",
    "buyer_country": "DE", "buyer_postcode": "10115", "buyer_city": "Berlin",
    "buyer_address_line": "Teststr. 2", "buyer_email": "client@example.org",
    "buyer_reference": "ORDER-1",
}


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
    (root / "seller.json").write_text(json.dumps(SELLER))
    return appmod.app.test_client()


def add_issuer(client, label="Example Company"):
    response = client.post("/issuers/create", data={"profile_label": label})
    assert response.status_code == 302
    issuer = parse_qs(urlparse(response.location).query)["issuer"][0]
    directory = appmod.DATA_DIR / "issuers" / issuer
    return issuer, directory


def number_on_page(client, issuer="default"):
    page = html.fromstring(client.get("/", query_string={"issuer": issuer}).data)
    return page.get_element_by_id("invoice-number").get("value")


@pytest.fixture
def fast_generation(monkeypatch):
    monkeypatch.setattr(appmod, "build_pdf", lambda markup, xml: b"%PDF-test")
    monkeypatch.setattr(appmod, "render_html_pdf", lambda markup: b"%PDF-test")
    monkeypatch.setattr(appmod, "extract_xml_from_pdf", lambda pdf: b"<xml/>")
    monkeypatch.setattr(appmod, "validate_xml_bytes", lambda xml: (True, []))
    monkeypatch.setattr(appmod, "validate_schematron",
                        lambda xml: {"available": True, "ok": True, "errors": [], "warnings": []})


def test_existing_data_is_first_profile_without_rewriting_files(client):
    original = appmod.SELLER_FILE.read_bytes()
    page = html.fromstring(client.get("/").data)
    assert not page.xpath('//*[@id="issuer-select"]')
    assert not page.xpath('//*[@id="issuer-delete-button" or @id="issuer-delete-dialog"]')
    form = page.get_element_by_id("settings-form")
    assert not form.xpath('.//input[@name="profile_label"]')
    assert form.xpath('./div[last()]/button[@id="issuer-add-button"]')
    assert appmod.SELLER_FILE.read_bytes() == original
    assert not (appmod.DATA_DIR / "issuers").exists()


def test_multiple_profiles_show_switcher_and_current_issuer(client):
    issuer, _ = add_issuer(client)
    for selected in ("default", issuer):
        page = html.fromstring(client.get("/", query_string={"issuer": selected}).data)
        select = page.get_element_by_id("issuer-select")
        assert [(o.get("value"), o.text) for o in select.xpath("./option")] == [
            ("default", SELLER["name"]), (issuer, "Example Company"),
        ]
        assert select.xpath("./option[@selected]/@value") == [selected]
        assert page.get_element_by_id("settings-form").xpath('.//input[@name="profile_label"]')
        assert page.get_element_by_id("issuer-delete-button") is not None
        assert page.get_element_by_id("issuer-delete-dialog") is not None
        assert select.xpath('ancestor::summary/parent::details[@id="master-data"]')
        # The selector belongs to its own GET form, never to the settings POST.
        assert select.get("form") == "issuer-switch-form"
        assert not select.xpath("ancestor::form")
        assert page.get_element_by_id("issuer-switch-form").get("method") == "get"
    assert "open" not in html.fromstring(client.get("/").data).get_element_by_id("master-data").attrib
    editing = html.fromstring(client.get("/?edit_issuer=1").data)
    assert "open" in editing.get_element_by_id("master-data").attrib


def test_new_profile_is_blank_and_has_own_number_sequence(client):
    issuer, directory = add_issuer(client)
    assert json.loads((directory / "seller.json").read_text()) == {
        "country": "DE", "profile_label": "Example Company",
    }
    assert number_on_page(client) == f"{YEAR}-011"
    assert number_on_page(client, issuer) == f"{YEAR}-001"
    assert (directory / "output").is_dir()


@pytest.mark.parametrize("delete_default", [False, True])
def test_delete_empty_profile_preserves_other_issuer_and_rejects_stale_tabs(client, delete_default):
    issuer, directory = add_issuer(client)
    company = dict(SELLER, name="Company Example", last_invoice_number=f"{YEAR}-030")
    (directory / "seller.json").write_text(json.dumps(company))
    appmod.CUSTOMERS_FILE.write_text('[{"name":"Shared Client"}]')
    target, survivor = ("default", issuer) if delete_default else (issuer, "default")
    target_file = appmod.SELLER_FILE if delete_default else directory / "seller.json"
    survivor_file = directory / "seller.json" if delete_default else appmod.SELLER_FILE
    original = survivor_file.read_bytes()
    customers = appmod.CUSTOMERS_FILE.read_bytes()
    response = client.post("/issuers/delete", data={"issuer": target, "confirm": "delete"})
    assert response.status_code == 200 and response.json["ok"]
    assert json.loads(target_file.read_text()) == {
        "_deleted": True, "profile_label": SELLER["name"] if delete_default else company["name"],
    }
    assert survivor_file.read_bytes() == original
    assert appmod.CUSTOMERS_FILE.read_bytes() == customers
    page = html.fromstring(client.get(response.json["next_url"]).data)
    assert not page.xpath('//*[@id="issuer-select"]')
    assert not page.xpath('//*[@id="issuer-delete-button" or @id="issuer-delete-dialog"]')
    assert page.get_element_by_id("invoice-form").xpath('./input[@name="issuer"]/@value') == [survivor]
    assert client.get("/").status_code == 200
    assert client.get("/", query_string={"issuer": target}).status_code == 410
    assert client.post("/settings/autosave", data={"issuer": target, "name": "Stale"}).status_code == 410
    assert client.post("/generate", data=dict(FORM, issuer=target)).status_code == 410
    assert survivor_file.read_bytes() == original
    assert number_on_page(client, survivor) == f"{YEAR}-{'031' if delete_default else '011'}"


@pytest.mark.parametrize("extra_profile", [False, True])
def test_deleting_last_profile_opens_fresh_identity_with_blank_master_data(client, extra_profile):
    target = "default"
    if extra_profile:
        target, _ = add_issuer(client)
        assert client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"}).status_code == 200
    response = client.post("/issuers/delete", data={"issuer": target, "confirm": "delete"})
    assert response.status_code == 200
    fresh = parse_qs(urlparse(response.json["next_url"]).query)["issuer"][0]
    assert fresh not in {target, "default"}
    saved = appmod.DATA_DIR / "issuers" / fresh / "seller.json"
    assert json.loads(saved.read_text()) == {"country": "DE"}
    page = html.fromstring(client.get("/").data)
    assert not page.xpath('//*[@id="issuer-select"]')
    assert "open" in page.get_element_by_id("master-data").attrib
    assert page.get_element_by_id("invoice-number").get("value") == f"{YEAR}-001"
    assert client.post("/settings/autosave", data={"issuer": target, "name": "Stale"}).status_code == 410
    assert json.loads(saved.read_text()) == {"country": "DE"}


@pytest.mark.parametrize("delete_default", [False, True])
@pytest.mark.parametrize("filename", ["invoice.pdf", "invoice.xml", "invoice.json"])
def test_deleting_profile_preserves_every_archive_file(client, delete_default, filename):
    issuer, directory = add_issuer(client)
    selected = "default" if delete_default else issuer
    seller = appmod.SELLER_FILE if delete_default else directory / "seller.json"
    archive = appmod.OUTPUT_DIR if delete_default else directory / "output"
    (archive / filename).write_bytes(b"Original invoice data")
    response = client.post("/issuers/delete", data={"issuer": selected, "confirm": "delete"})
    assert response.status_code == 200 and response.json["ok"]
    assert json.loads(seller.read_text())["_deleted"] is True
    assert (archive / filename).read_bytes() == b"Original invoice data"
    # Even a legacy archive with only XML/sidecar data stays discoverable.
    page = html.fromstring(client.get("/settings/panel").data)
    assert page.xpath(f'//select[@id="archive-issuer-select"]/option[@value="{selected}"]')


def test_delete_preserves_invoice_created_after_dialog_was_opened(client):
    add_issuer(client)
    page = html.fromstring(client.get("/").data)
    assert page.get_element_by_id("issuer-delete-confirm") is not None
    (appmod.OUTPUT_DIR / "new.pdf").write_bytes(b"Created in another window")
    response = client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"})
    assert response.status_code == 200
    assert client.get("/download/new.pdf?issuer=default").data == b"Created in another window"


def test_deletion_requires_explicit_confirmation_and_matching_issuer(client):
    issuer, _ = add_issuer(client)
    assert client.get("/issuers/delete").status_code == 405
    for fields in ({}, {"issuer": "default"}, {"confirm": "delete"}):
        assert client.post("/issuers/delete", data=fields).status_code == 400
    assert client.post(f"/issuers/delete?issuer={issuer}", data={
        "issuer": "default", "confirm": "delete",
    }).status_code == 400
    assert appmod.load_seller() == SELLER


def test_deleted_profiles_stay_deleted_when_data_folder_is_moved(client, tmp_path):
    issuer, _ = add_issuer(client)
    assert client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"}).status_code == 200
    assert appmod.set_data_dir(str(tmp_path / "moved"))[0]
    assert client.get("/?issuer=default").status_code == 410
    page = html.fromstring(client.get("/").data)
    assert page.get_element_by_id("invoice-form").xpath('./input[@name="issuer"]/@value') == [issuer]


@pytest.mark.parametrize("retire_default", [False, True])
def test_retired_issuer_archive_is_accessible_but_cannot_issue_or_edit(client, fast_generation, monkeypatch, retire_default):
    issuer, directory = add_issuer(client)
    client.post("/settings", data=dict(SELLER, issuer=issuer, name="Company Example"))
    target = "default" if retire_default else issuer
    survivor = issuer if retire_default else "default"
    archive = appmod.OUTPUT_DIR if retire_default else directory / "output"
    assert client.post("/generate", data=dict(FORM, issuer=target, profile="xrechnung")).status_code == 200
    before = {p.name: p.read_bytes() for p in archive.iterdir()}
    filename = f"Rechnung_{YEAR}-011.pdf"
    assert client.post("/issuers/delete", data={"issuer": target, "confirm": "delete"}).json["ok"]
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before
    for route in ("view", "download", "archive/preview"):
        assert client.get(f"/{route}/{filename}?issuer={target}").data == before[filename]
    assert client.get(f"/download/{filename[:-4]}.xml?issuer={target}").data == before[filename[:-4] + ".xml"]
    assert client.get(f"/download-zip/{filename}?issuer={target}").status_code == 200
    assert "Example Client" in client.get(f"/export/csv?issuer={target}").get_data(as_text=True)
    monkeypatch.setattr(appmod, "reveal_in_finder", lambda path: path.parent == archive)
    assert client.post(f"/reveal/{filename}?issuer={target}").json["ok"]
    assert client.post(f"/settings/panel?issuer={target}", data={"filename": filename[:-4] + ".xml"}).status_code == 200
    monkeypatch.setattr(appmod, "drafthorse_version_info", lambda: {})
    page = html.fromstring(client.get(f"/validate?issuer={target}").data)
    back = page.xpath('//p[@class="back-link"]/a/@href')[0]
    assert parse_qs(urlparse(back).query)["issuer"] == [survivor]
    assert client.get(back).status_code == 200
    assert not page.xpath('//*[@class="js-delete danger-item"]')
    assert not page.xpath('//a[contains(@href, "from=Rechnung")]')
    active = html.fromstring(client.get("/").data)
    assert active.get_element_by_id("invoice-form").xpath('./input[@name="issuer"]/@value') == [survivor]
    for route in ("settings", "settings/autosave", "generate", "preview-html", "issuers/default", "archive/delete"):
        assert client.post(f"/{route}", data=dict(FORM, issuer=target, filename=filename)).status_code == 410
    assert client.get(f"/?issuer={target}&from={filename}").status_code == 410
    assert {p.name: p.read_bytes() for p in archive.iterdir()} == before


def test_default_issuer_persists_without_changing_open_forms_or_numbering(client):
    issuer, directory = add_issuer(client)
    saved = appmod.SELLER_FILE.read_bytes(), (directory / "seller.json").read_bytes()
    assert client.post("/issuers/default", data={"issuer": issuer}).json == {"ok": True}
    # A fresh session uses the preference, but an explicit URL keeps its issuer.
    fresh = appmod.app.test_client()
    page = html.fromstring(fresh.get("/").data)
    assert page.get_element_by_id("invoice-form").xpath('./input[@name="issuer"]/@value') == [issuer]
    assert "disabled" in page.get_element_by_id("issuer-default-button").attrib
    legacy = html.fromstring(fresh.get("/?issuer=default").data)
    assert legacy.get_element_by_id("issuer-select").xpath('./option[@selected]/@value') == ["default"]
    assert "disabled" not in legacy.get_element_by_id("issuer-default-button").attrib
    assert legacy.get_element_by_id("settings-form").get("action") == "/settings?issuer=default"
    assert saved == (appmod.SELLER_FILE.read_bytes(), (directory / "seller.json").read_bytes())
    assert client.post("/settings/autosave", data={"issuer": "default", "name": "Still freelance"}).status_code == 204
    assert json.loads((directory / "seller.json").read_text())["profile_label"] == "Example Company"
    assert number_on_page(client) == f"{YEAR}-011"
    assert number_on_page(client, issuer) == f"{YEAR}-001"


def test_default_change_cannot_retarget_existing_legacy_archive_links(client):
    issuer, directory = add_issuer(client)
    filename = "same.pdf"
    (appmod.OUTPUT_DIR / filename).write_bytes(b"Legacy original")
    (directory / "output" / filename).write_bytes(b"Company original")
    page = html.fromstring(client.get("/settings/panel?issuer=default").data)
    view = page.xpath('//tr[@class="arch-row"]/@data-preview-url')[0]
    delete = page.xpath('//button[contains(@class, "js-delete")]/@data-url')[0]
    export = page.get_element_by_id("export-csv").get("data-url")
    assert client.post("/issuers/default", data={"issuer": issuer}).json["ok"]
    assert client.get(view).data == b"Legacy original"
    assert parse_qs(urlparse(export).query)["issuer"] == ["default"]
    assert client.post(delete, data={"filename": filename}).status_code == 302
    assert not (appmod.OUTPUT_DIR / filename).exists()
    assert (directory / "output" / filename).read_bytes() == b"Company original"


def test_deleting_selected_default_falls_back_to_surviving_profile(client):
    issuer, _ = add_issuer(client)
    assert client.post("/issuers/default", data={"issuer": issuer}).json["ok"]
    response = client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"})
    assert parse_qs(urlparse(response.json["next_url"]).query)["issuer"] == ["default"]
    page = html.fromstring(client.get("/").data)
    assert not page.xpath('//*[@id="issuer-default-button"]')
    assert page.get_element_by_id("invoice-form").xpath('./input[@name="issuer"]/@value') == ["default"]


def test_default_and_retired_archive_survive_data_folder_move(client, tmp_path):
    issuer, _ = add_issuer(client)
    assert client.post("/issuers/default", data={"issuer": issuer}).json["ok"]
    (appmod.OUTPUT_DIR / "original.pdf").write_bytes(b"Original")
    assert client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"}).json["ok"]
    old = appmod.DATA_DIR
    assert appmod.set_data_dir(str(tmp_path / "moved"))[0]
    assert not (old / "issuer_preferences.json").exists()
    page = html.fromstring(client.get("/").data)
    assert page.get_element_by_id("invoice-form").xpath('./input[@name="issuer"]/@value') == [issuer]
    assert client.get("/download/original.pdf?issuer=default").data == b"Original"


@pytest.mark.parametrize("conflict", ["seller.json", "issuer_preferences.json"])
def test_move_rejects_conflicting_legacy_identity_or_default(client, tmp_path, conflict):
    issuer, _ = add_issuer(client)
    assert client.post("/issuers/default", data={"issuer": issuer}).json["ok"]
    old = appmod.DATA_DIR
    original = (old / conflict).read_bytes()
    target = tmp_path / "conflicting"
    target.mkdir()
    (target / conflict).write_text('{"different": true}')
    assert appmod.set_data_dir(str(target)) == (False, "issuer_move_conflict")
    assert appmod.DATA_DIR == old
    assert (old / conflict).read_bytes() == original
    assert (target / conflict).read_text() == '{"different": true}'


def test_failed_default_save_preserves_previous_preference(client, monkeypatch):
    issuer, _ = add_issuer(client)
    assert client.post("/issuers/default", data={"issuer": "default"}).json["ok"]
    before = (appmod.DATA_DIR / "issuer_preferences.json").read_bytes()
    def fail(*args):
        raise OSError("read only")
    monkeypatch.setattr(appmod, "_write_json", fail)
    assert client.post("/issuers/default", data={"issuer": issuer}).status_code == 503
    assert (appmod.DATA_DIR / "issuer_preferences.json").read_bytes() == before
    assert client.post("/issuers/default", data={}).status_code == 400
    assert client.post(f"/issuers/default?issuer={issuer}", data={"issuer": "default"}).status_code == 400


def test_tabs_save_to_explicit_profiles_and_share_customers(client):
    issuer, directory = add_issuer(client)
    other = appmod.app.test_client()
    other.get(f"/?issuer={issuer}")
    assert client.post("/settings/autosave", data={"issuer": "default", "name": "Freelance New"}).status_code == 204
    assert other.post(f"/settings/autosave?issuer={issuer}", data={
        "issuer": issuer, "name": "Company New", "iban": "COMPANY", "profile_label": "Business",
    }).status_code == 204
    assert appmod.load_seller()["name"] == "Freelance New"
    assert appmod.load_seller()["iban"] == SELLER["iban"]
    saved = json.loads((directory / "seller.json").read_text())
    assert saved["name"] == "Company New" and saved["iban"] == "COMPANY"
    assert other.post(f"/customers/autosave?issuer={issuer}", data={"buyer_name": "Shared Client"}).status_code == 200
    assert "Shared Client" in client.get("/").get_data(as_text=True)
    assert appmod.OUTPUT_DIR == appmod.DATA_DIR / "output"


@pytest.mark.parametrize("issuer,code", [("../outside", 400), ("", 400), ("a" * 32, 404)])
def test_invalid_profile_never_falls_back_to_default(client, issuer, code):
    before = appmod.SELLER_FILE.read_bytes()
    assert client.post("/settings/autosave", data={"issuer": issuer, "name": "Wrong"}).status_code == code
    assert appmod.SELLER_FILE.read_bytes() == before


def test_conflicting_form_and_url_profile_is_rejected(client):
    issuer, directory = add_issuer(client)
    before = (directory / "seller.json").read_bytes()
    response = client.post(f"/settings/autosave?issuer={issuer}", data={"issuer": "default", "name": "Wrong"})
    assert response.status_code == 400
    assert (directory / "seller.json").read_bytes() == before


def test_linked_profile_cannot_access_other_directory(client, tmp_path):
    root = appmod.DATA_DIR / "issuers"
    root.mkdir()
    (root / ("a" * 32)).symlink_to(tmp_path, target_is_directory=True)
    assert client.get("/?issuer=" + "a" * 32).status_code == 404


def test_same_number_in_two_profiles_has_independent_files_and_counters(client, fast_generation):
    issuer, directory = add_issuer(client)
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example"))
    for selected in ("default", issuer):
        assert client.post("/generate", data=dict(FORM, issuer=selected)).status_code == 200
    filename = f"Rechnung_{YEAR}-011.pdf"
    assert (appmod.OUTPUT_DIR / filename).exists() and (directory / "output" / filename).exists()
    assert number_on_page(client) == number_on_page(client, issuer) == f"{YEAR}-012"
    assert client.post("/generate", data=dict(FORM, issuer=issuer, number=f"{YEAR}-020")).status_code == 200
    assert number_on_page(client) == f"{YEAR}-012"
    assert number_on_page(client, issuer) == f"{YEAR}-021"
    # Issuing an older number must not roll this issuer's sequence backwards.
    client.post("/generate", data=dict(FORM, issuer=issuer, number=f"{YEAR}-003"))
    assert json.loads((directory / "seller.json").read_text())["last_invoice_number"] == f"{YEAR}-020"
    assert number_on_page(client, issuer) == f"{YEAR}-021"


def test_parallel_requests_keep_issuer_and_counter_together(client, fast_generation):
    from concurrent.futures import ThreadPoolExecutor

    issuer, directory = add_issuer(client)
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example"))

    def generate(selected, number):
        with appmod.app.test_client() as c:
            return c.post("/generate", data=dict(FORM, issuer=selected, number=number)).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(generate, selected, f"{YEAR}-{n:03d}")
                   for selected in ("default", issuer) for n in (11, 12, 13)]
        assert all(f.result() == 200 for f in futures)
    for folder, name in [(appmod.OUTPUT_DIR, SELLER["name"]), (directory / "output", "Company Example")]:
        sidecars = list(folder.glob("*.json"))
        assert len(sidecars) == 3
        assert all(json.loads(p.read_text())["seller"]["name"] == name for p in sidecars)
    assert number_on_page(client) == number_on_page(client, issuer) == f"{YEAR}-014"


def test_archive_preview_download_csv_template_and_delete_are_scoped(client, fast_generation, monkeypatch):
    issuer, directory = add_issuer(client)
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example"))
    for selected, buyer in [("default", "Private Client"), (issuer, "Company Client")]:
        client.post("/generate", data=dict(FORM, issuer=selected, buyer_name=buyer, profile="xrechnung"))
    filename = f"Rechnung_{YEAR}-011.pdf"
    (directory / "output" / filename).write_bytes(b"%PDF-company-original")
    assert client.get(f"/archive/preview/{filename}?issuer={issuer}").data == b"%PDF-company-original"
    assert client.get(f"/download/{filename}?issuer={issuer}").data == b"%PDF-company-original"
    page = html.fromstring(client.get(f"/settings/panel?issuer={issuer}").data)
    for url in page.xpath('//*[@data-preview-url]/@data-preview-url | //a/@href'):
        if url.startswith(("/view/", "/download/", "/archive/", "/?", "/export/")):
            assert parse_qs(urlparse(url).query)["issuer"] == [issuer]
    assert "Company Client" in page.text_content() and "Private Client" not in page.text_content()
    csv = client.get(f"/export/csv?issuer={issuer}&from={YEAR}-01-01").get_data(as_text=True)
    assert "Company Client" in csv and "Private Client" not in csv
    template_page = client.get(f"/?issuer={issuer}&from={filename}").get_data(as_text=True)
    assert '"issuer_id": "' + issuer + '"' in template_page
    assert '"name": "Company Example"' in template_page
    paths = []
    monkeypatch.setattr(appmod, "reveal_in_finder", lambda path: paths.append(path) or True)
    client.post(f"/reveal/{filename}?issuer={issuer}")
    assert paths == [directory / "output" / filename]
    assert client.get(f"/download-zip/{filename}?issuer={issuer}").status_code == 200
    client.post(f"/archive/delete?issuer={issuer}", data={"filename": filename})
    assert not (directory / "output" / filename).exists()
    assert not (directory / "output" / filename.replace(".pdf", ".xml")).exists()
    assert (appmod.OUTPUT_DIR / filename).exists()


def test_number_conflict_warning_uses_only_selected_archive(client):
    issuer, directory = add_issuer(client)
    (directory / "output" / f"Rechnung_{YEAR}-030.pdf").write_bytes(b"%PDF-test")
    assert f'{YEAR}-030' in client.get(f"/?issuer={issuer}").get_data(as_text=True)
    assert f'{YEAR}-030' not in client.get("/").get_data(as_text=True)
    assert number_on_page(client) == f"{YEAR}-011"


def test_move_data_folder_keeps_all_profiles_including_empty_archives(client, tmp_path):
    issuer, directory = add_issuer(client)
    second, _ = add_issuer(client, "Empty profile")
    (directory / "output" / "example.pdf").write_bytes(b"%PDF-original")
    old = appmod.DATA_DIR
    target = tmp_path / "moved"
    response = client.post(f"/data-dir?issuer={issuer}", data={"data_dir": str(target)})
    assert response.status_code == 302
    assert appmod.DATA_DIR == target
    assert (target / "issuers" / issuer / "output" / "example.pdf").read_bytes() == b"%PDF-original"
    assert (target / "issuers" / second / "output").is_dir()
    assert client.get(f"/?issuer={issuer}").status_code == 200
    assert number_on_page(client, second) == f"{YEAR}-001"
    assert not (old / "issuers" / issuer / "seller.json").exists()


def test_profile_folder_cannot_become_data_root(client):
    issuer, directory = add_issuer(client)
    before = appmod.DATA_DIR
    assert appmod.set_data_dir(str(directory)) == (False, "data_dir_err_nested")
    assert appmod.DATA_DIR == before


def test_move_conflict_preserves_complete_source_profile(client, tmp_path):
    issuer, directory = add_issuer(client)
    (directory / "output" / "example.pdf").write_bytes(b"%PDF-source")
    target = tmp_path / "conflicting"
    (target / "issuers" / issuer / "output").mkdir(parents=True)
    (target / "issuers" / issuer / "seller.json").write_bytes((directory / "seller.json").read_bytes())
    (target / "issuers" / issuer / "output" / "example.pdf").write_bytes(b"%PDF-different")
    before = appmod.DATA_DIR
    assert appmod.set_data_dir(str(target)) == (False, "issuer_move_conflict")
    assert appmod.DATA_DIR == before
    appmod._drop_identical(before, target)
    assert (directory / "seller.json").exists()
    assert (directory / "output" / "example.pdf").read_bytes() == b"%PDF-source"


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
def test_real_pdf_and_xml_use_selected_issuer_and_preserve_original(client, profile):
    import io

    from pypdf import PdfReader

    issuer, directory = add_issuer(client)
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example", account_name="Company Account"))
    response = client.post("/generate", data=dict(FORM, issuer=issuer, profile=profile))
    assert response.status_code == 200
    assert "Validierung bestanden" in response.get_data(as_text=True)
    file = directory / "output" / f"Rechnung_{YEAR}-011.pdf"
    pdf = file.read_bytes()
    xml = (file.with_suffix(".xml").read_bytes() if profile == "xrechnung"
           else appmod.extract_xml_from_pdf(pdf))
    assert b"Company Example" in xml and b"Company Account" in xml
    assert b"Freelance Example" not in xml
    assert "Company Example" in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert appmod.load_seller()["last_invoice_number"] == SELLER["last_invoice_number"]
    client.post(f"/settings?issuer={issuer}", data={"name": "Company Renamed"})
    assert client.get(f"/archive/preview/{file.name}?issuer={issuer}").data == pdf
