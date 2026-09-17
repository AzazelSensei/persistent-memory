"""Real behaviour tests for the untrusted-text markdown renderer.

Every assertion here runs the actual ``static/pm/markdown.jsx`` module inside
node, so the security invariants are checked against the rendered element tree
instead of against the source text.
"""

import json

import pytest

from tests.daemon.jsx_runtime import (
    PM_STATIC_DIR,
    collect_nodes_by_type,
    extract_tree_text,
    iter_tree_nodes,
    run_js_source,
    run_jsx_module,
)

MARKDOWN_MODULE = "markdown.jsx"
MARKDOWN_PATH = PM_STATIC_DIR / MARKDOWN_MODULE

KNOWN_RECORDS_SETUP = 'window.PMUI = { pmById: (id) => ({ id, title: "kayit " + id }) };'
UNKNOWN_RECORDS_SETUP = "window.PMUI = { pmById: () => null };"

REDOS_LINE_LENGTH = 32000
REDOS_BUDGET_MS = 100


def _render_call(text):
    return f"return window.PMMarkdown.renderMarkdown({json.dumps(text)});"


def _render(text, setup_js=KNOWN_RECORDS_SETUP):
    return run_jsx_module(MARKDOWN_MODULE, _render_call(text), setup_js=setup_js)


def _render_many(texts, setup_js=KNOWN_RECORDS_SETUP):
    body = f"return {json.dumps(texts)}.map((t) => window.PMMarkdown.renderMarkdown(t));"
    return run_jsx_module(MARKDOWN_MODULE, body, setup_js=setup_js)


def _render_mutant(mutated_source, text, setup_js=KNOWN_RECORDS_SETUP):
    return run_js_source("\n".join([setup_js, mutated_source]), _render_call(text))


def _markdown_source():
    return MARKDOWN_PATH.read_text(encoding="utf-8")


def _mutate_source(old, new):
    source = _markdown_source()
    mutated = source.replace(old, new, 1)
    assert mutated != source, f"mutation did not apply: {old!r}"
    return mutated


def _node_types(tree):
    return [node["type"] for node in iter_tree_nodes(tree)]


def _clickable_ref_texts(tree):
    return [extract_tree_text(node) for node in collect_nodes_by_type(tree, "a")]


def _texts_of_type(tree, node_type):
    return [extract_tree_text(node) for node in collect_nodes_by_type(tree, node_type)]


def _all_prop_names(tree):
    names = set()
    for node in iter_tree_nodes(tree):
        names.update(node.get("props", {}).keys())
    return names


# --- inline nesting (references inside emphasis must stay clickable) ---------


def test_bold_wrapped_bracket_reference_stays_clickable():
    tree = _render("**[[D-0123]] karari**")
    strongs = collect_nodes_by_type(tree, "strong")
    assert len(strongs) == 1
    assert _clickable_ref_texts(strongs[0]) == ["D-0123"]
    assert extract_tree_text(tree) == "D-0123 karari"


def test_bold_wrapped_bare_reference_stays_clickable():
    tree = _render("**D-0123 karari**")
    strongs = collect_nodes_by_type(tree, "strong")
    assert _clickable_ref_texts(strongs[0]) == ["D-0123"]


def test_references_stay_clickable_inside_italic_strike_and_link_label():
    trees = _render_many(
        [
            "*bkz D-0123 sonu*",
            "~~eski D-0123 karari~~",
            "[bkz D-0123](https://ornek.test)",
            "*ic **[[D-0123]]** dis*",
        ]
    )
    assert _clickable_ref_texts(trees[0]) == ["D-0123"]
    assert _clickable_ref_texts(trees[1]) == ["D-0123"]
    assert _clickable_ref_texts(trees[2]) == ["D-0123"]
    assert _clickable_ref_texts(trees[3]) == ["D-0123"]
    assert collect_nodes_by_type(trees[0], "em")
    assert collect_nodes_by_type(trees[1], "del")
    assert collect_nodes_by_type(trees[3], "strong")


def test_nested_emphasis_does_not_leak_asterisk_markers_into_text():
    trees = _render_many(["**kalin [[D-0123]] son**", "**a *b* c**", "~~x **D-0123** y~~"])
    for tree in trees:
        assert "*" not in extract_tree_text(tree)
        assert "~" not in extract_tree_text(tree)
    assert _texts_of_type(trees[1], "em") == ["b"]
    assert _texts_of_type(trees[1], "strong") == ["a b c"]


