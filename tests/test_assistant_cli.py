"""Behavioral checks for the removable, read-only local assistant adapter."""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import assistant_cli as cli
from scripts.create_assistant_demo import create_demo
from zugferd import extract_xml_from_pdf

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path):
    return create_demo(tmp_path / "source")


@pytest.fixture
def draft(source):
    data = cli.create_draft(source, "Beispiel GmbH", "Rechnung_DEMO-ALT.json")
    data["invoice"].update(number="DEMO-2026-002", issue_date="2026-10-07", due_date="2026-10-21",
                           service_start="2026-10-01", service_end="2026-10-03")
    return data


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def call(capsys, source, *arguments):
    code = cli.main(["--data-dir", str(source), *map(str, arguments)])
    result = json.loads(capsys.readouterr().out)
    assert code == (0 if result["ok"] else 2)
    return result


def test_draft_clears_old_dates_discounts_and_uses_current_details(source):
    previous_path = source / "output/Rechnung_DEMO-ALT.json"
    previous = cli.read_json(previous_path)
    previous["invoice"].update(prepaid="100", discount="10", ref_number="OLDER")
    previous["items"][0].update(item_start="2026-09-01", item_end="2026-09-03", item_discount="5")
    previous["seller"]["iban"] = "OBSOLETE"
    previous["buyer"]["address_line"] = "Old address"
    save(previous_path, previous)
    before = snapshot(source)
    data = cli.create_draft(source, "Beispiel GmbH", previous_path.name)
    assert data["seller"]["iban"] != "OBSOLETE"
    assert data["buyer"]["address_line"] != "Old address"
    assert data["invoice"]["number"] == data["invoice"]["issue_date"] == ""
    assert data["invoice"]["due_date"] is None
    assert not {"service_start", "prepaid", "discount", "ref_number"} & data["invoice"].keys()
    assert not {"item_start", "item_end", "item_discount"} & data["items"][0].keys()
    assert snapshot(source) == before


def test_read_commands_and_draft_do_not_change_source(capsys, source, tmp_path):
    before = snapshot(source)
    assert len(call(capsys, source, "customers", "--query", "beispiel")["customers"]) == 1
    assert len(call(capsys, source, "templates", "--customer", "Beispiel GmbH")["templates"]) == 1
    path = tmp_path / "draft.json"
    assert call(capsys, source, "draft", "--customer", "Beispiel GmbH", "--out", path)["ok"]
    assert not call(capsys, source, "check", "--draft", path)["ok"]
    assert snapshot(source) == before


@pytest.mark.parametrize("change,expected", [
    (lambda d: d["invoice"].update(tax_treatment="invented"), "invoice.tax_treatment"),
    (lambda d: d["invoice"].update(issue_date="2026-02-30"), "invoice.issue_date"),
    (lambda d: d["invoice"].update(due_date="2026-01-01"), "invoice.due_date"),
    (lambda d: d["invoice"].update(service_end=None), "invoice"),
    (lambda d: d["items"][0].update(unit_price="1,000"), "items.0.unit_price"),
    (lambda d: d["items"][0].update(unit_price="NaN"), "items.0.unit_price"),
    (lambda d: d["items"][0].update(quantity=-1), "items.0.quantity"),
    (lambda d: d["items"][0].update(unit="LS"), "items.0.quantity"),
    (lambda d: d["items"][0].update(item_discount="101", item_discount_type="pct"), "items.0.item_discount"),
    (lambda d: d["invoice"].update(prepaid="9999"), "invoice.prepaid"),
    (lambda d: d["seller"].update(iban="MODIFIED"), "seller"),
    (lambda d: d["invoice"].update(bank_account="DE-NONEXISTENT"), "invoice.bank_account"),
    (lambda d: d["invoice"].update(doc_type="381"), "invoice.doc_type"),
    (lambda d: d["invoice"].update(total="99"), "invoice.total"),
])
def test_invalid_values_are_rejected_without_coercion(source, draft, change, expected):
    change(draft)
    _, errors = cli.prepare(draft, source)
    assert any(e["field"] == expected for e in errors), errors


