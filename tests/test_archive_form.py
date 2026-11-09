"""A rejected archive write must leave a usable invoice draft in its issuer context."""
import json

import pytest
from helpers import export_invoice
from lxml import html
from test_issuer_profiles import FORM, SELLER, YEAR, add_issuer
from test_issuer_profiles import client as client
from test_issuer_profiles import fast_generation as fast_generation
from werkzeug.datastructures import MultiDict

import app as m


@pytest.mark.parametrize("failure", ["number_conflict", "archive_io"])
@pytest.mark.parametrize("issuer_kind", ["default", "additional", "retired"])
def test_archive_error_preserves_complete_draft(client, fast_generation, monkeypatch, failure, issuer_kind):
    issuer, folder = add_issuer(client) if issuer_kind == "additional" else ("default", m.DATA_DIR)
    (folder / "seller.json").write_text(json.dumps(SELLER))
    if issuer_kind == "retired":
        add_issuer(client)
    original = dict(FORM, issuer=issuer)
    assert export_invoice(client, data=original).status_code == 200
    fields = MultiDict(original)
    fields.update(dict(note="Keep my draft", discount="10", discount_reason="Loyalty", prepaid="20", prepaid_ref="Deposit"))
    fields.setlist("description", ["Revised design", "Additional work"])
    fields.setlist("quantity", ["2", "3"])
    fields.setlist("unit", ["C62", "HUR"])
    fields.setlist("unit_price", ["100", "50"])
    if issuer_kind == "retired":
        assert client.post("/issuers/delete", data={"issuer": issuer, "confirm": "delete"}).json["ok"]
        fields.update(dict(doc_type="384", correction_source=f"Rechnung_{FORM['number']}.pdf"))
    before = {p.relative_to(m.DATA_DIR): p.read_bytes() for p in m.DATA_DIR.rglob("*") if p.is_file()}
    if failure == "archive_io":
        def unavailable(*args, **kwargs):
            raise OSError("Archive disk unavailable")
        monkeypatch.setattr(m, "archive_invoice", unavailable)
    response = export_invoice(client, data=fields, follow_redirects=True)
    assert response.status_code == 409
    assert not response.history
    assert {p.relative_to(m.DATA_DIR): p.read_bytes() for p in m.DATA_DIR.rglob("*") if p.is_file()} == before
    page = html.fromstring(response.data)
    assert not page.xpath('//*[@id="export-conflict"]')  # No misleading stale-master-data warning.
    script = page.xpath('//script[contains(text(), "window.SUBMITTED_FORM")]/text()')[0]
    draft = json.loads(script.split("window.SUBMITTED_FORM = ", 1)[1].split(";", 1)[0])
    for key, values in fields.lists():
        assert draft[key] == values
    form = page.get_element_by_id("invoice-form")
    assert form.xpath('./input[@name="issuer"]/@value') == [issuer]
    if issuer_kind == "retired":
        assert form.xpath('./input[@name="correction_source"]/@value') == [fields["correction_source"]]
    # The same form can be corrected and submitted without re-entering its lines.
    if failure == "number_conflict":
        fields["number"] = f"{YEAR}-012"
        assert export_invoice(client, data=fields).status_code == 200
        saved = json.loads((folder / "output" / f"Rechnung_{YEAR}-012.json").read_text())
        assert [item["description"] for item in saved["items"]] == fields.getlist("description")
