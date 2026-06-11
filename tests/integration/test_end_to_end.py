from __future__ import annotations

import json
import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.skipif(
    os.environ.get("PM_E2E") != "1",
    reason="real services; set PM_E2E=1",
)

CLAUDE_MEM_DB = Path.home() / ".claude-mem" / "claude-mem.db"
CLAUDE_MEM_PROJECT = os.environ.get("PM_E2E_CLAUDE_MEM_PROJECT", "demo-project")
EXPECTED_EMBED_DIM = 1024
TR_QUERY = "önbellek geçersiz kılma"
LOCALHOST_BASE_URL = "http://localhost"
MAX_OBSERVATION_ROWS = 5

DECISION_BODY = (
    "## Context / Problem\n"
    "Sicak veri her istekte DB'den cekiliyordu, latency yuksekti. "
    "Dusuk gecikme isteniyordu, ek altyapi maliyeti istenmiyordu.\n\n"
    "## Decision\n"
    "Redis yerine surec ici in-memory LRU cache (onbellek) kullanmaya karar verildi.\n\n"
    "## Rationale\n"
    "Redis ek operasyon yuku getiriyordu; in-memory cache yeterli ve hizliydi.\n\n"
    "## Outcome / Learned\n"
    "Onbellek latency'yi dusurdu.\n\n"
    "## Source (transcript)\n"
    "Session: e2e-sess\n"
)


def _lesson_body(decision_id: str) -> str:
    return (
        "## What happened\n"
        "Prod'da stale read yasandi: onbellek (cache) gecersiz kilma yapilmamisti.\n\n"
        "## Why\n"
        "Sadece TTL'e guvenildi, explicit cache invalidation yoktu. "
        f"In-memory cache karari ile baglantili: [[{decision_id}]]\n\n"
        "## When discovered\n"
        "Kullanici tutarsiz veri raporlayinca.\n\n"
        "## General rule\n"
        "Onbellek gecersiz kilma TTL ile birlikte explicit yapilmali.\n\n"
        "## Source (transcript)\n"
        "Session: e2e-sess\n"
    )


class _OllamaRetrievalAdapter:
    def __init__(self, embedder, vectors_by_id: dict[str, list[float]]):
        self._embedder = embedder
        self._vectors = vectors_by_id

    def embed_query(self, text: str) -> list[float]:
        from persistent_memory.embeddings import l2_normalize

        return l2_normalize(self._embedder.embed_one(text))

    def get_vector(self, record_id: str):
        return self._vectors.get(record_id)


def _print_step(num: int, name: str, detail: str) -> None:
    print(f"\n[E2E STEP {num}] {name}\n  {detail}")


@pytest.fixture()
def localhost_testclient(monkeypatch):
    original_init = TestClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("base_url", LOCALHOST_BASE_URL)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", patched_init)


