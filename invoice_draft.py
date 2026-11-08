"""Portable, untrusted invoice proposals. No app, filesystem or archive access.

The import UI and a future agent adapter can share this contract. It deliberately
contains no seller snapshot, invoice number, bank account or local identity.
"""
from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal

FORMAT = "erechnung-draft"
SCHEMA_VERSION = 1
MAX_BYTES = 128 * 1024
MAX_ITEMS = 100
INVOICE_FIELDS = {
    "issue_date", "due_date", "service_start", "service_end", "currency",
    "language", "profile", "tax_treatment", "note",
}
ITEM_FIELDS = {"description", "quantity", "unit", "unit_price", "item_start", "item_end"}


class DraftError(ValueError):
    """A stable error code and field path, suitable for UI or JSON adapters."""

    def __init__(self, code: str, field: str = ""):
        self.code = code
        self.field = field
        super().__init__(f"{code}: {field}")


def _object(value, allowed: set[str], required: set[str], field: str) -> dict:
    if not isinstance(value, dict):
        raise DraftError("invalid", field)
    if set(value) - allowed or required - set(value):
        raise DraftError("fields", field)
    return value


def _text(value, field: str, limit: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DraftError("invalid", field)
    if any((ord(c) < 32 and (not multiline or c not in "\n\r\t"))
           or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise DraftError("invalid", field)
    return value.strip()


def _decimal(value, field: str, *, positive: bool = False) -> str:
    # Decimal strings avoid locale ambiguity, float rounding and non-finite values.
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d{0,8})(?:\.\d{1,6})?", value):
        raise DraftError("invalid", field)
    if positive and Decimal(value) == 0:
        raise DraftError("invalid", field)
    return value


def _dates(values: dict, fields: tuple[str, str], path: str) -> None:
    for field in fields:
        if field not in values:
            continue
        value = values[field]
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise DraftError("invalid", f"{path}.{field}")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise DraftError("invalid", f"{path}.{field}") from exc
    start, end = (values.get(field) for field in fields)
    if start and end and end < start:
        raise DraftError("invalid", f"{path}.{fields[1]}")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise DraftError("json")
        result[key] = value
    return result


def parse_draft(raw: bytes, *, units: set[str], treatments: set[str]) -> dict:
    """Validate and normalize a proposal; never fill missing commercial terms."""
    if len(raw) > MAX_BYTES:
        raise DraftError("size")
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DraftError("json") from exc
    data = _object(data, {"format", "schema_version", "customer", "issuer", "invoice", "items"},
                   {"format", "schema_version", "customer", "items"}, "draft")
    if (data["format"] != FORMAT or type(data["schema_version"]) is not int
            or data["schema_version"] != SCHEMA_VERSION):
        raise DraftError("version")
    result = {
        "format": FORMAT, "schema_version": SCHEMA_VERSION,
        "customer": _text(data["customer"], "customer", 200),
    }
    if "issuer" in data:
        result["issuer"] = _text(data["issuer"], "issuer", 200)
    inv = dict(_object(data.get("invoice", {}), INVOICE_FIELDS, set(), "invoice"))
    for field, allowed in {"language": {"de", "en"}, "profile": {"en16931", "xrechnung"},
                           "tax_treatment": treatments}.items():
        if field in inv and (not isinstance(inv[field], str) or inv[field] not in allowed):
            raise DraftError("invalid", f"invoice.{field}")
    if "currency" in inv and (not isinstance(inv["currency"], str)
                              or not re.fullmatch(r"[A-Z]{3}", inv["currency"])):
        raise DraftError("invalid", "invoice.currency")
    if "note" in inv:
        inv["note"] = _text(inv["note"], "invoice.note", 4000, multiline=True)
    _dates(inv, ("issue_date", "due_date"), "invoice")
    _dates(inv, ("service_start", "service_end"), "invoice")
    result["invoice"] = inv
    if not isinstance(data["items"], list) or not 1 <= len(data["items"]) <= MAX_ITEMS:
        raise DraftError("invalid", "items")
    items = []
    for index, value in enumerate(data["items"]):
        path = f"items[{index}]"
        item = dict(_object(value, ITEM_FIELDS, {"description", "quantity", "unit", "unit_price"}, path))
        item["description"] = _text(item["description"], f"{path}.description", 2000, multiline=True)
        item["quantity"] = _decimal(item["quantity"], f"{path}.quantity", positive=True)
        item["unit_price"] = _decimal(item["unit_price"], f"{path}.unit_price")
        if not isinstance(item["unit"], str) or item["unit"] not in units:
            raise DraftError("invalid", f"{path}.unit")
        if item["unit"] == "LS" and Decimal(item["quantity"]) != 1:
            raise DraftError("invalid", f"{path}.quantity")
        _dates(item, ("item_start", "item_end"), path)
        items.append(item)
    result["items"] = items
    return result


def draft_form_values(draft: dict, buyer: dict) -> dict[str, list[str]]:
    """Map a validated proposal and locally chosen buyer into the existing form.

    The caller supplies fresh issuer identity/revision, number and date defaults.
    Never copy arbitrary customer fields (e.g. saved items) into the form.
    """
    fields = {key: [value] for key, value in draft["invoice"].items()}
    for key in ("name", "contact", "address_line", "postcode", "city", "state", "country",
                "vat_id", "email", "reference", "payment_term_days"):
        fields[f"buyer_{key}"] = [str(buyer.get(key) or "")]
    fields["buyer_country"] = [buyer.get("country") or "DE"]
    for key in ITEM_FIELDS:
        fields[key] = [item.get(key, "") for item in draft["items"]]
    return fields
