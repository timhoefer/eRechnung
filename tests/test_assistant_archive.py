"""Shared archive behavior, using only isolated fictional data."""
import json
from datetime import date
from pathlib import Path

import pytest

import app as appmod
import assistant_cli as cli
import invoice_archive as archive
from scripts.create_assistant_demo import create_demo


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = create_demo(tmp_path / "source")
    monkeypatch.setattr(appmod, "OUTPUT_DIR", source / "output")
    monkeypatch.setattr(appmod, "SELLER_FILE", source / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", source / "customers.json")
    data = cli.create_draft(source, "Beispiel GmbH", "Rechnung_DEMO-ALT.json")
    data["invoice"].update(number=f"{date.today().year}-042", issue_date="2026-10-07",
                           due_date="2026-10-21")
    return source, data


def invoke(capsys, source, command, data, tmp_path):
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    code = cli.main(["--data-dir", str(source), command, "--draft", str(path)])
    result = json.loads(capsys.readouterr().out)
    assert code == (0 if result["ok"] else 2)
    return result


def publish(source, data):
    return archive.archive_invoice(data, b"%PDF-test", b"<xml/>", source / "output", source / "seller.json")


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
def test_skill_archive_is_visible_usable_and_retry_preserves_bytes(setup, capsys, tmp_path, profile):
    source, data = setup
    data["invoice"]["profile"] = profile
    seller_before = cli.seller_from(source)
    customers_before = (source / "customers.json").read_bytes()
    result = invoke(capsys, source, "archive", data, tmp_path)
    assert result["ok"] and result["archived"] and result["validation"]["valid"], result
    assert not result["reused"]
    files = {Path(path): Path(path).read_bytes() for path in result["files"]}
    assert all(path.parent == source / "output" for path in files)
    assert any(path.suffix == ".xml" for path in files) == (profile == "xrechnung")
    current = cli.seller_from(source)
    assert current["last_invoice_number"] == data["invoice"]["number"]
    assert archive.seller_details(current) == archive.seller_details(seller_before)
    assert (source / "customers.json").read_bytes() == customers_before
    with appmod.app.test_client() as client:
        body = client.get("/settings/panel").get_data(as_text=True)
        assert data["invoice"]["number"] in body and "Beispiel GmbH" in body
        assert client.get("/archive/preview/" + result["filename"]).data == files[source / "output" / result["filename"]]
        assert "Beispiel GmbH" in client.get("/export/csv").get_data(as_text=True)
        assert client.get("/?from=" + result["filename"]).status_code == 200
        assert f'{date.today().year}-043' in client.get("/").get_data(as_text=True)
    again = invoke(capsys, source, "archive", data, tmp_path)
    assert again["ok"] and again["reused"], again
    assert all(path.read_bytes() == content for path, content in files.items())
    data["items"][0]["unit_price"] = "999"
    conflict = invoke(capsys, source, "archive", data, tmp_path)
    assert conflict["error"]["code"] == "number_conflict"
    assert all(path.read_bytes() == content for path, content in files.items())


def test_invalid_invoice_never_writes_archive_or_number(setup, capsys, tmp_path, monkeypatch):
    source, data = setup
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    monkeypatch.setattr(cli, "validate_schematron", lambda _: {"available": False})
    result = invoke(capsys, source, "archive", data, tmp_path)
    assert not result["ok"]
    assert {p: p.read_bytes() for p in source.rglob("*") if p.is_file()} == before


def test_seller_change_during_render_rejects_stale_invoice(setup, capsys, tmp_path, monkeypatch):
    source, data = setup
    render = cli.build_pdf
    def change_seller(*args):
        seller = cli.seller_from(source)
        seller["iban"] = "CHANGED"
        (source / "seller.json").write_bytes(archive.canonical(seller))
        return render(*args)
    monkeypatch.setattr(cli, "build_pdf", change_seller)
    result = invoke(capsys, source, "archive", data, tmp_path)
    assert result["error"]["code"] == "stale_seller"
    assert not list((source / "output").glob("*.pdf"))












def test_next_number_is_read_only_and_considers_archive(setup, capsys):
    source, data = setup
    publish(source, data)
    seller = cli.seller_from(source)
    seller["last_invoice_number"] = f"{date.today().year}-001"
    (source / "seller.json").write_bytes(archive.canonical(seller))
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert cli.main(["--data-dir", str(source), "next-number"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["number"] == f"{date.today().year}-043" and not result["reserved"]
    assert {p: p.read_bytes() for p in source.rglob("*") if p.is_file()} == before






@pytest.mark.parametrize("last,archived,unclear", [
    ("", [], True),
    ("INV-2026-09", ["INV-2026-09"], True),
    ("{previous}-050", ["{previous}-050"], True),
    ("{year}-002", ["PROJECT-{year}-003"], True),
    ("{year}-002", ["{year}-003"], False),
    ("{previous}-050", ["{year}-002"], False),
])
def test_unclear_numbering_requires_a_question(setup, last, archived, unclear):
    source, _ = setup
    year = date.today().year
    for path in (source / "output").glob("*.json"):
        path.unlink()
    seller = cli.seller_from(source)
    seller["last_invoice_number"] = last.format(year=year, previous=year-1)
    (source / "seller.json").write_bytes(archive.canonical(seller))
    for index, number in enumerate(archived):
        (source / "output" / f"entry{index}.json").write_bytes(archive.canonical({
            "invoice": {"number": number.format(year=year, previous=year-1)},
        }))
    result = cli.number_proposal(source)
    assert result["requires_clarification"] is unclear
    assert (result["number"] is None) is unclear
    assert bool(result["reasons"]) is unclear
    assert not result["reserved"]


@pytest.mark.parametrize("sidecars", [True, False])
def test_legacy_duplicates_require_real_invoice_number_instead_of_maximum(setup, sidecars):
    source, data = setup
    year = date.today().year
    number = f"{year}-099"
    seller = cli.seller_from(source)
    seller["last_invoice_number"] = number
    (source / "seller.json").write_bytes(archive.canonical(seller))
    for suffix in ("", " (2)"):
        pdf = source / "output" / f"Rechnung_{number}{suffix}.pdf"
        pdf.write_bytes(b"test invoice")
        if sidecars:
            pdf.with_suffix(".json").write_bytes(archive.canonical({"invoice": {"number": number}}))
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    result = cli.number_proposal(source)
    assert result["requires_clarification"]
    assert result["number"] is None and result["suggestion"] is None
    assert len(result["duplicate_numbers"][number]) == 2
    assert number in archive.archived_numbers(source / "output")
    assert {p: p.read_bytes() for p in source.rglob("*") if p.is_file()} == before


def test_pdf_and_its_sidecar_count_as_one_invoice(setup):
    source, data = setup
    publish(source, data)
    result = cli.number_proposal(source)
    assert not result["requires_clarification"]
    assert result["duplicate_numbers"] == {}