@pytest.mark.parametrize("link", [False, True])
def test_source_is_read_only_even_through_links(capsys, source, tmp_path, draft, link):
    destination = source
    if link:
        destination = tmp_path / "linked"
        destination.symlink_to(source, target_is_directory=True)
    before = snapshot(source)
    path = save(tmp_path / "draft.json", draft)
    for arguments in [("draft", "--customer", "Beispiel GmbH", "--out", destination / "new.json"),
                      ("preview", "--draft", path, "--out", destination / "new.pdf"),
                      ("export", "--draft", path, "--out-dir", destination / "new")]:
        result = call(capsys, source, *arguments)
        assert result["error"]["code"] == "source_is_read_only"
    assert snapshot(source) == before


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
@pytest.mark.parametrize("language", ["de", "en"])
def test_preview_export_roundtrip_and_retry(capsys, source, tmp_path, draft, profile, language):
    from pypdf import PdfReader
    draft["invoice"].update(profile=profile, language=language, prepaid="1.005")
    path = save(tmp_path / "draft.json", draft)
    before = snapshot(source)
    validation = call(capsys, source, "check", "--draft", path)
    assert validation["ok"] and validation["validation"]["valid"], validation
    assert validation["summary"]["due"] == "2854.99"
    preview = tmp_path / "preview.pdf"
    result = call(capsys, source, "preview", "--draft", path, "--out", preview)
    assert result["ok"], result
    pdf = preview.read_bytes()
    assert extract_xml_from_pdf(pdf) is None
    assert ("DRAFT" if language == "en" else "ENTWURF") in PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    out = tmp_path / "exports"
    exported = call(capsys, source, "export", "--draft", path, "--out-dir", out)
    assert exported["ok"] and exported["validation"]["valid"] and not exported["reused"], exported
    files_before = snapshot(out)
    again = call(capsys, source, "export", "--draft", path, "--out-dir", out)
    assert again["ok"] and again["reused"]
    assert snapshot(out) == files_before
    final_pdf = next(Path(exported["directory"]).glob("*.pdf")).read_bytes()
    assert ("DRAFT" if language == "en" else "ENTWURF") not in PdfReader(io.BytesIO(final_pdf)).pages[0].extract_text()
    assert (extract_xml_from_pdf(final_pdf) is None) == (profile == "xrechnung")
    assert bool(list(Path(exported["directory"]).glob("*.xml"))) == (profile == "xrechnung")
    draft["items"][0]["unit_price"] = "900"
    save(path, draft)
    conflict = call(capsys, source, "export", "--draft", path, "--out-dir", out)
    assert conflict["error"]["code"] == "number_conflict"
    assert snapshot(out) == files_before and snapshot(source) == before


def test_validation_failure_never_creates_export(capsys, source, tmp_path, draft, monkeypatch):
    path = save(tmp_path / "draft.json", draft)
    monkeypatch.setattr(cli, "validate_schematron", lambda _: {"available": False})
    out = tmp_path / "exports"
    assert not call(capsys, source, "export", "--draft", path, "--out-dir", out)["ok"]
    assert not out.exists()


def test_existing_source_number_cannot_be_exported(capsys, source, tmp_path, draft):
    draft["invoice"]["number"] = "DEMO-ALT"
    path = save(tmp_path / "draft.json", draft)
    result = call(capsys, source, "export", "--draft", path, "--out-dir", tmp_path / "exports")
    assert result["error"]["code"] == "number_in_archive"


def test_export_failure_leaves_no_partial_bundle(capsys, source, tmp_path, draft, monkeypatch):
    path = save(tmp_path / "draft.json", draft)
    def fail(*args, **kwargs):
        raise OSError("Simulated render failure")
    monkeypatch.setattr(cli, "build_pdf", fail)
    out = tmp_path / "exports"
    assert not call(capsys, source, "export", "--draft", path, "--out-dir", out)["ok"]
    assert not list(out.glob("Rechnung*")) and not list(out.glob(".invoice-*"))


def test_cli_does_not_import_app_or_create_source_directories(tmp_path):
    result = subprocess.run([sys.executable, "-c", "import assistant_cli, sys; assert 'app' not in sys.modules; assistant_cli.main(['schema'])"],
                            cwd=ROOT, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["source_access"] == "read-only"


def test_install_launch_remove_leaves_app_and_data_intact(source, tmp_path):
    skills = tmp_path / "skills"
    before = snapshot(source)
    installer = [sys.executable, str(ROOT / "scripts/install_assistant_skill.py"), "--skills-dir", str(skills)]
    subprocess.run([*installer, "--data-dir", str(source)], check=True, capture_output=True)
    launcher = skills / "erechnung/scripts/erechnung.py"
    result = subprocess.run([sys.executable, str(launcher), "customers", "--query", "Beispiel"],
                            check=True, capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert len(json.loads(result.stdout)["customers"]) == 1
    subprocess.run([*installer, "--uninstall"], check=True, capture_output=True)
    assert not (skills / "erechnung").exists()
    assert snapshot(source) == before and (ROOT / "app.py").is_file()