BOLD_AROUND_GLOB_CASES = [
    (
        "- **Kayit dosyalarina (`docs/decisions/*.md`, `docs/lessons/*.md`) ASLA dokunma** - veri.",
        "Kayit dosyalarina (docs/decisions/*.md, docs/lessons/*.md) ASLA dokunma - veri.",
        ["docs/decisions/*.md", "docs/lessons/*.md"],
    ),
    (
        "**PG pending/running = 0 + COMPLETE_* = true** (veya %100 done) sonra bitmis.",
        "PG pending/running = 0 + COMPLETE_* = true (veya %100 done) sonra bitmis.",
        [],
    ),
    (
        "**access log'da `185.67.34.*` yok** - cunku firewall var.",
        "access log'da 185.67.34.* yok - cunku firewall var.",
        ["185.67.34.*"],
    ),
]


@pytest.mark.parametrize("source,expected_text,expected_codes", BOLD_AROUND_GLOB_CASES)
def test_bold_span_containing_a_glob_keeps_every_character(source, expected_text, expected_codes):
    tree = _render(source, setup_js=UNKNOWN_RECORDS_SETUP)
    assert extract_tree_text(tree) == expected_text
    assert _texts_of_type(tree, "code") == expected_codes
    assert collect_nodes_by_type(tree, "strong")
    assert collect_nodes_by_type(tree, "em") == []


def test_bracket_reference_alias_is_not_rendered_and_id_wins_over_link_syntax():
    trees = _render_many(["[[D-0123|baska baslik]]", "[[D-0123]](https://ornek.test)"])
    assert _clickable_ref_texts(trees[0]) == ["D-0123"]
    assert extract_tree_text(trees[0]) == "D-0123"
    assert _clickable_ref_texts(trees[1]) == ["D-0123"]


def test_deeply_nested_markers_terminate_without_recursion_error():
    tree = _render("*" + "**" * 12 + "D-0123" + "**" * 12 + "*")
    assert "D-0123" in extract_tree_text(tree)


def test_depth_limit_is_high_enough_for_every_reachable_nesting_chain():
    tree = _render("~~**[*D-0123*](https://ornek.test)**~~")
    assert collect_nodes_by_type(tree, "del")
    assert collect_nodes_by_type(tree, "strong")
    assert [span["props"]["className"] for span in collect_nodes_by_type(tree, "span")] == ["pm-md-link"]
    assert collect_nodes_by_type(tree, "em")
    assert _clickable_ref_texts(tree) == ["D-0123"]
    assert extract_tree_text(tree) == "D-0123"


def test_link_label_containing_brackets_is_not_treated_as_a_link():
    tree = _render("[bkz [1]](https://ornek.test) ve D-0123")
    assert collect_nodes_by_type(tree, "span") == []
    assert _clickable_ref_texts(tree) == ["D-0123"]
    assert "https://ornek.test" in extract_tree_text(tree)


# --- code spans must stay inert --------------------------------------------


def test_reference_inside_code_span_is_not_clickable():
    tree = _render("`D-0001 gibi bir kimlik`")
    codes = collect_nodes_by_type(tree, "code")
    assert len(codes) == 1
    assert extract_tree_text(codes[0]) == "D-0001 gibi bir kimlik"
    assert _clickable_ref_texts(tree) == []
    assert collect_nodes_by_type(tree, "span") == []


def test_code_span_swallows_bracket_reference_and_emphasis_markers():
    tree = _render("`[[D-0123]] ve **kalin**`")
    assert extract_tree_text(tree) == "[[D-0123]] ve **kalin**"
    assert _clickable_ref_texts(tree) == []
    assert collect_nodes_by_type(tree, "strong") == []


def test_reference_outside_a_code_span_is_still_clickable():
    tree = _render("D-0123 ve `kod` daha")
    assert _clickable_ref_texts(tree) == ["D-0123"]
    assert _texts_of_type(tree, "code") == ["kod"]


def test_fenced_code_block_content_is_never_turned_into_references():
    tree = _render("```py\nid = 'D-0001'\n**kalin**\n```")
    assert _clickable_ref_texts(tree) == []
    assert collect_nodes_by_type(tree, "strong") == []
    assert _texts_of_type(tree, "pre") == ["id = 'D-0001'\n**kalin**"]


