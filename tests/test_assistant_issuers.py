"""Agent-independent issuer selection and writes, with fictional isolated data."""
import json
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pytest
from helpers import confirmed_post, export_invoice
from lxml import etree, html

import app as appmod
import assistant_cli as cli
import invoice_archive as archive
from scripts.create_assistant_demo import create_demo
from zugferd import extract_xml_from_pdf

SECOND = "b" * 32
YEAR = date.today().year
ROOT = Path(__file__).resolve().parents[1]


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = create_demo(tmp_path / "data", multiple_issuers=True)
    for name, path in {"DATA_DIR": root, "SELLER_FILE": root / "seller.json",
                       "CUSTOMERS_FILE": root / "customers.json", "OUTPUT_DIR": root / "output",
                       "CONFIG_FILE": tmp_path / "config.json", "BASE": tmp_path / "app"}.items():
        monkeypatch.setattr(appmod, name, path)
    return root


def draft(source, issuer=SECOND, number=None):
    data = cli.create_draft(source, "Beispiel GmbH", "Rechnung_DEMO-ALT.json", issuer)
    data["invoice"].update(number=number or f"{YEAR}-010", issue_date=f"{YEAR}-11-08", due_date=f"{YEAR}-11-22")
    return data


def call(capsys, source, *arguments):
    code = cli.main(["--data-dir", str(source), *map(str, arguments)])
    result = json.loads(capsys.readouterr().out)
    assert code == (0 if result["ok"] else 2)
    return result


def test_discovery_is_read_only_and_matches_app_default(source, capsys):
    before = snapshot(source)
    result = call(capsys, source, "issuers")
    assert [(p["id"], p["default"]) for p in result["issuers"]] == [("default", False), (SECOND, True)]
    assert result["default_issuer_id"] == SECOND
    assert all("iban" not in p and "vat_id" not in p for p in result["issuers"])
    with appmod.app.test_client() as client:
        page = html.fromstring(client.get("/").data)
        assert page.xpath('//*[@id="issuer-select"]/option[@selected]/@value') == [SECOND]
    assert snapshot(source) == before
    assert call(capsys, source, "customers")["shared_across_issuers"]


@pytest.mark.parametrize("arguments", [
    ["next-number"], ["templates", "--customer", "Beispiel GmbH"],
    ["draft", "--customer", "Beispiel GmbH", "--out", "unused.json"],
])
def test_multiple_profiles_require_choice_even_with_default_or_identical_names(source, capsys, arguments):
    write(source / "issuers" / SECOND / "seller.json", cli.seller_from(source))
    result = call(capsys, source, *arguments)
    assert result["error"]["code"] == "issuer_required"


def test_templates_bank_accounts_and_numbering_are_per_issuer(source, capsys):
    first, second = draft(source, "default"), draft(source)
    assert first["items"][0]["unit_price"] == "800"
    assert second["items"][0]["unit_price"] == "1200"
    assert first["seller"]["iban"] != second["seller"]["iban"]
    assert cli.prepare(first, source)[0]["bank"]["iban"] == first["seller"]["iban"]
    assert cli.prepare(second, source)[0]["bank"]["iban"] == second["seller"]["iban"]
    assert call(capsys, source, "--issuer", SECOND, "next-number")["number"] == f"{YEAR}-010"
    assert call(capsys, source, "--issuer", "default", "next-number")["requires_clarification"]
    template = source / "issuers" / SECOND / "output/Rechnung_DEMO-ALT.json"
    old = cli.read_json(template)
    old["issuer_id"] = "default"
    write(template, old)
    assert call(capsys, source, "--issuer", SECOND, "templates", "--customer", "Beispiel GmbH")["templates"] == []
    with pytest.raises(cli.InputError, match="different issuer"):
        draft(source)


@pytest.mark.parametrize("profile", ["en16931", "xrechnung"])
def test_two_issuers_can_archive_same_number_with_valid_xml_and_app_visibility(source, capsys, tmp_path, profile):
    customers = (source / "customers.json").read_bytes()
    for issuer in ("default", SECOND):
        data = draft(source, issuer)
        data["invoice"]["profile"] = profile
        path = write(tmp_path / "draft.json", data)
        result = call(capsys, source, "archive", "--draft", path)
        assert result["ok"] and result["validation"]["valid"], result
        assert result["summary"]["issuer_id"] == issuer
        assert result["summary"]["issuer_name"] == data["seller"]["name"]
        folder = source if issuer == "default" else source / "issuers" / issuer
        assert all(Path(p).parent == folder / "output" for p in result["files"])
        pdf = (folder / "output" / result["filename"]).read_bytes()
        xml = (folder / "output" / result["filename"]).with_suffix(".xml").read_bytes() if profile == "xrechnung" else extract_xml_from_pdf(pdf)
        assert etree.fromstring(xml).xpath("string(//*[local-name()='SellerTradeParty']/*[local-name()='Name'])") == data["seller"]["name"]
        sidecar = cli.read_json((folder / "output" / result["filename"]).with_suffix(".json"))
        assert sidecar["issuer_id"] == issuer
        saved = snapshot(folder / "output")
        assert call(capsys, source, "archive", "--draft", path)["reused"]
        assert snapshot(folder / "output") == saved
        assert cli.number_proposal(source, issuer)["number"] == f"{YEAR}-011"
        with appmod.app.test_client() as client:
            assert client.get("/archive/preview/" + result["filename"], query_string={"issuer": issuer}).data == pdf
            assert data["invoice"]["number"] in client.get("/export/csv", query_string={"issuer": issuer}).text
    assert (source / "customers.json").read_bytes() == customers


