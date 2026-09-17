import pytest

from tests.daemon.jsx_runtime import (
    FUNCTION_MARKER,
    PM_STATIC_DIR,
    JsxExtractionError,
    JsxRuntimeError,
    collect_nodes_by_type,
    extract_functions,
    extract_tree_text,
    has_node_type,
    run_extracted_functions,
    run_jsx_module,
)

MARKDOWN_MODULE = "markdown.jsx"
GRAPH_MODULE_PATH = PM_STATIC_DIR / "views-graph.jsx"
SCENE_MODULE_PATH = PM_STATIC_DIR / "views-council-scene.jsx"
GRAPH_VIEW_PRELUDE = "const W = 1000; const H = 600; const FIT_ZOOM_FLOOR = 0.2; const MAX_FIT_ZOOM = 2;"


def _render_markdown(text):
    literal = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return run_jsx_module(MARKDOWN_MODULE, f'return window.PMMarkdown.renderMarkdown("{literal}");')


def test_harness_loads_markdown_module_and_exposes_render_function():
    exported = run_jsx_module(
        MARKDOWN_MODULE,
        "return { keys: Object.keys(window.PMMarkdown), kind: typeof window.PMMarkdown.renderMarkdown };",
    )
    assert exported == {"keys": ["renderMarkdown"], "kind": "function"}


def test_render_markdown_bold_produces_strong_node_in_tree():
    tree = _render_markdown("**kalin**")
    strongs = collect_nodes_by_type(tree, "strong")
    assert len(strongs) == 1
    assert extract_tree_text(strongs[0]) == "kalin"
    assert has_node_type(tree, "strong") is True


def test_render_markdown_bold_wraps_strong_in_paragraph_and_keeps_text():
    tree = _render_markdown("**kalin**")
    assert [node["type"] for node in tree] == ["p"]
    assert tree[0]["props"]["className"] == "pm-md-p"
    assert extract_tree_text(tree) == "kalin"
    assert tree[0]["children"][0]["type"] == "strong"


def test_render_markdown_link_syntax_never_yields_clickable_anchor():
    tree = _render_markdown("[tikla](https://example.com)")
    assert collect_nodes_by_type(tree, "a") == []
    spans = collect_nodes_by_type(tree, "span")
    assert len(spans) == 1
    assert spans[0]["props"]["title"] == "https://example.com"
    assert extract_tree_text(spans[0]) == "tikla"


def test_render_markdown_table_builds_real_table_elements():
    tree = _render_markdown("| a | b |\n| --- | --- |\n| 1 | `x` |")
    types = [node["type"] for node in collect_nodes_by_type(tree, "table", "th", "td", "code")]
    assert types == ["table", "th", "th", "td", "td", "code"]
    assert extract_tree_text(tree) == "ab1x"


def test_render_markdown_record_reference_becomes_missing_span_without_registry():
    tree = _render_markdown("bkz D-0213")
    spans = collect_nodes_by_type(tree, "span")
    assert [span["props"]["className"] for span in spans] == ["pm-ref missing"]
    assert collect_nodes_by_type(tree, "a") == []


def test_render_markdown_record_reference_becomes_anchor_when_registry_knows_it():
    setup_js = 'window.PMUI = { pmById: (id) => ({ id, title: "kayit " + id }) };'
    tree = run_jsx_module(
        MARKDOWN_MODULE,
        'return window.PMMarkdown.renderMarkdown("bkz D-0213");',
        setup_js=setup_js,
    )
    anchors = collect_nodes_by_type(tree, "a")
    assert len(anchors) == 1
    assert anchors[0]["props"]["title"] == "kayit D-0213"
    assert anchors[0]["props"]["onClick"] == FUNCTION_MARKER
    assert "href" not in anchors[0]["props"]


def test_render_markdown_returns_empty_tree_for_blank_input():
    assert _render_markdown("") == []


def test_harness_reports_node_errors_with_stderr_detail():
    with pytest.raises(JsxRuntimeError) as excinfo:
        run_jsx_module(MARKDOWN_MODULE, "throw new Error('deliberate harness failure');")
    assert "deliberate harness failure" in str(excinfo.value)


def test_harness_rejects_unknown_module_name():
    with pytest.raises(JsxRuntimeError):
        run_jsx_module("no-such-module.jsx", "return 1;")


def test_extract_functions_pulls_pure_helpers_out_of_jsx_file():
    source = extract_functions(GRAPH_MODULE_PATH, ["clamp", "computeFitView"])
    assert source.startswith("function clamp(")
    assert "function computeFitView(bbox, viewport, padding)" in source
    assert "React.createElement" not in source


def test_extracted_graph_helpers_run_under_node():
    result = run_extracted_functions(
        path=GRAPH_MODULE_PATH,
        names=["clamp", "computeFitView", "clampPanToBounds"],
        prelude_js=GRAPH_VIEW_PRELUDE,
        script_body=(
            "const bbox = { minX: 0, minY: 0, maxX: 100, maxY: 100 };"
            "const viewport = { width: 400, height: 400 };"
            "return {"
            "  fit: computeFitView(bbox, viewport, 20),"
            "  fallback: computeFitView(null, viewport, 20),"
            "  panned: clampPanToBounds({ x: 99999, y: -99999, zoom: 1 }, bbox, viewport, 0.25),"
            "};"
        ),
    )
    assert result["fit"] == {"zoom": 2, "x": 100, "y": 100}
    assert result["fallback"] == {"zoom": 1, "x": 0, "y": 0}
    assert result["panned"]["x"] < 99999
    assert result["panned"]["y"] > -99999


def test_extract_functions_handles_jsx_module_with_template_and_regex_bodies():
    source = extract_functions(SCENE_MODULE_PATH, ["isRoundComplete", "plainPreview"])
    assert source.count("function ") == 2
    assert source.rstrip().endswith("}")


def test_extract_functions_fails_loudly_on_unknown_name():
    with pytest.raises(JsxExtractionError) as excinfo:
        extract_functions(GRAPH_MODULE_PATH, ["thisFunctionDoesNotExist"])
    assert "thisFunctionDoesNotExist" in str(excinfo.value)
    assert "views-graph.jsx" in str(excinfo.value)


def test_extract_functions_fails_loudly_on_missing_file_and_empty_name_list():
    with pytest.raises(JsxExtractionError):
        extract_functions(PM_STATIC_DIR / "nope.jsx", ["clamp"])
    with pytest.raises(JsxExtractionError):
        extract_functions(GRAPH_MODULE_PATH, [])
