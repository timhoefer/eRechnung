"""MCP access is enforced by the running app, not by instructions to an agent."""
from __future__ import annotations

import base64
import json
import os
import secrets
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from flask import abort, g, redirect, render_template, request, session, url_for
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import HTTPException

from invoice_archive import ArchiveError, archived_number_files, data_lock
from mcp_access import Access, AccessError
from mcp_contract import ITEM_FIELDS, TOOLS, validate


def publish_endpoint(m, url):
    if m.app.config.get("MCP_FEATURE"):
        path = m.BASE / "mcp-endpoint.json"
        m._write_json(path, {"url": url})
        m.app.config["MCP_ENDPOINT_FILE"] = str(path)


def register(m):
    app = m.app
    app.config["MCP_FEATURE"] = os.environ.get("ERECHNUNG_MCP") == "1"
    access = Access(lambda: m.BASE / "agent_access.json", m._write_json)
    app.extensions["mcp_access"] = access

    def enabled():
        if not app.config["MCP_FEATURE"]:
            abort(404)

    def csrf():
        return session.setdefault("mcp_csrf", secrets.token_urlsafe(32))

    def ui_guard():
        enabled()
        # A bearer credential never authorizes granting access or confirming changes.
        if request.headers.get("Authorization"):
            abort(403)
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                abort(403)
            if not secrets.compare_digest(request.form.get("csrf", ""), session.get("mcp_csrf", "invalid")):
                abort(403)

    def settings_page(token=None, error=None):
        state = access.load()
        access.prune()
        if m.FROZEN:
            command, args = sys.executable, ["--mcp"]
        else:
            command, args = sys.executable, [str(m.RESOURCE_BASE / "mcp_server.py")]
        endpoint = ({"ERECHNUNG_MCP_ENDPOINT_FILE": app.config["MCP_ENDPOINT_FILE"]}
                    if app.config.get("MCP_ENDPOINT_FILE") else {"ERECHNUNG_MCP_URL": request.host_url.rstrip("/")})
        configuration = {"mcpServers": {"erechnung": {
            "command": command, "args": args,
            "env": {**endpoint, "ERECHNUNG_MCP_TOKEN": token},
        }}} if token else None
        return render_template("agents.html", state=state, csrf=csrf(),
                               profiles=m.issuer_profiles(include_deleted=True),
                               requests=access.pending, configuration=configuration, error=error)

    @app.get("/agents")
    def agents_settings():
        ui_guard()
        with m.DATA_LOCK:
            return settings_page()

    @app.post("/agents/settings")
    def agents_update():
        ui_guard()
        m.BASE.mkdir(parents=True, exist_ok=True)
        with m.DATA_LOCK, data_lock(m.BASE):
            action = request.form.get("action")
            token = None
            if action == "enable":
                if request.form.get("consent") != "yes":
                    abort(400)
                access.enable(True)
            elif action == "disable":
                access.enable(False)
            elif action == "revoke":
                access.revoke(request.form.get("connection", ""))
            elif action == "connect":
                name = request.form.get("name", "").strip()
                issuers = request.form.getlist("issuers")
                allowed = {p["id"] for p in m.issuer_profiles(include_deleted=True) if p["available"]}
                if not name or len(name) > 80 or not issuers or not set(issuers) <= allowed:
                    abort(400)
                token = access.create(name, issuers, request.form.get("write") == "yes", m.DATA_DIR)
            else:
                abort(400)
            return settings_page(token)

    @app.get("/agents/requests/<identifier>")
    def agents_review(identifier):
        ui_guard()
        with m.DATA_LOCK:
            entry = access.get(identifier)
            return render_template("agent_request.html", entry=entry, identifier=identifier, csrf=csrf())

    @app.post("/agents/requests/<identifier>")
    def agents_decide(identifier):
        ui_guard()
        with m.DATA_LOCK, data_lock(m.DATA_DIR):
            entry = access.get(identifier)
            if entry["status"] != "pending":
                abort(409)
            connection = access.connection(entry["connection"]["id"], m.DATA_DIR)
            if connection != entry["connection"]:
                abort(403)
            decision = request.form.get("decision")
            if decision == "deny":
                entry.update(status="denied", confirmation=None, arguments={})
            elif decision == "approve":
                # Consume before executing: double clicks and retries cannot replay the write.
                entry["status"] = "executing"
                try:
                    result = execute(connection, entry["operation"], entry["arguments"],
                                     entry["confirmation"]["fingerprint"])
                    entry.update(status="completed" if result.get("ok") else "failed", result=result)
                finally:
                    if entry["status"] == "executing":
                        entry["status"] = "failed"
                    entry.update(confirmation=None, arguments={})
            else:
                abort(400)
            return redirect(url_for("agents_review", identifier=identifier), code=303)

    @app.after_request
    def agents_private(response):
        if (request.endpoint or "").startswith("agents_"):
            response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "same-origin",
                                     "X-Frame-Options": "DENY"})
        return response

    @app.errorhandler(AccessError)
    def agent_access_error(error):
        if request.endpoint == "agents_call":
            return {"ok": False, "error": "access_denied", "message": str(error)}, 403
        return str(error), 403

    @app.post("/agents/call")
    def agents_call():
        enabled()
        # Not a browser API. No cookies, cross-origin requests, arbitrary URLs or file paths.
        if request.headers.get("Origin") or request.headers.get("Cookie"):
            abort(403)
        request.max_content_length = 1_000_000
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            abort(401)
        with m.DATA_LOCK, data_lock(m.DATA_DIR):
            connection = access.authenticate(authorization[7:], m.DATA_DIR)
            payload = request.get_json()
            if not isinstance(payload, dict) or set(payload) != {"tool", "arguments"}:
                abort(400)
            return execute(connection, payload["tool"], payload["arguments"])

    def execute(connection, operation, arguments, approved=""):
        try:
            if not isinstance(operation, str):
                raise ValueError("Expected a tool name.")
            validate(operation, arguments)
            if TOOLS[operation]["write"] and not connection["writable"]:
                raise AccessError("This connection is read-only.")
            issuer = arguments.get("issuer")
            if issuer is not None and issuer not in connection["issuers"]:
                raise AccessError("Issuer not permitted.")
            if operation == "request_status":
                entry = access.get(arguments["request_id"], connection)
                return {"ok": True, "status": entry["status"], "result": entry.get("result")}
            if operation == "list_issuers":
                return {"ok": True, "issuers": [p for p in m.issuer_profiles(include_deleted=True)
                                                if p["id"] in connection["issuers"]]}
            if operation == "list_customers":
                if m.CUSTOMERS_FILE.is_symlink():
                    raise ValueError("Linked customer files are not supported.")
                query = arguments.get("query", "").lower()
                return {"ok": True, "customers": [c for c in m.load_customers() if query in c.get("name", "").lower()]}
            if operation == "invoice_schema":
                return {"ok": True, "tools": TOOLS, "units": {u[0]: u[1] for u in m.UNITS},
                        "tax_treatments": {k: v["label"] for k, v in m.TAX_TREATMENTS.items()}}
            fields = form_fields(operation, arguments)
            path = {"save_customer": "/customers/save", "save_customer_items": "/customers/items/save",
                    "delete_customer": "/customers/delete", "save_issuer": "/settings",
                    "deactivate_issuer": "/issuers/delete", "restore_issuer": "/issuers/restore",
                    "delete_invoice": "/archive/delete", "create_invoice": "/generate",
                    "check_invoice": "/preview", "preview_invoice": "/preview-pdf"}.get(operation, "/validate")
            # A distinct app context prevents issuer/approval state leaking between requests.
            with app.app_context(), app.test_request_context(path, method="POST", data=fields,
                    headers={"X-Requested-With": "fetch"}):
                g.mcp_connection = connection
                g.mcp_approved = approved
                early = app.preprocess_request()
                if early is not None:
                    raise ValueError("App rejected this operation.")
                if m.CUSTOMERS_FILE.is_symlink() or any(p.is_symlink() for p in m.output_dir().iterdir()):
                    raise ValueError("Linked customer or archive files are not supported.")
                if operation in {"get_issuer", "list_invoices", "get_invoice", "get_invoice_file", "next_number"}:
                    return read_data(operation, arguments)
                if operation in {"check_invoice", "preview_invoice", "create_invoice"}:
                    seller = m.invoice_seller()
                    if fields["seller_revision"] != m.seller_revision(seller):
                        raise ValueError("Issuer details changed. Read the issuer and review the invoice again.")
                    if fields["tax_treatment"] not in m.TAX_TREATMENTS:
                        raise ValueError("Unknown tax treatment.")
                    if any(unit not in {u[0] for u in m.UNITS} for unit in fields.getlist("unit")):
                        raise ValueError("Unknown unit.")
                    if fields.get("bank_account") and not any(
                            fields["bank_account"] in {a["iban"], a["account_number"]} for a in m.seller_accounts(seller)):
                        raise ValueError("Choose a saved bank account by IBAN or account number.")
                    checked = check_or_preview(operation)
                    if operation != "create_invoice" or not checked["ok"]:
                        return checked
                response = app.make_response(app.dispatch_request())
                if response.status_code >= 400:
                    return {"ok": False, "error": "app_rejected", "status": response.status_code,
                            "details": response.get_json(silent=True)}
                result = response.get_json(silent=True)
                if result is not None:
                    return result
                return {"ok": operation in {"delete_invoice", "restore_issuer"} and response.status_code < 400}
        except m.ChangeConfirmationRequired as exc:
            identifier = access.propose(connection, operation, arguments, exc.confirmation)
            return {"ok": False, "status": "approval_required", "request_id": identifier,
                    "message": "Review and explicitly approve this request in eRechnung → Agent access. No change has been made."}
        except (AccessError, ValueError, ArithmeticError, ArchiveError, HTTPException) as exc:
            return {"ok": False, "error": "rejected", "message": str(exc)}

    def form_fields(operation, arguments):
        fields = MultiDict({"issuer": arguments.get("issuer", "default")})
        for key in ("seller_revision", "correction_source", "filename"):
            if key in arguments:
                fields[key] = arguments[key]
        fields.update(arguments.get("invoice", {}))
        for key, value in arguments.get("buyer", {}).items():
            fields["buyer_" + key] = value
        for key in ITEM_FIELDS:
            if "items" in arguments:
                fields.setlist(key, [item.get(key, "") for item in arguments["items"]])
        if "previous_name" in arguments:
            fields["prev_name"] = arguments["previous_name"]
        if operation == "delete_customer":
            fields["buyer_name"] = arguments["name"]
        if operation in {"deactivate_issuer", "restore_issuer"}:
            fields["confirm"] = "delete" if operation == "deactivate_issuer" else "restore"
        if operation == "save_issuer":
            changes = arguments["changes"]
            fields.update({k: v for k, v in changes.items() if k not in {"accounts", "show_tax_number"}})
            # Partial updates must not silently toggle the existing tax-number preference.
            directory = m.issuer_directory(arguments["issuer"])
            seller = json.loads((directory / "seller.json").read_text())
            if not changes.get("show_tax_number", seller.get("show_tax_number", True)):
                fields["hide_tax_number"] = "on"
            if "accounts" in changes:
                fields["has_accounts_section"] = "1"
                for key in ("kind", "account_name", "bank_name", "iban", "bic", "account_number", "routing", "swift"):
                    fields.setlist("acct_" + key, [a.get(key, "") for a in changes["accounts"]])
        return fields

    def read_data(operation, arguments):
        if operation == "get_issuer":
            seller = m.load_seller()
            return {"ok": True, "seller": seller, "revision": m.seller_revision(seller)}
        if operation == "list_invoices":
            return {"ok": True, "invoices": m._settings_context()["archive"]}
        if operation in {"get_invoice", "get_invoice_file"}:
            filename = arguments["filename"]
            if Path(filename).name != filename:
                raise ValueError("Invalid filename.")
            original = m.correction_original(filename)
            if not original:
                raise ValueError("Invoice snapshot unavailable.")
            if operation == "get_invoice":
                return {"ok": True, "invoice": original}
            path = (m.output_dir() / filename).with_suffix("." + arguments["format"])
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
                raise ValueError("File unavailable or too large.")
            return {"ok": True, "filename": path.name, "mime_type": "application/" + arguments["format"],
                    "base64": base64.b64encode(path.read_bytes()).decode()}
        numbers = archived_number_files(m.output_dir(), strict=True)
        last = m.load_seller().get("last_invoice_number", "")
        import re
        standard = re.fullmatch(r"([0-9]{4})-([0-9]+)", last)
        ambiguous = (not standard or standard[1] != str(date.today().year)
                     or any(len(files) > 1 for files in numbers.values())
                     or any(not re.fullmatch(r"[0-9]{4}-[0-9]+", n) for n in numbers))
        return {"ok": True, "suggestion": m.suggest_invoice_number(m.load_seller(), numbers),
                "requires_clarification": ambiguous, "reserved": False}

    def check_or_preview(operation):
        data, markup, totals = m._assemble(request.form)
        inv = data["invoice"]
        if inv["doc_type"] in {"381", "384"} and not inv["ref_number"]:
            raise ValueError("Credit notes and corrections require the original invoice reference.")
        if inv["tax_treatment"] in {"eu_reverse", "non_eu"} and not data["buyer"].get("vat_id"):
            raise ValueError("This tax treatment requires the buyer's VAT ID.")
        if inv["profile"] == "xrechnung" and m.xrechnung_missing(data["seller"], data["buyer"]):
            raise ValueError("Required XRechnung issuer or customer details are missing.")
        computed, *_ = m.compute_totals(data["items"], m.TAX_TREATMENTS[inv["tax_treatment"]]["rate"])
        for item, calculated in zip(data["items"], computed, strict=True):
            if item.get("item_discount_type") == "abs" and Decimal(item["item_discount"]) > calculated["gross"]:
                raise ValueError("Line discount exceeds the line amount.")
        if inv["discount_type"] == "abs" and Decimal(inv["discount"]) > totals["line_total"]:
            raise ValueError("Invoice discount exceeds the net amount.")
        if Decimal(inv["prepaid"]) > totals["grand_total"]:
            raise ValueError("Prepaid amount exceeds the invoice total.")
        xml = m.build_xml(data)
        valid, messages = m.validate_xml_bytes(xml)
        sch = m.validate_schematron(xml)
        result = {"ok": bool(valid and sch.get("available") and sch.get("ok") and not sch.get("error")),
                  "totals": {k: str(v) for k, v in totals.items()}, "messages": messages, "schematron": sch}
        result["totals"]["due"] = str(totals["grand_total"] - Decimal(inv["prepaid"]))
        if operation == "preview_invoice" and result["ok"]:
            # Insert fixed text only; invoice fields are escaped by the normal template.
            start = markup.index(">", markup.index("<body")) + 1
            markup = markup[:start] + '<p style="color:#666">ENTWURF / DRAFT · Nur zur Vorschau / Preview only</p>' + markup[start:]
            result.update(filename="draft.pdf", mime_type="application/pdf",
                          base64=base64.b64encode(m.render_html_pdf(markup)).decode())
        return result
