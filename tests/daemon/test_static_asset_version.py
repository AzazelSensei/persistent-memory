"""Dashboard scripts must carry a version query so browsers refetch after edits."""

import os
import re

from starlette.testclient import TestClient

from persistent_memory.daemon.app import STATIC_DIR, create_app, static_asset_version

SCRIPT_SRC_RE = re.compile(r'src="/static/pm/([^"]+\.jsx)\?v=(\d+)"')


def test_static_asset_version_is_a_positive_stamp():
    version = static_asset_version()
    assert version.isdigit()
    assert int(version) > 0


def test_static_asset_version_changes_when_a_script_is_touched():
    before = static_asset_version()
    target = next(STATIC_DIR.glob("pm/*.jsx"))
    stat = target.stat()
    bumped = int(before) + 1_000_000_000
    try:
        os.utime(target, ns=(stat.st_atime_ns, bumped))
        assert static_asset_version() == str(bumped)
        assert static_asset_version() != before
    finally:
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def test_every_dashboard_script_tag_is_versioned(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)

    html = client.get("/").text
    versioned = SCRIPT_SRC_RE.findall(html)

    assert versioned, "no versioned script tags rendered"
    assert 'src="/static/pm/app.jsx"' not in html
    versions = {version for _name, version in versioned}
    assert len(versions) == 1


def test_versioned_script_url_is_served(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)

    html = client.get("/").text
    name, version = SCRIPT_SRC_RE.findall(html)[0]

    response = client.get(f"/static/pm/{name}?v={version}")

    assert response.status_code == 200
