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
        "explain": {
            "de": "Kunde in Deutschland → steuerbare Inlandsleistung mit 19 % USt.",
            "en": "Customer in Germany → domestic supply with 19% VAT.",
        },
    },
    "de_7": {
        "category": "S",
        "rate": Decimal("7"),
        "label": {"de": "Inland 7 % USt (ermäßigt)", "en": "Domestic 7% VAT (reduced)"},
        "note": {"de": None, "en": None},
        "reason": {"de": None, "en": None},
        "explain": {
            "de": "Ermäßigter Inlandssatz (7 %) – nur für bestimmte Leistungen; manuell zu wählen.",
            "en": "Reduced domestic rate (7%) – only for certain supplies; choose manually.",
        },
    },
    "non_eu": {
        # Kategorie AE (Reverse Charge) für Drittland-B2B (z. B. UK): der
        # Leistungsempfänger schuldet die Steuer. Setzt – wie EU-Reverse-Charge –
        # die USt-IdNr des Kunden voraus (BR-AE-02). NICHT O (verbietet USt-IdNr
        # + Steuersatz, BR-O-02/05) und nicht G (Ausfuhr-Semantik passt für eine
        # Dienstleistung schlechter).
        "category": "AE",
        "rate": Decimal("0"),
        "label": {
            "de": "Reverse Charge – Drittland (z. B. UK)",
            "en": "Reverse charge – third country (e.g. UK)",
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
        "explain": {
            "de": (
                "Kunde im Drittland (z. B. UK), B2B → nicht im Inland steuerbar "
                "(§ 3a Abs. 2 UStG); Reverse Charge nach dem Recht des Kundenlandes. "
                "Voraussetzung: Kunde ist Unternehmer (Nachweis aufbewahren, z. B. UK: "
                "Certificate of Residence) und dessen USt-IdNr liegt vor."
            ),
            "en": (
                "Customer in a third country (e.g. UK), B2B → not subject to German VAT "
                "(Sec. 3a(2) UStG); reverse charge under the customer's rules. "
                "Requires: customer is a business (keep proof, e.g. UK Certificate of "
                "Residence) and their VAT ID is available."
            ),
        },
    },
    "non_eu_g": {
        # Fallback für Drittland-Kunden OHNE USt-IdNr: Kategorie G (steuerfreie
        # Ausfuhr, "VAT not charged") verlangt nur die USt-IdNr des Verkäufers
        # (BR-G-02), nicht die des Kunden – anders als AE. Reverse Charge gilt
        # weiterhin; der Nachweis der Unternehmereigenschaft (z. B. UK: Certificate
        # of Residence) wird separat aufbewahrt, nicht in der Rechnung.
        "category": "G",
        "rate": Decimal("0"),
        "label": {
            "de": "Nicht steuerbar – Drittland (ohne USt-IdNr)",
            "en": "Not taxable – third country (no VAT ID)",
        },
        "note": {
            "de": (
                "Nicht im Inland steuerbare sonstige Leistung (§ 3a Abs. 2 UStG). "
                "Die Steuer schuldet der Leistungsempfänger nach den Vorschriften "
                "seines Landes."
            ),
            "en": (
                "Not subject to German VAT — place of supply is where the customer "
                "belongs (Sec. 3a(2) German VAT Act). VAT to be accounted for by the "
                "recipient under the rules of the recipient's country."
            ),
        },
        "reason": {
            "de": "Nicht steuerbare sonstige Leistung (§ 3a Abs. 2 UStG)",
            "en": "Non-taxable other service (Section 3a (2) UStG)",
        },
        "explain": {
            "de": (
                "Drittland-Kunde ohne USt-IdNr → als nicht steuerbare Leistung "
                "behandelt; es genügt deine eigene USt-IdNr (keine Kunden-USt-IdNr nötig)."
            ),
            "en": (
                "Third-country customer without VAT ID → treated as a non-taxable "
                "supply; only your own VAT ID is required (no customer VAT ID needed)."
            ),
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
        "explain": {
            "de": (
                "Kunde im EU-Ausland, B2B → Reverse Charge: der Kunde schuldet die USt "
                "in seinem Land (Art. 196 MwStSystRL, § 13b UStG). Voraussetzung: "
                "gültige USt-IdNr des Kunden."
            ),
            "en": (
                "Customer in another EU country, B2B → reverse charge: the customer owes "
                "VAT in their country (Art. 196 EU VAT Directive, Sec. 13b UStG). "
                "Requires the customer's valid VAT ID."
            ),
        },
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
        "explain": {
            "de": (
                "Du als Kleinunternehmer (§ 19 UStG) → es wird keine USt ausgewiesen, "
                "unabhängig vom Kundenland."
            ),
            "en": (
                "You as a small business (Sec. 19 UStG) → no VAT is charged, regardless "
                "of the customer's country."
            ),
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


def _dec(value, default="0") -> Decimal:
    """Robuste Decimal-Konvertierung: ungültige/leere/NaN/Inf-Eingaben -> default.
    Verhindert, dass nicht-numerische Formulareingaben eine Exception auslösen."""
    try:
        d = Decimal(str(value).strip())
    except (ArithmeticError, ValueError, TypeError):
        return Decimal(default)
    return d if d.is_finite() else Decimal(default)


def compute_totals(items, rate: Decimal, discount=Decimal("0"), discount_type="abs"):
    """Zeilensummen, Zwischensumme, Rabatt, Steuerbasis, Steuer und Brutto berechnen.

    Rückgabe: (computed, line_total, discount, tax_basis, tax_total, grand_total)
      line_total  – Summe der Positionen (BT-106)
      discount    – Gesamt-Nachlass (BT-107) als Betrag, auf [0, line_total] begrenzt
      tax_basis   – Steuerbasis = line_total − discount (BT-109)
    discount_type: "abs" (fester Betrag) oder "pct" (Prozent der Positionssumme).
    """
    line_total = Decimal("0")
    computed = []
    for it in items:
        qty = _dec(it["quantity"])
        unit_price = _dec(it["unit_price"])
        gross = q(qty * unit_price)
        # Positions-Rabatt (BG-27): Prozent oder fester Betrag, auf [0, gross] begrenzt.
        d_type = it.get("item_discount_type") or "pct"
        d_val = _dec(it.get("item_discount") or "0")
        if d_val < Decimal("0"):
            d_val = Decimal("0")
        if d_type == "abs":
            line_disc = q(d_val)
            if line_disc > gross:
                line_disc = gross
        else:  # pct
            if d_val > Decimal("100"):
                d_val = Decimal("100")
            line_disc = q(gross * d_val / Decimal("100"))
        net = q(gross - line_disc)
        line_total += net
        computed.append({
            **it, "qty": qty, "unit_price": unit_price, "gross": gross,
            "line_disc": line_disc, "disc_type": d_type, "disc_val": d_val,
            "net": net,
        })
    line_total = q(line_total)
    # Gesamt-Nachlass (BT-107): Prozent der Positionssumme oder fester Betrag.
    dval = _dec(discount)
    if dval < Decimal("0"):
        dval = Decimal("0")
    if discount_type == "pct":
        if dval > Decimal("100"):
            dval = Decimal("100")
        discount = q(line_total * dval / Decimal("100"))
    else:
        discount = q(dval)
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
        data["items"], rate, discount_in, inv.get("discount_type") or "abs"
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
        # BG-27 Positions-Nachlass (Rabatt): mindert das Positions-Netto (BT-131).
        if it.get("line_disc", 0) > 0:
            lac = TradeAllowanceCharge()
            lac.indicator = False  # Abschlag
            lac.actual_amount = it["line_disc"]  # BT-136
            if it.get("disc_type") == "pct" and it.get("disc_val"):
                lac.calculation_percent = it["disc_val"]  # BT-138
                lac.basis_amount = it["gross"]  # BT-137
            lac.reason = it.get("item_discount_reason") or (  # BT-139
                "Rabatt" if lang != "en" else "Discount"
            )
            li.settlement.allowance_charge.add(lac)
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


def _safe_parser():
    """Gehärteter lxml-Parser für nicht vertrauenswürdiges (hochgeladenes) XML:
    keine Entity-Auflösung, kein Netzwerk, keine DTD, keine huge_tree-Expansion.
    Defense-in-Depth gegen XXE/Billion-Laughs – unabhängig von Library-Defaults."""
    from lxml import etree

    return etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False,
        dtd_validation=False, huge_tree=False,
    )


def validate_xml_bytes(xml: bytes):
    """XML strukturell gegen die EN-16931-XSD prüfen. -> (ok, [meldungen])."""
    from lxml import etree

    try:
        doc = etree.fromstring(xml, _safe_parser())
    except etree.XMLSyntaxError as e:
        return False, [f"XML nicht wohlgeformt: {e}"]
    schema = etree.XMLSchema(file=_xsd_path())
    ok = schema.validate(doc)
    messages = [
        f"Zeile {e.line}: {e.message}" for e in schema.error_log
    ]
    return ok, messages


# --- Schematron: Geschäftsregeln (BR-*), die das XSD nicht prüft ------------
_SCH_STATE: dict = {}  # Cache: "proc" + je XSLT-Pfad das kompilierte Stylesheet
_SCH_LOCK = None
_SCH_EN16931 = "EN16931-CII-validation.xslt"  # EN-16931-Kernregeln
_SCH_XRECHNUNG = "XRechnung-CII-validation.xsl"  # zusätzliche BR-DE-Regeln


def _schematron_dir() -> str:
    import os
    import sys

    # Gebündelt (PyInstaller): Ressourcen liegen unter sys._MEIPASS.
    base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    return os.path.join(base, "schematron")


def schematron_available() -> bool:
    """True, wenn EN16931-XSLT vorhanden und saxonche installiert ist."""
    import os

    if not os.path.exists(os.path.join(_schematron_dir(), _SCH_EN16931)):
        return False
    try:
        import saxonche  # noqa: F401
    except ImportError:
        return False
    return True


def _run_schematron(xslt_path: str, xml: bytes):
    """Ein Stylesheet ausführen -> (errors:list[str], warnings:list[str])."""
    import threading

    from lxml import etree
    from saxonche import PySaxonProcessor

    global _SCH_LOCK
    if _SCH_LOCK is None:
        _SCH_LOCK = threading.Lock()

    with _SCH_LOCK:
        if "proc" not in _SCH_STATE:
            _SCH_STATE["proc"] = PySaxonProcessor(license=False)
        proc = _SCH_STATE["proc"]
        if xslt_path not in _SCH_STATE:
            _SCH_STATE[xslt_path] = proc.new_xslt30_processor().compile_stylesheet(
                stylesheet_file=xslt_path
            )
        node = proc.parse_xml(xml_text=xml.decode("utf-8"))
        svrl = _SCH_STATE[xslt_path].transform_to_string(xdm_node=node)

    root = etree.fromstring(svrl.encode("utf-8"))
    ns = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
    errs, warns = [], []
    for fa in root.findall(".//svrl:failed-assert", ns):
        flag = (fa.get("flag") or fa.get("role") or "fatal").lower()
        text_el = fa.find("svrl:text", ns)
        msg = " ".join((text_el.text or "").split()) if text_el is not None else "(ohne Text)"
        (warns if flag in ("warning", "info") else errs).append(msg)
    return errs, warns


def validate_schematron(xml: bytes) -> dict:
    """Geschäftsregeln per Schematron prüfen (EN 16931 + ggf. XRechnung BR-DE).

    Das XRechnung-Profil wird automatisch an der Spec-ID im XML erkannt; dann
    laufen zusätzlich die BR-DE-Regeln. Rückgabe:
    {"available", "ok", "errors", "warnings", "error", "xrechnung"}.
    Robust: fehlt saxonche/XSLT oder wirft Saxon, bleibt die Seite heil.
    """
    import os

    out = {"available": False, "ok": None, "errors": [], "warnings": [], "error": None, "xrechnung": False}
    d = _schematron_dir()
    en_path = os.path.join(d, _SCH_EN16931)
    if not os.path.exists(en_path):
        return out
    try:
        import saxonche  # noqa: F401
    except ImportError:
        return out

    paths = [en_path]
    is_xr = b"xrechnung" in xml.lower()  # Spec-ID enthält "...:xrechnung_3.0"
    if is_xr:
        xr_path = os.path.join(d, _SCH_XRECHNUNG)
        if os.path.exists(xr_path):
            paths.append(xr_path)

    err_counts: dict = {}
    warn_counts: dict = {}
    try:
        for p in paths:
            errs, warns = _run_schematron(p, xml)
            for m in errs:
                err_counts[m] = err_counts.get(m, 0) + 1
            for m in warns:
                warn_counts[m] = warn_counts.get(m, 0) + 1
    except Exception as exc:  # Saxon-/Parse-Fehler dürfen die Seite nicht killen
        out["error"] = str(exc)
        return out

    def _fmt(counts):
        return [m + (f" (×{c})" if c > 1 else "") for m, c in counts.items()]

    out["available"] = True
    out["xrechnung"] = is_xr
    out["errors"] = _fmt(err_counts)
    out["warnings"] = _fmt(warn_counts)
    out["ok"] = not err_counts
    return out


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
