"""Recall quality benchmark: query -> expected record, recall@k + MRR.

Measures two modes side by side:
  - scoped: search restricted to the record's project (mirrors real prompt-recall usage)
  - global: no project filter (cross-project stress test)

Usage: python eval/recall_eval.py [queries.json] [records_dir]
queries.json: [{"query": ..., "expect_id": "D-0001", "project": "Desktop"}, ...]
"""
import json
import math
import sys
import time
from datetime import date
from pathlib import Path

from persistent_memory.daemon import services
from persistent_memory.retriever import search

DEFAULT_QUERIES = "eval/recall_queries.json"
DEFAULT_RECORDS_DIR = "docs"
TOP_K = 10
FAIL_RANK_THRESHOLD = 3


NDCG_CAP = 10


def _dcg_single(rank: int, cap: int = NDCG_CAP) -> float:
    if rank == 0 or rank > cap:
        return 0.0
    return 1.0 / math.log2(rank + 1)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (pct / 100.0) * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _metrics(ranks: list[int]) -> dict:
    n = len(ranks) or 1
    return {
        "recall@1": sum(1 for r in ranks if r == 1) / n,
        "recall@3": sum(1 for r in ranks if 1 <= r <= 3) / n,
        "recall@5": sum(1 for r in ranks if 1 <= r <= 5) / n,
        "mrr": sum((1.0 / r if r else 0.0) for r in ranks) / n,
        "ndcg@10": sum(_dcg_single(r) for r in ranks) / n,
    }


def evaluate(queries, views, adapter, now, *, scoped: bool, top_k: int = TOP_K, demote_ids=None) -> dict:
    ranks: list[int] = []
    fails: list[dict] = []
    latencies: list[float] = []
    for item in queries:
        project = item.get("project") if scoped else None
        started = time.perf_counter()
        candidates = search(
            item["query"], project=project, records=views, embedder=adapter, now=now,
            top_k=top_k, demote_ids=demote_ids,
        )
        latencies.append((time.perf_counter() - started) * 1000.0)
        ids = [c.record.id for c in candidates]
        rank = ids.index(item["expect_id"]) + 1 if item["expect_id"] in ids else 0
        ranks.append(rank)
        if rank == 0 or rank > FAIL_RANK_THRESHOLD:
            fails.append({"expect": item["expect_id"], "rank": rank,
                          "query": item["query"], "top3": ids[:3]})
    return {"n": len(ranks), **_metrics(ranks), "fails": fails, "latencies": latencies}


def _print(label: str, res: dict) -> None:
    print(f"[{label}] n={res['n']}  recall@1={res['recall@1']:.2f}  "
          f"recall@3={res['recall@3']:.2f}  recall@5={res['recall@5']:.2f}  "
          f"MRR={res['mrr']:.3f}  nDCG@10={res['ndcg@10']:.3f}")


def main() -> None:
    queries_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERIES
    records_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_RECORDS_DIR
    queries = json.loads(Path(queries_path).read_text(encoding="utf-8"))
    views = services._collect_embed_views(Path(records_dir))
    adapter = services._build_retrieval_adapter(Path(records_dir), views)
    now = date.today().isoformat()
    demote_ids = services._build_demote_ids(Path(records_dir))

    scoped = evaluate(queries, views, adapter, now, scoped=True, demote_ids=demote_ids)
    glob = evaluate(queries, views, adapter, now, scoped=False, demote_ids=demote_ids)
    _print("scoped", scoped)
    _print("global", glob)
    lat = scoped["latencies"] + glob["latencies"]
    print(f"latency: p50={_percentile(lat, 50):.1f}ms  p95={_percentile(lat, 95):.1f}ms")
    print(f"\nscoped weak results ({len(scoped['fails'])}):")
    for f in scoped["fails"]:
        loc = "NOT FOUND" if f["rank"] == 0 else f"rank={f['rank']}"
        print(f"  [{f['expect']}] {loc} | {f['query']}  -> {f['top3']}")


if __name__ == "__main__":
    main()
