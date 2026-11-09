"""Keep agent-created invoices compatible with the normal app's data and forms."""
import json

import pytest
from test_assistant_cli import call, save, snapshot
from test_assistant_cli import draft as draft
from test_assistant_cli import source as source

import assistant_cli as cli


@pytest.mark.parametrize("digits", ["١٢", "１２", "1.٢"])
@pytest.mark.parametrize("section,field", [
    ("item", "quantity"), ("item", "unit_price"), ("item", "item_discount"),
    ("invoice", "discount"), ("invoice", "prepaid"),
])
def test_non_ascii_numbers_cannot_reach_invoice_calculation(source, draft, section, field, digits):
    target = draft["items"][0] if section == "item" else draft["invoice"]
    target[field] = digits
    data, errors = cli.prepare(draft, source)
    expected = f"items.0.{field}" if section == "item" else f"invoice.{field}"
    assert not data
    assert any(error["field"] == expected and "ASCII" in error["message"] for error in errors)


@pytest.mark.parametrize("command", ["check", "preview", "export", "archive"])
def test_non_ascii_amounts_fail_without_rendering_or_writing(source, draft, tmp_path, capsys, monkeypatch, command):
    draft["items"][0]["quantity"] = "١٢"
    path = save(tmp_path / "draft.json", draft)
    before = snapshot(tmp_path)
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid numbers must be rejected before rendering or validation")
    monkeypatch.setattr(cli, "render_invoice_preview", unexpected)
    monkeypatch.setattr(cli, "build_xml", unexpected)
    extra = ["--out", tmp_path / "preview.pdf"] if command == "preview" else (
        ["--out-dir", tmp_path / "exports"] if command == "export" else [])
    result = call(capsys, source, command, "--draft", path, *extra)
    assert not result["ok"] and result["errors"][0]["field"] == "items.0.quantity"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("selected,query", [(0, "Straße"), (0, "STRAẞE"), (1, "Strasse"), (1, "STRASSE")])
def test_customer_and_template_selection_keep_distinct_names_separate(source, selected, query):
    original = cli.customers_from(source)[0]
    customers = [dict(original, name="Straße", city="Berlin"),
                 dict(original, name="Strasse", city="Hamburg")]
    (source / "customers.json").write_text(json.dumps(customers))
    previous = cli.read_json(source / "output/Rechnung_DEMO-ALT.json")
    for i, customer in enumerate(customers):
        save(source / f"output/customer-{i}.json", dict(previous, buyer=customer))
    before = snapshot(source)
    draft = cli.create_draft(source, query, None)
    assert draft["buyer"]["name"] == customers[selected]["name"]
    assert draft["buyer"]["city"] == customers[selected]["city"]
    templates = cli.templates_from(source, query)
    assert [t["template"] for t in templates] == [f"customer-{selected}.json"]
    assert cli.create_draft(source, query, templates[0]["template"])["buyer"] == draft["buyer"]
    with pytest.raises(cli.InputError, match="different customer"):
        cli.create_draft(source, query, f"customer-{1-selected}.json")
    assert snapshot(source) == before
