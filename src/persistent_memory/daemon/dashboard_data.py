"""Builds the JSON payload embedded into the single-page dashboard (app.html)."""

import datetime
import json
import re
from pathlib import Path

from persistent_memory.daemon import services
from persistent_memory.daemon.config import (
    DECISIONS_DIRNAME,
    GRAPHIFY_OUT_DIRNAME,
    LESSONS_DIRNAME,
)

GRAPH_JSON_FILENAME = "graph.json"
# Bilingual: new records title the provenance section "Source", older corpora
# use the Turkish "Kaynak".
SOURCE_HEADING_PREFIXES = ("Kaynak", "Source")
UI_STATUS_ALIASES = {"reverted-as-mistake": "reverted"}
DECISION_SECTION_KEYS = ("context", "decision", "rationale", "outcome")
LESSON_SECTION_KEYS = ("what", "why", "when", "rule")
PALETTE = (
    "#22d3ee", "#9d8cff", "#3ddc97", "#f5b13d", "#ff6b81", "#4fd1c5", "#e879f9",
    "#60a5fa", "#fbbf24", "#34d399", "#f472b6", "#a78bfa", "#2dd4bf", "#fb923c",
)
RELATED_LIMIT = 6
REF_RE = re.compile(r"\[\[([DLP]-\d{4})(?:\|[^\]]*)?\]\]")
RELATED_SIDECAR_NAME = "relationships.json"
HEALTH_PAIRS_NAME = "health_pairs.json"
ACTIVITY_LIMIT = 8
UNEXPECTED_LIMIT = 10
STALE_AGE_DAYS = 90


def _ui_status(status: str | None) -> str:
    return UI_STATUS_ALIASES.get(status or "", status or "proposed")


def _kind_from_id(record_id: str) -> str:
    return "lesson" if record_id.startswith("L") else "decision"


def _short_id(record_id: str) -> str:
    prefix, _, number = record_id.partition("-")
    return f"{prefix}{int(number)}" if number.isdigit() else record_id


def _section_keys(kind: str) -> tuple[str, ...]:
    return LESSON_SECTION_KEYS if kind == "lesson" else DECISION_SECTION_KEYS


def split_record_sections(body: str, kind: str) -> tuple[list[dict], dict | None]:
    raw = services._split_sections(body)
    source = next((s for s in raw if s["heading"].startswith(SOURCE_HEADING_PREFIXES)), None)
    content = [s for s in raw if not s["heading"].startswith(SOURCE_HEADING_PREFIXES)]
    keys = _section_keys(kind)
    sections = [
        {
            "label": section["heading"],
            "en": keys[index] if index < len(keys) else f"s{index + 1}",
            "text": section["text"],
        }
        for index, section in enumerate(content)
    ]
    return sections, source


def _date_str(value) -> str:
    text = str(value or "")
    return text[:10]


def load_related_sidecar(records_dir: Path) -> dict:
    path = Path(records_dir) / RELATED_SIDECAR_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_health_pairs(records_dir: Path) -> list:
    path = Path(records_dir) / HEALTH_PAIRS_NAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def load_graph(records_dir: Path) -> dict | None:
    path = Path(records_dir) / GRAPHIFY_OUT_DIRNAME / GRAPH_JSON_FILENAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _community_labels(graph: dict, communities: set[int]) -> dict[int, str]:
    node_community = {n["id"]: n.get("community") for n in graph.get("nodes", [])}
    hyperedges = graph.get("graph", {}).get("hyperedges", [])
    labels: dict[int, str] = {}
    for community in communities:
        members = {nid for nid, c in node_community.items() if c == community}
        best_label, best_overlap = None, 0
        for edge in hyperedges:
            overlap = len(members.intersection(edge.get("nodes", [])))
            if overlap > best_overlap:
                best_label, best_overlap = edge.get("label"), overlap
        labels[community] = best_label or f"Cluster {community + 1}"
    return labels


