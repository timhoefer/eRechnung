"""Customer grants must cover every data path, not just the customer picker."""
import hashlib
import json

import pytest
from lxml import html
from test_mcp_access import BUYER, call, configure, decide, grant, invoice_args, snapshot
from test_mcp_access import client as client
from test_mcp_access import fresh_access as fresh_access

import app as m

PRIVATE = {**BUYER, "name": "Private client", "email": "private@example.org",
           "items": [{"description": "Confidential project", "unit_price": "987"}]}


def selection_keys(client, *names):
    page = html.fromstring(client.get("/agents").data)
    return [label.xpath('.//input/@value')[0] for label in page.xpath('//label[.//input[@name="customers"]]')
            if label.text_content().strip() in names]


def scoped_grant(client, mode="selected", names=(BUYER["name"],), writable=True):
    assert configure(client, "enable", consent="yes").status_code == 200
    response = configure(client, "connect", name="Scoped agent", issuers=["default"],
                         write="yes" if writable else "", customer_mode=mode,
                         customers=selection_keys(client, *names))
    assert response.status_code == 200
    config = json.loads(html.fromstring(response.data).get_element_by_id("mcp-configuration").text)
    return config["mcpServers"]["erechnung"]["env"]["ERECHNUNG_MCP_TOKEN"]


def selected_args(token):
    customer = call(token, "list_customers")["customers"][0]
    return {**invoice_args(), "customer_id": customer["customer_id"]}


def finalize(client, token, arguments):
    pending = call(token, "create_invoice", **arguments)
    assert pending.get("status") == "approval_required", pending
    assert decide(client, pending["request_id"]).status_code == 303
    status = call(token, "request_status", request_id=pending["request_id"])
    assert status["status"] == "completed", status
    return status["result"]["filename"]


def seed_archive(name, buyer, customer_id=None):
    # Cheap existing files for authorization tests; successful PDF/XML paths use
    # the actual generator below. No real invoice data enters this suite.
    original = {"issuer_id": "default", "seller": m.load_seller(), "buyer": buyer,
                "invoice": {**invoice_args()["invoice"], "number": name}, "items": invoice_args()["items"]}
    if customer_id:
        original["customer_id"] = customer_id
    stem = m.OUTPUT_DIR / ("Rechnung_" + name)
    stem.with_suffix(".pdf").write_bytes(b"fictional archived PDF")
    original["_archive"] = {"sha256": {
        stem.with_suffix(".pdf").name: hashlib.sha256(b"fictional archived PDF").hexdigest(),
    }}
    stem.with_suffix(".json").write_text(json.dumps(original))
    return stem.with_suffix(".pdf").name


@pytest.mark.parametrize("language", ["de", "en"])
@pytest.mark.parametrize("customers", [[], [BUYER], [BUYER, PRIVATE]])
def test_new_grant_defaults_to_all_but_requires_an_explicit_scope_submission(client, language, customers):
    client.set_cookie("lang", language)
    m._write_json(m.CUSTOMERS_FILE, customers)
    assert configure(client, "enable", consent="yes").status_code == 200
    page = html.fromstring(client.get("/agents").data)
    mode = page.get_element_by_id("agent-customer-mode")
    assert mode.value == "all"
    assert mode.xpath('./option/@value') == ["selected", "all"]
    group, = page.xpath('//*[@data-selection-group="customers"]')
    assert "hidden" in group.attrib and "disabled" in group.attrib
    assert len(group.xpath('.//input[@name="customers"]')) == len(customers)
    assert not group.xpath('.//input[@checked]')
    access = m.app.extensions["mcp_access"]
    before = access.load(), snapshot()
    # Omitting the field cannot silently create an unrestricted or unusable grant.
    response = configure(client, "connect", name="Default grant", issuers="default", write="yes")
    assert response.status_code == 403
    assert (access.load(), snapshot()) == before
    token = scoped_grant(client, mode="all", names=())
    assert access.authenticate(token, m.DATA_DIR)["customer_mode"] == "all"


