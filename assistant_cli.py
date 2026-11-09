"""Optional local assistant adapter. Only the explicit archive command writes app data.

No HTTP server, LLM dependency, application import, or automatic invoice numbering.
Every response is JSON. Exit 2 means invalid input or an unsuccessful validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_archive import (
    ArchiveError,
    archive_invoice,
    archived_number_files,
    data_lock,
    seller_details,
)
from invoice_core import (
    COUNTRY_NAME,
    UNITS,
    payment_days,
    payment_terms_text,
    render_invoice_preview,
    safe_name,
    select_account,
    suggest_invoice_number,
    xrechnung_missing,
)
from issuer_store import (
    IssuerError,
    default_issuer,
    issuer_directory,
    issuer_profiles,
    issuer_scope,
    seller_revision,
)
from version import __version__
from zugferd import (
    TAX_TREATMENTS,
    build_pdf,
    build_xml,
    extract_xml_from_pdf,
    q,
    render_html_pdf,
    validate_schematron,
    validate_xml_bytes,
)

INVOICE_FIELDS = {
    "number", "issue_date", "due_date", "service_start", "service_end", "currency",
    "tax_treatment", "language", "profile", "note", "payment_terms", "doc_type",
    "ref_number", "ref_date", "discount", "discount_type", "discount_reason",
    "prepaid", "prepaid_ref", "bank_account",
}
ITEM_FIELDS = {
    "description", "quantity", "unit", "unit_price", "item_start", "item_end",
    "item_discount", "item_discount_type", "item_discount_reason",
}
BUYER_FIELDS = {
    "name", "contact", "address_line", "postcode", "city", "state", "country",
    "vat_id", "email", "reference", "payment_term_days",
}


class InputError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise InputError("invalid_arguments", message)


def read_json(path: Path):
    if path.stat().st_size > 5_000_000:
        raise InputError("file_too_large", "JSON input exceeds 5 MB.")
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def output_path(path: Path, source: Path) -> Path:
    """Never write inside the selected application's data directory, including links."""
    path = path.expanduser().resolve()
    if path == source or source in path.parents:
        raise InputError("source_is_read_only", "Choose an output path outside the app's data directory.")
    return path


