"""Fictional data and a normal invoice form for mutation confirmation tests."""
import json
from datetime import date

import pytest

import app as appmod

SELLER = {
    "name": "Example Studio", "address_line": "Teststr. 1", "postcode": "10829",
    "city": "Berlin", "country": "DE", "vat_id": "DE123456789",
    "email": "example@example.org", "phone": "+493012345678",
    "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
    "last_invoice_number": f"{date.today().year}-010",
}
BUYER = {"name": "Example Client", "address_line": "Teststr. 2", "postcode": "10115",
         "city": "Berlin", "country": "DE", "email": "client@example.org",
         "reference": "ORDER-1", "payment_term_days": "30"}
OTHER = "a" * 32


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    (root / "output").mkdir()
    (root / ".erechnung.lock").touch()
    monkeypatch.setattr(appmod, "BASE", tmp_path / "app")
    monkeypatch.setattr(appmod, "DATA_DIR", root)
    monkeypatch.setattr(appmod, "SELLER_FILE", root / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", root / "customers.json")
    monkeypatch.setattr(appmod, "OUTPUT_DIR", root / "output")
    monkeypatch.setattr(appmod, "CONFIG_FILE", tmp_path / "config.json")
    appmod.SELLER_FILE.write_text(json.dumps(SELLER))
    appmod.CUSTOMERS_FILE.write_text(json.dumps([BUYER]))
    return appmod.app.test_client()


def snapshot():
    return {p.relative_to(appmod.DATA_DIR).as_posix(): p.read_bytes()
            for p in appmod.DATA_DIR.rglob("*") if p.is_file()}


def add_other(*, deleted=False):
    directory = appmod.DATA_DIR / "issuers" / OTHER
    directory.mkdir(parents=True)
    (directory / "output").mkdir()
    (directory / "seller.json").write_text(json.dumps({
        **SELLER, "name": "Other Company", "profile_label": "Company",
        "last_invoice_number": f"{date.today().year}-020", "_deleted": deleted,
    }))
    return directory


def invoice_fields(client):
    # Match a regular filled invoice form, including the current seller revision.
    assert client.get('/').status_code == 200
    fields = {"issuer": ["default"], "seller_revision": [appmod.seller_revision(appmod.load_seller())],
              "number": ["TEST-1"], "issue_date": [date.today().isoformat()],
              "profile": ["en16931"], "tax_treatment": ["de_19"], "currency": ["EUR"],
              "description": ["Design retainer", "Workshop"], "quantity": ["15", "1"],
              "unit": ["DAY", "LS"], "unit_price": ["800", "100.50"]}
    fields.update({"buyer_" + key: [value] for key, value in BUYER.items()})
    return fields
