"""Daemon configuration: ports, directory layout and derived paths."""

from dataclasses import dataclass, field
from pathlib import Path

from persistent_memory.graph_ingest import CLAUDEMEM_DB_PATH
from persistent_memory.transcripts import PROJECTS_ROOT

DAEMON_HOST = "127.0.0.1"
DAEMON_PORT = 37778
HEARTBEAT_MESSAGE_THRESHOLD = 5

GRAPHIFY_OUT_DIRNAME = "graphify-out"
GRAPH_HTML_FILENAME = "graph.html"

DECISIONS_DIRNAME = "decisions"
LESSONS_DIRNAME = "lessons"

INDEX_ROOT_DIRNAME = ".pm-index"
TRANSCRIPT_INDEX_DIRNAME = "transcripts"


@dataclass(frozen=True)
class DaemonConfig:
    records_dir: Path
    host: str = DAEMON_HOST
    port: int = DAEMON_PORT
    watch_enabled: bool = True
    claudemem_db_path: Path = field(default=CLAUDEMEM_DB_PATH)
    projects_root: Path = field(default=PROJECTS_ROOT)
    transcript_index_dir: Path | None = None

    @property
    def transcript_index_path(self) -> Path:
        if self.transcript_index_dir is not None:
            return self.transcript_index_dir
        return self.records_dir / INDEX_ROOT_DIRNAME / TRANSCRIPT_INDEX_DIRNAME

    @property
    def decisions_dir(self) -> Path:
        return self.records_dir / DECISIONS_DIRNAME

    @property
    def lessons_dir(self) -> Path:
        return self.records_dir / LESSONS_DIRNAME

    @property
    def graphify_out_dir(self) -> Path:
        return self.records_dir / GRAPHIFY_OUT_DIRNAME

    @property
    def graph_html_path(self) -> Path:
        return self.graphify_out_dir / GRAPH_HTML_FILENAME
