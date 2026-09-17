import json
import re

from starlette.testclient import TestClient

from persistent_memory.daemon.app import STATIC_DIR, TEMPLATES_DIR, create_app
from persistent_memory.daemon.config import DaemonConfig
from persistent_memory.i18n import MESSAGES, reset_lang_cache
from tests.daemon.jsx_runtime import run_extracted_functions

PM_STATIC = STATIC_DIR / "pm"
GRAPH_I18N_KEYS = sorted(key for key in MESSAGES if key.startswith("ui.graph."))


def _client(tmp_path):
    cfg = DaemonConfig(records_dir=tmp_path, watch_enabled=False, projects_root=tmp_path)
    return TestClient(create_app(records_dir=tmp_path, config=cfg))


def _graph_jsx():
    return (PM_STATIC / "views-graph.jsx").read_text(encoding="utf-8")


def test_graph_static_file_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/pm/views-graph.jsx")
    assert resp.status_code == 200
    assert "PMGraph" in resp.text


def test_template_wires_graph_script_with_version():
    html = (TEMPLATES_DIR / "app.html").read_text(encoding="utf-8")
    assert "/static/pm/views-graph.jsx?v={{ pm_asset_version }}" in html


def test_graph_view_defines_force_simulation_function():
    graph_jsx = _graph_jsx()
    assert "function simulationTick(" in graph_jsx
    assert "function applyRepulsionBrute(" in graph_jsx
    assert "function applyAttraction(" in graph_jsx
    assert "function applyClusterGravity(" in graph_jsx
    assert "function applyCenterGravity(" in graph_jsx
    assert "function integrateNodes(" in graph_jsx


def test_graph_view_has_alpha_decay_and_stop_condition():
    graph_jsx = _graph_jsx()
    assert "ALPHA_DECAY" in graph_jsx
    assert "ALPHA_MIN" in graph_jsx
    assert "alpha < ALPHA_MIN" in graph_jsx
    assert "alpha *= ALPHA_DECAY" in graph_jsx


def test_graph_view_has_repulsion_grid_fallback_for_large_graphs():
    graph_jsx = _graph_jsx()
    assert "REPULSION_GRID_THRESHOLD" in graph_jsx
    assert "function buildGrid(" in graph_jsx
    assert "function applyRepulsionGrid(" in graph_jsx


def test_graph_view_has_deterministic_seeded_rng():
    graph_jsx = _graph_jsx()
    assert "function makeRng(" in graph_jsx
    assert "const SEED = " in graph_jsx
    assert "Math.random" not in graph_jsx


def test_graph_view_has_zoom_pan_handlers():
    graph_jsx = _graph_jsx()
    assert "onWheel" in graph_jsx
    assert "onCanvasMouseDown" in graph_jsx
    assert "onCanvasDoubleClick" in graph_jsx
    assert "getScreenCTM" in graph_jsx


def test_graph_view_has_zoom_constants():
    graph_jsx = _graph_jsx()
    assert "MIN_ZOOM = " in graph_jsx
    assert "MAX_ZOOM = " in graph_jsx


def test_graph_view_maps_type_to_color():
    graph_jsx = _graph_jsx()
    assert "const TYPE_COLOR = " in graph_jsx
    assert "decision:" in graph_jsx
    assert "lesson:" in graph_jsx


def test_graph_view_maps_type_to_shape():
    graph_jsx = _graph_jsx()
    assert "const TYPE_SHAPE = " in graph_jsx
    assert '"diamond"' in graph_jsx
    assert '"circle"' in graph_jsx


def test_graph_view_scales_radius_by_importance():
    graph_jsx = _graph_jsx()
    assert "function radiusForImp(" in graph_jsx
    assert "MIN_R = " in graph_jsx
    assert "MAX_R = " in graph_jsx
    assert "IMP_MIN" in graph_jsx
    assert "IMP_MAX" in graph_jsx


def test_graph_view_status_ring_encodes_status():
    graph_jsx = _graph_jsx()
    assert "const STATUS_RING = " in graph_jsx
    assert "accepted:" in graph_jsx
    assert "proposed:" in graph_jsx
    assert "reverted:" in graph_jsx
    assert "superseded:" in graph_jsx


def test_graph_view_edge_style_differs_by_type():
    graph_jsx = _graph_jsx()
    assert "const EDGE_DASH = " in graph_jsx
    assert "conceptually_related_to" in graph_jsx
    assert "semantically_similar_to" in graph_jsx
    assert "rationale_for" in graph_jsx
    assert "shares_data_with" in graph_jsx


