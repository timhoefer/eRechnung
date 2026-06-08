"""Routen-/Integrationstests. Nutzen einen isolierten Temp-Datenordner – die
echten seller/customers/output-Dateien werden NICHT angefasst.

Der volle /generate-Roundtrip ruft build_pdf (WeasyPrint/Pango) auf und wird
übersprungen, wenn WeasyPrint nicht verfügbar ist (z. B. in der CI)."""
import json

import pytest

import app as appmod

try:  # WeasyPrint lädt native Libs beim Import -> ohne Pango nicht verfügbar
    import weasyprint  # noqa: F401
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False


@pytest.fixture
def client(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(appmod, "OUTPUT_DIR", out)
    monkeypatch.setattr(appmod, "SELLER_FILE", tmp_path / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", tmp_path / "customers.json")
    (tmp_path / "seller.json").write_text(json.dumps({
        "name": "Selftest GmbH", "country": "DE", "city": "Berlin",
        "postcode": "10829", "address_line": "Teststr. 1",
        "vat_id": "DE123456789", "email": "a@b.de", "phone": "+490",
        "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
        "bank_name": "Testbank", "account_name": "Selftest GmbH",
        "show_tax_number": False,
    }), encoding="utf-8")
    return appmod.app.test_client()


def test_index_ok(client):
    assert client.get("/").status_code == 200


def test_preview_html_renders(client):
    r = client.post("/preview-html", data={
        "description": "Test", "quantity": "1", "unit_price": "100",
        "tax_treatment": "de_19",
    })
    assert r.status_code == 200
    assert b"<" in r.data  # HTML-Fragment


def test_settings_panel_renders(client):
    r = client.get("/settings/panel")
    assert r.status_code == 200
    assert b"check-file-form" in r.data and b"datadir-form" in r.data


_FORM = {
    "number": "2026-001", "issue_date": "2026-01-01", "due_date": "2026-01-15",
    "description": "Leistung", "quantity": "1", "unit": "C62", "unit_price": "100",
    "tax_treatment": "de_19", "language": "de",
    "buyer_name": "Muster GmbH", "buyer_country": "DE",
}


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_generate_creates_pdf_and_sidecar(client):
    r = client.post("/generate", data=dict(_FORM))
    assert r.status_code == 200
    pdfs = list(appmod.OUTPUT_DIR.glob("*.pdf"))
    assert len(pdfs) == 1
    assert (appmod.OUTPUT_DIR / "Rechnung_2026-001.json").exists()  # Sidecar


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_generate_duplicate_number_keeps_both(client):
    client.post("/generate", data=dict(_FORM))
    r2 = client.post("/generate", data=dict(_FORM))  # gleiche Nummer erneut
    assert r2.status_code == 200
    pdfs = sorted(p.name for p in appmod.OUTPUT_DIR.glob("*.pdf"))
    assert len(pdfs) == 2  # nichts überschrieben
    assert "Rechnung_2026-001.pdf" in pdfs
    assert any("(2)" in n for n in pdfs)
    body = r2.get_data(as_text=True)
    assert "bereits" in body or "already" in body  # Duplikat-Hinweis
