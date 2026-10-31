"""crew_chief.viewer — themed pages for the Markdown and JSON files in ``results/``.

Stdlib only. Everything from a file is HTML-escaped before any markup is added, so a
result file cannot inject script or style; links keep only safe schemes. The pages style
themselves with the portfolio tokens (``var(--surface)``), so they follow the system theme.
"""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from crew_chief import theme

MAX_JSON_BYTES = 8 * 1024 * 1024
FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

CSS = """
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,sans-serif}
main{max-width:1000px;margin:0 auto;padding:16px 16px 64px}
.bar{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;margin:4px 0 12px}
.bar h1{font-size:18px;margin:0;word-break:break-all}.bar .sp{flex:1}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.btn{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:6px;
padding:3px 10px;font:inherit;font-size:13px;cursor:pointer}
.doc{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:8px 20px}
.doc h1,.doc h2,.doc h3,.doc h4{line-height:1.25;margin:1.2em 0 .4em}
.doc h1{font-size:24px;border-bottom:1px solid var(--border);padding-bottom:6px}
.doc h2{font-size:19px;border-bottom:1px solid var(--border);padding-bottom:4px}.doc h3{font-size:16px}
.doc code{background:var(--surface2);border-radius:4px;padding:1px 5px;font:13px ui-monospace,monospace}
.doc pre{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:10px 12px;
overflow:auto}.doc pre code{background:none;padding:0}
.doc table{border-collapse:collapse;display:block;overflow-x:auto;margin:10px 0}
.doc th,.doc td{border:1px solid var(--border);padding:4px 10px;text-align:left;white-space:nowrap}
.doc th{background:var(--surface2)}.doc tr:nth-child(even) td{background:var(--accent-dim)}
.doc blockquote{margin:10px 0;padding:2px 14px;border-left:3px solid var(--accent);color:var(--muted)}
.doc hr{border:0;border-top:1px solid var(--border);margin:16px 0}
.doc ul,.doc ol{padding-left:24px}
.tree{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:10px 14px;
font:13px/1.55 ui-monospace,monospace;overflow:auto}
.tree details{margin-left:0}.tree .j-kids{margin-left:18px;border-left:1px dotted var(--border);padding-left:10px}
.tree summary{cursor:pointer}.j-key{color:var(--accent)}.j-meta{color:var(--muted)}
.j-string{color:var(--green)}.j-number{color:var(--yellow)}.j-boolean{color:var(--purple)}.j-null{color:var(--muted)}
.j-more{margin:2px 0}.muted{color:var(--muted);font-size:13px}
"""


# -- Markdown ----------------------------------------------------------------

_SAFE_URL = re.compile(r"(https?://|/|#|\./|\.\./|[A-Za-z0-9_-][^:]*$)", re.I)
_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _link(match: re.Match[str]) -> str:
    label, url = match.group(1), html.unescape(match.group(2)).strip()
    if not _SAFE_URL.match(url):
        return label
    path = url.split("#")[0].split("?")[0]
    name = PurePosixPath(path).name
    if (
        "://" not in url
        and not url.startswith(("/", "#"))
        and name.endswith((".md", ".json"))
        and FILE.fullmatch(name)
    ):
        url = f"/view/results/{name}"  # a sibling result file opens in the viewer too
    return f'<a href="{html.escape(url, quote=True)}">{label}</a>'