def test_graph_view_gives_unexpected_edges_special_style():
    graph_jsx = _graph_jsx()
    assert "gr-edge-unexp" in graph_jsx
    assert "UNEXPECTED_COLOR" in graph_jsx
    assert '"6 4"' in graph_jsx
    assert "@keyframes gr-flow" in graph_jsx


def test_graph_view_defines_glow_filter():
    graph_jsx = _graph_jsx()
    assert 'id="gr-glow"' in graph_jsx
    assert "feGaussianBlur" in graph_jsx
    assert "feMerge" in graph_jsx


def test_graph_view_has_label_declutter_threshold():
    graph_jsx = _graph_jsx()
    assert "LABEL_ZOOM_THRESHOLD" in graph_jsx
    assert "LABEL_TOP_DEGREE_COUNT" in graph_jsx
    assert "topDegreeIds" in graph_jsx
    assert "matchesQuery" in graph_jsx


def test_graph_view_updates_positions_via_ref_not_per_frame_state():
    graph_jsx = _graph_jsx()
    assert "posRef" in graph_jsx
    assert "requestAnimationFrame" in graph_jsx
    assert "setAttribute(\"transform\"" in graph_jsx
    assert "setSettled(true)" in graph_jsx


def test_graph_view_never_uses_dangerous_html():
    graph_jsx = _graph_jsx()
    assert "dangerouslySetInnerHTML" not in graph_jsx


def test_graph_view_has_hover_and_persistent_selection_state():
    graph_jsx = _graph_jsx()
    assert "const [selectedId, setSelectedId] = useState(" in graph_jsx
    assert "const [hover, setHover] = useState(" in graph_jsx
    assert "const focalId = hover || selectedId || null;" in graph_jsx


def test_graph_view_computes_neighbourhood_and_second_degree():
    graph_jsx = _graph_jsx()
    assert "const neighborSet = focalId" in graph_jsx
    assert "const secondDegreeIds = useMemo(" in graph_jsx
    assert "SECOND_DEGREE_OPACITY" in graph_jsx
    assert "function computeNodeVisualState(" in graph_jsx


def test_graph_view_background_click_clears_selection():
    graph_jsx = _graph_jsx()
    assert "let dragged = false;" in graph_jsx
    assert "if (!dragged) setSelectedId(null);" in graph_jsx


def test_graph_view_has_transition_css_for_hover_dim():
    graph_jsx = _graph_jsx()
    assert "transition:opacity 150ms ease" in graph_jsx


def test_graph_view_detail_panel_shows_record_fields():
    graph_jsx = _graph_jsx()
    assert "gr-d-title" in graph_jsx
    assert "StatusPill" in graph_jsx
    assert "Importance value={rec.importance}" in graph_jsx
    assert "Go to record" in graph_jsx
    assert 'nav("detail", { id: rec.id })' in graph_jsx


def test_graph_view_detail_panel_lists_neighbors_and_focuses_on_click():
    graph_jsx = _graph_jsx()
    assert "function neighborRowsFor(" in graph_jsx
    assert "const neighborRows = useMemo(" in graph_jsx
    assert "onClick={() => focusNode(row.id)}" in graph_jsx


def test_graph_view_has_focus_navigation_function():
    graph_jsx = _graph_jsx()
    assert "function focusNode(" in graph_jsx
    assert "FOCUS_DURATION_MS" in graph_jsx
    assert "requestAnimationFrame(step)" in graph_jsx


def test_graph_view_has_reset_button():
    graph_jsx = _graph_jsx()
    assert "function resetAll(" in graph_jsx
    assert 'onClick={resetAll}' in graph_jsx


def test_graph_view_cluster_panel_folds_long_tail():
    graph_jsx = _graph_jsx()
    assert "const CLUSTER_TOP_COUNT = 10;" in graph_jsx
    assert "const [clustersExpanded, setClustersExpanded] = useState(" in graph_jsx
    assert "hiddenClusterCount" in graph_jsx
    assert '"ui.graph.show_more"' in graph_jsx
    assert "(+${hiddenClusterCount})" in graph_jsx


def test_graph_view_cluster_click_toggles_halo_highlight():
    graph_jsx = _graph_jsx()
    assert "const onClusterClick = " in graph_jsx
    assert "const isHalo = activeCluster && n.cluster === activeCluster;" in graph_jsx
    assert "clusterColorById" in graph_jsx


