"""Create an explicitly fictional data directory for trying the optional skill."""
import argparse
import json
from pathlib import Path


def create_demo(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "output").mkdir()
    seller = {"name": "Demo Studio – Beispieldaten", "country": "DE", "city": "Berlin",
              "postcode": "10115", "address_line": "Musterstraße 1", "vat_id": "DE123456789",
              "email": "studio@example.com", "phone": "+4930000000",
              "iban": "DE02120300000000202051", "bic": "BYLADEM1001", "bank_name": "Beispielbank",
              "account_name": "Demo Studio", "last_invoice_number": "DEMO-ALT"}
    buyer = {"name": "Beispiel GmbH", "country": "DE", "city": "Berlin", "postcode": "10115",
             "address_line": "Beispielweg 2", "email": "kunde@example.com", "reference": "04011000-12345-67"}
    old = {"seller": seller, "buyer": buyer,
           "invoice": {"number": "DEMO-ALT", "issue_date": "2026-09-01", "due_date": "2026-09-15",
                       "service_start": "2026-09-01", "service_end": "2026-09-03", "language": "de",
                       "currency": "EUR", "profile": "en16931", "doc_type": "380", "tax_treatment": "de_19"},
           "items": [{"description": "Gestaltung – Beispielprojekt", "quantity": "3", "unit": "DAY", "unit_price": "800"}]}
    for filename, data in {"seller.json": seller, "customers.json": [buyer],
                           "output/Rechnung_DEMO-ALT.json": old}.items():
        (directory / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(create_demo(args.directory.expanduser().resolve()))
