"""Archive transactions use isolated fictional records, without agent adapters."""
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from helpers import confirmed_post

import app as appmod
import invoice_archive as archive
from invoice_core import suggest_invoice_number
from issuer_store import seller_revision


def read_seller(source):
    return json.loads((source / "seller.json").read_text())


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / "data"
    source.mkdir()
    (source / "output").mkdir()
    seller = {"name": "Example Studio", "country": "DE", "city": "Berlin",
              "address_line": "Teststr. 1", "postcode": "10829", "vat_id": "DE123456789"}
    (source / "seller.json").write_text(json.dumps(seller))
    monkeypatch.setattr(appmod, "DATA_DIR", source)
    monkeypatch.setattr(appmod, "OUTPUT_DIR", source / "output")
    monkeypatch.setattr(appmod, "SELLER_FILE", source / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", source / "customers.json")
    data = {"issuer_id": "default", "seller_revision": seller_revision(seller), "seller": seller,
            "buyer": {"name": "Example Customer", "country": "DE"},
            "invoice": {"number": f"{date.today().year}-042", "issue_date": "2026-10-07",
                        "profile": "en16931", "tax_treatment": "de_19"},
            "items": [{"description": "Design", "quantity": "1", "unit_price": "100", "unit": "HUR"}]}
    return source, data


def publish(source, data):
    return archive.archive_invoice(data, b"%PDF-test", b"<xml/>", source / "output", source / "seller.json")


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
    assert read_seller(source)["last_invoice_number"] == data["invoice"]["number"]


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


@pytest.mark.parametrize("file_kind", [".pdf", ".json", ".xml", ".csv"])
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
    assert read_seller(source)["last_invoice_number"] == f"{year}-050"
    assert suggest_invoice_number(read_seller(source), archive.archived_numbers(source / "output")) == f"{year}-051"


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
                              cwd=Path(archive.__file__).parent, text=True, capture_output=True, check=True).stdout.strip()
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
            assert confirmed_post(client, "/settings/autosave", data={"name": "Changed name",
                               "seller_revision": data["seller_revision"]}).status_code == 204
        finished.set()
    with archive.data_lock(source):
        thread = threading.Thread(target=autosave)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(0.1)
        publish(source, data)
    thread.join(timeout=5)
    assert finished.is_set()
    seller = read_seller(source)
    assert seller["name"] == "Changed name"
    assert seller["last_invoice_number"] == data["invoice"]["number"]