def test_graph_view_search_matches_id_title_and_project():
    graph_jsx = _graph_jsx()
    assert "function matchesQueryNode(n, q) {" in graph_jsx
    assert "n.id.toLowerCase().includes(q)" in graph_jsx
    assert "(n.title || \"\").toLowerCase().includes(q)" in graph_jsx
    assert "(n.project || \"\").toLowerCase().includes(q)" in graph_jsx
    assert "const searchMatches = useMemo(" in graph_jsx
    assert "gr-matchcount" in graph_jsx


def test_graph_view_search_enter_focuses_first_match():
    graph_jsx = _graph_jsx()
    assert "const onSearchKeyDown = (ev) => {" in graph_jsx
    assert 'if (ev.key === "Enter")' in graph_jsx
    assert "focusNode(searchMatches[0].id)" in graph_jsx


def test_graph_view_has_type_status_and_project_filters():
    graph_jsx = _graph_jsx()
    assert "const toggleTypeFilter = " in graph_jsx
    assert "const toggleStatusFilter = " in graph_jsx
    assert "const [filterProject, setFilterProject] = useState(" in graph_jsx
    assert "function statusFilterGroup(" in graph_jsx
    assert "const clearFilters = " in graph_jsx
    assert "const activeFilterCount = " in graph_jsx


def test_graph_view_filters_hide_nodes_from_render():
    graph_jsx = _graph_jsx()
    assert "const visibleNodes = useMemo(" in graph_jsx
    assert "const visibleIdSet = useMemo(" in graph_jsx
    assert "if (!visibleIdSet.has(n.id)) return null;" in graph_jsx
    assert "if (!visibleIdSet.has(e.from) || !visibleIdSet.has(e.to)) return null;" in graph_jsx


def test_graph_view_escape_clears_selection_and_search():
    graph_jsx = _graph_jsx()
    assert 'window.addEventListener("keydown", onKeyDown);' in graph_jsx
    assert 'if (ev.key !== "Escape") return;' in graph_jsx
    assert "setSelectedId(null);\n        setQuery(\"\");" in graph_jsx


def test_graph_view_uses_real_buttons_and_select_for_controls():
    graph_jsx = _graph_jsx()
    assert '<select className="gr-select"' in graph_jsx
    assert '<button key={c.id} className={"gr-legrow"' in graph_jsx
    assert '<button key={row.id} className="gr-neighrow"' in graph_jsx


def test_graph_view_search_input_has_label():
    graph_jsx = _graph_jsx()
    assert 'htmlFor="gr-search-input"' in graph_jsx
    assert 'id="gr-search-input"' in graph_jsx


def test_nav_registers_graph_view():
    app_jsx = (PM_STATIC / "app.jsx").read_text(encoding="utf-8")
    assert '"graph"' in app_jsx
    assert "PMGraph" in app_jsx


# ---- Faz: palette validation, accessibility, i18n --------------------------


def _parse_i18n(body: str) -> dict:
    start = body.index("window.PM_I18N = ") + len("window.PM_I18N = ")
    end = body.index(";", start)
    return json.loads(body[start:end])


def test_graph_i18n_keys_exist():
    assert len(GRAPH_I18N_KEYS) > 0


def test_i18n_has_graph_keys_in_both_languages(tmp_path, monkeypatch):
    for lang in ("en", "tr"):
        monkeypatch.setenv("PM_LANG", lang)
        reset_lang_cache()
        try:
            client = _client(tmp_path)
            resp = client.get("/")
            i18n_data = _parse_i18n(resp.text)
            for key in GRAPH_I18N_KEYS:
                assert i18n_data.get(key), f"missing/empty {key} for lang={lang}"
        finally:
            monkeypatch.delenv("PM_LANG", raising=False)
            reset_lang_cache()