MUTATIONS_THAT_MUST_LEAK_A_CODE_SPAN_REFERENCE = [
    pytest.param(
        "{ regex: CODE_SPAN_RE, build: buildCodeSpanNode },",
        "",
        id="code-span-rule-dropped",
    ),
    pytest.param(
        'h("code", { key: nextKey(ctx), className: "pm-md-code-inline" }, m[1])',
        'h("code", { key: nextKey(ctx), className: "pm-md-code-inline" }, renderNestedInline(m[1], ctx))',
        id="code-span-content-recursed",
    ),
    pytest.param(
        "    const pending = INLINE_RULES.map((rule) => findNextRuleMatch(text, rule, 0));",
        "    const pending = INLINE_RULES.slice(1).concat(INLINE_RULES[0])"
        ".map((rule) => findNextRuleMatch(text, rule, 0));",
        id="rule-order-desynced-from-pending",
    ),
]


@pytest.mark.parametrize("old,new", MUTATIONS_THAT_MUST_LEAK_A_CODE_SPAN_REFERENCE)
def test_code_span_inertness_test_actually_detects_a_broken_renderer(old, new):
    tree = _render_mutant(_mutate_source(old, new), "`D-0001 gibi bir kimlik`")
    leaked = _clickable_ref_texts(tree) or _texts_of_type(tree, "code") != ["D-0001 gibi bir kimlik"]
    assert leaked, "mutation left the renderer intact; the inertness test proves nothing"


# --- link syntax must never become navigable --------------------------------


LINK_ATTACK_INPUTS = [
    "[tikla](https://ornek.test)",
    "[tikla](javascript:alert)",
    "[tikla](JaVaScRiPt:alert)",
    "[tikla](data:text/html;base64,PHNjcmlwdD4=)",
    "[tikla](vbscript:msgbox)",
    "[](https://ornek.test)",
    "[[tikla]](javascript:alert)",
    "![resim](javascript:alert)",
]


def test_link_syntax_never_produces_an_anchor_or_href_prop():
    trees = _render_many(LINK_ATTACK_INPUTS, setup_js=UNKNOWN_RECORDS_SETUP)
    for source, tree in zip(LINK_ATTACK_INPUTS, trees):
        assert collect_nodes_by_type(tree, "a") == [], source
        assert "href" not in _all_prop_names(tree), source
        assert "src" not in _all_prop_names(tree), source
        assert "dangerouslySetInnerHTML" not in _all_prop_names(tree), source


def test_link_label_renders_as_plain_span_with_url_only_in_title():
    tree = _render("[tikla](https://ornek.test)", setup_js=UNKNOWN_RECORDS_SETUP)
    spans = collect_nodes_by_type(tree, "span")
    assert len(spans) == 1
    assert spans[0]["props"]["className"] == "pm-md-link"
    assert spans[0]["props"]["title"] == "https://ornek.test"
    assert extract_tree_text(spans[0]) == "tikla"


def test_only_record_references_ever_produce_an_anchor_element():
    tree = _render("[tikla](javascript:alert) ve D-0123 ve [[L-0007]]")
    anchors = collect_nodes_by_type(tree, "a")
    assert [extract_tree_text(a) for a in anchors] == ["D-0123", "L-0007"]
    for anchor in anchors:
        assert set(anchor["props"]) == {"key", "className", "title", "onClick"}


def test_unknown_record_reference_is_inert_span_not_anchor():
    tree = _render("bkz D-0213", setup_js=UNKNOWN_RECORDS_SETUP)
    spans = collect_nodes_by_type(tree, "span")
    assert [span["props"]["className"] for span in spans] == ["pm-ref missing"]
    assert collect_nodes_by_type(tree, "a") == []


def test_renderer_never_emits_a_raw_html_bearing_prop_for_hostile_input():
    hostile = "<img src=x onerror=alert(1)> & <script>alert(1)</script> **D-0123**"
    tree = _render(hostile)
    assert "dangerouslySetInnerHTML" not in _all_prop_names(tree)
    assert "script" not in _node_types(tree)
    assert "img" not in _node_types(tree)
    assert "<script>alert(1)</script>" in extract_tree_text(tree)


# --- italic rule, verified in node rather than in python re -----------------


ITALIC_CASES = [
    ("council_post ile board a yazabiliyorum ve council_read", []),
    ("PM_COUNCIL_READONLY=1 ve MAX_TOTAL_TURN_CALLS", []),
    ("turn in (None, round_number) kosulu", []),
    ("2 * 3 * 4 = 24", []),
    ("ag_izleme_ servisi", []),
    ("cok_katmanli_yapi", []),
    ("yigin_izleme_ hatasi", []),
    ("_italik_ metin", ["italik"]),
    ("bu *vurgu* olmali", ["vurgu"]),
    ("sonunda _vurgu_.", ["vurgu"]),
    ("bir *iki* uc _dort_ bes", ["iki", "dort"]),
    ("_agirlik_ onemli", ["agirlik"]),
]

