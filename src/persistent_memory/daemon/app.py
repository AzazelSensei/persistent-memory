"""FastAPI app factory for the persistent-memory daemon.

Endpoint inventory (paths are part of the public contract — hooks and the
MCP server call them; never rename):

Read-only JSON (no token):
    GET /api/health, /api/metrics, /api/records, /api/candidates,
        /api/supersession-candidates, /api/recall, /api/prompt-recall,
        /api/search, /api/projects, /api/projects/{project},
        /api/records/{id}/source, /api/records/{id}/raw

Mutating JSON (require X-PM-Token):
    POST /api/records (create decision or lesson on demand),
         /api/records/{id}/body, /api/records/accept-all,
         /api/records/{id}/accept, /api/records/{id}/reject,
         /api/records/{old}/supersede-by/{new}, /api/consolidate,
         /api/extract, /api/supersession-candidates/dismiss

HTML dashboard:
    GET /, /app, /legacy, /decisions, /lessons, /records/{id}, /projects,
        /projects/{project}, /timeline, /search, /health, /graph

Security model: the daemon binds to loopback only and TrustedHostMiddleware
rejects foreign Host headers (DNS-rebinding guard). Mutations require a
random per-install token sent in the X-PM-Token header; browsers never send
custom headers cross-site, so this doubles as CSRF protection.
"""

import asyncio
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

import json

from persistent_memory import i18n as _i18n
from persistent_memory.daemon import dashboard_data, services
from persistent_memory.daemon.config import (
    DECISIONS_DIRNAME,
    HEARTBEAT_MESSAGE_THRESHOLD,
    LESSONS_DIRNAME,
    DaemonConfig,
)
from persistent_memory.daemon.services import (
    ACCEPTED_STATUS,
    PROPOSED_STATUS,
    REJECTED_STATUS,
    count_markdown,
    filter_by_status,
    filter_by_type,
    list_records,
    list_records_with_titles,
    sort_by_date_desc,
)
from persistent_memory.daemon.token import load_or_create_token
from persistent_memory.daemon.watcher import HeartbeatCounter, RecordChangeHandler
from persistent_memory.schema import ID_PATTERN

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
TOKEN_HEADER = "X-PM-Token"
SEARCH_TOP_K_MIN = 1
SEARCH_TOP_K_MAX = 50
HTTP_ACCEPTED = 202
RECENT_LIMIT = 8
SOURCE_TIME_START = 11
SOURCE_TIME_END = 16


