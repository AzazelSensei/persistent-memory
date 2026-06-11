"""Fixed-budget recall block: top memory records rendered for prompt injection.

The block is injected into new sessions as additional context, so
``RECALL_HEADER`` is functional AI-facing instruction text, not
decoration. Budgeting uses a cheap chars/4 token estimate — exact
tokenization is not worth a tokenizer dependency for a soft cap.
Candidates below ``MIN_VISIBILITY_SCORE`` are dropped so near-zero
results (e.g. heavily dampened superseded records) never spend budget.
"""

from __future__ import annotations

from typing import Any, Callable

CHARS_PER_TOKEN = 4
DEFAULT_TOKEN_BUDGET = 1200
MIN_VISIBILITY_SCORE = 1e-3
RECALL_HEADER = "## Recall — past decisions and lessons"
RECALL_TOP_K = 20


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN + 1


def _format_candidate(candidate: Any) -> str:
    rec = candidate.record
    summary = rec.body.strip().splitlines()[0] if rec.body.strip() else ""
    return f"- [{rec.id}] {rec.title} ({rec.status}, {rec.date}): {summary}"


def build_recall_block(project: str | None, searcher: Callable[..., list[Any]],
                       token_budget: int = DEFAULT_TOKEN_BUDGET) -> str:
    candidates = searcher(project=project, top_k=RECALL_TOP_K)
    visible = [c for c in candidates if c.score >= MIN_VISIBILITY_SCORE]
    if not visible:
        return ""
    lines = [RECALL_HEADER]
    used = estimate_tokens(RECALL_HEADER)
    has_body = False
    for candidate in visible:
        line = _format_candidate(candidate)
        cost = estimate_tokens(line)
        if used + cost > token_budget:
            break
        lines.append(line)
        used += cost
        has_body = True
    # A bare header is noise: emit nothing unless at least one record fits.
    if not has_body:
        return ""
    return "\n".join(lines)
