#!/usr/bin/env python3
"""Stage 0 — slice essay HTML into prose_body and side channels."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESSAYS = ROOT / "essays"

FORMULA_CLASS = re.compile(r"formula|gl-formula|katex|math|\bf\b", re.I)


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


class BodySlicer(HTMLParser):
    """Extract prose_body (no formula/code/nav) and side channels from essay-body HTML."""

    def __init__(self):
        super().__init__()
        self.prose_parts: list[str] = []
        self.formulas: list[str] = []
        self.code: list[str] = []
        self.quotes: list[str] = []
        self._skip = 0
        self._math_stack: list[str] = []
        self._code_buf: list[str] = []
        self._quote_buf: list[str] = []
        self._in_quote = False

    def _in_math(self) -> bool:
        return bool(self._math_stack)

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "blockquote":
            self._in_quote = True
            self._quote_buf = []
        if FORMULA_CLASS.search(cls) or tag in ("sup", "sub") and "fn" not in cls:
            if FORMULA_CLASS.search(cls) or tag in ("span", "em", "strong"):
                self._math_stack.append("formula")
        if tag in ("code", "pre"):
            self._math_stack.append("code")
            self._code_buf = []
        if tag == "em" and "fn" in cls:
            pass  # footnote marker — skip number in prose
        elif not self._skip and not self._in_math() and not self._in_quote and tag in (
            "p", "div", "li", "td", "h2", "h3", "h4"
        ):
            if tag == "div" and "sub-h" in cls:
                self.prose_parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("span", "em", "strong", "sup", "sub") and self._math_stack:
            self._math_stack.pop()
        if tag in ("code", "pre"):
            if self._code_buf:
                self.code.append("".join(self._code_buf).strip())
            self._code_buf = []
            if self._math_stack:
                self._math_stack.pop()
        if tag == "blockquote" and self._in_quote:
            q = re.sub(r"\s+", " ", "".join(self._quote_buf)).strip()
            if q:
                self.quotes.append(q)
            self._in_quote = False
            self._quote_buf = []

    def handle_data(self, data):
        if self._skip:
            return
        if self._math_stack:
            if self._math_stack[-1] == "code":
                self._code_buf.append(data)
            else:
                t = data.strip()
                if t:
                    self.formulas.append(t)
            return
        if self._in_quote:
            self._quote_buf.append(data)
            return
        if data.strip():
            self.prose_parts.append(data)

    def prose_text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.prose_parts)).strip()


def extract_body_html(html: str) -> str:
    m = re.search(
        r'<div class="essay-body">(.*?)</div>\s*</div>\s*<(?:blockquote|aside|hr|section|div class="note")',
        html,
        re.S,
    )
    if m:
        return m.group(1)
    m = re.search(r'<div class="essay-body">(.*?)</div>', html, re.S)
    return m.group(1) if m else ""


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
    return out


def parse_meta(html: str) -> tuple[str, int | None]:
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = re.sub(r"<[^>]+>", "", h1_m.group(1)).strip() if h1_m else ""
    label_m = re.search(r'class="essay-label"[^>]*>([^<]+)', html)
    label = label_m.group(1) if label_m else ""
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
