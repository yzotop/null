#!/usr/bin/env python3
"""Рёбра по ссылкам в тексте: что автор написал прозой, но граф не знает.

Usage:  python3 scripts/prose-edges.py [--apply] [--with-fields] [--context N]

Reads:  data/links.json, страницы узлов графа
Writes: ничего — если не передан --apply

Ссылка внутри абзаца — утверждение «отсюда осмысленно идти туда»,
сделанное автором осознанно. Задача — записать в граф то, что уже
написано в тексте, и ничего сверх.

Направление одно. Ссылка A → B даёт ребро A → B и только его.
Обратное — отдельное решение автора, а не следствие этого.

Что вырезается до разбора и не считается вовсе:
  section.related    — там ссылки и так равны исходящим рёбрам
  section.backlinks  — машинный блок
  header.topbar, .breadcrumb, footer — навигация
  a.xref             — межстраничная перебивка, не абзац
  div.offsite        — внешние ссылки, в граф не идут
  script, style      — не текст
  div.series         — оглавление серии: список соседних эссе, такой же
                      навигационный блок, как related, а не утверждение

Остальное делится на две группы, потому что это разные высказывания:
  проза  — ссылка внутри предложения или сноски: «об этом — в таком-то»
  поля   — p.fields, строка «эссе: A · B · объекты: C» в блоке margin:
           перечень см-также, ближе к related, чем к фразе

Вставляются по умолчанию только «проза». Поля — по флагу --with-fields.

Ссылки на файлы, за которыми нет узла, не пропускаются молча:
они выносятся отдельным списком — это либо страница без узла,
либо битая ссылка, и то и другое стоит увидеть.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PREFIX = "/null/"

# Вырезается насовсем. Заменяется пробелами той же длины, чтобы
# смещения ссылок остались валидными для классификации ниже.
STRIP = [
    re.compile(r'<header class="topbar">.*?</header>', re.S),
    re.compile(r'<div class="breadcrumb">.*?</div>', re.S),
    re.compile(r"<footer\b.*?</footer>", re.S),
    re.compile(r'<section class="related">.*?</section>', re.S),
    re.compile(r'<section class="backlinks">.*?</section>', re.S),
    re.compile(r'<a class="xref\b.*?</a>', re.S),
    re.compile(r'<div class="offsite">.*?</div>', re.S),
    # Блок закрывается через </ol></div>, а не </div></div> — на паре
    # </div> регулярка не находила ничего и серия утекала в «прозу».
    re.compile(r'<div class="series">.*?</ol>\s*</div>', re.S),
    re.compile(r"<script\b.*?</script>", re.S),
    re.compile(r"<style\b.*?</style>", re.S),
]

# Не вырезается, но помечается: ссылки отсюда — отдельная группа.
FIELDS = re.compile(r'<p class="fields">.*?</p>', re.S)


def load() -> tuple[dict, dict, set]:
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        d = json.load(f)
    by_id = {n["id"]: n for n in d["nodes"]}
    url2id = {n["url"]: n["id"] for n in d["nodes"]}
    pairs = {(e["from"], e["to"]) for e in d["edges"]}
    return d, {"by_id": by_id, "url2id": url2id}, pairs


def body_of(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Тело страницы + диапазоны p.fields в нём.

    Вырезанное заменяется пробелами той же длины: смещения ссылок
    должны остаться валидными, иначе классификация поедет.
    """
    for rx in STRIP:
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text, [m.span() for m in FIELDS.finditer(text)]


def context(text: str, pos: int, width: int) -> str:
    lo, hi = max(0, pos - width), min(len(text), pos + width)
    frag = re.sub(r"<[^>]+>", "", text[lo:hi])
    return re.sub(r"\s+", " ", frag).strip()


def scan(idx: dict, pairs: set, width: int) -> tuple[list, list]:
    found, unknown = [], []
    for nid, n in idx["by_id"].items():
        url = n.get("url", "")
        if not url.startswith(SITE_PREFIX):
            continue
        rel = url[len(SITE_PREFIX):]
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        body, field_spans = body_of(raw)
        base = posixpath.dirname(rel)
        seen: set[str] = set()
        for m in re.finditer(r'<a[^>]+href="([^"]+)"', body):
            href = m.group(1)
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            tail = href.split("#")[0]
            if not tail:
                continue
            p = tail[len(SITE_PREFIX):] if tail.startswith(SITE_PREFIX) \
                else posixpath.normpath(posixpath.join(base, tail))
            target = idx["url2id"].get(SITE_PREFIX + p)
            if target is None:
                if p not in seen:
                    seen.add(p)
                    # Ссылка на каталог — это его index.html, а не битая
                    # ссылка: проверять надо оба варианта.
                    cand = os.path.join(ROOT, p)
                    exists = os.path.isfile(cand) or os.path.isfile(
                        os.path.join(cand, "index.html"))
                    unknown.append((rel, href, exists))
                continue
            if target == nid or target in seen:
                continue
            seen.add(target)
            if (nid, target) in pairs:
                continue          # уже в графе — молча
            kind = "поля" if any(a <= m.start() < b for a, b in field_spans) else "проза"
            found.append((nid, target, rel, context(body, m.start(), width), kind))
    return found, unknown


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    with_fields = "--with-fields" in sys.argv[1:]
    width = 120
    if "--context" in sys.argv[1:]:
        width = int(sys.argv[sys.argv.index("--context") + 1])

    d, idx, pairs = load()
    found, unknown = scan(idx, pairs, width)
    by_id = idx["by_id"]

    prose = [f for f in found if f[4] == "проза"]
    fields = [f for f in found if f[4] == "поля"]

    for title, group in (("ПРОЗА — ссылка внутри фразы или сноски", prose),
                         ("ПОЛЯ — p.fields, перечень см-также", fields)):
        pages = sorted({f[2] for f in group})
        print(f"{title}: {len(group)} рёбер на {len(pages)} страницах\n")
        cur = None
        for nid, tid, rel, ctx, _ in sorted(group, key=lambda x: (x[2], x[1])):
            if rel != cur:
                cur = rel
                print(f"── {rel}   [{nid}]")
            print(f"   {nid} → {tid}   «{by_id[tid]['title'][:44]}»")
            print(f"      …{ctx}…")
        print()
    if unknown:
        print(f"\nссылки на файлы без узла в графе: {len(unknown)}")
        for rel, href, exists in sorted(set(unknown)):
            mark = "файл есть, узла нет" if exists else "БИТАЯ ССЫЛКА"
            print(f"   {rel}  →  {href}   ({mark})")

    take = prose + (fields if with_fields else [])
    if not apply:
        print(f"read-only. К вставке готово: {len(take)} "
              f"({'проза + поля' if with_fields else 'только проза'}).")
        print("Вставить:            python3 scripts/prose-edges.py --apply")
        print("Вместе с полями:     python3 scripts/prose-edges.py --apply --with-fields")
        return 0

    if not take:
        print("вставлять нечего.")
        return 0

    p = os.path.join(ROOT, "data", "links.json")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    data = json.loads(src)
    if json.dumps(data, ensure_ascii=False, indent=2) != src:
        print("\nОШИБКА: round-trip не совпал, править структурой нельзя.")
        return 1
    have = {(e["from"], e["to"]) for e in data["edges"]}
    added = 0
    for nid, tid, _, _, _ in take:
        if (nid, tid) in have:
            continue
        have.add((nid, tid))
        data["edges"].append({"from": nid, "to": tid})
        added += 1
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\nдобавлено рёбер: {added}   всего в графе: {len(data['edges'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
