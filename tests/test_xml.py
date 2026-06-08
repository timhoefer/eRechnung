"""Round-trip-Test: build_xml erzeugt wohlgeformtes, EN-16931-XSD-valides CII-XML
mit korrekten Beträgen. Fängt Regressionen in der XML-Erzeugung nach Dep-Updates."""
from zugferd import build_xml, has_doctype, validate_xml_bytes


def make_data():
    return {
        "seller": {
            "name": "Selftest GmbH", "country": "DE", "city": "Berlin",
            "postcode": "10829", "address_line": "Teststr. 1",
            "vat_id": "DE123456789", "email": "a@b.de", "phone": "+490",
            "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
            "bank_name": "Testbank", "account_name": "Selftest GmbH",
            "show_tax_number": False,
        },
        "buyer": {
            "name": "Muster GmbH", "country": "DE", "city": "Köln",
            "postcode": "50667", "address_line": "Domkloster 4",
            "vat_id": "", "email": "k@muster.de", "state": "",
            "contact": "", "reference": "",
        },
        "invoice": {
            "number": "TEST-1", "issue_date": "2026-01-01", "due_date": "2026-01-15",
            "currency": "EUR", "tax_treatment": "de_19", "language": "de",
            "profile": "en16931", "doc_type": "380", "note": None,
            "payment_terms": "Zahlbar innerhalb von 14 Tagen.", "discount": "0",
            "ref_number": None, "ref_date": None, "service_start": None,
            "service_end": None, "discount_reason": None,
        },
        "items": [{
            "description": "Leistung", "quantity": "2", "unit": "C62",
            "unit_price": "100", "item_discount": "0", "item_discount_type": "pct",
            "item_start": None, "item_end": None, "item_discount_reason": None,
        }],
    }


def test_build_xml_wellformed_and_values():
    xml = build_xml(make_data())
    assert xml.lstrip().startswith(b"<")
    assert b"TEST-1" in xml
    assert b"238.00" in xml  # 2*100 net, 19% -> 238 brutto


def test_build_xml_is_xsd_valid():
    xml = build_xml(make_data())
    ok, messages = validate_xml_bytes(xml)
    assert ok, "XSD-Fehler:\n" + "\n".join(messages)


def test_prepayment_omits_delivery_date():
    # Vorausrechnung (386): Leistung noch nicht erbracht -> BT-72 entfällt,
    # kein Default aufs Rechnungsdatum; XML bleibt EN-16931-XSD-valide.
    data = make_data()
    data["invoice"]["doc_type"] = "386"
    xml = build_xml(data)
    ok, messages = validate_xml_bytes(xml)
    assert ok, "XSD-Fehler:\n" + "\n".join(messages)
    assert b">386<" in xml  # BT-3 Belegart
    assert b"ActualDeliverySupplyChainEvent" not in xml  # BT-72 weggelassen


def test_normal_invoice_has_delivery_date():
    # Gegenprobe: normale Rechnung (380) ohne Datum -> BT-72 = Rechnungsdatum.
    assert b"ActualDeliverySupplyChainEvent" in build_xml(make_data())


def test_prepaid_reduces_due_amount():
    # Schlussrechnung mit Anzahlung: BT-113 gesetzt, Zahlbetrag = Brutto − Anzahlung.
    data = make_data()
    data["invoice"]["prepaid"] = "100"  # 100 brutto Anzahlung (Brutto gesamt 238)
    xml = build_xml(data)
    ok, messages = validate_xml_bytes(xml)
    assert ok, "XSD-Fehler:\n" + "\n".join(messages)
    assert b"TotalPrepaidAmount" in xml      # BT-113
    assert b">100.00<" in xml                # Anzahlung
    assert b">138.00<" in xml                # BT-115 Zahlbetrag 238 − 100


def test_doctype_detection():
    assert has_doctype(b'<?xml version="1.0"?>\n<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>\n<r/>')
    assert not has_doctype(b'<?xml version="1.0"?><rsm:CrossIndustryInvoice/>')
    assert not has_doctype(b"<root/>")


def test_validate_rejects_doctype_xxe():
    # XXE-Schutz: DOCTYPE/DTD wird vor jedem Parser abgelehnt (SaxonC würde sonst
    # externe Entities auflösen -> Dateioffenlegung).
    xxe = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/hostname">]><r>&x;</r>'
    ok, msgs = validate_xml_bytes(xxe)
    assert ok is False
    assert any("DOCTYPE" in m or "Sicherheit" in m for m in msgs)


def test_xrechnung_profile_specid():
    data = make_data()
    data["invoice"]["profile"] = "xrechnung"
    xml = build_xml(data)
    assert b"xrechnung_3.0" in xml.lower()
