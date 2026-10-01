"""Echte PDF/XML-Roundtrips; in CI sind alle nativen Abhängigkeiten Pflicht."""
import io
import json
import os

import pytest

import app as appmod
from zugferd import extract_xml_from_pdf, render_html_pdf, validate_schematron, validate_xml_bytes


@pytest.fixture(scope="module", autouse=True)
def native_dependencies():
    try:
        import saxonche  # noqa: F401
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:
        if os.environ.get("ERECHNUNG_REQUIRE_INTEGRATION") == "1":
            pytest.fail(f"Pflicht-Abhängigkeit fehlt: {exc}")
        pytest.skip(f"PDF/SaxonC fehlt: {exc}")


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
@pytest.mark.parametrize("language", ["de", "en"])
def test_generated_invoice_roundtrip(tmp_path, monkeypatch, profile, language):
    from pypdf import PdfReader

    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(appmod, "OUTPUT_DIR", out)
    monkeypatch.setattr(appmod, "SELLER_FILE", tmp_path / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", tmp_path / "customers.json")
    appmod.save_seller({
        "name": "Integration GmbH", "country": "DE", "city": "Berlin",
        "postcode": "10115", "address_line": "Teststr. 1", "vat_id": "DE123456789",
        "email": "seller@example.com", "phone": "+4930123456",
        "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
        "account_name": "Integration GmbH",
    })
    form = {
        "number": "ROUNDTRIP-1", "issue_date": "2026-01-01", "due_date": "2026-01-15",
        "profile": profile, "language": language, "tax_treatment": "de_19",
        "buyer_name": "Beispiel GmbH", "buyer_country": "DE", "buyer_city": "Berlin",
        "buyer_postcode": "10115", "buyer_address_line": "Teststr. 2",
        "buyer_email": "buyer@example.com", "buyer_reference": "04011000-12345-67",
        "description": "Integrationstest", "quantity": "2", "unit": "C62", "unit_price": "100",
    }
    with appmod.app.test_client() as client:
        response = client.post("/generate", data=form)
    assert response.status_code == 200
    pdf = (out / "Rechnung_ROUNDTRIP-1.pdf").read_bytes()
    reader = PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "ROUNDTRIP-1" in text and "Integrationstest" in text
    assert ("238,00" if language == "de" else "238.00") in text
    assert len(reader.pages) == 1
    assert ("Seite 1 von 1" if language == "de" else "Page 1 of 1") not in text
    embedded = extract_xml_from_pdf(pdf)
    if profile == "xrechnung":
        assert embedded is None  # PDF ist ausschließlich Sichtexemplar
        xml = (out / "Rechnung_ROUNDTRIP-1.xml").read_bytes()
        assert b"xrechnung_3.0" in xml
    else:
        assert embedded is not None
        xml = embedded
        assert not list(out.glob("*.xml"))
    ok, errors = validate_xml_bytes(xml)
    assert ok, errors
    result = validate_schematron(xml)
    assert result["available"] and result["ok"] is True, result
    assert result["error"] is None
    assert result["xrechnung"] == (profile == "xrechnung")
    assert b">238.00<" in xml
    sidecar = json.loads((out / "Rechnung_ROUNDTRIP-1.json").read_text())
    assert sidecar["invoice"]["profile"] == profile


@pytest.mark.parametrize("pdf_a", [False, True])
@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("item_count", [1, 35])
def test_invoice_footer_after_pagination(pdf_a, language, item_count):
    from pypdf import PdfReader

    seller = {
        "name": "Layout GmbH", "address_line": "Teststr. 1", "postcode": "10115",
        "city": "Berlin", "country": "DE", "iban": "DE02120300000000202051",
        "bic": "BYLADEM1001", "bank_name": "Testbank",
    }
    buyer = {"name": "Example Ltd", "country": "GB", "city": "London", "postcode": "SW1A 1AA"}
    inv = {
        "number": "LAYOUT-1", "language": language, "issue_date": "2026-01-01",
        "due_date": "2026-01-15", "doc_type": "380", "currency": "EUR",
        "tax_treatment": "non_eu", "payment_terms": "Payable within 14 days.",
    }
    items = [{
        "description": f"Service {index}: " + "A detailed description of the supplied services. " * 3,
        "quantity": "2", "unit": "C62", "unit_price": "100",
    } for index in range(1, item_count + 1)]
    with appmod.app.test_request_context("/"):
        markup, _ = appmod.render_invoice_preview(seller, buyer, inv, items)
    reader = PdfReader(io.BytesIO(render_html_pdf(markup, pdf_a=pdf_a)))
    texts = [page.extract_text() for page in reader.pages]
    text = "\n".join(texts)
    assert ("Deutschland" if language == "de" else "Germany") in texts[0]
    assert seller["iban"] in text  # Must remain a single copyable string.
    assert "01.01.2026" in texts[0] and "15.01.2026" in texts[0]
    for index in range(1, item_count + 1):
        assert f"Service {index}:" in text
    if item_count == 1:
        assert len(reader.pages) == 1
        assert ("Seite 1 von 1" if language == "de" else "Page 1 of 1") not in text
    else:
        assert len(reader.pages) > 1
        for index, page_text in enumerate(texts, 1):
            footer = (f"Rechnung LAYOUT-1 · Seite {index} von {len(texts)}" if language == "de"
                      else f"Invoice LAYOUT-1 · Page {index} of {len(texts)}")
            assert footer in page_text
    if pdf_a:
        metadata = reader.trailer["/Root"]["/Metadata"].get_data()
        assert b'pdfaid:part="3"' in metadata
        assert b'pdfaid:conformance="B"' in metadata
