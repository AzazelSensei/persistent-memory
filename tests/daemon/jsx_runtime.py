"""Node-backed behaviour harness for the dashboard's static/pm/*.jsx modules.

The dashboard has no build step: every ``static/pm/*.jsx`` file is an IIFE that
writes onto ``window``. This module loads such a file inside node with stub
``window`` / ``document`` / ``React`` globals so tests can assert on real
runtime behaviour instead of on source text.

``React.createElement`` is stubbed into a plain ``{type, props, children}``
tree, which survives ``JSON.stringify`` and comes back to Python as nested
dicts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

import pytest

from persistent_memory.daemon.app import STATIC_DIR

PM_STATIC_DIR = STATIC_DIR / "pm"

NODE_TIMEOUT_SECONDS = 30
RESULT_SENTINEL = "__PM_JSX_RESULT__"
FUNCTION_MARKER = "[function]"
NODE_MISSING_REASON = "node is not installed; jsx behaviour tests need node >= 22"

REGEX_PRECEDING_CHARS = set("(,=:[!&|?{};+-*%~^<>\n")
FUNCTION_KEYWORD = "function"


class JsxExtractionError(AssertionError):
    """Raised when a named function cannot be carved out of a .jsx file."""


class JsxRuntimeError(AssertionError):
    """Raised when the node subprocess fails, times out or returns garbage."""


_RUNTIME_PRELUDE = r"""
const FUNCTION_MARKER = "__PM_FUNCTION_MARKER__";

function normalizeChildren(items) {
  const out = [];
  items.forEach((item) => {
    if (Array.isArray(item)) {
      normalizeChildren(item).forEach((child) => out.push(child));
      return;
    }
    if (item === null || item === undefined || item === false || item === true) return;
    out.push(item);
  });
  return out;
}

function serializeProps(props) {
  if (!props) return {};
  const out = {};
  Object.keys(props).forEach((key) => {
    const value = props[key];
    out[key] = typeof value === "function" ? FUNCTION_MARKER : value;
  });
  return out;
}

function resolveElementType(type) {
  if (typeof type === "function") return type.name || "component";
  if (type === null || type === undefined) return "unknown";
  return type;
}

function createElement(type, props, ...children) {
  return {
    type: resolveElementType(type),
    props: serializeProps(props),
    children: normalizeChildren(children),
  };
}

function createStubNode(tag) {
  return {
    tagName: tag,
    id: "",
    className: "",
    textContent: "",
    style: {},
    children: [],
    setAttribute() {},
    getAttribute() { return null; },
    appendChild(child) { this.children.push(child); return child; },
    removeChild() {},
    addEventListener() {},
    removeEventListener() {},
  };
}

const documentStub = {
  getElementById() { return null; },
  createElement(tag) { return createStubNode(tag); },
  createElementNS(ns, tag) { return createStubNode(tag); },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {},
  removeEventListener() {},
  head: { appendChild() {} },
  body: { appendChild() {} },
};

const reactStub = {
  createElement,
  Fragment: "Fragment",
  useState(initial) { return [typeof initial === "function" ? initial() : initial, function setState() {}]; },
  useEffect() {},
  useLayoutEffect() {},
  useMemo(factory) { return factory(); },
  useCallback(fn) { return fn; },
  useRef(initial) { return { current: initial === undefined ? null : initial }; },
  memo(component) { return component; },
};

const windowStub = {
  React: reactStub,
  document: documentStub,
  devicePixelRatio: 1,
  location: { href: "http://localhost/", pathname: "/", search: "", hash: "" },
  addEventListener() {},
  removeEventListener() {},
  requestAnimationFrame() { return 0; },
  cancelAnimationFrame() {},
  matchMedia() {
    return { matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} };
  },
  getComputedStyle() { return { getPropertyValue() { return ""; } }; },
};

globalThis.window = windowStub;
globalThis.document = documentStub;
globalThis.React = reactStub;
globalThis.navigator = globalThis.navigator || { userAgent: "node", language: "en" };