def test_app_page_turkish_i18n_has_graph_heading(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_LANG", "tr")
    reset_lang_cache()
    try:
        client = _client(tmp_path)
        resp = client.get("/")
        assert resp.status_code == 200
        i18n_data = _parse_i18n(resp.text)
        assert i18n_data.get("ui.graph.heading") == "Graf"
        assert i18n_data.get("ui.graph.table_toggle_show") == "Tablo görünümü"
    finally:
        monkeypatch.delenv("PM_LANG", raising=False)
        reset_lang_cache()


def test_graph_view_calls_t_for_every_catalog_string():
    graph_jsx = _graph_jsx()
    for key in GRAPH_I18N_KEYS:
        assert f'"{key}"' in graph_jsx, f"{key} not referenced in views-graph.jsx"


def test_graph_view_legend_shows_type_status_edge_and_unexpected_groups():
    graph_jsx = _graph_jsx()
    assert "ui.graph.legend_type_heading" in graph_jsx
    assert "ui.graph.legend_status_heading" in graph_jsx
    assert "ui.graph.legend_edge_heading" in graph_jsx
    assert "ui.graph.legend_unexpected" in graph_jsx
    assert "STATUS_ORDER.map(" in graph_jsx
    assert "EDGE_TYPE_ORDER.map(" in graph_jsx


def test_graph_view_status_legend_covers_all_four_statuses():
    graph_jsx = _graph_jsx()
    for status in ("accepted", "proposed", "reverted", "superseded"):
        assert f'"ui.graph.status_{status}"' in graph_jsx
        assert f'"ui.graph.status_{status}_style"' in graph_jsx


def test_graph_view_has_table_view_toggle_and_accessible_component():
    graph_jsx = _graph_jsx()
    assert "const [showTable, setShowTable] = useState(" in graph_jsx
    assert "function GraphTable(" in graph_jsx
    assert "<table" in graph_jsx
    assert "<caption>" in graph_jsx
    assert 'scope="col"' in graph_jsx


def test_graph_table_lists_required_columns():
    graph_jsx = _graph_jsx()
    table_block = graph_jsx[graph_jsx.index("function GraphTable(") :]
    for key in (
        "ui.graph.table_col_id",
        "ui.graph.table_col_title",
        "ui.graph.table_col_type",
        "ui.graph.table_col_status",
        "ui.graph.table_col_project",
        "ui.graph.table_col_degree",
    ):
        assert key in table_block


def test_graph_view_respects_prefers_reduced_motion():
    graph_jsx = _graph_jsx()
    assert "prefers-reduced-motion: reduce" in graph_jsx
    assert "reducedMotionRef" in graph_jsx
    assert "gr-edge-unexp{animation:none}" in graph_jsx


def test_graph_view_type_colors_are_the_validated_hexes():
    """TYPE_COLOR must stay exactly these two hexes — chosen independent of
    --accent (default cyan #22d3ee, and a user tweak to violet #9d8cff) so the
    type-color channel never collides with whatever accent the user picks.

    node validate_palette.js "#1f9e6f,#d9720f" --mode dark
      [PASS] Lightness band         all 2 inside L 0.48-0.67
      [PASS] Chroma floor           all 2 >= 0.1
      [PASS] CVD separation         worst adjacent #d9720f<->#1f9e6f dE 9.4 (protan) - tritan 29.3
      [PASS] Normal-vision floor    worst adjacent #d9720f<->#1f9e6f dE 23.4 (normal)
      [PASS] Contrast vs surface    all 2 >= 3:1
      -> ALL CHECKS PASS

    node validate_palette.js "#1f9e6f,#d9720f" --mode light
      [PASS] Lightness band         all 2 inside L 0.43-0.77
      [PASS] Chroma floor           all 2 >= 0.1
      [PASS] CVD separation         worst adjacent #d9720f<->#1f9e6f dE 9.4 (protan) - tritan 29.3
      [PASS] Normal-vision floor    worst adjacent #d9720f<->#1f9e6f dE 23.4 (normal)
      [PASS] Contrast vs surface    all 2 >= 3:1
      -> ALL CHECKS PASS

    Both hexes were also checked against each accent candidate (adjacent-pair
    CVD/normal-vision dE, --mode dark): #1f9e6f vs #22d3ee dE 20.0/20.6,
    #1f9e6f vs #9d8cff dE 20.0/27.4, #d9720f vs #22d3ee dE 24.6/31.9,
    #d9720f vs #9d8cff dE 29.2/29.3 — all comfortably clear of the 8.0/15.0
    targets, so the type colors read distinctly from either accent.
    """
    graph_jsx = _graph_jsx()
    start = graph_jsx.index("const TYPE_COLOR = {")
    end = graph_jsx.index("}", start)
    type_color_block = graph_jsx[start:end]
    assert "#1f9e6f" in type_color_block
    assert "#d9720f" in type_color_block


def test_graph_view_node_labels_use_high_contrast_text_color():
    graph_jsx = _graph_jsx()
    assert 'const LABEL_TEXT_COLOR = "var(--txt-hi)"' in graph_jsx
    assert "fill={LABEL_TEXT_COLOR}" in graph_jsx


# ---- Faz: gorsel/palet duzeltmeleri -----------------------------------------


def test_graph_view_focus_ring_is_neutral_not_accent():
    graph_jsx = _graph_jsx()
    assert 'const FOCUS_RING_COLOR = "var(--txt-hi)";' in graph_jsx
    assert 'stroke={isSelected ? "var(--accent)"' not in graph_jsx
    assert "stroke={(isHover || isSelected) ? FOCUS_RING_COLOR : (ring.color || col)}" in graph_jsx
    start = graph_jsx.index("stroke={e.unexpected")
    end = graph_jsx.index("\n", start)
    stroke_line = graph_jsx[start:end]
    assert "FOCUS_RING_COLOR" in stroke_line
    assert '"var(--accent)"' not in stroke_line


def test_graph_view_canvas_height_matches_content_not_side_panel_stretch():
    graph_jsx = _graph_jsx()
    wrap_start = graph_jsx.index(".gr-wrap{")
    wrap_rule = graph_jsx[wrap_start:graph_jsx.index("}", wrap_start)]
    assert "align-items:flex-start" in wrap_rule
    side_start = graph_jsx.index(".gr-side{")
    side_rule = graph_jsx[side_start:graph_jsx.index("}", side_start)]
    assert "overflow-y:auto" in side_rule
    assert "max-height" in side_rule


def test_graph_view_cluster_legend_colors_are_capped_to_top_rank():
    graph_jsx = _graph_jsx()
    assert "function clusterSwatchColor(" in graph_jsx
    assert "const CLUSTER_NEUTRAL_COLOR = " in graph_jsx
    assert "rank < CLUSTER_TOP_COUNT ? color : CLUSTER_NEUTRAL_COLOR" in graph_jsx
    assert "clusterSwatchColor(idx, c.color)" in graph_jsx
    assert '"ui.graph.legend_small_cluster"' in graph_jsx


def test_graph_view_focus_node_skips_pan_zoom_tween_when_reduced_motion():
    graph_jsx = _graph_jsx()
    start = graph_jsx.index("function focusNode(")
    end = graph_jsx.index("\n    }\n", start)
    block = graph_jsx[start:end]
    assert "reducedMotionRef.current" in block


def test_graph_view_neighbor_edge_type_uses_i18n_label():
    graph_jsx = _graph_jsx()
    assert "function edgeTypeLabel(" in graph_jsx
    assert "edgeTypeLabel(row.type)" in graph_jsx
    assert '<span className="ty">{row.type}</span>' not in graph_jsx


def test_graph_view_label_gap_is_converted_to_screen_units():
    graph_jsx = _graph_jsx()
    assert "const LABEL_GAP = " in graph_jsx
    assert "LABEL_GAP / view.zoom" in graph_jsx
    assert "y={r + 11}" not in graph_jsx


# ---- Faz: zoom-out kirpilma duzeltmesi (fit-to-content) --------------------


def test_graph_view_reset_button_calls_fit_not_static_zoom_one():
    graph_jsx = _graph_jsx()
    start = graph_jsx.index("function resetAll(")
    end = graph_jsx.index("\n    }\n", start)
    block = graph_jsx[start:end]
    assert "computeFitView(" in block
    assert "runFitTransition(" in block
    assert "{ zoom: 1, x: 0, y: 0 }" not in block


def test_graph_view_auto_fits_when_simulation_settles_or_filters_change():
    graph_jsx = _graph_jsx()
    assert "}, [settled, visibleIdSet, viewSize]);" in graph_jsx
    settle_effect_start = graph_jsx.index("if (!settled) return undefined;")
    settle_effect_block = graph_jsx[settle_effect_start:settle_effect_start + 400]
    assert "computeFitView(" in settle_effect_block
    assert "runFitTransition(" in settle_effect_block


def test_graph_view_fit_transition_skips_tween_on_reduced_motion():
    graph_jsx = _graph_jsx()
    start = graph_jsx.index("function runFitTransition(")
    end = graph_jsx.index("\n    }\n", start)
    block = graph_jsx[start:end]
    assert "reducedMotionRef.current" in block
    assert "setView(target)" in block


def test_graph_view_layout_is_unbounded_and_framed_by_fit():
    graph_jsx = _graph_jsx()

    def const_val(name):
        match = re.search(rf"\b{name}\s*=\s*([\d.]+)", graph_jsx)
        assert match, f"{name} not found"
        return float(match.group(1))

    max_r = const_val("MAX_R")
    bbox_padding = const_val("BBOX_LABEL_PADDING")
    halo_margin = const_val("CLUSTER_HALO_MARGIN")
    assert max_r > 17, "MAX_R must widen past the pre-fix 17 for importance to read"
    assert "NODE_MARGIN" not in graph_jsx, (
        "the layout must not clamp nodes to a fixed box: repulsion and springs settle "
        "their own spacing, and clamping compresses dense graphs into a block"
    )
    assert "radiusForImp(n.imp), BBOX_LABEL_PADDING" in graph_jsx, (
        "with no clamp, clipping is prevented by the fit pass measuring node radii"
    )
    assert bbox_padding >= halo_margin, "fit padding must at least contain the cluster halo"


def test_graph_view_layout_space_scales_with_node_count():
    graph_jsx = _graph_jsx()
    assert "function resizeLayoutSpace(" in graph_jsx
    assert "Math.sqrt(nodeCount / LAYOUT_BASE_NODES)" in graph_jsx, (
        "force layout spacing goes as sqrt(area/N), so the simulation space must grow "
        "with the node count or dense graphs collapse"
    )
    assert "resizeLayoutSpace(PM.nodes.length)" in graph_jsx


# ---- Faz: fit-to-content DAVRANIS testleri (node harness) ------------------

GRAPH_JSX_PATH = PM_STATIC / "views-graph.jsx"
FIT_FUNCTION_NAMES = ("clamp", "computeBoundingBox", "computeFitView", "clampPanToBounds")
FIT_CONSTANT_NAMES = (
    "W",
    "H",
    "MIN_ZOOM",
    "MAX_ZOOM",
    "MAX_FIT_ZOOM",
    "FIT_ZOOM_FLOOR",
    "FIT_PADDING",
    "MIN_VISIBLE_FRACTION",
    "DRAG_CLICK_THRESHOLD",
)
GEOMETRY_EPSILON = 1e-9
DRAG_HANDLER_HEADER = "const onCanvasMouseDown = (ev) => {"
DRAG_HANDLER_FUNCTION_HEADER = "function onCanvasMouseDown(ev) {"
FIT_CALL_DECLARATION_COUNT = 1

DRAG_SCENARIO_PRELUDE = """
let view = { zoom: 1, x: 0, y: 0 };
let bbox = null;
let lastView = null;
let isDragging = false;
let lastSelectedId = "unset";
const dragEvents = {};

function setView(next) { lastView = next; view = next; }
function setIsDragging(flag) { isDragging = flag; }
function setSelectedId(id) { lastSelectedId = id; }
function toSvgPoint(clientX, clientY) { return { x: clientX, y: clientY }; }

function runDragScenario(nextBBox, dragTo) {
  bbox = nextBBox;
  view = { zoom: 1, x: 0, y: 0 };
  lastView = null;
  Object.keys(dragEvents).forEach((key) => { delete dragEvents[key]; });
  window.addEventListener = function (type, fn) {
    if (!dragEvents[type]) dragEvents[type] = [];
    dragEvents[type].push(fn);
  };
  window.removeEventListener = function () {};
  onCanvasMouseDown({ button: 0, clientX: 0, clientY: 0, target: {} });
  if (!dragEvents.mousemove) throw new Error("drag handler registered no mousemove listener");
  dragEvents.mousemove.forEach((fn) => fn({ clientX: dragTo.x, clientY: dragTo.y }));
  if (!lastView) throw new Error("drag handler never called setView");
  return lastView;
}
"""


def _graph_constant(name):
    match = re.search(rf"(?:const|,)\s*{name}\s*=\s*(-?[\d.]+)", _graph_jsx())
    assert match, f"{name} constant not found in views-graph.jsx"
    return float(match.group(1))


def _fit_prelude_js():
    declarations = [f"const {name} = {_graph_constant(name)};" for name in FIT_CONSTANT_NAMES]
    fields = ", ".join(f"{name}: {name}" for name in FIT_CONSTANT_NAMES)
    declarations.append(f"function graphConstants() {{ return {{ {fields} }}; }}")
    return "\n".join(declarations)


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
    raise AssertionError(f"unbalanced braces after {header!r} in views-graph.jsx")


def _drag_handler_js():
    block = _extract_block(_graph_jsx(), DRAG_HANDLER_HEADER)
    return DRAG_HANDLER_FUNCTION_HEADER + block[len(DRAG_HANDLER_HEADER) :]


def _run_fit_js(script_body, extra_prelude=""):
    return run_extracted_functions(
        path=GRAPH_JSX_PATH,
        names=FIT_FUNCTION_NAMES,
        prelude_js="\n".join([_fit_prelude_js(), extra_prelude]),
        script_body=script_body,
    )


def _project(world_value, zoom, offset):
    return world_value * zoom + offset


def _visible_fraction(low, high, zoom, offset, viewport_size):
    screen_low = _project(low, zoom, offset)
    screen_high = _project(high, zoom, offset)
    span = screen_high - screen_low
    overlap = max(0.0, min(screen_high, viewport_size) - max(screen_low, 0.0))
    return overlap / span


def test_fit_view_shrinks_oversized_graph_until_every_corner_is_on_screen():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const viewport = { width: c.W, height: c.H };
        const bbox = { minX: -5000, minY: -4000, maxX: 5000, maxY: 4000 };
        const fit = computeFitView(bbox, viewport, c.FIT_PADDING);
        const corners = [
          [bbox.minX, bbox.minY], [bbox.maxX, bbox.minY],
          [bbox.minX, bbox.maxY], [bbox.maxX, bbox.maxY],
        ].map((p) => ({ x: p[0] * fit.zoom + fit.x, y: p[1] * fit.zoom + fit.y }));
        return {
          zoom: fit.zoom,
          corners: corners,
          spanW: (bbox.maxX - bbox.minX) * fit.zoom,
          spanH: (bbox.maxY - bbox.minY) * fit.zoom,
          viewport: viewport,
          padding: c.FIT_PADDING,
        };
        """
    )
    viewport = result["viewport"]
    assert result["zoom"] < 1, "a graph far larger than the canvas must be zoomed OUT, not in"
    for corner in result["corners"]:
        assert -GEOMETRY_EPSILON <= corner["x"] <= viewport["width"] + GEOMETRY_EPSILON, corner
        assert -GEOMETRY_EPSILON <= corner["y"] <= viewport["height"] + GEOMETRY_EPSILON, corner
    assert result["spanW"] <= viewport["width"] - 2 * result["padding"] + GEOMETRY_EPSILON
    assert result["spanH"] <= viewport["height"] - 2 * result["padding"] + GEOMETRY_EPSILON


def test_fit_view_caps_zoom_for_tiny_graphs_instead_of_over_magnifying():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const bbox = { minX: 495, minY: 275, maxX: 505, maxY: 285 };
        const fit = computeFitView(bbox, { width: c.W, height: c.H }, c.FIT_PADDING);
        return { zoom: fit.zoom, maxFitZoom: c.MAX_FIT_ZOOM };
        """
    )
    assert result["zoom"] == result["maxFitZoom"]