def test_separate_exports_same_number_do_not_collide_or_write_app_data(source, capsys, tmp_path):
    before = snapshot(source)
    folders = []
    for issuer in ("default", SECOND):
        path = write(tmp_path / "draft.json", draft(source, issuer))
        result = call(capsys, source, "export", "--draft", path, "--out-dir", tmp_path / "exports")
        assert result["ok"], result
        folder = Path(result["directory"])
        assert folder.parent.name == issuer
        folders.append(folder)
    assert folders[0] != folders[1] and snapshot(source) == before


def test_default_changes_cannot_retarget_draft_and_explicit_mismatch_fails(source, capsys, tmp_path):
    data = draft(source)
    write(source / "issuer_preferences.json", {"default_issuer": "default"})
    path = write(tmp_path / "draft.json", data)
    result = call(capsys, source, "check", "--draft", path)
    assert result["ok"] and result["summary"]["issuer_id"] == SECOND
    result = call(capsys, source, "--issuer", "default", "archive", "--draft", path)
    assert any(e["field"] == "issuer_id" for e in result["errors"])
    assert not list(source.rglob("*.pdf"))


@pytest.mark.parametrize("change", ["address", "bank", "reactivation", "revision"])
def test_master_data_changes_require_new_draft_but_counter_changes_do_not(source, change):
    data = draft(source)
    path = source / "issuers" / SECOND / "seller.json"
    seller = cli.read_json(path)
    seller["last_invoice_number"] = f"{YEAR}-011"
    write(path, seller)
    assert cli.prepare(data, source)[1] == []
    if change == "address":
        seller["address_line"] = "Neue Adresse 42"
    elif change == "bank":
        seller["iban"] = "DE02120300000000202051"
    elif change == "reactivation":
        seller["_revision"] = "new-after-reactivation"
    else:
        data.pop("seller_revision")
    write(path, seller)
    assert any(e["field"] == "seller" for e in cli.prepare(data, source)[1])


@pytest.mark.parametrize("command,extra", [("check", []), ("archive", []), ("preview", ["--out", "unused.pdf"]),
                                           ("export", ["--out-dir", "unused-exports"])])
def test_inactive_issuers_reject_all_invoice_operations(source, capsys, tmp_path, command, extra):
    path = write(tmp_path / "draft.json", draft(source))
    seller_path = source / "issuers" / SECOND / "seller.json"
    write(seller_path, dict(cli.read_json(seller_path), _deleted=True))
    before = snapshot(source)
    result = call(capsys, source, command, "--draft", path, *extra)
    assert result["error"]["code"] == "issuer_inactive"
    assert snapshot(source) == before
    result = call(capsys, source, "issuers")
    assert result["issuers"][1]["deleted"] and result["default_issuer_id"] == "default"


def test_retirement_during_render_is_checked_before_archive_write(source, capsys, tmp_path, monkeypatch):
    path = write(tmp_path / "draft.json", draft(source))
    render = cli.build_pdf
    def retire(markup, xml):
        with appmod.app.test_client() as client:
            assert confirmed_post(client, "/issuers/delete", data={"issuer": SECOND, "confirm": "delete"}).json["ok"]
        return render(markup, xml)
    monkeypatch.setattr(cli, "build_pdf", retire)
    result = call(capsys, source, "archive", "--draft", path)
    assert result["error"]["code"] == "issuer_inactive"
    assert not list(source.rglob("*.pdf"))
    assert cli.seller_from(source / "issuers" / SECOND)["last_invoice_number"] == f"{YEAR}-009"


def test_draft_cannot_move_to_an_identical_other_data_root_or_use_old_schema(source, tmp_path):
    data = draft(source)
    other = tmp_path / "other"
    shutil.copytree(source, other)
    assert any(e["field"] == "data_scope" for e in cli.prepare(data, other)[1])
    data["schema_version"] = 1
    assert cli.prepare(data, source)[1][0]["field"] == "schema_version"