function reportResult(value) {
  const payload = JSON.stringify({ value: value === undefined ? null : value });
  process.stdout.write("\n" + "__PM_RESULT_SENTINEL__" + payload + "\n");
}
"""


def _build_runtime_prelude() -> str:
    return _RUNTIME_PRELUDE.replace("__PM_FUNCTION_MARKER__", FUNCTION_MARKER).replace(
        "__PM_RESULT_SENTINEL__", RESULT_SENTINEL
    )


def require_node() -> str:
    """Return the node binary path, skipping the test when node is absent."""
    node_path = shutil.which("node")
    if not node_path:
        pytest.skip(NODE_MISSING_REASON)
    return node_path


def _run_node_script(script: str, *, timeout: int) -> Any:
    node_path = require_node()
    with tempfile.TemporaryDirectory(prefix="pm-jsx-") as tmp_dir:
        script_path = Path(tmp_dir) / "harness.js"
        script_path.write_text(script, encoding="utf-8")
        try:
            completed = subprocess.run(
                [node_path, str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise JsxRuntimeError(
                f"node harness timed out after {timeout}s; stdout={exc.stdout!r} stderr={exc.stderr!r}"
            ) from exc

    if completed.returncode != 0:
        raise JsxRuntimeError(
            f"node harness exited with {completed.returncode}\n"
            f"--- stderr ---\n{completed.stderr}\n--- stdout ---\n{completed.stdout}"
        )
    return _parse_harness_output(completed.stdout, completed.stderr)


def _parse_harness_output(stdout: str, stderr: str) -> Any:
    for line in reversed(stdout.splitlines()):
        if not line.startswith(RESULT_SENTINEL):
            continue
        payload = line[len(RESULT_SENTINEL) :]
        try:
            return json.loads(payload)["value"]
        except (ValueError, KeyError) as exc:
            raise JsxRuntimeError(f"node harness produced unreadable result line: {payload!r}") from exc
    raise JsxRuntimeError(
        f"node harness produced no result line\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )


def _wrap_script_body(body: str, load_js: str) -> str:
    return "\n".join(
        [
            _build_runtime_prelude(),
            "try {",
            load_js,
            "  const value = (function () {",
            body,
            "  })();",
            "  reportResult(value);",
            "} catch (err) {",
            '  process.stderr.write(String((err && err.stack) || err) + "\\n");',
            "  process.exit(1);",
            "}",
        ]
    )


def resolve_module_path(module_name: str) -> Path:
    path = PM_STATIC_DIR / module_name
    if not path.is_file():
        raise JsxRuntimeError(f"jsx module not found: {path}")
    return path


def run_jsx_module(
    module_name: str,
    script_body: str,
    *,
    setup_js: str = "",
    timeout: int = NODE_TIMEOUT_SECONDS,
) -> Any:
    """Load ``static/pm/<module_name>`` in node, then run ``script_body``.

    ``script_body`` is a function body: it must ``return`` a JSON-serializable
    value, which is handed back as a Python object.
    """
    module_path = resolve_module_path(module_name)
    load_js = "\n".join(
        [
            setup_js,
            f"  const moduleSource = require('fs').readFileSync({json.dumps(str(module_path))}, 'utf8');",
            "  (0, eval)(moduleSource);",
        ]
    )
    return _run_node_script(_wrap_script_body(script_body, load_js), timeout=timeout)


def run_js_source(
    source_js: str,
    script_body: str,
    *,
    timeout: int = NODE_TIMEOUT_SECONDS,
) -> Any:
    """Evaluate arbitrary JS (e.g. extracted functions), then run ``script_body``."""
    load_js = f"  (0, eval)({json.dumps(source_js)});"
    return _run_node_script(_wrap_script_body(script_body, load_js), timeout=timeout)


def run_extracted_functions(
    *,
    path: Path | str,
    names: Iterable[str],
    script_body: str,
    prelude_js: str = "",
    timeout: int = NODE_TIMEOUT_SECONDS,
) -> Any:
    """Carve the named pure functions out of a .jsx file and run them in node."""
    extracted = extract_functions(path, names)
    return run_js_source("\n".join([prelude_js, extracted]), script_body, timeout=timeout)


def _skip_line_comment(source: str, index: int) -> int:
    end = source.find("\n", index)
    return len(source) if end < 0 else end + 1


def _skip_block_comment(source: str, index: int) -> int:
    end = source.find("*/", index + 2)
    if end < 0:
        raise JsxExtractionError("unterminated block comment while scanning jsx source")
    return end + 2


def _skip_quoted(source: str, index: int) -> int:
    quote = source[index]
    i = index + 1
    while i < len(source):
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == quote:
            return i + 1
        if ch == "\n":
            raise JsxExtractionError("unterminated string literal while scanning jsx source")
        i += 1
    raise JsxExtractionError("unterminated string literal while scanning jsx source")


def _skip_template(source: str, index: int) -> int:
    i = index + 1
    while i < len(source):
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            return i + 1
        if source[i : i + 2] == "${":
            i = _skip_substitution(source, i + 2)
            continue
        i += 1
    raise JsxExtractionError("unterminated template literal while scanning jsx source")


def _skip_substitution(source: str, index: int) -> int:
    depth = 1
    i = index
    while i < len(source):
        ch = source[i]
        if ch == "`":
            i = _skip_template(source, i)
            continue
        if ch in "\"'":
            i = _skip_quoted(source, i)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise JsxExtractionError("unterminated template substitution while scanning jsx source")


def _skip_regex(source: str, index: int) -> int:
    i = index + 1
    in_class = False
    while i < len(source):
        ch = source[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return i + 1
        elif ch == "\n":
            raise JsxExtractionError("unterminated regex literal while scanning jsx source")
        i += 1
    raise JsxExtractionError("unterminated regex literal while scanning jsx source")


def _is_regex_position(previous_char: str) -> bool:
    if not previous_char:
        return True
    return previous_char in REGEX_PRECEDING_CHARS


def _find_function_start(source: str, name: str, path: Path) -> int:
    pattern = re.compile(r"(?:^|[^\w$.])" + FUNCTION_KEYWORD + r"\s+" + re.escape(name) + r"\s*\(")
    match = pattern.search(source)
    if not match:
        raise JsxExtractionError(f"function {name!r} not found in {path}")
    return source.index(FUNCTION_KEYWORD, match.start())


def _find_function_end(source: str, start: int, name: str, path: Path) -> int:
    i = start
    depth = 0
    has_opened = False
    previous_char = ""
    total = len(source)
    while i < total:
        pair = source[i : i + 2]
        ch = source[i]
        if pair == "//":
            i = _skip_line_comment(source, i)
            continue
        if pair == "/*":
            i = _skip_block_comment(source, i)
            continue
        if ch in "\"'":
            i = _skip_quoted(source, i)
            previous_char = '"'
            continue
        if ch == "`":
            i = _skip_template(source, i)
            previous_char = "`"
            continue
        if ch == "/" and _is_regex_position(previous_char):
            i = _skip_regex(source, i)
            previous_char = "/"
            continue
        if ch == "{":
            depth += 1
            has_opened = True
        elif ch == "}":
            depth -= 1
            if has_opened and depth == 0:
                return i + 1
            if depth < 0:
                raise JsxExtractionError(f"unbalanced braces while extracting {name!r} from {path}")
        if not ch.isspace():
            previous_char = ch
        i += 1
    raise JsxExtractionError(f"unterminated body while extracting {name!r} from {path}")


def extract_functions(path: Path | str, names: Iterable[str]) -> str:
    """Return the source of the named top-level ``function`` declarations.

    Braces are counted while skipping strings, templates, comments and regex
    literals. Anything that cannot be extracted raises ``JsxExtractionError``
    so a broken test fails loudly instead of silently passing.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise JsxExtractionError(f"jsx file not found: {file_path}")
    source = file_path.read_text(encoding="utf-8")
    wanted = list(names)
    if not wanted:
        raise JsxExtractionError(f"no function names requested for {file_path}")
    chunks = []
    for name in wanted:
        start = _find_function_start(source, name, file_path)
        end = _find_function_end(source, start, name, file_path)
        chunks.append(source[start:end])
    return "\n\n".join(chunks)


def extract_tree_text(node: Any) -> str:
    """Flatten an element tree into its plain visible text."""
    if node is None or isinstance(node, bool):
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, (int, float)):
        return str(node)
    if isinstance(node, list):
        return "".join(extract_tree_text(child) for child in node)
    if isinstance(node, dict):
        return extract_tree_text(node.get("children"))
    return ""


def iter_tree_nodes(node: Any):
    """Yield every element dict in the tree, depth first."""
    if isinstance(node, list):
        for child in node:
            yield from iter_tree_nodes(child)
        return
    if not isinstance(node, dict):
        return
    yield node
    yield from iter_tree_nodes(node.get("children"))


def collect_nodes_by_type(node: Any, *types: str) -> list[dict]:
    """Collect every element whose ``type`` matches one of ``types``."""
    wanted = set(types)
    return [item for item in iter_tree_nodes(node) if item.get("type") in wanted]


def has_node_type(node: Any, node_type: str) -> bool:
    return bool(collect_nodes_by_type(node, node_type))