def test_fit_view_on_zero_area_bbox_stays_finite_and_within_zoom_bounds():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const bbox = { minX: 120, minY: 90, maxX: 120, maxY: 90 };
        const fit = computeFitView(bbox, { width: c.W, height: c.H }, c.FIT_PADDING);
        return {
          fit: fit,
          allFinite: Number.isFinite(fit.zoom) && Number.isFinite(fit.x) && Number.isFinite(fit.y),
          floor: c.FIT_ZOOM_FLOOR,
          ceiling: c.MAX_FIT_ZOOM,
          centerX: 120 * fit.zoom + fit.x,
          centerY: 90 * fit.zoom + fit.y,
          viewport: { width: c.W, height: c.H },
        };
        """
    )
    assert result["allFinite"] is True
    assert result["floor"] <= result["fit"]["zoom"] <= result["ceiling"]
    assert abs(result["centerX"] - result["viewport"]["width"] / 2) < GEOMETRY_EPSILON
    assert abs(result["centerY"] - result["viewport"]["height"] / 2) < GEOMETRY_EPSILON


def test_bounding_box_pads_by_radius_and_ignores_nodes_without_position():
    result = _run_fit_js(
        """
        const nodes = [{ id: "a" }, { id: "b" }, { id: "ghost" }];
        const posById = { a: { x: 0, y: 0 }, b: { x: 100, y: 50 } };
        return {
          bbox: computeBoundingBox(nodes, posById, () => 10, 5),
          empty: computeBoundingBox([], {}, () => 10, 5),
          allMissing: computeBoundingBox(nodes, {}, () => 10, 5),
        };
        """
    )
    assert result["bbox"] == {"minX": -15, "minY": -15, "maxX": 115, "maxY": 65}
    assert result["empty"] is None
    assert result["allMissing"] is None


def test_fit_view_of_empty_graph_falls_back_to_identity_without_throwing():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const bbox = computeBoundingBox([], {}, () => 10, 5);
        return {
          fit: computeFitView(bbox, { width: c.W, height: c.H }, c.FIT_PADDING),
          pan: clampPanToBounds({ zoom: 1, x: 42, y: -17 }, bbox, { width: c.W, height: c.H }, c.MIN_VISIBLE_FRACTION),
        };
        """
    )
    assert result["fit"] == {"zoom": 1, "x": 0, "y": 0}
    assert result["pan"] == {"x": 42, "y": -17}


