"""Local embedding stack: Ollama bge-m3 client, flat vector index, retrieval adapter.

Everything runs locally — embeddings come from an Ollama-served bge-m3
model, so no external API key is needed. Vectors are L2-normalized at
write time, which lets ``VectorIndex.query`` use a plain dot product as
cosine similarity. The index is a flat numpy matrix persisted atomically
(temp file + ``os.replace``) so a crash mid-save never leaves a torn
index; at the current corpus scale (hundreds of records) brute-force
search is faster and simpler than maintaining an ANN structure.

``content_hash_for`` hashes exactly the text that gets embedded
(``compose_record_text``), so re-indexing skips records whose embedded
representation is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

import httpx
import numpy as np

OLLAMA_URL = "http://localhost:11434/api/embed"
MODEL_NAME = "bge-m3"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 0.5
# Embed only the leading body slice: record bodies front-load the decision/
# lesson summary, and unbounded input wastes embedding latency.
BODY_SUMMARY_MAX_CHARS = 2000
VECTORS_FILE = "vectors.npy"
IDS_FILE = "ids.json"


class EmbeddingError(RuntimeError):
    pass


class OllamaEmbedder:
    def __init__(
        self,
        url: str = OLLAMA_URL,
        model: str = MODEL_NAME,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = MAX_RETRIES,
        transport: httpx.BaseTransport | None = None,
    ):
        self._url = url
        self._model = model
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        last_error: httpx.HTTPError | None = None
        for attempt in range(self._max_retries):
            try:
                response = self._client.post(self._url, json={"model": self._model, "input": texts})
                response.raise_for_status()
                return response.json()["embeddings"]
            except httpx.HTTPError as err:
                last_error = err
                if attempt < self._max_retries - 1:
                    time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
        raise EmbeddingError(
            f"Ollama embed request failed after {self._max_retries} attempts ({self._url}): {last_error}"
        ) from last_error


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0.0:
        return list(vector)
    return [x / norm for x in vector]


def compose_record_text(record) -> str:
    tags_text = " ".join(record.tags or [])
    body_summary = (record.body or "")[:BODY_SUMMARY_MAX_CHARS]
    return f"{record.title}\n{tags_text}\n{body_summary}".strip()


def embed_record(record, embedder: OllamaEmbedder) -> list[float]:
    text = compose_record_text(record)
    return l2_normalize(embedder.embed_one(text))


def content_hash_for(record) -> str:
    return hashlib.sha256(compose_record_text(record).encode("utf-8")).hexdigest()


def _write_file_atomic(path: Path, mode: str, writer) -> None:
    encoding = None if "b" in mode else "utf-8"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, mode, encoding=encoding) as handle:
            writer(handle)
        os.replace(tmp_name, path)
    except OSError:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


class VectorIndex:
    def __init__(self, index_dir: Path):
        self._dir = Path(index_dir)
        self._vectors: np.ndarray = np.empty((0, 0), dtype=np.float32)
        self._ids: list[str] = []
        self._pos: dict[str, int] = {}
        self._hashes: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._ids)

    def ids(self) -> list[str]:
        return list(self._ids)

    def hash_of(self, record_id: str) -> str | None:
        return self._hashes.get(record_id)

    def vector_of(self, record_id: str) -> list[float] | None:
        position = self._pos.get(record_id)
        if position is None:
            return None
        return self._vectors[position].tolist()

    def upsert(self, record_id: str, vector: list[float], content_hash: str) -> bool:
        if self._hashes.get(record_id) == content_hash:
            return False
        row = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        position = self._pos.get(record_id)
        if position is not None:
            self._vectors[position] = row
        else:
            self._vectors = row if self._vectors.size == 0 else np.vstack([self._vectors, row])
            self._ids.append(record_id)
            self._pos[record_id] = len(self._ids) - 1
        self._hashes[record_id] = content_hash
        return True

    def remove(self, record_id: str) -> bool:
        position = self._pos.get(record_id)
        if position is None:
            return False
        self._vectors = np.delete(self._vectors, position, axis=0)
        self._ids.pop(position)
        del self._hashes[record_id]
        self._pos = {rid: i for i, rid in enumerate(self._ids)}
        return True

    def query(self, vector: list[float], top_k: int) -> list[tuple[str, float]]:
        if len(self._ids) == 0:
            return []
        q = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm
        scores = self._vectors @ q
        k = min(top_k, len(self._ids))
        top = np.argsort(-scores)[:k]
        return [(self._ids[i], float(scores[i])) for i in top]

    def save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        _write_file_atomic(
            self._dir / VECTORS_FILE, "wb", lambda handle: np.save(handle, self._vectors)
        )
        meta = json.dumps({"ids": self._ids, "hashes": self._hashes}, ensure_ascii=False)
        _write_file_atomic(self._dir / IDS_FILE, "w", lambda handle: handle.write(meta))

    def load(self) -> None:
        vectors_path = self._dir / VECTORS_FILE
        ids_path = self._dir / IDS_FILE
        if not vectors_path.exists() or not ids_path.exists():
            return
        vectors = np.load(vectors_path)
        meta = json.loads(ids_path.read_text())
        ids = meta["ids"]
        row_count = int(vectors.shape[0]) if vectors.ndim == 2 else 0
        if row_count != len(ids):
            return
        self._vectors = vectors
        self._ids = ids
        self._hashes = meta["hashes"]
        self._pos = {rid: i for i, rid in enumerate(ids)}


class RetrievalAdapter:
    def __init__(self, embedder: OllamaEmbedder, index: VectorIndex):
        self._embedder = embedder
        self._index = index
        self._query_cache: dict[str, list[float]] = {}

    def embed_query(self, text: str) -> list[float]:
        cached = self._query_cache.get(text)
        if cached is not None:
            return cached
        vector = l2_normalize(self._embedder.embed_one(text))
        self._query_cache[text] = vector
        return vector

    def get_vector(self, record_id: str) -> list[float] | None:
        return self._index.vector_of(record_id)
