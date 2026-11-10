"""Check journal values against the archived document, without changing invoices."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from lxml import etree

from invoice_archive import digest
from zugferd import _safe_parser, extract_xml_from_pdf, has_doctype

NS = {"rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
      "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
      "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"}


class JournalConflict(Exception):
    def __init__(self, filename: str, reason: str = "mismatch"):
        self.filename, self.reason = filename, reason
        super().__init__(filename)


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or linked document")
    return path.read_bytes()


def _record(xml: bytes) -> dict:
    if has_doctype(xml):
        raise ValueError("DTD is not supported")
    root = etree.fromstring(xml, _safe_parser())
    if root.tag != "{" + NS["rsm"] + "}CrossIndustryInvoice" or root.getroottree().docinfo.doctype:
        raise ValueError("Not a CII invoice")

    def value(path, *, optional=False):
        nodes = root.xpath(path, namespaces=NS)
        if optional and not nodes:
            return ""
        if len(nodes) != 1 or len(nodes[0]):
            raise ValueError("Missing or ambiguous journal field")
        return nodes[0].text or ""

    def number(path):
        result = Decimal(value(path))
        if not result.is_finite():
            raise ValueError("Non-finite journal amount")
        return result

    header = "rsm:ExchangedDocument/ram:"
    trade = "rsm:SupplyChainTradeTransaction/ram:"
    buyer = trade + "ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:"
    settlement = trade + "ApplicableHeaderTradeSettlement/ram:"
    tax = settlement + "ApplicableTradeTax/ram:"
    totals = settlement + "SpecifiedTradeSettlementHeaderMonetarySummation/ram:"
    date_path = header + "IssueDateTime/udt:DateTimeString"
    if root.xpath(date_path + "/@format", namespaces=NS) != ["102"]:
        raise ValueError("Unsupported invoice date")
    currency = value(settlement + "InvoiceCurrencyCode")
    if root.xpath(totals + "TaxTotalAmount/@currencyID", namespaces=NS) != [currency]:
        raise ValueError("Ambiguous tax currency")
    if value(tax + "TypeCode") != "VAT":
        raise ValueError("Unsupported tax")
    return {
        "number": value(header + "ID"),
        "date": datetime.strptime(value(date_path), "%Y%m%d").date().isoformat(),
        "buyer": value(buyer + "Name"), "country": value(buyer + "PostalTradeAddress/ram:CountryID"),
        "seller": value(trade + "ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name"),
        "currency": currency, "type": value(header + "TypeCode"),
        "reference": value(settlement + "InvoiceReferencedDocument/ram:IssuerAssignedID", optional=True),
        "category": value(tax + "CategoryCode"), "rate": number(tax + "RateApplicablePercent"),
        "net": number(totals + "TaxBasisTotalAmount"), "vat": number(totals + "TaxTotalAmount"),
        "gross": number(totals + "GrandTotalAmount"),
        "tax_basis": number(tax + "BasisAmount"), "tax_amount": number(tax + "CalculatedAmount"),
    }


def verify_csv_source(document: Path, data: dict, sidecar_bytes: bytes,
                      expected: dict, issuer: str) -> dict[Path, str]:
    """Return snapshots for a final recheck, or refuse the entire export.

    Always compare the actual XML, including for unchanged modern invoices:
    a newer calculation engine must not silently change old journal amounts.
    This is a journal consistency check, not a new XSD/Schematron validation.
    """
    try:
        if data.get("issuer_id", issuer) != issuer:
            raise ValueError("Wrong issuer")
        source = document.with_suffix(".xml") if data["invoice"].get("profile") == "xrechnung" else document
        contents = {document: _read(document)}
        if source not in contents:
            contents[source] = _read(source)
        snapshots = {p: digest(raw) for p, raw in contents.items()}
        snapshots[document.with_suffix(".json")] = digest(sidecar_bytes)
        raw = contents[source]
        xml = raw if source.suffix.lower() == ".xml" else extract_xml_from_pdf(raw)
        if not xml:
            raise ValueError("No embedded XML")
        actual = _record(xml)
    except Exception as exc:
        # PDF parsers can raise different exceptions for corrupt external files.
        # Do not expose parser details or silently fall back to the saved JSON.
        raise JournalConflict(document.name, "unreadable") from exc
    if actual != expected:
        raise JournalConflict(document.name)
    return snapshots


def verify_csv_snapshots(snapshots: dict[Path, str]) -> None:
    for path, checksum in snapshots.items():
        try:
            if digest(_read(path)) != checksum:
                raise ValueError("Changed during export")
        except (OSError, ValueError) as exc:
            raise JournalConflict(path.name, "changed") from exc