def test_legacy_no_customer_access_stays_restricted(client):
    token = scoped_grant(client, mode="none")
    filename = seed_archive("OLD", BUYER)
    before = snapshot()
    assert call(token, "list_customers")["customers"] == []
    assert call(token, "list_invoices", issuer="default")["invoices"] == []
    assert call(token, "get_issuer", issuer="default")["ok"]
    assert call(token, "invoice_schema")["ok"]
    for operation in ("get_invoice", "delete_invoice"):
        assert not call(token, operation, issuer="default", filename=filename)["ok"]
    assert not call(token, "get_invoice_file", issuer="default", filename=filename, format="pdf")["ok"]
    for operation in ("check_invoice", "preview_invoice", "create_invoice"):
        assert not call(token, operation, **invoice_args())["ok"]
    assert not call(token, "save_customer", issuer="default", buyer=BUYER)["ok"]
    assert snapshot() == before
    assert not m.app.extensions["mcp_access"].pending


@pytest.mark.parametrize("problem", ["empty", "unknown", "changed", "invalid_mode", "ambiguous"])
def test_invalid_or_stale_selection_never_grants_access(client, problem):
    configure(client, "enable", consent="yes")
    keys = selection_keys(client, BUYER["name"])
    if problem == "empty":
        keys = []
    elif problem == "unknown":
        keys = ["x" * 64]
    elif problem == "changed":
        m._write_json(m.CUSTOMERS_FILE, [{**BUYER, "city": "Hamburg"}])
    elif problem == "ambiguous":
        m._write_json(m.CUSTOMERS_FILE, [BUYER, BUYER])
    before = snapshot()
    response = configure(client, "connect", name="Scoped", issuers="default",
                         customer_mode="invalid" if problem == "invalid_mode" else "selected", customers=keys)
    assert response.status_code in (400, 403)
    assert not m.app.extensions["mcp_access"].load()["connections"]
    assert snapshot() == before


def test_multiple_selected_customers_search_items_and_future_customers(client):
    second = {**BUYER, "name": "Second selected", "items": invoice_args()["items"]}
    m._write_json(m.CUSTOMERS_FILE, [BUYER, second, PRIVATE])
    token = scoped_grant(client, names=(BUYER["name"], second["name"]))
    customers = call(token, "list_customers")["customers"]
    assert [c["name"] for c in customers] == [BUYER["name"], second["name"]]
    assert customers[1]["items"] == second["items"]
    assert all(c["customer_id"] and "_customer_id" not in c for c in customers)
    assert call(token, "list_customers", query="Private")["customers"] == []
    m._write_json(m.CUSTOMERS_FILE, [*m.load_customers(), {**BUYER, "name": "Added later"}])
    assert call(token, "list_customers")["customers"] == customers


@pytest.mark.parametrize("legacy", [False, True])
def test_all_and_legacy_grants_preserve_full_access(client, legacy):
    token = grant(client)
    access = m.app.extensions["mcp_access"]
    if legacy:
        state = access.load()
        connection = next(iter(state["connections"].values()))
        del connection["customer_mode"]
        del connection["customer_ids"]
        access.save(state)
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    filename = seed_archive("LEGACY", PRIVATE)
    assert len(call(token, "list_customers")["customers"]) == 2
    assert call(token, "get_invoice", issuer="default", filename=filename)["ok"]
    assert len(call(token, "list_invoices", issuer="default")["invoices"]) == 1


@pytest.mark.parametrize("operation", ["save_customer", "save_customer_items", "delete_customer",
                                       "check_invoice", "preview_invoice", "create_invoice"])
@pytest.mark.parametrize("bad", ["missing_id", "wrong_id", "foreign_name", "injected_id"])
def test_denied_customer_operations_cannot_read_write_or_request_approval(client, operation, bad):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    token = scoped_grant(client)
    arguments = selected_args(token)
    buyer = dict(BUYER)
    if bad == "missing_id":
        arguments.pop("customer_id")
    elif bad == "wrong_id":
        arguments["customer_id"] = "f" * 32
    elif bad == "foreign_name":
        buyer = {k: v for k, v in PRIVATE.items() if k != "items"}
    else:
        buyer["_customer_id"] = arguments["customer_id"]
    arguments["buyer"] = buyer
    if operation not in {"check_invoice", "preview_invoice", "create_invoice"}:
        arguments = {k: v for k, v in arguments.items() if k in {"issuer", "buyer", "customer_id", "items"}}
        if operation == "save_customer":
            arguments.pop("items")
        elif operation == "delete_customer":
            arguments = {k: v for k, v in arguments.items() if k not in {"buyer", "items"}}
            arguments["name"] = buyer["name"]
            if bad == "injected_id":
                arguments["_customer_id"] = arguments["customer_id"]
    before = snapshot()
    assert not call(token, operation, **arguments)["ok"]
    assert not m.app.extensions["mcp_access"].pending
    assert snapshot() == before


