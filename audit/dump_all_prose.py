#!/usr/bin/env python3
"""Dump prose_body of all essays into audit/all-prose.md for manual review."""
from __future__ import annotations

import re
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
ESSAYS = ROOT / "essays"
OUT = AUDIT / "all-prose.md"

if str(AUDIT) not in sys.path:
    sys.path.insert(0, str(AUDIT))

from collect_metrics import load_categories
from problem_html import parse_essay, normalize_prose


def essay_date(html: str) -> str:
    for pat in (
        r'class="essay-label"[^>]*>([^<]+)',
        r'class="label"[^>]*>([^<]+)',
        r'class="obj-subtitle"[^>]*>([^<]+)',
    ):
        m = re.search(pat, html)
        if m:
            dm = re.search(r"(\d{4}\.\d{2})", m.group(1))
            if dm:
                return dm.group(1)
    return "—"


def word_count(text: str) -> int:
    return len(re.findall(r"[а-яёa-z]+", text, re.I))


def main() -> int:
    categories = load_categories()
    rows: list[tuple[str, str, str, str, int]] = []

    for path in sorted(ESSAYS.glob("*.html")):
        if path.name == "index.html":
            continue
        slug = path.stem
        html = path.read_text(encoding="utf-8")
        cat = categories.get(slug, ("", ""))[1] or "—"
        date = essay_date(html)
        slice_ = parse_essay(path)
        words = word_count(slice_.prose_body)
        rows.append((date, slug, cat, slice_.prose_body, words))

    rows.sort(key=lambda r: (r[0] if r[0] != "—" else "9999.99", r[1]))

    parts = [
        "# All essay prose — ручная вычитка",
        "",
        "Источник: `problem_html.parse_essay` → только `prose_body` "
        "(без сносок, нав, формул, кода, blockquote-врезок).",
        f"Эссе: {len(rows)}. Порядок: по дате (старые сверху).",
        "",
    ]

    for date, slug, cat, body, words in rows:
        parts.append(f"=== {slug} · {cat} · {date} · {words} слов ===")
        parts.append(body)
        parts.append("")

    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {len(rows)} essays → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
