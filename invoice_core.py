"""Shared, side-effect-free invoice rendering for the app and optional adapters."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from countries import COUNTRIES
from i18n import t as translate
from zugferd import TAX_TREATMENTS, _dec, compute_totals, fmt_money, loc, q


def price_filter(value, lang="de"):
    amount = _dec(value)
    decimals = max(2, -int(amount.normalize().as_tuple().exponent))
    text = f"{amount:,.{decimals}f}"
    return text if lang == "en" else text.translate(str.maketrans(",.", ".,"))


def money_filter(value, lang="de"):
    return fmt_money(value, lang)


def datefmt_filter(value):
    """ISO-Datum (YYYY-MM-DD) -> DD.MM.YYYY; unbekanntes Format unverändert."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return str(value)


def qtyfmt_filter(value, lang="de"):
    """Menge ohne überflüssige Nachkommastellen, lokalisiertes Dezimaltrennzeichen."""
    d = Decimal(str(value))
    s = format(d.normalize(), "f")
    if lang != "en" and "." in s:
        s = s.replace(".", ",")
    return s


def _norm_account(a: dict) -> dict:
    """Ein Konto-Dict auf einheitliche Form bringen: alle Felder gesetzt (leer, falls
    unbenutzt), 'kind' abgeleitet ("intl", wenn eine Kontonummer da ist, sonst "iban").
    So können Templates und XML jedes Konto gleich behandeln."""
    kind = a.get("kind") or ("intl" if (a.get("account_number") or "").strip() else "iban")
    return {
        "kind": kind,
        "account_name": a.get("account_name", ""),
        "bank_name": a.get("bank_name", ""),
        "iban": a.get("iban", ""), "bic": a.get("bic", ""),
        "account_number": a.get("account_number", ""),
        "routing": a.get("routing", ""), "swift": a.get("swift", ""),
    }


def _acct_id(a: dict) -> str:
    """Stabiler Schlüssel eines Kontos: Kontonummer (International) bzw. IBAN (SEPA)."""
    return a["account_number"] if a["kind"] == "intl" else a["iban"]


def seller_accounts(seller: dict) -> list:
    """Alle Zahlungskonten: Hauptkonto (flache Felder) zuerst, danach die weiteren
    aus seller['accounts']. Konten ohne Schlüssel (IBAN bzw. Kontonummer) werden
    ausgelassen. Identifiziert wird ein Konto über diesen Schlüssel (stabil), nicht
    über die Listenposition."""
    out = []
    primary = _norm_account({
        "kind": seller.get("bank_kind"),
        "account_name": seller.get("account_name", ""),
        "bank_name": seller.get("bank_name", ""),
        "iban": seller.get("iban", ""), "bic": seller.get("bic", ""),
        "account_number": seller.get("account_number", ""),
        "routing": seller.get("routing", ""), "swift": seller.get("swift", ""),
    })
    if _acct_id(primary).strip():
        out.append(primary)
    for a in (seller.get("accounts") or []):
        na = _norm_account(a)
        if _acct_id(na).strip():
            out.append(na)
    return out


def _norm_iban(s) -> str:
    return "".join(str(s or "").split()).upper()


def select_account(seller: dict, key) -> dict | None:
    """Konto anhand seines Schlüssels (IBAN bzw. Kontonummer) wählen. Zuerst per
    Schlüssel matchen – so übersteht die Auswahl Umsortieren/Entfernen. Alt-Sidecars
    enthalten noch einen numerischen Index; der greift nur, wenn kein Schlüssel passt.
    Fallback: erstes Konto; None, wenn keins hinterlegt ist."""
    accts = seller_accounts(seller)
    if not accts:
        return None
    k = str(key or "").strip()
    if k:
        kn = _norm_iban(k)  # tolerant gegen Leerzeichen/Kleinschreibung
        for a in accts:
            if _norm_iban(_acct_id(a)) == kn:
                return a
    if k.isdigit():  # Alt-Sidecar: numerischer Index (nur ohne Schlüssel-Treffer)
        i = int(k)
        if 0 <= i < len(accts):
            return accts[i]
    return accts[0]


def payment_terms_text(days: int, lang: str) -> str:
    """Lokalisierter Zahlungsbedingungs-Satz aus dem Zahlungsziel (Tage)."""
    if lang == "en":
        unit = "day" if days == 1 else "days"
        return f"Payable within {days} {unit} net."
    unit = "Tag" if days == 1 else "Tagen"
    return f"Zahlbar innerhalb von {days} {unit} ohne Abzug."


def payment_days(form):
    """Zahlungsziel in Tagen aus Fällig − Rechnungsdatum (None, wenn kein Fällig-Datum)."""
    issue, due = form.get("issue_date"), form.get("due_date")
    if not issue or not due:
        return None
    try:
        d = (date.fromisoformat(due) - date.fromisoformat(issue)).days
    except ValueError:
        return None
    return d if d >= 0 else None


def xrechnung_missing(seller: dict, buyer: dict) -> list:
    """Pflichtfelder, die XRechnung über EN16931 hinaus verlangt (BR-DE-*)."""
    missing = []
    if not seller.get("phone"):
        missing.append("xr_seller_phone")
    if not seller.get("email"):
        missing.append("xr_seller_email")
    if not buyer.get("email"):
        missing.append("xr_buyer_email")
    if not buyer.get("reference"):
        missing.append("xr_buyer_ref")
    return missing


