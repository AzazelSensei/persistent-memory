import json

import pytest
from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.i18n import reset_lang_cache


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _parse_i18n(body: str) -> dict:
    start = body.index("window.PM_I18N = ") + len("window.PM_I18N = ")
    end = body.index(";", start)
    return json.loads(body[start:end])


def test_app_page_embeds_pm_i18n(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "window.PM_I18N" in resp.text


def test_app_page_embeds_window_t_helper(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert "window.t = function" in resp.text


def test_app_page_english_i18n_by_default(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    i18n_data = _parse_i18n(resp.text)
    assert i18n_data.get("ui.btn.approve") == "Approve"
    assert i18n_data.get("ui.nav.overview") == "Overview"
    assert i18n_data.get("ui.cand.heading") == "Supersession candidates"


def test_app_page_turkish_i18n_with_pm_lang(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_LANG", "tr")
    reset_lang_cache()
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "window.PM_I18N" in resp.text
    i18n_data = _parse_i18n(resp.text)
    assert i18n_data.get("ui.btn.approve") == "Onayla"
    assert i18n_data.get("ui.btn.reject") == "Reddet"
    assert i18n_data.get("ui.cand.heading") == "Supersession adayları"


def test_app_page_english_default_does_not_include_turkish_values(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    i18n_data = _parse_i18n(resp.text)
    assert "Onayla" not in i18n_data.values()
    assert "Reddet" not in i18n_data.values()