def build_graph_payload(graph: dict | None, records_by_id: dict) -> dict:
    empty = {"clusters": [], "nodes": [], "edges": [], "adjacency": {}}
    if not graph:
        return empty
    node_community: dict[str, int] = {}
    nodes: list[dict] = []
    for node in graph.get("nodes", []):
        record_id = node["id"]
        record = records_by_id.get(record_id)
        if record is None:
            continue
        community = node.get("community") or 0
        node_community[record_id] = community
        nodes.append(
            {
                "id": record_id,
                "label": _short_id(record_id),
                "cluster": f"c{community}",
                "status": record["status"],
                "kind": record["kind"],
                "imp": record["importance"],
                "title": record["title"],
                "project": record["project"],
            }
        )
    communities = sorted(set(node_community.values()))
    labels = _community_labels(graph, set(communities))
    clusters = [
        {"id": f"c{c}", "label": labels[c], "color": PALETTE[index % len(PALETTE)]}
        for index, c in enumerate(communities)
    ]

    edges: list[dict] = []
    adjacency: dict[str, list[tuple[str, float]]] = {}
    cross_edges: list[dict] = []
    for link in graph.get("links", []):
        source, target = link.get("source"), link.get("target")
        if source not in node_community or target not in node_community:
            continue
        conf = float(link.get("confidence_score") or link.get("weight") or 0.0)
        is_cross = node_community[source] != node_community[target]
        edge = {
            "from": source,
            "to": target,
            "type": link.get("relation") or "related",
            "conf": round(conf, 2),
            "unexpected": False,
        }
        edges.append(edge)
        if is_cross:
            cross_edges.append(edge)
        adjacency.setdefault(source, []).append((target, conf))
        adjacency.setdefault(target, []).append((source, conf))

    cross_edges.sort(key=lambda e: e["conf"], reverse=True)
    for edge in cross_edges[:UNEXPECTED_LIMIT]:
        edge["unexpected"] = True

    return {"clusters": clusters, "nodes": nodes, "edges": edges, "adjacency": adjacency}


def _body_refs(body: str, self_id: str) -> list[str]:
    refs: list[str] = []
    for match in REF_RE.finditer(body):
        rid = match.group(1)
        if rid != self_id and rid not in refs:
            refs.append(rid)
    return refs


def _build_record(record, body: str, title: str) -> dict:
    kind = "lesson" if record.type.value == "lesson" else "decision"
    sections, _source = split_record_sections(body, kind)
    supersedes = record.supersedes[0] if record.supersedes else None
    superseded_by = record.superseded_by[0] if record.superseded_by else None
    return {
        "id": record.id,
        "title": title,
        "status": _ui_status(record.status.value),
        "project": record.project,
        "date": record.date.isoformat(),
        "importance": round(float(record.salience), 2),
        "tags": list(record.tags),
        "kind": kind,
        "sections": sections,
        "source": {
            "session": record.provenance.session,
            "sessionTitle": record.project,
            "passages": [],
        },
        "relationships": {
            "supersedes": supersedes,
            "supersededBy": superseded_by,
            "related": _body_refs(body, record.id),
        },
    }


def _load_all_records(records_dir: Path) -> list[dict]:
    from persistent_memory.records import read_record

    root = Path(records_dir)
    records: list[dict] = []
    for dirname in (DECISIONS_DIRNAME, LESSONS_DIRNAME):
        directory = root / dirname
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == services.INDEX_FILENAME:
                continue
            try:
                record, body = read_record(path)
            except (ValueError, OSError):
                continue
            title = services._title_from_body(body, record.id)
            records.append(_build_record(record, body, title))
    return records


def _build_projects(records: list[dict], *, projects_root: Path, records_dir: Path) -> list[dict]:
    overview = services.project_overview(projects_root=projects_root, records_dir=records_dir)
    projects: list[dict] = []
    for index, info in enumerate(overview):
        projects.append(
            {
                "id": info["name"],
                "name": info["name"],
                "dec": info["decisions_count"],
                "les": info["lessons_count"],
                "conv": info["transcript_count"],
                "last": _date_str(info["last_activity"]),
                "color": PALETTE[index % len(PALETTE)],
            }
        )
    return projects


