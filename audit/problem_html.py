#!/usr/bin/env python3
"""Stage 0 — slice essay HTML into prose_body and side channels."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESSAYS = ROOT / "essays"

FORMULA_CLASS = re.compile(r"formula|gl-formula|katex|\bmath\b|\bcase\b", re.I)
FORMULA_CLASS_TOKENS = frozenset({"f", "formula", "gl-formula", "katex", "math", "case"})


def _is_formula_class(cls: str) -> bool:
    if FORMULA_CLASS.search(cls):
        return True
    return bool(FORMULA_CLASS_TOKENS.intersection(cls.split()))
SKIP_CLASS = re.compile(
    r"\b(label|lead|margin|mh|fields|fn|num|related|backlinks|series|"
    r"obj-header|obj-glyph|card-tag|obj-title|obj-subtitle|"
    r"gl-letter|gl-bridge|math|formula|parts|part|when|plate|"
    r"ax|axl|fork-ax|fork-axl|fork-lbl|figcaption|note|xref|meta|sym)\b",
    re.I,
)
PROSE_END = re.compile(
    r'<div class="margin"|<section class="related"|<section class="backlinks"|'
    r'<hr class="section-divider',
    re.I,
)


@dataclass
class EssaySlice:
    slug: str
    prose_body: str
    footnotes: list[str] = field(default_factory=list)
    nav: str = ""
    formulas: list[str] = field(default_factory=list)
    code: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    read_declared: int | None = None
    title: str = ""


VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})


@dataclass
class _Frame:
    skip: bool = False
    quote: bool = False
    math: bool = False
    code: bool = False


class BodySlicer(HTMLParser):
    """Extract prose_body (no formula/code/nav/blockquote) from essay HTML chunk."""

    def __init__(self):
        super().__init__()
        self.prose_parts: list[str] = []
        self.formulas: list[str] = []
        self.code: list[str] = []
        self.quotes: list[str] = []
        self._frames: list[_Frame] = [_Frame()]
        self._quote_buf: list[str] = []
        self._code_buf: list[str] = []
        self._in_sup = False

    def _cur(self) -> _Frame:
        return self._frames[-1]

    def _skip(self) -> bool:
        return any(f.skip for f in self._frames)

    def _in_math(self) -> bool:
        return any(f.math or f.code for f in self._frames)

    def _in_quote(self) -> bool:
        return any(f.quote for f in self._frames)

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag == "hr":
                pass  # ignore
            return
        cls = dict(attrs).get("class", "")
        parent = self._cur()
        skip = parent.skip or tag in (
            "script", "style", "nav", "header", "footer", "h1",
            "figure", "svg", "canvas", "table", "aside",
        )
        if not skip and SKIP_CLASS.search(cls):
            skip = True
        is_math = not skip and (_is_formula_class(cls) or cls == "gl-formula")
        is_code = not skip and tag in ("code", "pre")
        quote = tag == "blockquote"
        self._frames.append(_Frame(skip=skip, quote=quote, math=is_math, code=is_code))
        if quote:
            self._quote_buf = []
        if tag == "sup":
            self._in_sup = True
        elif not skip and not is_math and not is_code and not quote:
            if tag in ("h2", "h3", "h4") or (tag == "div" and "sub-h" in cls):
                self.prose_parts.append(" ")

    def handle_endtag(self, tag):
        if tag == "sup":
            self._in_sup = False
        if len(self._frames) > 1:
            frame = self._frames.pop()
            if frame.quote and self._quote_buf:
                q = re.sub(r"\s+", " ", "".join(self._quote_buf)).strip()
                if q:
                    self.quotes.append(q)
                self._quote_buf = []
            if frame.code and self._code_buf:
                self.code.append("".join(self._code_buf).strip())
                self._code_buf = []

    def handle_data(self, data):
        if self._in_sup or self._skip():
            return
        frame = self._cur()
        if frame.math:
            t = data.strip()
            if t:
                self.formulas.append(t)
            return
        if frame.code:
            self._code_buf.append(data)
            return
        if frame.quote:
            self._quote_buf.append(data)
            return
        if data.strip():
            self.prose_parts.append(data)

    def prose_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.prose_parts)).strip()


def _extract_essay_body_classic(html: str) -> str:
    m = re.search(r'<div class="essay-body">', html)
    if not m:
        return ""
    rest = html[m.end() :]
    end = re.search(
        r"</div>\s*</div>\s*(?:<blockquote|<aside|<hr|<section|<div class=\"note\")",
        rest,
        re.S | re.I,
    )
    return rest[: end.start()] if end else rest


def _is_redirect(html: str) -> bool:
    return bool(re.search(r'<meta\s+http-equiv="refresh"', html[:3000], re.I))


def _extract_glossary_body(chunk: str) -> str:
    parts: list[str] = []
    m = re.search(r'</header>\s*(.*?)(?:<div class="gl-letter"|<hr)', chunk, re.S | re.I)
    if m:
        parts.append(m.group(1))
    for term in re.findall(r'<div class="gl-term[^"]*">(.*?)</div>', chunk, re.S):
        parts.append(term)
    return "\n".join(parts)


def _extract_new_template_body(chunk: str) -> str:
    """Prose wrapper inside <article> (evo, bayes4, forking, …)."""
    m = re.search(
        r'<div class="([a-z][a-z0-9_-]*)">'
        r'(?:(?!</div>).)*?'
        r'(?:<p[^>]*\bclass="first"|<h2\b|<p\b)',
        chunk,
        re.S | re.I,
    )
    if not m:
        return ""
    cls = m.group(1)
    if cls in ("series",):
        return ""
    body_m = re.search(rf'<div class="{re.escape(cls)}">(.*)', chunk, re.S)
    if not body_m:
        return ""
    body = body_m.group(1)
    end = PROSE_END.search(body)
    if end:
        body = body[: end.start()]
    return body


def extract_body_html(html: str) -> str:
    if _is_redirect(html):
        return ""

    classic = _extract_essay_body_classic(html)
    if classic:
        return classic

    art = re.search(r"<article>(.*?)</article>", html, re.S)
    if not art:
        return ""
    chunk = art.group(1)

    if "gl-term" in chunk:
        return _extract_glossary_body(chunk)

    new_body = _extract_new_template_body(chunk)
    if new_body:
        return new_body

    # Fallback: paragraphs in article outside header/related
    fallback = re.sub(r"<header[^>]*>.*?</header>", "", chunk, flags=re.S | re.I)
    for marker in (
        r'<section class="related".*',
        r'<section class="backlinks".*',
        r'<div class="series".*',
    ):
        fallback = re.sub(marker, "", fallback, flags=re.S | re.I)
    return fallback


def extract_nav(html: str) -> str:
    m = re.search(r'<header class="topbar">(.*?)</header>', html, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()


def extract_footnotes(html: str) -> list[str]:
    out: list[str] = []
    for block in re.findall(r'<div class="note">(.*?)</div>', html, re.S):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block)).strip()
        if t:
            out.append(t)
    for block in re.findall(r'<div class="fn">(.*?)</div>', html, re.S):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block)).strip()
        if t and t not in out:
            out.append(t)
    return out


def parse_meta(html: str) -> tuple[str, int | None]:
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if not h1_m:
        h1_m = re.search(r'<div class="obj-title">([^<]+)', html)
    title = re.sub(r"<[^>]+>", "", h1_m.group(1)).strip() if h1_m else ""
    label_m = re.search(r'class="essay-label"[^>]*>([^<]+)', html)
    if not label_m:
        label_m = re.search(r'class="label"[^>]*>([^<]+)', html)
    if not label_m:
        label_m = re.search(r'class="obj-subtitle"[^>]*>([^<]+)', html)
    label = label_m.group(1) if label_m else ""
    date_m = re.search(r"(\d{4}\.\d{2})", label)
    read_m = re.search(r"~(\d+)\s*мин", label, re.I) or re.search(r"(\d+)\s*мин", label, re.I)
    read_declared = int(read_m.group(1)) if read_m else None
    return title, read_declared


def normalize_prose(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_essay(path: Path) -> EssaySlice:
    html = path.read_text(encoding="utf-8")
    title, read_declared = parse_meta(html)
    body_html = extract_body_html(html)
    slicer = BodySlicer()
    slicer.feed(body_html)
    return EssaySlice(
        slug=path.stem,
        prose_body=normalize_prose(slicer.prose_text()),
        footnotes=extract_footnotes(html),
        nav=extract_nav(html),
        formulas=slicer.formulas,
        code=slicer.code,
        quotes=slicer.quotes,
        read_declared=read_declared,
        title=title,
    )


def sentence_at(text: str, pos: int) -> str:
    """Return the sentence in text containing position pos."""
    for m in re.finditer(r"[^.!?…]+[.!?…]?", text):
        if m.start() <= pos < m.end():
            return normalize_prose(m.group(0))
    return ""


def expand_span(text: str, start: int, end: int, max_len: int = 220) -> str:
    """Expand match to sentence boundaries for a verbatim span."""
    sent = sentence_at(text, start)
    if sent and len(sent) <= max_len:
        return sent
    span = text[max(0, start - 40) : min(len(text), end + 40)].strip()
    if len(span) > max_len:
        span = "…" + span[: max_len - 1] + "…"
    return normalize_prose(span)
