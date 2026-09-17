"""Business logic behind the daemon's HTTP endpoints.

Architecture role: Claude Code hooks are thin signals — they only ping the
daemon (recall, prompt-recall, extract) and must return within their tight
hook budget. All heavy work lives here: loading and caching record views,
embedding/upserting vectors, running retrieval, and spawning detached
extraction agents. Everything operates on the markdown record corpus under
``records_dir`` (decisions/, lessons/) plus the ``.pm-index`` sidecar state.
"""

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import frontmatter

from persistent_memory.daemon.config import (
    DECISIONS_DIRNAME,
    INDEX_ROOT_DIRNAME,
    LESSONS_DIRNAME,
)
from persistent_memory.i18n import t

logger = logging.getLogger(__name__)

INDEX_FILENAME = "index.md"
PROPOSED_STATUS = "proposed"
RECORD_FIELDS = ("id", "type", "status", "date", "project", "salience", "supersedes", "superseded-by")
LIST_FIELDS = ("supersedes", "superseded-by")
PREFIX_TO_TYPE = {"D": "decision", "L": "lesson", "P": "principle"}


def count_markdown(directory: Path) -> int:
    if not directory.exists():
        return 0
    return len([p for p in directory.glob("*.md") if p.name != INDEX_FILENAME])


def _type_from_id(record_id: str | None) -> str | None:
    if not record_id or "-" not in record_id:
        return None
    return PREFIX_TO_TYPE.get(record_id.split("-", 1)[0])


def load_record_meta(path: Path) -> dict:
    post = frontmatter.load(str(path))
    meta = {field: post.metadata.get(field) for field in RECORD_FIELDS}
    for field in LIST_FIELDS:
        meta[field] = meta.get(field) or []
    meta["path"] = str(path)
    inferred = _type_from_id(meta.get("id"))
    if inferred:
        meta["type"] = inferred
    return meta


def sort_by_date_desc(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: str(r.get("date") or ""), reverse=True)


def list_records(directories: list[Path]) -> list[dict]:
    records: list[dict] = []
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == INDEX_FILENAME:
                continue
            records.append(load_record_meta(path))
    return records


SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
H1_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)


def _title_from_body(body: str, fallback: str) -> str:
    match = H1_HEADING_RE.search(body)
    if match:
        return match.group(1).strip()
    return fallback


def list_records_with_titles(directories: list[Path]) -> list[dict]:
    records: list[dict] = []
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == INDEX_FILENAME:
                continue
            meta = load_record_meta(path)
            meta["title"] = _read_title(path)
            records.append(meta)
    return records


def _read_title(path: Path) -> str:
    from persistent_memory.records import read_record

    try:
        _, body = read_record(path)
    except ValueError:
        return path.stem
    return _title_from_body(body, path.stem)


def filter_by_status(records: list[dict], status: str) -> list[dict]:
    return [r for r in records if r.get("status") == status]


def filter_by_type(records: list[dict], record_type: str) -> list[dict]:
    return [r for r in records if r.get("type") == record_type]


DEFAULT_TOP_K = 5

_RECORDS_CACHE_LOCK = threading.Lock()
_RECORDS_CACHE: dict[str, tuple[tuple, list, set]] = {}
_INDEX_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, tuple[tuple, Any]] = {}

# Prompt hooks can arrive concurrently (for example, several agent/tool loops
# starting together). A corpus fingerprint is O(number-of-records) filesystem
# work, so concurrent callers share the one in-flight scan. Unlike a TTL cache,
# a later sequential call still rescans immediately and observes file changes.
_FINGERPRINT_CONDITION = threading.Condition()
_FINGERPRINT_INFLIGHT: set[str] = set()
_FINGERPRINT_RESULTS: dict[str, tuple] = {}
_RETRIEVAL_ADAPTER_CACHE: dict[str, tuple[tuple, tuple, object]] = {}


PROMPT_RECALL_METRIC = "prompt_recall_count"
EXTRACTION_STARTED_METRIC = "extraction_started_count"

_METRICS_LOCK = threading.Lock()
_METRICS: dict[str, int] = {PROMPT_RECALL_METRIC: 0, EXTRACTION_STARTED_METRIC: 0}


def bump_metric(name: str) -> None:
    with _METRICS_LOCK:
        _METRICS[name] = _METRICS.get(name, 0) + 1


def metrics_snapshot() -> dict[str, int]:
    with _METRICS_LOCK:
        return dict(_METRICS)


def reset_metrics() -> None:
    with _METRICS_LOCK:
        for name in _METRICS:
            _METRICS[name] = 0


def _records_fingerprint(records_dir: Path) -> tuple:
    entries = []
    for dirname in (DECISIONS_DIRNAME, LESSONS_DIRNAME):
        directory = Path(records_dir) / dirname
        if not directory.is_dir():
            continue
        with os.scandir(directory) as scanner:
            for entry in scanner:
                if not entry.is_file() or not entry.name.endswith(".md"):
                    continue
                if entry.name == INDEX_FILENAME:
                    continue
                stat = entry.stat()
                entries.append((entry.path, stat.st_mtime_ns, stat.st_size))
    entries.sort()
    return tuple(entries)


def _records_fingerprint_singleflight(records_dir: Path) -> tuple:
    """Share one in-flight corpus scan among concurrent callers.

    Once that cohort finishes, a later call starts a fresh scan so direct file
    edits are visible immediately; there is no time-based stale window.
    """
    key = str(Path(records_dir))
    with _FINGERPRINT_CONDITION:
        if key in _FINGERPRINT_INFLIGHT:
            while key in _FINGERPRINT_INFLIGHT:
                _FINGERPRINT_CONDITION.wait()
            return _FINGERPRINT_RESULTS[key]
        _FINGERPRINT_INFLIGHT.add(key)
    try:
        fingerprint = _records_fingerprint(Path(records_dir))
    except BaseException:
        with _FINGERPRINT_CONDITION:
            _FINGERPRINT_INFLIGHT.discard(key)
            _FINGERPRINT_CONDITION.notify_all()
        raise
    with _FINGERPRINT_CONDITION:
        _FINGERPRINT_RESULTS[key] = fingerprint
        _FINGERPRINT_INFLIGHT.discard(key)
        _FINGERPRINT_CONDITION.notify_all()
    return fingerprint