def write_new(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(content)
    except FileExistsError as exc:
        raise InputError("output_exists", "Output already exists; choose a new path.") from exc


def seller_from(source: Path) -> dict:
    seller = read_json(source / "seller.json")
    if not isinstance(seller, dict):
        raise InputError("invalid_seller", "seller.json must contain an object.")
    return seller


def select_issuer(source: Path, issuer: str | None = None) -> tuple[str, Path, dict]:
    """Require a deliberate choice when more than one active identity exists."""
    if issuer is None:
        active = [p for p in issuer_profiles(source) if not p["deleted"]]
        if len(active) != 1:
            raise InputError("issuer_required", "Choose an active issuer with issuers and --issuer ID; the app default is only a suggestion.")
        issuer = active[0]["id"]
    directory = issuer_directory(source, issuer)
    seller = seller_from(directory)
    if seller.get("_deleted") is True:
        raise InputError("issuer_inactive", "This issuer is inactive. Reactivate it in the app before creating invoices.")
    return issuer, directory, seller


def customers_from(source: Path) -> list:
    path = source / "customers.json"
    customers = read_json(path) if path.exists() else []
    if not isinstance(customers, list) or any(not isinstance(c, dict) for c in customers):
        raise InputError("invalid_customers", "customers.json must contain a list of objects.")
    return customers


def templates_from(source: Path, customer: str, issuer: str | None = None) -> list:
    issuer, directory, _ = select_issuer(source, issuer)
    results = []
    for path in sorted((directory / "output").glob("*.json")):
        if path.is_symlink():
            continue
        try:
            data = read_json(path)
            if not isinstance(data, dict) or not isinstance(data.get("buyer"), dict):
                continue
            if data.get("issuer_id", issuer) != issuer:
                continue
            buyer, invoice = data["buyer"], data.get("invoice", {})
            if customer.lower() != str(buyer.get("name", "")).lower():
                continue
            results.append({"template": path.name, "number": invoice.get("number"),
                            "issue_date": invoice.get("issue_date"), "customer": buyer.get("name")})
        except (OSError, ValueError, AttributeError, InputError):
            continue
    return sorted(results, key=lambda item: (str(item["issue_date"] or ""), item["template"]), reverse=True)


def create_draft(source: Path, customer: str, template: str | None, issuer: str | None = None) -> dict:
    issuer, directory, seller = select_issuer(source, issuer)
    # Match the app's customer identity rule. Case folding conflates Straße/Strasse.
    matches = [c for c in customers_from(source) if str(c.get("name", "")).lower() == customer.lower()]
    if len(matches) != 1:
        raise InputError("ambiguous_customer", "Choose one exact customer name from the customer list.")
    buyer = {key: value for key, value in matches[0].items() if key in BUYER_FIELDS}
    invoice = {"number": "", "issue_date": "", "due_date": None, "currency": "EUR",
               "language": "de", "profile": "en16931", "doc_type": "380", "tax_treatment": ""}
    items = matches[0].get("items", [])
    if template:
        if template != Path(template).name or not template.endswith(".json"):
            raise InputError("invalid_template", "Use a filename returned by the templates command.")
        path = directory / "output" / template
        if path.is_symlink():
            raise InputError("invalid_template", "Linked templates are not supported.")
        previous = read_json(path)
        if previous.get("issuer_id", issuer) != issuer:
            raise InputError("wrong_issuer", "The template belongs to a different issuer.")
        if str(previous.get("buyer", {}).get("name", "")).lower() != customer.lower():
            raise InputError("wrong_customer", "The template belongs to a different customer.")
        # Ordinary invoices only: correction/credit references must not carry into a new bill.
        if previous.get("invoice", {}).get("doc_type", "380") != "380":
            raise InputError("unsupported_template", "Choose an ordinary invoice as the template.")
        for key in ("currency", "language", "profile", "tax_treatment", "bank_account"):
            if key in previous["invoice"]:
                invoice[key] = previous["invoice"][key]
        items = previous.get("items", [])
    # Dates, references, deposits and discounts are deliberately not carried into the next period.
    items = [{key: item[key] for key in ("description", "quantity", "unit", "unit_price") if key in item}
             for item in items]
    return {"schema_version": 2, "issuer_id": issuer, "data_scope": issuer_scope(source),
            "seller_revision": seller_revision(seller), "seller": seller, "buyer": buyer,
            "invoice": invoice, "items": items}


def prepare(data, source: Path, issuer: str | None = None) -> tuple[dict, list[dict]]:
    """Reject ambiguous/coerced values before passing data to the existing engine."""
    errors: list[dict] = []

    def error(field, message):
        errors.append({"field": field, "message": message})

    if not isinstance(data, dict) or data.get("schema_version") != 2:
        return {}, [{"field": "schema_version", "message": "Create a fresh version 2 draft with an explicitly bound issuer."}]
    for key in data.keys() - {"schema_version", "issuer_id", "data_scope", "seller_revision", "seller", "buyer", "invoice", "items"}:
        error(key, "Unknown field.")
    if not isinstance(data.get("issuer_id"), str) or not data["issuer_id"]:
        error("issuer_id", "Keep the issuer ID from a fresh draft.")
    elif issuer is not None and issuer != data["issuer_id"]:
        error("issuer_id", "The requested issuer differs from the draft. Create and review a new draft to change issuers.")
    if data.get("data_scope") != issuer_scope(source):
        error("data_scope", "This draft belongs to another data directory. Create and review a fresh draft.")
    for key in ("seller", "buyer", "invoice"):
        if not isinstance(data.get(key), dict):
            error(key, "Expected an object.")
    if not isinstance(data.get("items"), list) or not data.get("items"):
        error("items", "At least one line item is required.")
    if errors:
        return {}, errors
    issuer, _, current_seller = select_issuer(source, data["issuer_id"])
    seller, buyer, inv, items = data["seller"], data["buyer"], dict(data["invoice"]), data["items"]
    if (data.get("seller_revision") != seller_revision(current_seller)
            or seller_details(seller) != seller_details(current_seller)):
        error("seller", "Issuer details differ from the source. Create a fresh draft; do not edit issuer data here.")

    def fields(value, allowed, prefix):
        for key in value:
            if key not in allowed:
                error(f"{prefix}.{key}", "Unknown field.")
            elif value[key] is not None and not isinstance(value[key], str):
                error(f"{prefix}.{key}", "Expected text (decimal values use a dot, without thousands separators).")

    fields(inv, INVOICE_FIELDS, "invoice")
    fields(buyer, BUYER_FIELDS, "buyer")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            error(f"items.{index}", "Expected an object.")
        else:
            fields(item, ITEM_FIELDS, f"items.{index}")
    if errors:
        return {}, errors

    def required(value, key, prefix):
        if not isinstance(value.get(key), str) or not value[key].strip():
            error(f"{prefix}.{key}", "Required.")

    def choice(value, key, allowed, prefix):
        if value.get(key) not in allowed:
            error(f"{prefix}.{key}", "Choose one of: " + ", ".join(sorted(allowed)))

    def number(value, key, prefix, default=None, positive=False):
        raw = value.get(key)
        if raw in (None, "") and default is not None:
            raw = default
        try:
            # Browser number fields and the app calculator only accept ASCII digits.
            if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,12}(?:\.[0-9]{1,8})?", raw):
                raise InvalidOperation
            result = Decimal(raw)
            if positive and result <= 0:
                raise InvalidOperation
            return result
        except InvalidOperation:
            kind = "positive" if positive else "nonnegative"
            error(f"{prefix}.{key}", f"Use a {kind} decimal string with ASCII digits (0-9).")
            return Decimal(0)

    def dates(value, start, end, prefix):
        parsed = {}
        for key in (start, end):
            raw = value.get(key)
            if raw:
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                        raise ValueError
                    parsed[key] = date.fromisoformat(raw)
                except ValueError:
                    error(f"{prefix}.{key}", "Use a valid YYYY-MM-DD date.")
        if start in parsed and end in parsed and parsed[end] < parsed[start]:
            error(f"{prefix}.{end}", "End date must not precede start date.")
        return parsed

    for party, name in ((seller, "seller"), (buyer, "buyer")):
        for key in ("name", "address_line", "city", "country"):
            required(party, key, name)
        choice(party, "country", set(COUNTRY_NAME), name)
    for key in ("number", "issue_date", "currency"):
        required(inv, key, "invoice")
    choice(inv, "tax_treatment", set(TAX_TREATMENTS), "invoice")
    choice(inv, "language", {"de", "en"}, "invoice")
    choice(inv, "profile", {"en16931", "xrechnung"}, "invoice")
    choice(inv, "doc_type", {"380"}, "invoice")
    if inv.get("currency") and not re.fullmatch(r"[A-Z]{3}", inv["currency"]):
        error("invoice.currency", "Use an uppercase ISO currency code.")
    dates(inv, "issue_date", "due_date", "invoice")
    for value, start, end, prefix in [(inv, "service_start", "service_end", "invoice")]+[
        (item, "item_start", "item_end", f"items.{index}") for index, item in enumerate(items)
    ]:
        if bool(value.get(start)) != bool(value.get(end)):
            error(prefix, "Supply both period dates, or neither.")
        dates(value, start, end, prefix)
    number(inv, "prepaid", "invoice", "0")
    discounts = []
    for index, value in enumerate([inv, *items]):
        prefix = "invoice" if index == 0 else f"items.{index-1}"
        key = "discount" if index == 0 else "item_discount"
        kind = value.get(key + "_type") or ("abs" if index == 0 else "pct")
        discount = number(value, key, prefix, "0")
        discounts.append(discount)
        if kind not in {"pct", "abs"}:
            error(prefix + "." + key + "_type", "Use pct or abs.")
        if kind == "pct" and discount > 100:
            error(prefix + "." + key, "Percentage must not exceed 100.")
    for index, item in enumerate(items):
        prefix = f"items.{index}"
        required(item, "description", prefix)
        choice(item, "unit", {unit[0] for unit in UNITS}, prefix)
        quantity = number(item, "quantity", prefix, positive=True)
        price = number(item, "unit_price", prefix)
        if item.get("unit") == "LS" and quantity != 1:
            error(prefix + ".quantity", "Lump-sum items must have quantity 1.")
        if item.get("item_discount_type") == "abs" and discounts[index+1] > quantity * price:
            error(prefix + ".item_discount", "Discount exceeds the line amount.")
    if inv.get("tax_treatment") in {"eu_reverse", "non_eu"} and not buyer.get("vat_id"):
        error("buyer.vat_id", "Required for this tax treatment.")
    if inv.get("profile") == "xrechnung":
        for key in xrechnung_missing(seller, buyer):
            error(key, "Required for XRechnung.")
    if inv.get("ref_number") or inv.get("ref_date"):
        error("invoice.ref_number", "This prototype supports ordinary invoices without correction references.")
    logo = seller.get("logo")
    if logo and (not isinstance(logo, str) or not logo.startswith("data:image/") or len(logo) > 1_500_000):
        error("seller.logo", "Logo must be a local data:image URI, as saved by the app.")
    if errors:
        return {}, errors
    bank = select_account(seller, inv.get("bank_account"))
    if inv.get("bank_account"):
        # Resolve legacy indexes, but never silently fall back from a missing account.
        from invoice_core import seller_accounts
        accounts = seller_accounts(seller)
        key = "".join(inv["bank_account"].split()).upper()
        identifiers = {"".join((a["iban"] if a["kind"] == "iban" else a["account_number"]).split()).upper() for a in accounts}
        if key not in identifiers and not (key.isdigit() and int(key) < len(accounts)):
            return {}, [{"field": "invoice.bank_account", "message": "Selected bank account no longer exists."}]
    days = payment_days(inv)
    inv["payment_terms"] = payment_terms_text(days, inv["language"]) if days is not None else None
    data = {"issuer_id": issuer, "seller": seller, "buyer": buyer, "invoice": inv, "items": items, "bank": bank}
    _, totals = render_invoice_preview(seller, buyer, inv, items)
    if Decimal(inv.get("discount") or "0") > totals[0] and (inv.get("discount_type") or "abs") == "abs":
        error("invoice.discount", "Discount exceeds the subtotal.")
    if Decimal(inv.get("prepaid") or "0") > totals[4]:
        error("invoice.prepaid", "Prepaid amount exceeds the invoice total.")
    return data, errors


