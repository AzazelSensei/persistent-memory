from persistent_memory.daemon.app import STATIC_DIR

PM_STATIC = STATIC_DIR / "pm"


def _graph_jsx():
    return (PM_STATIC / "views-graph.jsx").read_text(encoding="utf-8")


def test_graph_view_clears_selection_when_filtered_out():
    graph_jsx = _graph_jsx()
    assert "if (selectedId && !visibleIdSet.has(selectedId)) setSelectedId(null);" in graph_jsx
    assert "[visibleIdSet, selectedId]" in graph_jsx


def test_graph_view_canvas_hint_describes_select_then_panel_navigation():
    graph_jsx = _graph_jsx()
    assert "click → record" not in graph_jsx
    assert "click to select" in graph_jsx
    assert "open record from the panel" in graph_jsx or "double-click" in graph_jsx


def test_graph_view_search_match_always_wins_over_selection_dimming():
    graph_jsx = _graph_jsx()
    start = graph_jsx.index("function computeNodeVisualState(")
    end = graph_jsx.index("\n  }\n", start)
    block = graph_jsx[start:end]
    assert "const hasQuery = !!query.trim();" in block
    assert "if (hasQuery) {" in block
    assert 'if (matchesQuery(n)) return "focus";' in block


def test_graph_view_wheel_listener_is_registered_non_passive():
    graph_jsx = _graph_jsx()
    assert 'addEventListener("wheel", ' in graph_jsx
    assert "{ passive: false }" in graph_jsx
    assert 'removeEventListener("wheel", ' in graph_jsx
    assert "onWheel={onWheel}" not in graph_jsx


def test_graph_view_edge_opacity_floor_meets_contrast_and_avoids_line2():
    graph_jsx = _graph_jsx()
    assert "const EDGE_MIN_OP = 0.75, EDGE_MAX_OP = 1;" in graph_jsx
    start = graph_jsx.index("stroke={e.unexpected")
    end = graph_jsx.index("\n", start)
    stroke_line = graph_jsx[start:end]
    assert "var(--line2)" not in stroke_line
    assert "var(--dim)" in stroke_line


def test_graph_view_node_double_click_opens_record():
    graph_jsx = _graph_jsx()
    assert 'onDoubleClick={(ev) => { ev.stopPropagation(); nav("detail", { id: n.id }); }}' in graph_jsx


def test_graph_table_row_has_button_for_keyboard_access():
    graph_jsx = _graph_jsx()
    table_block = graph_jsx[graph_jsx.index("function GraphTable(") :]
    assert '<button className="gr-idbtn"' in table_block


def test_graph_cluster_row_truncates_long_labels_with_title():
    graph_jsx = _graph_jsx()
    assert "gr-leglabel{" in graph_jsx
    assert "text-overflow:ellipsis" in graph_jsx.split("gr-leglabel{", 1)[1].split("}", 1)[0]
    assert "title={c.label}" in graph_jsx
