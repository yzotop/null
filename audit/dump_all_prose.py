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

from collect_metrics import load_categories, parse_meta
from problem_html import parse_essay


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
        meta = parse_meta(html)
        cat = categories.get(slug, ("", ""))[1] or "—"
        date = meta.get("date") or "—"
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