def _invalidate_runtime_caches(records_dir: Path) -> None:
    """Invalidate corpus-derived caches after a watcher-observed change."""
    key = str(Path(records_dir))
    with _FINGERPRINT_CONDITION:
        _FINGERPRINT_RESULTS.pop(key, None)
    with _RECORDS_CACHE_LOCK:
        _RECORDS_CACHE.pop(key, None)
    with _INDEX_LOCK:
        _RETRIEVAL_ADAPTER_CACHE.pop(key, None)


def _clear_runtime_caches() -> None:
    """Clear process caches (test/support helper; safe between daemon runs)."""
    with _FINGERPRINT_CONDITION:
        _FINGERPRINT_RESULTS.clear()
    with _RECORDS_CACHE_LOCK:
        _RECORDS_CACHE.clear()
    with _INDEX_LOCK:
        _INDEX_CACHE.clear()
        _RETRIEVAL_ADAPTER_CACHE.clear()


def _load_views_and_demote(records_dir: Path) -> tuple[list, set]:
    from persistent_memory.lint import collect_records
    from persistent_memory.retriever import adapt_loaded_record

    views: list = []
    demote: set[str] = set()
    for dirname in (DECISIONS_DIRNAME, LESSONS_DIRNAME):
        directory = Path(records_dir) / dirname
        if not directory.is_dir():
            continue
        for loaded in collect_records(directory):
            views.append(adapt_loaded_record(loaded))
            if loaded.record.superseded_by:
                demote.add(loaded.record.id)
    return views, demote


def _cached_views_and_demote(
    records_dir: Path, fingerprint: tuple | None = None
) -> tuple[list, set]:
    key = str(records_dir)
    if fingerprint is None:
        fingerprint = _records_fingerprint(records_dir)
    with _RECORDS_CACHE_LOCK:
        cached = _RECORDS_CACHE.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1], cached[2]
        # Keep the miss build under the lock. Corpus changes are infrequent;
        # duplicate parsing of thousands of markdown files is far worse than
        # making concurrent readers wait for the single builder.
        views, demote = _load_views_and_demote(records_dir)
        _RECORDS_CACHE[key] = (fingerprint, views, demote)
        return views, demote


def _collect_embed_views(records_dir: Path, fingerprint: tuple | None = None) -> list:
    return _cached_views_and_demote(records_dir, fingerprint)[0]


def _index_stamp(index_dir: Path) -> tuple:
    from persistent_memory.embeddings import IDS_FILE, VECTORS_FILE

    stamps = []
    for name in (VECTORS_FILE, IDS_FILE):
        try:
            stat = (index_dir / name).stat()
            stamps.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append((name, 0, 0))
    return tuple(stamps)


def _shared_index_locked(records_dir: Path):
    from persistent_memory.embeddings import VectorIndex

    index_dir = Path(records_dir) / INDEX_DIRNAME
    stamp = _index_stamp(index_dir)
    cached = _INDEX_CACHE.get(str(index_dir))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    index = VectorIndex(index_dir)
    index.load()
    _INDEX_CACHE[str(index_dir)] = (stamp, index)
    return index


def _refresh_index_stamp_locked(records_dir: Path, index) -> None:
    index_dir = Path(records_dir) / INDEX_DIRNAME
    _INDEX_CACHE[str(index_dir)] = (_index_stamp(index_dir), index)


def _build_retrieval_adapter(
    records_dir: Path, views: list, fingerprint: tuple | None = None
):
    from persistent_memory.embeddings import (
        OllamaEmbedder,
        RetrievalAdapter,
        content_hash_for,
        embed_record as _embed,
    )

    key = str(Path(records_dir))
    if fingerprint is None:
        fingerprint = _records_fingerprint(records_dir)
    # Index synchronization is single-flight. More importantly, once a corpus
    # fingerprint + persisted index stamp has been synchronized, subsequent
    # requests return the adapter directly instead of repeating an O(N)
    # content-hash pass while holding _INDEX_LOCK.
    with _INDEX_LOCK:
        index_dir = Path(records_dir) / INDEX_DIRNAME
        stamp = _index_stamp(index_dir)
        cached = _RETRIEVAL_ADAPTER_CACHE.get(key)
        if cached is not None and cached[0] == fingerprint and cached[1] == stamp:
            return cached[2]

        embedder = OllamaEmbedder()
        index = _shared_index_locked(records_dir)
        changed = False
        for view in views:
            new_hash = content_hash_for(view)
            if index.hash_of(view.id) == new_hash:
                continue
            index.upsert(view.id, _embed(view, embedder), content_hash=new_hash)
            changed = True
        if changed:
            index.save()
            _refresh_index_stamp_locked(records_dir, index)
        stamp = _index_stamp(index_dir)
        adapter = RetrievalAdapter(embedder, index)
        _RETRIEVAL_ADAPTER_CACHE[key] = (fingerprint, stamp, adapter)
        return adapter


def _build_demote_ids(records_dir: Path, fingerprint: tuple | None = None) -> set[str]:
    """Records to demote at retrieval time: superseded (outdated) records.

    An outdated record should not outrank its current replacement. Demotion
    only — superseded records stay visible so contradictions remain auditable.
    """
    return _cached_views_and_demote(records_dir, fingerprint)[1]


