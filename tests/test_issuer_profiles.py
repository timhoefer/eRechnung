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
    options = page.get_element_by_id("issuer-select").xpath("./option")
    assert [(o.get("value"), o.text) for o in options] == [("default", SELLER["name"])]
    assert appmod.SELLER_FILE.read_bytes() == original
    assert not (appmod.DATA_DIR / "issuers").exists()


def test_new_profile_is_blank_and_has_own_number_sequence(client):
    issuer, directory = add_issuer(client)
    assert json.loads((directory / "seller.json").read_text()) == {
        "country": "DE", "profile_label": "Example Company",
    }
    assert number_on_page(client) == f"{YEAR}-011"
    assert number_on_page(client, issuer) == f"{YEAR}-001"
    assert (directory / "output").is_dir()


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
