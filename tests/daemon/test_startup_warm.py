from pathlib import Path

import pytest
from starlette.testclient import TestClient

from persistent_memory.daemon import services
from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig


def test_warm_retrieval_primes_all_runtime_caches(tmp_path, monkeypatch):
    events = []
    fingerprint = ("fingerprint",)
    views = [object()]

    class Adapter:
        def embed_query(self, query):
            events.append(("embed", query))

    monkeypatch.setattr(
        services,
        "_records_fingerprint_singleflight",
        lambda records_dir: events.append(("fingerprint", records_dir)) or fingerprint,
    )
    monkeypatch.setattr(
        services,
        "_collect_embed_views",
        lambda records_dir, value: events.append(("views", records_dir, value)) or views,
    )
    monkeypatch.setattr(
        services,
        "_build_retrieval_adapter",
        lambda records_dir, value, fp: events.append(("adapter", records_dir, value, fp))
        or Adapter(),
    )
    monkeypatch.setattr(
        services,
        "_build_demote_ids",
        lambda records_dir, value: events.append(("demote", records_dir, value)) or set(),
    )
    monkeypatch.setattr(
        "persistent_memory.retriever._cached_bm25",
        lambda value: events.append(("bm25", value)),
    )

    services.warm_retrieval(records_dir=tmp_path)

    assert events == [
        ("fingerprint", tmp_path),
        ("views", tmp_path, fingerprint),
        ("adapter", tmp_path, views, fingerprint),
        ("demote", tmp_path, fingerprint),
        ("bm25", views),
        ("embed", ""),
    ]


def test_app_lifespan_warms_before_health_is_available(tmp_path, monkeypatch):
    calls: list[Path] = []
    monkeypatch.setattr(
        services,
        "warm_retrieval",
        lambda *, records_dir: calls.append(records_dir),
    )
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)

    with TestClient(create_app(records_dir=tmp_path, config=cfg)) as client:
        assert calls == [tmp_path]
        assert client.get("/api/health").status_code == 200


def test_app_lifespan_fails_closed_when_warmup_fails(tmp_path, monkeypatch):
    def fail_warmup(*, records_dir):
        raise RuntimeError(f"warmup failed for {records_dir}")

    monkeypatch.setattr(services, "warm_retrieval", fail_warmup)
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    client = TestClient(create_app(records_dir=tmp_path, config=cfg))

    with pytest.raises(RuntimeError, match="warmup failed"):
        with client:
            raise AssertionError("lifespan should not become ready")