def test_full_pipeline_with_real_services(tmp_path, monkeypatch, localhost_testclient):
    from persistent_memory import graph_ingest, records
    from persistent_memory.consolidate import (
        GRAPH_FILENAME,
        GRAPHIFY_OUT_DIRNAME,
        parse_analysis,
        run_full_build,
    )
    from persistent_memory.daemon.app import create_app
    from persistent_memory.daemon.config import DaemonConfig
    from persistent_memory.embeddings import (
        OllamaEmbedder,
        VectorIndex,
        embed_record,
    )
    from persistent_memory.lint import collect_records
    from persistent_memory.recall import build_recall_block
    from persistent_memory.records import NewRecordSpec
    from persistent_memory.retriever import (
        RetrievalCandidate,
        adapt_loaded_record,
        filter_by_project,
        recency_weight,
        salience_weight,
        search,
    )
    from persistent_memory.schema import Provenance

    project = "pm-e2e"
    records_root = tmp_path / "records"
    provenance = Provenance(session="e2e-sess", cwd=str(tmp_path), agent="claude")

    # ---- STEP 1: REAL records ----
    decision_path = records.create_decision(
        records_root,
        NewRecordSpec(
            project=project,
            provenance=provenance,
            tags=["cache", "onbellek", "latency"],
            salience=0.9,
            date=date.today(),
            body=DECISION_BODY,
        ),
    )
    decision_record, _ = records.read_record(decision_path)
    lesson_path = records.create_lesson(
        records_root,
        NewRecordSpec(
            project=project,
            provenance=provenance,
            tags=["cache", "invalidation", "stale-read"],
            salience=0.8,
            date=date.today(),
            body=_lesson_body(decision_record.id),
        ),
    )
    lesson_record, _ = records.read_record(lesson_path)
    assert decision_path.exists() and lesson_path.exists()
    assert decision_record.id.startswith("D-")
    assert lesson_record.id.startswith("L-")
    _print_step(
        1,
        "REAL records",
        f"decision={decision_record.id} ({decision_path.name}), "
        f"lesson={lesson_record.id} ({lesson_path.name})",
    )

    # ---- STEP 2: REAL Ollama embedding + VectorIndex ----
    embedder = OllamaEmbedder()
    decisions_dir = records_root / "decisions"
    lessons_dir = records_root / "lessons"
    loaded = collect_records(decisions_dir) + collect_records(lessons_dir)
    views = [adapt_loaded_record(item) for item in loaded]
    assert len(views) == 2

    index = VectorIndex(tmp_path / ".index")
    vectors_by_id: dict[str, list[float]] = {}
    dims: set[int] = set()
    for view in views:
        vector = embed_record(view, embedder)
        dims.add(len(vector))
        vectors_by_id[view.id] = vector
        index.upsert(view.id, vector, content_hash=view.id)
    index.save()
    assert dims == {EXPECTED_EMBED_DIM}, f"unexpected vector dims: {dims}"
    assert len(index) == 2
    _print_step(
        2,
        "REAL Ollama embedding",
        f"model=bge-m3, dims={sorted(dims)}, indexed_ids={index.ids()}",
    )

    # ---- STEP 3: REAL retrieval (Ollama query embedding + BM25 + RRF) ----
    adapter = _OllamaRetrievalAdapter(embedder, vectors_by_id)
    now = date.today().isoformat()
    results = search(
        query=TR_QUERY,
        project=project,
        records=views,
        embedder=adapter,
        now=now,
        top_k=10,
    )
    assert results, "search returned no candidates"
    top_ids = [c.record.id for c in results]
    assert {decision_record.id, lesson_record.id}.issubset(set(top_ids)), top_ids
    assert top_ids[0] in {decision_record.id, lesson_record.id}, top_ids
    _print_step(
        3,
        "REAL retrieval (TR query)",
        f"query={TR_QUERY!r} -> top_ranked={top_ids[0]} "
        f"scores={[(c.record.id, round(c.score, 6)) for c in results]}",
    )

    # ---- STEP 4: REAL recall block ----
    def searcher(*, project: str | None, top_k: int) -> list[RetrievalCandidate]:
        scoped = filter_by_project(views, project)
        candidates = [
            RetrievalCandidate(
                record=view,
                score=recency_weight(view.date, now) * salience_weight(view),
            )
            for view in scoped
        ]
        candidates.sort(key=lambda cand: (-cand.score, cand.record.id))
        return candidates[:top_k]

    from persistent_memory.recall import DEFAULT_TOKEN_BUDGET, estimate_tokens

    recall_block = build_recall_block(project, searcher)
    assert recall_block, "recall block empty"
    assert estimate_tokens(recall_block) <= DEFAULT_TOKEN_BUDGET
    assert decision_record.id in recall_block
    assert lesson_record.id in recall_block
    _print_step(
        4,
        "REAL recall block",
        f"chars={len(recall_block)}, est_tokens={estimate_tokens(recall_block)}, "
        f"first_line={recall_block.splitlines()[0]!r}",
    )

    # ---- STEP 5: REAL claude-mem ingest (read-only) ----
    assert CLAUDE_MEM_DB.is_file(), f"claude-mem db missing: {CLAUDE_MEM_DB}"
    ro_conn = sqlite3.connect(f"file:{CLAUDE_MEM_DB}?mode=ro", uri=True)
    try:
        since_row = ro_conn.execute(
            "SELECT created_at_epoch FROM observations WHERE project = ? "
            "ORDER BY created_at_epoch DESC LIMIT 1 OFFSET ?",
            (CLAUDE_MEM_PROJECT, MAX_OBSERVATION_ROWS - 1),
        ).fetchone()
    finally:
        ro_conn.close()
    since_epoch = int(since_row[0]) if since_row else 0

    rows = graph_ingest.pull_observations(
        str(CLAUDE_MEM_DB), project=CLAUDE_MEM_PROJECT, since_epoch=since_epoch
    )
    assert rows, "no observations pulled"
    assert len(rows) <= MAX_OBSERVATION_ROWS + 2, f"pulled too many: {len(rows)}"

    write_conn = graph_ingest.open_claudemem_db(str(CLAUDE_MEM_DB))
    try:
        with pytest.raises(sqlite3.OperationalError):
            write_conn.execute(
                "UPDATE observations SET title = title WHERE id = ?",
                (rows[0]["id"],),
            )
    finally:
        write_conn.close()

    observations_dir = tmp_path / "corpus" / "observations"
    ledger_path = tmp_path / "corpus" / ".dedup_ledger.json"
    written = graph_ingest.export_observations(
        str(CLAUDE_MEM_DB),
        project=CLAUDE_MEM_PROJECT,
        out_dir=str(observations_dir),
        ledger_path=str(ledger_path),
        since_epoch=since_epoch,
    )
    assert written, "no observation md files written"
    md_files = sorted(observations_dir.glob("*.md"))
    assert md_files, "no .md observation files produced"
    _print_step(
        5,
        "REAL claude-mem ingest (read-only)",
        f"project={CLAUDE_MEM_PROJECT}, since_epoch={since_epoch}, "
        f"pulled={len(rows)}, exported_md={len(md_files)}, "
        f"write_blocked=True, sample={md_files[0].name}",
    )

    # ---- STEP 6: unified corpus (SYMLINKS) + REAL headless consolidation ----
    corpus_root = tmp_path / "corpus" / "unified"
    linked = graph_ingest.build_unified_corpus(
        corpus_root=str(corpus_root),
        decisions_dir=str(decisions_dir),
        lessons_dir=str(lessons_dir),
        observations_dir=str(observations_dir),
    )
    assert linked, "no files linked into unified corpus"
    symlink_names = sorted(p.name for p in linked)
    assert all((corpus_root / name).is_symlink() for name in symlink_names)
    assert f"{decision_record.id}.md" in symlink_names
    assert f"{lesson_record.id}.md" in symlink_names

    # graphify writes graphify-out/ into the process cwd; point cwd at corpus_root
    # so consolidate.run_consolidation/parse_analysis can find the graph.
    monkeypatch.chdir(corpus_root)
    build_result = run_full_build(corpus_root)
    assert build_result.returncode == 0

    graph_path = corpus_root / GRAPHIFY_OUT_DIRNAME / GRAPH_FILENAME
    assert graph_path.exists(), f"graph.json not produced at {graph_path}"
    raw_graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_nodes = raw_graph.get("nodes", [])
    source_files = {n.get("source_file", "") for n in graph_nodes}
    decision_in_graph = any(
        decision_record.id in sf or Path(sf).name == f"{decision_record.id}.md"
        for sf in source_files
    )
    lesson_in_graph = any(
        lesson_record.id in sf or Path(sf).name == f"{lesson_record.id}.md"
        for sf in source_files
    )

    analysis = parse_analysis(graph_path)
    cross_community_surprises = [
        (s.node_a, s.node_b, s.relation, s.score) for s in analysis.surprises
    ]
    _print_step(
        6,
        "unified corpus (symlinks) + REAL graphify consolidation",
        f"linked={len(linked)} ({symlink_names}); "
        f"graph_node_count={len(graph_nodes)}; "
        f"decision_in_graph={decision_in_graph}; lesson_in_graph={lesson_in_graph}; "
        f"communities={ {k: len(v) for k, v in analysis.communities.items()} }; "
        f"gods={[(g.label, g.degree) for g in analysis.gods]}; "
        f"surprises={cross_community_surprises}; "
        f"source_files={sorted(source_files)}",
    )
    assert graph_nodes, "graph.json has zero nodes — graphify produced empty graph"
    assert decision_in_graph and lesson_in_graph, (
        "SYMLINK BUG: graphify did not pick up symlinked records — "
        f"source_files={sorted(source_files)}"
    )
    assert analysis.communities, "no communities computed"
    assert analysis.gods, "no god nodes computed"
    assert analysis.surprises, "no cross-community surprise edges found"

    # ---- STEP 7: REAL daemon via TestClient ----
    cfg = DaemonConfig(records_dir=records_root, watch_enabled=False)
    app = create_app(records_dir=records_root, config=cfg)
    client = TestClient(app)
    with client:
        health = client.get("/api/health")
        assert health.status_code == 200, health.text
        health_body = health.json()
        assert health_body["status"] == "ok"
        assert health_body["decisions_count"] == 1
        assert health_body["lessons_count"] == 1

        search_resp = client.get("/api/search", params={"q": TR_QUERY})
        search_body = search_resp.json()

        recall_resp = client.get("/api/recall", params={"project": project})
        recall_body = recall_resp.json()

    _print_step(
        7,
        "REAL daemon (TestClient)",
        f"/api/health={health.status_code} {health_body}; "
        f"/api/search={search_resp.status_code} body={search_body}; "
        f"/api/recall={recall_resp.status_code} "
        f"block_len={len(recall_body.get('block', '')) if recall_resp.status_code == 200 else 'n/a'}",
    )
    assert search_resp.status_code == 200, search_resp.text
    returned_ids = {r["id"] for r in search_body.get("results", [])}
    assert {decision_record.id, lesson_record.id} & returned_ids, search_body
    assert recall_resp.status_code == 200, recall_resp.text
    assert recall_body.get("block"), "recall endpoint returned empty block"
    assert decision_record.id in recall_body["block"]
