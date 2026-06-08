"""Lokale Web-App zur Erstellung von ZUGFeRD-E-Rechnungen."""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

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
from i18n import LANGUAGES, get_ui_lang, localize_rule
from i18n import t as translate
from zugferd import (
    TAX_TREATMENTS,
    _dec,
    build_pdf,
    build_xml,
    compute_totals,
    extract_xml_from_pdf,
    fmt_money,
    loc,
    q,
    validate_schematron,
    validate_xml_bytes,
)

# Als gebündelte .app (PyInstaller) liegen Code/Ressourcen schreibgeschützt im
# Bundle (sys._MEIPASS), Nutzerdaten gehören nach ~/Library/Application Support.
# Im normalen Quell-Start (run.sh / start.command) bleibt alles wie gehabt.
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    RESOURCE_BASE = Path(sys._MEIPASS)  # type: ignore[attr-defined]  # nur im Bundle
    BASE = Path.home() / "Library" / "Application Support" / "eRechnung"
    BASE.mkdir(parents=True, exist_ok=True)
else:
    RESOURCE_BASE = Path(__file__).parent
    BASE = Path(__file__).parent


def _patch_cffi_dlopen() -> None:
    """WeasyPrint lädt native Libs per Leaf-Name, z. B. cffi.dlopen('libpango-1.0.dylib').
    dlopen durchsucht das App-Bundle aber nicht. Wir mappen darum jeden gesuchten
    Namen, der als Datei im Bundle existiert, auf seinen absoluten Pfad.

    Bewusst OHNE DYLD_*-Variablen gelöst – die werden unter macOS Hardened Runtime
    (für die spätere Notarisierung nötig) ignoriert. Läuft vor dem ersten Import
    von WeasyPrint, da dieser erst in build_pdf() erfolgt."""
    import os as _os

    import cffi

    libdir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    _dbg = _os.environ.get("ERECHNUNG_DEBUG")

    # WeasyPrint probiert je Lib mehrere Namensvarianten der Reihe nach und nimmt
    # den ersten Treffer. Damit schon der ERSTE Versuch ins Bundle zeigt (und nicht
    # zufällig ein systemweit installiertes Homebrew-Pango erwischt), mappen wir
    # alle Varianten explizit auf die gebündelte Datei.
    _ALIASES = {
        "libgobject-2.0.0.dylib": ("libgobject-2.0-0", "gobject-2.0-0", "gobject-2.0"),
        "libpango-1.0.dylib": ("libpango-1.0-0", "pango-1.0-0", "pango-1.0"),
        "libharfbuzz.0.dylib": ("libharfbuzz-0", "harfbuzz", "harfbuzz-0.0"),
        "libharfbuzz-subset.0.dylib": ("libharfbuzz-subset-0", "harfbuzz-subset", "harfbuzz-subset-0.0"),
        "libfontconfig.1.dylib": ("libfontconfig-1", "fontconfig-1", "fontconfig"),
        "libpangoft2-1.0.dylib": ("libpangoft2-1.0-0", "pangoft2-1.0-0", "pangoft2-1.0"),
    }
    _name_map = {}
    for _file, _variants in _ALIASES.items():
        if (libdir / _file).exists():
            for _v in _variants:
                _name_map[_v] = str(libdir / _file)

    _orig = cffi.FFI.dlopen

    def _dlopen(self, name=None, *args, **kwargs):
        if name:
            if name in _name_map:
                name = _name_map[name]
            else:
                cand = libdir / Path(name).name
                if cand.exists():
                    name = str(cand)
            if _dbg:
                print(f"[patch] dlopen -> {name}", file=sys.stderr)
        return _orig(self, name, *args, **kwargs)

    cffi.FFI.dlopen = _dlopen


if FROZEN:
    _patch_cffi_dlopen()

CONFIG_FILE = BASE / "config.json"  # merkt sich den gewählten Datenordner


