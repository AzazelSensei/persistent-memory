"""Tests for the i18n layer wired into the dashboard HTML endpoint.

Covers:
- window.PM_I18N is present in GET /
- default (English) rendered page assertions
- PM_LANG=tr renders Turkish strings into the JSON block
"""

import json

import persistent_memory.i18n as i18n
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from starlette.testclient import TestClient


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def test_app_page_contains_pm_i18n_block(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "window.PM_I18N" in resp.text


def test_app_page_contains_window_t_helper(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert "window.t" in resp.text


def test_default_english_pm_i18n_contains_english_strings(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text
    # Extract the PM_I18N JSON from the page
    marker = "window.PM_I18N = "
    start = text.index(marker) + len(marker)
    end = text.index(";", start)
    data = json.loads(text[start:end])
    assert data["ui.btn.approve"] == "Approve"
    assert data["ui.btn.reject"] == "Reject"
    assert data["ui.cand.heading"] == "Supersession candidates"
    assert data["ui.nav.overview"] == "Overview"


def test_turkish_pm_i18n_contains_turkish_strings(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_LANG", "tr")
    i18n.reset_lang_cache()
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    text = resp.text
    assert "Onayla" in text
    assert "Reddet" in text
    assert "Supersession adayları" in text
    # Parse the JSON block to be precise
    marker = "window.PM_I18N = "
    start = text.index(marker) + len(marker)
    end = text.index(";", start)
    data = json.loads(text[start:end])
    assert data["ui.btn.approve"] == "Onayla"
    assert data["ui.btn.reject"] == "Reddet"
    assert data["ui.cand.heading"] == "Supersession adayları"
    assert data["ui.nav.overview"] == "Genel Bakış"


def test_turkish_views_list_strings(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_LANG", "tr")
    i18n.reset_lang_cache()
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    marker = "window.PM_I18N = "
    start = resp.text.index(marker) + len(marker)
    end = resp.text.index(";", start)
    data = json.loads(resp.text[start:end])
    assert data["ui.list.queue_mode"] == "Kuyruk modu"
    assert data["ui.list.bulk.accept"] == "Seçilenleri onayla"
    assert data["ui.list.bulk.reject"] == "Seçilenleri reddet"
    assert data["ui.list.bulk.clear"] == "Temizle"
    assert data["ui.list.all_projects"] == "tüm projeler"
    assert data["ui.queue.complete"] == "Kuyruk tamamlandı"
    assert data["ui.queue.back_to_list"] == "Listeye dön"