def validate_xml(xml: bytes) -> dict:
    ok, messages = validate_xml_bytes(xml)
    rules = validate_schematron(xml)
    valid = bool(ok and rules and rules.get("available") and rules.get("ok") and not rules.get("error"))
    return {"valid": valid, "xsd": {"valid": ok, "messages": messages}, "rules": rules}


def export(data: dict, root: Path) -> dict:
    """Publish a complete bundle atomically; identical retries return its existing files."""
    xml = build_xml(data)
    validation = validate_xml(xml)
    if not validation["valid"]:
        return {"ok": False, "validation": validation}
    name = "Rechnung_" + safe_name(data["invoice"]["number"])
    root = root / data["issuer_id"]
    if root.is_symlink():
        raise InputError("linked_export", "Choose an export directory without a linked issuer folder.")
    target = root / name
    fingerprint = digest(canonical(data))
    root.mkdir(parents=True, exist_ok=True)
    # A single export directory is the transaction boundary. No app archive/state is mutated.
    import fcntl
    with (root / ".export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if target.is_symlink():
            raise InputError("linked_export", "Choose an export directory without a linked invoice folder.")
        if target.exists():
            receipt = read_json(target / "receipt.json")
            if receipt.get("fingerprint") != fingerprint:
                raise InputError("number_conflict", "This export folder already contains a different invoice with that number.")
            for filename, expected in receipt["sha256"].items():
                if filename != Path(filename).name or digest((target / filename).read_bytes()) != expected:
                    raise InputError("changed_export", "An exported file changed; no files were overwritten.")
            return {"ok": True, "reused": True, "directory": str(target), "files": [str(target / f) for f in receipt["sha256"]], "validation": validation}
        markup, _ = render_invoice_preview(data["seller"], data["buyer"], data["invoice"], data["items"])
        is_xr = data["invoice"]["profile"] == "xrechnung"
        pdf = render_html_pdf(markup) if is_xr else build_pdf(markup, xml)
        if not is_xr:
            embedded = extract_xml_from_pdf(pdf)
            if embedded != xml:
                raise InputError("embedding_failed", "The PDF does not contain the generated invoice XML.")
        payloads = {name + ".pdf": pdf, name + ".json": canonical({k: data[k] for k in ("issuer_id", "seller", "buyer", "invoice", "items")})}
        if is_xr:
            payloads[name + ".xml"] = xml
        receipt = {"fingerprint": fingerprint, "version": __version__, "sha256": {key: digest(value) for key, value in payloads.items()}}
        staging = Path(tempfile.mkdtemp(prefix=".invoice-", dir=root))
        try:
            for filename, content in payloads.items():
                (staging / filename).write_bytes(content)
            (staging / "receipt.json").write_bytes(canonical(receipt))
            staging.rename(target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {"ok": True, "reused": False, "directory": str(target), "files": [str(target / f) for f in payloads], "validation": validation}



def number_proposal(source: Path, issuer: str | None = None) -> dict:
    issuer, directory, seller = select_issuer(source, issuer)
    inventory = archived_number_files(directory / "output", strict=True)
    numbers = set(inventory)
    duplicates = {number: files for number, files in inventory.items() if len(files) > 1}
    last = seller.get("last_invoice_number") or ""
    year = date.today().year
    suggestion = suggest_invoice_number(seller, numbers)
    reasons = []
    if duplicates:
        reasons.append("Some invoice numbers occur more than once. Ask which invoices were actually issued and which number to use; do not infer it from the archive maximum or assume duplicates are tests.")
    match = re.fullmatch(r"(\d{4})-(\d+)", last)
    current_standard = any(re.fullmatch(rf"{year}-\d+", number) for number in numbers)
    if not last and not numbers:
        reasons.append("No previous number is available; ask which numbering scheme to start.")
    if last and match is None:
        reasons.append("The last number uses a custom scheme; ask which scheme and next number to use.")
    if match and int(match.group(1)) != year and not current_standard:
        reasons.append("The year changed; ask whether to start a new yearly sequence.")
    if any(str(year) in number and not re.fullmatch(r"\d{4}-\d+", number) for number in numbers):
        reasons.append("The archive includes other numbering schemes for this year; ask which one applies.")
    if numbers and not last and not current_standard:
        reasons.append("The archive does not establish a current standard sequence; ask for the invoice number.")
    return {"ok": True, "issuer_id": issuer, "number": None if reasons else suggestion, "suggestion": None if duplicates else suggestion,
            "duplicate_numbers": duplicates,
            "last_invoice_number": last or None, "requires_clarification": bool(reasons),
            "reasons": reasons, "reserved": False}


def run(args) -> dict:
    if args.command == "schema":
        return {"ok": True, "schema_version": 2, "version": __version__, "invoice_fields": sorted(INVOICE_FIELDS),
                "item_fields": sorted(ITEM_FIELDS), "units": {unit[0]: unit[1] for unit in UNITS},
                "tax_treatments": {key: value["label"] for key, value in TAX_TREATMENTS.items()},
                "formats": ["en16931", "xrechnung"], "document_types": ["380"],
                "source_access": "read-only except archive",
                "draft_identity_fields": ["issuer_id", "data_scope", "seller_revision"],
                "issuers": "use issuers; choose --issuer ID when multiple active profiles exist; drafts retain their issuer",
                "exports": "separate output folder; no archive registration or number reservation",
                "archive": "explicit validated finalization into the app archive; shared local number lock"}
    if args.data_dir is None:
        raise InputError("missing_data_dir", "Select the app's data directory explicitly with --data-dir.")
    source = args.data_dir.expanduser().resolve(strict=True)
    if not source.is_dir() or (source.parent.name == "issuers" and re.fullmatch(r"[a-f0-9]{32}", source.name)):
        raise InputError("invalid_data_dir", "Select the shared app data directory, not an issuer subfolder.")
    if args.command == "issuers":
        profiles = issuer_profiles(source)
        preferred = default_issuer(source, [p for p in profiles if not p["deleted"]])
        return {"ok": True, "default_issuer_id": preferred,
                "issuers": [{**p, "default": p["id"] == preferred and not p["deleted"]} for p in profiles]}
    if args.command == "next-number":
        return number_proposal(source, args.issuer)
    if args.command == "customers":
        return {"ok": True, "shared_across_issuers": True, "customers": [{key: c.get(key, "") for key in BUYER_FIELDS}
                for c in customers_from(source) if args.query.casefold() in str(c.get("name", "")).casefold()]}
    if args.command == "templates":
        issuer, _, _ = select_issuer(source, args.issuer)
        return {"ok": True, "issuer_id": issuer, "templates": templates_from(source, args.customer, issuer)}
    if args.command == "draft":
        data = create_draft(source, args.customer, args.template, args.issuer)
        out = output_path(args.out, source)
        write_new(out, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        return {"ok": True, "issuer_id": data["issuer_id"], "draft": str(out), "needs_input": ["invoice.number", "invoice.issue_date", "invoice.tax_treatment", "items"],
                "note": "Confirm the service period, prices and tax treatment; the draft does not reserve a number."}
    data, errors = prepare(read_json(args.draft), source, args.issuer)
    if errors:
        return {"ok": False, "errors": errors}
    markup, totals = render_invoice_preview(data["seller"], data["buyer"], data["invoice"], data["items"], draft=True)
    summary = {"issuer_id": data["issuer_id"], "issuer_name": data["seller"]["name"],
               "issuer_label": data["seller"].get("profile_label") or data["seller"]["name"],
               "number": data["invoice"]["number"], "customer": data["buyer"]["name"],
               "currency": data["invoice"]["currency"], "net": str(totals[2]), "tax": str(totals[3]),
               "gross": str(totals[4]), "due": str(totals[4] - q(Decimal(data["invoice"].get("prepaid") or "0")))}
    if args.command == "preview":
        out = output_path(args.out, source)
        write_new(out, render_html_pdf(markup))
        return {"ok": True, "preview": str(out), "summary": summary, "note": "Draft preview, without invoice XML."}
    if args.command == "check":
        validation = validate_xml(build_xml(data))
        return {"ok": validation["valid"], "summary": summary, "validation": validation}
    if args.command == "archive":
        xml = build_xml(data)
        validation = validate_xml(xml)
        if not validation["valid"]:
            return {"ok": False, "validation": validation}
        markup, _ = render_invoice_preview(data["seller"], data["buyer"], data["invoice"], data["items"])
        is_xr = data["invoice"]["profile"] == "xrechnung"
        pdf = render_html_pdf(markup) if is_xr else build_pdf(markup, xml)
        if not is_xr and extract_xml_from_pdf(pdf) != xml:
            raise InputError("embedding_failed", "The PDF does not contain the generated invoice XML.")
        with data_lock(source):
            _, directory, _ = select_issuer(source, data["issuer_id"])
            archived = archive_invoice(data, pdf, xml, directory / "output", directory / "seller.json",
                                       expected_seller=data["seller"], lock_directory=source)
        return {"ok": True, "archived": True, **archived, "summary": summary,
                "validation": validation, "note": "Saved in the app archive. Refresh the archive to see this invoice."}
    root = output_path(args.out_dir, source)
    number = data["invoice"]["number"]
    _, directory, _ = select_issuer(source, data["issuer_id"])
    if number in archived_number_files(directory / "output", strict=True):
        raise InputError("number_in_archive", "This invoice number already exists in the selected issuer's archive.")
    return export(data, root)


def main(argv=None) -> int:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="App data directory (only archive writes here)")
    parser.add_argument("--issuer", help="Issuer ID from issuers; required for a new draft when multiple profiles exist")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")
    commands.add_parser("issuers")
    commands.add_parser("next-number")
    customers = commands.add_parser("customers")
    customers.add_argument("--query", default="")
    templates = commands.add_parser("templates")
    templates.add_argument("--customer", required=True)
    draft = commands.add_parser("draft")
    draft.add_argument("--customer", required=True)
    draft.add_argument("--template")
    draft.add_argument("--out", type=Path, required=True)
    for command in ("check", "preview", "export", "archive"):
        action = commands.add_parser(command)
        action.add_argument("--draft", type=Path, required=True)
        if command == "preview":
            action.add_argument("--out", type=Path, required=True)
        if command == "export":
            action.add_argument("--out-dir", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        result = run(args)
    except (InputError, ArchiveError, IssuerError) as exc:
        result = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    except (OSError, ValueError, InvalidOperation, KeyError, TypeError, AttributeError) as exc:
        result = {"ok": False, "error": {"code": "invalid_input_or_io", "message": str(exc)}}
    except Exception as exc:
        result = {"ok": False, "error": {"code": "engine_error", "message": str(exc)}}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
