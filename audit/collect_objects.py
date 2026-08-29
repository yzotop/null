#!/usr/bin/env python3
"""Layer A mechanical metrics for null objects. Read-only.

Парный к collect_metrics.py: тот считает эссе, этот — объекты. Отдельным
скриптом, а не флагом к существующему, ровно по той причине, что записана
в scripts/update_meta.py: у объектов другая структура заголовка, и сводить
их в одну таблицу значит испортить обе.

Usage:  python3 audit/collect_objects.py [--quiet]

Пишет:  audit/objects-metrics.csv  — механика по каждому объекту
        audit/objects-flags.md     — только то, где есть что чинить

Ничего не судит. Литературность, материал, актуальность — вердикт от
чтения, здесь их нет. Здесь только то, что считается.

Плотность приёмов даётся с перцентилем по корпусу: «не X, а Y» — законная
конструкция, и сравнивать её надо с медианой сайта, а не с нулём.

Счётчик слов НЕ реализован здесь заново, а импортируется из
scripts/update_reading_time.py — тем же приёмом, каким update_meta.py
берёт построение URL из generate_sitemap.py. Иначе два счётчика неизбежно
разъезжаются: так и вышло в первой версии, где этот скрипт не считал
саму метку и держал пять объектов в вечных ложных срабатываниях.
"""
from __future__ import annotations

import csv
import math
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBJECTS = ROOT / "objects"
HERE = Path(__file__).resolve().parent
OUT_CSV = HERE / "objects-metrics.csv"
OUT_MD = HERE / "objects-flags.md"

sys.path.insert(0, str(ROOT / "scripts"))
from update_reading_time import (  # noqa: E402
    MAIN_RE,
    WPM_DEFAULT as WPM,
    TOLERANCE_DEFAULT as DRIFT,
    count_words,
    drop_chrome,
    is_redirect,
)


LABEL_RE = re.compile(r'<div class="essay-label">([^<]*)</div>')
NUM_RE = re.compile(r"~?\s*([\d\s]+?)\s*слов\s*·\s*(\d+)\s*мин")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
TAG_RE = re.compile(r"<[^>]+>")

ANTITHESIS = re.compile(r"(?:это\s+)?не\s+[^.,;!?]{1,45}[,—-]\s*(?:а|это)\s", re.I)
VAGUE = re.compile(
    r"\b(?:многие|некоторые|ряд)\s+(?:исследовател|учён|эксперт|специалист|экономист|математик|физик)"
    r"|\bпринято\s+считать\b|\bсчитается,\s*что\b|\bкак\s+известно\b", re.I)
TRIPLE = re.compile(r"\b\w[\w-]+,\s+\w[\w-]+\s+и\s+\w[\w-]+\b")
SOURCE_HINT = re.compile(r"https?://|\b(19|20)\d{2}\b")


def punchlines(html: str) -> int:
    """Короткая ударная концовка раздела — последнее предложение до 6 слов."""
    n = 0
    for chunk in re.split(r"(?=<h[23])", html):
        ps = re.findall(r"<p[^>]*>(.*?)</p>", chunk, re.S)
        if not ps:
            continue
        tail = re.sub(r"\s+", " ", TAG_RE.sub(" ", ps[-1])).strip()
        sents = [x for x in re.split(r"(?<=[.!?])\s+", tail) if x]
        if sents and len(sents[-1].split()) <= 6:
            n += 1
    return n


def resolve(rel: str, href: str) -> str:
    if href.startswith("/"):
        return re.sub(r"^/null/", "", os.path.normpath(href)).replace(os.sep, "/")
    return os.path.normpath(os.path.join(os.path.dirname(rel), href)).replace(os.sep, "/")


