"""Feature announcements must survive restarts without affecting invoice data."""
import json

import pytest
from lxml import html

import app as appmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "BASE", tmp_path)
    monkeypatch.setattr(appmod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(appmod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(appmod, "SELLER_FILE", tmp_path / "seller.json")
    monkeypatch.setattr(appmod, "CUSTOMERS_FILE", tmp_path / "customers.json")
    monkeypatch.setattr(appmod, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(appmod, "drafthorse_version_info", lambda: {})
    appmod.OUTPUT_DIR.mkdir()
    appmod.SELLER_FILE.write_text('{"name": "Example Studio"}')
    return appmod.app.test_client()


def dialog(response):
    assert response.status_code == 200
    return html.fromstring(response.data).xpath('//dialog[@id="whats-new-dialog"]')[0]


def acknowledge(client):
    return client.post("/whats-new/seen", json={"id": appmod.ANNOUNCEMENT["id"]})


@pytest.mark.parametrize("language,title,feature", [
    ("de", "Neu in eRechnung", "Klarere Rechnungen"),
    ("en", "What's new in eRechnung", "Clearer invoices"),
])
def test_unseen_announcement_is_localized_but_not_acknowledged_on_load(client, language, title, feature):
    client.set_cookie("lang", language)
    modal = dialog(client.get("/"))
    assert modal.get("data-auto-open") == "true"
    assert title in modal.text_content() and feature in modal.text_content()
    assert len(modal.xpath('.//ul/li')) == 3
    assert not appmod.CONFIG_FILE.exists()
    assert dialog(client.get("/")).get("data-auto-open") == "true"


def test_acknowledgement_survives_new_client_port_and_preserves_config(client):
    appmod.CONFIG_FILE.write_text(json.dumps({"data_dir": "/example/data", "other": "keep"}))
    seller = appmod.SELLER_FILE.read_bytes()
    for _ in range(2):
        assert acknowledge(client).get_json() == {"ok": True}
    config = json.loads(appmod.CONFIG_FILE.read_text())
    assert config == {"data_dir": "/example/data", "other": "keep",
                      "seen_announcements": [appmod.ANNOUNCEMENT["id"]]}
    assert appmod.SELLER_FILE.read_bytes() == seller
    new_client = appmod.app.test_client()
    assert dialog(new_client.get("/", base_url="http://127.0.0.1:56789")).get("data-auto-open") == "false"
    panel = html.fromstring(new_client.get("/settings/panel").data)
    assert len(panel.xpath('//button[@data-open-whats-new]')) == 1
    assert dialog(new_client.get("/validate")).get("data-auto-open") == "false"


def test_only_new_feature_ids_trigger_another_announcement(client, monkeypatch):
    old_id = appmod.ANNOUNCEMENT["id"]
    assert acknowledge(client).status_code == 200
    monkeypatch.setattr(appmod, "APP_VERSION", "1.1.5")
    assert dialog(client.get("/")).get("data-auto-open") == "false"
    monkeypatch.setattr(appmod, "ANNOUNCEMENT", dict(appmod.ANNOUNCEMENT, id="new-feature", version="1.2.0"))
    assert dialog(client.get("/")).get("data-auto-open") == "true"
    assert acknowledge(client).status_code == 200
    assert json.loads(appmod.CONFIG_FILE.read_text())["seen_announcements"] == [old_id, "new-feature"]


def test_onboarding_has_priority_without_marking_news_seen(client):
    appmod.SELLER_FILE.unlink()
    response = client.get("/")
    assert b'id="onboard-modal"' in response.data
    assert dialog(response).get("data-auto-open") == "false"
    assert not appmod.CONFIG_FILE.exists()


def test_reading_news_before_setup_does_not_skip_folder_selection(client):
    appmod.SELLER_FILE.unlink()
    assert acknowledge(client).status_code == 200
    response = client.get("/")
    assert b'id="onboard-modal"' in response.data
    assert dialog(response).get("data-auto-open") == "false"


@pytest.mark.parametrize("announcement", [None, {"id": "empty", "items": []}])
def test_announcement_can_be_disabled(client, monkeypatch, announcement):
    monkeypatch.setattr(appmod, "ANNOUNCEMENT", announcement)
    assert b'id="whats-new-dialog"' not in client.get("/").data
    assert b"data-open-whats-new" not in client.get("/settings/panel").data
    assert client.post("/whats-new/seen", json={"id": "empty"}).status_code == 404
    assert not appmod.CONFIG_FILE.exists()


@pytest.mark.parametrize("data", [{"id": "future-feature"}, {}, [], None])
def test_unknown_or_invalid_acknowledgements_cannot_change_config(client, data):
    assert client.post("/whats-new/seen", json=data).status_code == 400
    assert not appmod.CONFIG_FILE.exists()


def test_cross_origin_cannot_dismiss_news(client):
    response = client.post("/whats-new/seen", json={"id": appmod.ANNOUNCEMENT["id"]},
                           headers={"Origin": "https://example.com"})
    assert response.status_code == 403
    assert not appmod.CONFIG_FILE.exists()


def test_failed_save_keeps_announcement_unread(client, monkeypatch):
    def fail(*args):
        raise OSError("read-only folder")

    monkeypatch.setattr(appmod, "_write_json", fail)
    assert acknowledge(client).status_code == 503
    assert dialog(client.get("/")).get("data-auto-open") == "true"


def test_changing_data_folder_keeps_seen_announcements(client, tmp_path):
    assert acknowledge(client).status_code == 200
    target = tmp_path / "invoices"
    assert client.post("/data-dir", data={"data_dir": str(target)}).status_code == 302
    config = json.loads(appmod.CONFIG_FILE.read_text())
    assert config["data_dir"] == str(target)
    assert config["seen_announcements"] == [appmod.ANNOUNCEMENT["id"]]
    assert dialog(client.get("/")).get("data-auto-open") == "false"