UNITS = [
    ("HUR", {"de": "Stunde", "en": "Hour"}, {"de": "Stunden", "en": "Hours"}),
    ("DAY", {"de": "Tag", "en": "Day"}, {"de": "Tage", "en": "Days"}),
    ("WEE", {"de": "Woche", "en": "Week"}, {"de": "Wochen", "en": "Weeks"}),
    ("MON", {"de": "Monat", "en": "Month"}, {"de": "Monate", "en": "Months"}),
    ("ANN", {"de": "Jahr", "en": "Year"}, {"de": "Jahre", "en": "Years"}),
    ("C62", {"de": "Stück", "en": "Piece"}, {"de": "Stück", "en": "Pieces"}),
    ("LS", {"de": "Pauschal", "en": "Lump sum"}, {"de": "Pauschal", "en": "Lump sum"}),
]


COUNTRY_NAME = dict(COUNTRIES)


ADDRESS_STATE_COUNTRIES = {"US", "CA", "AU"}


def _clean(line: str) -> str:
    """Mehrfach-Leerzeichen reduzieren, Ränder und verwaiste Kommata entfernen."""
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"\s+,", ",", line)
    return line.strip(" ,")


def format_buyer_address(buyer: dict, lang: str) -> list[str]:
    """Adresszeilen des Kunden landesüblich anordnen (rein für die PDF-Optik).

    Das XML bleibt unberührt – dort sind alle Adressteile strukturiert.
    """
    lines: list[str] = []
    if buyer.get("address_line"):
        lines.append(buyer["address_line"].strip())

    country = (buyer.get("country") or "DE").upper()
    city = (buyer.get("city") or "").strip()
    postcode = (buyer.get("postcode") or "").strip()
    state = (buyer.get("state") or "").strip()

    if country in ADDRESS_STATE_COUNTRIES and state:
        if country == "US":
            locality = [f"{city}, {state} {postcode}"]
        else:  # CA, AU: "Stadt ST PLZ"
            locality = [f"{city} {state} {postcode}"]
    elif country == "GB":
        locality = [city, postcode]  # UK: Stadt und Postcode auf eigenen Zeilen
    else:
        locality = [f"{postcode} {city}"]  # DE/EU-Standard: "PLZ Stadt"

    for raw in locality:
        cleaned = _clean(raw)
        if cleaned:
            lines.append(cleaned)

    if country != "DE":
        lines.append(loc(COUNTRY_NAME.get(country, {"de": country, "en": country}), lang))

    return lines


def format_seller_country(seller: dict, buyer: dict, lang: str) -> str:
    """Absenderland in Rechnungssprache, wenn der Kunde im Ausland sitzt."""
    seller_country = (seller.get("country") or "DE").strip().upper() or "DE"
    buyer_country = (buyer.get("country") or "DE").strip().upper() or "DE"
    if seller_country == buyer_country:
        return ""
    return loc(COUNTRY_NAME.get(seller_country, {"de": seller_country, "en": seller_country}), lang)


def suggest_invoice_number(seller: dict) -> str:
    last = seller.get("last_invoice_number", "")
    year = date.today().year
    m = re.match(r"^(\d{4})-(\d+)$", last or "")
    if m and int(m.group(1)) == year:
        return f"{year}-{int(m.group(2)) + 1:03d}"
    return f"{year}-001"


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)


def render_invoice_preview(seller, buyer, inv, items, mode="", *, draft=False):
    """Rechnungs-HTML für Live-Vorschau und neue Exporte rendern.
    Rückgabe: (html, (line_total, discount, tax_basis, tax_total, grand_total, treatment))."""
    inv_lang = inv.get("language") or "de"
    tt = inv.get("tax_treatment", "de_19")
    if tt not in TAX_TREATMENTS:
        tt = "de_19"
    treatment = TAX_TREATMENTS[tt]
    computed, line_total, discount, tax_basis, tax_total, grand_total = compute_totals(
        items, cast(Decimal, treatment["rate"]), _dec(inv.get("discount") or "0"),
        inv.get("discount_type") or "abs",
    )
    # Anzahlung (BT-113): vom Brutto abziehen -> Zahlbetrag (BT-115).
    prepaid = q(_dec(inv.get("prepaid") or "0"))
    if prepaid < Decimal("0"):
        prepaid = Decimal("0")
    if prepaid > grand_total:
        prepaid = grand_total
    due_amount = q(grand_total - prepaid)
    unit_labels = {code: loc(sg, inv_lang) for code, sg, pl in UNITS}
    unit_labels_pl = {code: loc(pl, inv_lang) for code, sg, pl in UNITS}
    body_class = "mini" if mode == "mini" else ("page" if mode else "")
    bank = select_account(seller, inv.get("bank_account"))
    html = _templates.get_template("invoice_pdf.html").render(
        draft=draft,
        ti=translate(inv_lang),
        body_class=body_class,
        seller=seller,
        seller_country=format_seller_country(seller, buyer, inv_lang),
        bank=bank,
        buyer=buyer,
        buyer_address_lines=format_buyer_address(buyer, inv_lang),
        inv=inv,
        items=computed,
        unit_labels=unit_labels,
        unit_labels_pl=unit_labels_pl,
        treatment=treatment,
        treatment_note=loc(treatment["note"], inv_lang),
        treatment_label=loc(treatment["label"], inv_lang),
        line_total=line_total,
        discount=discount,
        tax_basis=tax_basis,
        tax_total=tax_total,
        grand_total=grand_total,
        prepaid=prepaid,
        due_amount=due_amount,
        D=Decimal,
    )
    return html, (line_total, discount, tax_basis, tax_total, grand_total, treatment)

_templates = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
    autoescape=select_autoescape(["html"]),
)
_templates.filters.update(price=price_filter, money=money_filter, datefmt=datefmt_filter, qtyfmt=qtyfmt_filter)