def inline(text: str) -> str:
    """Inline Markdown on one line of text; the text is escaped first."""
    out, spans = html.escape(text), []

    def keep(match: re.Match[str]) -> str:
        spans.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(spans) - 1}\x00"

    out = re.sub(r"`([^`]+)`", keep, out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", _link, out)
    out = re.sub(
        r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", out
    )
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", out)
    out = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<em>\1</em>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _table(rows: list[str]) -> str:
    head, aligns = _cells(rows[0]), _cells(rows[1])

    def style(i: int) -> str:
        a = aligns[i] if i < len(aligns) else ""
        right, left = a.endswith(":"), a.startswith(":")
        if right and left:
            return ' style="text-align:center"'
        return ' style="text-align:right"' if right else ""

    th = "".join(f"<th{style(i)}>{inline(c)}</th>" for i, c in enumerate(head))
    body = "".join(
        "<tr>"
        + "".join(f"<td{style(i)}>{inline(c)}</td>" for i, c in enumerate(_cells(r)))
        + "</tr>"
        for r in rows[2:]
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def markdown_to_html(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i, para = 0, []
    stack: list[tuple[int, str]] = []  # open lists: (indent, tag)

    def flush() -> None:
        if para:
            out.append("<p>" + inline(" ".join(s.strip() for s in para)) + "</p>")
            para.clear()

    def close_lists(to: int = -1) -> None:
        while stack and stack[-1][0] > to:
            out.append(f"</li></{stack.pop()[1]}>")

    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush(), close_lists()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith(fence.group(1)):
                code.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            i += 1
            continue
        if not line.strip():
            flush(), close_lists()
            i += 1
            continue
        if (
            "|" in line
            and i + 1 < len(lines)
            and _TABLE_SEP.match(lines[i + 1])
            and "|" in lines[i + 1] + line
        ):
            flush(), close_lists()
            rows = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush(), close_lists()
            level = len(heading.group(1))
            out.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif _HR.match(line):
            flush(), close_lists()
            out.append("<hr>")
        elif line.lstrip().startswith(">"):
            flush(), close_lists()
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(lines[i].lstrip()[1:].lstrip())
                i += 1
            out.append("<blockquote>" + markdown_to_html("\n".join(quote)) + "</blockquote>")
            continue
        elif item := _ITEM.match(line):
            flush()
            indent, tag = (
                len(item.group(1).expandtabs(4)),
                "ol" if item.group(2)[0].isdigit() else "ul",
            )
            if stack and indent > stack[-1][0]:
                out.append(f"<{tag}><li>")
                stack.append((indent, tag))
            else:
                close_lists(indent)
                if stack and stack[-1][0] == indent:
                    out.append("</li><li>")
                else:
                    out.append(f"<{tag}><li>")
                    stack.append((indent, tag))
            out.append(inline(item.group(3)))
        elif stack and line.startswith((" ", "\t")):
            out.append(" " + inline(line.strip()))  # a wrapped list item
        else:
            close_lists()
            para.append(line)
        i += 1
    flush(), close_lists()
    return "\n".join(out)


# -- JSON --------------------------------------------------------------------

_TREE_JS = """
const data = JSON.parse(document.getElementById("data").textContent);
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; };
const scalar = (v) => v === null ? el("span", "j-null", "null") : el("span", "j-" + typeof v, typeof v === "string" ? JSON.stringify(v) : String(v));
const PAGE = 200;
function build(key, v, open) {
  const row = el("div", "j-row");
  if (v !== null && typeof v === "object") {
    const arr = Array.isArray(v), entries = arr ? v.map((x, i) => [String(i), x]) : Object.entries(v);
    const d = el("details"), s = el("summary");
    if (key !== null) s.append(el("span", "j-key", key), ": ");
    s.append(el("span", "j-meta", arr ? "[" + entries.length + " items]" : "{" + entries.length + " keys}"));
    d.append(s);
    let filled = false;
    const fill = () => {
      if (filled) return; filled = true;
      const box = el("div", "j-kids"), more = el("button", "btn j-more", "Show more"); let shown = 0;
      const next = () => { entries.slice(shown, shown + PAGE).forEach(([k, x]) => box.insertBefore(build(k, x, false), more)); shown += PAGE; more.hidden = shown >= entries.length; };
      more.onclick = next; box.append(more); next(); d.append(box);
    };
    d.addEventListener("toggle", () => { if (d.open) fill(); });
    if (open) { d.open = true; fill(); }
    row.append(d);
  } else { if (key !== null) row.append(el("span", "j-key", key), ": "); row.append(scalar(v)); }
  return row;
}
const tree = document.getElementById("tree");
tree.append(build(null, data, true));
const all = (open) => { let n = 0; for (let pass = 0; pass < 6 && n < 1500; pass++) tree.querySelectorAll("details").forEach((d) => { if (open && n < 1500 && !d.open) { d.open = true; n++; } else if (!open) d.open = false; }); if (!open) tree.firstElementChild.firstElementChild.open = true; };
document.getElementById("expand").onclick = () => all(true);
document.getElementById("collapse").onclick = () => all(false);
"""


def json_body(text: str, raw_url: str) -> str:
    """A collapsible tree for a JSON document, or its text if it is too large or not JSON."""
    raw = f'<a href="{html.escape(raw_url, quote=True)}">raw</a>'
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        return f'<p class="muted">Too large to render here ({raw}).</p>'
    try:
        json.loads(text)
    except ValueError as exc:
        return f'<p class="muted">Not valid JSON ({html.escape(str(exc))}); {raw}.</p><pre class="tree">{html.escape(text)}</pre>'
    embedded = text.replace("<", "\\u003c")
    return (
        '<div class="bar"><button class="btn" id="expand">Expand all</button>'
        '<button class="btn" id="collapse">Collapse all</button></div>'
        f'<div class="tree" id="tree"></div><script type="application/json" id="data">{embedded}</script>'
        f"<script>{_TREE_JS}</script>"
    )


# -- SVG ---------------------------------------------------------------------

SVG_NS = "http://www.w3.org/2000/svg"
MAX_SVG_BYTES = 2 * 1024 * 1024
# Drawing elements only: no script, style, foreignObject, image or anything that loads a resource.
SVG_ELEMENTS = frozenset(
    [
        "svg",
        "g",
        "defs",
        "title",
        "desc",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "path",
        "text",
        "tspan",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
        "mask",
        "marker",
        "symbol",
        "use",
    ]
)
_UNSAFE_STYLE = re.compile(r"url\((?!\s*['\"]?#)|expression|javascript|@import", re.I)


def _clean_style(value: str) -> str:
    return ";".join(d for d in value.split(";") if d.strip() and not _UNSAFE_STYLE.search(d))


def _clean_svg(node: ET.Element) -> None:
    for child in list(node):
        name = child.tag.rsplit("}", 1)[-1] if isinstance(child.tag, str) else ""
        if name not in SVG_ELEMENTS:
            node.remove(child)
            continue
        _clean_svg(child)
    for attr in list(node.attrib):
        local = attr.rsplit("}", 1)[-1].lower()
        value = node.attrib[attr]
        if local.startswith("on") or (local == "href" and not value.startswith("#")):
            del node.attrib[attr]
        elif local == "style":
            node.attrib[attr] = _clean_style(value)


def clean_svg(text: str) -> str | None:
    """The drawing in *text* with everything but plain shapes and text removed, or None if it is
    not a usable SVG. Its colours stay ``var(--token)``, so inline it follows the page's theme."""
    if len(text.encode("utf-8")) > MAX_SVG_BYTES:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    if root.tag != f"{{{SVG_NS}}}svg":
        return None
    _clean_svg(root)
    ET.register_namespace("", SVG_NS)
    root.set("style", (root.get("style", "") + ";max-width:100%;height:auto").lstrip(";"))
    for attr in ("width", "height"):
        root.attrib.pop(attr, None)  # scale to the page; the viewBox keeps the proportions
    return ET.tostring(root, encoding="unicode")


def svg_body(text: str, raw_url: str) -> str:
    drawing = clean_svg(text)
    if drawing is None:
        raw = f'<a href="{html.escape(raw_url, quote=True)}">raw</a>'
        return f'<p class="muted">Not a usable SVG, or too large to show here ({raw}).</p>'
    return f'<div class="doc" style="text-align:center">{drawing}</div>'


# -- page --------------------------------------------------------------------


def page(title: str, body: str, raw_url: str, extra: str = "") -> str:
    """A complete themed page; the caller adds the top bar (``benchui.with_home_link``)."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>{theme.HEAD}<style>{theme.SWITCHER_CSS}{CSS}</style></head>"
        f'<body><main><div class="bar"><a href="/results/">&larr; All files</a><h1>{html.escape(title)}</h1>'
        f'<span class="sp"></span>{extra}<a href="{html.escape(raw_url, quote=True)}">raw</a></div>{body}</main></body></html>'
    )


def render(name: str, text: str, raw_url: str, extra: str = "") -> str | None:
    """The themed page for a ``.md``, ``.json`` or ``.svg`` file, or None for any other kind."""
    suffix = PurePosixPath(name).suffix
    if suffix == ".md":
        return page(name, f'<div class="doc">{markdown_to_html(text)}</div>', raw_url)
    if suffix == ".json":
        return page(name, json_body(text, raw_url), raw_url, extra)
    if suffix == ".svg":
        return page(name, svg_body(text, raw_url), raw_url, extra)
    return None
