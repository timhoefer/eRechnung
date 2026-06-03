"""ZUGFeRD-Erzeugung: EN-16931-XML bauen und als Factur-X/ZUGFeRD ins PDF einbetten."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from drafthorse.models.accounting import (
    ApplicableTradeTax,
    CategoryTradeTax,
    TradeAllowanceCharge,
)
from drafthorse.models.document import Document
from drafthorse.models.note import IncludedNote
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentMeans, PaymentTerms
from drafthorse.models.references import InvoiceReferencedDocument
from drafthorse.models.tradelines import LineItem

TWO = Decimal("0.01")


def q(value) -> Decimal:
    """Auf 2 Nachkommastellen kaufmännisch runden."""
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def fmt_money(value, lang: str = "de") -> str:
    """Zahl mit Tausender-/Dezimaltrennung je Sprache: de=1.234,56 · en=1,234.56."""
    s = f"{q(value):,.2f}"  # englischer Stil: 1,234.56
    if lang != "en":
        s = s.translate(str.maketrans({",": ".", ".": ","}))
    return s


# Steuerliche Behandlungen. category = EN-16931 VAT-Kategoriecode.
# label/note/reason sind je Sprache (de/en) hinterlegt:
#   note   = Pflichthinweis auf der Rechnung (Freitext)
#   reason = ExemptionReason im XML (BT-120) bei steuerfrei/nicht steuerbar
TAX_TREATMENTS = {
    "de_19": {
        "category": "S",
        "rate": Decimal("19"),
        "label": {"de": "Inland 19 % USt", "en": "Domestic 19% VAT"},
        "note": {"de": None, "en": None},
        "reason": {"de": None, "en": None},
    },
    "de_7": {
        "category": "S",
        "rate": Decimal("7"),
        "label": {"de": "Inland 7 % USt (ermäßigt)", "en": "Domestic 7% VAT (reduced)"},
        "note": {"de": None, "en": None},
        "reason": {"de": None, "en": None},
    },
    "non_eu": {
        "category": "O",
        "rate": Decimal("0"),
        "label": {
            "de": "Nicht steuerbar – Drittland (Dienstleistung)",
            "en": "Not taxable – third country (service)",
        },
        "note": {
            "de": (
                "Nicht im Inland steuerbare sonstige Leistung (§ 3a Abs. 2 UStG). "
                "Die Steuer schuldet der Leistungsempfänger im Wege des "
                "Reverse-Charge-Verfahrens nach den Vorschriften seines Landes."
            ),
            "en": (
                "Not subject to German VAT — place of supply is where the customer "
                "belongs (Sec. 3a(2) German VAT Act). VAT to be accounted for by the "
                "recipient under the reverse-charge rules of the recipient's country."
            ),
        },
        "reason": {
            "de": "Nicht steuerbare sonstige Leistung (§ 3a Abs. 2 UStG)",
            "en": "Non-taxable other service (Section 3a (2) UStG)",
        },
    },
    "eu_reverse": {
        "category": "AE",
        "rate": Decimal("0"),
        "label": {"de": "Reverse Charge – EU B2B", "en": "Reverse charge – EU B2B"},
        "note": {
            "de": (
                "Steuerschuldnerschaft des Leistungsempfängers / Reverse Charge "
                "(Art. 196 MwStSystRL, § 13b UStG)."
            ),
            "en": (
                "Reverse charge – the recipient is liable for VAT "
                "(Art. 196 EU VAT Directive, Section 13b UStG)."
            ),
        },
        "reason": {"de": "Reverse charge", "en": "Reverse charge"},
    },
    "kleinunternehmer": {
        "category": "E",
        "rate": Decimal("0"),
        "label": {
            "de": "Kleinunternehmer (§ 19 UStG)",
            "en": "Small business (Section 19 UStG)",
        },
        "note": {
            "de": (
                "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet "
                "(Kleinunternehmerregelung)."
            ),
            "en": (
                "In accordance with Section 19 German VAT Act (UStG), no VAT is "
                "charged (small business scheme)."
            ),
        },
        "reason": {
            "de": "Steuerbefreiung gemäß § 19 UStG",
            "en": "VAT exemption pursuant to Section 19 UStG",
        },
    },
}


def loc(value, lang: str):
    """Lokalisierten Wert holen (dict je Sprache) mit Fallback auf Deutsch."""
    if isinstance(value, dict):
        return value.get(lang) or value.get("de")
    return value


def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def compute_totals(items, rate: Decimal, discount=Decimal("0")):
    """Zeilensummen, Zwischensumme, Rabatt, Steuerbasis, Steuer und Brutto berechnen.

    Rückgabe: (computed, line_total, discount, tax_basis, tax_total, grand_total)
      line_total  – Summe der Positionen (BT-106)
      discount    – Gesamt-Nachlass (BT-107), auf [0, line_total] begrenzt
      tax_basis   – Steuerbasis = line_total − discount (BT-109)
    """
    line_total = Decimal("0")
    computed = []
    for it in items:
        qty = Decimal(str(it["quantity"]))
        unit_price = Decimal(str(it["unit_price"]))
        net = q(qty * unit_price)
        line_total += net
        computed.append({**it, "net": net, "qty": qty, "unit_price": unit_price})
    line_total = q(line_total)
    discount = q(discount)
    if discount < Decimal("0"):
        discount = Decimal("0.00")
    if discount > line_total:
        discount = line_total
    tax_basis = q(line_total - discount)
    tax_total = q(tax_basis * rate / Decimal("100"))
    grand_total = q(tax_basis + tax_total)
    return computed, line_total, discount, tax_basis, tax_total, grand_total


def build_xml(data) -> bytes:
    """EN-16931-konformes CII-XML aus dem Rechnungs-Dict erzeugen."""
    seller = data["seller"]
    buyer = data["buyer"]
    inv = data["invoice"]
    treatment = TAX_TREATMENTS[inv["tax_treatment"]]
    rate = treatment["rate"]
    lang = inv.get("language", "de")
    note_text = loc(treatment["note"], lang)
    reason_text = loc(treatment["reason"], lang)

    discount_in = Decimal(str(inv.get("discount") or "0"))
    computed, line_total, discount, tax_basis, tax_total, grand_total = compute_totals(
        data["items"], rate, discount_in
    )
    currency = inv.get("currency", "EUR")
    profile = inv.get("profile", "en16931")

    doc = Document()
    if profile == "xrechnung":
        # XRechnung 3.0 CIUS: eigene Spec-ID (BT-24) + Geschäftsprozess (BT-23)
        doc.context.guideline_parameter.id = (
            "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
        )
        doc.context.business_parameter.id = (
            "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
        )
    else:
        doc.context.guideline_parameter.id = "urn:cen.eu:en16931:2017"
    doc.header.id = inv["number"]
    # BT-3 Belegart: 380 Rechnung, 381 Gutschrift/Storno, 384 Korrekturrechnung
    doc.header.type_code = inv.get("doc_type") or "380"
    doc.header.issue_date_time = _parse_date(inv["issue_date"])

    # BT-25/BT-26 Bezug auf vorausgegangene Rechnung (bei Storno/Korrektur Pflicht).
    ref_number = inv.get("ref_number")
    if ref_number:
        ird = doc.trade.settlement.invoice_referenced_document
        ird.issuer_assigned_id = ref_number  # BT-25
        if inv.get("ref_date"):
            ird.issue_date_time = _parse_date(inv["ref_date"])  # BT-26

    # Pflichthinweis (Steuerbefreiung / Reverse Charge) + optionaler Freitext
    if note_text:
        n = IncludedNote()
        n.content = note_text
        doc.header.notes.add(n)
    if inv.get("note"):
        n2 = IncludedNote()
        n2.content = inv["note"]
        doc.header.notes.add(n2)

    # Verkäufer (du)
    s = doc.trade.agreement.seller
    s.name = seller.get("name", "")
    s.address.line_one = seller.get("address_line", "")
    s.address.postcode = seller.get("postcode", "")
    s.address.city_name = seller.get("city", "")
    s.address.country_id = seller.get("country", "DE")
    if seller.get("vat_id"):
        tr = TaxRegistration()
        tr.id = ("VA", seller["vat_id"])  # USt-IdNr.
        s.tax_registrations.add(tr)
    # Steuernummer (FC) nur, wenn vorhanden und in den Stammdaten aktiviert.
    # Rechtlich genügt USt-IdNr ODER Steuernummer (§ 14 Abs. 4 Nr. 2 UStG).
    if seller.get("tax_number") and seller.get("show_tax_number", True):
        tr2 = TaxRegistration()
        tr2.id = ("FC", seller["tax_number"])  # Steuernummer
        s.tax_registrations.add(tr2)
    if seller.get("email"):
        s.electronic_address.uri_ID = ("EM", seller["email"])
    if profile == "xrechnung":
        # BG-6 Verkäufer-Kontakt: Name + Telefon + E-Mail (BR-DE-2/5/6/7)
        s.contact.person_name = seller.get("contact_name") or seller.get("name", "")
        if seller.get("phone"):
            s.contact.telephone.number = seller["phone"]
        if seller.get("email"):
            s.contact.email.address = seller["email"]

    # Käufer (Kunde)
    b = doc.trade.agreement.buyer
    b.name = buyer["name"]
    if buyer.get("contact"):
        b.contact.person_name = buyer["contact"]  # z.Hd. / c/o (BT-56)
    b.address.line_one = buyer.get("address_line", "")
    b.address.postcode = buyer.get("postcode", "")
    b.address.city_name = buyer.get("city", "")
    if buyer.get("state"):
        b.address.country_subdivision = buyer["state"]  # BT-54 Region/Bundesland
    b.address.country_id = buyer.get("country", "DE")
    if buyer.get("vat_id"):
        btr = TaxRegistration()
        btr.id = ("VA", buyer["vat_id"])  # USt-IdNr. des Kunden (BT-48)
        b.tax_registrations.add(btr)
    if buyer.get("email"):
        b.electronic_address.uri_ID = ("EM", buyer["email"])
    # BT-10 Buyer reference: Pflicht-Geschäftsregel; Kundenreferenz oder Platzhalter
    doc.trade.agreement.buyer_reference = buyer.get("reference") or "N/A"

    # BT-73/BT-74 Abrechnungs-/Leistungszeitraum (optional): nur wenn beide Daten gesetzt.
    svc_start = inv.get("service_start")
    svc_end = inv.get("service_end")
    if svc_start and svc_end:
        doc.trade.settlement.period.start = _parse_date(svc_start)
        doc.trade.settlement.period.end = _parse_date(svc_end)

    # BT-72 Liefer-/Leistungsdatum: Pflicht (§14 UStG, BR-FX-EN-04).
    # Bei Zeitraum = dessen Ende; sonst spätestes Positions-Ende; sonst Rechnungsdatum.
    line_ends = [it["item_end"] for it in computed if it.get("item_end")]
    delivery_date = svc_end or inv.get("service_date") or (max(line_ends) if line_ends else None) or inv["issue_date"]
    doc.trade.delivery.event.occurrence = _parse_date(delivery_date)

    # Rechnungspositionen
    for idx, it in enumerate(computed, start=1):
        li = LineItem()
        li.document.line_id = str(idx)
        li.product.name = it["description"]
        li.agreement.net.amount = q(it["unit_price"])
        li.delivery.billed_quantity = (it["qty"], it.get("unit", "C62"))
        li.settlement.trade_tax.type_code = "VAT"
        li.settlement.trade_tax.category_code = treatment["category"]
        li.settlement.trade_tax.rate_applicable_percent = rate
        # BT-134/BT-135 Positions-Leistungszeitraum (optional): nur wenn beide Daten gesetzt.
        if it.get("item_start") and it.get("item_end"):
            li.settlement.period.start = _parse_date(it["item_start"])
            li.settlement.period.end = _parse_date(it["item_end"])
        li.settlement.monetary_summation.total_amount = it["net"]
        doc.trade.items.add(li)

    # BG-20 Beleg-Nachlass (Rabatt). Mindert die Steuerbasis der Kategorie.
    if discount > 0:
        ac = TradeAllowanceCharge()
        ac.indicator = False  # False = Abschlag/Allowance (kein Zuschlag)
        ac.actual_amount = discount  # BT-92
        # BR-33: ein Beleg-Nachlass braucht einen Grund -> Default, falls leer.
        ac.reason = inv.get("discount_reason") or (
            "Rabatt" if lang != "en" else "Discount"
        )
        cat = CategoryTradeTax()  # BT-95/96: gleiche Kategorie/Satz wie die Positionen
        cat.type_code = "VAT"
        cat.category_code = treatment["category"]
        cat.rate_applicable_percent = rate
        ac.trade_tax.add(cat)
        doc.trade.settlement.allowance_charge.add(ac)

    # Steueraufstellung (eine Gruppe je Behandlung)
    tax = ApplicableTradeTax()
    tax.calculated_amount = tax_total
    tax.basis_amount = tax_basis
    tax.type_code = "VAT"
    tax.category_code = treatment["category"]
    tax.rate_applicable_percent = rate
    if reason_text:
        tax.exemption_reason = reason_text
    doc.trade.settlement.trade_tax.add(tax)

    doc.trade.settlement.currency_code = currency

    # Zahlungsweg (SEPA-Überweisung)
    if seller.get("iban"):
        pm = PaymentMeans()
        pm.type_code = "58"  # SEPA credit transfer
        pm.payee_account.iban = seller["iban"]
        if seller.get("account_name"):
            pm.payee_account.account_name = seller["account_name"]
        if seller.get("bic"):
            pm.payee_institution.bic = seller["bic"]
        doc.trade.settlement.payment_means.add(pm)

    # Zahlungsbedingungen / Fälligkeit
    pt = PaymentTerms()
    if inv.get("due_date"):
        pt.due = _parse_date(inv["due_date"])
    if inv.get("payment_terms"):
        pt.description = inv["payment_terms"]
    doc.trade.settlement.terms.add(pt)

    # Gesamtsummen
    ms = doc.trade.settlement.monetary_summation
    ms.line_total = line_total
    ms.charge_total = Decimal("0.00")
    ms.allowance_total = discount  # BT-107: Summe der Abschläge
    ms.tax_basis_total = tax_basis  # BT-109: line_total − discount (ohne currencyID)
    ms.tax_total = (tax_total, currency)  # BT-110: currencyID Pflicht
    ms.grand_total = grand_total
    ms.due_amount = grand_total

    return doc.serialize(schema="FACTUR-X_EN16931")


def build_pdf(html: str, xml: bytes) -> bytes:
    """HTML zu PDF/A-3 rendern und das XML als ZUGFeRD-Anhang einbetten."""
    from pathlib import Path

    import weasyprint
    from drafthorse.pdf import attach_xml

    # base_url = Projektordner, damit relative Schrift-URLs (static/fonts/…) laden.
    base_url = str(Path(__file__).resolve().parent)
    base_pdf = weasyprint.HTML(string=html, base_url=base_url).write_pdf(
        pdf_variant="pdf/a-3b"
    )
    # level=None: drafthorse erkennt EN 16931 bzw. XRECHNUNG aus der Spec-ID im XML.
    return attach_xml(base_pdf, xml)


def _xsd_path() -> str:
    import os

    import drafthorse

    return os.path.join(
        os.path.dirname(drafthorse.__file__),
        "schema",
        "Factur-X_1.0.07_EN16931.xsd",
    )


def validate_xml_bytes(xml: bytes):
    """XML strukturell gegen die EN-16931-XSD prüfen. -> (ok, [meldungen])."""
    from lxml import etree

    try:
        doc = etree.fromstring(xml)
    except etree.XMLSyntaxError as e:
        return False, [f"XML nicht wohlgeformt: {e}"]
    schema = etree.XMLSchema(file=_xsd_path())
    ok = schema.validate(doc)
    messages = [
        f"Zeile {e.line}: {e.message}" for e in schema.error_log
    ]
    return ok, messages


def extract_xml_from_pdf(pdf_bytes: bytes):
    """Eingebettetes ZUGFeRD-/Factur-X-XML aus einem PDF herausziehen."""
    import io

    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    attachments = reader.attachments
    for name in ("factur-x.xml", "zugferd-invoice.xml", "ZUGFeRD-invoice.xml"):
        if name in attachments:
            return list(attachments[name])[0]
    for name in attachments:
        if name.lower().endswith(".xml"):
            return list(attachments[name])[0]
    return None