def test_pan_clamp_keeps_min_visible_fraction_on_every_extreme_offset():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const viewport = { width: c.W, height: c.H };
        const bbox = { minX: 0, minY: 0, maxX: 400, maxY: 300 };
        const far = 1e6;
        const offsets = [
          { x: far, y: far }, { x: -far, y: -far },
          { x: far, y: -far }, { x: -far, y: far },
        ];
        return {
          bbox: bbox,
          viewport: viewport,
          fraction: c.MIN_VISIBLE_FRACTION,
          zoom: 0.8,
          clamped: offsets.map((o) => clampPanToBounds({ zoom: 0.8, x: o.x, y: o.y }, bbox, viewport, c.MIN_VISIBLE_FRACTION)),
        };
        """
    )
    bbox, viewport = result["bbox"], result["viewport"]
    for clamped in result["clamped"]:
        visible_x = _visible_fraction(bbox["minX"], bbox["maxX"], result["zoom"], clamped["x"], viewport["width"])
        visible_y = _visible_fraction(bbox["minY"], bbox["maxY"], result["zoom"], clamped["y"], viewport["height"])
        assert visible_x >= result["fraction"] - GEOMETRY_EPSILON, clamped
        assert visible_y >= result["fraction"] - GEOMETRY_EPSILON, clamped


def test_canvas_drag_of_a_million_pixels_still_leaves_the_graph_on_screen():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const bbox = { minX: 0, minY: 0, maxX: 400, maxY: 300 };
        return {
          bbox: bbox,
          viewport: { width: c.W, height: c.H },
          fraction: c.MIN_VISIBLE_FRACTION,
          away: runDragScenario(bbox, { x: 1e6, y: 1e6 }),
          back: runDragScenario(bbox, { x: -1e6, y: -1e6 }),
        };
        """,
        extra_prelude="\n".join([DRAG_SCENARIO_PRELUDE, _drag_handler_js()]),
    )
    bbox, viewport = result["bbox"], result["viewport"]
    for key in ("away", "back"):
        view = result[key]
        visible_x = _visible_fraction(bbox["minX"], bbox["maxX"], view["zoom"], view["x"], viewport["width"])
        visible_y = _visible_fraction(bbox["minY"], bbox["maxY"], view["zoom"], view["y"], viewport["height"])
        assert visible_x >= result["fraction"] - GEOMETRY_EPSILON, (key, view)
        assert visible_y >= result["fraction"] - GEOMETRY_EPSILON, (key, view)


