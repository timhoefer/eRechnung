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


def test_export_csv(client):
    out = appmod.OUTPUT_DIR
    (out / "Rechnung_2026-001.pdf").write_bytes(b"%PDF-1.4")
    (out / "Rechnung_2026-001.json").write_text(json.dumps({
        "invoice": {"number": "2026-001", "issue_date": "2026-03-15",
                    "currency": "EUR", "tax_treatment": "de_19"},
        "buyer": {"name": "Muster GmbH", "country": "DE"},
        "items": [{"description": "Leistung", "quantity": "2",
                   "unit": "C62", "unit_price": "100"}],
    }), encoding="utf-8")
    r = client.get("/export/csv?from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200
    assert "text/csv" in r.headers["Content-Type"]
    body = r.get_data(as_text=True)
    assert "2026-001" in body and "Muster GmbH" in body
    # 2 × 100 = 200 netto, 19 % = 38 USt, 238 brutto (locale-tolerant)
    assert ("200,00" in body or "200.00" in body)
    assert ("238,00" in body or "238.00" in body)
    # Datumsfilter: außerhalb -> Rechnung nicht enthalten
    r2 = client.get("/export/csv?from=2025-01-01&to=2025-12-31")
    assert "2026-001" not in r2.get_data(as_text=True)


_FORM = {
    "number": "2026-001", "issue_date": "2026-01-01", "due_date": "2026-01-15",
    "description": "Leistung", "quantity": "1", "unit": "C62", "unit_price": "100",
    "tax_treatment": "de_19", "language": "de",
    "buyer_name": "Muster GmbH", "buyer_country": "DE",
}


def test_storno_requires_reference(client):
    # 381 (Storno) ohne Bezug -> abgelehnt, kein PDF (Redirect vor dem Rendern).
    r = client.post("/generate", data=dict(_FORM, doc_type="381"))
    assert r.status_code in (302, 303)
    assert not list(appmod.OUTPUT_DIR.glob("*.pdf"))


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_generate_creates_pdf_and_sidecar(client):
    r = client.post("/generate", data=dict(_FORM))
    assert r.status_code == 200
    pdfs = list(appmod.OUTPUT_DIR.glob("*.pdf"))
    assert len(pdfs) == 1
    assert (appmod.OUTPUT_DIR / "Rechnung_2026-001.json").exists()  # Sidecar


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_xrechnung_writes_standalone_xml(client):
    # XRechnung-Modus: einreichbare .xml + PDF-Sichtexemplar; .xml herunterladbar.
    r = client.post("/generate", data=dict(
        _FORM, profile="xrechnung",
        buyer_city="Köln", buyer_postcode="50667", buyer_address_line="Domkloster 4",
        buyer_email="k@muster.de", buyer_reference="04011000-12345-67",
    ))
    assert r.status_code == 200
    out = appmod.OUTPUT_DIR
    assert (out / "Rechnung_2026-001.pdf").exists()  # Sichtexemplar
    xml = out / "Rechnung_2026-001.xml"
    assert xml.exists()  # einreichbare XRechnung
    assert b"xrechnung_3.0" in xml.read_bytes()  # korrekte CIUS-Spec-ID
    d = client.get("/download/Rechnung_2026-001.xml")
    assert d.status_code == 200 and "xml" in d.headers["Content-Type"]
    assert "PDF + XML" in r.get_data(as_text=True)  # kombinierter Download angeboten
    # ZIP-Bundle enthält PDF + XML
    import io
    import zipfile
    z = client.get("/download-zip/Rechnung_2026-001.pdf")
    assert z.status_code == 200 and "zip" in z.headers["Content-Type"]
    names = sorted(zipfile.ZipFile(io.BytesIO(z.data)).namelist())
    assert names == ["Rechnung_2026-001.pdf", "Rechnung_2026-001.xml"]


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
