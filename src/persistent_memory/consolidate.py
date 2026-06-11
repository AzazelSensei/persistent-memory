"""Graph-driven consolidation of the unified memory corpus.

Reads the graph.json produced by a graphify build over the corpus and turns
graph structure into maintenance signals: cross-community "surprise" edges
become supersession candidates, low-degree nodes become knowledge gaps, and
high-degree "god" nodes earn a salience boost. Can also trigger the headless
graphify rebuild itself.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph
from pydantic import BaseModel

SURPRISE_SCORE_THRESHOLD = 0.66
THIN_DEGREE_THRESHOLD = 2
ORPHAN_DEGREE_THRESHOLD = 1
GOD_SALIENCE_BOOST = 0.15
MAX_SALIENCE = 1.0
DEFAULT_TOP_GODS = 5
GRAPHIFY_OUT_DIRNAME = "graphify-out"
GRAPH_FILENAME = "graph.json"
CLAUDE_BUILD_PROMPT = "/graphify {root} --update"
CLAUDE_OUTPUT_FORMAT = "json"
CLAUDE_PERMISSION_MODE = "bypassPermissions"
GRAPHIFY_TIMEOUT_SECONDS = 600


class GraphNotBuiltError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphSignal:
    graph: nx.Graph

    @classmethod
    def from_graph_json(cls, graph_path: Path) -> "GraphSignal":
        path = Path(graph_path)
        if not path.exists():
            raise FileNotFoundError(f"graph.json not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            graph = json_graph.node_link_graph(raw, edges="links")
        except TypeError:
            graph = json_graph.node_link_graph(raw)
        return cls(graph=graph)

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def label_of(self, node_id: str) -> str:
        return self.graph.nodes[node_id].get("label", node_id)

    def neighbors(self, node_id: str) -> list[str]:
        if node_id not in self.graph:
            return []
        return list(self.graph.neighbors(node_id))

    def community_of(self, node_id: str) -> int | None:
        if node_id not in self.graph:
            return None
        return self.graph.nodes[node_id].get("community")

    def shortest_path(self, source: str, target: str) -> list[str]:
        if source not in self.graph or target not in self.graph:
            return []
        if not nx.has_path(self.graph, source, target):
            return []
        return nx.shortest_path(self.graph, source, target)

    def _record_id_of(self, node_id: str) -> str | None:
        source_file = self.graph.nodes[node_id].get("source_file", "")
        if not source_file:
            return None
        return Path(source_file).stem

    def _seed_nodes_for(self, record_id: str) -> list[str]:
        return [n for n in self.graph if self._record_id_of(n) == record_id]

    def ranked_ids_for(self, seed: str) -> list[str]:
        seed_nodes = self._seed_nodes_for(seed)
        if not seed_nodes:
            return []
        ordered_nodes = list(
            nx.bfs_tree(self.graph, seed_nodes[0]).nodes(),
        )
        ranked: list[str] = []
        for node_id in ordered_nodes:
            record_id = self._record_id_of(node_id)
            if record_id is None or record_id in ranked:
                continue
            ranked.append(record_id)
        return ranked


class GodNode(BaseModel):
    id: str
    label: str
    degree: int


class SurpriseEdge(BaseModel):
    node_a: str
    node_b: str
    relation: str = ""
    score: float = 0.0
    source_files: list[str] = []


class GapNode(BaseModel):
    id: str
    label: str
    degree: int


class GraphAnalysis(BaseModel):
    communities: dict[int, list[str]] = {}
    gods: list[GodNode] = []
    surprises: list[SurpriseEdge] = []
    knowledge_gaps: list[GapNode] = []


def _communities_from_graph(graph: nx.Graph) -> dict[int, list[str]]:
    communities: dict[int, list[str]] = {}
    for node_id, data in graph.nodes(data=True):
        community = data.get("community")
        if community is None:
            continue
        communities.setdefault(int(community), []).append(node_id)
    return communities


def _gods_from_graph(graph: nx.Graph, top_n: int = DEFAULT_TOP_GODS) -> list[GodNode]:
    ranked = sorted(graph.degree(), key=lambda item: item[1], reverse=True)
    gods: list[GodNode] = []
    for node_id, degree in ranked[:top_n]:
        if degree == 0:
            continue
        gods.append(GodNode(
            id=node_id,
            label=graph.nodes[node_id].get("label", node_id),
            degree=degree,
        ))
    return gods


def _surprises_from_graph(graph: nx.Graph) -> list[SurpriseEdge]:
    surprises: list[SurpriseEdge] = []
    for source, target, data in graph.edges(data=True):
        community_a = graph.nodes[source].get("community")
        community_b = graph.nodes[target].get("community")
        if community_a is None or community_b is None or community_a == community_b:
            continue
        source_file = data.get("source_file")
        surprises.append(SurpriseEdge(
            node_a=graph.nodes[source].get("label", source),
            node_b=graph.nodes[target].get("label", target),
            relation=data.get("relation", ""),
            score=float(data.get("confidence_score", 0.0)),
            source_files=[source_file] if source_file else [],
        ))
    return surprises


def _knowledge_gaps_from_graph(graph: nx.Graph) -> list[GapNode]:
    gaps: list[GapNode] = []
    for node_id, degree in graph.degree():
        if degree >= THIN_DEGREE_THRESHOLD:
            continue
        gaps.append(GapNode(
            id=node_id,
            label=graph.nodes[node_id].get("label", node_id),
            degree=degree,
        ))
    return gaps


def parse_analysis(graph_path: Path) -> GraphAnalysis:
    signal = GraphSignal.from_graph_json(graph_path)
    graph = signal.graph
    return GraphAnalysis(
        communities=_communities_from_graph(graph),
        gods=_gods_from_graph(graph),
        surprises=_surprises_from_graph(graph),
        knowledge_gaps=_knowledge_gaps_from_graph(graph),
    )


def _record_id_from_node(signal: GraphSignal, node_id: str) -> str | None:
    if node_id not in signal.graph:
        return None
    source_file = signal.graph.nodes[node_id].get("source_file", "")
    if not source_file:
        return None
    return Path(source_file).stem


def boost_salience_from_gods(
    analysis: GraphAnalysis,
    signal: GraphSignal,
    current_salience: dict[str, float],
) -> dict[str, float]:
    updated: dict[str, float] = {}
    for god in analysis.gods:
        record_id = _record_id_from_node(signal, god.id)
        if record_id is None or record_id not in current_salience:
            continue
        boosted = min(current_salience[record_id] + GOD_SALIENCE_BOOST, MAX_SALIENCE)
        updated[record_id] = boosted
    return updated


class KnowledgeGap(BaseModel):
    node_id: str
    label: str
    degree: int
    source_file: str = ""


def flag_knowledge_gaps(signal: GraphSignal) -> list[KnowledgeGap]:
    gaps = []
    for node_id, degree in signal.graph.degree():
        if degree > ORPHAN_DEGREE_THRESHOLD:
            continue
        data = signal.graph.nodes[node_id]
        gaps.append(KnowledgeGap(
            node_id=node_id,
            label=data.get("label", node_id),
            degree=degree,
            source_file=data.get("source_file", ""),
        ))
    return gaps


class SupersessionCandidate(BaseModel):
    source_label: str
    target_label: str
    relation: str
    score: float
    source_files: list[str] = []


def map_surprises_to_supersession_candidates(
    analysis: GraphAnalysis,
) -> list[SupersessionCandidate]:
    candidates = []
    for surprise in analysis.surprises:
        if surprise.score < SURPRISE_SCORE_THRESHOLD:
            continue
        candidates.append(SupersessionCandidate(
            source_label=surprise.node_a,
            target_label=surprise.node_b,
            relation=surprise.relation,
            score=surprise.score,
            source_files=surprise.source_files,
        ))
    return candidates


def run_full_build(corpus_root: Path) -> subprocess.CompletedProcess:
    prompt = CLAUDE_BUILD_PROMPT.format(root=corpus_root)
    cmd = [
        "claude", "-p", prompt,
        "--permission-mode", CLAUDE_PERMISSION_MODE,
        "--output-format", CLAUDE_OUTPUT_FORMAT,
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=GRAPHIFY_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"full build failed: {result.stderr}")
    return result


class ConsolidationResult(BaseModel):
    supersession_candidates: list[SupersessionCandidate]
    knowledge_gaps: list[KnowledgeGap]
    salience_updates: dict[str, float]

    model_config = {"arbitrary_types_allowed": True}


def run_consolidation(
    corpus_root: Path,
    current_salience: dict[str, float],
    should_full_build: bool,
) -> ConsolidationResult:
    out_dir = Path(corpus_root) / GRAPHIFY_OUT_DIRNAME
    graph_path = out_dir / GRAPH_FILENAME
    if should_full_build:
        run_full_build(corpus_root)
    elif not graph_path.exists():
        raise GraphNotBuiltError(
            f"no existing graph to reuse, full build required: {graph_path}"
        )
    signal = GraphSignal.from_graph_json(graph_path)
    analysis = parse_analysis(graph_path)
    return ConsolidationResult(
        supersession_candidates=map_surprises_to_supersession_candidates(analysis),
        knowledge_gaps=flag_knowledge_gaps(signal),
        salience_updates=boost_salience_from_gods(
            analysis=analysis, signal=signal, current_salience=current_salience,
        ),
    )
