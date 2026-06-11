"""Read-only MCP server — a thin stdio wrapper over the running daemon's HTTP API.

Lets an agent ACTIVELY query memory (search/get/list/provenance); it complements
the passive recall injection done by the hooks. No writes — accept/reject/extract
stay in the daemon. Reuses the daemon's loaded index (the embedding model is not
loaded a second time).

Run (from a Claude Code / Codex MCP config):
    <venv>/bin/python -m persistent_memory.mcp_server
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

DAEMON_BASE_URL = os.environ.get("PM_DAEMON_URL", "http://127.0.0.1:37778")
HTTP_TIMEOUT_SECONDS = 5.0
DEFAULT_TOP_K = 5
DEFAULT_RECENT_LIMIT = 10
DAEMON_DOWN_MSG = (
    "persistent-memory daemon is not responding (127.0.0.1:37778). "
    "Check it with `python -m persistent_memory.doctor` or install.sh."
)

mcp = FastMCP("persistent-memory")


def _get(path: str, params: dict | None = None) -> dict:
    response = httpx.get(
        f"{DAEMON_BASE_URL}{path}", params=params or {}, timeout=HTTP_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.json()


@mcp.tool()
def search_memory(query: str, top_k: int = DEFAULT_TOP_K) -> str:
    """Retrieve past DECISIONS (D-####) and LESSONS (L-####) via hybrid semantic + keyword search (all projects).

    Use when: during a task you wonder "what did we decide / learn about this before",
    or when the recall block injected at session start is not enough.
    query: topic to search for (e.g. "database choice", "extraction cost", "auth bug").
    top_k: number of results (default 5).
    Each returned line: [ID] title (project) — score. Use get_record(ID) for the full content.
    """
    try:
        data = _get("/api/search", {"q": query, "top_k": top_k})
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    results = data.get("results", [])
    if not results:
        return f"No results for '{query}'."
    lines = [
        f"- [{r.get('id')}] {r.get('title') or ''} ({r.get('project') or ''}) "
        f"— score {round(float(r.get('score') or 0.0), 3)}"
        for r in results
    ]
    return "\n".join(lines)


@mcp.tool()
def get_record(record_id: str) -> str:
    """Fetch the FULL markdown body of a record (Context/Decision/Rationale/Outcome + source quote).

    record_id: e.g. "D-0042" (decision) or "L-0017" (lesson).
    """
    try:
        data = _get(f"/api/records/{record_id}/raw")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 422):
            return f"Record not found: {record_id}"
        return DAEMON_DOWN_MSG
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    return data.get("body") or f"Empty record: {record_id}"


@mcp.tool()
def list_recent(record_type: str | None = None, limit: int = DEFAULT_RECENT_LIMIT) -> str:
    """List the most recently recorded decisions/lessons (by date, newest -> oldest).

    record_type: "decision" | "lesson" | None (all).
    limit: number of records (default 10).
    """
    params: dict = {"titles": "true"}
    if record_type:
        params["type"] = record_type
    try:
        data = _get("/api/records", params)
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    records = sorted(
        data.get("records", []), key=lambda r: str(r.get("date") or ""), reverse=True
    )[:limit]
    if not records:
        return "No records."
    return "\n".join(
        f"- [{r.get('id')}] {r.get('title') or ''} "
        f"({r.get('project') or ''}, {r.get('date') or ''}, {r.get('status') or ''})"
        for r in records
    )


@mcp.tool()
def get_record_provenance(record_id: str) -> str:
    """Fetch the ORIGINAL transcript quotes a record is based on (reason-preserving / auditable source).

    Use when: you want to verify what a decision was actually based on.
    record_id: e.g. "D-0042".
    """
    try:
        data = _get(f"/api/records/{record_id}/source")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 422):
            return f"Record not found: {record_id}"
        return DAEMON_DOWN_MSG
    except httpx.HTTPError:
        return DAEMON_DOWN_MSG
    passages = data.get("passages", [])
    if not passages:
        return f"No source quotes for {record_id}."
    return "\n\n".join(
        f"[{p.get('time') or ''}] (score {p.get('score')})\n{p.get('text') or ''}"
        for p in passages
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