@pytest.mark.parametrize("issuer,code", [("../outside", "invalid_issuer"), ("default/output", "invalid_issuer"),
                                         ("a" * 32, "unknown_issuer")])
def test_invalid_or_missing_issuers_never_fall_back(source, capsys, issuer, code):
    before = snapshot(source)
    assert call(capsys, source, "--issuer", issuer, "next-number")["error"]["code"] == code
    assert snapshot(source) == before


@pytest.mark.parametrize("link", ["output", "seller.json"])
def test_linked_profile_data_is_not_read(source, capsys, tmp_path, link):
    path = source / "issuers" / SECOND / link
    moved = tmp_path / link
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=moved.is_dir())
    result = call(capsys, source, "--issuer", SECOND, "next-number")
    assert result["error"]["code"] == "linked_issuer"


def test_linked_export_profile_cannot_write_inside_app_data(source, capsys, tmp_path):
    path = write(tmp_path / "draft.json", draft(source))
    root = tmp_path / "exports"
    root.mkdir()
    (root / SECOND).symlink_to(source / "issuers" / SECOND / "output", target_is_directory=True)
    before = snapshot(source)
    result = call(capsys, source, "export", "--draft", path, "--out-dir", root)
    assert result["error"]["code"] == "linked_export" and snapshot(source) == before


def test_app_and_cli_share_number_conflicts_and_keep_other_issuers_untouched(source, capsys, tmp_path):
    data = draft(source)
    form = {**data["invoice"], **data["items"][0], "issuer": SECOND,
            **{"buyer_" + k: v for k, v in data["buyer"].items()}}
    with appmod.app.test_client() as client:
        assert export_invoice(client, data=form).status_code == 200
    before = snapshot(source)
    data["items"][0]["unit_price"] = "999"
    path = write(tmp_path / "draft.json", data)
    assert call(capsys, source, "archive", "--draft", path)["error"]["code"] == "number_conflict"
    assert snapshot(source) == before


def test_pending_other_issuer_is_recovered_before_data_folder_move(source, tmp_path, monkeypatch):
    data = draft(source)
    folder = source / "issuers" / SECOND
    with monkeypatch.context() as patch:
        patch.setattr(archive.os, "link", lambda *_: (_ for _ in ()).throw(OSError("Interrupted")))
        with pytest.raises(OSError):
            archive.archive_invoice(data, b"%PDF-test", b"<xml/>", folder / "output", folder / "seller.json", lock_directory=source)
    target = tmp_path / "moved"
    assert appmod.set_data_dir(str(target))[0]
    moved = target / "issuers" / SECOND
    assert (moved / "output" / f"Rechnung_{YEAR}-010.pdf").read_bytes() == b"%PDF-test"
    assert cli.seller_from(moved)["last_invoice_number"] == f"{YEAR}-010"
    assert not (folder / "output/.archive-pending").exists()
    assert cli.number_proposal(target, SECOND)["number"] == f"{YEAR}-011"


def test_additional_issuer_writer_waits_for_same_root_lock_in_another_process(source, tmp_path):
    path = write(tmp_path / "draft.json", draft(source))
    script = """
import json, sys
from pathlib import Path
from invoice_archive import archive_invoice
source, draft = map(Path, sys.argv[1:])
data = json.loads(draft.read_text())
folder = source / 'issuers' / data['issuer_id']
print('ready', flush=True)
archive_invoice(data, b'%PDF-test', b'<xml/>', folder/'output', folder/'seller.json', lock_directory=source)
print('saved', flush=True)
"""
    process = None
    try:
        with archive.data_lock(source):
            process = subprocess.Popen([sys.executable, "-c", script, str(source), str(path)], cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            assert process.stdout.readline().strip() == "ready"
            time.sleep(0.1)
            assert process.poll() is None and not list(source.rglob("*.pdf"))
        out, err = process.communicate(timeout=15)
        assert process.returncode == 0 and out.strip() == "saved", err
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()


@pytest.mark.parametrize("arguments", [[], ["unknown"], ["archive"], ["--issuer"]])
def test_direct_agent_invocation_returns_structured_errors_without_skill(source, arguments):
    result = subprocess.run([sys.executable, str(ROOT / "assistant_cli.py"), *arguments], cwd=source,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "invalid_arguments"


def test_direct_agent_invocation_without_app_or_codex_and_explicit_root_required(source):
    result = subprocess.run([sys.executable, str(ROOT / "assistant_cli.py"), "--data-dir", str(source), "issuers"],
                            cwd=source, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)["default_issuer_id"] == SECOND
    result = subprocess.run([sys.executable, str(ROOT / "assistant_cli.py"), "issuers"],
                            cwd=source, text=True, capture_output=True, check=False)
    assert result.returncode == 2 and json.loads(result.stdout)["error"]["code"] == "missing_data_dir"
