"""Customer allowlists: immutable IDs, never authorization by customer name."""
from __future__ import annotations

import json
import re
import secrets

from mcp_access import AccessError, digest


def customer_id(customer):
    value = customer.get("_customer_id")
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) else None


def mode(connection):
    # Existing grants already included the entire customer list and archive.
    return connection.get("customer_mode", "all")


def choices(customers):
    """Bind the first grant to the displayed record, including changes since GET."""
    return [{"key": digest(json.dumps(c, sort_keys=True)), "name": c.get("name", "")}
            for c in customers]


def assign_selected(customers, selected):
    if not selected:
        raise AccessError("Select at least one customer.")
    options = choices(customers)
    if any(sum(option["key"] == key for option in options) != 1 for key in selected):
        raise AccessError("Customer details changed or are ambiguous. Reload and select again.")
    ids = []
    for record, option in zip(customers, options, strict=True):
        if option["key"] not in selected:
            continue
        identifier = customer_id(record)
        if not identifier:
            identifier = record["_customer_id"] = secrets.token_hex(16)
        if sum(customer_id(c) == identifier for c in customers) != 1:
            raise AccessError("Ambiguous customer identity. Resolve it in the app first.")
        ids.append(identifier)
    return ids


def permitted(connection, customer, customers):
    if mode(connection) == "all":
        return True
    identifier = customer_id(customer)
    return (mode(connection) == "selected" and identifier is not None
            and identifier in connection.get("customer_ids", [])
            and sum(customer_id(c) == identifier for c in customers) == 1)


def visible_customers(connection, customers):
    return [{**{k: v for k, v in c.items() if k != "_customer_id"},
             **({"customer_id": customer_id(c)} if customer_id(c) else {})}
            for c in customers if permitted(connection, c, customers)]


def require_customer(connection, arguments, customers, operation):
    if mode(connection) == "all":
        return
    matches = [c for c in customers if customer_id(c) == arguments.get("customer_id")
               and permitted(connection, c, customers)]
    if len(matches) != 1:
        raise AccessError("Customer not permitted.")
    customer = matches[0]
    name = arguments.get("previous_name") or arguments.get("buyer", {}).get("name") or arguments.get("name", "")
    same_name = [c for c in customers if c.get("name", "").strip().lower() == name.strip().lower()]
    if len(same_name) != 1 or same_name[0] != customer:
        raise AccessError("Customer not permitted.")
    buyer_name = arguments.get("buyer", {}).get("name", "").strip().lower()
    if buyer_name and any(c != customer and c.get("name", "").strip().lower() == buyer_name for c in customers):
        raise AccessError("Customer not permitted.")
    if operation in {"check_invoice", "preview_invoice", "create_invoice"}:
        if arguments["invoice"].get("doc_type") in {"381", "384"} and not arguments.get("correction_source"):
            raise AccessError("A customer-scoped correction requires a permitted original invoice.")


def permitted_invoice(connection, original, customers):
    if mode(connection) == "all":
        return True
    if not isinstance(original, dict) or not original.get("customer_id"):
        return False
    matches = [c for c in customers if customer_id(c) == original["customer_id"]]
    return len(matches) == 1 and permitted(connection, matches[0], customers)