def test_renaming_and_updates_keep_identity_without_leaking_other_customers(client):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    token = scoped_grant(client)
    identifier = selected_args(token)["customer_id"]
    renamed = {**BUYER, "name": "Renamed client", "city": "Hamburg"}
    pending = call(token, "save_customer", issuer="default", buyer=renamed,
                   previous_name=BUYER["name"], customer_id=identifier)
    assert pending["status"] == "approval_required"
    assert decide(client, pending["request_id"]).status_code == 303
    status = call(token, "request_status", request_id=pending["request_id"])
    assert status["status"] == "completed"
    assert "Private client" not in json.dumps(status)
    customer, = call(token, "list_customers")["customers"]
    assert customer["customer_id"] == identifier and customer["name"] == renamed["name"]
    result = call(token, "save_customer_items", issuer="default", buyer=renamed,
                  customer_id=identifier, items=invoice_args()["items"])
    # Adding new saved items may be direct; replacing existing ones is confirmed.
    if result.get("status") == "approval_required":
        decide(client, result["request_id"])
        result = call(token, "request_status", request_id=result["request_id"])
    assert "Private client" not in json.dumps(result)
    assert m.load_customers()[1] == PRIVATE
    assert m.load_customers()[0]["_customer_id"] == identifier


def test_deletion_and_same_name_recreation_do_not_inherit_grant(client):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    token = scoped_grant(client)
    identifier = selected_args(token)["customer_id"]
    filename = seed_archive("GRANTED", BUYER, identifier)
    pending = call(token, "delete_customer", issuer="default", name=BUYER["name"], customer_id=identifier)
    assert decide(client, pending["request_id"]).status_code == 303
    status = call(token, "request_status", request_id=pending["request_id"])
    assert status["status"] == "completed" and "Private client" not in json.dumps(status)
    m._write_json(m.CUSTOMERS_FILE, [*m.load_customers(), BUYER])
    fresh = scoped_grant(client)
    assert selected_args(fresh)["customer_id"] != identifier
    assert call(token, "list_customers")["customers"] == []
    for credential in (token, fresh):
        assert not call(credential, "get_invoice", issuer="default", filename=filename)["ok"]
    assert (m.OUTPUT_DIR / filename).exists()


@pytest.mark.parametrize("replacement", ["deleted", "duplicate_id"])
def test_pending_approval_rechecks_customer_identity(client, replacement):
    token = scoped_grant(client)
    identifier = selected_args(token)["customer_id"]
    pending = call(token, "save_customer", issuer="default", customer_id=identifier,
                   buyer={**BUYER, "city": "Hamburg"})
    customers = [BUYER] if replacement == "deleted" else [*m.load_customers(), {**PRIVATE, "_customer_id": identifier}]
    m._write_json(m.CUSTOMERS_FILE, customers)
    before = snapshot()
    assert decide(client, pending["request_id"]).status_code == 303
    status = call(token, "request_status", request_id=pending["request_id"])
    assert status["status"] == "failed"
    assert call(token, "list_customers")["customers"] == []
    assert snapshot() == before


def test_archive_filters_and_direct_file_actions_fail_closed(client):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    token = scoped_grant(client)
    identifier = selected_args(token)["customer_id"]
    allowed = seed_archive("ALLOWED", BUYER, identifier)
    blocked = [seed_archive("PRIVATE", PRIVATE, "b" * 32), seed_archive("UNLINKED", BUYER)]
    assert [i["filename"] for i in call(token, "list_invoices", issuer="default")["invoices"]] == [allowed]
    assert call(token, "get_invoice", issuer="default", filename=allowed)["ok"]
    assert call(token, "get_invoice_file", issuer="default", filename=allowed, format="pdf")["ok"]
    before = snapshot()
    for filename in blocked:
        for operation in ("get_invoice", "delete_invoice"):
            assert not call(token, operation, issuer="default", filename=filename)["ok"]
        for file_format in ("pdf", "xml"):
            assert not call(token, "get_invoice_file", issuer="default", filename=filename, format=file_format)["ok"]
    assert not m.app.extensions["mcp_access"].pending
    assert snapshot() == before
    pending = call(token, "delete_invoice", issuer="default", filename=allowed)
    assert pending["status"] == "approval_required"
    assert decide(client, pending["request_id"]).status_code == 303
    assert not (m.OUTPUT_DIR / allowed).exists()
    assert all((m.OUTPUT_DIR / filename).exists() for filename in blocked)


