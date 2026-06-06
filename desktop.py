"""Desktop-Wrapper für die eRechnung-App.

Startet den Flask-Server lokal in einem Hintergrund-Thread und zeigt die
Oberfläche in einem nativen Fenster (pywebview) – kein Browser, kein Terminal.
Wird als Einstiegspunkt für den gebündelten macOS-App-Build (PyInstaller)
verwendet. Der klassische Start über run.sh / start.command bleibt unberührt.
"""
import socket
import sys
import threading

from werkzeug.serving import make_server

from app import app


def _selftest() -> int:
    """Native Libs ohne GUI prüfen: erzeugt eine Test-Rechnung (WeasyPrint/Pango)
    und validiert sie (lxml + saxonche). Nutzt eigene Testdaten und fasst die
    echten Nutzerdaten nicht an. Exit 0 = ok. Für den Build-Check."""
    import app as appmod
    from zugferd import (
        extract_xml_from_pdf,
        validate_schematron,
        validate_xml_bytes,
    )

    # Verkäufer für den Test fest vorgeben (statt aus seller.json zu lesen),
    # damit der Test datenunabhängig und reproduzierbar ist.
    appmod.load_seller = lambda: {
        "name": "Selftest GmbH", "country": "DE", "city": "Berlin",
        "postcode": "10829", "address_line": "Teststr. 1",
        "vat_id": "DE123456789", "email": "test@example.com", "phone": "+490",
        "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
        "bank_name": "Testbank", "account_name": "Selftest GmbH",
        "payment_term_days": "14", "show_tax_number": True,
    }

    client = app.test_client()
    resp = client.post(
        "/preview",
        data={
            "number": "SELFTEST-1", "issue_date": "2026-01-01",
            "description": "Tëst-Leistung", "quantity": "1", "unit": "C62",
            "unit_price": "100", "tax_treatment": "de_19", "language": "de",
            "buyer_name": "Muster GmbH", "buyer_country": "DE",
        },
    )
    pdf = resp.get_data()
    pdf_ok = resp.status_code == 200 and pdf[:4] == b"%PDF"          # WeasyPrint/Pango
    emb = extract_xml_from_pdf(pdf) if pdf_ok else None              # pypdf
    xsd_ok = validate_xml_bytes(emb)[0] if emb else False            # lxml + XSD
    sch = validate_schematron(emb) if emb else {"available": False}  # saxonche
    print(f"[selftest] PDF={pdf_ok} ({len(pdf)} bytes)  XSD={xsd_ok}  "
          f"Schematron available={sch.get('available')} ok={sch.get('ok')}")
    # saxonche ist optional fürs Erzeugen, aber wir wollen wissen, ob es im Bundle
    # läuft -> als Teil des Build-Checks verlangen wir 'available'.
    return 0 if (pdf_ok and emb and xsd_ok and sch.get("available")) else 1


def _free_port() -> int:
    """Einen freien lokalen Port auswählen (vermeidet Konflikte mit 5000/5055)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    import webview

    port = _free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    webview.create_window(
        "eRechnung",
        f"http://127.0.0.1:{port}/",
        width=1280,
        height=900,
        min_size=(960, 640),
    )
    webview.start()  # blockiert bis das Fenster geschlossen wird
    server.shutdown()


if __name__ == "__main__":
    main()
