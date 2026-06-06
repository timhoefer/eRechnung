"""Tests für die localhost-Schutzmechanismen (CSRF/DNS-Rebinding) und Helfer.
Die Cross-Origin-/Fremd-Host-Fälle werden VOR dem Handler geblockt – es wird
dabei nichts geschrieben."""
import app


def test_netloc_is_local():
    f = app._netloc_is_local
    assert f("127.0.0.1:5055")
    assert f("localhost:5000")
    assert f("127.0.0.1")
    assert f("[::1]:5000")
    assert not f("evil.example")
    assert not f("evil.example:5000")
    assert not f("")
    assert not f(None)


def test_safe_name_strips_path_chars():
    assert app.safe_name("2026-011") == "2026-011"
    out = app.safe_name("../etc/passwd")
    assert "/" not in out and ".." not in out
    assert "/" not in app.safe_name("a b/c")


def test_csrf_cross_origin_post_blocked():
    # Wird im before_request mit 403 abgewiesen -> Handler läuft nicht, kein Write.
    c = app.app.test_client()
    r = c.post("/settings/autosave", data={"name": "x"},
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_dns_rebinding_foreign_host_blocked():
    c = app.app.test_client()
    r = c.get("/", headers={"Host": "evil.example"})
    assert r.status_code == 403


def test_local_get_ok():
    c = app.app.test_client()
    assert c.get("/").status_code == 200


def test_local_post_with_origin_not_blocked():
    # /preview-html schreibt nichts (nur Rendern) -> sicher als "lokal erlaubt"-Probe.
    c = app.app.test_client()
    r = c.post("/preview-html", data={"number": "X"},
               headers={"Origin": "http://127.0.0.1:5055"})
    assert r.status_code == 200
