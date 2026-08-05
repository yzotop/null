#!/usr/bin/env python3
"""Build sitemap.xml for null (canonical: https://yzotop.github.io/null).

Usage:  python3 scripts/generate_sitemap.py [--dry-run]

Reads:  every *.html in the repo, minus EXCLUDED
        git log — for <lastmod>
Writes: sitemap.xml at the repo root

Idempotent: same commit history in, byte-identical file out.

<lastmod> comes from git (last commit that touched the file), never from
mtime. mtime is wrong after a fresh clone, and a scripted pass over many
files would stamp them all with the day the script ran.

Scope: null is served from https://yzotop.github.io/null/ — a project
page, not the domain root. A sitemap at /null/sitemap.xml is only valid
for URLs under /null/, so every generated <loc> is asserted to stay
inside that prefix. (robots.txt cannot help here at all: it is only read
at the origin root, which this repo does not control.)
"""
from __future__ import annotations

import os
import subprocess
import sys
from xml.sax.saxutils import escape

SITE_ORIGIN = "https://yzotop.github.io"
SITE_PREFIX = "/null/"

# Страницы, которые есть на диске, но не должны попадать в карту сайта.
# Путь относительно корня репозитория.
EXCLUDED = {
    # ── Заглушки-редиректы ──────────────────────────────────────────
    # meta refresh на цель + canonical на неё же. В карте сайта должна
    # быть цель, а не перенаправление на неё.
    "essays/two-systems.html",           # → essays/oshibki-po-pravilam.html
    "essays/cognitive-biases.html",      # → essays/oshibki-po-pravilam.html
    "charts/index.html",                 # → visuals/charts/
    "objects/books/index.html",          # → books/
    # ── Не страница сайта ───────────────────────────────────────────
    # Прототип инструмента дизерных портретов: лежит в tools/ рядом
    # с исходными jpg, ни с одной страницы на него нет ссылки.
    "tools/portraits-proto/preview.html",
}

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def git_lastmod() -> dict[str, str]:
    """path -> YYYY-MM-DD of the last commit touching it. One git call."""
    out = subprocess.run(
        ["git", "log", "--format=@%cs", "--name-only"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    dates: dict[str, str] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("@"):
            current = line[1:]
        elif line and current:
            dates.setdefault(line, current)  # first hit = most recent
    return dates


def find_pages() -> list[str]:
    """Every .html in the repo as a repo-relative path, minus EXCLUDED."""
    pages = []
    for dp, dirnames, fns in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in fns:
            if not fn.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), ROOT)
            if rel not in EXCLUDED:
                pages.append(rel)
    return sorted(pages)


def check_undeclared_redirects(pages: list[str]) -> list[str]:
    """Redirect stubs that nobody added to EXCLUDED yet."""
    found = []
    for rel in pages:
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            if 'http-equiv="refresh"' in f.read(1024):
                found.append(rel)
    return found


def to_loc(rel: str) -> str:
    """Repo path -> public URL. index.html becomes its directory."""
    path = rel[: -len("index.html")] if rel.endswith("index.html") else rel
    return SITE_ORIGIN + SITE_PREFIX + path


def main() -> int:
    dry_run = "--dry-run" in sys.argv[1:]
    pages = find_pages()

    stray = check_undeclared_redirects(pages)
    if stray:
        print("ОШИБКА: заглушки-редиректы вне списка EXCLUDED:")
        for rel in stray:
            print(f"   {rel}")
        print("Добавьте их в EXCLUDED с комментарием, куда ведут. Ничего не записано.")
        return 1

    dates = git_lastmod()
    locs = sorted({to_loc(rel): rel for rel in pages}.items())

    prefix = SITE_ORIGIN + SITE_PREFIX
    outside = [loc for loc, _ in locs if not loc.startswith(prefix)]
    if outside:
        print(f"ОШИБКА: URL вне {prefix} — {len(outside)}:")
        for loc in outside[:10]:
            print(f"   {loc}")
        print("Ничего не записано.")
        return 1

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    no_date = []
    for loc, rel in locs:
        lines.append("  <url>")
        lines.append(f"    <loc>{escape(loc)}</loc>")
        if rel in dates:
            lines.append(f"    <lastmod>{dates[rel]}</lastmod>")
        else:
            no_date.append(rel)
        lines.append("  </url>")
    lines.append("</urlset>")
    lines.append("")
    text = "\n".join(lines)

    print(f"страниц на диске:  {len(pages) + len(EXCLUDED)}")
    print(f"исключено:         {len(EXCLUDED)}")
    print(f"URL в карте:       {len(locs)}")
    if no_date:
        print(f"без даты в git:    {len(no_date)} — {', '.join(no_date[:5])}")

    out_path = os.path.join(ROOT, "sitemap.xml")
    old = ""
    if os.path.isfile(out_path):
        with open(out_path, encoding="utf-8") as f:
            old = f.read()

    if dry_run:
        print("--dry-run: " + ("файл изменился бы." if old != text else "изменений нет."))
        return 0
    if old == text:
        print("sitemap.xml уже актуален, записывать нечего.")
        return 0

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"записан {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