ITALIC_UNICODE_CASES = [
    ("_ağırlık_ onemli", ["ağırlık"]),
    ("şu _değişken_ adı", ["değişken"]),
    ("_çok katmanlı_ yapı", ["çok katmanlı"]),
]

ITALIC_UNICODE_SNAKE_CASE_LEAKS = [
    ("ağ_izleme_ servisi", []),
    ("yığın_izleme_ hatası", []),
    ("çöp_toplama_ suresi", []),
]


def test_italic_rule_leaves_snake_case_identifiers_alone_in_the_browser_engine():
    texts = [case[0] for case in ITALIC_CASES]
    trees = _render_many(texts, setup_js=UNKNOWN_RECORDS_SETUP)
    found = [_texts_of_type(tree, "em") for tree in trees]
    assert found == [case[1] for case in ITALIC_CASES]


def test_italic_rule_emphasises_unicode_words_in_the_browser_engine():
    texts = [case[0] for case in ITALIC_UNICODE_CASES]
    trees = _render_many(texts, setup_js=UNKNOWN_RECORDS_SETUP)
    found = [_texts_of_type(tree, "em") for tree in trees]
    assert found == [case[1] for case in ITALIC_UNICODE_CASES]


def test_italic_rule_leaves_unicode_snake_case_identifiers_alone():
    texts = [case[0] for case in ITALIC_UNICODE_SNAKE_CASE_LEAKS]
    trees = _render_many(texts, setup_js=UNKNOWN_RECORDS_SETUP)
    found = [_texts_of_type(tree, "em") for tree in trees]
    assert found == [case[1] for case in ITALIC_UNICODE_SNAKE_CASE_LEAKS]


# --- object-shape safety ----------------------------------------------------


PROTOTYPE_POLLUTION_INPUTS = [
    "[[__proto__]] ve [[constructor]] ve [[prototype]]",
    "[[D-0123|__proto__]] karari",
    "__proto__ D-0123 constructor",
    "[__proto__](javascript:alert)",
    "`__proto__`",
]


def test_hostile_reference_ids_do_not_pollute_object_prototype():
    probe = run_jsx_module(
        MARKDOWN_MODULE,
        f"{json.dumps(PROTOTYPE_POLLUTION_INPUTS)}.forEach("
        "(t) => window.PMMarkdown.renderMarkdown(t));"
        "return {"
        "  polluted: {}.polluted === undefined ? null : {}.polluted,"
        "  protoKeys: Object.getOwnPropertyNames(Object.prototype).length,"
        "  isPrototypeIntact: Object.getPrototypeOf({}) === Object.prototype,"
        "};",
        setup_js=KNOWN_RECORDS_SETUP,
    )
    assert probe["polluted"] is None
    assert probe["isPrototypeIntact"] is True
    assert probe["protoKeys"] > 0


def test_reference_lookup_only_ever_receives_well_formed_record_ids():
    seen = run_jsx_module(
        MARKDOWN_MODULE,
        "const seen = [];"
        "window.PMUI = { pmById: (id) => { seen.push(id); return null; } };"
        '["[[__proto__]]", "[[D-0123|__proto__]]", "__proto__ D-0123", "[[L-0007]]", "P-9999"]'
        ".forEach((t) => window.PMMarkdown.renderMarkdown(t));"
        "return seen;",
    )
    assert seen == ["D-0123", "D-0123", "L-0007", "P-9999"]


# --- purity -----------------------------------------------------------------


def test_render_markdown_is_pure_across_repeated_calls():
    text = "# Baslik\n\n**[[D-0123]]** ve `kod` ve *ital*\n\n- madde D-0124\n"
    both = run_jsx_module(
        MARKDOWN_MODULE,
        f"const text = {json.dumps(text)};"
        "const first = window.PMMarkdown.renderMarkdown(text);"
        "const second = window.PMMarkdown.renderMarkdown(text);"
        "return { first, second, same: JSON.stringify(first) === JSON.stringify(second) };",
        setup_js=KNOWN_RECORDS_SETUP,
    )
    assert both["same"] is True
    assert both["first"] == both["second"]


def test_render_markdown_returns_empty_tree_for_empty_and_missing_input():
    empties = run_jsx_module(
        MARKDOWN_MODULE,
        "return ["
        '  window.PMMarkdown.renderMarkdown(""),'
        "  window.PMMarkdown.renderMarkdown(null),"
        "  window.PMMarkdown.renderMarkdown(undefined),"
        "];",
        setup_js=UNKNOWN_RECORDS_SETUP,
    )
    assert empties == [[], [], []]