def test_dynamic_min_zoom_lets_the_fitted_view_survive_the_wheel_clamp():
    result = _run_fit_js(
        """
        const c = graphConstants();
        const bbox = { minX: -6000, minY: -5000, maxX: 6000, maxY: 5000 };
        const fit = computeFitView(bbox, { width: c.W, height: c.H }, c.FIT_PADDING);
        const dynamicFloor = Math.min(c.MIN_ZOOM, fit.zoom * 0.5);
        return {
          fitZoom: fit.zoom,
          staticFloor: c.MIN_ZOOM,
          dynamicFloor: dynamicFloor,
          withDynamicFloor: clamp(fit.zoom, dynamicFloor, c.MAX_ZOOM),
          withStaticFloor: clamp(fit.zoom, c.MIN_ZOOM, c.MAX_ZOOM),
        };
        """
    )
    assert result["fitZoom"] < result["staticFloor"]
    assert result["dynamicFloor"] < result["fitZoom"]
    assert result["withDynamicFloor"] == result["fitZoom"]
    assert result["withStaticFloor"] == result["staticFloor"]


def test_every_fit_call_site_lowers_the_zoom_floor_to_match_the_fit():
    graph_jsx = _graph_jsx()
    call_sites = graph_jsx.count("computeFitView(") - FIT_CALL_DECLARATION_COUNT
    floor_updates = graph_jsx.count("minZoomRef.current = Math.min(MIN_ZOOM, fit.zoom * 0.5);")
    assert call_sites > 0
    assert floor_updates == call_sites


def test_both_pan_interactions_route_their_offset_through_the_clamp():
    graph_jsx = _graph_jsx()
    wheel_block = _extract_block(graph_jsx, "const onWheel = (ev) => {")
    drag_block = _extract_block(graph_jsx, DRAG_HANDLER_HEADER)
    for block in (wheel_block, drag_block):
        assert "clampPanToBounds(" in block
        assert "clamped.x" in block
        assert "clamped.y" in block