def _load_app_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _resolve_data_dir() -> Path:
    """Datenordner aus config.json (vom Nutzer wählbar, z. B. Dropbox);
    Fallback auf den App-Ordner. App bleibt offline – nur dieser Ordner zählt."""
    raw = (_load_app_config().get("data_dir") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            pass
    return BASE


def _drop_identical(src_dir: Path, ref_dir: Path) -> None:
    """Aus src_dir alle Datendateien entfernen, die in ref_dir byte-identisch
    vorliegen (sicheres 'Verschieben'/Aufräumen). Es wird nichts gelöscht, wenn
    die Kopie fehlt oder abweicht – Datenverlust ist damit ausgeschlossen."""
    if src_dir.resolve() == ref_dir.resolve():
        return
    import filecmp

    def rm(s: Path, r: Path) -> None:
        try:
            if s.is_file() and r.is_file() and filecmp.cmp(s, r, shallow=False):
                s.unlink()
        except OSError:
            pass

    rm(src_dir / "seller.json", ref_dir / "seller.json")
    rm(src_dir / "customers.json", ref_dir / "customers.json")
    src_out = src_dir / "output"
    if src_out.is_dir():
        for f in list(src_out.iterdir()):
            if f.is_file():
                rm(f, ref_dir / "output" / f.name)
        try:
            if not any(src_out.iterdir()):
                src_out.rmdir()
        except OSError:
            pass


DATA_DIR = _resolve_data_dir()
SELLER_FILE = DATA_DIR / "seller.json"
CUSTOMERS_FILE = DATA_DIR / "customers.json"
OUTPUT_DIR = DATA_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# Eigener Datenordner aktiv? Dann im App-Ordner verbliebene identische
# Kopien aufräumen (z. B. nach einem früheren Umzug).
_drop_identical(BASE, DATA_DIR)


def set_data_dir(raw: str):
    """Datenordner umstellen: prüfen, vorhandene Daten in den neuen Ordner
    verschieben (ohne zu überschreiben; Original erst nach verifizierter
    Kopie entfernt), Pfad speichern, globale Pfade aktualisieren. -> (ok, key)."""
    global DATA_DIR, SELLER_FILE, CUSTOMERS_FILE, OUTPUT_DIR
    import shutil

    raw = (raw or "").strip()
    target = BASE if not raw else Path(raw).expanduser()
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False, "data_dir_err_write"

    old = DATA_DIR
    if target.resolve() != old.resolve():
        # Vorhandene Daten in den neuen Ordner übernehmen, aber nichts
        # überschreiben (Recovery-Fall: Zielordner enthält schon Daten).
        (target / "output").mkdir(exist_ok=True)
        for name in ("seller.json", "customers.json"):
            src, dst = old / name, target / name
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)
        src_out = old / "output"
        if src_out.is_dir():
            for f in src_out.iterdir():
                dst = target / "output" / f.name
                if f.is_file() and not dst.exists():
                    shutil.copy2(f, dst)

    cfg = _load_app_config()
    cfg["data_dir"] = "" if target.resolve() == BASE.resolve() else str(target)
    try:
        CONFIG_FILE.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        return False, "data_dir_err_save"

    DATA_DIR = target
    SELLER_FILE = target / "seller.json"
    CUSTOMERS_FILE = target / "customers.json"
    OUTPUT_DIR = target / "output"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Verschieben abschließen: identische Originale im alten Ordner entfernen.
    if target.resolve() != old.resolve():
        _drop_identical(old, target)
    return True, "data_dir_ok"

def _file_info(p: Path) -> dict:
    try:
        ts = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        ts = "?"
    return {"path": str(p), "modified": ts}


