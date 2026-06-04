"""Lokale Web-App zur Erstellung von ZUGFeRD-E-Rechnungen."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from countries import COUNTRIES
from i18n import LANGUAGES, get_ui_lang
from i18n import t as translate
from zugferd import (
    TAX_TREATMENTS,
    build_pdf,
    build_xml,
    compute_totals,
    extract_xml_from_pdf,
    fmt_money,
    loc,
    schematron_available,
    validate_schematron,
    validate_xml_bytes,
)

BASE = Path(__file__).parent
SELLER_FILE = BASE / "seller.json"
CUSTOMERS_FILE = BASE / "customers.json"
OUTPUT_DIR = BASE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = "erechnung-local"  # nur für Flash-Messages, rein lokal


@app.template_filter("money")
def money_filter(value, lang="de"):
    return fmt_money(value, lang)


@app.template_filter("datefmt")
def datefmt_filter(value):
    """ISO-Datum (YYYY-MM-DD) -> DD.MM.YYYY; unbekanntes Format unverändert."""
    if not value:
        return ""
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d.%m.%Y")
    except (ValueError, TypeError):
        return str(value)


@app.template_filter("qtyfmt")
def qtyfmt_filter(value, lang="de"):
    """Menge ohne überflüssige Nachkommastellen, lokalisiertes Dezimaltrennzeichen."""
    d = Decimal(str(value))
    s = format(d.normalize(), "f")
    if lang != "en" and "." in s:
        s = s.replace(".", ",")
    return s


def _country_sortkey(name: str) -> str:
    """Sortierschlüssel ohne Umlaute/Akzente (Ä→a, é→e …) für saubere A–Z-Reihung."""
    import unicodedata

    s = name.lower().replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


@app.context_processor
def inject_i18n():
    lang = get_ui_lang(request)
    countries = sorted(COUNTRIES, key=lambda c: _country_sortkey(loc(c[1], lang)))
    return {
        "t": translate(lang),
        "lang": lang,
        "languages": LANGUAGES,
        "loc": loc,
        "countries": countries,
    }


@app.route("/setlang/<code>")
def setlang(code):
    resp = redirect(request.referrer or url_for("index"))
    if code in LANGUAGES:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365)
    return resp


# --- Persistenz ------------------------------------------------------------
def load_seller() -> dict:
    if SELLER_FILE.exists():
        return json.loads(SELLER_FILE.read_text(encoding="utf-8"))
    return {"country": "DE"}


def save_seller(data: dict) -> None:
    SELLER_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


SELLER_FIELDS = [
    "name", "subtitle", "address_line", "postcode", "city", "country", "vat_id",
    "tax_number", "email", "phone", "web", "iban", "bic", "bank_name",
    "account_name", "default_payment_terms",
]


def apply_seller_form(seller: dict, form) -> dict:
    for field in SELLER_FIELDS:
        if field in form:
            seller[field] = form.get(field, "").strip()
    # Checkbox: fehlt im abgesendeten Stammdaten-Formular = abgewählt.
    seller["show_tax_number"] = form.get("show_tax_number") is not None
    return seller


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


# Einheiten: menschenlesbares Label (de/en) -> UN/ECE-Code (für das XML).
UNITS = [
    ("HUR", {"de": "Stunde", "en": "Hour"}),
    ("DAY", {"de": "Tag", "en": "Day"}),
    ("WEE", {"de": "Woche", "en": "Week"}),
    ("MON", {"de": "Monat", "en": "Month"}),
    ("ANN", {"de": "Jahr", "en": "Year"}),
    ("C62", {"de": "Stück", "en": "Piece"}),
    ("LS", {"de": "Pauschal", "en": "Lump sum"}),
]


def load_customers() -> list[dict]:
    if CUSTOMERS_FILE.exists():
        return json.loads(CUSTOMERS_FILE.read_text(encoding="utf-8"))
    return []


def save_customers(customers: list[dict]) -> None:
    CUSTOMERS_FILE.write_text(
        json.dumps(customers, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def upsert_customer(buyer: dict) -> None:
    """Kunden anhand des Namens anlegen oder aktualisieren."""
    if not buyer.get("name"):
        return
    customers = load_customers()
    for c in customers:
        if c["name"].lower() == buyer["name"].lower():
            c.update(buyer)
            break
    else:
        customers.append(buyer)
    save_customers(customers)


def save_customer_items(name: str, items: list, buyer: dict) -> list:
    """Positionen beim Kunden (per Name) ablegen; Kunde anlegen, falls neu."""
    customers = load_customers()
    for c in customers:
        if c["name"].lower() == name.lower():
            c["items"] = items
            break
    else:
        buyer = {**buyer, "items": items}
        customers.append(buyer)
    save_customers(customers)
    return items


def buyer_from_form(form) -> dict:
    return {
        "name": form.get("buyer_name", "").strip(),
        "contact": form.get("buyer_contact", "").strip(),
        "address_line": form.get("buyer_address_line", "").strip(),
        "postcode": form.get("buyer_postcode", "").strip(),
        "city": form.get("buyer_city", "").strip(),
        "state": form.get("buyer_state", "").strip(),
        "country": form.get("buyer_country", "").strip() or "DE",
        "vat_id": form.get("buyer_vat_id", "").strip(),
        "email": form.get("buyer_email", "").strip(),
        "reference": form.get("buyer_reference", "").strip(),
    }


# --- Adressformatierung ----------------------------------------------------
# Code -> {"de": ..., "en": ...} für den lokalisierten Ländernamen im Adressblock.
COUNTRY_NAME = dict(COUNTRIES)

# Länder, für die ein Bundesland/Staat im Adressblock landesüblich ist.
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


# --- Helfer ----------------------------------------------------------------
def suggest_invoice_number(seller: dict) -> str:
    last = seller.get("last_invoice_number", "")
    year = date.today().year
    m = re.match(r"^(\d{4})-(\d+)$", last or "")
    if m and int(m.group(1)) == year:
        return f"{year}-{int(m.group(2)) + 1:03d}"
    return f"{year}-001"


def parse_items(form) -> list[dict]:
    items = []
    starts = form.getlist("item_start")
    ends = form.getlist("item_end")
    discounts = form.getlist("item_discount")
    discount_types = form.getlist("item_discount_type")
    for i, (desc, qty, unit, price) in enumerate(
        zip(
            form.getlist("description"),
            form.getlist("quantity"),
            form.getlist("unit"),
            form.getlist("unit_price"),
        )
    ):
        if not desc.strip():
            continue
        items.append(
            {
                "description": desc.strip(),
                "quantity": (qty or "1").replace(",", "."),
                "unit": unit or "C62",
                "unit_price": (price or "0").replace(",", "."),
                "item_start": (starts[i] if i < len(starts) else "") or None,
                "item_end": (ends[i] if i < len(ends) else "") or None,
                "item_discount": ((discounts[i] if i < len(discounts) else "0") or "0").replace(",", "."),
                "item_discount_type": (discount_types[i] if i < len(discount_types) else "pct") or "pct",
            }
        )
    return items


# Felder, die eine gespeicherte Kunden-Position bilden (ohne datumsabhängigen Zeitraum).
SAVED_ITEM_FIELDS = ("description", "quantity", "unit", "unit_price")


def stored_items(items: list[dict]) -> list[dict]:
    return [{k: it[k] for k in SAVED_ITEM_FIELDS} for it in items]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", text)


def load_draft(src: str | None) -> dict | None:
    """Sidecar-JSON einer archivierten Rechnung laden (für „als Vorlage öffnen")."""
    if not src:
        return None
    name = Path(src).stem + ".json"  # Verzeichnis-/Endungsanteile entfernen (kein Traversal)
    path = OUTPUT_DIR / name
    if path.name != name or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _assemble(form):
    """Formulardaten -> (data-dict, gerendertes HTML, totals-bundle)."""
    seller = load_seller()
    items = parse_items(form)
    inv_lang = form.get("language", "") or get_ui_lang(request)
    inv = {
        "number": form.get("number", "").strip(),
        "issue_date": form.get("issue_date"),
        "due_date": form.get("due_date") or None,
        "service_start": form.get("service_start") or None,
        "service_end": form.get("service_end") or None,
        "currency": form.get("currency", "EUR"),
        "tax_treatment": form.get("tax_treatment", "de_19"),
        "language": inv_lang,
        "profile": form.get("profile", "en16931"),
        "note": form.get("note", "").strip() or None,
        "payment_terms": form.get("payment_terms", "").strip() or None,
        "doc_type": form.get("doc_type", "380") or "380",
        "ref_number": form.get("ref_number", "").strip() or None,
        "ref_date": form.get("ref_date") or None,
        "discount": (form.get("discount", "0") or "0").replace(",", ".").strip() or "0",
        "discount_reason": form.get("discount_reason", "").strip() or None,
    }
    buyer = buyer_from_form(form)
    data = {"seller": seller, "buyer": buyer, "invoice": inv, "items": items}

    treatment = TAX_TREATMENTS[inv["tax_treatment"]]
    computed, line_total, discount, tax_basis, tax_total, grand_total = compute_totals(
        items, treatment["rate"], Decimal(str(inv["discount"]))
    )
    unit_labels = {code: loc(label, inv_lang) for code, label in UNITS}
    mode = form.get("_full")
    body_class = "mini" if mode == "mini" else ("page" if mode else "")
    html = render_template(
        "invoice_pdf.html",
        ti=translate(inv_lang),  # Übersetzungen in Rechnungssprache
        body_class=body_class,
        seller=seller,
        buyer=buyer,
        buyer_address_lines=format_buyer_address(buyer, inv_lang),
        inv=inv,
        items=computed,
        unit_labels=unit_labels,
        treatment=treatment,
        treatment_note=loc(treatment["note"], inv_lang),
        treatment_label=loc(treatment["label"], inv_lang),
        line_total=line_total,
        discount=discount,
        tax_basis=tax_basis,
        tax_total=tax_total,
        grand_total=grand_total,
        D=Decimal,
    )
    totals = {
        "line_total": line_total,
        "discount": discount,
        "tax_basis": tax_basis,
        "tax_total": tax_total,
        "grand_total": grand_total,
        "treatment_label": loc(treatment["label"], get_ui_lang(request)),
    }
    return data, html, totals


# --- Routen ----------------------------------------------------------------
@app.route("/")
def index():
    seller = load_seller()
    today = date.today()
    defaults = {
        "number": suggest_invoice_number(seller),
        "issue_date": today.isoformat(),
        "due_date": (today + timedelta(days=14)).isoformat(),
        "payment_terms": seller.get(
            "default_payment_terms", "Zahlbar innerhalb von 14 Tagen ohne Abzug."
        ),
    }
    draft = load_draft(request.args.get("from"))
    return render_template(
        "form.html",
        seller=seller,
        treatments=TAX_TREATMENTS,
        defaults=defaults,
        customers=load_customers(),
        units=UNITS,
        draft=draft,
    )


@app.route("/settings", methods=["POST"])
def settings():
    seller = apply_seller_form(load_seller(), request.form)
    save_seller(seller)
    flash("Stammdaten gespeichert.", "ok")
    return redirect(url_for("index"))


@app.route("/settings/autosave", methods=["POST"])
def settings_autosave():
    """Stammdaten beim Tippen sichern (ohne Redirect/Flash)."""
    seller = apply_seller_form(load_seller(), request.form)
    save_seller(seller)
    return ("", 204)


@app.route("/customers/autosave", methods=["POST"])
def customers_autosave():
    """Kunden beim Tippen sichern. prev_name erlaubt Umbenennen ohne Duplikat."""
    buyer = buyer_from_form(request.form)
    if not buyer["name"]:
        return ("", 204)
    prev = (request.form.get("prev_name") or "").strip().lower()
    customers = load_customers()
    target = None
    if prev:
        target = next((c for c in customers if c["name"].lower() == prev), None)
    if target is None:
        target = next(
            (c for c in customers if c["name"].lower() == buyer["name"].lower()), None
        )
    if target is None:
        customers.append(buyer)
    else:
        target.update(buyer)
    save_customers(customers)
    return {"name": buyer["name"]}


@app.route("/customers/items/save", methods=["POST"])
def customers_items_save():
    """Aktuelle Rechnungspositionen beim ausgewählten Kunden speichern (AJAX)."""
    name = request.form.get("buyer_name", "").strip()
    items = stored_items(parse_items(request.form))
    if not name:
        return {"ok": False, "error": "no_name"}, 400
    if not items:
        return {"ok": False, "error": "no_items"}, 400
    saved = save_customer_items(name, items, buyer_from_form(request.form))
    return {"ok": True, "name": name, "items": saved}


@app.route("/customers/save", methods=["POST"])
def customers_save():
    buyer = buyer_from_form(request.form)
    if not buyer["name"]:
        flash("Kundenname fehlt – nicht gespeichert.", "err")
        return redirect(url_for("index"))
    upsert_customer(buyer)
    flash(f"Kunde „{buyer['name']}“ gespeichert.", "ok")
    return redirect(url_for("index"))


@app.route("/customers/delete", methods=["POST"])
def customers_delete():
    customers = load_customers()
    idx = request.form.get("saved_customer", "")
    if idx.isdigit() and int(idx) < len(customers):
        removed = customers.pop(int(idx))
        save_customers(customers)
        flash(f"Kunde „{removed['name']}“ gelöscht.", "ok")
    else:
        flash("Kein Kunde ausgewählt.", "err")
    return redirect(url_for("index"))


@app.route("/preview-html", methods=["POST"])
def preview_html():
    """Live-HTML-Vorschau (gleiches Layout wie das PDF), für das Panel rechts."""
    _, html, _ = _assemble(request.form)
    return html


@app.route("/preview", methods=["POST"])
def preview():
    """PDF-Vorschau inline im Browser (wird nicht archiviert)."""
    data, html, _ = _assemble(request.form)
    if not data["items"]:
        msg = translate(get_ui_lang(request))["need_item"]
        return Response(
            f"<!doctype html><meta charset='utf-8'>"
            f"<body style='font:15px sans-serif;padding:40px;color:#b91c1c'>{msg}</body>",
            status=400,
            mimetype="text/html",
        )
    xml = build_xml(data)
    pdf = build_pdf(html, xml)
    return Response(
        pdf,
        mimetype="application/pdf",
        headers={"Content-Disposition": 'inline; filename="vorschau.pdf"'},
    )


@app.route("/generate", methods=["POST"])
def generate():
    seller = load_seller()
    data, html, totals = _assemble(request.form)
    if not data["items"]:
        flash(translate(get_ui_lang(request))["need_item"], "err")
        return redirect(url_for("index"))
    if data["invoice"]["tax_treatment"] in ("eu_reverse", "non_eu") and not data["buyer"].get("vat_id"):
        flash(translate(get_ui_lang(request))["need_buyer_vat"], "err")
        return redirect(url_for("index"))
    if data["invoice"]["profile"] == "xrechnung":
        missing = xrechnung_missing(seller, data["buyer"])
        if missing:
            ui = translate(get_ui_lang(request))
            flash(ui["need_xrechnung"] + " " + ", ".join(ui[k] for k in missing), "err")
            return redirect(url_for("index"))

    # Kunde automatisch sichern (anlegen/aktualisieren)
    upsert_customer(data["buyer"])

    inv_number = data["invoice"]["number"]
    xml = build_xml(data)
    pdf = build_pdf(html, xml)

    # Archivieren
    filename = f"Rechnung_{safe_name(inv_number)}.pdf"
    (OUTPUT_DIR / filename).write_bytes(pdf)

    # Sidecar mit den Formulardaten – ermöglicht „als Vorlage öffnen".
    sidecar = {"buyer": data["buyer"], "invoice": data["invoice"], "items": data["items"]}
    (OUTPUT_DIR / f"{Path(filename).stem}.json").write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Validierung des eingebetteten XML (Round-Trip aus dem fertigen PDF):
    # XSD-Struktur + EN16931-Geschäftsregeln (Schematron).
    embedded = extract_xml_from_pdf(pdf)
    ok, messages = validate_xml_bytes(embedded) if embedded else (False, ["Kein XML im PDF gefunden."])
    sch = validate_schematron(embedded) if embedded else None
    valid = ok and (not sch or not sch["available"] or sch["ok"])

    # Letzte Rechnungsnummer merken
    seller["last_invoice_number"] = inv_number
    save_seller(seller)

    return render_template(
        "result.html",
        filename=filename,
        inv=data["invoice"],
        buyer=data["buyer"],
        totals=totals,
        valid=valid,
        messages=messages,
        sch=sch,
    )


@app.route("/download/<path:filename>")
def download(filename):
    return _serve(filename, inline=False)


@app.route("/view/<path:filename>")
def view(filename):
    return _serve(filename, inline=True)


@app.route("/archive/delete", methods=["POST"])
def archive_delete():
    """Archivierte Rechnung (PDF + Sidecar-JSON) löschen – nur innerhalb OUTPUT_DIR."""
    filename = request.form.get("filename", "")
    path = OUTPUT_DIR / filename
    # Pfad-Traversal verhindern: nur einfache Dateinamen direkt im Ausgabeordner.
    if filename and path.name == filename and path.suffix == ".pdf" and path.exists():
        path.unlink()
        sidecar = OUTPUT_DIR / f"{path.stem}.json"
        if sidecar.exists():
            sidecar.unlink()
        flash(translate(get_ui_lang(request))["invoice_deleted"], "ok")
    return redirect(url_for("validate"))


def _serve(filename, inline):
    path = OUTPUT_DIR / filename
    if path.name != filename or not path.exists():
        abort(404)
    disp = "inline" if inline else "attachment"
    return Response(
        path.read_bytes(),
        mimetype="application/pdf",
        headers={"Content-Disposition": f'{disp}; filename="{filename}"'},
    )


def _version_gt(a: str, b: str) -> bool:
    """Ist Version a neuer als b? Tolerant ggü. Formaten wie '2025.2.0'."""

    def parts(v: str) -> list[int]:
        out = []
        for chunk in str(v).split("."):
            digits = "".join(c for c in chunk if c.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa > pb


def drafthorse_version_info() -> dict:
    """Installierte drafthorse-Version mit der neuesten auf PyPI vergleichen."""
    import importlib.metadata as meta

    info = {"current": None, "latest": None, "update_available": False, "error": None}
    try:
        info["current"] = meta.version("drafthorse")
    except meta.PackageNotFoundError:
        info["error"] = "not_installed"
        return info

    import json as _json
    import urllib.request as _req

    try:
        with _req.urlopen(
            "https://pypi.org/pypi/drafthorse/json", timeout=4
        ) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        info["latest"] = data["info"]["version"]
    except Exception:
        info["error"] = "offline"
        return info

    info["update_available"] = _version_gt(info["latest"], info["current"])
    return info


@app.route("/validate", methods=["GET", "POST"])
def validate():
    """Prüfseite: erzeugte Rechnungen erneut validieren oder Datei hochladen."""
    result = None
    if request.method == "POST":
        result = _validate_request()

    archive = []
    for p in sorted(OUTPUT_DIR.glob("*.pdf"), reverse=True):
        archive.append(
            {
                "filename": p.name,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "has_draft": (OUTPUT_DIR / f"{p.stem}.json").exists(),
            }
        )
    return render_template(
        "validate.html",
        result=result,
        archive=archive,
        depinfo=drafthorse_version_info(),
    )


def _validate_request():
    upload = request.files.get("file")
    filename = request.form.get("filename")
    if upload and upload.filename:
        raw = upload.read()
        label = upload.filename
    elif filename:
        path = OUTPUT_DIR / filename
        if path.name != filename or not path.exists():
            return {"label": filename, "ok": False, "messages": ["Datei nicht gefunden."]}
        raw = path.read_bytes()
        label = filename
    else:
        return None

    xml = raw if raw.lstrip().startswith(b"<") else extract_xml_from_pdf(raw)
    if not xml:
        return {"label": label, "ok": False, "xsd_messages": ["Kein eingebettetes XML gefunden."], "sch": None}
    xsd_ok, xsd_messages = validate_xml_bytes(xml)
    sch = validate_schematron(xml)
    overall = xsd_ok and (not sch["available"] or sch["ok"])
    return {
        "label": label,
        "ok": overall,
        "xsd_ok": xsd_ok,
        "xsd_messages": xsd_messages,
        "sch": sch,
    }


if __name__ == "__main__":
    import os

    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
