#!/usr/bin/env python3
"""Recounts site contents and updates the numbers in man.html and index.html.

Usage:  python3 scripts/update_counts.py [--dry-run]

Reads:  essays/, objects/, visuals/, visuals/charts/, books/, music/
        data/links.json  (nodes / edges of the link graph)
Writes: in-place edits to man.html and index.html — numbers only

Idempotent: a second run reports every position as unchanged.

Counting rule — by path, not by graph type. Every row in the man-page
CONTENTS table is keyed by a path, so each number is simply "how many
.html pages live at that path", index.html excluded.

One consequence worth knowing: visuals/terminal.html is typed `curious`
in the graph (an object, not a visualisation), so the graph counts 35
visuals where the filesystem has 36. Path-based counting says 36. The
graph is used only for the node/edge totals of map.html.

Also agrees the noun with the number: 1591 ребро, 1592 ребра, 1595 рёбер.
Without this a recount quietly produces broken Russian ("1591 рёбер").
"эссе" is indeclinable and carries no forms.

Fails loudly: if a pattern is not found, the script reports it and exits
non-zero rather than silently leaving a stale number behind.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def count_pages(*parts: str, recursive: bool = False) -> int:
    """Count .html pages at a path, excluding index.html."""
    path = os.path.join(ROOT, *parts)
    if recursive:
        return sum(
            1
            for dp, _, fns in os.walk(path)
            for fn in fns
            if fn.endswith(".html") and fn != "index.html"
        )
    return sum(
        1
        for fn in os.listdir(path)
        if fn.endswith(".html") and fn != "index.html"
    )


def collect_counts() -> dict[str, int]:
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        graph = json.load(f)
    return {
        "essays": count_pages("essays"),
        "objects": count_pages("objects", recursive=True),
        "visuals": count_pages("visuals"),
        "charts": count_pages("visuals", "charts"),
        "books": count_pages("books"),
        "music": count_pages("music"),
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
    }


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Russian numeral agreement: (1 ребро, 2 ребра, 5 рёбер)."""
    one, few, many = forms
    if n % 100 in range(11, 15):
        return many
    last = n % 10
    if last == 1:
        return one
    if last in (2, 3, 4):
        return few
    return many


# Each rule: (file, label, regex, key in counts, forms or None).
# Group 1 is context kept verbatim, group 2 is the number, group 3 is the
# noun that follows. With forms=None group 3 is also kept verbatim, so
# nothing but the digits can change.
def build_rules(c: dict[str, int]) -> list[tuple]:
    man = "man.html"
    idx = "index.html"

    def card(section: str) -> str:
        # <a class="section-card" href="essays/"> ... <div class="card-count-num">39</div>
        return (
            r'(<a class="section-card" href="' + section + r'/">'
            r'(?:(?!</a>).)*?<div class="card-count-num">)(\d+)(</div>)'
        )

    OBJ = ("объект", "объекта", "объектов")
    VIS = ("визуализация", "визуализации", "визуализаций")
    TOOL = ("инструмент", "инструмента", "инструментов")
    BOOK = ("книга", "книги", "книг")
    ALBUM = ("альбом", "альбома", "альбомов")
    NODE = ("узел", "узла", "узлов")
    EDGE = ("ребро", "ребра", "рёбер")
    LINK = ("связь", "связи", "связей")

    def alt(forms: tuple[str, str, str]) -> str:
        return "(?:" + "|".join(sorted(set(forms), key=len, reverse=True)) + ")"

    return [
        # ─── man.html · CONTENTS ───
        (man, "man · objects",  r'(/null/objects/</td><td class="v">)(\d+)( ' + alt(OBJ) + r')', "objects", OBJ),
        (man, "man · essays",   r'(/null/essays/</td><td class="v">)(\d+)( эссе)', "essays", None),
        (man, "man · visuals",  r'(/null/visuals/</td><td class="v">)(\d+)( ' + alt(VIS) + r')', "visuals", VIS),
        (man, "man · charts",   r'(/null/visuals/charts/</td><td class="v">)(\d+)( ' + alt(TOOL) + r')', "charts", TOOL),
        (man, "man · books",    r'(/null/books/</td><td class="v">)(\d+)( ' + alt(BOOK) + r')', "books", BOOK),
        (man, "man · music",    r'(/null/music/</td><td class="v">)(\d+)( ' + alt(ALBUM) + r')', "music", ALBUM),
        (man, "man · nodes",    r'(граф связей · )(\d+)( ' + alt(NODE) + r')', "nodes", NODE),
        (man, "man · edges",    r'(граф связей · \d+ \S+ · )(\d+)( ' + alt(EDGE) + r')', "edges", EDGE),
        # ─── index.html · карточки разделов ───
        # книги намеренно показывают ∞ в card-count-num — не трогаем
        (idx, "index · objects",     card("objects"), "objects", None),
        (idx, "index · essays",      card("essays"), "essays", None),
        (idx, "index · visuals",     card("visuals"), "visuals", None),
        (idx, "index · music",       card("music"), "music", None),
        (idx, "index · music (tag)", r'(<div class="card-tag">suno · sonic pi · )(\d+)( ' + alt(ALBUM) + r')', "music", ALBUM),
        (idx, "index · books (meta)", r'(<div class="card-meta">)(\d+)( ' + alt(BOOK) + r')', "books", BOOK),
        # ─── index.html · плашка графа ───
        (idx, "index · nodes", r'(<span class="left">)(\d+)( ' + alt(NODE) + r')', "nodes", NODE),
        (idx, "index · edges", r'(<span class="left">\d+ \S+ · )(\d+)( ' + alt(LINK) + r')', "edges", LINK),
    ]


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]
    counts = collect_counts()

    print("посчитано по файлам:")
    for k, v in counts.items():
        print(f"   {k:<8} {v}")
    print()

    files: dict[str, str] = {}
    changed = 0
    failed: list[str] = []

    for fname, label, pattern, key, forms in build_rules(counts):
        if fname not in files:
            with open(os.path.join(ROOT, fname), encoding="utf-8") as f:
                files[fname] = f.read()

        rx = re.compile(pattern, re.S)
        m = rx.search(files[fname])
        if not m:
            print(f"   ✗ {label:<22} шаблон не найден")
            failed.append(label)
            continue

        was, now = int(m.group(2)), counts[key]
        tail_was = m.group(3)
        tail_now = (" " + plural(now, forms)) if forms else tail_was

        if was == now and tail_was == tail_now:
            print(f"   = {label:<22} {was}{tail_was} (без изменений)")
            continue

        files[fname] = rx.sub(lambda mm: mm.group(1) + str(now) + tail_now, files[fname], count=1)
        print(f"   → {label:<22} {was}{tail_was} → {now}{tail_now}")
        changed += 1

    print()
    if failed:
        print(f"ОШИБКА: шаблонов не найдено — {len(failed)}: {', '.join(failed)}")
        print("Ничего не записано.")
        return 1

    if dry_run:
        print(f"--dry-run: изменилось бы позиций — {changed}. Файлы не тронуты.")
        return 0

    if not changed:
        print("Всё уже актуально, записывать нечего.")
        return 0

    for fname, text in files.items():
        with open(os.path.join(ROOT, fname), "w", encoding="utf-8") as f:
            f.write(text)
    print(f"обновлено позиций: {changed} в {len(files)} файлах")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
