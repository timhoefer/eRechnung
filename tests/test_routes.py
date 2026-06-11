"""Routen-/Integrationstests. Nutzen einen isolierten Temp-Datenordner – die
echten seller/customers/output-Dateien werden NICHT angefasst.

Der volle /generate-Roundtrip ruft build_pdf (WeasyPrint/Pango) auf und wird
übersprungen, wenn WeasyPrint nicht verfügbar ist (z. B. in der CI)."""
import json

import pytest

import app as appmod

try:  # WeasyPrint lädt native Libs beim Import -> ohne Pango nicht verfügbar
    import weasyprint  # noqa: F401
    HAS_WEASYPRINT = True
except Exception:
    HAS_WEASYPRINT = False


@pytest.fixture
def client(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(appmod, "OUTPUT_DIR", out)
    monkeypatch.setattr(appmod, "SELLER_FILE", tmp_path / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", tmp_path / "customers.json")
    (tmp_path / "seller.json").write_text(json.dumps({
        "name": "Selftest GmbH", "country": "DE", "city": "Berlin",
        "postcode": "10829", "address_line": "Teststr. 1",
        "vat_id": "DE123456789", "email": "a@b.de", "phone": "+490",
        "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
        "bank_name": "Testbank", "account_name": "Selftest GmbH",
        "show_tax_number": False,
    }), encoding="utf-8")
    return appmod.app.test_client()


def test_index_ok(client):
    assert client.get("/").status_code == 200


def test_preview_html_renders(client):
    r = client.post("/preview-html", data={
        "description": "Test", "quantity": "1", "unit_price": "100",
        "tax_treatment": "de_19",
    })
    assert r.status_code == 200
    assert b"<" in r.data  # HTML-Fragment


def test_settings_panel_renders(client):
    r = client.get("/settings/panel")
    assert r.status_code == 200
    assert b"check-file-form" in r.data and b"datadir-form" in r.data


def test_export_csv(client):
    out = appmod.OUTPUT_DIR
    (out / "Rechnung_2026-001.pdf").write_bytes(b"%PDF-1.4")
    (out / "Rechnung_2026-001.json").write_text(json.dumps({
        "invoice": {"number": "2026-001", "issue_date": "2026-03-15",
                    "currency": "EUR", "tax_treatment": "de_19"},
        "buyer": {"name": "Muster GmbH", "country": "DE"},
        "items": [{"description": "Leistung", "quantity": "2",
                   "unit": "C62", "unit_price": "100"}],
    }), encoding="utf-8")
    r = client.get("/export/csv?from=2026-01-01&to=2026-12-31")
    assert r.status_code == 200
    assert "text/csv" in r.headers["Content-Type"]
    body = r.get_data(as_text=True)
    assert "2026-001" in body and "Muster GmbH" in body
    # 2 × 100 = 200 netto, 19 % = 38 USt, 238 brutto (locale-tolerant)
    assert ("200,00" in body or "200.00" in body)
    assert ("238,00" in body or "238.00" in body)
    # Datumsfilter: außerhalb -> Rechnung nicht enthalten
    r2 = client.get("/export/csv?from=2025-01-01&to=2025-12-31")
    assert "2026-001" not in r2.get_data(as_text=True)
    # Datumsbereich steht im Dateinamen (DE-Default: rechnungen_<from>_bis_<to>.csv)
    assert 'filename="rechnungen_2026-01-01_bis_2026-12-31.csv"' in r.headers["Content-Disposition"]
    r3 = client.get("/export/csv?from=2026-01-01")
    assert 'filename="rechnungen_ab_2026-01-01.csv"' in r3.headers["Content-Disposition"]
    # Kein/ungültiger Bereich -> schlichter Name (nichts Ungeprüftes in den Dateinamen)
    r4 = client.get("/export/csv?from=..%2Fevil")
    assert 'filename="rechnungen.csv"' in r4.headers["Content-Disposition"]


_FORM = {
    "number": "2026-001", "issue_date": "2026-01-01", "due_date": "2026-01-15",
    "description": "Leistung", "quantity": "1", "unit": "C62", "unit_price": "100",
    "tax_treatment": "de_19", "language": "de",
    "buyer_name": "Muster GmbH", "buyer_country": "DE",
}


def test_storno_requires_reference(client):
    # 381 (Storno) ohne Bezug -> abgelehnt, kein PDF (Redirect vor dem Rendern).
    r = client.post("/generate", data=dict(_FORM, doc_type="381"))
    assert r.status_code in (302, 303)
    assert not list(appmod.OUTPUT_DIR.glob("*.pdf"))


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_generate_creates_pdf_and_sidecar(client):
    r = client.post("/generate", data=dict(_FORM))
    assert r.status_code == 200
    pdfs = list(appmod.OUTPUT_DIR.glob("*.pdf"))
    assert len(pdfs) == 1
    assert (appmod.OUTPUT_DIR / "Rechnung_2026-001.json").exists()  # Sidecar


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_xrechnung_writes_standalone_xml(client):
    # XRechnung-Modus: einreichbare .xml + PDF-Sichtexemplar; .xml herunterladbar.
    r = client.post("/generate", data=dict(
        _FORM, profile="xrechnung",
        buyer_city="Köln", buyer_postcode="50667", buyer_address_line="Domkloster 4",
        buyer_email="k@muster.de", buyer_reference="04011000-12345-67",
    ))
    assert r.status_code == 200
    out = appmod.OUTPUT_DIR
    assert (out / "Rechnung_2026-001.pdf").exists()  # Sichtexemplar
    xml = out / "Rechnung_2026-001.xml"
    assert xml.exists()  # einreichbare XRechnung
    assert b"xrechnung_3.0" in xml.read_bytes()  # korrekte CIUS-Spec-ID
    d = client.get("/download/Rechnung_2026-001.xml")
    assert d.status_code == 200 and "xml" in d.headers["Content-Type"]
    assert "PDF + XML" in r.get_data(as_text=True)  # kombinierter Download angeboten
    # ZIP-Bundle enthält PDF + XML
    import io
    import zipfile
    z = client.get("/download-zip/Rechnung_2026-001.pdf")
    assert z.status_code == 200 and "zip" in z.headers["Content-Type"]
    names = sorted(zipfile.ZipFile(io.BytesIO(z.data)).namelist())
    assert names == ["Rechnung_2026-001.pdf", "Rechnung_2026-001.xml"]


@pytest.mark.skipif(not HAS_WEASYPRINT, reason="braucht WeasyPrint/Pango (Rendering)")
def test_generate_duplicate_number_keeps_both(client):
    client.post("/generate", data=dict(_FORM))
    r2 = client.post("/generate", data=dict(_FORM))  # gleiche Nummer erneut
    assert r2.status_code == 200
    pdfs = sorted(p.name for p in appmod.OUTPUT_DIR.glob("*.pdf"))
    assert len(pdfs) == 2  # nichts überschrieben
    assert "Rechnung_2026-001.pdf" in pdfs
    assert any("(2)" in n for n in pdfs)
    body = r2.get_data(as_text=True)
    assert "bereits" in body or "already" in body  # Duplikat-Hinweis


# --- Desktop-Modus: „Im Finder zeigen" statt Download (WKWebView lädt nicht) ----

def _make_archive_entry(out, number="2026-001"):
    """PDF + Sidecar-JSON in OUTPUT_DIR anlegen -> Archiv-Eintrag mit Entwurf."""
    stem = f"Rechnung_{number}"
    (out / f"{stem}.pdf").write_bytes(b"%PDF-1.4")
    (out / f"{stem}.json").write_text(json.dumps({
        "invoice": {"number": number, "issue_date": "2026-03-15",
                    "currency": "EUR", "tax_treatment": "de_19"},
        "buyer": {"name": "Muster GmbH", "country": "DE"},
        "items": [{"description": "Leistung", "quantity": "1",
                   "unit": "C62", "unit_price": "100"}],
    }), encoding="utf-8")
    return f"{stem}.pdf"


def test_reveal_missing_file_404(client):
    # Pfad-Prüfung greift vor dem Plattform-Check -> 404 auch auf der CI (Linux).
    assert client.post("/reveal/gibtsnicht.pdf").status_code == 404


def test_reveal_existing_file_opens_finder(client, monkeypatch):
    pdf = _make_archive_entry(appmod.OUTPUT_DIR)
    calls = []
    monkeypatch.setattr("subprocess.run", lambda *a, **k: calls.append(a[0]))
    monkeypatch.setattr(appmod.sys, "platform", "darwin")
    r = client.post("/reveal/" + pdf)
    assert r.status_code == 200 and r.get_json()["ok"]
    assert calls and calls[0][:2] == ["open", "-R"]


def test_settings_panel_desktop_uses_reveal(client, monkeypatch):
    _make_archive_entry(appmod.OUTPUT_DIR)
    monkeypatch.setitem(appmod.app.config, "DESKTOP", True)
    body = client.get("/settings/panel").get_data(as_text=True)
    assert "reveal-btn" in body and "csv-export-btn" in body
    assert "/download/" not in body  # keine echten Download-Links im Desktop


def test_export_csv_desktop_writes_file(client, monkeypatch):
    pdf = _make_archive_entry(appmod.OUTPUT_DIR)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: None)  # kein Finder
    monkeypatch.setattr(appmod.sys, "platform", "darwin")
    monkeypatch.setitem(appmod.app.config, "DESKTOP", True)
    r = client.get("/export/csv?file=" + pdf)
    assert r.is_json and r.get_json()["ok"]
    assert (appmod.OUTPUT_DIR / "Rechnung_2026-001.csv").exists()


def test_export_csv_browser_downloads(client):
    pdf = _make_archive_entry(appmod.OUTPUT_DIR)  # DESKTOP nicht gesetzt
    r = client.get("/export/csv?file=" + pdf)
    assert "text/csv" in r.headers["Content-Type"]


def test_settings_save_fetch_returns_json(client):
    # Stammdaten speichern per fetch -> JSON + Toast statt Redirect/Banner.
    r = client.post("/settings", data={"name": "Neu GmbH"},
                    headers={"X-Requested-With": "fetch"})
    d = r.get_json()
    assert d["ok"] and d["message"]
    assert json.loads(appmod.SELLER_FILE.read_text(encoding="utf-8"))["name"] == "Neu GmbH"
    # Ohne Header: klassischer Redirect (No-JS-Fallback)
    r2 = client.post("/settings", data={"name": "Neu GmbH"})
    assert r2.status_code in (302, 303)


def test_csv_export_escapes_formula_injection(client):
    out = appmod.OUTPUT_DIR
    (out / "Rechnung_2026-001.pdf").write_bytes(b"%PDF-1.4")
    (out / "Rechnung_2026-001.json").write_text(json.dumps({
        "invoice": {"number": "2026-001", "issue_date": "2026-03-01",
                    "currency": "EUR", "tax_treatment": "de_19"},
        "buyer": {"name": "=SUM(A1:A9)", "country": "DE"},
        "items": [{"description": "L", "quantity": "1", "unit": "C62", "unit_price": "100"}],
    }), encoding="utf-8")
    body = client.get("/export/csv").get_data(as_text=True)
    assert "'=SUM(A1:A9)" in body          # mit ' entschärft
    assert ";=SUM(A1:A9)" not in body      # nicht roh als Formel


def test_customers_delete_fetch_json(client):
    appmod.save_customers([{"name": "Muster GmbH", "country": "DE"}])
    hdr = {"X-Requested-With": "fetch"}
    r = client.post("/customers/delete", headers=hdr, data={"buyer_name": "Muster GmbH"})
    d = r.get_json()
    assert d["ok"] and "Muster GmbH" in d["message"] and d["customers"] == []
    # Unbekannter Name -> ok:False
    assert client.post("/customers/delete", headers=hdr,
                       data={"buyer_name": "Gibtsnicht"}).get_json()["ok"] is False


def test_num_str_matches_calc_js_num():
    # Server _num_str() muss dieselben Werte liefern wie num() in static/calc.js
    # (Spiegel: tests/calc.test.js::"num: Parität-Fälle"). Sonst weichen Vorschau
    # (Client) und PDF/XML (Server) bei deutscher Zahlenschreibweise ab.
    cases = [
        ("1234,56", 1234.56), ("1.234,56", 1234.56), ("2.500,00", 2500.0),
        ("1234.56", 1234.56), ("1.234.567", 1234567.0), ("1.234", 1.234),
        ("1234", 1234.0), ("", 0.0), ("abc", 0.0), ("12,", 12.0), ("1e9", 1e9),
    ]
    for raw, expected in cases:
        assert float(appmod._dec(appmod._num_str(raw))) == expected, raw


def test_logo_stored_only_if_valid_image_data_uri(client):
    from werkzeug.datastructures import MultiDict
    good = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="
    s = appmod.apply_seller_form({"name": "S"}, MultiDict({"logo": good}))
    assert s["logo"] == good
    # Kein Bild-data-URI -> verworfen (kein beliebiger Inhalt)
    s2 = appmod.apply_seller_form({"name": "S"}, MultiDict({"logo": "javascript:alert(1)"}))
    assert s2["logo"] == ""
    # Übergroßes Logo -> verworfen
    big = "data:image/png;base64," + ("A" * 1_600_000)
    s3 = appmod.apply_seller_form({"name": "S"}, MultiDict({"logo": big}))
    assert s3["logo"] == ""


def test_logo_appears_in_preview(client):
    out = appmod.SELLER_FILE
    base = json.loads(out.read_text(encoding="utf-8"))
    base["logo"] = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    out.write_text(json.dumps(base), encoding="utf-8")
    body = client.post("/preview-html", data={
        "description": "L", "quantity": "1", "unit_price": "100", "tax_treatment": "de_19",
    }).get_data(as_text=True)
    assert "brand-mark" in body and base["logo"] in body


def test_customers_save_fetch_returns_json(client):
    # Per fetch (JS): JSON statt Redirect -> kein Reload, Toast im Client.
    hdr = {"X-Requested-With": "fetch"}
    r = client.post("/customers/save", headers=hdr,
                    data={"buyer_name": "Muster GmbH", "buyer_country": "DE"})
    d = r.get_json()
    assert d["ok"] and "Muster GmbH" in d["message"]
    assert any(c["name"] == "Muster GmbH" for c in d["customers"])
    # Fehlender Name -> ok: False mit Meldung
    assert client.post("/customers/save", headers=hdr, data={}).get_json()["ok"] is False
    # Ohne fetch-Header bleibt der klassische Redirect (No-JS-Fallback)
    r2 = client.post("/customers/save", data={"buyer_name": "X", "buyer_country": "DE"})
    assert r2.status_code in (302, 303)


def test_customer_payment_term_roundtrip(client):
    # Kundenspezifisches Zahlungsziel: Formular -> buyer -> Kundenspeicher.
    from werkzeug.datastructures import MultiDict
    md = MultiDict({"buyer_name": "Muster GmbH", "buyer_country": "DE",
                    "buyer_payment_term_days": "30"})
    buyer = appmod.buyer_from_form(md)
    assert buyer["payment_term_days"] == "30"
    appmod.upsert_customer(buyer)
    saved = appmod.load_customers()
    assert saved[0]["payment_term_days"] == "30"


# --- Erststart: nach dem Datenordner fragen ------------------------------------

def test_first_run_shows_folder_modal(client, monkeypatch, tmp_path):
    # Frisch: weder config.json noch seller.json -> Willkommens-Dialog mit Ordnerwahl.
    monkeypatch.setattr(appmod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(appmod, "SELLER_FILE", tmp_path / "kein_seller.json")
    body = client.get("/").get_data(as_text=True)
    assert "onboard-modal" in body
    assert 'name="origin" value="onboarding"' in body
    assert "Documents" in body  # vorgeschlagener Pfad


def test_no_folder_modal_when_seller_exists(client):
    # Der client-Fixture legt seller.json an -> kein Erststart, kein Dialog.
    body = client.get("/").get_data(as_text=True)
    assert "onboard-modal" not in body


# --- Mehrere Bankkonten (#26) ---------------------------------------------------

def test_seller_accounts_combines_primary_and_extras():
    flat = {"name": "S", "iban": "DE11", "bic": "B1", "bank_name": "Bank A",
            "account_name": "Inh"}
    assert len(appmod.seller_accounts(flat)) == 1
    combo = dict(flat, accounts=[{"bank_name": "Wise", "iban": "DE22"}, {"iban": ""}])
    accts = appmod.seller_accounts(combo)
    assert [a["iban"] for a in accts] == ["DE11", "DE22"]  # leeres Konto übersprungen
    assert appmod.seller_accounts({"name": "X"}) == []  # ohne IBAN keine Konten
    # Auswahl per IBAN (stabiler Schlüssel), tolerant gegen Leerzeichen/Kleinschreibung
    assert appmod.select_account(combo, "DE22")["bank_name"] == "Wise"
    assert appmod.select_account(combo, "de 22")["bank_name"] == "Wise"
    # Unbekannte IBAN / kein Schlüssel -> erstes Konto
    assert appmod.select_account(combo, "DE99")["iban"] == "DE11"
    assert appmod.select_account(combo, None)["iban"] == "DE11"
    # Alt-Sidecars: numerischer Index wird weiter unterstützt (inkl. Clamp)
    assert appmod.select_account(combo, "1")["iban"] == "DE22"
    assert appmod.select_account(combo, "99")["iban"] == "DE11"
    # Kernfix: IBAN-Auswahl übersteht das Wegfallen des Hauptkontos (Index täte das nicht)
    shifted = {"name": "S", "iban": "", "accounts": [
        {"iban": "DEAA"}, {"iban": "DE22", "bank_name": "Wise"}]}
    assert appmod.select_account(shifted, "DE22")["bank_name"] == "Wise"


def test_apply_seller_form_parses_extra_accounts():
    from werkzeug.datastructures import MultiDict
    md = MultiDict()
    md.add("has_accounts_section", "1")
    for k, v in [("acct_iban", "DE22"), ("acct_bic", "B2"),
                 ("acct_bank_name", "Wise"), ("acct_account_name", "Inh")]:
        md.add(k, v)
    for k in ("acct_iban", "acct_bic", "acct_bank_name", "acct_account_name"):
        md.add(k, "")  # leerer Block -> wird verworfen
    seller = appmod.apply_seller_form({"name": "S", "iban": "DE11"}, md)
    assert seller["accounts"] == [{"account_name": "Inh", "bank_name": "Wise",
                                   "iban": "DE22", "bic": "B2"}]


def test_invoice_form_has_account_selector_element(client):
    # Auswähler ist immer im DOM (JS befüllt ihn aus den Konten + blendet ihn ab 2
    # Konten ein); initial ausgeblendet. Die weiteren Konten stehen in den Stammdaten.
    body = client.get("/").get_data(as_text=True)
    assert 'id="bank-select-wrap"' in body and 'name="bank_account"' in body
    assert 'id="add-account"' in body and 'id="acct-template"' in body


def test_preview_uses_selected_account(client):
    out = appmod.SELLER_FILE
    base = json.loads(out.read_text(encoding="utf-8"))
    base["accounts"] = [{"iban": "DE99USD0", "bic": "B2",
                         "bank_name": "Wise", "account_name": "Inh"}]
    out.write_text(json.dumps(base), encoding="utf-8")
    form = {"description": "L", "quantity": "1", "unit_price": "100",
            "tax_treatment": "de_19"}
    # Konto per IBAN gewählt -> erscheint im Vorschau-HTML ...
    body1 = client.post("/preview-html", data=dict(form, bank_account="DE99USD0")).get_data(as_text=True)
    assert "DE99USD0" in body1
    # ... Hauptkonto (per IBAN) zeigt die flache IBAN, nicht das Zweitkonto.
    body0 = client.post("/preview-html", data=dict(form, bank_account=base["iban"])).get_data(as_text=True)
    assert base["iban"] in body0 and "DE99USD0" not in body0
    # Alt-Sidecar-Kompatibilität: numerischer Index funktioniert weiter.
    bodyl = client.post("/preview-html", data=dict(form, bank_account="1")).get_data(as_text=True)
    assert "DE99USD0" in bodyl


def test_data_dir_set_onboarding_redirects_to_form(client, monkeypatch):
    # set_data_dir stubben -> keine echten Dateioperationen; nur Redirect-Ziel prüfen.
    monkeypatch.setattr(appmod, "set_data_dir", lambda raw: (True, "data_dir_saved"))
    r = client.post("/data-dir", data={"data_dir": "/x", "origin": "onboarding"})
    assert r.status_code in (302, 303) and "validate" not in r.headers["Location"]
    r2 = client.post("/data-dir", data={"data_dir": "/x"})  # ohne origin -> Einstellungen
    assert r2.status_code in (302, 303) and "validate" in r2.headers["Location"]


def test_parse_items_lump_sum_forces_quantity_one():
    """Pauschal (LS) ist ein Festbetrag: Menge wird serverseitig auf 1 normalisiert
    (Client sperrt das Feld; hier der No-JS-/Alt-Draft-Pfad)."""
    from werkzeug.datastructures import MultiDict
    form = MultiDict([
        ("description", "Projektpauschale"), ("quantity", "3"),
        ("unit", "LS"), ("unit_price", "1000"),
        ("description", "Beratung"), ("quantity", "2"),
        ("unit", "HUR"), ("unit_price", "100"),
    ])
    items = appmod.parse_items(form)
    assert items[0]["unit"] == "LS" and items[0]["quantity"] == "1"
    assert items[1]["quantity"] == "2"  # andere Einheiten bleiben unangetastet


def test_archive_check_targets_xml_for_xrechnung(client):
    """Bei XRechnung-Einträgen (standalone .xml + Sicht-PDF) muss "prüfen" die
    einreichbare XML prüfen, nicht das PDF (das PDF hat kein eingebettetes XML)."""
    out = appmod.OUTPUT_DIR
    (out / "Rechnung_2026-001.pdf").write_bytes(b"%PDF-1.4")
    (out / "Rechnung_2026-001.xml").write_bytes(b"<x/>")
    (out / "Rechnung_2026-001.json").write_text(json.dumps({
        "invoice": {"number": "2026-001", "issue_date": "2026-03-15",
                    "profile": "xrechnung"},
        "buyer": {"name": "K"}, "items": [],
    }), encoding="utf-8")
    # Hybrid-Eintrag ohne .xml daneben: prüft weiterhin das PDF.
    (out / "Rechnung_2026-002.pdf").write_bytes(b"%PDF-1.4")
    html = client.get("/settings/panel").get_data(as_text=True)
    assert 'value="Rechnung_2026-001.xml"' in html
    assert 'value="Rechnung_2026-002.pdf"' in html
    # Die Prüfung der XML läuft direkt über den XML-Pfad (kein PDF-Extrakt).
    r = client.post("/settings/panel", data={"filename": "Rechnung_2026-001.xml"})
    assert r.status_code == 200
    assert "Rechnung_2026-001.xml" in r.get_data(as_text=True)
