from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from persistent_memory.embeddings import VectorIndex
from persistent_memory.retriever import cosine_similarity

EMBED_DIM = 1024


def _unit_vec(seed: float) -> list[float]:
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    v[0] = seed
    n = np.linalg.norm(v)
    return (v / n).tolist()


def _axis_vec(axis: int) -> list[float]:
    v = np.zeros(EMBED_DIM, dtype=np.float32)
    v[axis] = 1.0
    return v.tolist()


def test_new_index_is_empty(tmp_path):
    assert len(VectorIndex(tmp_path / ".pm-index")) == 0


def test_load_missing_files_starts_empty(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.load()
    assert len(index) == 0


def test_upsert_adds_new_vector(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    changed = index.upsert("D-0001", _unit_vec(1.0), content_hash="h1")
    assert changed is True
    assert len(index) == 1


def test_upsert_same_hash_skips(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("D-0001", _unit_vec(1.0), content_hash="h1")
    changed = index.upsert("D-0001", _unit_vec(9.0), content_hash="h1")
    assert changed is False
    assert len(index) == 1


def test_upsert_changed_hash_replaces_vector(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("D-0001", _unit_vec(1.0), content_hash="h1")
    changed = index.upsert("D-0001", _unit_vec(2.0), content_hash="h2")
    assert changed is True
    assert len(index) == 1


def test_persist_then_load_roundtrip(tmp_path):
    index_dir = tmp_path / ".pm-index"
    index = VectorIndex(index_dir)
    index.upsert("D-0001", _unit_vec(1.0), content_hash="h1")
    index.save()

    assert (index_dir / "vectors.npy").exists()
    assert (index_dir / "ids.json").exists()

    reloaded = VectorIndex(index_dir)
    reloaded.load()
    assert len(reloaded) == 1
    assert "D-0001" in reloaded.ids()


def test_remove_existing_id(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("D-0001", _unit_vec(1.0), content_hash="h1")
    index.upsert("D-0002", _unit_vec(2.0), content_hash="h2")
    removed = index.remove("D-0001")
    assert removed is True
    assert len(index) == 1
    assert index.ids() == ["D-0002"]


def test_remove_missing_id_returns_false(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("D-0001", _unit_vec(1.0), content_hash="h1")
    assert index.remove("D-9999") is False
    assert len(index) == 1


def test_query_empty_index_returns_empty(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    assert index.query(_axis_vec(0), top_k=5) == []


def test_query_orders_by_cosine_descending(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("A", _axis_vec(0), content_hash="ha")
    index.upsert("B", _axis_vec(1), content_hash="hb")
    index.upsert("C", _axis_vec(2), content_hash="hc")

    results = index.query(_axis_vec(1), top_k=2)
    assert len(results) == 2
    assert results[0][0] == "B"
    assert pytest.approx(results[0][1], abs=1e-5) == 1.0


def test_query_top_k_caps_results(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    for i in range(5):
        index.upsert(f"D-{i}", _axis_vec(i), content_hash=f"h{i}")
    assert len(index.query(_axis_vec(0), top_k=3)) == 3


def test_query_records_limits_results_to_requested_ids(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("OUTSIDE", _axis_vec(0), content_hash="h0")
    index.upsert("A", _axis_vec(1), content_hash="h1")
    index.upsert("B", _axis_vec(2), content_hash="h2")

    results = index.query_records(_axis_vec(1), ["B", "MISSING", "A"])

    assert [record_id for record_id, _ in results] == ["A", "B"]
    assert results[0][1] == pytest.approx(1.0, abs=1e-12)


def test_query_records_matches_individual_cosine_scores(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    vectors = {"A": [3.0, 4.0], "B": [2.0, 0.0], "C": [0.0, 1.0]}
    for record_id, vector in vectors.items():
        index.upsert(record_id, vector, content_hash=record_id)
    query = [2.0, 1.0]

    results = index.query_records(query, ["C", "A", "B"])
    expected = sorted(
        ((record_id, cosine_similarity(query, vector)) for record_id, vector in vectors.items()),
        key=lambda pair: (-pair[1], pair[0]),
    )

    assert [record_id for record_id, _ in results] == [record_id for record_id, _ in expected]
    assert [score for _, score in results] == pytest.approx([score for _, score in expected], abs=1e-12)


def test_query_records_treats_nonfinite_vectors_as_zero_score(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    index.upsert("A", [float("nan"), 1.0], content_hash="a")
    index.upsert("B", [1.0, 0.0], content_hash="b")

    assert index.query_records([float("nan"), 1.0], ["B", "A"]) == [
        ("A", 0.0),
        ("B", 0.0),
    ]
    assert index.query_records([1.0, 0.0], ["A", "B"]) == [("B", 1.0), ("A", 0.0)]


def test_query_records_is_safe_during_concurrent_mutation(tmp_path):
    index = VectorIndex(tmp_path / ".pm-index")
    for i in range(128):
        index.upsert(f"R-{i}", [float(i + 1), 1.0], content_hash=str(i))
    record_ids = [f"R-{i}" for i in range(128)]

    def read_many() -> None:
        for _ in range(100):
            results = index.query_records([1.0, 1.0], record_ids)
            assert all(np.isfinite(score) for _, score in results)

    def mutate_many() -> None:
        for i in range(100):
            record_id = f"R-{i % 128}"
            index.remove(record_id)
            index.upsert(record_id, [float(i + 1), 1.0], content_hash=f"new-{i}")

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(read_many) for _ in range(4)]
        futures.append(executor.submit(mutate_many))
        for future in futures:
            future.result()


def test_load_resets_on_mismatched_files(tmp_path):
    index_dir = tmp_path / ".pm-index"
    index = VectorIndex(index_dir)
    index.upsert("D-0001", _axis_vec(0), content_hash="h1")
    index.upsert("D-0002", _axis_vec(1), content_hash="h2")
    index.save()
    np.save(index_dir / "vectors.npy", np.asarray([_axis_vec(0)], dtype=np.float32))
    fresh = VectorIndex(index_dir)
    fresh.load()
    assert len(fresh) == 0


def test_save_leaves_no_temp_files(tmp_path):
    index_dir = tmp_path / ".pm-index"
    index = VectorIndex(index_dir)
    index.upsert("D-0001", _axis_vec(0), content_hash="h1")
    index.save()
    leftovers = [p.name for p in index_dir.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