def _passage_time(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    if "T" in timestamp:
        return timestamp.split("T", 1)[1][:5]
    if len(timestamp) >= SOURCE_TIME_END:
        return timestamp[SOURCE_TIME_START:SOURCE_TIME_END]
    return timestamp


class ExtractRequest(BaseModel):
    project: str
    cwd: str | None = None
    transcript_path: str | None = None
    session_id: str | None = None
    flush: bool | None = None
    reason: str | None = None


class BodyUpdate(BaseModel):
    body: str


class DismissCandidateRequest(BaseModel):
    source_id: str | None = None
    source_label: str | None = None
    target_id: str | None = None
    target_label: str | None = None


ALLOWED_RECORD_TYPES = {"decision", "lesson"}
DEFAULT_SESSION = "manual"
DEFAULT_CWD = ""
DEFAULT_AGENT = "api"


class CreateRecordRequest(BaseModel):
    type: str
    title: str
    project: str
    body: str | None = None
    tags: list[str] = []
    salience: float = 0.5
    session: str | None = None
    cwd: str | None = None
    agent: str | None = None


def _start_observer(cfg: DaemonConfig, loop: asyncio.AbstractEventLoop):
    from watchdog.observers import Observer

    heartbeat = HeartbeatCounter(threshold=HEARTBEAT_MESSAGE_THRESHOLD)

    def on_consolidate() -> None:
        loop.call_soon_threadsafe(
            lambda: asyncio.ensure_future(_run_consolidation_async(cfg))
        )

    handler = RecordChangeHandler(
        records_dir=cfg.records_dir,
        heartbeat=heartbeat,
        on_consolidate=on_consolidate,
    )
    observer = Observer()
    for dirname in (DECISIONS_DIRNAME, LESSONS_DIRNAME):
        watched = cfg.records_dir / dirname
        if not watched.is_dir():
            continue
        observer.schedule(handler, str(watched), recursive=False)
    observer.start()
    return observer


async def _run_consolidation_async(cfg: DaemonConfig) -> None:
    await asyncio.to_thread(
        services.run_consolidation, records_dir=cfg.records_dir, cluster_only=True
    )


def create_app(records_dir: Path, config: DaemonConfig | None = None) -> FastAPI:
    cfg = config or DaemonConfig(records_dir=Path(records_dir))
    token = load_or_create_token(cfg.records_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        observer = None
        if cfg.watch_enabled:
            observer = _start_observer(cfg, asyncio.get_running_loop())
        try:
            yield
        finally:
            if observer is not None:
                observer.stop()
                observer.join()

    app = FastAPI(title="persistent-memory daemon", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.state.config = cfg
    app.state.token = token
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates = templates

    if cfg.graphify_out_dir.exists():
        app.mount("/static/graph", StaticFiles(directory=str(cfg.graphify_out_dir)), name="graph")
    pm_static = STATIC_DIR / "pm"
    if pm_static.is_dir():
        app.mount("/static/pm", StaticFiles(directory=str(pm_static)), name="pm-static")

    def require_token(x_pm_token: str | None = Header(default=None)) -> None:
        # Custom header + constant-time compare; see module docstring for the
        # loopback/CSRF reasoning.
        if x_pm_token is None or not secrets.compare_digest(x_pm_token, token):
            raise HTTPException(status_code=403, detail="invalid or missing token")

    def all_records() -> list[dict]:
        return list_records([cfg.decisions_dir, cfg.lessons_dir])

    @app.get("/api/health")
    def get_health():
        return {
            "status": "ok",
            "host": cfg.host,
            "port": cfg.port,
            "decisions_count": count_markdown(cfg.decisions_dir),
            "lessons_count": count_markdown(cfg.lessons_dir),
        }

    @app.get("/api/metrics")
    def get_metrics():
        body = services.metrics_snapshot()
        body["records_total"] = count_markdown(cfg.decisions_dir) + count_markdown(cfg.lessons_dir)
        return body

    @app.get("/api/records")
    def get_records(
        type: str | None = Query(default=None),
        titles: bool = Query(default=False),
    ):
        records = (
            list_records_with_titles([cfg.decisions_dir, cfg.lessons_dir])
            if titles
            else all_records()
        )
        if type:
            records = filter_by_type(records, type)
        return {"records": records}

    @app.post("/api/records", status_code=201, dependencies=[Depends(require_token)])
    def post_create_record(payload: CreateRecordRequest):
        from persistent_memory.records import (
            NewRecordSpec,
            create_decision,
            create_lesson,
            decision_body_template,
            lesson_body_template,
        )
        from persistent_memory.schema import Provenance

        if payload.type not in ALLOWED_RECORD_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"invalid type '{payload.type}': must be 'decision' or 'lesson'",
            )
        provenance = Provenance(
            session=payload.session or DEFAULT_SESSION,
            cwd=payload.cwd or DEFAULT_CWD,
            agent=payload.agent or DEFAULT_AGENT,
        )
        title_prefix = f"# {payload.title}\n\n"
        if payload.body is not None:
            body_text = title_prefix + payload.body
        else:
            template = decision_body_template() if payload.type == "decision" else lesson_body_template()
            body_text = title_prefix + template
        spec = NewRecordSpec(
            project=payload.project,
            provenance=provenance,
            tags=list(payload.tags),
            salience=payload.salience,
            body=body_text,
        )
        if payload.type == "decision":
            path = create_decision(cfg.records_dir, spec)
            record_type = "decision"
        else:
            path = create_lesson(cfg.records_dir, spec)
            record_type = "lesson"
        record_id = path.stem
        return {"id": record_id, "path": str(path), "type": record_type}

    @app.get("/api/candidates")
    def get_candidates():
        return {"candidates": filter_by_status(all_records(), PROPOSED_STATUS)}

    @app.get("/api/supersession-candidates")
    def get_supersession_candidates():
        return {
            "candidates": services.list_supersession_candidates(records_dir=cfg.records_dir)
        }

    @app.post("/api/supersession-candidates/dismiss", dependencies=[Depends(require_token)])
    def post_dismiss_candidate(payload: DismissCandidateRequest):
        source = payload.source_id or payload.source_label
        target = payload.target_id or payload.target_label
        if not source or not target:
            raise HTTPException(
                status_code=422, detail="source and target are required (id or label)"
            )
        return services.dismiss_supersession_candidate(
            records_dir=cfg.records_dir, source=source, target=target
        )

    @app.get("/api/recall")
    def get_recall(project: str | None = Query(default=None)):
        return {"block": services.run_recall(records_dir=cfg.records_dir, project=project)}

    @app.get("/api/prompt-recall")
    def get_prompt_recall(
        q: str = Query(...),
        project: str | None = Query(default=None),
        budget: int = Query(default=services.PROMPT_RECALL_BUDGET_TOKENS),
    ):
        try:
            block = services.run_prompt_recall(
                q, records_dir=cfg.records_dir, project=project, budget=budget
            )
        except Exception:
            block = ""
        return {"block": block}

    @app.get("/api/search")
    def get_search(
        q: str = Query(...),
        top_k: int = Query(default=services.DEFAULT_TOP_K, ge=SEARCH_TOP_K_MIN, le=SEARCH_TOP_K_MAX),
    ):
        results = services.run_search(q, records_dir=cfg.records_dir, top_k=top_k)
        return {"query": q, "results": results}

    @app.get("/api/projects")
    def get_projects():
        return {
            "projects": services.project_overview(
                projects_root=cfg.projects_root, records_dir=cfg.records_dir
            )
        }

    @app.get("/api/projects/{project}")
    def get_project(project: str):
        return services.project_detail(
            project=project, projects_root=cfg.projects_root, records_dir=cfg.records_dir
        )

    @app.get("/api/records/{record_id}/source")
    def get_record_source(record_id: str):
        if not ID_PATTERN.match(record_id):
            raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")
        try:
            detail = services.record_detail(
                cfg.records_dir, record_id, transcript_index_dir=cfg.transcript_index_path
            )
        except (FileNotFoundError, KeyError):
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        passages = [
            {
                "score": round(float(passage.get("score") or 0.0), 2),
                "time": _passage_time(passage.get("timestamp")),
                "text": passage.get("text") or "",
            }
            for passage in detail.get("source_passages", [])
        ]
        return {"passages": passages}

    @app.get("/api/records/{record_id}/raw")
    def get_record_raw(record_id: str):
        from persistent_memory.records import read_record_by_id

        if not ID_PATTERN.match(record_id):
            raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")
        try:
            _, body = read_record_by_id(cfg.records_dir, record_id)
        except (FileNotFoundError, KeyError, ValueError):
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        return {"id": record_id, "body": body}

    @app.post("/api/records/{record_id}/body", dependencies=[Depends(require_token)])
    def post_record_body(record_id: str, payload: BodyUpdate):
        from persistent_memory.records import ImmutableRecordError, write_body

        if not ID_PATTERN.match(record_id):
            raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")
        try:
            write_body(cfg.records_dir, record_id, payload.body)
        except ImmutableRecordError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except (FileNotFoundError, KeyError, ValueError):
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        return {"id": record_id, "saved": True}

    def change_status(record_id: str, status: str) -> dict:
        if not ID_PATTERN.match(record_id):
            raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")
        try:
            return services.apply_status(record_id, records_dir=cfg.records_dir, status=status)
        except (FileNotFoundError, KeyError):
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        except ValueError:
            raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")

    @app.post("/api/records/accept-all", dependencies=[Depends(require_token)])
    def post_accept_all(
        project: str | None = Query(default=None),
        type: str | None = Query(default=None),
    ):
        accepted = services.accept_all(cfg.records_dir, project=project, record_type=type)
        return {"accepted": accepted}

    @app.post("/api/records/{record_id}/accept", dependencies=[Depends(require_token)])
    def post_accept(record_id: str):
        return change_status(record_id, ACCEPTED_STATUS)

    @app.post("/api/records/{record_id}/reject", dependencies=[Depends(require_token)])
    def post_reject(record_id: str):
        return change_status(record_id, REJECTED_STATUS)

    @app.post(
        "/api/records/{old_id}/supersede-by/{new_id}",
        dependencies=[Depends(require_token)],
    )
    def post_link_supersession(old_id: str, new_id: str):
        from persistent_memory.records import SupersessionLinkError, link_supersession

        for record_id in (old_id, new_id):
            if not ID_PATTERN.match(record_id):
                raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")
        try:
            result = link_supersession(cfg.records_dir, old_id, new_id)
        except SupersessionLinkError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {
            "old": {
                "id": result.old_record.id,
                "status": result.old_record.status.value,
                "superseded_by": result.old_record.superseded_by,
            },
            "new": {
                "id": result.new_record.id,
                "status": result.new_record.status.value,
                "supersedes": result.new_record.supersedes,
            },
            "already_linked": result.already_linked,
        }

    @app.post("/api/consolidate", dependencies=[Depends(require_token)])
    def post_consolidate(full: bool = Query(default=False)):
        return services.run_consolidation(records_dir=cfg.records_dir, cluster_only=not full)

    @app.post("/api/extract", dependencies=[Depends(require_token)])
    def post_extract(body: ExtractRequest):
        result = services.trigger_extraction(
            project=body.project,
            cwd=body.cwd or "",
            transcript_path=body.transcript_path,
            records_dir=cfg.records_dir,
        )
        return JSONResponse(content=result, status_code=HTTP_ACCEPTED)

    def _project_names(records: list[dict]) -> list[str]:
        names = {r.get("project") for r in records if r.get("project")}
        return sorted(names)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/app", response_class=HTMLResponse)
    def page_app(request: Request):
        return templates.TemplateResponse(
            request,
            "app.html",
            {
                "pm_json": dashboard_data.pm_payload_json(cfg),
                "pm_token": token,
                "pm_i18n_json": json.dumps(_i18n.ui_strings(), ensure_ascii=False),
            },
        )

    @app.get("/legacy", response_class=HTMLResponse)
    def page_index(request: Request):
        records = list_records_with_titles([cfg.decisions_dir, cfg.lessons_dir])
        candidates = sort_by_date_desc(filter_by_status(records, PROPOSED_STATUS))
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "decisions_count": count_markdown(cfg.decisions_dir),
                "lessons_count": count_markdown(cfg.lessons_dir),
                "projects_count": len(_project_names(records)),
                "candidates": candidates,
                "recent": sort_by_date_desc(records)[:RECENT_LIMIT],
                "has_graph": cfg.graph_html_path.exists(),
                "pm_token": token,
            },
        )

    @app.get("/decisions", response_class=HTMLResponse)
    def page_decisions(request: Request):
        records = sort_by_date_desc(list_records_with_titles([cfg.decisions_dir]))
        return templates.TemplateResponse(
            request,
            "list.html",
            {
                "records": records,
                "heading": _i18n.t("dashboard.heading.decisions"),
                "projects": _project_names(records),
                "pm_token": token,
            },
        )

    @app.get("/lessons", response_class=HTMLResponse)
    def page_lessons(request: Request):
        records = sort_by_date_desc(list_records_with_titles([cfg.lessons_dir]))
        return templates.TemplateResponse(
            request,
            "list.html",
            {
                "records": records,
                "heading": _i18n.t("dashboard.heading.lessons"),
                "projects": _project_names(records),
                "pm_token": token,
            },
        )

    @app.get("/records/{record_id}", response_class=HTMLResponse)
    def page_record_detail(request: Request, record_id: str):
        if not ID_PATTERN.match(record_id):
            raise HTTPException(status_code=422, detail=f"malformed id: {record_id}")
        try:
            detail = services.record_detail(
                cfg.records_dir, record_id, transcript_index_dir=cfg.transcript_index_path
            )
        except (FileNotFoundError, KeyError):
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        return templates.TemplateResponse(
            request, "record_detail.html", {"detail": detail, "pm_token": token}
        )

    @app.get("/projects", response_class=HTMLResponse)
    def page_projects(request: Request):
        projects = services.project_overview(
            projects_root=cfg.projects_root, records_dir=cfg.records_dir
        )
        return templates.TemplateResponse(request, "projects.html", {"projects": projects})

    @app.get("/projects/{project}", response_class=HTMLResponse)
    def page_project_detail(request: Request, project: str):
        detail = services.project_detail(
            project=project, projects_root=cfg.projects_root, records_dir=cfg.records_dir
        )
        return templates.TemplateResponse(request, "project_detail.html", {"detail": detail})

    @app.get("/timeline", response_class=HTMLResponse)
    def page_timeline(request: Request):
        records = sort_by_date_desc(all_records())
        return templates.TemplateResponse(request, "timeline.html", {"records": records})

    @app.get("/search", response_class=HTMLResponse)
    def page_search(request: Request):
        return templates.TemplateResponse(request, "search.html", {})

    @app.get("/health", response_class=HTMLResponse)
    def page_health(request: Request):
        report = services.run_lint(records_dir=cfg.records_dir)
        return templates.TemplateResponse(request, "health.html", {"report": report})

    @app.get("/graph", response_class=HTMLResponse)
    def page_graph(request: Request):
        return templates.TemplateResponse(
            request, "graph.html", {"has_graph": cfg.graph_html_path.exists()}
        )

    return app
