import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@pytest.fixture(autouse=True)
def _reset_shared_state():
    from persistent_memory.daemon.services import reset_metrics
    from persistent_memory.retriever import _reset_bm25_cache

    _reset_bm25_cache()
    reset_metrics()