def main() -> int:
    quiet = "--quiet" in sys.argv[1:]
    if not OBJECTS.is_dir():
        print("ОШИБКА: не найдена папка objects/.")
        return 1

    pages = []
    for path in sorted(OBJECTS.rglob("*.html")):
        if path.name == "index.html":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if is_redirect(text):
            continue
        pages.append((str(path.relative_to(ROOT)).replace(os.sep, "/"), text))
    if not pages:
        print("ОШИБКА: в objects/ не найдено ни одной страницы.")
        return 1

    valid = {str(p.relative_to(ROOT)).replace(os.sep, "/") for p in ROOT.rglob("*.html")}
    rows, inbound = [], {}

    for rel, html in pages:
        words = count_words(html) or 0
        m = MAIN_RE.search(html)
        text = re.sub(r"\s+", " ",
                      TAG_RE.sub(" ", drop_chrome(m.group(1)) if m else "")).strip()
        t = TITLE_RE.search(html)
        title = re.sub(r"\s+", " ", TAG_RE.sub("", t.group(1))).split("—")[0].strip() if t else rel

        lab = LABEL_RE.search(html)
        num = NUM_RE.search(lab.group(1)) if lab else None
        decl_w = int(re.sub(r"\s", "", num.group(1))) if num else ""
        decl_m = int(num.group(2)) if num else ""
        calc_m = max(1, math.ceil(words / WPM)) if words else ""
        drift = abs(decl_w - words) / words if (num and words) else 0

        out_links = [h for h in re.findall(r'href="([^"#?]+\.html)[^"]*"', html)
                     if not h.startswith("http")]
        broken = []
        for h in out_links:
            tgt = resolve(rel, h)
            if tgt in valid:
                inbound[tgt] = inbound.get(tgt, 0) + 1
            else:
                broken.append(h)

        notes = re.findall(r'class="t"[^>]*>(.*?)</', html, re.S)
        no_source = sum(1 for n in notes if not SOURCE_HINT.search(TAG_RE.sub(" ", n)))
        anti = len(ANTITHESIS.findall(text))

        rows.append({
            "slug": rel[len("objects/"):-len(".html")],
            "path": rel,
            "title": title,
            "category": rel.split("/")[1],
            "words": words,
            "read_min_calc": calc_m,
            "words_declared": decl_w,
            "read_min_declared": decl_m,
            "flag_readtime": "да" if drift > DRIFT else "",
            "antithesis": anti,
            "antithesis_per_1k": round(anti / words * 1000, 1) if words else 0,
            "antithesis_pct": 0,
            "vague_refs": len(VAGUE.findall(text)),
            "punchlines": punchlines(html),
            "triples": len(TRIPLE.findall(text)),
            "footnotes": len(notes),
            "footnotes_without_source": no_source,
            "links_out": len(out_links),
            "broken_links_count": len(broken),
            "broken_links": " | ".join(broken),
            "inbound": 0,
        })

    dens = sorted(r["antithesis_per_1k"] for r in rows)
    for r in rows:
        r["antithesis_pct"] = round(100 * sum(1 for d in dens if d <= r["antithesis_per_1k"]) / len(dens))
        r["inbound"] = inbound.get(r["path"], 0)

    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    median = statistics.median(dens)
    lines = [
        "# Флаги по объектам (только где есть что чинить)",
        "",
        f"Генерируется `audit/collect_objects.py`, ничего не судит. Объектов: {len(rows)}. "
        f"Медиана антитезы «не X, а Y» по корпусу: {median} на 1000 слов — сравнивать надо с ней.",
        "",
    ]
    flagged = 0
    for r in sorted(rows, key=lambda x: x["path"]):
        bul = []
        if r["flag_readtime"]:
            bul.append(f"**время чтения:** объявлено {r['words_declared']} слов / {r['read_min_declared']} мин, "
                       f"насчитано {r['words']} / {r['read_min_calc']}")
        if r["broken_links_count"]:
            bul.append(f"**битые ссылки:** {r['broken_links']}")
        if r["antithesis_pct"] >= 85 and r["antithesis"] >= 3:
            bul.append(f"**антитеза «не X, а Y»:** {r['antithesis']} шт, {r['antithesis_per_1k']}/1000 "
                       f"— {r['antithesis_pct']}-й перцентиль")
        if r["vague_refs"]:
            bul.append(f"**ссылки без имени:** {r['vague_refs']}")
        if r["punchlines"] >= 3:
            bul.append(f"**ударные концовки разделов:** {r['punchlines']}")
        if r["footnotes_without_source"]:
            bul.append(f"**сноски без источника:** {r['footnotes_without_source']} из {r['footnotes']}")
        if r["inbound"] == 0:
            bul.append("**нет входящих ссылок**")
        if not bul:
            continue
        flagged += 1
        lines += [f"## {r['slug']} — {r['title']}", f"{r['category']} · {r['words']} слов", ""]
        lines += [f"- {b}" for b in bul]
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    if not quiet:
        print(f"объектов обработано: {len(rows)}")
        print(f"с флагами:           {flagged}")
        print(f"время чтения врёт:   {sum(1 for r in rows if r['flag_readtime'])}")
        print(f"битых ссылок:        {sum(r['broken_links_count'] for r in rows)}")
        print(f"без входящих:        {sum(1 for r in rows if r['inbound'] == 0)}")
        print(f"\n{OUT_CSV.relative_to(ROOT)}\n{OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
