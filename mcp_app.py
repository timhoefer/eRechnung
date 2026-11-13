"""MCP access is enforced by the running app, not by instructions to an agent."""
from __future__ import annotations

import base64
import hashlib
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

import mcp_customer_scope as customer_scope
from invoice_archive import ArchiveError, archived_number_files, data_lock
from mcp_access import (
    DESTRUCTIVE,
    WRITE_OPERATIONS,
    Access,
    AccessError,
    digest,
    permission,
    permission_choices,
    validate_permissions,
)
from mcp_contract import ITEM_FIELDS, TOOLS, validate

ASSISTANTS = {"chatgpt": "ChatGPT", "codex": "Codex", "claude": "Claude", "other": ""}


def publish_endpoint(m, url):
    # Publish even with the feature off so the bridge reuses this instance and
    # receives its refusal instead of opening another copy with different flags.
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

    def connection_name(assistant="other"):
        name = request.form.get("name", "").strip()
        if len(name) > 80:
            abort(400)
        return name or ASSISTANTS[assistant] or ("Meine Verbindung" if m.get_ui_lang(request) == "de" else "My connection")

    def disclaimer(active):
        text = m.translate(m.get_ui_lang(request))
        return text["disclaimer_full"] + " " + text["disclaimer_agent" if active else "disclaimer_local"]

    @app.context_processor
    def agent_ui_context():
        # Share only the switch state, never credentials or connection details.
        active = False
        unavailable = False
        if app.config["MCP_FEATURE"]:
            try:
                with m.DATA_LOCK:
                    active = access.load().get("enabled", False)
            except AccessError:
                # A broken optional integration must not prevent normal invoicing.
                unavailable = True
        return {"agent_enabled": active, "agent_access_unavailable": unavailable,
                "disclaimer_text": disclaimer(active),
                "agent_permission_choices": permission_choices, "agent_destructive_operations": DESTRUCTIVE,
                "agent_csrf": csrf() if app.config["MCP_FEATURE"] and not request.headers.get("Authorization") else ""}

    def ui_guard():
        enabled()
        # A bearer credential never authorizes granting access or confirming changes.
        if request.headers.get("Authorization"):
            abort(403)
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin != request.host_url.rstrip("/"):
                abort(403)
            expected = session.get("mcp_csrf")
            supplied = request.form.get("csrf", "")
            if (not isinstance(expected, str) or not expected or not supplied
                    or not secrets.compare_digest(supplied.encode(), expected.encode())):
                abort(403)

    def configuration_context(token=None):
        if m.FROZEN:
            command, args = sys.executable, ["--mcp"]
        else:
            command, args = sys.executable, [str(m.RESOURCE_BASE / "mcp_server.py")]
        endpoint = ({"ERECHNUNG_MCP_ENDPOINT_FILE": app.config["MCP_ENDPOINT_FILE"]}
                    if app.config.get("MCP_ENDPOINT_FILE") else {"ERECHNUNG_MCP_URL": request.host_url.rstrip("/")})
        startup = ({"ERECHNUNG_TEST_MODE": "1"} if m.TEST_MODE else
                   {"ERECHNUNG_MCP_AUTOSTART": "1"} if app.config.get("MCP_ENDPOINT_FILE") else {})
        configuration = {"mcpServers": {"erechnung": {
            "command": command, "args": args,
            "env": {**endpoint, **startup, "ERECHNUNG_MCP_TOKEN": token, "ERECHNUNG_MCP": "1"},
        }}} if token else None
        return {"configuration": configuration, "autostart": "ERECHNUNG_MCP_AUTOSTART" in startup}

    def settings_page(token=None, error=None, *, embedded=False):
        state = access.load()
        customers = customer_records()
        access.prune()
        configuration = configuration_context(token)
        setup_context = None
        if token:
            setup_context = dict(connection=access.authenticate(token, m.DATA_DIR), new_connection=True,
                                 csrf=csrf(), profiles=m.issuer_profiles(include_deleted=True),
                                 customer_names={customer_scope.customer_id(c): c.get("name", "") for c in customers},
                                 **configuration)
        return render_template("_agent_management.html" if embedded else "agents.html",
                               agent_settings=embedded, state=state, csrf=csrf(),
                               profiles=m.issuer_profiles(include_deleted=True),
                               customer_choices=customer_scope.choices(customers),
                               customer_names={customer_scope.customer_id(c): c.get("name", "") for c in customers},
                               requests=access.pending, error=error, setup_context=setup_context,
                               setup_views=configuration_views(setup_context) if setup_context else None,
                               **configuration)

    def configuration_views(context):
        # Both languages travel only in this response. Credentials stay out of
        # sessions/storage and language changes never replay key creation.
        return {lang: render_template("_agent_setup_content.html", lang=lang, t=m.translate(lang),
                                      dialog_mode=True, **context) for lang in ("de", "en")}

    def customer_records():
        if m.CUSTOMERS_FILE.is_symlink():
            raise AccessError("Linked customer files are not supported.")
        return m.load_customers()

    def permission_fields(existing=None):
        policies = None
        if request.form.get("permission_policy") == "1":
            policies = validate_permissions({operation: request.form.get("permission_" + operation)
                                              for operation in WRITE_OPERATIONS})
        elif existing and "permissions" in existing:
            abort(400)
        issuers = request.form.getlist("issuers")
        allowed = {p["id"] for p in m.issuer_profiles() if p["available"]}
        # Existing archive grants may be retained or removed, never newly added.
        if existing:
            allowed.update(existing["issuers"])
        if not issuers or not set(issuers) <= allowed:
            abort(400)
        mode = request.form.get("customer_mode", "none")
        if mode not in {"none", "selected", "all"}:
            abort(400)
        ids = []
        if mode == "selected":
            customers = customer_records()
            ids = customer_scope.assign_selected(customers, request.form.getlist("customers"))
            # Only internal identities are added; no invoice or customer fields change.
            m._write_json(m.CUSTOMERS_FILE, customers)
        return dict(issuers=issuers, writable=request.form.get("write") == "yes",
                    permissions=policies, client_approvals=request.form.get("client_approvals") == "yes",
                    customer_mode=mode, customer_ids=ids)

    @app.get("/agents")
    def agents_settings():
        ui_guard()
        with m.DATA_LOCK:
            return settings_page()

    def settings_fragment():
        enabled()
        if request.headers.get("Authorization"):
            abort(403)
        with m.DATA_LOCK:
            try:
                return settings_page(embedded=True)
            except AccessError:
                # Optional agent settings must not block the invoice/archive UI.
                return render_template("_agent_access_unavailable.html", agent_access_unavailable=True)

    app.extensions["mcp_settings_fragment"] = settings_fragment

    def panel_response(token=None):
        return {"management": settings_page(token, embedded=True),
                "disclaimer": disclaimer(access.load()["enabled"])}

    @app.get("/agents/panel")
    def agents_panel():
        ui_guard()
        with m.DATA_LOCK:
            return panel_response()

    @app.get("/agents/status")
    def agents_status():
        # Readiness only: never expose grants, profile data or a CSRF session.
        return {"service": "eRechnung", "mcp_enabled": app.config["MCP_FEATURE"]}

    @app.post("/agents/language")
    def agents_language():
        ui_guard()
        language = request.form.get("language")
        if language not in {"de", "en"}:
            abort(400)
        response = app.make_response({"language": language})
        response.set_cookie("lang", language, max_age=365 * 86400, samesite="Lax")
        return response

    @app.route("/agents/connections/<identifier>/setup", methods=["GET", "POST"])
    def agents_setup(identifier):
        ui_guard()
        with m.DATA_LOCK, data_lock(m.BASE), data_lock(m.DATA_DIR):
            state = access.load()
            connection = state["connections"].get(identifier) if state.get("enabled") else None
            # A paused connection can be reconfigured, but must remain paused.
            if not connection or connection.get("scope") != digest(str(m.DATA_DIR.resolve())):
                raise AccessError("Connection unavailable in this data folder.")
            revision = digest(json.dumps(connection, sort_keys=True))
            token = None
            changed = False
            renamed = False
            permissions_saved = False
            if request.method == "POST":
                action = request.form.get("action")
                if action in {"rename", "permissions"}:
                    if request.form.get("revision") != revision:
                        changed = True
                    else:
                        if action == "rename":
                            access.rename(identifier, connection_name())
                            renamed = True
                        else:
                            access.set_permissions(identifier, connection, **permission_fields(connection))
                            permissions_saved = True
                        connection = access.load()["connections"][identifier]
                        revision = digest(json.dumps(connection, sort_keys=True))
                elif request.form.get("confirm") != "renew" or request.form.get("revision") != revision:
                    # Also makes double submission/reload harmless: it cannot
                    # invalidate a key that was just displayed by the first POST.
                    changed = True
                else:
                    token = access.renew(identifier, connection)
            customers = customer_records()
            profiles = m.issuer_profiles(include_deleted=True)
            choices = customer_scope.choices(customers)
            for choice, customer in zip(choices, customers, strict=True):
                choice["selected"] = customer_scope.customer_id(customer) in connection.get("customer_ids", [])
            context = dict(connection=connection, revision=revision, profiles=profiles,
                           permission_profiles=[p for p in profiles if (p["available"] and not p["deleted"])
                                                or p["id"] in connection["issuers"]],
                           customer_choices=choices,
                           customer_names={customer_scope.customer_id(c): c.get("name", "") for c in customers},
                           changed=changed, renamed=renamed, permissions_saved=permissions_saved,
                           csrf=csrf(), **configuration_context(token))
            if request.headers.get("X-Requested-With") == "fetch":
                return {"views": configuration_views(context), "updated": renamed or permissions_saved}, 409 if changed else 200
            return render_template("agent_setup.html", **context), 409 if changed else 200

    @app.post("/agents/settings")
    def agents_update():
        ui_guard()
        m.BASE.mkdir(parents=True, exist_ok=True)
        with m.DATA_LOCK, data_lock(m.BASE), data_lock(m.DATA_DIR):
            action = request.form.get("action")
            in_settings = request.form.get("return_to") == "settings"
            inline = in_settings and request.headers.get("X-Requested-With") == "fetch"
            token = None
            if action == "enable":
                if request.form.get("consent") != "yes":
                    abort(400)
                access.enable(True)
            elif action == "disable":
                state = access.load()
                if state.get("enabled") or state["connections"]:
                    revision = digest(json.dumps(state, sort_keys=True))
                    confirmed = request.form.get("confirm") == "yes"
                    if not confirmed or request.form.get("revision") != revision:
                        context = dict(connections=state["connections"].values(), revision=revision,
                                       changed=confirmed, csrf=csrf(), in_settings=in_settings, inline=inline)
                        if inline:
                            return {"confirmation": render_template("_agent_disable_confirmation.html", **context)}, 409 if confirmed else 200
                        return render_template("agent_disable.html", **context), 409 if confirmed else 200
                access.enable(False)
            elif action in {"pause", "resume"}:
                access.set_active(request.form.get("connection", ""), action == "resume")
            elif action == "revoke":
                identifier = request.form.get("connection", "")
                connection = access.load()["connections"].get(identifier)
                if not connection:
                    abort(404)
                if request.form.get("confirm") != "yes":
                    context = dict(connection=connection, csrf=csrf(), in_settings=in_settings, inline=inline)
                    if inline:
                        return {"confirmation": render_template("_agent_revoke_confirmation.html", **context)}
                    return render_template("agent_revoke.html", **context)
                access.revoke(identifier)
            elif action == "connect":
                assistant = request.form.get("assistant", "other")
                if assistant not in ASSISTANTS:
                    abort(400)
                name = connection_name(assistant)
                state = access.load()
                if not state.get("enabled") or len(state["connections"]) >= 20:
                    raise AccessError("Enable access first; at most 20 connections are supported.")
                token = access.create(name, directory=m.DATA_DIR, assistant=assistant, **permission_fields())
            else:
                abort(400)
            if in_settings:
                if inline:
                    return panel_response(token)
                if not token:
                    return redirect(url_for("validate"))
            return settings_page(token)

    def request_view(entry, identifier, *, decided=False):
        inline = request.headers.get("X-Requested-With") == "fetch"
        context = dict(entry=entry, identifier=identifier, csrf=csrf(), inline=inline)
        if inline:
            return {"confirmation": render_template("_agent_request_content.html", **context),
                    "decided": decided}
        return render_template("agent_request.html", **context)

    @app.get("/agents/requests/<identifier>")
    def agents_review(identifier):
        ui_guard()
        with m.DATA_LOCK:
            entry = access.get(identifier)
            return request_view(entry, identifier)

    @app.post("/agents/requests/<identifier>")
    def agents_decide(identifier):
        ui_guard()
        with m.DATA_LOCK, data_lock(m.DATA_DIR):
            entry = access.get(identifier)
            connection = access.connection(entry["connection"]["id"], m.DATA_DIR)
            decide_entry(entry, connection, request.form.get("decision"))
            if request.headers.get("X-Requested-With") == "fetch":
                return request_view(entry, identifier, decided=True)
            return redirect(url_for("agents_review", identifier=identifier), code=303)

    def decide_entry(entry, connection, decision):
        if entry["status"] != "pending":
            abort(409)
        if connection != entry["connection"]:
            abort(403)
        if decision not in {"approve", "deny", "cancel"}:
            abort(400)
        entry.pop("client_nonce", None)
        if decision != "approve":
            entry.update(status="denied" if decision == "deny" else "cancelled", confirmation=None, arguments={})
            return
        # Consume before execution; app and client decisions share this one-shot path.
        entry["status"] = "executing"
        try:
            result = execute(connection, entry["operation"], entry["arguments"], entry["confirmation"]["fingerprint"])
            entry.update(status="completed" if result.get("ok") else "failed", result=result)
        finally:
            if entry["status"] == "executing":
                entry["status"] = "failed"
            entry.update(confirmation=None, arguments={})

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

    def bearer_token():
        enabled()
        # Not a browser API. No cookies, cross-origin requests, arbitrary URLs or file paths.
        if request.headers.get("Origin") or request.headers.get("Cookie"):
            abort(403)
        request.max_content_length = 1_000_000
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            abort(401)
        return authorization[7:]

    @app.post("/agents/call")
    def agents_call():
        token = bearer_token()
        with m.DATA_LOCK, data_lock(m.DATA_DIR):
            connection = access.authenticate(token, m.DATA_DIR)
            payload = request.get_json()
            if not isinstance(payload, dict) or set(payload) != {"tool", "arguments"}:
                abort(400)
            result = execute(connection, payload["tool"], payload["arguments"])
            if result.get("status") == "approval_required" and connection.get("client_approvals") is True:
                entry = access.get(result["request_id"], connection)
                # Private bridge envelope: stripped before any tool result reaches the model.
                nonce = entry.setdefault("client_nonce", secrets.token_urlsafe(32))
                review = {k: v for k, v in entry["confirmation"].items() if k != "fingerprint"}
                result["_client_approval"] = {"nonce": nonce, "connection": connection["name"], "review": review}
            return result

    @app.post("/agents/client-decision")
    def agents_client_decision():
        token = bearer_token()
        with m.DATA_LOCK, data_lock(m.DATA_DIR):
            connection = access.authenticate(token, m.DATA_DIR)
            payload = request.get_json()
            if (not isinstance(payload, dict) or set(payload) != {"request_id", "nonce", "decision"}
                    or any(not isinstance(v, str) for v in payload.values())):
                abort(400)
            entry = access.get(payload["request_id"], connection)
            if (connection.get("client_approvals") is not True or not entry.get("client_nonce")
                    or not secrets.compare_digest(entry["client_nonce"].encode(), payload["nonce"].encode())):
                abort(403)
            decide_entry(entry, connection, payload["decision"])
            return {**entry.get("result", {"ok": False}), "status": entry["status"], "request_id": payload["request_id"]}

    def execute(connection, operation, arguments, approved=""):
        try:
            if not isinstance(operation, str):
                raise ValueError("Expected a tool name.")
            validate(operation, arguments)
            policy = permission(connection, operation)
            if policy == "deny":
                raise AccessError("This operation is not permitted for this connection.")
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
                query = arguments.get("query", "").lower()
                return {"ok": True, "customers": [c for c in customer_scope.visible_customers(connection, customer_records())
                                                   if query in c.get("name", "").lower()]}
            if operation == "invoice_schema":
                return {"ok": True, "tools": TOOLS, "units": {u[0]: u[1] for u in m.UNITS},
                        "tax_treatments": {k: v["label"] for k, v in m.TAX_TREATMENTS.items()}}
            if operation in {"save_customer", "save_customer_items", "delete_customer",
                             "check_invoice", "preview_invoice", "create_invoice"}:
                customer_scope.require_customer(connection, arguments, customer_records(), operation)
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
                g.mcp_operation = operation
                g.mcp_policy = policy
                g.mcp_customer_policy = permission(connection, "save_customer")
                g.mcp_approved = approved
                early = app.preprocess_request()
                if early is not None:
                    raise ValueError("App rejected this operation.")
                if m.CUSTOMERS_FILE.is_symlink() or any(p.is_symlink() for p in m.output_dir().iterdir()):
                    raise ValueError("Linked customer or archive files are not supported.")
                source = arguments.get("correction_source")
                if source and customer_scope.mode(connection) != "all":
                    original = require_invoice(connection, source)
                    if original.get("customer_id") != arguments.get("customer_id"):
                        raise AccessError("Invoice not permitted.")
                if operation == "delete_invoice" and customer_scope.mode(connection) != "all":
                    require_invoice(connection, arguments["filename"])
                if operation in {"get_issuer", "list_invoices", "get_invoice", "get_invoice_file", "next_number"}:
                    return read_data(connection, operation, arguments)
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
                    if isinstance(result, dict) and "customers" in result:
                        result["customers"] = customer_scope.visible_customers(connection, result["customers"])
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

    def require_invoice(connection, filename):
        original = m.correction_original(filename)
        if not customer_scope.permitted_invoice(connection, original, customer_records()):
            raise AccessError("Invoice not permitted.")
        if not original:
            raise ValueError("Invoice snapshot unavailable.")
        return original

    def read_data(connection, operation, arguments):
        if operation == "get_issuer":
            seller = m.load_seller()
            return {"ok": True, "seller": seller, "revision": m.seller_revision(seller)}
        if operation == "list_invoices":
            if customer_scope.mode(connection) == "none":
                return {"ok": True, "invoices": []}
            customers = customer_records()
            # The UI defaults to the current year; MCP promises the full granted
            # archive. Its internal sort sentinel (-inf for undated rows) is not JSON.
            return {"ok": True, "invoices": [{k: v for k, v in entry.items() if k != "created_sort"}
                    for entry in m._settings_context(archive_year="all")["archive"]
                    if customer_scope.permitted_invoice(connection, m.correction_original(entry["filename"]), customers)]}
        if operation in {"get_invoice", "get_invoice_file"}:
            filename = arguments["filename"]
            if Path(filename).name != filename:
                raise ValueError("Invalid filename.")
            original = require_invoice(connection, filename)
            if operation == "get_invoice":
                return {"ok": True, "invoice": original}
            file_format = arguments["format"]
            embedded_xml = file_format == "xml" and original["invoice"].get("profile") != "xrechnung"
            path = (m.output_dir() / filename).with_suffix(".pdf" if embedded_xml else "." + file_format)
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
                raise ValueError("File unavailable or too large.")
            content = path.read_bytes()
            if customer_scope.mode(connection) != "all":
                # Bind the bytes actually returned to the original customer
                # assignment, not to a mutable validation receipt. Revalidating
                # an externally replaced file must never grant its new contents.
                receipt = original.get("_archive")
                checksums = receipt.get("sha256") if isinstance(receipt, dict) else None
                expected = checksums.get(path.name) if isinstance(checksums, dict) else None
                if expected != hashlib.sha256(content).hexdigest():
                    raise AccessError("File changed or archive checksum unavailable; "
                                      "download denied for customer-restricted access.")
            if embedded_xml:
                from pypdf.errors import PyPdfError
                try:
                    content = m.extract_xml_from_pdf(content)
                except (PyPdfError, ValueError, KeyError) as exc:
                    raise ValueError("Cannot read XML from the archived PDF.") from exc
                if not content or len(content) > 20_000_000:
                    raise ValueError("Embedded XML unavailable or too large.")
            return {"ok": True, "filename": path.with_suffix("." + file_format).name,
                    "mime_type": "application/" + file_format, "base64": base64.b64encode(content).decode()}
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
