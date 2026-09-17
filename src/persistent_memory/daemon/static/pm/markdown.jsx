// persistent-memory — safe markdown renderer for untrusted LLM-authored text.
// Produces React elements only (React.createElement), never HTML strings.
// No unsafe raw-HTML injection API, no third-party markdown library.
(function () {
  const React = window.React;
  const h = React.createElement;

  const CODE_FENCE_RE = /^```\s*([^\s`]*)\s*$/;
  const CODE_FENCE_END_RE = /^```\s*$/;
  const HEADING_RE = /^(#{1,6})\s+(.*)$/;
  const HR_RE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
  const BLOCKQUOTE_RE = /^>\s?(.*)$/;
  const LIST_ITEM_RE = /^(\s*)([-*]|\d+\.)\s+(.+)$/;
  const LIST_ORDERED_RE = /^\d+\.$/;
  const TABLE_CELL_SEP_RE = /^:?-{2,}:?$/;

  const CODE_SPAN_RE = /`([^`\n]+)`/g;
  const BOLD_RE = /\*\*((?:[^*]|\*(?!\*))+?)\*\*/g;
  const STRIKE_RE = /~~([^~]+?)~~/g;
  const ITALIC_RE = /\*([^\s*][^*\n]*?[^\s*]|[^\s*])\*|_([^\s_][^_\n]*?[^\s_]|[^\s_])_/g;
  const WORD_CHAR_RE = /[\p{L}\p{N}_]/u;
  const LINK_RE = /\[([^\[\]\n]*)\]\(([^()\s]+)\)/g;
  const REF_BRACKET_RE = /\[\[([DLP]-\d{4})(?:\|[^\]]*)?\]\]/g;
  const REF_BARE_RE = /\b([DLP]-\d{4})\b/g;

  const MAX_INLINE_DEPTH = 8;

  function parseTableRow(line) {
    let trimmed = line.trim();
    if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
    if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
    return trimmed.split("|").map((c) => c.trim());
  }

  function isSeparatorRow(line) {
    if (!line || line.indexOf("|") < 0) return false;
    const cells = parseTableRow(line);
    return cells.length > 0 && cells.every((c) => TABLE_CELL_SEP_RE.test(c));
  }

  function isBlockStart(lines, i) {
    const line = lines[i];
    if (CODE_FENCE_RE.test(line)) return true;
    if (HEADING_RE.test(line)) return true;
    if (HR_RE.test(line)) return true;
    if (BLOCKQUOTE_RE.test(line)) return true;
    if (LIST_ITEM_RE.test(line)) return true;
    if (line.indexOf("|") >= 0 && i + 1 < lines.length && isSeparatorRow(lines[i + 1])) return true;
    return false;
  }

  function parseBlocks(lines) {
    const blocks = [];
    const n = lines.length;
    let i = 0;
    while (i < n) {
      const line = lines[i];

      if (line.trim() === "") { i += 1; continue; }

      if (CODE_FENCE_RE.test(line)) {
        const fenceMatch = CODE_FENCE_RE.exec(line);
        const lang = (fenceMatch && fenceMatch[1]) || "";
        const codeLines = [];
        i += 1;
        while (i < n && !CODE_FENCE_END_RE.test(lines[i])) {
          codeLines.push(lines[i]);
          i += 1;
        }
        if (i < n) i += 1;
        blocks.push({ type: "code", lang, content: codeLines.join("\n") });
        continue;
      }

      if (line.indexOf("|") >= 0 && i + 1 < n && isSeparatorRow(lines[i + 1])) {
        const header = parseTableRow(line);
        i += 2;
        const rows = [];
        while (i < n && lines[i].trim() !== "" && lines[i].indexOf("|") >= 0) {
          rows.push(parseTableRow(lines[i]));
          i += 1;
        }
        blocks.push({ type: "table", header, rows });
        continue;
      }

      if (HEADING_RE.test(line)) {
        const m = HEADING_RE.exec(line);
        blocks.push({ type: "heading", level: m[1].length, text: m[2] });
        i += 1;
        continue;
      }

      if (HR_RE.test(line)) {
        blocks.push({ type: "hr" });
        i += 1;
        continue;
      }

      if (BLOCKQUOTE_RE.test(line)) {
        const quoteLines = [];
        while (i < n) {
          const m = BLOCKQUOTE_RE.exec(lines[i]);
          if (!m) break;
          quoteLines.push(m[1]);
          i += 1;
        }
        blocks.push({ type: "quote", lines: quoteLines });
        continue;
      }

      if (LIST_ITEM_RE.test(line)) {
        const first = LIST_ITEM_RE.exec(line);
        const ordered = LIST_ORDERED_RE.test(first[2]);
        const items = [];
        while (i < n) {
          const m = LIST_ITEM_RE.exec(lines[i]);
          if (!m) break;
          if (LIST_ORDERED_RE.test(m[2]) !== ordered) break;
          items.push({ indent: m[1].length, text: m[3] });
          i += 1;
        }
        blocks.push({ type: "list", ordered, items });
        continue;
      }

      const paraLines = [];
      while (i < n && lines[i].trim() !== "" && !isBlockStart(lines, i)) {
        paraLines.push(lines[i]);
        i += 1;
      }
      if (paraLines.length === 0) {
        paraLines.push(lines[i]);
        i += 1;
      }
      blocks.push({ type: "para", lines: paraLines });
    }
    return blocks;
  }

  function renderRefNode(id, key, nav) {
    const pmById = (window.PMUI && window.PMUI.pmById) || (() => null);
    const known = pmById(id);
    if (!known) return h("span", { key, className: "pm-ref missing", title: "record not found" }, id);
    return h("a", {
      key,
      className: "pm-ref",
      title: known.title,
      onClick: (e) => { e.stopPropagation(); nav && nav("detail", { id }); },
    }, id);
  }

  function nextKey(ctx) {
    return "k" + (ctx.keyState.n++);
  }

  function renderNestedInline(text, ctx) {
    return renderInlineNodes(text, { nav: ctx.nav, keyState: ctx.keyState, depth: ctx.depth + 1 });
  }

  function buildCodeSpanNode(m, ctx) {
    return h("code", { key: nextKey(ctx), className: "pm-md-code-inline" }, m[1]);
  }

  function buildRefBracketNode(m, ctx) {
    return renderRefNode(m[1], nextKey(ctx), ctx.nav);
  }

  function buildRefBareNode(m, ctx) {
    return renderRefNode(m[1], nextKey(ctx), ctx.nav);
  }

  function buildBoldNode(m, ctx) {
    return h("strong", { key: nextKey(ctx) }, renderNestedInline(m[1], ctx));
  }

  function buildStrikeNode(m, ctx) {
    return h("del", { key: nextKey(ctx) }, renderNestedInline(m[1], ctx));
  }

  function buildItalicNode(m, ctx) {
    return h("em", { key: nextKey(ctx) }, renderNestedInline(m[1] || m[2], ctx));
  }

  function buildMdLinkNode(m, ctx) {
    return h("span", { key: nextKey(ctx), className: "pm-md-link", title: m[2] }, renderNestedInline(m[1] || m[2], ctx));
  }

  function isWordChar(char) {
    return char !== undefined && WORD_CHAR_RE.test(char);
  }

  function hasFreeStandingUnderscores(text, match) {
    if (match[2] === undefined) return true;
    if (isWordChar(text[match.index - 1])) return false;
    return !isWordChar(text[match.index + match[0].length]);
  }

  const INLINE_RULES = [
    { regex: CODE_SPAN_RE, build: buildCodeSpanNode },
    { regex: REF_BRACKET_RE, build: buildRefBracketNode },
    { regex: BOLD_RE, build: buildBoldNode },
    { regex: STRIKE_RE, build: buildStrikeNode },
    { regex: ITALIC_RE, build: buildItalicNode, isValid: hasFreeStandingUnderscores },
    { regex: LINK_RE, build: buildMdLinkNode },
    { regex: REF_BARE_RE, build: buildRefBareNode },
  ];

  function findNextRuleMatch(text, rule, from) {
    let start = from;
    while (start <= text.length) {
      rule.regex.lastIndex = start;
      const m = rule.regex.exec(text);
      if (!m) return null;
      if (m[0].length === 0) {
        start = m.index + 1;
        continue;
      }
      if (rule.isValid && !rule.isValid(text, m)) {
        start = m.index + 1;
        continue;
      }
      return m;
    }
    return null;
  }

  function pickEarliestRule(text, pending, pos) {
    let best = -1;
    for (let i = 0; i < INLINE_RULES.length; i += 1) {
      if (pending[i] && pending[i].index < pos) pending[i] = findNextRuleMatch(text, INLINE_RULES[i], pos);
      if (!pending[i]) continue;
      if (best >= 0 && pending[i].index >= pending[best].index) continue;
      best = i;
    }
    return best;
  }

  function renderInlineNodes(text, ctx) {
    if (text === "") return [];
    if (ctx.depth >= MAX_INLINE_DEPTH) return [text];
    const pending = INLINE_RULES.map((rule) => findNextRuleMatch(text, rule, 0));
    const out = [];
    let pos = 0;
    while (pos < text.length) {
      const best = pickEarliestRule(text, pending, pos);
      if (best < 0) break;
      const match = pending[best];
      if (match.index > pos) out.push(text.slice(pos, match.index));
      out.push(INLINE_RULES[best].build(match, ctx));
      pos = match.index + match[0].length;
    }
    if (pos < text.length) out.push(text.slice(pos));
    return out;
  }

  function renderInline(text, nav, keyState) {
    return renderInlineNodes(text, { nav, keyState, depth: 0 });
  }

  function renderMultilineInline(lines, nav, keyState) {
    const out = [];
    lines.forEach((line, idx) => {
      if (idx > 0) out.push(h("br", { key: "br" + (keyState.n++) }));
      renderInline(line, nav, keyState).forEach((node) => out.push(node));
    });
    return out;
  }

  function headingTag(level) {
    if (level <= 2) return "h3";
    if (level <= 4) return "h4";
    return "h5";
  }

  function renderBlock(block, nav, keyState, blockKey) {
    if (block.type === "code") {
      return h("div", { key: blockKey, className: "pm-md-codeblock" },
        block.lang ? h("div", { className: "pm-md-codelang" }, block.lang) : null,
        h("pre", null, h("code", null, block.content)));
    }
    if (block.type === "table") {
      return h("div", { key: blockKey, className: "pm-md-tablewrap" },
        h("table", { className: "pm-md-table" },
          h("thead", null, h("tr", null, block.header.map((cell, ci) =>
            h("th", { key: "h" + ci }, renderInline(cell, nav, keyState))))),
          h("tbody", null, block.rows.map((row, ri) =>
            h("tr", { key: "r" + ri }, row.map((cell, ci) =>
              h("td", { key: "c" + ci }, renderInline(cell, nav, keyState))))))));
    }
    if (block.type === "heading") {
      return h(headingTag(block.level), { key: blockKey, className: "pm-md-heading" }, renderInline(block.text, nav, keyState));
    }
    if (block.type === "hr") {
      return h("hr", { key: blockKey, className: "pm-md-hr" });
    }
    if (block.type === "quote") {
      return h("blockquote", { key: blockKey, className: "pm-md-quote" }, renderMultilineInline(block.lines, nav, keyState));
    }
    if (block.type === "list") {
      const Tag = block.ordered ? "ol" : "ul";
      return h(Tag, { key: blockKey, className: "pm-md-list" },
        block.items.map((item, ii) =>
          h("li", { key: "i" + ii, style: { marginLeft: Math.min(item.indent, 24) } }, renderInline(item.text, nav, keyState))));
    }
    return h("p", { key: blockKey, className: "pm-md-p" }, renderMultilineInline(block.lines, nav, keyState));
  }

  function renderMarkdown(text, options) {
    const opts = options || {};
    const nav = opts.nav;
    if (text === null || text === undefined || text === "") return [];
    const lines = String(text).replace(/\r\n/g, "\n").split("\n");
    const blocks = parseBlocks(lines);
    const keyState = { n: 0 };
    return blocks.map((block, bi) => renderBlock(block, nav, keyState, "b" + bi));
  }

  if (!document.getElementById("pm-markdown-css")) {
    const s = document.createElement("style");
    s.id = "pm-markdown-css";
    s.textContent = `
.pm-md-heading{margin:14px 0 6px;font-weight:600;color:var(--txt-hi);line-height:1.3}
h3.pm-md-heading{font-size:15.5px}
h4.pm-md-heading{font-size:14px}
h5.pm-md-heading{font-size:12.5px;text-transform:uppercase;letter-spacing:.3px;color:var(--faint)}
.pm-md-p{margin:8px 0;line-height:1.55;color:var(--txt)}
.pm-md-hr{border:none;border-top:1px solid var(--line);margin:14px 0}
.pm-md-quote{margin:10px 0;padding:2px 12px;border-left:3px solid var(--line2);color:var(--faint);font-style:italic;line-height:1.5}
.pm-md-list{margin:8px 0;padding-left:20px;line-height:1.55;color:var(--txt)}
.pm-md-list li{margin:2px 0}
.pm-md-codeblock{margin:10px 0;background:var(--bg2);border:1px solid var(--line);border-radius:6px;overflow-x:auto}
.pm-md-codeblock pre{margin:0;padding:10px 12px;white-space:pre-wrap;word-break:break-word;font-family:var(--font-mono);font-size:12px;color:var(--txt)}
.pm-md-codelang{font-family:var(--font-mono);font-size:10.5px;color:var(--faint);padding:6px 12px 0;text-transform:lowercase}
.pm-md-code-inline{font-family:var(--font-mono);font-size:0.92em;background:var(--bg2);border:1px solid var(--line);border-radius:4px;padding:0 4px;color:var(--txt-hi)}
.pm-md-tablewrap{margin:10px 0;overflow-x:auto}
.pm-md-table{border-collapse:collapse;width:100%;font-size:12.5px}
.pm-md-table th,.pm-md-table td{border:1px solid var(--line);padding:6px 10px;text-align:left;color:var(--txt);white-space:normal}
.pm-md-table th{color:var(--txt-hi);background:var(--panel-hi);font-weight:600}
.pm-md-link{border-bottom:1px dashed var(--faint);cursor:default}
`;
    document.head.appendChild(s);
  }

  window.PMMarkdown = { renderMarkdown };
})();
