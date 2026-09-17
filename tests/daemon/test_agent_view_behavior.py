"""Real behaviour tests for the agent rules & memory view (views-agents.jsx).

``views-agents.jsx`` uses JSX syntax, which plain node cannot ``eval`` without
a transpiler (see ``jsx_runtime.py`` — its harness has none). Following the
pattern already used in ``test_graph_view_static.py`` for ``onCanvasMouseDown``,
the pure/JSX-free logic that actually drives each behaviour is carved out of
the source text and exercised in node against a small hand-written scenario
prelude, instead of asserting on source strings.
"""

import json

from persistent_memory.daemon.app import STATIC_DIR
from tests.daemon.jsx_runtime import run_extracted_functions, run_js_source

PM_STATIC = STATIC_DIR / "pm"
AGENTS_JSX_PATH = PM_STATIC / "views-agents.jsx"


def _agents_jsx():
    return AGENTS_JSX_PATH.read_text(encoding="utf-8")


def _extract_block(source, header):
    start = source.index(header)
    index = source.index("{", start)
    depth = 0
    while index < len(source):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unbalanced braces after {header!r} in views-agents.jsx")


def _extract_statement(source, header):
    start = source.index(header)
    end = source.index("\n", start)
    return source[start:end].rstrip()


def _as_function_declaration(source, arrow_header, function_header):
    """Turn ``const name = (args) => { ... }`` into a ``function`` declaration.

    Node's indirect ``eval`` (used by ``run_js_source``) only leaks top-level
    ``function`` declarations past the eval call — ``const``/``let`` bindings,
    including const-arrow-function handlers, are discarded once the eval call
    returns (verified empirically; see the module docstring). Rewriting the
    extracted handler as a function declaration keeps its exact body intact
    while making it callable from the test's scenario code afterwards.
    """
    block = _extract_block(source, arrow_header)
    return function_header + block[len(arrow_header) :]


def _as_function_from_expression(source, header, fn_name):
    statement = _extract_statement(source, header)
    assert statement.endswith(";"), statement
    expr = statement[len(header) : -1].strip()
    return f"function {fn_name}() {{ return {expr}; }}"


# --- (a) inventory load renders exactly one row per group -------------------

SAMPLE_GROUPS = [
    {"agent": "claude", "layer": "rules", "scope": "global", "count": 1},
    {"agent": "claude", "layer": "memory", "scope": "proj-a", "count": 2},
    {"agent": "claude", "layer": "memory", "scope": "proj-b", "count": 1},
    {"agent": "codex", "layer": "rules", "scope": "global", "count": 1},
    {"agent": "codex", "layer": "memory", "scope": "global", "count": 3},
    {"agent": "grok", "layer": "rules", "scope": "global", "count": 1},
]


def test_build_tree_yields_exactly_one_row_per_inventory_group():
    result = run_extracted_functions(
        path=AGENTS_JSX_PATH,
        names=("groupKey", "buildTree"),
        script_body=f"""
        const groups = {json.dumps(SAMPLE_GROUPS)};
        const tree = buildTree(groups);
        const rowKeys = [];
        tree.forEach((agentNode) => {{
          agentNode.layerOrder.forEach((layer) => {{
            agentNode.layers[layer].forEach((g) => {{
              rowKeys.push(groupKey(g.agent, g.layer, g.scope));
            }});
          }});
        }});
        return {{ rowKeys: rowKeys, agentCount: tree.length }};
        """,
    )
    expected_keys = [g["agent"] + ":" + g["layer"] + ":" + g["scope"] for g in SAMPLE_GROUPS]
    assert sorted(result["rowKeys"]) == sorted(expected_keys)
    assert len(result["rowKeys"]) == len(SAMPLE_GROUPS), "one tree row per group, no drops or duplicates"
    assert result["agentCount"] == 3


