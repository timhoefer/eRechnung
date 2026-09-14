"""Echte PDF/XML-Roundtrips; in CI sind alle nativen Abhängigkeiten Pflicht."""
import io
import json
import os

import pytest

import app as appmod
from zugferd import extract_xml_from_pdf, validate_schematron, validate_xml_bytes


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