# --- adversarial input must not stall the tab -------------------------------


ADVERSARIAL_LINES = {
    "open-brackets": '"[".repeat(N)',
    "unterminated-link": '"[a](" + "x".repeat(N)',
    "asterisks": '"*".repeat(N)',
    "underscores": '"_".repeat(N)',
    "backticks": '"`".repeat(N)',
    "bracket-soup": '"*[`~_D-0001".repeat(Math.floor(N / 11))',
}


def test_adversarial_single_line_input_renders_in_linear_time():
    body = (
        f"const N = {REDOS_LINE_LENGTH};"
        f"const cases = {json.dumps(ADVERSARIAL_LINES)};"
        "const out = {};"
        "Object.keys(cases).forEach((name) => {"
        "  const line = eval(cases[name]);"
        "  const started = process.hrtime.bigint();"
        "  window.PMMarkdown.renderMarkdown(line);"
        "  out[name] = Number(process.hrtime.bigint() - started) / 1e6;"
        "});"
        "return out;"
    )
    timings = run_jsx_module(MARKDOWN_MODULE, body, setup_js=UNKNOWN_RECORDS_SETUP)
    assert set(timings) == set(ADVERSARIAL_LINES)
    slow = {name: ms for name, ms in timings.items() if ms >= REDOS_BUDGET_MS}
    assert not slow, f"quadratic backtracking is back: {slow} (budget {REDOS_BUDGET_MS}ms)"


def test_link_scan_cost_does_not_explode_when_the_line_doubles():
    body = (
        f"const N = {REDOS_LINE_LENGTH};"
        "const time = (line) => {"
        "  const started = process.hrtime.bigint();"
        "  window.PMMarkdown.renderMarkdown(line);"
        "  return Number(process.hrtime.bigint() - started) / 1e6;"
        "};"
        'time("[".repeat(1000));'
        'return { single: time("[".repeat(N)), doubled: time("[".repeat(N * 2)) };'
    )
    timings = run_jsx_module(MARKDOWN_MODULE, body, setup_js=UNKNOWN_RECORDS_SETUP)
    assert timings["single"] < REDOS_BUDGET_MS
    assert timings["doubled"] < REDOS_BUDGET_MS


# --- block level structure --------------------------------------------------


def test_headings_never_render_as_h1_or_h2():
    trees = _render_many(
        ["# bir", "## iki", "### uc", "#### dort", "##### bes", "###### alti"],
        setup_js=UNKNOWN_RECORDS_SETUP,
    )
    assert [tree[0]["type"] for tree in trees] == ["h3", "h3", "h4", "h4", "h5", "h5"]
    for tree in trees:
        assert tree[0]["props"]["className"] == "pm-md-heading"


def test_block_constructs_render_as_their_semantic_elements():
    trees = _render_many(
        [
            "- bir\n- iki",
            "1. bir\n2. iki",
            "> alinti\n> devam",
            "---",
            "| a | b |\n| --- | --- |\n| 1 | 2 |",
            "```js\nconst x = 1;\n```",
        ],
        setup_js=UNKNOWN_RECORDS_SETUP,
    )
    assert [node["type"] for node in collect_nodes_by_type(trees[0], "ul", "li")] == ["ul", "li", "li"]
    assert [node["type"] for node in collect_nodes_by_type(trees[1], "ol", "li")] == ["ol", "li", "li"]
    assert extract_tree_text(trees[2]) == "alintidevam"
    assert collect_nodes_by_type(trees[2], "blockquote")
    assert [node["type"] for node in trees[3]] == ["hr"]
    assert [node["type"] for node in collect_nodes_by_type(trees[4], "table", "th", "td")] == [
        "table",
        "th",
        "th",
        "td",
        "td",
    ]
    assert _texts_of_type(trees[5], "pre") == ["const x = 1;"]


def test_emphasis_marks_render_as_strong_em_and_del():
    tree = _render("**kalin** *ital* ~~ustu~~ `kod`", setup_js=UNKNOWN_RECORDS_SETUP)
    assert _texts_of_type(tree, "strong") == ["kalin"]
    assert _texts_of_type(tree, "em") == ["ital"]
    assert _texts_of_type(tree, "del") == ["ustu"]
    assert _texts_of_type(tree, "code") == ["kod"]


def test_every_sibling_node_in_a_rendered_tree_carries_a_unique_key():
    tree = _render("**[[D-0123]]** *a* `b` [c](d) D-0124 ~~e~~")
    keys = [node["props"].get("key") for node in iter_tree_nodes(tree) if node["props"].get("key")]
    assert len(keys) == len(set(keys))
