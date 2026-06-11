import json

from starlette.testclient import TestClient

from persistent_memory.daemon.app import create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.daemon.token import load_or_create_token

OLD_LABEL = "Eski Cache Karari (D-0001)"
NEW_LABEL = "Yeni Cache Karari (D-0002)"
PLAIN_LABEL = "Etiketsiz Dugum"
HIGH_SCORE = 0.9
LOW_SCORE = 0.7
DISMISSED_FILE = ".pm-index/dismissed-candidates.json"


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _headers(tmp_path):
    return {"X-PM-Token": load_or_create_token(tmp_path)}


def write_graph(records_dir):
    out = records_dir / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    graph = {
        "directed": False,
        "multigraph": False,
        "graph": {},
        "nodes": [
            {"id": "old_node", "label": OLD_LABEL, "community": 0},
            {"id": "new_node", "label": NEW_LABEL, "community": 1},
            {"id": "plain_node", "label": PLAIN_LABEL, "community": 2},
        ],
        "links": [
            {
                "source": "old_node",
                "target": "new_node",
                "relation": "contradicts",
                "confidence_score": HIGH_SCORE,
                "source_file": "D-0002.md",
            },
            {
                "source": "plain_node",
                "target": "new_node",
                "relation": "references",
                "confidence_score": LOW_SCORE,
            },
            {
                "source": "old_node",
                "target": "plain_node",
                "relation": "references",
                "confidence_score": 0.2,
            },
        ],
    }
    (out / "graph.json").write_text(json.dumps(graph), encoding="utf-8")


def _candidate_by_labels(candidates, label_a, label_b):
    return next(
        c for c in candidates
        if {c["source_label"], c["target_label"]} == {label_a, label_b}
    )


def test_missing_graph_returns_empty_list(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/supersession-candidates")
    assert resp.status_code == 200
    assert resp.json() == {"candidates": []}


def test_candidates_listed_from_graph(tmp_path):
    write_graph(tmp_path)
    client = _client(tmp_path)
    candidates = client.get("/api/supersession-candidates").json()["candidates"]
    assert len(candidates) == 2
    assert candidates[0]["score"] >= candidates[1]["score"]
    high = _candidate_by_labels(candidates, OLD_LABEL, NEW_LABEL)
    assert high["score"] == HIGH_SCORE
    assert high["relation"] == "contradicts"
    assert {high["source_id"], high["target_id"]} == {"D-0001", "D-0002"}
    assert high["source_files"] == ["D-0002.md"]


def test_label_without_record_id_maps_to_null(tmp_path):
    write_graph(tmp_path)
    client = _client(tmp_path)
    candidates = client.get("/api/supersession-candidates").json()["candidates"]
    plain = _candidate_by_labels(candidates, PLAIN_LABEL, NEW_LABEL)
    ids = {plain["source_id"], plain["target_id"]}
    assert None in ids
    assert "D-0002" in ids


def test_dismiss_by_id_drops_candidate(tmp_path):
    write_graph(tmp_path)
    client = _client(tmp_path)
    resp = client.post(
        "/api/supersession-candidates/dismiss",
        json={"source_id": "D-0001", "target_id": "D-0002"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 200
    assert resp.json()["dismissed"] is True
    candidates = client.get("/api/supersession-candidates").json()["candidates"]
    labels = {frozenset((c["source_label"], c["target_label"])) for c in candidates}
    assert frozenset((OLD_LABEL, NEW_LABEL)) not in labels
    assert frozenset((PLAIN_LABEL, NEW_LABEL)) in labels
    assert (tmp_path / DISMISSED_FILE).exists()


def test_dismiss_by_mixed_id_and_label(tmp_path):
    write_graph(tmp_path)
    client = _client(tmp_path)
    client.post(
        "/api/supersession-candidates/dismiss",
        json={"source_id": "D-0002", "target_label": PLAIN_LABEL},
        headers=_headers(tmp_path),
    )
    candidates = client.get("/api/supersession-candidates").json()["candidates"]
    labels = {frozenset((c["source_label"], c["target_label"])) for c in candidates}
    assert frozenset((PLAIN_LABEL, NEW_LABEL)) not in labels
    assert frozenset((OLD_LABEL, NEW_LABEL)) in labels


def test_dismiss_is_idempotent(tmp_path):
    write_graph(tmp_path)
    client = _client(tmp_path)
    payload = {"source_id": "D-0001", "target_id": "D-0002"}
    client.post("/api/supersession-candidates/dismiss", json=payload, headers=_headers(tmp_path))
    client.post("/api/supersession-candidates/dismiss", json=payload, headers=_headers(tmp_path))
    stored = json.loads((tmp_path / DISMISSED_FILE).read_text(encoding="utf-8"))
    assert len(stored) == 1


def test_dismiss_without_token_returns_403(tmp_path):
    write_graph(tmp_path)
    client = _client(tmp_path)
    resp = client.post(
        "/api/supersession-candidates/dismiss",
        json={"source_id": "D-0001", "target_id": "D-0002"},
    )
    assert resp.status_code == 403


def test_dismiss_missing_pair_returns_422(tmp_path):
    client = _client(tmp_path)
    resp = client.post(
        "/api/supersession-candidates/dismiss",
        json={"source_id": "D-0001"},
        headers=_headers(tmp_path),
    )
    assert resp.status_code == 422
