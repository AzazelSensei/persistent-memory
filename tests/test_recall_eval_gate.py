import json
import math
import os
from datetime import date
from pathlib import Path

import pytest

from eval.recall_eval import _metrics, _percentile

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_EVAL_ENABLED = os.environ.get("PM_EVAL_LIVE") == "1"
SCOPED_MRR_THRESHOLD = 0.88
GLOBAL_MRR_THRESHOLD = 0.82


def test_ndcg_perfect_rank_is_one():
    assert _metrics([1])["ndcg@10"] == 1.0


def test_ndcg_rank_two_is_discounted():
    expected = 1.0 / math.log2(3)
    assert abs(_metrics([2])["ndcg@10"] - expected) < 1e-9


def test_ndcg_miss_is_zero():
    assert _metrics([0])["ndcg@10"] == 0.0


def test_percentile_basic():
    assert _percentile([10, 20, 30, 40], 50) == 25.0
    assert _percentile([10], 95) == 10.0


def test_percentile_empty_is_zero():
    assert _percentile([], 50) == 0.0


@pytest.mark.skipif(not LIVE_EVAL_ENABLED, reason="requires live Ollama: set PM_EVAL_LIVE=1")
def test_recall_quality_above_threshold():
    from eval.recall_eval import evaluate
    from persistent_memory.daemon import services

    records_dir = REPO_ROOT / "docs"
    queries = json.loads((REPO_ROOT / "eval" / "recall_queries.json").read_text(encoding="utf-8"))
    views = services._collect_embed_views(records_dir)
    adapter = services._build_retrieval_adapter(records_dir, views)
    demote = services._build_demote_ids(records_dir)
    now = date.today().isoformat()
    scoped = evaluate(queries, views, adapter, now, scoped=True, demote_ids=demote)
    glob = evaluate(queries, views, adapter, now, scoped=False, demote_ids=demote)
    assert scoped["mrr"] >= SCOPED_MRR_THRESHOLD, f"scoped MRR regression: {scoped['mrr']}"
    assert glob["mrr"] >= GLOBAL_MRR_THRESHOLD, f"global MRR regression: {glob['mrr']}"
