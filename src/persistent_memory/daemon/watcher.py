"""Filesystem watcher: re-embeds changed records and paces consolidation.

Watches decisions/ and lessons/ for markdown changes. Each change is embedded
immediately (so search stays fresh) and counted by a heartbeat; every N-th
change triggers a consolidation pass.

``on_moved`` matters because record writers use atomic rename (write to a
temp file, then rename onto the final ``.md`` path): such a write surfaces as
a move event whose ``dest_path`` is the real record, not as on_modified.
"""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEventHandler

from persistent_memory.daemon import services
from persistent_memory.daemon.config import HEARTBEAT_MESSAGE_THRESHOLD

logger = logging.getLogger(__name__)

MARKDOWN_SUFFIX = ".md"
COALESCE_WINDOW_SECONDS = 0.5


class HeartbeatCounter:
    def __init__(self, *, threshold: int = HEARTBEAT_MESSAGE_THRESHOLD):
        self._threshold = threshold
        self._count = 0
        self._lock = threading.Lock()

    def tick(self) -> bool:
        with self._lock:
            self._count += 1
            if self._count >= self._threshold:
                self._count = 0
                return True
            return False


class RecordChangeHandler(FileSystemEventHandler):
    def __init__(
        self,
        *,
        records_dir: Path,
        heartbeat: HeartbeatCounter | None = None,
        on_consolidate: Callable[[], None] | None = None,
    ):
        self._records_dir = Path(records_dir)
        self._heartbeat = heartbeat or HeartbeatCounter()
        self._on_consolidate = on_consolidate
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self.changes_seen = 0

    def _is_coalesced(self, path: Path) -> bool:
        now = time.monotonic()
        key = str(path)
        with self._lock:
            last = self._last_seen.get(key)
            self._last_seen[key] = now
            return last is not None and (now - last) < COALESCE_WINDOW_SECONDS

    def _handle(self, src_path: str, is_directory: bool) -> None:
        if is_directory:
            return
        path = Path(src_path)
        if path.suffix != MARKDOWN_SUFFIX:
            return
        if self._is_coalesced(path):
            return
        self._embed_safe(path)
        self.changes_seen += 1
        if self._heartbeat.tick() and self._on_consolidate is not None:
            self._on_consolidate()

    def _embed_safe(self, path: Path) -> None:
        try:
            services.embed_record(path, records_dir=self._records_dir)
        except Exception:
            logger.warning("failed to embed record: %s", path, exc_info=True)

    def on_modified(self, event) -> None:
        self._handle(event.src_path, event.is_directory)

    def on_created(self, event) -> None:
        self._handle(event.src_path, event.is_directory)

    def on_moved(self, event) -> None:
        # Atomic-rename writes (tmp file -> final .md) arrive here; the record
        # that needs embedding is the rename destination.
        self._handle(getattr(event, "dest_path", event.src_path), event.is_directory)