def test_build_tree_keeps_each_agents_layers_and_scopes_separate():
    result = run_extracted_functions(
        path=AGENTS_JSX_PATH,
        names=("groupKey", "buildTree"),
        script_body=f"""
        const groups = {json.dumps(SAMPLE_GROUPS)};
        const tree = buildTree(groups);
        const claudeNode = tree.find((n) => n.agent === "claude");
        const codexNode = tree.find((n) => n.agent === "codex");
        return {{
          claudeLayers: claudeNode.layerOrder,
          claudeMemoryScopes: claudeNode.layers.memory.map((g) => g.scope),
          codexMemoryCount: codexNode.layers.memory.length,
        }};
        """,
    )
    assert result["claudeLayers"] == ["rules", "memory"]
    assert sorted(result["claudeMemoryScopes"]) == ["proj-a", "proj-b"]
    assert result["codexMemoryCount"] == 1


# --- (b) switching asset with unsaved changes asks for confirmation ---------

ORIGINAL_ID = "claude:rules:global:CLAUDE.md"
OTHER_ID = "claude:memory:proj-a:not.md"


def _select_flow_js():
    source = _agents_jsx()
    do_select = _as_function_declaration(
        source, "const doSelect = (id) => {", "function doSelect(id) {"
    )
    try_select = _as_function_declaration(
        source, "const trySelect = (id) => {", "function trySelect(id) {"
    )
    confirm_discard = _as_function_from_expression(
        source, "const confirmDiscard = () => ", "confirmDiscard"
    )
    cancel_discard = _as_function_from_expression(
        source, "const cancelDiscard = () => ", "cancelDiscard"
    )
    return "\n".join(
        [
            f"let selectedId = {json.dumps(ORIGINAL_ID)};",
            "let pendingId = null;",
            "let dirty = true;",
            "function setSelectedId(id) { selectedId = id; }",
            "function setPendingId(id) { pendingId = id; }",
            do_select,
            try_select,
            confirm_discard,
            cancel_discard,
            "function snapshot() { return { selectedId: selectedId, pendingId: pendingId }; }",
            "function setDirty(flag) { dirty = flag; }",
        ]
    )


def test_switching_asset_while_dirty_asks_first_and_declining_keeps_selection():
    result = run_js_source(
        _select_flow_js(),
        f"""
        const before = snapshot();

        trySelect({json.dumps(OTHER_ID)});
        const afterAttempt = snapshot();

        cancelDiscard();
        const afterDecline = snapshot();

        return {{ before: before, afterAttempt: afterAttempt, afterDecline: afterDecline }};
        """,
    )
    assert result["before"] == {"selectedId": ORIGINAL_ID, "pendingId": None}
    assert result["afterAttempt"] == {"selectedId": ORIGINAL_ID, "pendingId": OTHER_ID}, (
        "unsaved changes must raise a pending confirmation instead of switching immediately"
    )
    assert result["afterDecline"] == {"selectedId": ORIGINAL_ID, "pendingId": None}, (
        "declining the switch must leave the original selection untouched"
    )


def test_confirming_the_switch_while_dirty_then_applies_the_pending_selection():
    result = run_js_source(
        _select_flow_js(),
        f"""
        trySelect({json.dumps(OTHER_ID)});
        confirmDiscard();
        return snapshot();
        """,
    )
    assert result == {"selectedId": OTHER_ID, "pendingId": None}


def test_switching_asset_without_unsaved_changes_needs_no_confirmation():
    result = run_js_source(
        _select_flow_js(),
        f"""
        setDirty(false);
        trySelect({json.dumps(OTHER_ID)});
        return snapshot();
        """,
    )
    assert result == {"selectedId": OTHER_ID, "pendingId": None}


def test_reselecting_the_currently_open_asset_while_dirty_is_a_no_op():
    result = run_js_source(
        _select_flow_js(),
        f"""
        trySelect({json.dumps(ORIGINAL_ID)});
        return snapshot();
        """,
    )
    assert result == {"selectedId": ORIGINAL_ID, "pendingId": None}
