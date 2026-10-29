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


def revision(client, issuer="default"):
    page = html.fromstring(client.get("/", query_string={"issuer": issuer}).data)
    return page.xpath('//input[@name="seller_revision"]/@value')[0]


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
    assert json.loads(target_file.read_text()) == dict(SELLER if delete_default else company,
        _deleted=True, profile_label=SELLER["name"] if delete_default else company["name"])
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
    client.post("/settings", data=dict(SELLER, issuer=issuer, name="Company Example", seller_revision=revision(client, issuer)))
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
    assert client.post("/settings/autosave", data={"issuer": "default", "name": "Still freelance", "seller_revision": revision(client)}).status_code == 204
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
    assert client.post("/settings/autosave", data={"issuer": "default", "name": "Freelance New", "seller_revision": revision(client)}).status_code == 204
    assert other.post(f"/settings/autosave?issuer={issuer}", data={
        "issuer": issuer, "name": "Company New", "iban": "COMPANY", "profile_label": "Business",
        "seller_revision": revision(other, issuer),
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
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example", seller_revision=revision(client, issuer)))
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
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example", seller_revision=revision(client, issuer)))

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
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example", seller_revision=revision(client, issuer)))
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


@pytest.mark.parametrize("legacy", [False, True])
def test_move_conflict_preserves_complete_source_profile(client, tmp_path, legacy):
    _, directory = add_issuer(client)
    if legacy:
        directory = appmod.DATA_DIR
    (directory / "output" / "example.pdf").write_bytes(b"%PDF-source")
    target = tmp_path / "conflicting"
    destination = target / directory.relative_to(appmod.DATA_DIR)
    (destination / "output").mkdir(parents=True)
    (destination / "seller.json").write_bytes((directory / "seller.json").read_bytes())
    (destination / "output" / "example.pdf").write_bytes(b"%PDF-different")
    before = appmod.DATA_DIR
    assert appmod.set_data_dir(str(target)) == (False, "issuer_move_conflict")
    assert appmod.DATA_DIR == before
    appmod._drop_identical(before, target)
    assert (directory / "seller.json").exists()
    assert (directory / "output" / "example.pdf").read_bytes() == b"%PDF-source"


@pytest.mark.parametrize("legacy", [False, True])
def test_cleanup_keeps_profile_together_until_every_file_is_copied(client, tmp_path, legacy):
    _, directory = add_issuer(client)
    if legacy:
        directory = appmod.DATA_DIR
    (directory / "output" / "example.pdf").write_bytes(b"%PDF-source")
    target = tmp_path / "partial-copy"
    destination = target / directory.relative_to(appmod.DATA_DIR)
    destination.mkdir(parents=True)
    (destination / "seller.json").write_bytes((directory / "seller.json").read_bytes())
    appmod._drop_identical(appmod.DATA_DIR, target)
    assert (directory / "seller.json").exists()
    assert (directory / "output" / "example.pdf").read_bytes() == b"%PDF-source"


def test_failed_data_copy_leaves_source_and_config_unchanged(client, tmp_path, monkeypatch):
    import shutil

    add_issuer(client)
    old = appmod.DATA_DIR
    before = {p: p.read_bytes() for p in old.rglob("*") if p.is_file()}
    copy = shutil.copy2
    def fail(src, dst):
        if "issuers" in src.parts:
            raise OSError("disk full")
        return copy(src, dst)
    monkeypatch.setattr(shutil, "copy2", fail)
    assert appmod.set_data_dir(str(tmp_path / "full")) == (False, "data_dir_err_write")
    assert (tmp_path / "full" / "seller.json").exists()
    assert appmod.DATA_DIR == old
    assert not appmod.CONFIG_FILE.exists()
    assert all(p.read_bytes() == contents for p, contents in before.items())


@pytest.mark.parametrize("legacy", [False, True])
def test_move_never_copies_into_linked_archive(client, tmp_path, legacy):
    _, directory = add_issuer(client)
    if legacy:
        directory = appmod.DATA_DIR
    (directory / "output" / "example.pdf").write_bytes(b"%PDF-source")
    target = tmp_path / "linked"
    destination = target / directory.relative_to(appmod.DATA_DIR)
    destination.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    (destination / "output").symlink_to(external, target_is_directory=True)
    before = appmod.DATA_DIR
    assert appmod.set_data_dir(str(target)) == (False, "data_dir_err_write")
    assert appmod.DATA_DIR == before
    assert list(external.iterdir()) == []
    assert (directory / "output" / "example.pdf").read_bytes() == b"%PDF-source"


def test_inplace_data_move_reports_conflicts_and_refreshes_draft_scope(client, tmp_path):
    target = tmp_path / "destination"
    target.mkdir()
    (target / "seller.json").write_text('{"name": "Other issuer"}')
    old_scope = appmod.issuer_scope()
    response = client.post("/data-dir?issuer=default", data={"data_dir": str(target)},
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200
    assert not response.json["ok"]
    assert "abweichende Kopie" in response.json["message"]
    assert response.json["issuer_scope"] == old_scope
    response = client.post("/data-dir?issuer=default", data={"data_dir": str(tmp_path / "empty")},
                           headers={"X-Requested-With": "fetch"})
    assert response.json["ok"]
    assert response.json["issuer_scope"] == appmod.issuer_scope() != old_scope


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
def test_real_pdf_and_xml_use_selected_issuer_and_preserve_original(client, profile):
    import io

    from pypdf import PdfReader

    issuer, directory = add_issuer(client)
    client.post(f"/settings?issuer={issuer}", data=dict(SELLER, name="Company Example", account_name="Company Account", seller_revision=revision(client, issuer)))
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
    client.post(f"/settings?issuer={issuer}", data={"name": "Company Renamed", "seller_revision": revision(client, issuer)})
    assert client.get(f"/archive/preview/{file.name}?issuer={issuer}").data == pdf


@pytest.mark.parametrize("endpoint", ["settings", "settings/autosave"])
@pytest.mark.parametrize("extra_profile", [False, True])
def test_stale_master_data_is_rejected_without_losing_newer_changes(client, endpoint, extra_profile):
    issuer, directory = add_issuer(client) if extra_profile else ("default", appmod.DATA_DIR)
    token = revision(client, issuer)
    first = client.post(f"/{endpoint}?issuer={issuer}", data={
        "seller_revision": token, "address_line": "New address", "name": "Updated studio",
    })
    assert first.status_code in (204, 302)
    saved = (directory / "seller.json").read_bytes()
    stale = client.post(f"/{endpoint}?issuer={issuer}", data={
        "seller_revision": token, "address_line": "Old address", "name": "Old studio",
    })
    assert stale.status_code == 409 and not stale.json["ok"]
    assert (directory / "seller.json").read_bytes() == saved
    assert client.post(f"/{endpoint}?issuer={issuer}", data={"name": "No revision"}).status_code == 409
    assert (directory / "seller.json").read_bytes() == saved
    current = revision(client, issuer)
    assert current != token
    assert client.post(f"/{endpoint}?issuer={issuer}", data={
        "seller_revision": current, "address_line": "Latest address",
    }).status_code in (204, 302)


def test_simultaneous_master_writes_cannot_both_accept_the_same_revision(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    token = revision(client)
    ready = Barrier(2)
    def save(name):
        with appmod.app.test_client() as tab:
            ready.wait(timeout=5)
            return tab.post("/settings/autosave?issuer=default", data={
                "seller_revision": token, "name": name,
            }).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["Window A", "Window B"])) == [204, 409]


def test_invoice_counter_does_not_invalidate_master_data_revision(client, fast_generation):
    token = revision(client)
    assert client.post("/generate", data=FORM).status_code == 200
    response = client.post("/settings/autosave?issuer=default", data={
        "seller_revision": token, "address_line": "New address",
    })
    assert response.status_code == 204
    assert response.headers["X-Seller-Revision"] != token
    assert appmod.load_seller()["last_invoice_number"] == FORM["number"]


def test_identical_save_from_an_old_tab_is_harmless(client):
    fields = dict(SELLER, seller_revision=revision(client))
    first = client.post("/settings/autosave?issuer=default", data=fields)
    assert first.status_code == 204
    saved = appmod.SELLER_FILE.read_bytes()
    second = client.post("/settings/autosave?issuer=default", data=fields)
    assert second.status_code == 204
    assert second.headers["X-Seller-Revision"] == first.headers["X-Seller-Revision"]
    assert appmod.SELLER_FILE.read_bytes() == saved


@pytest.mark.parametrize("legacy_marker", [False, True])
@pytest.mark.parametrize("kind", ["381", "384"])
def test_retired_issuer_can_issue_linked_adjustment_only(client, fast_generation, kind, legacy_marker):
    issuer, directory = add_issuer(client)
    (directory / "seller.json").write_text(json.dumps(dict(SELLER, name="Retired Company")))
    assert client.post("/generate", data=dict(FORM, issuer=issuer)).status_code == 200
    source = f"Rechnung_{FORM['number']}.pdf"
    before = {p.name: p.read_bytes() for p in (directory / "output").iterdir()}
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    if legacy_marker:
        (directory / "seller.json").write_text(json.dumps({"_deleted": True, "profile_label": "Retired Company"}))
    original_seller = (directory / "seller.json").read_bytes()
    query = {"issuer": issuer, "correction_source": source, "doc_type": kind}
    page = html.fromstring(client.get("/", query_string=query).data)
    assert not page.xpath('//*[@id="issuer-select" or @id="issuer-add-button" or @id="issuer-default-button"]')
    assert page.xpath('//*[@id="settings-form"]/fieldset[@disabled]')
    assert page.xpath('//*[@id="doc_type"]/option/@value') == ["381", "384"]
    assert page.xpath('//*[@id="doc_type"]/option[@selected]/@value') == [kind]
    assert page.xpath('//input[@name="ref_number"]/@value') == [FORM["number"]]
    assert page.xpath('//input[@name="correction_source"]/@value') == [source]
    assert page.get_element_by_id("invoice-number").get("value") == f"{YEAR}-012"
    fields = dict(FORM, **query, number=f"{YEAR}-012", ref_number="FORGED", ref_date="2000-01-01")
    assert client.post("/preview-html", data=fields).status_code == 200
    for forbidden in ("380", "386", "other", ""):
        assert client.post("/generate", data=dict(fields, doc_type=forbidden)).status_code == 410
    assert client.post("/settings/autosave", query_string=query, data={"name": "Changed"}).status_code == 410
    assert client.post("/generate", data=fields).status_code == 200
    adjustment = json.loads((directory / "output" / f"Rechnung_{YEAR}-012.json").read_text())
    assert adjustment["issuer_id"] == issuer
    assert adjustment["seller"]["name"] == "Retired Company"
    assert adjustment["invoice"]["doc_type"] == kind
    assert adjustment["invoice"]["ref_number"] == FORM["number"]
    assert adjustment["invoice"]["ref_date"] == FORM["issue_date"]
    assert all((directory / "output" / name).read_bytes() == data for name, data in before.items())
    stored = json.loads((directory / "seller.json").read_text())
    assert stored.pop("last_invoice_number") == f"{YEAR}-012"
    prior = json.loads(original_seller)
    prior.pop("last_invoice_number", None)
    assert stored == prior
    assert client.get("/", query_string={"issuer": issuer}).status_code == 410
    archive = html.fromstring(client.get("/settings/panel", query_string={"issuer": issuer}).data)
    assert archive.xpath('//a[contains(@href, "correction_source=") and contains(@href, "doc_type=381")]')
    active = html.fromstring(client.get("/").data)
    assert not active.xpath(f'//option[@value="{issuer}"]')


def test_retired_adjustments_reject_missing_foreign_or_invalid_originals(client, fast_generation):
    issuer, directory = add_issuer(client)
    source = f"Rechnung_{FORM['number']}.pdf"
    assert client.post("/generate", data=FORM).status_code == 200
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    for name in (source, "../output/" + source, "missing.pdf", "example.xml"):
        assert client.get("/", query_string={"issuer": issuer, "correction_source": name, "doc_type": "381"}).status_code == 410
    for p in appmod.OUTPUT_DIR.iterdir():
        (directory / "output" / p.name).write_bytes(p.read_bytes())
    # Even a copied invoice with the other issuer's explicit identity is rejected.
    assert client.get("/", query_string={"issuer": issuer, "correction_source": source, "doc_type": "381"}).status_code == 410


@pytest.mark.parametrize("kind", ["381", "384"])
def test_retired_adjustment_uses_verified_kind_when_it_is_only_in_url(client, fast_generation, kind):
    add_issuer(client)
    client.post("/generate", data=FORM)
    client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"})
    query = {"issuer": "default", "correction_source": f"Rechnung_{FORM['number']}.pdf", "doc_type": kind}
    # Like customer actions, a request may carry its correction context in the URL.
    response = client.post("/generate", query_string=query, data=dict(FORM, number=f"{YEAR}-012"))
    assert response.status_code == 200
    adjustment = json.loads((appmod.OUTPUT_DIR / f"Rechnung_{YEAR}-012.json").read_text())
    assert adjustment["invoice"]["doc_type"] == kind
    assert adjustment["invoice"]["ref_number"] == FORM["number"]


@pytest.mark.parametrize("kind,profile", [("381", "en16931"), ("384", "xrechnung")])
def test_real_adjustment_for_retired_issuer_validates(client, kind, profile):
    add_issuer(client)
    assert client.post("/generate", data=FORM).status_code == 200
    original = appmod.OUTPUT_DIR / f"Rechnung_{FORM['number']}.pdf"
    before = original.read_bytes()
    assert client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"}).json["ok"]
    response = client.post("/generate", data=dict(FORM, issuer="default", doc_type=kind, profile=profile,
                           correction_source=original.name, number=f"{YEAR}-012"))
    assert response.status_code == 200 and "Validierung bestanden" in response.get_data(as_text=True)
    assert original.read_bytes() == before


@pytest.mark.parametrize("extra_profile", [False, True])
def test_address_and_name_changes_keep_identity_numbering_and_originals(client, fast_generation, extra_profile):
    issuer, folder = add_issuer(client) if extra_profile else ("default", appmod.DATA_DIR)
    (folder / "seller.json").write_text(json.dumps(SELLER))
    assert client.post("/generate", data=dict(FORM, issuer=issuer)).status_code == 200
    originals = {p.name: p.read_bytes() for p in (folder / "output").iterdir()}
    token = revision(client, issuer)
    assert client.post("/settings/autosave", data={"issuer": issuer, "seller_revision": token,
        "name": "Updated Studio", "address_line": "New address 42"}).status_code == 204
    assert number_on_page(client, issuer) == f"{YEAR}-012"
    assert client.post("/generate", data=dict(FORM, issuer=issuer, number=f"{YEAR}-012")).status_code == 200
    new = json.loads((folder / "output" / f"Rechnung_{YEAR}-012.json").read_text())
    assert new["issuer_id"] == issuer
    assert new["seller"]["name"] == "Updated Studio"
    assert new["seller"]["address_line"] == "New address 42"
    assert all((folder / "output" / name).read_bytes() == data for name, data in originals.items())


@pytest.mark.parametrize("restore_default", [False, True])
def test_restore_keeps_identity_archive_numbering_and_startup_default(client, fast_generation, restore_default):
    other, folder = add_issuer(client)
    issuer, folder = ("default", appmod.DATA_DIR) if restore_default else (other, folder)
    (folder / "seller.json").write_text(json.dumps(dict(SELLER, profile_label=SELLER["name"])))
    assert client.post("/issuers/default", data={"issuer": issuer}).json["ok"]
    assert client.post("/generate", data=dict(FORM, issuer=issuer)).status_code == 200
    source = f"Rechnung_{FORM['number']}.pdf"
    old_token = revision(client, issuer)
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    assert client.post("/generate", data=dict(FORM, issuer=issuer, doc_type="381", correction_source=source,
                       number=f"{YEAR}-012")).status_code == 200
    originals = {p.name: p.read_bytes() for p in (folder / "output").iterdir()}
    startup = other if restore_default else "default"
    body = {"issuer": issuer, "confirm": "restore"}
    response = client.post("/issuers/restore", data=body)
    assert response.status_code == 302
    assert parse_qs(urlparse(response.location).query)["issuer"] == [issuer]
    seller = json.loads((folder / "seller.json").read_text())
    assert "_deleted" not in seller
    assert seller["address_line"] == SELLER["address_line"]
    assert seller["last_invoice_number"] == f"{YEAR}-012"
    assert number_on_page(client, issuer) == f"{YEAR}-013"
    assert all((folder / "output" / name).read_bytes() == data for name, data in originals.items())
    page = html.fromstring(client.get("/").data)
    assert page.xpath('//*[@id="issuer-select"]/option[@selected]/@value') == [startup]
    # A retry is idempotent; an old tab must not regain write access after restoring.
    assert client.post("/issuers/restore", data=body).status_code == 302
    assert json.loads((folder / "seller.json").read_text()) == seller
    assert client.post("/settings/autosave", data={"issuer": issuer, "seller_revision": old_token,
                       "address_line": "Stale overwrite"}).status_code == 409


def test_restore_empty_profile_is_discoverable_and_does_not_create_another_identity(client):
    issuer, folder = add_issuer(client, "Empty issuer")
    client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"})
    page = html.fromstring(client.get("/").data)
    assert page.xpath(f'//*[@id="issuer-create-dialog"]//form[contains(@class,"issuer-restore-form")]/input[@name="issuer" and @value="{issuer}"]')
    archive = html.fromstring(client.get("/settings/panel").data)
    assert archive.xpath(f'//*[@id="archive-issuer-select"]/option[@value="{issuer}"]')
    retired = html.fromstring(client.get("/settings/panel", query_string={"issuer": issuer}).data)
    assert retired.xpath('//form[contains(@class,"issuer-restore-form")]')
    assert client.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code == 302
    assert number_on_page(client, issuer) == f"{YEAR}-001"
    assert list((appmod.DATA_DIR / "issuers").iterdir()) == [folder]


@pytest.mark.parametrize("legacy_marker", [False, True])
def test_restore_uses_archive_when_counter_is_missing_or_stale(client, fast_generation, legacy_marker):
    add_issuer(client)
    client.post("/generate", data=FORM)
    client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"})
    seller = {"_deleted": True, "profile_label": "Old studio"} if legacy_marker else dict(appmod.load_seller(), last_invoice_number=f"{YEAR}-003")
    appmod.SELLER_FILE.write_text(json.dumps(seller))
    assert client.post("/issuers/restore", data={"issuer": "default", "confirm": "restore"}).status_code == 302
    assert number_on_page(client) == f"{YEAR}-012"
    assert appmod.load_seller()["name"] == SELLER["name"]
    assert appmod.load_seller()["iban"] == SELLER["iban"]


def test_restore_requires_matching_explicit_identity_and_retains_data_on_failure(client, monkeypatch):
    issuer, folder = add_issuer(client)
    client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"})
    original = (folder / "seller.json").read_bytes()
    for body in ({"issuer": issuer}, {"confirm": "restore"}, {"issuer": "default", "confirm": "restore"}):
        assert client.post("/issuers/restore", query_string={"issuer": issuer}, data=body).status_code == 400
    write_json = appmod._write_json

    def fail_seller(path, data):
        if path == folder / "seller.json":
            raise OSError("test disk error")
        write_json(path, data)

    monkeypatch.setattr(appmod, "_write_json", fail_seller)
    assert client.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code == 503
    assert (folder / "seller.json").read_bytes() == original


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
@pytest.mark.parametrize("kind", ["381", "384"])
def test_real_lifecycle_with_address_change_adjustment_and_reactivation(client, profile, kind):
    """Exercise the whole lifecycle with actual PDFs/XML and three identities."""
    import io

    from lxml import etree
    from pypdf import PdfReader

    issuer, folder = add_issuer(client, "Company")
    other, other_folder = add_issuer(client, "Other company")
    (folder / "seller.json").write_text(json.dumps(SELLER))
    (other_folder / "seller.json").write_text(json.dumps(dict(SELLER, last_invoice_number=f"{YEAR}-050")))
    untouched = appmod.SELLER_FILE.read_bytes(), (other_folder / "seller.json").read_bytes()
    fields = dict(FORM, issuer=issuer, profile=profile)
    response = client.post("/generate", data=fields)
    assert response.status_code == 200 and "Validierung bestanden" in response.get_data(as_text=True)
    originals = {p.name: p.read_bytes() for p in (folder / "output").iterdir()}
    original_pdf = f"Rechnung_{YEAR}-011.pdf"
    assert SELLER["address_line"] in PdfReader(io.BytesIO(originals[original_pdf])).pages[0].extract_text()

    # A move and another bank account must not create a new issuer or counter.
    account = "DE89370400440532013000"
    update = dict(SELLER, issuer=issuer, seller_revision=revision(client, issuer),
                  name="Company after move", address_line="New Street 42", has_accounts_section="1",
                  acct_kind="iban", acct_iban=account, acct_bic="COBADEFFXXX",
                  acct_account_name="Company secondary account", acct_bank_name="Example Bank")
    assert client.post("/settings/autosave", data=update).status_code == 204
    assert number_on_page(client, issuer) == f"{YEAR}-012"
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    response = client.post("/generate", data=dict(fields, number=f"{YEAR}-012", doc_type=kind,
                           correction_source=original_pdf, bank_account=account))
    assert response.status_code == 200 and "Validierung bestanden" in response.get_data(as_text=True)
    file = folder / "output" / f"Rechnung_{YEAR}-012.pdf"
    embedded = appmod.extract_xml_from_pdf(file.read_bytes())
    xml = file.with_suffix(".xml").read_bytes() if profile == "xrechnung" else embedded
    assert (embedded is None) == (profile == "xrechnung")
    root = etree.fromstring(xml)
    def value(name):
        return root.xpath(f"//*[local-name()='{name}']/text()")

    assert "Company after move" in value("Name")
    assert "New Street 42" in value("LineOne")
    assert SELLER["address_line"] not in value("LineOne")
    assert account in value("IBANID")
    assert kind in value("TypeCode")
    assert root.xpath("//*[local-name()='InvoiceReferencedDocument']/*[local-name()='IssuerAssignedID']/text()") == [FORM["number"]]
    text = "\n".join(p.extract_text() for p in PdfReader(file).pages)
    assert "Company after move" in text and "New Street 42" in text and account in text

    before_restore = {p.name: p.read_bytes() for p in (folder / "output").iterdir()}
    for _ in range(2):
        assert client.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code == 302
        assert number_on_page(client, issuer) == f"{YEAR}-013"
    response = client.post("/generate", data=dict(fields, number=f"{YEAR}-013", bank_account=account))
    assert response.status_code == 200 and "Validierung bestanden" in response.get_data(as_text=True)
    assert number_on_page(client, issuer) == f"{YEAR}-014"
    assert number_on_page(client, other) == f"{YEAR}-051"
    assert untouched == (appmod.SELLER_FILE.read_bytes(), (other_folder / "seller.json").read_bytes())
    assert all((folder / "output" / name).read_bytes() == data for name, data in originals.items())
    assert all((folder / "output" / name).read_bytes() == data for name, data in before_restore.items())


@pytest.mark.parametrize("counter,archived,expected", [
    ("{year}-010", ["{year}-011"], "{year}-012"),
    ("{year}-020", ["{year}-011"], "{year}-021"),
    ("{last_year}-999", ["{last_year}-999"], "{year}-001"),
    ("{last_year}-999", ["{year}-004"], "{year}-005"),
    ("{year}-999", [], "{year}-1000"),
    ("CUSTOM-4", ["{year}-011", "CUSTOM-5"], "{year}-012"),
    ("", ["{year}-009", "{year}-1000", "{year}-020"], "{year}-1001"),
])
def test_number_suggestion_after_retirement_handles_years_and_archive_maximum(client, counter, archived, expected):
    def number(value):
        return value.format(year=YEAR, last_year=YEAR - 1)

    add_issuer(client)
    seller = dict(SELLER, last_invoice_number=number(counter))
    appmod.SELLER_FILE.write_text(json.dumps(seller))
    for value in archived:
        # Legacy PDFs without sidecars must also contribute their standard number.
        (appmod.OUTPUT_DIR / f"Rechnung_{number(value)}.pdf").write_bytes(b"%PDF-test")
    for _ in range(2):
        assert number_on_page(client) == number(expected)
        assert client.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"}).json["ok"]
        assert client.post("/issuers/restore", data={"issuer": "default", "confirm": "restore"}).status_code == 302
    assert number_on_page(client) == number(expected)


def test_recreating_identical_details_does_not_take_over_retired_identity(client, fast_generation):
    issuer, folder = add_issuer(client, SELLER["name"])
    (folder / "seller.json").write_text(json.dumps(SELLER))
    assert client.post("/generate", data=dict(FORM, issuer=issuer)).status_code == 200
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    duplicate, duplicate_folder = add_issuer(client, SELLER["name"])
    assert duplicate != issuer
    assert client.post("/settings/autosave", data=dict(SELLER, issuer=duplicate,
                       seller_revision=revision(client, duplicate))).status_code == 204
    assert number_on_page(client, duplicate) == f"{YEAR}-001"
    assert not list((duplicate_folder / "output").iterdir())
    assert client.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code == 302
    assert number_on_page(client, issuer) == f"{YEAR}-012"
    assert number_on_page(client, duplicate) == f"{YEAR}-001"
    assert client.get(f"/download/Rechnung_{YEAR}-011.pdf?issuer={duplicate}").status_code == 404
    assert client.get(f"/download/Rechnung_{YEAR}-011.pdf?issuer={issuer}").status_code == 200


@pytest.mark.parametrize("target_default", [False, True])
def test_retired_identity_can_be_restored_after_data_folder_move(client, fast_generation, tmp_path, target_default):
    other, folder = add_issuer(client)
    issuer, folder = ("default", appmod.DATA_DIR) if target_default else (other, folder)
    (folder / "seller.json").write_text(json.dumps(SELLER))
    assert client.post("/generate", data=dict(FORM, issuer=issuer)).status_code == 200
    originals = {p.name: p.read_bytes() for p in (folder / "output").iterdir()}
    assert client.post("/issuers/default", data={"issuer": issuer}).json["ok"]
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    assert appmod.set_data_dir(str(tmp_path / "moved"))[0]
    assert client.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code == 302
    assert number_on_page(client, issuer) == f"{YEAR}-012"
    for name, data in originals.items():
        if name.endswith(".pdf"):
            assert client.get(f"/download/{name}?issuer={issuer}").data == data
    fresh = appmod.app.test_client()
    page = html.fromstring(fresh.get("/").data)
    assert page.xpath('//*[@id="issuer-select"]/option[@selected]/@value') == [other if target_default else "default"]


def test_concurrent_restore_keeps_single_identity_and_revision(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    issuer, folder = add_issuer(client)
    assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
    ready = Barrier(2)

    def restore(_):
        with appmod.app.test_client() as tab:
            ready.wait(timeout=5)
            return tab.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(restore, range(2))) == [302, 302]
    assert list((appmod.DATA_DIR / "issuers").iterdir()) == [folder]
    assert number_on_page(client, issuer) == f"{YEAR}-001"
    token = revision(client, issuer)
    assert client.post("/issuers/restore", data={"issuer": issuer, "confirm": "restore"}).status_code == 302
    assert revision(client, issuer) == token


def test_concurrent_retirement_and_export_never_revives_issuer_or_loses_original(client, fast_generation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    add_issuer(client)
    assert client.post("/generate", data=FORM).status_code == 200
    original = {p.name: p.read_bytes() for p in appmod.OUTPUT_DIR.iterdir()}
    ready = Barrier(2)

    def act(action):
        with appmod.app.test_client() as tab:
            ready.wait(timeout=5)
            if action == "delete":
                return tab.post("/issuers/delete", data={"issuer": "default", "confirm": "delete"}).status_code
            return tab.post("/generate", data=dict(FORM, issuer="default", number=f"{YEAR}-012")).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        deleted, generated = list(pool.map(act, ["delete", "generate"]))
    assert deleted == 200 and generated in (200, 410)
    assert appmod.load_seller()["_deleted"] is True
    assert all((appmod.OUTPUT_DIR / name).read_bytes() == data for name, data in original.items())
    assert client.post("/issuers/restore", data={"issuer": "default", "confirm": "restore"}).status_code == 302
    assert number_on_page(client) == f"{YEAR}-{'013' if generated == 200 else '012'}"
