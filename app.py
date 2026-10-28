"""Lokale Web-App zur Erstellung von ZUGFeRD-E-Rechnungen."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import sys
import tempfile
import threading
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
    g,
    has_request_context,
    redirect,
    render_template,
    request,
    url_for,
)

from countries import COUNTRIES
from i18n import LANGUAGES, get_ui_lang, localize_rule
from i18n import t as translate
from version import __version__ as APP_VERSION
from whats_new import ANNOUNCEMENT
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
    render_html_pdf,
    validate_schematron,
    validate_xml_bytes,
)

logger = logging.getLogger("erechnung")

# Als gebündelte .app (PyInstaller) liegen Code/Ressourcen schreibgeschützt im
# Bundle (sys._MEIPASS), Nutzerdaten gehören nach ~/Library/Application Support.
# Im normalen Quell-Start (run.sh / start.command) bleibt alles wie gehabt.
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    RESOURCE_BASE = Path(sys._MEIPASS)  # type: ignore[attr-defined]  # nur im Bundle
    BASE = Path.home() / "Library" / "Application Support" / "eRechnung"
else:
    RESOURCE_BASE = Path(__file__).parent
    BASE = Path(__file__).parent


if "--selftest" in sys.argv:
    _SELFTEST_DIR = tempfile.TemporaryDirectory(prefix="erechnung-selftest-")
    BASE = Path(_SELFTEST_DIR.name)
BASE.mkdir(parents=True, exist_ok=True)


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

CONFIG_FILE = BASE / "config.json"  # Datenordner und lokal gelesene Feature-Hinweise


def _load_app_config() -> dict:
    try:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return config if isinstance(config, dict) else {}
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
    profile_files = _issuer_data_files(src_dir)
    for issuer in {p.parts[1] for p in profile_files}:
        files = [p for p in profile_files if p.parts[1] == issuer]
        try:
            identical = all((ref_dir / p).is_file() and filecmp.cmp(src_dir / p, ref_dir / p, shallow=False)
                            for p in files)
        except OSError:
            identical = False
        if identical:
            for relative in files:
                rm(src_dir / relative, ref_dir / relative)
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


def _issuer_data_files(directory: Path) -> list[Path]:
    """Only app-managed issuer files, never symlinked external directories."""
    root = directory / "issuers"
    if not root.is_dir() or root.is_symlink():
        return []
    files: list[Path] = []
    for profile in root.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", profile.name) or not profile.is_dir() or profile.is_symlink():
            continue
        paths = [profile / "seller.json"]
        out = profile / "output"
        if out.is_dir() and not out.is_symlink():
            paths.extend(out.iterdir())
        files.extend(p.relative_to(directory) for p in paths if p.is_file() and not p.is_symlink())
    return files


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
    # A profile/output folder cannot become the shared data root (or vice versa).
    # Otherwise moving data would reclassify one issuer's invoices as another's.
    if target.resolve() != old.resolve() and any(
        target.resolve().is_relative_to((old / name).resolve())
        or old.resolve().is_relative_to((target / name).resolve())
        for name in ("issuers", "output")
    ):
        return False, "data_dir_err_nested"
    if target.resolve() != old.resolve():
        # Reject partial merges of the same profile before moving anything.
        # A conflicting copy needs a deliberate choice, not an automatic overwrite.
        import filecmp

        try:
            for relative in _issuer_data_files(old):
                dst = target / relative
                if any(p.is_symlink() for p in (target / "issuers", dst.parent, dst.parent.parent, dst)):
                    return False, "data_dir_err_write"
                if dst.exists() and (not dst.is_file() or not filecmp.cmp(old / relative, dst, shallow=False)):
                    return False, "issuer_move_conflict"
        except OSError:
            return False, "data_dir_err_write"
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
        for relative in _issuer_data_files(old):
            src, dst = old / relative, target / relative
            # An existing target must never redirect a copy outside its data folder.
            if any(p.is_symlink() for p in (target / "issuers", dst.parent, dst.parent.parent, dst)):
                return False, "data_dir_err_write"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copy2(src, dst)
            if relative.name == "seller.json":
                if (dst.parent / "output").is_symlink():
                    return False, "data_dir_err_write"
                (dst.parent / "output").mkdir(exist_ok=True)

    cfg = _load_app_config()
    cfg["data_dir"] = "" if target.resolve() == BASE.resolve() else str(target)
    try:
        _write_json(CONFIG_FILE, cfg)
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
    if has_request_context():
        _select_issuer()
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
    profile_dirs = {p.parent for p in _issuer_data_files(DATA_DIR)}
    for d in (DATA_DIR, DATA_DIR / "output", *(DATA_DIR / p for p in profile_dirs)):
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
DATA_LOCK = threading.RLock()

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


@app.before_request
def _lock_data_changes():
    # Serialize writes in the threaded local server, including read-modify-write
    # operations. Pure previews do not need to wait for invoice generation.
    if request.method == "POST" and request.endpoint in {
        "settings", "settings_autosave", "customers_autosave",
        "customers_items_save", "customers_save", "customers_delete",
        "generate", "archive_delete", "data_dir_set", "whats_new_seen", "issuer_create",
    }:
        DATA_LOCK.acquire()
        g.data_locked = True


@app.teardown_request
def _unlock_data_changes(error):
    if g.pop("data_locked", False):
        DATA_LOCK.release()


def _write_json(path: Path, data) -> None:
    # Readers always see the complete old or new file, even during autosave.
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=path.parent, delete=False) as f:
            name = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


# The original issuer stays at the original paths. Additional issuers have their
# own seller.json and output directory; customers remain shared. Never switch
# global paths when selecting an issuer: concurrent tabs must remain independent.
def issuer_directory(issuer: str) -> Path:
    if issuer == "default":
        return SELLER_FILE.parent
    if not re.fullmatch(r"[a-f0-9]{32}", issuer):
        abort(400)
    root = SELLER_FILE.parent / "issuers"
    directory = root / issuer
    if root.is_symlink() or directory.is_symlink() or not directory.is_dir():
        abort(404)
    if not (directory / "seller.json").is_file() or (directory / "seller.json").is_symlink():
        abort(404)
    if (directory / "output").is_symlink():
        abort(404)
    return directory


@app.before_request
def _select_issuer():
    if request.endpoint == "static":
        return
    values = request.args.getlist("issuer") + request.form.getlist("issuer")
    if len(set(values)) > 1:
        abort(400)
    issuer = values[0] if values else "default"
    directory = issuer_directory(issuer)
    g.issuer_id = issuer
    g.issuer_seller_file = SELLER_FILE if issuer == "default" else directory / "seller.json"
    g.issuer_output_dir = OUTPUT_DIR if issuer == "default" else directory / "output"


def current_issuer() -> str:
    return g.get("issuer_id", "default") if has_request_context() else "default"


def seller_file() -> Path:
    return g.get("issuer_seller_file", SELLER_FILE) if has_request_context() else SELLER_FILE


def output_dir() -> Path:
    return g.get("issuer_output_dir", OUTPUT_DIR) if has_request_context() else OUTPUT_DIR


@app.url_defaults
def _issuer_urls(endpoint, values):
    if endpoint != "static" and current_issuer() != "default":
        values.setdefault("issuer", current_issuer())


def issuer_label(seller: dict) -> str:
    return seller.get("profile_label") or seller.get("name") or translate(get_ui_lang(request))["issuer_default"]


def issuer_profiles() -> list[dict]:
    ids = ["default"]
    root = SELLER_FILE.parent / "issuers"
    if root.is_dir() and not root.is_symlink():
        ids += sorted(p.name for p in root.iterdir()
                      if re.fullmatch(r"[a-f0-9]{32}", p.name) and p.is_dir() and not p.is_symlink()
                      and (p / "seller.json").exists())
    profiles = []
    for issuer in ids:
        path = SELLER_FILE if issuer == "default" else root / issuer / "seller.json"
        if path.is_symlink():
            continue
        try:
            seller = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            profiles.append({"id": issuer, "label": issuer_label(seller)})
        except (OSError, ValueError, AttributeError):
            # Keep an unreadable profile visible; selecting it surfaces the error
            # instead of silently creating a replacement with a fresh counter.
            profiles.append({"id": issuer, "label": translate(get_ui_lang(request))["issuer_unavailable"]})
    return profiles


@app.context_processor
def _issuer_context():
    return {"issuer_id": current_issuer(), "issuer_name": issuer_label(load_seller())}


@app.route("/issuers/create", methods=["POST"])
def issuer_create():
    label = request.form.get("profile_label", "").strip()
    if not label or len(label) > 100:
        abort(400)
    issuer = secrets.token_hex(16)
    root = SELLER_FILE.parent / "issuers"
    if root.is_symlink():
        abort(400)
    directory = root / issuer
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "output").mkdir()
    _write_json(directory / "seller.json", {"country": "DE", "profile_label": label})
    return redirect(url_for("index", issuer=issuer))


@app.template_filter("price")
def price_filter(value, lang="de"):
    amount = _dec(value)
    decimals = max(2, -int(amount.normalize().as_tuple().exponent))
    text = f"{amount:,.{decimals}f}"
    return text if lang == "en" else text.translate(str.maketrans(",.", ".,"))


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
        "is_desktop": bool(app.config.get("DESKTOP")),
        "whats_new": whats_new_context(lang),
    }


def whats_new_context(lang: str) -> dict | None:
    if not ANNOUNCEMENT or not ANNOUNCEMENT["items"]:
        return None
    seen = _load_app_config().get("seen_announcements", [])
    return {
        "id": ANNOUNCEMENT["id"],
        "version": ANNOUNCEMENT["version"],
        "auto_open": ANNOUNCEMENT.get("auto_open") is True,
        "seen": isinstance(seen, list) and ANNOUNCEMENT["id"] in seen,
        "items": [{"icon": item["icon"], "title": loc(item["title"], lang),
                   "text": loc(item["text"], lang)} for item in ANNOUNCEMENT["items"]],
    }


@app.route("/whats-new/seen", methods=["POST"])
def whats_new_seen():
    data = request.get_json(silent=True)
    if not ANNOUNCEMENT or not ANNOUNCEMENT["items"]:
        return abort(404)
    if not isinstance(data, dict) or data.get("id") != ANNOUNCEMENT["id"]:
        return abort(400)
    config = _load_app_config()
    seen = config.get("seen_announcements", [])
    if not isinstance(seen, list):
        seen = []
    if ANNOUNCEMENT["id"] not in seen:
        config["seen_announcements"] = [*seen, ANNOUNCEMENT["id"]]
        try:
            _write_json(CONFIG_FILE, config)
        except OSError:
            logger.warning("Could not save announcement state", exc_info=True)
            return {"ok": False}, 503
    return {"ok": True}


@app.route("/setlang/<code>")
def setlang(code):
    resp = redirect(request.referrer or url_for("index"))
    if code in LANGUAGES:
        resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365)
    return resp


# --- Persistenz ------------------------------------------------------------
def load_seller() -> dict:
    if seller_file().exists():
        return json.loads(seller_file().read_text(encoding="utf-8"))
    return {"country": "DE"}


def save_seller(data: dict) -> None:
    _write_json(seller_file(), data)


SELLER_FIELDS = [
    "profile_label", "name", "subtitle", "address_line", "postcode", "city", "country", "vat_id",
    "tax_number", "email", "phone", "web", "iban", "bic", "bank_name",
    "account_name",
    # Hauptkonto-Kontotyp + Nicht-IBAN-Felder (International): Kontonummer,
    # Routing/ABA und SWIFT stehen neben den flachen IBAN-Feldern.
    "bank_kind", "account_number", "routing", "swift",
]


def apply_seller_form(seller: dict, form) -> dict:
    for field in SELLER_FIELDS:
        if field in form:
            seller[field] = form.get(field, "").strip()
    # Checkbox "Steuernummer ausblenden": aktiv -> show_tax_number = False.
    seller["show_tax_number"] = form.get("hide_tax_number") is None
    # Logo (Briefkopf) als data-URI – nur echte Bild-URIs akzeptieren, Größe deckeln
    # (~1,5 MB data-URI), damit seller.json nicht unbegrenzt wächst.
    if "logo" in form:
        logo = form.get("logo", "").strip()
        seller["logo"] = logo if logo.startswith("data:image/") and len(logo) <= 1_500_000 else ""
    # Weitere Bankkonten (optional). Das Hauptkonto bleibt in den flachen Feldern
    # (iban/bic/...); zusätzliche Konten landen in seller["accounts"]. Nur anfassen,
    # wenn das Formular die Sektion wirklich enthält -> Teil-Posts wischen nichts weg.
    if form.get("has_accounts_section"):
        kinds = form.getlist("acct_kind")
        holders = form.getlist("acct_account_name")
        banks = form.getlist("acct_bank_name")
        ibans = form.getlist("acct_iban")
        bics = form.getlist("acct_bic")
        accnums = form.getlist("acct_account_number")
        routings = form.getlist("acct_routing")
        swifts = form.getlist("acct_swift")

        def at(lst: list, j: int) -> str:
            return lst[j].strip() if j < len(lst) else ""

        # Jede Konto-Zeile liefert genau einen Eintrag in jeder getlist (alle Felder
        # sind stets im DOM), daher fluchten die Listen über den Zeilenindex.
        extras = []
        n = max(len(kinds), len(ibans), len(accnums))
        for i in range(n):
            if at(kinds, i) == "intl":
                accnum = at(accnums, i)
                if not accnum:  # leere Blöcke überspringen
                    continue
                extras.append({
                    "kind": "intl", "account_name": at(holders, i),
                    "bank_name": at(banks, i), "account_number": accnum,
                    "routing": at(routings, i), "swift": at(swifts, i),
                })
            else:
                iban = at(ibans, i)
                if not iban:  # leere Blöcke überspringen
                    continue
                extras.append({
                    "kind": "iban", "account_name": at(holders, i),
                    "bank_name": at(banks, i), "iban": iban, "bic": at(bics, i),
                })
        seller["accounts"] = extras
    return seller


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
    _write_json(CUSTOMERS_FILE, customers)


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
        # Optionales kundenspezifisches Zahlungsziel (überschreibt den Standard;
        # nur fürs Vorbelegen von "Fällig am" – das Datum selbst bleibt maßgeblich).
        "payment_term_days": form.get("buyer_payment_term_days", "").strip(),
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


def format_seller_country(seller: dict, buyer: dict, lang: str) -> str:
    """Absenderland in Rechnungssprache, wenn der Kunde im Ausland sitzt."""
    seller_country = (seller.get("country") or "DE").strip().upper() or "DE"
    buyer_country = (buyer.get("country") or "DE").strip().upper() or "DE"
    if seller_country == buyer_country:
        return ""
    return loc(COUNTRY_NAME.get(seller_country, {"de": seller_country, "en": seller_country}), lang)


# --- Helfer ----------------------------------------------------------------
def suggest_invoice_number(seller: dict) -> str:
    last = seller.get("last_invoice_number", "")
    year = date.today().year
    m = re.fullmatch(r"(\d{4})-(\d+)", last or "")
    if m and int(m.group(1)) == year:
        return f"{year}-{int(m.group(2)) + 1:03d}"
    return f"{year}-001"


def _num_str(s) -> str:
    """Zahleneingabe robust zu einem Punkt-Dezimal-String normalisieren – muss mit
    num() in static/calc.js übereinstimmen, sonst weichen Vorschau und PDF ab.
    Komma = Dezimaltrenner -> Tausender-Punkte entfernen, Komma zu Punkt; ohne
    Komma bleibt der Punkt der Dezimaltrenner."""
    s = str(s or "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") >= 2:  # "1.234.567" = Tausender (kein Komma) -> Punkte raus
        s = s.replace(".", "")
    return s or "0"


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
        unit_code = unit or "C62"
        items.append(
            {
                "description": desc.strip(),
                # Pauschal (LS) = Festbetrag: Menge immer 1 (Client sperrt das Feld,
                # hier zusätzlich normalisiert für No-JS/alte Drafts).
                "quantity": "1" if unit_code == "LS" else _num_str(qty or "1"),
                "unit": unit_code,
                "unit_price": _num_str(price or "0"),
                "item_start": (starts[i] if i < len(starts) else "") or None,
                "item_end": (ends[i] if i < len(ends) else "") or None,
                "item_discount": _num_str((discounts[i] if i < len(discounts) else "0") or "0"),
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
    path = output_dir() / name
    if path.name != name or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def render_invoice_preview(seller, buyer, inv, items, mode=""):
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
    html = render_template(
        "invoice_pdf.html",
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
        "discount": _num_str(form.get("discount", "0")),
        "discount_type": "abs" if form.get("discount_type") == "abs" else "pct",
        "discount_reason": form.get("discount_reason", "").strip() or None,
        "prepaid": _num_str(form.get("prepaid", "0")),
        "prepaid_ref": form.get("prepaid_ref", "").strip() or None,
        "bank_account": form.get("bank_account", "0"),  # gewähltes Konto (0 = Hauptkonto)
    }
    buyer = buyer_from_form(form)
    data = {
        "seller": seller, "buyer": buyer, "invoice": inv, "items": items,
        "bank": select_account(seller, inv["bank_account"]),  # gewähltes Zahlungskonto
    }

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
    for p in output_dir().glob("*.pdf"):
        sidecar = output_dir() / f"{p.stem}.json"
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
    for p in output_dir().glob("*.pdf"):
        sidecar = output_dir() / f"{p.stem}.json"
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


DEFAULT_TERM_DAYS = 14  # Standard-Zahlungsziel für neue Kunden (pro Kunde änderbar)


@app.route("/")
def index():
    seller = load_seller()
    today = date.today()
    defaults = {
        "number": suggest_invoice_number(seller),
        "issue_date": today.isoformat(),
        "due_date": (today + timedelta(days=DEFAULT_TERM_DAYS)).isoformat(),
    }
    draft = load_draft(request.args.get("from"))
    # Erststart: noch kein Datenordner gewählt UND keine Stammdaten -> beim ersten
    # Öffnen aktiv nach dem Speicherort fragen (Vorschlag: sichtbarer Dokumente-Ordner
    # statt des versteckten Application-Support-Standards).
    first_run = "data_dir" not in _load_app_config() and not SELLER_FILE.exists()
    return render_template(
        "form.html",
        seller=seller,
        issuers=issuer_profiles(),
        issuer_scope=hashlib.sha256(str(SELLER_FILE.parent.resolve()).encode()).hexdigest()[:16],
        treatments=TAX_TREATMENTS,
        defaults=defaults,
        customers=load_customers(),
        units=UNITS,
        draft=draft,
        used_numbers=used_invoice_numbers(),
        ref_invoices=archived_invoices(),
        first_run=first_run,
        show_whats_new=not first_run,
        suggested_data_dir=str(Path.home() / "Documents" / "eRechnung"),
        can_browse=(sys.platform == "darwin"),
    )


@app.route("/settings", methods=["POST"])
def settings():
    seller = apply_seller_form(load_seller(), request.form)
    save_seller(seller)
    msg = translate(get_ui_lang(request))["master_saved"]
    # Per fetch (JS): kein Redirect/Reload -> Scrollposition bleibt, Toast statt Banner.
    if request.headers.get("X-Requested-With") == "fetch":
        return {"ok": True, "message": msg, "issuer_label": issuer_label(seller)}
    flash(msg, "ok")
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
    ui = translate(get_ui_lang(request))
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    if not buyer["name"]:
        msg = ui["customer_name_missing"]
        if is_fetch:
            return {"ok": False, "message": msg}
        flash(msg, "err")
        return redirect(url_for("index"))
    upsert_customer(buyer)
    msg = ui["customer_saved"].replace("{name}", buyer["name"])
    # Per fetch (JS): kein Redirect/Reload -> Scrollposition bleibt, Toast statt Banner;
    # aktualisierte Kundenliste mitliefern, damit die Combobox frisch bleibt.
    if is_fetch:
        return {"ok": True, "message": msg, "customers": load_customers()}
    flash(msg, "ok")
    return redirect(url_for("index"))


@app.route("/customers/delete", methods=["POST"])
def customers_delete():
    name = request.form.get("buyer_name", "").strip()
    customers = load_customers()
    match = next(
        (c for c in customers if c.get("name", "").strip().lower() == name.lower()),
        None,
    ) if name else None
    ui = translate(get_ui_lang(request))
    is_fetch = request.headers.get("X-Requested-With") == "fetch"
    if match:
        customers.remove(match)
        save_customers(customers)
        msg, ok = ui["customer_deleted"].replace("{name}", match["name"]), True
    else:
        msg, ok = ui["customer_not_found"], False
    # Per fetch (JS): kein Reload -> Scrollposition bleibt, Toast; frische Kundenliste mit.
    if is_fetch:
        return {"ok": ok, "message": msg, "customers": load_customers()}
    flash(msg, "ok" if ok else "err")
    return redirect(url_for("index"))


@app.route("/preview-html", methods=["POST"])
def preview_html():
    """Live-HTML-Vorschau (gleiches Layout wie das PDF), für das Panel rechts."""
    _, html, _ = _assemble(request.form)
    return html


@app.route("/preview", methods=["POST"])
def preview():
    """Volles ZUGFeRD-PDF (mit eingebettetem XML) inline – wird NICHT archiviert.
    Genutzt vom Build-Selbsttest (desktop.py _selftest), der das eingebettete XML
    extrahiert und validiert; daher kein toter Code."""
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
    try:
        _, html, _ = _assemble(request.form)
        pdf = render_html_pdf(html)  # gemeinsamer Renderpfad mit build_pdf
    except Exception:
        logger.debug("preview_pdf render failed (meist unvollständige Eingabe)", exc_info=True)
        # Unvollständige/fehlerhafte Eingaben (z. B. beim Tippen) -> kein 500,
        # sondern eine schlichte Meldung; der Client zeigt ohnehin „keine Vorschau".
        msg = translate(get_ui_lang(request))["no_preview"]
        return Response(
            f"<!doctype html><meta charset='utf-8'>"
            f"<body style='font:15px sans-serif;padding:40px;color:#888'>{msg}</body>",
            status=400,
            mimetype="text/html",
        )
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
    is_xr = data["invoice"]["profile"] == "xrechnung"
    xml = build_xml(data)
    # XRechnung: die einreichbare .xml ist der Hauptbeleg; das PDF ist nur ein
    # visuelles Sichtexemplar (kein eingebettetes XML). ZUGFeRD: ein hybrides PDF.
    pdf = render_html_pdf(html) if is_xr else build_pdf(html, xml)

    # Archivieren – eine vorhandene Datei NIE überschreiben. Wird dieselbe
    # Rechnungsnummer erneut verwendet (z. B. versehentlich), würde sonst eine
    # evtl. korrekte Rechnung still zerstört. Bei Kollision eindeutigen Namen
    # vergeben; beide bleiben im Archiv sichtbar, der Fehler ist korrigierbar.
    stem = f"Rechnung_{safe_name(inv_number)}"
    name, n = stem, 2
    while True:
        filename = f"{name}.pdf"
        try:
            # Exclusive creation also protects against a second app process.
            with (output_dir() / filename).open("xb") as f:
                f.write(pdf)
            break
        except FileExistsError:
            name = f"{stem} ({n})"
            n += 1
    duplicate = name != stem
    file_stem = Path(filename).stem
    # XRechnung: standalone-XML neben das PDF legen (der eigentliche Beleg).
    xml_filename = None
    if is_xr:
        xml_filename = f"{file_stem}.xml"
        (output_dir() / xml_filename).write_bytes(xml)

    # Sidecar mit den Formulardaten – ermöglicht „als Vorlage öffnen" und die
    # Archiv-Vorschau. seller wird mitgespeichert, damit die Vorschau dem Stand
    # zum Erzeugungszeitpunkt entspricht (auch wenn die Stammdaten sich ändern).
    sidecar = {
        "issuer_id": current_issuer(),
        "seller": seller, "buyer": data["buyer"],
        "invoice": data["invoice"], "items": data["items"],
    }
    (output_dir() / f"{file_stem}.json").write_text(
        json.dumps(sidecar, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Validierung: XSD-Struktur + EN16931/BR-DE-Geschäftsregeln (Schematron).
    # XRechnung direkt aus der standalone-XML, ZUGFeRD aus dem eingebetteten XML.
    sch: dict | None
    if is_xr:
        ok, messages = validate_xml_bytes(xml)
        sch = validate_schematron(xml)
    else:
        embedded = extract_xml_from_pdf(pdf)
        ok, messages = validate_xml_bytes(embedded) if embedded else (False, ["Kein XML im PDF gefunden."])
        sch = validate_schematron(embedded) if embedded else None
    valid = bool(ok and sch and sch["available"] and sch["ok"] and not sch.get("error"))

    # Letzte Rechnungsnummer merken
    current_seller = load_seller()
    last = current_seller.get("last_invoice_number", "")
    old_standard = re.fullmatch(r"(\d{4})-(\d+)", last or "")
    new_standard = re.fullmatch(r"(\d{4})-(\d+)", inv_number)
    if not (old_standard and new_standard
            and tuple(map(int, old_standard.groups())) > tuple(map(int, new_standard.groups()))):
        current_seller["last_invoice_number"] = inv_number
    save_seller(current_seller)

    return render_template(
        "result.html",
        filename=filename,
        xml_filename=xml_filename,
        is_xrechnung=is_xr,
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


@app.route("/download-zip/<path:filename>")
def download_zip(filename):
    """PDF + zugehörige XRechnung-XML als ZIP (ein Klick -> beide Belege)."""
    import io
    import zipfile

    path = output_dir() / filename
    if path.name != filename or path.suffix.lower() != ".pdf" or not path.exists():
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(path, arcname=path.name)
        xml = output_dir() / f"{path.stem}.xml"
        if xml.exists():
            z.write(xml, arcname=xml.name)
    return Response(
        buf.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{path.stem}.zip"'},
    )


def reveal_in_finder(path) -> bool:
    """Datei im Finder zeigen (macOS) – gemeinsamer Helfer für reveal() und den
    Desktop-CSV-Export."""
    if sys.platform != "darwin":
        return False
    import subprocess

    try:
        subprocess.run(["open", "-R", str(path)], timeout=10)
    except Exception:
        logger.warning("reveal_in_finder failed for %s", path, exc_info=True)
        return False
    return True


@app.route("/reveal/<path:filename>", methods=["POST"])
def reveal(filename):
    """Datei im Finder zeigen. In der Desktop-App ersetzt das den Download –
    die Belege liegen ohnehin schon im output/-Ordner."""
    path = output_dir() / filename
    if path.name != filename or not path.exists():
        abort(404)
    if not reveal_in_finder(path):
        return {"ok": False, "error": "failed"}
    return {"ok": True}


@app.route("/view/<path:filename>")
def view(filename):
    return _serve(filename, inline=True)


@app.route("/archive/preview/<path:filename>")
def archive_preview(filename):
    """Das gespeicherte Original-PDF anzeigen, unabhängig von Vorlage/Stammdaten."""
    if Path(filename).suffix.lower() != ".pdf":
        abort(404)
    return _serve(filename, inline=True)


@app.route("/archive/delete", methods=["POST"])
def archive_delete():
    """Archivierte Rechnung (PDF + Sidecar-JSON) löschen – nur innerhalb OUTPUT_DIR."""
    filename = request.form.get("filename", "")
    path = output_dir() / filename
    # Pfad-Traversal verhindern: nur einfache Dateinamen direkt im Ausgabeordner.
    if filename and path.name == filename and path.suffix == ".pdf" and path.exists():
        path.unlink()
        # Sidecar + XRechnung-XML + evtl. exportierte Einzel-CSV mitlöschen
        for sib in (f"{path.stem}.json", f"{path.stem}.xml", f"{path.stem}.csv"):
            p = output_dir() / sib
            if p.exists():
                p.unlink()
        flash(translate(get_ui_lang(request))["invoice_deleted"], "ok")
    return redirect(url_for("validate"))


def _serve(filename, inline):
    path = output_dir() / filename
    if path.name != filename or not path.exists():
        abort(404)
    disp = "inline" if inline else "attachment"
    mime = "application/xml" if path.suffix.lower() == ".xml" else "application/pdf"
    return Response(
        path.read_bytes(),
        mimetype=mime,
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


# Repo für den (vom Nutzer ausgelösten) App-Update-Check. Bewusst nur auf Klick –
# kein automatischer Call beim Start, damit das Offline-Prinzip gewahrt bleibt.
GITHUB_REPO = "timhoefer/eRechnung"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"


@app.route("/check-updates", methods=["POST"])
def check_updates():
    """Neueste GitHub-Release-Version mit der laufenden App-Version vergleichen.
    Nur auf ausdrücklichen Klick – der einzige App-bezogene Netzwerk-Call."""
    import json as _json
    import urllib.request as _req

    info: dict[str, Any] = {
        "current": APP_VERSION, "latest": None, "update_available": False,
        "error": None, "url": GITHUB_RELEASES_URL,
    }
    try:
        req = _req.Request(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "eRechnung"},
        )
        with _req.urlopen(req, timeout=6) as resp:  # noqa: S310 (feste https-URL)
            data = _json.loads(resp.read().decode("utf-8"))
        tag = (data.get("tag_name") or "").lstrip("vV").strip()
        info["latest"] = tag or None
        info["url"] = data.get("html_url") or GITHUB_RELEASES_URL
        if tag:
            info["update_available"] = _version_gt(tag, APP_VERSION)
    except Exception:
        logger.warning("check_updates failed", exc_info=True)
        info["error"] = "offline"
    return info


def _settings_context() -> dict:
    """Gemeinsamer Kontext für die Einstellungen/Archiv (Vollseite + In-Place-Panel)."""
    archive = []
    for p in sorted(output_dir().glob("*.pdf"), reverse=True):
        # Nummer, Kunde + Rechnungsbetrag aus dem Sidecar (fehlt/defekt: ohne).
        number, buyer_name, amount, currency = None, None, None, "EUR"
        sidecar = output_dir() / f"{p.stem}.json"
        if sidecar.exists():
            try:
                d = json.loads(sidecar.read_text(encoding="utf-8"))
                inv = d.get("invoice") or {}
                number = (inv.get("number") or "").strip() or None
                buyer_name = (d.get("buyer") or {}).get("name")
                treatment = TAX_TREATMENTS.get(
                    inv.get("tax_treatment") or "de_19", TAX_TREATMENTS["de_19"]
                )
                *_, amount = compute_totals(
                    d.get("items") or [], cast(Decimal, treatment["rate"]),
                    _dec(inv.get("discount") or "0"), inv.get("discount_type") or "abs",
                )
                currency = inv.get("currency") or "EUR"
            except (ValueError, OSError, ArithmeticError):
                logger.warning("Sidecar %s nicht lesbar/berechenbar", sidecar.name, exc_info=True)
        if not number and p.stem.startswith("Rechnung_"):
            # Ohne Sidecar: Nummer aus dem Tool-Namensschema ableiten (wie
            # used_invoice_numbers); fremde Dateien zeigen den Dateinamen.
            number = p.stem[len("Rechnung_"):]
        archive.append(
            {
                "filename": p.name,
                "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                ),
                "has_draft": sidecar.exists(),
                "xml_filename": (
                    f"{p.stem}.xml" if (output_dir() / f"{p.stem}.xml").exists() else None
                ),
                "number": number,
                "buyer": buyer_name,
                "amount": amount,
                "currency": currency,
            }
        )
    return {
        "archive": archive,
        "data_dir": str(DATA_DIR),
        "data_dir_custom": DATA_DIR.resolve() != BASE.resolve(),
        "can_browse": (sys.platform == "darwin"),
        "conflicts": data_conflicts(),
        "app_version": APP_VERSION,
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
    for p in output_dir().glob("*.pdf"):
        sidecar = output_dir() / f"{p.stem}.json"
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
        doc_type = inv.get("doc_type") or "380"
        sign = -1 if doc_type == "381" else 1
        rows.append([
            inv.get("number", ""), issue, buyer.get("name", ""), buyer.get("country", ""),
            loc(treatment["label"], lang), treatment["category"], str(treatment["rate"]),
            fnum(sign * net), fnum(sign * vat), fnum(sign * gross), inv.get("currency", "EUR"),
            doc_type, inv.get("ref_number") or "",
        ])
    rows.sort(key=lambda r: (r[1], r[0]))  # nach Datum, dann Nummer

    header = (
        ["Nummer", "Datum", "Kunde", "Land", "Behandlung", "USt-Code",
         "USt-Satz %", "Netto", "USt-Betrag", "Brutto", "Währung", "Belegart", "Originalrechnung"] if de else
        ["Number", "Date", "Customer", "Country", "Treatment", "VAT code",
         "VAT rate %", "Net", "VAT amount", "Gross", "Currency", "Document type", "Original invoice"]
    )
    # CSV-Formel-Injection abwehren: Zellen, die mit =,+,-,@ (oder Tab/CR) beginnen,
    # werden in Excel/Calc sonst als Formel ausgewertet -> mit ' als Text entschärfen.
    def csv_safe(v):
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";" if de else ",")
    writer.writerow(header)
    writer.writerows([[c if i in (7, 8, 9) else csv_safe(c)
                       for i, c in enumerate(r)] for r in rows])
    data = ("\ufeff" + buf.getvalue()).encode("utf-8")  # BOM -> Umlaute in Excel
    if only:
        name = f"{Path(only).stem}.csv"
    else:
        # Datumsbereich in den Dateinamen (nur echte ISO-Daten: der Name wird im
        # Desktop-Modus als Datei geschrieben -> keine freien Strings zulassen).
        def iso(s: str) -> str:
            return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""

        base = "rechnungen" if de else "invoices"
        ab, bis = ("_ab_", "_bis_") if de else ("_from_", "_to_")
        rng = ""
        if iso(frm) and iso(to):
            rng = f"_{frm}{bis}{to}"
        elif iso(frm):
            rng = f"{ab}{frm}"
        elif iso(to):
            rng = f"{bis}{to}"
        name = f"{base}{rng}.csv"
    if app.config.get("DESKTOP") and sys.platform == "darwin":
        # Desktop-App: WKWebView lädt nichts herunter -> CSV in den Datenordner
        # schreiben und im Finder zeigen.
        out = output_dir() / name
        out.write_bytes(data)
        reveal_in_finder(out)
        return {"ok": True, "name": name}
    return Response(
        data, mimetype="text/csv",  # Flask ergänzt charset=utf-8 automatisch
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.route("/data-dir", methods=["POST"])
def data_dir_set():
    ok, key = set_data_dir(request.form.get("data_dir", ""))
    ui = translate(get_ui_lang(request))
    flash(ui.get(key, key), "ok" if ok else "err")
    # Beim Erststart kommt die Auswahl aus dem Willkommens-Dialog -> zurück aufs
    # Formular (nicht in die Einstellungen).
    dest = "index" if request.form.get("origin") == "onboarding" else "validate"
    return redirect(url_for(dest))


@app.route("/data-dir/browse", methods=["POST"])
def data_dir_browse():
    """Nativen Ordner-Dialog öffnen (lokal, macOS) und gewählten Pfad zurückgeben."""
    import subprocess

    if sys.platform != "darwin":
        return {"ok": False, "error": "unsupported"}
    # Den Dialog über System Events aktiviert öffnen, sonst erscheint er u. U. HINTER
    # dem App-Fenster und wirkt dadurch verzögert.
    script = (
        'tell application "System Events"\n'
        "  activate\n"
        '  set f to choose folder with prompt "Datenordner wählen" '
        "default location (path to home folder)\n"
        "end tell\n"
        "POSIX path of f"
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=600
        )
    except Exception:
        logger.warning("data_dir_browse: osascript failed", exc_info=True)
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
        path = output_dir() / filename
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
            logger.warning("extract_xml_from_pdf failed for upload %s", label, exc_info=True)
            xml = None
    if not xml:
        return {"label": label, "ok": False, "xsd_messages": ["Kein eingebettetes XML gefunden."], "sch": None}
    xsd_ok, xsd_messages = validate_xml_bytes(xml)
    sch = validate_schematron(xml)
    overall = bool(xsd_ok and sch["available"] and sch["ok"] and not sch.get("error"))
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
