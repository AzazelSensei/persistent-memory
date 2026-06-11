import numpy as np
import pytest

from persistent_memory.embeddings import VectorIndex

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
