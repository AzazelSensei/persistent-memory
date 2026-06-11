"""Semantic search over raw transcript chunks (provenance RAG).

Windows transcript messages into fixed-size chunks, embeds them locally, and
retrieves the passages most similar to a query. Used to surface the original
conversation excerpts a record came from. Content-hash dedup keeps index
rebuilds idempotent.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from persistent_memory.embeddings import OllamaEmbedder, l2_normalize
from persistent_memory.transcripts import (
    PROJECTS_ROOT,
    Message,
    _first_cwd,
    list_projects,
    project_transcripts,
    read_transcript,
)

CHUNK_WINDOW = 6
CHUNK_MAX_CHARS = 1500
DEFAULT_TOP_K = 5

VECTORS_FILE = "vectors.npy"
META_FILE = "meta.json"
TRANSCRIPTS_SUBDIR = "transcripts"


@dataclass
class Chunk:
    project: str
    session_id: str
    text: str
    timestamp: str | None
    ordinal: int


def _content_hash(project: str, session_id: str, text: str) -> str:
    return hashlib.sha256(f"{project}\x00{session_id}\x00{text}".encode("utf-8")).hexdigest()


def _has_signal(messages: list[Message]) -> bool:
    return any(m.text and not m.is_tool for m in messages)


def _render(messages: list[Message]) -> str:
    return "\n".join(f"[{m.role}] {m.text}" for m in messages if m.text)


def _project_name(project_dir: Path) -> str:
    cwd = None
    for transcript in project_transcripts(project_dir):
        cwd = _first_cwd(transcript)
        if cwd:
            break
    if cwd:
        return Path(cwd).name
    return project_dir.name


def chunk_project(
    project_dir: Path, window: int = CHUNK_WINDOW, max_chars: int = CHUNK_MAX_CHARS
) -> list[Chunk]:
    project = _project_name(project_dir)
    chunks: list[Chunk] = []
    for transcript in project_transcripts(project_dir):
        session_id = transcript.stem
        messages = [m for m in read_transcript(transcript) if m.text]
        ordinal = 0
        for start in range(0, len(messages), window):
            group = messages[start : start + window]
            if not _has_signal(group):
                continue
            text = _render(group)[:max_chars]
            timestamp = next((m.timestamp for m in group), None)
            chunks.append(
                Chunk(
                    project=project,
                    session_id=session_id,
                    text=text,
                    timestamp=timestamp,
                    ordinal=ordinal,
                )
            )
            ordinal += 1
    return chunks


EMBED_BATCH_SIZE = 32


class TranscriptRagIndex:
    def __init__(self) -> None:
        self._vectors: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self._meta: list[dict] = []
        self._hashes: set[str] = set()

    def __len__(self) -> int:
        return len(self._meta)

    def add_chunks(self, chunks: list[Chunk], embedder: OllamaEmbedder) -> int:
        pending = [c for c in chunks if _content_hash(c.project, c.session_id, c.text) not in self._hashes]
        if not pending:
            return 0
        new_rows: list[np.ndarray] = []
        new_meta: list[dict] = []
        for start in range(0, len(pending), EMBED_BATCH_SIZE):
            batch = pending[start:start + EMBED_BATCH_SIZE]
            raw = embedder.embed_batch([c.text for c in batch])
            for chunk, vector in zip(batch, raw):
                content_hash = _content_hash(chunk.project, chunk.session_id, chunk.text)
                if content_hash in self._hashes:
                    continue
                new_rows.append(np.asarray(l2_normalize(vector), dtype=np.float32).reshape(1, -1))
                new_meta.append(
                    {
                        "project": chunk.project,
                        "session_id": chunk.session_id,
                        "timestamp": chunk.timestamp,
                        "text": chunk.text,
                        "hash": content_hash,
                    }
                )
                self._hashes.add(content_hash)
        if not new_rows:
            return 0
        stacked = np.vstack(new_rows)
        self._vectors = stacked if self._vectors.size == 0 else np.vstack([self._vectors, stacked])
        self._meta.extend(new_meta)
        return len(new_rows)

    def query(self, vector: list[float], top_k: int, project: str | None = None) -> list[dict]:
        if not self._meta:
            return []
        q = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm
        scores = self._vectors @ q
        order = np.argsort(-scores)
        results: list[dict] = []
        for i in order:
            meta = self._meta[i]
            if project is not None and meta["project"] != project:
                continue
            results.append(
                {
                    "text": meta["text"],
                    "project": meta["project"],
                    "session_id": meta["session_id"],
                    "timestamp": meta["timestamp"],
                    "score": float(scores[i]),
                }
            )
            if len(results) >= top_k:
                break
        return results

    def save(self, index_dir: Path) -> None:
        path = Path(index_dir)
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / VECTORS_FILE, self._vectors)
        (path / META_FILE).write_text(json.dumps(self._meta, ensure_ascii=False))

    def load(self, index_dir: Path) -> None:
        path = Path(index_dir)
        vectors_path = path / VECTORS_FILE
        meta_path = path / META_FILE
        if not vectors_path.exists() or not meta_path.exists():
            return
        self._vectors = np.load(vectors_path)
        self._meta = json.loads(meta_path.read_text())
        self._hashes = {m["hash"] for m in self._meta}


def build_transcript_index(
    index_dir: Path,
    projects_root: Path | None = None,
    embedder: OllamaEmbedder | None = None,
) -> int:
    root = Path(projects_root) if projects_root is not None else PROJECTS_ROOT
    active_embedder = embedder if embedder is not None else OllamaEmbedder()
    index = TranscriptRagIndex()
    total = 0
    for info in list_projects(root):
        for directory in info.dirs:
            chunks = chunk_project(directory)
            if not chunks:
                continue
            total += index.add_chunks(chunks, active_embedder)
    index.save(index_dir)
    return total


def retrieve_for_text(
    text: str,
    *,
    index_dir: Path,
    project: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    embedder: OllamaEmbedder | None = None,
) -> list[dict]:
    path = Path(index_dir)
    if not path.exists():
        return []
    index = TranscriptRagIndex()
    index.load(path)
    if len(index) == 0:
        return []
    active_embedder = embedder if embedder is not None else OllamaEmbedder()
    vector = l2_normalize(active_embedder.embed_one(text))
    return index.query(vector, top_k=top_k, project=project)