def _build_activity(records: list[dict]) -> list[dict]:
    ordered = sorted(records, key=lambda r: r["date"], reverse=True)[:ACTIVITY_LIMIT]
    return [
        {"t": r["date"], "kind": r["status"], "id": r["id"], "title": r["title"], "project": r["project"]}
        for r in ordered
    ]


def _build_health(records_dir: Path, records: list[dict]) -> list[dict]:
    health: list[dict] = []
    report = services.run_lint(records_dir=records_dir)
    for line in report.get("conflicts", []):
        record_id = line.split("]", 1)[-1].split(":", 1)[0].strip()
        health.append(
            {"level": "conflict", "title": "Conflict / supersession", "detail": line, "ids": [record_id]}
        )
    today = datetime.date.today()
    stale = [
        r for r in records
        if r["status"] == "proposed"
        and (today - datetime.date.fromisoformat(r["date"])).days >= STALE_AGE_DAYS
    ]
    if stale:
        health.append(
            {
                "level": "stale",
                "title": "Stale: records awaiting review for a long time",
                "detail": f"{len(stale)} 'proposed' record(s) pending for {STALE_AGE_DAYS}+ days",
                "ids": [stale[0]["id"]],
            }
        )
    for pair in load_health_pairs(records_dir):
        a, b = pair.get("a"), pair.get("b")
        is_conflict = pair.get("verdict") == "contradiction"
        health.append(
            {
                "level": "conflict" if is_conflict else "duplicate",
                "title": ("Conflict" if is_conflict else "Possible duplicate") + f": {a} ↔ {b}",
                "detail": pair.get("reason", ""),
                "ids": [a, b],
            }
        )
    return health


def _build_stats(records: list[dict], graph_payload: dict, projects: list[dict]) -> dict:
    by_status: dict[str, int] = {}
    for record in records:
        by_status[record["status"]] = by_status.get(record["status"], 0) + 1
    graph = load_graph_counts(graph_payload)
    return {
        "total": len(records),
        "loaded": len(records),
        "proposed": by_status.get("proposed", 0),
        "accepted": by_status.get("accepted", 0),
        "superseded": by_status.get("superseded", 0),
        "reverted": by_status.get("reverted", 0),
        "graphNodes": graph["nodes"],
        "graphEdges": graph["edges"],
        "clusters": graph["clusters"],
        "projects": len(projects),
    }


def load_graph_counts(graph_payload: dict) -> dict:
    return {
        "nodes": len(graph_payload["nodes"]),
        "edges": len(graph_payload["edges"]),
        "clusters": len(graph_payload["clusters"]),
    }


def build_pm_payload(cfg) -> dict:
    records = _load_all_records(cfg.records_dir)
    records_by_id = {r["id"]: r for r in records}

    graph = load_graph(cfg.records_dir)
    graph_payload = build_graph_payload(graph, records_by_id)
    graph_payload.pop("adjacency", None)
    sidecar = load_related_sidecar(cfg.records_dir)

    for record in records:
        self_id = record["id"]
        exclude = {self_id, record["relationships"]["supersedes"], record["relationships"]["supersededBy"]}
        merged = list(record["relationships"]["related"])
        for extra in sidecar.get(self_id, []):
            if extra not in merged:
                merged.append(extra)
        record["relationships"]["related"] = [
            rid for rid in merged if rid in records_by_id and rid not in exclude
        ][:RELATED_LIMIT]

    ordered = sorted(records, key=lambda r: (r["date"], r["id"]), reverse=True)
    decisions = [r for r in ordered if r["kind"] == "decision"]
    lessons = [r for r in ordered if r["kind"] == "lesson"]
    projects = _build_projects(records, projects_root=cfg.projects_root, records_dir=cfg.records_dir)

    return {
        "projects": projects,
        "decisions": decisions,
        "lessons": lessons,
        "all": ordered,
        "byId": records_by_id,
        "activity": _build_activity(records),
        "health": _build_health(cfg.records_dir, records),
        "clusters": graph_payload["clusters"],
        "nodes": graph_payload["nodes"],
        "edges": graph_payload["edges"],
        "stats": _build_stats(records, graph_payload, projects),
    }


def pm_payload_json(cfg) -> str:
    raw = json.dumps(build_pm_payload(cfg), ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
