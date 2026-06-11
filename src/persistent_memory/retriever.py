"""Hybrid memory retrieval: BM25 + vector + optional graph signal, fused with RRF.

Ranking pipeline (see ``search``):

1. Each source produces an ordered candidate list: lexical BM25 (with
   query-side synonym expansion), dense cosine similarity over local
   embeddings, and — when a graph signal is available — records related
   to the top BM25 hit.
2. Sources are fused with Reciprocal Rank Fusion (RRF, k=60) and the
   fused scores are min-max normalized into a relevance term.
3. Final score = 0.90 * relevance + 0.07 * salience + 0.03 * recency.
   The weights were chosen by measurement against the recall eval set
   (eval/recall_eval.py). Min-max normalization is a deliberate choice:
   a fixed scale compressed the relevance term and let salience dominate
   the mix — measured as a recall regression.
4. Superseded / reverted-as-mistake records (and explicitly demoted ids)
   are dampened by a constant factor rather than filtered out, so history
   stays reachable but ranks below current knowledge.

Tokenization folds Turkish diacritics to ASCII (see ``query_expansion``):
plain ``str.casefold`` maps "İ" to "i" + U+0307 (combining dot above),
which never matches ASCII "i", so Turkish and English spellings of the
same term would silently produce disjoint BM25 tokens without the fold.

BM25 indexes are cached per corpus signature (record id + body/title/tags
lengths per record). The signature is a deliberate approximation of
content identity: hashing full record text on every search would cost
more than the rebuilds it avoids, and an edit that changes content while
preserving every length is rare enough to tolerate for ranking purposes.

All orderings are tie-broken by record id so results are deterministic
across runs and platforms.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

from .index import _extract_title
from .lint import LoadedRecord
from .query_expansion import TURKISH_DOTLESS_I, _fold_token, expand_query

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
EPSILON = 1e-9
RECENCY_HALF_LIFE_DAYS = 30.0
DATE_FORMAT_LEN = 10
STATUS_SUPERSEDED = "superseded"
STATUS_REVERTED = "reverted-as-mistake"
DAMPENED_STATUSES = {STATUS_SUPERSEDED, STATUS_REVERTED}
SUPERSEDED_DAMP_FACTOR = 0.3
# Canonical RRF smoothing constant (Cormack et al., 2009).
RRF_K = 60
# Weights measured on eval/recall_eval.py — retune against the eval set,
# not by intuition (see module docstring).
RELEVANCE_WEIGHT = 0.90
SALIENCE_WEIGHT = 0.07
RECENCY_WEIGHT = 0.03


@dataclass
class RetrievalCandidate:
    record: Any
    score: float


@dataclass(frozen=True)
class EmbedView:
    id: str
    project: str
    date: str
    status: str
    salience: float
    tags: list[str]
    title: str
    body: str


def adapt_loaded_record(loaded: LoadedRecord) -> EmbedView:
    record = loaded.record
    return EmbedView(
        id=record.id,
        project=record.project,
        date=record.date.isoformat(),
        status=record.status.value,
        salience=record.salience,
        tags=list(record.tags),
        title=_extract_title(loaded),
        body=loaded.body,
    )


def tokenize_text(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    return [_fold_token(match.group(0)) for match in TOKEN_PATTERN.finditer(text)]


def build_record_text(record: Any) -> str:
    tag_text = " ".join(record.tags) if record.tags else ""
    return f"{record.title} {record.body} {tag_text}"


_BM25_CACHE_LOCK = threading.Lock()
_BM25_CACHE: dict[tuple, Any] = {}
_BM25_CACHE_MAX = 4


def _reset_bm25_cache() -> None:
    with _BM25_CACHE_LOCK:
        _BM25_CACHE.clear()


def _corpus_signature(records: list[Any]) -> tuple:
    # Cheap content-identity approximation: lengths instead of hashes
    # (deliberate; see module docstring).
    return tuple(
        (rec.id, len(rec.body or ""), len(rec.title or ""), len(rec.tags or ()))
        for rec in records
    )


def _cached_bm25(records: list[Any]) -> Any:
    signature = _corpus_signature(records)
    with _BM25_CACHE_LOCK:
        cached = _BM25_CACHE.get(signature)
        if cached is not None:
            return cached
    corpus = [tokenize_text(build_record_text(rec)) for rec in records]
    bm25 = BM25Okapi(corpus)
    with _BM25_CACHE_LOCK:
        while len(_BM25_CACHE) >= _BM25_CACHE_MAX:
            _BM25_CACHE.pop(next(iter(_BM25_CACHE)))
        _BM25_CACHE[signature] = bm25
    return bm25


def bm25_rank(query: str, records: list[Any]) -> list[Any]:
    # Only the query is synonym-expanded — expanding the corpus would
    # distort BM25 document-length statistics and bloat the index.
    query_tokens = tokenize_text(expand_query(query))
    if not query_tokens or not records:
        return []
    bm25 = _cached_bm25(records)
    scores = bm25.get_scores(query_tokens)
    paired = sorted(zip(records, scores), key=lambda pair: (-pair[1], pair[0].id))
    return [rec for rec, _ in paired]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    a = np.asarray(vec_a, dtype=np.float64)
    b = np.asarray(vec_b, dtype=np.float64)
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm < EPSILON:
        return 0.0
    return float(np.dot(a, b) / norm)


def vector_rank(query: str, records: list[Any], embedder: Any) -> list[Any]:
    if not query or not query.strip() or not records:
        return []
    query_vec = embedder.embed_query(query)
    if not query_vec:
        return []
    scored = []
    for rec in records:
        record_vec = embedder.get_vector(rec.id)
        if record_vec is None:
            continue
        scored.append((rec, cosine_similarity(query_vec, record_vec)))
    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return [rec for rec, _ in scored]


def _parse_iso_date(value: str) -> date | None:
    if not value or len(value) < DATE_FORMAT_LEN:
        return None
    try:
        return date.fromisoformat(value[:DATE_FORMAT_LEN])
    except ValueError:
        return None


def recency_weight(record_date: str, now: str) -> float:
    """Exponential decay with a 30-day half-life; unparseable dates score 0."""
    parsed = _parse_iso_date(record_date)
    parsed_now = _parse_iso_date(now)
    if parsed is None or parsed_now is None:
        return 0.0
    age_days = max((parsed_now - parsed).days, 0)
    return float(0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS))


def _clamp_unit(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def salience_weight(record: Any) -> float:
    raw = _clamp_unit(float(record.salience))
    if record.status in DAMPENED_STATUSES:
        return raw * SUPERSEDED_DAMP_FACTOR
    return raw


def _rrf_scores(ranked_sources: list[list[Any]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in ranked_sources:
        for rank, rec in enumerate(ranked):
            scores[rec.id] = scores.get(rec.id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return scores


def rrf_fuse(ranked_sources: list[list[Any]]) -> list[Any]:
    if not ranked_sources:
        return []
    records_by_id = {rec.id: rec for ranked in ranked_sources for rec in ranked}
    scores = _rrf_scores(ranked_sources)
    # id-anchored tie-break: equal fused scores must order identically
    # across runs (dict iteration order would otherwise leak in).
    ordered_ids = sorted(scores, key=lambda rid: (-scores[rid], rid))
    return [records_by_id[rid] for rid in ordered_ids]


def graph_rank(seed_id: str, records: list[Any], graph_signal: Any) -> list[Any]:
    if not seed_id or not records or graph_signal is None:
        return []
    ranked_ids = graph_signal.ranked_ids_for(seed_id)
    if not ranked_ids:
        return []
    by_id = {rec.id: rec for rec in records}
    return [by_id[rid] for rid in ranked_ids if rid in by_id]


def filter_by_project(records: list[Any], project: str | None) -> list[Any]:
    if project is None:
        return list(records)
    return [rec for rec in records if rec.project == project]


def search(query: str, project: str | None, records: list[Any], embedder: Any,
           now: str, top_k: int, graph_signal: Any = None,
           demote_ids: set[str] | None = None) -> list[RetrievalCandidate]:
    """Run the full hybrid pipeline; see module docstring for the scoring model."""
    if not query or not query.strip():
        return []
    scoped = filter_by_project(records, project)
    if not scoped:
        return []
    bm25_ranked = bm25_rank(query, scoped)
    vector_ranked = vector_rank(query, scoped, embedder)
    sources = [bm25_ranked, vector_ranked]
    if graph_signal is not None and bm25_ranked:
        graph_ranked = graph_rank(bm25_ranked[0].id, scoped, graph_signal)
        if graph_ranked:
            sources.append(graph_ranked)
    fused_scores = _rrf_scores(sources)
    if not fused_scores:
        return []
    by_id = {rec.id: rec for source in sources for rec in source}
    # Min-max normalize fused RRF scores into [0, 1]. Deliberate over a
    # fixed scale: a constant divisor squashed relevance and let salience
    # dominate the weighted mix (measured on the recall eval set).
    lo = min(fused_scores.values())
    hi = max(fused_scores.values())
    span = (hi - lo) or 1.0
    candidates = []
    for rid, raw in fused_scores.items():
        rec = by_id[rid]
        relevance = (raw - lo) / span
        score = (
            RELEVANCE_WEIGHT * relevance
            + SALIENCE_WEIGHT * _clamp_unit(float(rec.salience))
            + RECENCY_WEIGHT * recency_weight(rec.date, now)
        )
        # Dampen — never drop — outdated knowledge so it stays reachable.
        if rec.status in DAMPENED_STATUSES or (demote_ids and rid in demote_ids):
            score *= SUPERSEDED_DAMP_FACTOR
        candidates.append(RetrievalCandidate(record=rec, score=score))
    candidates.sort(key=lambda cand: (-cand.score, cand.record.id))
    return candidates[:top_k]