@pytest.mark.parametrize("kind", ["381", "384"])
def test_corrections_require_permitted_original_and_matching_customer(client, kind):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    token = scoped_grant(client, names=(BUYER["name"], PRIVATE["name"]))
    arguments = selected_args(token)
    customers = call(token, "list_customers")["customers"]
    allowed = seed_archive("SOURCE", BUYER, customers[0]["customer_id"])
    foreign = seed_archive("OTHER", PRIVATE, customers[1]["customer_id"])
    unlinked = seed_archive("OLD", BUYER)
    arguments["invoice"].update(number="CORRECTION", doc_type=kind, ref_number="SOURCE")
    before = snapshot()
    for source in (None, foreign, unlinked):
        tested = {**arguments, **({"correction_source": source} if source else {})}
        assert not call(token, "create_invoice", **tested)["ok"]
    assert snapshot() == before
    assert not m.app.extensions["mcp_access"].pending
    filename = finalize(client, token, {**arguments, "correction_source": allowed})
    saved = json.loads((m.OUTPUT_DIR / filename).with_suffix(".json").read_text())
    assert saved["customer_id"] == arguments["customer_id"]


def test_selected_invoice_generation_preview_and_download(client):
    token = scoped_grant(client)
    arguments = selected_args(token)
    before = snapshot()
    assert call(token, "check_invoice", **arguments)["ok"]
    preview = call(token, "preview_invoice", **arguments)
    assert preview["ok"] and preview["base64"]
    assert snapshot() == before
    filename = finalize(client, token, arguments)
    invoice = call(token, "get_invoice", issuer="default", filename=filename)["invoice"]
    assert invoice["customer_id"] == arguments["customer_id"]
    assert len(call(token, "list_invoices", issuer="default")["invoices"]) == 1
    for file_format in ("pdf", "xml"):
        assert call(token, "get_invoice_file", issuer="default", filename=filename, format=file_format)["ok"]


@pytest.mark.parametrize("original_linked", [False, True])
def test_correction_with_changed_customer_never_inherits_original_grant(client, original_linked):
    m._write_json(m.CUSTOMERS_FILE, [BUYER, PRIVATE])
    scoped = scoped_grant(client, names=(BUYER["name"], PRIVATE["name"]))
    customers = call(scoped, "list_customers")["customers"]
    source = seed_archive("SOURCE", BUYER, customers[0]["customer_id"] if original_linked else None)
    full = grant(client)
    arguments = invoice_args()
    arguments["buyer"] = {k: v for k, v in PRIVATE.items() if k != "items"}
    arguments["invoice"].update(number="CHANGED-RECIPIENT", doc_type="384", ref_number="SOURCE")
    arguments["correction_source"] = source
    filename = finalize(client, full, arguments)
    invoice = call(full, "get_invoice", issuer="default", filename=filename)["invoice"]
    assert "customer_id" not in invoice
    assert not call(scoped, "get_invoice", issuer="default", filename=filename)["ok"]


def test_grant_and_identical_reexport_never_relabel_old_invoices(client):
    full = grant(client)
    original_args = invoice_args()
    filename = finalize(client, full, original_args)
    archived = {p.name: p.read_bytes() for p in m.OUTPUT_DIR.iterdir() if p.is_file()}
    token = scoped_grant(client)
    assert not call(token, "get_invoice", issuer="default", filename=filename)["ok"]
    arguments = selected_args(token)
    assert finalize(client, token, arguments) == filename
    assert {p.name: p.read_bytes() for p in m.OUTPUT_DIR.iterdir() if p.is_file()} == archived
    assert not call(token, "get_invoice", issuer="default", filename=filename)["ok"]