def data_conflicts() -> list:
    """Mögliche Datenkonflikte erkennen (nie automatisch auflösen):
    - abweichende/verwaiste Kopien im App-Ordner, wenn ein eigener Datenordner aktiv ist
    - Dropbox-/Sync-Konfliktkopien im aktiven Datenordner."""
    import filecmp

    out = []
    if DATA_DIR.resolve() != BASE.resolve():
        for name in ("seller.json", "customers.json"):
            s, r = BASE / name, DATA_DIR / name
            if s.is_file() and r.is_file():
                try:
                    same = filecmp.cmp(s, r, shallow=False)
                except OSError:
                    same = True
                if not same:
                    out.append(
                        {"type": "leftover", "name": name,
                         "a": _file_info(s), "b": _file_info(r)}
                    )
            elif s.is_file() and not r.is_file():
                out.append({"type": "orphan", "name": name, "a": _file_info(s)})

    markers = ("conflicted copy", "in konflikt stehende", "in-konflikt", "konfliktkopie")
    for d in (DATA_DIR, DATA_DIR / "output"):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.is_file() and any(m in f.name.lower() for m in markers):
                    out.append({"type": "sync", "name": f.name, "a": _file_info(f)})
    return out


app = Flask(
    __name__,
    template_folder=str(RESOURCE_BASE / "templates"),
    static_folder=str(RESOURCE_BASE / "static"),
)
# Flash-Messages signieren. Lokal/Single-User: aus Env, sonst pro Start zufällig
# (kein hartkodiertes Secret mehr; Flash überlebt einen Neustart nicht – egal hier).
app.secret_key = os.environ.get("ERECHNUNG_SECRET_KEY") or secrets.token_hex(32)
# Upload-/Form-Größe begrenzen (Schutz vor Speicher-DoS über /validate).
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB
# Templates bei Änderung neu laden, ohne Server-Neustart (Quell-Start). Vernachlässig-
# barer Aufwand lokal; verhindert „neues CSS auf altem HTML" nach einem git pull.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# Die App ist ein rein lokales Tool (127.0.0.1). Hostnamen, die als „lokal"
# gelten – schützt gegen DNS-Rebinding und Cross-Site-Zugriffe von Webseiten.
LOCAL_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


def _netloc_is_local(netloc: str | None) -> bool:
    """True, wenn host[:port] auf 127.0.0.1/localhost/::1 zeigt."""
    if not netloc:
        return False
    try:
        host = urlparse("//" + netloc).hostname
    except ValueError:
        return False
    return host in LOCAL_HOSTNAMES


@app.before_request
def _guard_local_only():
    """Zwei Schutzschichten für das localhost-Tool:
    1) Host-Header muss lokal sein  -> blockt DNS-Rebinding.
    2) Bei zustandsändernden Methoden muss Origin/Referer lokal sein -> blockt
       CSRF (eine fremde Webseite kann sonst Formulare an 127.0.0.1 senden und
       z. B. die Bankverbindung in den Stammdaten überschreiben)."""
    if not _netloc_is_local(request.host):
        abort(403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin is not None:
            if not _netloc_is_local(urlparse(origin).netloc):
                abort(403)
        else:
            referer = request.headers.get("Referer")
            if referer is not None and not _netloc_is_local(urlparse(referer).netloc):
                abort(403)


@app.template_global()
def asset_version(filename: str) -> str:
    """Cache-Busting-Token aus der mtime der Static-Datei – automatisch, ohne
    manuelles Hochzählen von ?v=. Ändert sich die Datei, ändert sich das Token."""
    try:
        return str(int((RESOURCE_BASE / "static" / filename).stat().st_mtime))
    except OSError:
        return "0"


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
    "account_name", "payment_term_days",
]


def apply_seller_form(seller: dict, form) -> dict:
    for field in SELLER_FIELDS:
        if field in form:
            seller[field] = form.get(field, "").strip()
    # Checkbox "Steuernummer ausblenden": aktiv -> show_tax_number = False.
    seller["show_tax_number"] = form.get("hide_tax_number") is None
    return seller


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