def warm_retrieval(*, records_dir: Path) -> None:
    from persistent_memory.retriever import _cached_bm25

    fingerprint = _records_fingerprint_singleflight(records_dir)
    views = _collect_embed_views(records_dir, fingerprint)
    if not views:
        return
    adapter = _build_retrieval_adapter(records_dir, views, fingerprint)
    _build_demote_ids(records_dir, fingerprint)
    _cached_bm25(views)
    adapter.embed_query("")


def run_search(query: str, *, records_dir: Path, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    from datetime import date

    from persistent_memory.retriever import search

    fingerprint = _records_fingerprint_singleflight(records_dir)
    views = _collect_embed_views(records_dir, fingerprint)
    candidates = search(
        query,
        project=None,
        records=views,
        embedder=_build_retrieval_adapter(records_dir, views, fingerprint),
        now=date.today().isoformat(),
        top_k=top_k,
        demote_ids=_build_demote_ids(records_dir, fingerprint),
    )
    return [
        {
            "id": cand.record.id,
            "title": cand.record.title,
            "project": cand.record.project,
            "score": cand.score,
        }
        for cand in candidates
    ]


PROMPT_RECALL_TOP_K = 3
PROMPT_RECALL_BUDGET_TOKENS = 700
PROMPT_RECALL_CHARS_PER_TOKEN = 4
# Header text is resolved at call time via i18n.t so PM_LANG applies per process.
PROMPT_RECALL_HEADER_KEY = "prompt_recall.header"
# Bilingual on purpose: new records use English headings ("Decision",
# "General rule") while older corpora may still use the Turkish originals.
DECISION_GIST_HEADINGS = ("Karar", "Decision")
LESSON_GIST_HEADINGS = ("Genel kural", "General rule")


def _gist_from_body(body: str, *, preferred_headings: tuple[str, ...]) -> str:
    sections = _split_sections(body)
    for heading in preferred_headings:
        for section in sections:
            if section["heading"].casefold() == heading.casefold() and section["text"]:
                return section["text"].splitlines()[0].strip()
    for section in sections:
        if section["text"]:
            return section["text"].splitlines()[0].strip()
    return ""


def _preferred_gist_headings(record_id: str) -> tuple[str, ...]:
    if _type_from_id(record_id) == "lesson":
        return LESSON_GIST_HEADINGS
    return DECISION_GIST_HEADINGS


def run_prompt_recall(
    query: str, *, records_dir: Path, project: str | None,
    top_k: int = PROMPT_RECALL_TOP_K, budget: int = PROMPT_RECALL_BUDGET_TOKENS,
    minimum_relevance: float = 0.0,
) -> str:
    bump_metric(PROMPT_RECALL_METRIC)
    if not query or not query.strip():
        return ""
    try:
        candidates = _search_for_prompt_recall(query, records_dir=records_dir, project=project, top_k=top_k)
    except Exception:
        logger.warning("prompt-recall search failed (project=%s)", project, exc_info=True)
        return ""
    return _format_prompt_recall_block(
        candidates, budget=budget, minimum_relevance=minimum_relevance
    )


CROSS_PROJECT_MAX = 2
CROSS_PROJECT_SCORE_RATIO = 0.55
CROSS_PROJECT_RANK_LIMIT = 3


def _cross_project_hits(query, views, adapter, now, project, seen, demote_ids=None) -> list:
    from persistent_memory.retriever import search

    global_hits = search(
        query, project=None, records=views, embedder=adapter, now=now,
        top_k=CROSS_PROJECT_RANK_LIMIT, demote_ids=demote_ids,
    )
    if not global_hits:
        return []
    threshold = (global_hits[0].score or 0.0) * CROSS_PROJECT_SCORE_RATIO
    cross = []
    for cand in global_hits:
        if cand.record.project == project or cand.record.id in seen:
            continue
        if cand.score >= threshold:
            cross.append(cand)
        if len(cross) >= CROSS_PROJECT_MAX:
            break
    return cross


def _search_for_prompt_recall(query: str, *, records_dir: Path, project: str | None, top_k: int) -> list:
    from datetime import date

    from persistent_memory.retriever import search

    limit = max(0, min(top_k, PROMPT_RECALL_TOP_K))
    fingerprint = _records_fingerprint_singleflight(records_dir)
    views = _collect_embed_views(records_dir, fingerprint)
    if not views:
        return []
    adapter = _build_retrieval_adapter(records_dir, views, fingerprint)
    now = date.today().isoformat()
    demote = _build_demote_ids(records_dir, fingerprint)
    primary = search(
        query, project=project, records=views, embedder=adapter, now=now,
        top_k=limit, demote_ids=demote,
    )
    if project is None or len(primary) >= limit:
        return primary
    seen = {cand.record.id for cand in primary}
    cross = _cross_project_hits(query, views, adapter, now, project, seen, demote)
    return (primary + cross)[:limit]


def _format_prompt_recall_block(
    candidates: list, *, budget: int, minimum_relevance: float = 0.0
) -> str:
    if not candidates:
        return ""
    header = t(PROMPT_RECALL_HEADER_KEY)
    lines = [header]
    used = _estimate_recall_tokens(header)
    for candidate in candidates:
        if float(candidate.score or 0.0) < minimum_relevance:
            continue
        view = candidate.record
        gist = _gist_from_body(view.body, preferred_headings=_preferred_gist_headings(view.id))
        line = f"- [{view.id}] {view.title} ({view.project}): {gist}"
        cost = _estimate_recall_tokens(line)
        if used + cost > budget:
            break
        lines.append(line)
        used += cost
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _estimate_recall_tokens(text: str) -> int:
    return len(text) // PROMPT_RECALL_CHARS_PER_TOKEN + 1


def run_recall(*, records_dir: Path, project: str | None) -> str:
    from datetime import date

    from persistent_memory.recall import build_recall_block
    from persistent_memory.retriever import (
        RetrievalCandidate,
        SUPERSEDED_DAMP_FACTOR,
        filter_by_project,
        recency_weight,
        salience_weight,
    )

    views = _collect_embed_views(records_dir)
    now = date.today().isoformat()
    demote = _build_demote_ids(records_dir)

    def searcher(*, project: str | None, top_k: int) -> list[RetrievalCandidate]:
        scoped = filter_by_project(views, project)
        candidates = [
            RetrievalCandidate(
                record=view,
                score=recency_weight(view.date, now)
                * salience_weight(view)
                * (SUPERSEDED_DAMP_FACTOR if view.id in demote else 1.0),
            )
            for view in scoped
        ]
        candidates.sort(key=lambda cand: (-cand.score, cand.record.id))
        return candidates[:top_k]

    return build_recall_block(project, searcher)


SUPERSESSION_CHECK = "supersession"


def run_lint(*, records_dir: Path) -> dict:
    from datetime import date

    from persistent_memory.lint import Severity, run_lint as _lint

    errors: list[str] = []
    conflicts: list[str] = []
    report = _lint(Path(records_dir), today=date.today())
    for finding in report.findings:
        line = f"[{finding.check}] {finding.record_id}: {finding.message}"
        if finding.check == SUPERSESSION_CHECK:
            conflicts.append(line)
        elif finding.severity >= Severity.ERROR:
            errors.append(line)
    return {"errors": errors, "conflicts": conflicts}


ACCEPTED_STATUS = "accepted"
REJECTED_STATUS = "reverted-as-mistake"


def apply_status(record_id: str, *, records_dir: Path, status: str) -> dict:
    from persistent_memory.records import update_status
    from persistent_memory.schema import RecordStatus

    update_status(Path(records_dir), record_id, RecordStatus(status))
    return {"id": record_id, "status": status}


def accept_all(records_dir: Path, *, project: str | None = None, record_type: str | None = None) -> int:
    root = Path(records_dir)
    pending = filter_by_status(
        list_records([root / DECISIONS_DIRNAME, root / LESSONS_DIRNAME]), PROPOSED_STATUS
    )
    count = 0
    for meta in pending:
        if project is not None and meta.get("project") != project:
            continue
        if record_type is not None and meta.get("type") != record_type:
            continue
        record_id = meta.get("id")
        if not record_id:
            continue
        apply_status(record_id, records_dir=root, status=ACCEPTED_STATUS)
        count += 1
    return count


def _split_sections(body: str) -> list[dict]:
    matches = list(SECTION_HEADING_RE.finditer(body))
    sections: list[dict] = []
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append({"heading": heading, "text": body[start:end].strip()})
    return sections


def _resolve_chain(records_dir: Path, ids: list[str]) -> list[dict]:
    from persistent_memory.records import find_record_path

    resolved: list[dict] = []
    for ref_id in ids:
        title = ref_id
        try:
            path = find_record_path(Path(records_dir), ref_id)
            title = _read_title(path)
        except (FileNotFoundError, ValueError, KeyError):
            title = ref_id
        resolved.append({"id": ref_id, "title": title})
    return resolved


SOURCE_PASSAGE_TOP_K = 5


def _default_transcript_index_dir(records_dir: Path) -> Path:
    from persistent_memory.daemon.config import INDEX_ROOT_DIRNAME, TRANSCRIPT_INDEX_DIRNAME

    return Path(records_dir) / INDEX_ROOT_DIRNAME / TRANSCRIPT_INDEX_DIRNAME


def _retrieve_source_passages(
    *, query_text: str, index_dir: Path, project: str | None
) -> list[dict]:
    from persistent_memory.transcript_rag import retrieve_for_text

    try:
        return retrieve_for_text(
            query_text, index_dir=index_dir, project=project, top_k=SOURCE_PASSAGE_TOP_K
        )
    except Exception:
        logger.warning("source passage retrieval failed (project=%s)", project, exc_info=True)
        return []


def _source_query_text(title: str, sections: list[dict]) -> str:
    first_body = sections[0]["text"] if sections else ""
    return f"{title}\n{first_body}".strip()


def record_detail(records_dir: Path, record_id: str, transcript_index_dir: Path | None = None) -> dict:
    from persistent_memory.records import read_record_by_id

    record, body = read_record_by_id(Path(records_dir), record_id)
    title = _title_from_body(body, record.id)
    sections = _split_sections(body)
    index_dir = transcript_index_dir or _default_transcript_index_dir(records_dir)
    source_passages = _retrieve_source_passages(
        query_text=_source_query_text(title, sections),
        index_dir=index_dir,
        project=record.project,
    )
    return {
        "id": record.id,
        "title": title,
        "type": record.type.value,
        "status": record.status.value,
        "project": record.project,
        "date": record.date.isoformat(),
        "salience": record.salience,
        "tags": list(record.tags),
        "provenance": record.provenance.model_dump(),
        "sections": sections,
        "supersedes": _resolve_chain(records_dir, record.supersedes),
        "superseded_by": _resolve_chain(records_dir, record.superseded_by),
        "source_passages": source_passages,
    }


INDEX_DIRNAME = ".index"


def embed_record(path: Path, *, records_dir: Path) -> None:
    from persistent_memory.embeddings import (
        OllamaEmbedder,
        content_hash_for,
        embed_record as _embed,
    )
    from persistent_memory.lint import collect_records
    from persistent_memory.retriever import adapt_loaded_record

    record_path = Path(path)
    loaded = next(
        (item for item in collect_records(record_path.parent) if item.path == record_path),
        None,
    )
    if loaded is None:
        return
    view = adapt_loaded_record(loaded)
    content_hash = content_hash_for(view)
    with _INDEX_LOCK:
        index = _shared_index_locked(records_dir)
        if index.hash_of(view.id) == content_hash:
            return
        vector = _embed(view, OllamaEmbedder())
        index.upsert(view.id, vector, content_hash)
        index.save()
        _refresh_index_stamp_locked(records_dir, index)
    # Do this after releasing _INDEX_LOCK; invalidation also clears the cached
    # adapter under that lock.
    _invalidate_runtime_caches(records_dir)


def _current_salience_map(records_dir: Path) -> dict[str, float]:
    salience: dict[str, float] = {}
    for meta in list_records([records_dir / DECISIONS_DIRNAME, records_dir / LESSONS_DIRNAME]):
        record_id = meta.get("id")
        value = meta.get("salience")
        if record_id is not None and value is not None:
            salience[record_id] = float(value)
    return salience


def run_consolidation(*, records_dir: Path, cluster_only: bool = True) -> dict:
    from persistent_memory.consolidate import run_consolidation as _run

    corpus_root = Path(records_dir)
    result = _run(
        corpus_root,
        current_salience=_current_salience_map(corpus_root),
        should_full_build=not cluster_only,
    )
    return {
        "supersession_candidates": [c.model_dump() for c in result.supersession_candidates],
        "knowledge_gaps": [g.model_dump() for g in result.knowledge_gaps],
        "salience_updates": result.salience_updates,
    }


DISMISSED_CANDIDATES_FILENAME = "dismissed-candidates.json"
CANDIDATE_LABEL_ID_RE = re.compile(r"\b([DLP]-\d{4})\b")


def _dismissed_candidates_path(records_dir: Path) -> Path:
    return Path(records_dir) / INDEX_ROOT_DIRNAME / DISMISSED_CANDIDATES_FILENAME


def _load_dismissed_pairs(records_dir: Path) -> list[dict]:
    import json

    path = _dismissed_candidates_path(records_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("could not read dismissed-candidates file: %s", path, exc_info=True)
        return []
    return data if isinstance(data, list) else []


def _pair_key(source: str, target: str) -> frozenset[str]:
    return frozenset((source, target))


def _dismissed_keys(records_dir: Path) -> set[frozenset[str]]:
    return {
        _pair_key(pair.get("source") or "", pair.get("target") or "")
        for pair in _load_dismissed_pairs(records_dir)
    }


def _record_id_in_label(label: str) -> str | None:
    match = CANDIDATE_LABEL_ID_RE.search(label)
    return match.group(1) if match else None


def _candidate_key(candidate: dict) -> frozenset[str]:
    return _pair_key(
        candidate["source_id"] or candidate["source_label"],
        candidate["target_id"] or candidate["target_label"],
    )


def list_supersession_candidates(*, records_dir: Path) -> list[dict]:
    from persistent_memory.consolidate import (
        GRAPH_FILENAME,
        GRAPHIFY_OUT_DIRNAME,
        map_surprises_to_supersession_candidates,
        parse_analysis,
    )

    graph_path = Path(records_dir) / GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
    try:
        analysis = parse_analysis(graph_path)
    except FileNotFoundError:
        return []
    dismissed = _dismissed_keys(records_dir)
    candidates: list[dict] = []
    for candidate in map_surprises_to_supersession_candidates(analysis):
        item = candidate.model_dump()
        item["source_id"] = _record_id_in_label(candidate.source_label)
        item["target_id"] = _record_id_in_label(candidate.target_label)
        if _candidate_key(item) in dismissed:
            continue
        candidates.append(item)
    candidates.sort(key=lambda c: -c["score"])
    return candidates


def dismiss_supersession_candidate(*, records_dir: Path, source: str, target: str) -> dict:
    import json

    from persistent_memory.records import _write_text_atomic

    pairs = _load_dismissed_pairs(records_dir)
    existing = {
        _pair_key(pair.get("source") or "", pair.get("target") or "") for pair in pairs
    }
    if _pair_key(source, target) not in existing:
        pairs.append({"source": source, "target": target})
        path = _dismissed_candidates_path(records_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(path, json.dumps(pairs, ensure_ascii=False, indent=2))
    return {"dismissed": True, "source": source, "target": target}


RECENT_TITLES_LIMIT = 5
RECENT_MESSAGES_LIMIT = 20
MESSAGE_SNIPPET_LENGTH = 240


def _records_by_project(records_dir: Path, project: str) -> dict[str, list[dict]]:
    decisions = [
        r for r in list_records([Path(records_dir) / DECISIONS_DIRNAME]) if r.get("project") == project
    ]
    lessons = [
        r for r in list_records([Path(records_dir) / LESSONS_DIRNAME]) if r.get("project") == project
    ]
    return {"decisions": decisions, "lessons": lessons}


def _snippet(text: str | None) -> str:
    if not text:
        return ""
    if len(text) <= MESSAGE_SNIPPET_LENGTH:
        return text
    return text[:MESSAGE_SNIPPET_LENGTH].rstrip() + "…"


def _project_by_name(projects_root: Path, project: str):
    from persistent_memory.transcripts import list_projects

    return next((p for p in list_projects(projects_root) if p.name == project), None)


def _recent_messages(project_dir: Path) -> list[dict]:
    from persistent_memory.transcripts import project_transcripts, read_transcript

    messages: list[dict] = []
    for transcript in project_transcripts(project_dir):
        for message in read_transcript(transcript):
            if not message.text:
                continue
            messages.append(
                {
                    "role": message.role,
                    "text": _snippet(message.text),
                    "timestamp": message.timestamp,
                    "is_tool": message.is_tool,
                }
            )
    messages.sort(key=lambda m: (m["timestamp"] or ""), reverse=True)
    return messages[:RECENT_MESSAGES_LIMIT]


def project_overview(*, projects_root: Path, records_dir: Path) -> list[dict]:
    from persistent_memory.transcripts import list_projects

    overview: list[dict] = []
    for info in list_projects(projects_root):
        records = _records_by_project(records_dir, info.name)
        overview.append(
            {
                "name": info.name,
                "path": info.path,
                "transcript_count": info.transcript_count,
                "last_activity": info.last_activity,
                "decisions_count": len(records["decisions"]),
                "lessons_count": len(records["lessons"]),
            }
        )
    return overview


def project_detail(*, project: str, projects_root: Path, records_dir: Path) -> dict:
    records = _records_by_project(records_dir, project)
    detail = {
        "name": project,
        "recent_messages": [],
        "decisions": records["decisions"],
        "lessons": records["lessons"],
    }
    if not project:
        return detail
    info = _project_by_name(projects_root, project)
    if info is None:
        return detail
    detail["recent_messages"] = _recent_messages(info.dir)
    return detail


CODEX_ROOT = Path.home() / ".codex"
KIMI_ROOT = Path.home() / ".kimi-code"
GROK_ROOT = Path.home() / ".grok"


def _extraction_backend_for(transcript_path: "Path | str | None") -> str:
    """Return host-specific backend for the transcript path.

    Rule: each host extracts with itself — never cross-host fallback.
    Codex → codex, Kimi → kimi, Grok → grok, Claude (and unknown) → claude.
    """
    if transcript_path is None:
        return "claude"
    try:
        resolved = Path(transcript_path).resolve()
        if resolved.is_relative_to(CODEX_ROOT.resolve()):
            return "codex"
        if resolved.is_relative_to(KIMI_ROOT.resolve()):
            return "kimi"
        if resolved.is_relative_to(GROK_ROOT.resolve()):
            return "grok"
    except (TypeError, ValueError):
        pass
    return "claude"


class TranscriptPathError(ValueError):
    pass


EXTRACTION_STARTED_STATUS = "started"
EXTRACTION_RUNNING_STATUS = "already-running"
EXTRACTION_BASELINE_STATUS = "baseline-set"
EXTRACTION_NO_NEW_STATUS = "no-new-messages"
EXTRACTION_BACKEND_UNAVAILABLE_STATUS = "backend-unavailable"
EXTRACTION_LOG_DIRNAME = "extraction-logs"
WATERMARK_DIRNAME = "extraction-watermarks"
SLICE_DIRNAME = "extraction-slices"
FIRST_RUN_MAX_MESSAGES = 60
DEFAULT_MAX_SLICE_MESSAGES = None
EXTRA_PATH_DIRS = (
    Path.home() / ".local" / "bin",
    Path.home() / ".grok" / "bin",
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


class ExtractionBackendError(RuntimeError):
    """Host CLI for this transcript source is missing; do not cross-host fall back."""

    def __init__(self, backend: str, message: str):
        super().__init__(message)
        self.backend = backend

EXTRACTION_MAX_SECONDS = 900

_extraction_lock = threading.Lock()
_extraction_procs: dict[str, tuple[subprocess.Popen, float]] = {}


def reset_extraction_state() -> None:
    with _extraction_lock:
        _extraction_procs.clear()


def _prune_finished_extractions() -> None:
    # A hung extraction agent would otherwise block its project forever (one
    # extraction per project at a time), so kill anything past the deadline.
    now = time.monotonic()
    for project, (proc, started_at) in list(_extraction_procs.items()):
        if proc.poll() is not None:
            del _extraction_procs[project]
        elif now - started_at > EXTRACTION_MAX_SECONDS:
            proc.kill()
            del _extraction_procs[project]


def _extraction_env() -> dict:
    env = os.environ.copy()
    extra = os.pathsep.join(str(p) for p in EXTRA_PATH_DIRS if p.is_dir())
    if extra:
        env["PATH"] = os.pathsep.join(filter(None, [extra, env.get("PATH", "")]))
    return env


def _resolve_claude_bin(env: dict) -> str:
    from persistent_memory.extraction_prompt import CLAUDE_BIN

    return shutil.which(CLAUDE_BIN, path=env.get("PATH")) or CLAUDE_BIN


def _resolve_codex_bin(env: dict) -> str | None:
    from persistent_memory.extraction_prompt import CODEX_APP_BIN, CODEX_BIN, CODEX_BIN_ENV

    override = env.get(CODEX_BIN_ENV)
    if override:
        return override
    if CODEX_APP_BIN.is_file():
        return str(CODEX_APP_BIN)
    return shutil.which(CODEX_BIN, path=env.get("PATH"))


def _resolve_kimi_bin(env: dict) -> str | None:
    from persistent_memory.extraction_prompt import KIMI_BIN

    return shutil.which(KIMI_BIN, path=env.get("PATH"))


def _resolve_grok_bin(env: dict) -> str | None:
    from persistent_memory.extraction_prompt import (
        GROK_BIN,
        GROK_BIN_ENV,
        GROK_HOME_BIN,
        GROK_USER_BIN,
    )

    override = env.get(GROK_BIN_ENV)
    if override:
        return override
    for candidate in (GROK_USER_BIN, GROK_HOME_BIN):
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return shutil.which(GROK_BIN, path=env.get("PATH"))


def _index_subdir(records_dir: Path | None, name: str) -> Path:
    from persistent_memory.daemon.token import default_records_dir

    base = Path(records_dir) if records_dir else default_records_dir()
    path = base / INDEX_ROOT_DIRNAME / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extraction_log_path(records_dir: Path | None, project: str) -> Path:
    safe_project = re.sub(r"[^A-Za-z0-9_.-]", "_", project) or "unknown"
    log_dir = _index_subdir(records_dir, EXTRACTION_LOG_DIRNAME)
    return log_dir / f"{safe_project}-{time.strftime('%Y%m%d-%H%M%S')}.log"


def _watermark_path(records_dir: Path | None, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "unknown"
    return _index_subdir(records_dir, WATERMARK_DIRNAME) / f"{safe}.json"


def _read_watermark(path: Path) -> int:
    import json

    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("count", 0))
    except (OSError, ValueError):
        return 0


def _write_watermark(path: Path, count: int) -> None:
    import json

    path.write_text(json.dumps({"count": count}), encoding="utf-8")


TRANSCRIPT_ROOTS_ENV = "PM_TRANSCRIPT_ROOTS"
DEFAULT_TRANSCRIPT_ROOTS = (
    Path.home() / ".claude" / "projects",
    Path.home() / ".codex",
    Path.home() / ".kimi-code",
    Path.home() / ".grok",
)
CWD_ROOTS_ENV = "PM_CWD_ROOTS"
DEFAULT_CWD_ROOTS = (Path.home(),)


class CwdValidationError(ValueError):
    pass


def _roots_from_env(env_name: str, defaults: tuple[Path, ...]) -> tuple[Path, ...]:
    override = os.environ.get(env_name)
    if not override:
        return defaults
    return tuple(Path(part) for part in override.split(os.pathsep) if part)


def _allowed_transcript_roots() -> tuple[Path, ...]:
    return _roots_from_env(TRANSCRIPT_ROOTS_ENV, DEFAULT_TRANSCRIPT_ROOTS)


def _allowed_cwd_roots() -> tuple[Path, ...]:
    return _roots_from_env(CWD_ROOTS_ENV, DEFAULT_CWD_ROOTS)


def _validate_transcript_path(transcript_path: str) -> Path:
    resolved = Path(transcript_path).resolve()
    for root in _allowed_transcript_roots():
        if resolved.is_relative_to(root.resolve()):
            return resolved
    raise TranscriptPathError(f"transcript_path outside allowed roots: {transcript_path}")


def _validate_cwd(cwd: str) -> Path:
    resolved = Path(cwd).resolve()
    if not resolved.is_dir():
        raise CwdValidationError(f"cwd is not an existing directory: {cwd}")
    for root in _allowed_cwd_roots():
        if resolved.is_relative_to(root.resolve()):
            return resolved
    raise CwdValidationError(f"cwd outside allowed roots: {cwd}")


def _checked_cwd(cwd: str) -> str:
    if not cwd:
        return ""
    try:
        _validate_cwd(cwd)
    except CwdValidationError:
        logger.warning("extraction cwd rejected, continuing without cwd: %s", cwd, exc_info=True)
        return ""
    return cwd


def _normalize_max_messages(max_messages: int | None) -> int | None:
    if max_messages is None:
        return DEFAULT_MAX_SLICE_MESSAGES
    try:
        value = int(max_messages)
    except (TypeError, ValueError):
        return DEFAULT_MAX_SLICE_MESSAGES
    return value if value > 0 else DEFAULT_MAX_SLICE_MESSAGES


def prepare_extraction_input(
    *,
    transcript_path: str,
    records_dir: Path | None,
    force: bool = False,
    reset_watermark: bool = False,
    max_messages: int | None = None,
) -> dict:
    from persistent_memory.transcripts import read_transcript

    resolved = _validate_transcript_path(transcript_path)
    session_id = resolved.stem
    messages = [m for m in read_transcript(resolved) if m.text and not m.is_tool]
    total = len(messages)
    wm_path = _watermark_path(records_dir, session_id)
    watermark = 0 if reset_watermark else _read_watermark(wm_path)
    # A watermark above the message count means the transcript was truncated
    # or replaced (e.g. session restart); reset rather than skip everything.
    if watermark > total:
        watermark = 0
    base = {"session_id": session_id, "total": total, "wm_path": str(wm_path)}
    if not force and watermark <= 0 and total > FIRST_RUN_MAX_MESSAGES:
        return {**base, "new_count": 0, "is_baseline": True}
    new = messages[watermark:] if watermark > 0 else messages
    if not new:
        return {**base, "new_count": 0, "is_baseline": False}
    limit = _normalize_max_messages(max_messages)
    if limit is not None:
        new = new[:limit]
    watermark_after = watermark + len(new)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id) or "unknown"
    slice_path = _index_subdir(records_dir, SLICE_DIRNAME) / f"{safe}-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    slice_path.write_text("\n\n".join(f"[{m.role}] {m.text}" for m in new), encoding="utf-8")
    return {
        **base,
        "new_count": len(new),
        "is_baseline": False,
        "slice_path": str(slice_path),
        "watermark_before": watermark,
        "watermark_after": watermark_after,
        "complete": watermark_after >= total,
    }


DEDUP_CONTEXT_TOP_K = 12
DEDUP_SLICE_CHARS = 4000


def _existing_similar_records(slice_path: str, records_dir: Path | None) -> list[str]:
    from datetime import date

    from persistent_memory.retriever import search

    try:
        slice_text = Path(slice_path).read_text(encoding="utf-8")[:DEDUP_SLICE_CHARS]
        views = _collect_embed_views(records_dir)
        if not views:
            return []
        adapter = _build_retrieval_adapter(records_dir, views)
        cands = search(
            slice_text, project=None, records=views, embedder=adapter,
            now=date.today().isoformat(), top_k=DEDUP_CONTEXT_TOP_K,
        )
        return [f"- [{c.record.id}] ({c.record.project}) {c.record.title}" for c in cands]
    except Exception:
        logger.warning("similar-record search for dedup context failed", exc_info=True)
        return []


def _build_argv_for_backend(
    backend: str,
    *,
    prompt: str,
    cwd: str,
    records_dir: Path | None,
    env: dict,
) -> tuple[list[str], str]:
    """Return (argv, executable) for the given backend.

    Host purity: codex/kimi/grok/claude each use their own CLI. Missing host
    binary raises ``ExtractionBackendError`` — never cross-host fall back
    (e.g. Grok session must not spawn Claude).
    """
    from persistent_memory.daemon.token import default_records_dir
    from persistent_memory.extraction_prompt import (
        build_codex_extraction_argv,
        build_extraction_argv,
        build_grok_extraction_argv,
        build_kimi_extraction_argv,
    )

    if backend == "codex":
        codex_bin = _resolve_codex_bin(env)
        if codex_bin is None:
            raise ExtractionBackendError("codex", "codex binary not found")
        rdir = Path(records_dir) if records_dir else default_records_dir()
        argv = build_codex_extraction_argv(prompt=prompt, records_dir=rdir)
        return argv, codex_bin
    if backend == "kimi":
        kimi_bin = _resolve_kimi_bin(env)
        if kimi_bin is None:
            raise ExtractionBackendError("kimi", "kimi binary not found")
        argv = build_kimi_extraction_argv(prompt=prompt, cwd=cwd)
        return argv, kimi_bin
    if backend == "grok":
        grok_bin = _resolve_grok_bin(env)
        if grok_bin is None:
            raise ExtractionBackendError("grok", "grok binary not found")
        rdir = Path(records_dir) if records_dir else default_records_dir()
        repo_root = str(rdir.parent)
        argv = build_grok_extraction_argv(prompt=prompt, cwd=repo_root)
        return argv, grok_bin
    argv = build_extraction_argv(prompt=prompt, cwd=cwd)
    claude_bin = _resolve_claude_bin(env)
    return argv, claude_bin


def trigger_extraction(
    *, project: str, cwd: str, transcript_path: str | None = None, records_dir: Path | None = None,
    branch: str | None = None, force: bool = False, reset_watermark: bool = False,
    max_messages: int | None = None,
) -> dict:
    from persistent_memory.extraction_prompt import build_extraction_prompt

    cwd = _checked_cwd(cwd)
    with _extraction_lock:
        _prune_finished_extractions()
        if project in _extraction_procs:
            return {"status": EXTRACTION_RUNNING_STATUS, "project": project}
        slice_info = None
        if transcript_path:
            try:
                slice_info = prepare_extraction_input(
                    transcript_path=transcript_path,
                    records_dir=records_dir,
                    force=force,
                    reset_watermark=reset_watermark,
                    max_messages=max_messages,
                )
            except TranscriptPathError:
                logger.warning("extraction transcript path rejected: %s", transcript_path, exc_info=True)
                slice_info = None
                transcript_path = None
            except Exception:
                logger.warning("extraction slice preparation failed: %s", transcript_path, exc_info=True)
                slice_info = None
        if slice_info is not None and slice_info["new_count"] == 0:
            if slice_info["is_baseline"]:
                _write_watermark(Path(slice_info["wm_path"]), slice_info["total"])
                return {"status": EXTRACTION_BASELINE_STATUS, "project": project, "total": slice_info["total"]}
            return {"status": EXTRACTION_NO_NEW_STATUS, "project": project, "total": slice_info["total"]}
        prompt = build_extraction_prompt(project=project, cwd=cwd or "", records_dir=records_dir, branch=branch)
        if slice_info is not None:
            prompt = f"{prompt}\nNEW messages to process are in this file (open it with Read; process ONLY these): {slice_info['slice_path']}\n"
            existing = _existing_similar_records(slice_info["slice_path"], records_dir)
            if existing:
                prompt = (
                    f"{prompt}\nEXISTING RELATED RECORDS — if a decision/lesson you extract is "
                    "ESSENTIALLY THE SAME as one of these, DO NOT create a new record (already "
                    "captured, skip it); only write what is genuinely new:\n" + "\n".join(existing) + "\n"
                )
        elif transcript_path:
            prompt = f"{prompt}\nTranscript file for this session (open it with Read): {transcript_path}\n"
        backend = _extraction_backend_for(transcript_path)
        env = _extraction_env()
        try:
            argv, executable = _build_argv_for_backend(
                backend, prompt=prompt, cwd=cwd or "", records_dir=records_dir, env=env
            )
        except ExtractionBackendError as exc:
            logger.warning(
                "extraction backend unavailable for host=%s project=%s: %s",
                exc.backend,
                project,
                exc,
            )
            return {
                "status": EXTRACTION_BACKEND_UNAVAILABLE_STATUS,
                "project": project,
                "backend": exc.backend,
            }
        log_path = _extraction_log_path(records_dir, project)
        log_handle = open(log_path, "w", encoding="utf-8")
        try:
            proc_cwd = cwd or None
            if backend in {"codex", "grok"} and records_dir is not None:
                proc_cwd = str(Path(records_dir).parent)
            proc = subprocess.Popen(
                argv,
                executable=executable,
                cwd=proc_cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        _extraction_procs[project] = (proc, time.monotonic())
        if slice_info is not None:
            _write_watermark(Path(slice_info["wm_path"]), slice_info.get("watermark_after", slice_info["total"]))
        bump_metric(EXTRACTION_STARTED_METRIC)
        result = {
            "status": EXTRACTION_STARTED_STATUS,
            "project": project,
            "log": str(log_path),
            "backend": backend,
        }
        if slice_info is not None:
            result["new_messages"] = slice_info["new_count"]
            result["total"] = slice_info["total"]
            result["watermark_after"] = slice_info.get("watermark_after", slice_info["total"])
            result["complete"] = bool(slice_info.get("complete", True))
        return result
