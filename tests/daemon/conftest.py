import pytest
from starlette.testclient import TestClient

LOCALHOST_BASE_URL = "http://localhost"


@pytest.fixture(autouse=True)
def _localhost_testclient(monkeypatch):
    original_init = TestClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("base_url", LOCALHOST_BASE_URL)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", patched_init)