# Einheiten: menschenlesbares Label (de/en) -> UN/ECE-Code (für das XML).
UNITS = [
    ("HUR", {"de": "Stunde", "en": "Hour"}, {"de": "Stunden", "en": "Hours"}),
    ("DAY", {"de": "Tag", "en": "Day"}, {"de": "Tage", "en": "Days"}),
    ("WEE", {"de": "Woche", "en": "Week"}, {"de": "Wochen", "en": "Weeks"}),
    ("MON", {"de": "Monat", "en": "Month"}, {"de": "Monate", "en": "Months"}),
    ("ANN", {"de": "Jahr", "en": "Year"}, {"de": "Jahre", "en": "Years"}),
    ("C62", {"de": "Stück", "en": "Piece"}, {"de": "Stück", "en": "Pieces"}),
    ("LS", {"de": "Pauschal", "en": "Lump sum"}, {"de": "Pauschal", "en": "Lump sum"}),
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
    discount_reasons = form.getlist("item_discount_reason")
    for i, (desc, qty, unit, price) in enumerate(
        zip(
            form.getlist("description"),
            form.getlist("quantity"),
            form.getlist("unit"),
            form.getlist("unit_price"),
            strict=False,  # bei abweichenden Längen am kürzesten enden (defensiv)
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
                "item_discount_reason": (discount_reasons[i].strip() if i < len(discount_reasons) else "") or None,
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


def render_invoice_preview(seller, buyer, inv, items, mode=""):
    """Rechnungs-HTML rendern – für Live-Vorschau und Archiv-Vorschau gleichermaßen.
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
    html = render_template(
        "invoice_pdf.html",
        ti=translate(inv_lang),
        body_class=body_class,
        seller=seller,
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


def _assemble(form):
    """Formulardaten -> (data-dict, gerendertes HTML, totals-bundle)."""
    seller = load_seller()
    items = parse_items(form)
    inv_lang = form.get("language", "") or get_ui_lang(request)
    _pay_days = payment_days(form)
    # Eingaben gegen erlaubte Werte prüfen, damit manipulierte Formulardaten keine
    # KeyError/Exception (und damit 500/Debugger) auslösen.
    tax_treatment = form.get("tax_treatment", "de_19")
    if tax_treatment not in TAX_TREATMENTS:
        tax_treatment = "de_19"
    profile = form.get("profile", "en16931")
    if profile not in ("en16931", "xrechnung"):
        profile = "en16931"
    doc_type = form.get("doc_type", "380") or "380"
    if doc_type not in ("380", "381", "384", "386"):
        doc_type = "380"
    inv = {
        "number": form.get("number", "").strip(),
        "issue_date": form.get("issue_date"),
        "due_date": form.get("due_date") or None,
        "service_start": form.get("service_start") or None,
        "service_end": form.get("service_end") or None,
        "currency": form.get("currency", "EUR"),
        "tax_treatment": tax_treatment,
        "language": inv_lang,
        "profile": profile,
        "note": form.get("note", "").strip() or None,
        # Zahlungsbedingung aus dem Fälligkeitsdatum ableiten und in der
        # Rechnungssprache formulieren (erscheint im PDF-Schluss + BT-20).
        "payment_terms": (
            payment_terms_text(_pay_days, inv_lang) if _pay_days is not None else None
        ),
        "doc_type": doc_type,
        "ref_number": form.get("ref_number", "").strip() or None,
        "ref_date": form.get("ref_date") or None,
        "discount": (form.get("discount", "0") or "0").replace(",", ".").strip() or "0",
        "discount_type": "abs" if form.get("discount_type") == "abs" else "pct",
        "discount_reason": form.get("discount_reason", "").strip() or None,
        "prepaid": (form.get("prepaid", "0") or "0").replace(",", ".").strip() or "0",
        "prepaid_ref": form.get("prepaid_ref", "").strip() or None,
    }
    buyer = buyer_from_form(form)
    data = {"seller": seller, "buyer": buyer, "invoice": inv, "items": items}

    html, (line_total, discount, tax_basis, tax_total, grand_total, treatment) = \
        render_invoice_preview(seller, buyer, inv, items, mode=form.get("_full") or "")
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
def used_invoice_numbers() -> list[str]:
    """Bereits vergebene Rechnungsnummern im Archiv (für den Live-Hinweis im Formular).
    Quelle ist primär die Sidecar-JSON (exakt), sonst der Dateiname."""
    nums = set()
    for p in OUTPUT_DIR.glob("*.pdf"):
        sidecar = OUTPUT_DIR / f"{p.stem}.json"
        num = None
        if sidecar.exists():
            try:
                num = (json.loads(sidecar.read_text(encoding="utf-8")).get("invoice") or {}).get("number")
            except (ValueError, OSError):
                num = None
        if not num and p.stem.startswith("Rechnung_"):
            num = p.stem[len("Rechnung_"):]
        if num:
            nums.add(num.strip())
    return sorted(nums)


def archived_invoices() -> list[dict]:
    """Im Tool erzeugte Rechnungen als {number, date} aus den Sidecars – für den
    Bezugs-Auswähler bei Storno/Korrektur. Neueste zuerst, je Nummer einmal."""
    rows = []
    for p in OUTPUT_DIR.glob("*.pdf"):
        sidecar = OUTPUT_DIR / f"{p.stem}.json"
        if not sidecar.exists():
            continue
        try:
            inv = json.loads(sidecar.read_text(encoding="utf-8")).get("invoice") or {}
        except (ValueError, OSError):
            continue
        num = (inv.get("number") or "").strip()
        if num:
            rows.append({"number": num, "date": inv.get("issue_date") or ""})
    seen, uniq = set(), []
    for r in sorted(rows, key=lambda r: (r["date"], r["number"]), reverse=True):
        if r["number"] in seen:
            continue
        seen.add(r["number"])
        uniq.append(r)
    return uniq


@app.route("/")
def index():
    seller = load_seller()
    today = date.today()
    try:
        term_days = int(seller.get("payment_term_days") or 14)
    except (TypeError, ValueError):
        term_days = 14
    defaults = {
        "number": suggest_invoice_number(seller),
        "issue_date": today.isoformat(),
        "due_date": (today + timedelta(days=term_days)).isoformat(),
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
        used_numbers=used_invoice_numbers(),
        ref_invoices=archived_invoices(),
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
    name = request.form.get("buyer_name", "").strip()
    customers = load_customers()
    match = next(
        (c for c in customers if c.get("name", "").strip().lower() == name.lower()),
        None,
    ) if name else None
    if match:
        customers.remove(match)
        save_customers(customers)
        flash(f"Kunde „{match['name']}“ gelöscht.", "ok")
    else:
        flash("Kein gespeicherter Kunde mit diesem Namen.", "err")
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


@app.route("/preview-pdf", methods=["POST"])
def preview_pdf():
    """Visuelle PDF-Vorschau (ohne ZUGFeRD-XML-Einbettung) für die ausgeklappte
    Ansicht – zeigt die echten Seitenumbrüche, deutlich schneller als die volle
    Erzeugung (die Seitenumbrüche sind identisch; nur das XML fehlt). Rendert auch
    ohne Positionen das Template (wie die Mini-Vorschau)."""
    _, html, _ = _assemble(request.form)
    import weasyprint

    base_url = str(Path(__file__).resolve().parent)
    pdf = weasyprint.HTML(string=html, base_url=base_url).write_pdf()
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
    # Storno (381) / Korrektur (384) brauchen den Bezug zur Originalrechnung (BT-25).
    if data["invoice"]["doc_type"] in ("381", "384") and not data["invoice"].get("ref_number"):
        flash(translate(get_ui_lang(request))["need_ref"], "err")
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

    # Archivieren – eine vorhandene Datei NIE überschreiben. Wird dieselbe
    # Rechnungsnummer erneut verwendet (z. B. versehentlich), würde sonst eine
    # evtl. korrekte Rechnung still zerstört. Bei Kollision eindeutigen Namen
    # vergeben; beide bleiben im Archiv sichtbar, der Fehler ist korrigierbar.
    stem = f"Rechnung_{safe_name(inv_number)}"
    duplicate = (OUTPUT_DIR / f"{stem}.pdf").exists()
    name, n = stem, 2
    while (OUTPUT_DIR / f"{name}.pdf").exists():
        name = f"{stem} ({n})"
        n += 1
    filename = f"{name}.pdf"
    (OUTPUT_DIR / filename).write_bytes(pdf)

    # Sidecar mit den Formulardaten – ermöglicht „als Vorlage öffnen" und die
    # Archiv-Vorschau. seller wird mitgespeichert, damit die Vorschau dem Stand
    # zum Erzeugungszeitpunkt entspricht (auch wenn die Stammdaten sich ändern).
    sidecar = {
        "seller": seller, "buyer": data["buyer"],
        "invoice": data["invoice"], "items": data["items"],
    }
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
        duplicate=duplicate,
    )


@app.route("/download/<path:filename>")
def download(filename):
    return _serve(filename, inline=False)


@app.route("/view/<path:filename>")
def view(filename):
    return _serve(filename, inline=True)


@app.route("/archive/preview/<path:filename>")
def archive_preview(filename):
    """HTML-Vorschau einer archivierten Rechnung aus ihrer Sidecar-JSON – gleicher
    Look wie die Live-Vorschau. Nur für app-erzeugte Rechnungen (mit Sidecar)."""
    draft = load_draft(filename)
    if not draft:
        return abort(404)
    seller = draft.get("seller") or load_seller()  # Altbestände ohne seller -> aktuell
    html, _ = render_invoice_preview(
        seller, draft.get("buyer") or {}, draft.get("invoice") or {},
        draft.get("items") or [], mode="mini",
    )
    return html


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

    info: dict[str, Any] = {"current": None, "latest": None, "update_available": False, "error": None}
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


def _settings_context() -> dict:
    """Gemeinsamer Kontext für die Einstellungen/Archiv (Vollseite + In-Place-Panel)."""
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
    return {
        "archive": archive,
        "data_dir": str(DATA_DIR),
        "data_dir_custom": DATA_DIR.resolve() != BASE.resolve(),
        "can_browse": (sys.platform == "darwin"),
        "conflicts": data_conflicts(),
    }


def _localized_validation():
    """Datei-/Archiv-Prüfung auswerten und Schematron-Texte lokalisieren."""
    result = _validate_request()
    if result:
        lang = get_ui_lang(request)
        sch = result.get("sch")
        if sch and sch.get("available"):
            sch["errors"] = [localize_rule(m, lang) for m in sch["errors"]]
            sch["warnings"] = [localize_rule(m, lang) for m in sch["warnings"]]
    return result


@app.route("/validate", methods=["GET", "POST"])
def validate():
    """Prüfseite (Vollseite, Fallback). Erzeugte Rechnungen prüfen oder Datei hochladen."""
    result = _localized_validation() if request.method == "POST" else None
    return render_template(
        "validate.html", result=result, depinfo=drafthorse_version_info(),
        **_settings_context(),
    )


@app.route("/settings/panel", methods=["GET", "POST"])
def settings_panel():
    """Einstellungen/Archiv als HTML-Fragment für das In-Place-Panel auf der Startseite.
    Die Versionsprüfung (PyPI, langsam) wird separat per /settings/depinfo nachgeladen."""
    result = _localized_validation() if request.method == "POST" else None
    return render_template(
        "settings_panel.html", result=result, lazy_deps=True, inplace=True,
        **_settings_context(),
    )


@app.route("/settings/depinfo")
def settings_depinfo():
    """Nur die Versions-Karte (wird vom Panel asynchron nachgeladen)."""
    return render_template("_deps_card.html", depinfo=drafthorse_version_info())


@app.route("/export/csv")
def export_csv():
    """Rechnungen als Buchungsjournal-CSV (für eigene Buchhaltung/EÜR/USt-VA).
    Optional gefiltert über ?from=YYYY-MM-DD&to=YYYY-MM-DD oder eine Einzelrechnung
    über ?file=<dateiname>. Quelle ist die Sidecar-JSON (nur app-erzeugte Rechnungen)."""
    import csv
    import io

    lang = get_ui_lang(request)
    de = lang != "en"
    frm = (request.args.get("from") or "").strip()
    to = (request.args.get("to") or "").strip()
    only = request.args.get("file")

    def fnum(value):
        s = f"{value:.2f}"
        return s.replace(".", ",") if de else s

    rows = []
    for p in OUTPUT_DIR.glob("*.pdf"):
        sidecar = OUTPUT_DIR / f"{p.stem}.json"
        if not sidecar.exists() or (only and p.name != only):
            continue
        try:
            d = json.loads(sidecar.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        inv = d.get("invoice") or {}
        issue = inv.get("issue_date") or ""
        if (frm and issue < frm) or (to and issue > to):
            continue
        treatment = TAX_TREATMENTS.get(inv.get("tax_treatment") or "de_19", TAX_TREATMENTS["de_19"])
        _c, _lt, _disc, net, vat, gross = compute_totals(
            d.get("items") or [], cast(Decimal, treatment["rate"]),
            _dec(inv.get("discount") or "0"), inv.get("discount_type") or "abs",
        )
        buyer = d.get("buyer") or {}
        rows.append([
            inv.get("number", ""), issue, buyer.get("name", ""), buyer.get("country", ""),
            loc(treatment["label"], lang), treatment["category"], str(treatment["rate"]),
            fnum(net), fnum(vat), fnum(gross), inv.get("currency", "EUR"),
        ])
    rows.sort(key=lambda r: (r[1], r[0]))  # nach Datum, dann Nummer

    header = (
        ["Nummer", "Datum", "Kunde", "Land", "Behandlung", "USt-Code",
         "USt-Satz %", "Netto", "USt-Betrag", "Brutto", "Währung"] if de else
        ["Number", "Date", "Customer", "Country", "Treatment", "VAT code",
         "VAT rate %", "Net", "VAT amount", "Gross", "Currency"]
    )
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";" if de else ",")
    writer.writerow(header)
    writer.writerows(rows)
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")  # BOM -> Umlaute in Excel
    name = f"{Path(only).stem}.csv" if only else "rechnungen.csv"
    return Response(
        data, mimetype="text/csv",  # Flask ergänzt charset=utf-8 automatisch
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.route("/data-dir", methods=["POST"])
def data_dir_set():
    ok, key = set_data_dir(request.form.get("data_dir", ""))
    ui = translate(get_ui_lang(request))
    flash(ui.get(key, key), "ok" if ok else "err")
    return redirect(url_for("validate"))


@app.route("/data-dir/browse", methods=["POST"])
def data_dir_browse():
    """Nativen Ordner-Dialog öffnen (lokal, macOS) und gewählten Pfad zurückgeben."""
    import subprocess

    if sys.platform != "darwin":
        return {"ok": False, "error": "unsupported"}
    script = (
        'POSIX path of (choose folder with prompt "Datenordner wählen" '
        "default location (path to home folder))"
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=600
        )
    except Exception:
        return {"ok": False, "error": "failed"}
    if r.returncode != 0:  # vom Nutzer abgebrochen
        return {"ok": True, "path": None}
    return {"ok": True, "path": r.stdout.strip() or None}


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

    if raw.lstrip().startswith(b"<"):
        xml = raw
    else:
        try:
            xml = extract_xml_from_pdf(raw)
        except Exception:  # defektes/manipuliertes PDF darf nicht crashen
            xml = None
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

    # Debugger standardmäßig AUS: der Werkzeug-Debugger erlaubt sonst bei jeder
    # Exception Code-Ausführung und leakt Quellcode/Variablen (z. B. Bankdaten).
    # Nur bei Bedarf in der Entwicklung via FLASK_DEBUG=1 einschalten.
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=debug)
