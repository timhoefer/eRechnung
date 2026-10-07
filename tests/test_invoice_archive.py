"""Shared archive behavior, using only isolated fictional data."""
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

import app as appmod
import assistant_cli as cli
import invoice_archive as archive
from invoice_core import suggest_invoice_number
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


@pytest.mark.parametrize("failure", ["sidecar", "pdf", "number"])
def test_interrupted_commit_is_completed_on_retry(setup, monkeypatch, failure):
    source, data = setup
    output = source / "output"
    real_link, remember = archive.os.link, archive._remember_number
    def fail_link(src, dst):
        if Path(dst).suffix == (".pdf" if failure == "pdf" else ".json"):
            raise OSError("Disk unavailable")
        real_link(src, dst)
    def fail_number(*args):
        raise OSError("Disk unavailable")
    with monkeypatch.context() as patch:
        if failure == "number":
            patch.setattr(archive, "_remember_number", fail_number)
        else:
            patch.setattr(archive.os, "link", fail_link)
        with pytest.raises(OSError):
            publish(source, data)
    assert (output / ".archive-pending/manifest.json").exists()
    if failure != "number":
        assert not list(output.glob("*.pdf"))
    # A PDF, if visible, already has every associated invoice file.
    for pdf in output.glob("*.pdf"):
        assert pdf.with_suffix(".json").exists()
    assert archive._remember_number is remember
    retry = publish(source, data)
    assert retry["reused"]
    assert len(list(output.glob("*.pdf"))) == 1
    assert not (output / ".archive-pending").exists()
    assert cli.seller_from(source)["last_invoice_number"] == data["invoice"]["number"]


def test_recovery_never_overwrites_external_conflict(setup, monkeypatch):
    source, data = setup
    with monkeypatch.context() as patch:
        patch.setattr(archive.os, "link", lambda *_: (_ for _ in ()).throw(OSError("Unavailable")))
        with pytest.raises(OSError):
            publish(source, data)
    target = source / "output" / ("Rechnung_" + data["invoice"]["number"] + ".json")
    target.write_text("keep this file")
    with pytest.raises(archive.ArchiveError, match="recovery conflict"):
        publish(source, data)
    assert target.read_text() == "keep this file"


@pytest.mark.parametrize("file_kind", [".pdf", ".json", ".xml"])
def test_orphan_and_sanitized_filename_collisions_are_rejected(setup, file_kind):
    source, data = setup
    data["invoice"].update(number="A/B", profile="xrechnung")
    existing = source / "output" / ("Rechnung_A_B" + file_kind)
    existing.write_bytes(b"keep")
    with pytest.raises(archive.ArchiveError):
        publish(source, data)
    assert existing.read_bytes() == b"keep"


@pytest.mark.parametrize("changed", ["pdf", "sidecar"])
def test_retry_detects_changed_invoice_files(setup, changed):
    source, data = setup
    result = publish(source, data)
    path = source / "output" / result["filename"]
    if changed == "pdf":
        path.write_bytes(b"changed")
    else:
        path = path.with_suffix(".json")
        sidecar = json.loads(path.read_text())
        sidecar["items"][0]["unit_price"] = "9999"
        path.write_bytes(archive.canonical(sidecar))
    original = path.read_bytes()
    with pytest.raises(archive.ArchiveError, match="changed"):
        publish(source, data)
    assert path.read_bytes() == original


def test_delayed_invoice_or_retry_does_not_move_number_back(setup):
    source, data = setup
    year = date.today().year
    data["invoice"]["number"] = f"{year}-050"
    publish(source, data)
    data["invoice"]["number"] = f"{year}-042"
    publish(source, data)
    assert cli.seller_from(source)["last_invoice_number"] == f"{year}-050"
    assert suggest_invoice_number(cli.seller_from(source), archive.archived_numbers(source / "output")) == f"{year}-051"


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


def test_parallel_local_processes_cannot_publish_conflicting_invoices(setup, tmp_path):
    source, data = setup
    draft = tmp_path / "data.json"
    draft.write_bytes(archive.canonical(data))
    script = '''
import json, sys
from pathlib import Path
from invoice_archive import archive_invoice, ArchiveError
source, path, buyer = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
data = json.loads(path.read_text())
data['buyer']['name'] = buyer
try:
    archive_invoice(data, b'%PDF-test', b'<xml/>', source/'output', source/'seller.json')
    print('saved')
except ArchiveError as exc:
    print(exc.code)
'''
    def worker(i):
        return subprocess.run([sys.executable, "-c", script, str(source), str(draft), str(i)],
                              cwd=Path(cli.__file__).parent, text=True, capture_output=True, check=True).stdout.strip()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(worker, range(4)))
    assert results.count("saved") == 1
    assert results.count("number_conflict") == 3
    assert len(list((source / "output").glob("*.pdf"))) == 1


def test_app_seller_autosave_waits_for_shared_archive_lock(setup):
    source, data = setup
    started, finished = threading.Event(), threading.Event()
    def autosave():
        started.set()
        with appmod.app.test_client() as client:
            assert client.post("/settings/autosave", data={"name": "Changed name"}).status_code == 204
        finished.set()
    with archive.data_lock(source):
        thread = threading.Thread(target=autosave)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(0.1)
        publish(source, data)
    thread.join(timeout=5)
    assert finished.is_set()
    seller = cli.seller_from(source)
    assert seller["name"] == "Changed name"
    assert seller["last_invoice_number"] == data["invoice"]["number"]


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
