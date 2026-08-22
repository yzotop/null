#!/usr/bin/env python3
"""Рёбра по ссылкам в секции related.

Usage:  python3 scripts/related-edges.py [--apply] [--min-freq N] [--verbose]

Reads:  data/links.json, страницы узлов графа
Writes: ничего — если не передан --apply

Ссылка в related — утверждение автора «отсюда осмысленно идти туда».
Отношение одностороннее: ссылка без ребра дефект, ребро без ссылки норма
(секция курируется и показывает не всё). Задача — записать в граф то,
что уже написано в HTML.

Все рёбра направленные. Обратные не достраиваются: если обе стороны
связи написаны в HTML, оба ребра придут независимо, каждое со своей
страницы. Достраивать симметрию значило бы утверждать за автора.

── Правило отбора, двухступенчатое ──────────────────────────────────

Частота — частота пары (цель, подпись) по всему корпусу. Она отделяет
размноженную копированием строку от суждения, но неидеально: узел может
упоминаться часто просто потому, что он единственный в своём роде.
Поэтому частота — фильтр кандидатов, а решает вторая ступень.

  1. частота < MIN_FREQ                    → вставить
  2. частота >= MIN_FREQ и при этом:
       тип цели visual/chart/statistic     → вставить
       подпись содержит пояснение после —  → вставить
       иначе                               → придержать

Смысл второй ступени: «vi-axelrod «турниры Аксельрода»» стоит на пяти
страницах куста кооперации не от копирования — визуал турниров ровно
один, и называть его иначе нечем. А «natural «натуральные числа»» на
десяти страницах не сообщает причины связи, и десять таких рёбер
сделали бы узел центром графа ни за что.

Придержанное — решение, а не долг: выписывается в held.txt и учитывается
проверкой 5 в preflight отдельной строкой, чтобы основное число дефектов
сходилось в ноль.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PREFIX = "/null/"
MIN_FREQ_DEFAULT = 3

# Ссылки в related, ведущие не на узел графа: разделы и карта. Адресаты
# законные, подтвердить ребром нечем — узла нет. Список явный, чтобы
# проверка сходилась в ноль, а не в «семь всегда».
NON_NODE = {
    "objects/numbers/constants/",   # раздел констант
    "music",                        # раздел музыки
    "visuals",                      # раздел визуалов
    "map.html",                     # карта связей
}

REL_RE = re.compile(r'<section class="related">.*?</section>', re.S)
LINK_RE = re.compile(r'<a href="([^"]+)">(.*?)\s*→</a>')
# Пояснение — длинное тире с непустым текстом после него. Точка «·»
# не считается: она разделяет части имени («Ньютон · Principia»),
# а не объясняет связь.
EXPLAINED = re.compile(r"—\s*\S")

# «Единственна в своём роде»: визуал, график, конкретная именованная
# статистика. В корпусе это не категории, а отдельные объекты — p-value,
# доверительный интервал, дисперсия, BLEU, Elo. Противоположность им —
# широкие цели: тип (natural, prime), оператор (op-mod), гипотеза,
# эссе. Их подпись без пояснения ничего не сообщает о причине связи.
INSERT_TYPES = {"visual", "chart", "statistic"}


def scan() -> tuple[list, list, dict]:
    """Возвращает (кандидаты, ссылки-не-на-узел-вне-белого-списка, граф)."""
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        d = json.load(f)
    by_id = {n["id"]: n for n in d["nodes"]}
    by_url = {n["url"]: n["id"] for n in d["nodes"]}
    out: dict[str, set[str]] = {}
    for e in d["edges"]:
        out.setdefault(e["from"], set()).add(e["to"])

    cand, stray = [], []
    for nid, n in by_id.items():
        url = n.get("url", "")
        if not url.startswith(SITE_PREFIX):
            continue
        rel = url[len(SITE_PREFIX):]
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            m = REL_RE.search(f.read())
        if not m:
            continue
        base = posixpath.dirname(rel)
        seen = set()
        for href, label in LINK_RE.findall(m.group(0)):
            p = (href[len(SITE_PREFIX):] if href.startswith(SITE_PREFIX)
                 else posixpath.normpath(posixpath.join(base, href)))
            p = p.split("#")[0]
            target = by_url.get(SITE_PREFIX + p)
            if target is None:
                if p not in NON_NODE:
                    stray.append((rel, href))
                continue
            # Ключ с полным href: #pavlov и #generous-tit-for-tat ведут
            # на один файл, но это разные адресаты.
            if (target, href) in seen:
                continue
            seen.add((target, href))
            if target not in out.get(nid, set()):
                cand.append((rel, nid, target, href, label))
    return cand, stray, {"by_id": by_id}


def classify(cand: list, by_id: dict, min_freq: int) -> tuple[list, list, Counter]:
    freq = Counter((t, lab) for _, _, t, _, lab in cand)
    take, held = [], []
    for row in cand:
        _, _, t, _, lab = row
        if freq[(t, lab)] < min_freq:
            take.append(row)
        elif by_id[t]["type"] in INSERT_TYPES or EXPLAINED.search(lab):
            take.append(row)
        else:
            held.append(row)
    return take, held, freq


def held_pairs(held: list) -> dict:
    g = defaultdict(list)
    for rel, _, t, _, lab in held:
        g[(t, lab)].append(rel)
    return g


def main() -> int:
    argv = sys.argv[1:]
    apply = "--apply" in argv
    verbose = "--verbose" in argv
    min_freq = int(argv[argv.index("--min-freq") + 1]) if "--min-freq" in argv \
        else MIN_FREQ_DEFAULT

    cand, stray, g = scan()
    by_id = g["by_id"]
    take, held, freq = classify(cand, by_id, min_freq)

    print(f"кандидатов (ссылка в related без ребра): {len(cand)}")
    print(f"порог частоты: {min_freq}")
    print(f"   вставить:  {len(take)}")
    print(f"   придержать:{len(held):>4}   пар: {len(held_pairs(held))}")
    if stray:
        print(f"   ссылки не на узел вне белого списка: {len(stray)}")
        for rel, href in stray[:10]:
            print(f"      {rel}  →  {href}")

    print("\nпридержано по правилу — цель широкая, подпись без пояснения:")
    for (t, lab), pages in sorted(held_pairs(held).items(), key=lambda x: -len(x[1])):
        print(f"   ×{len(pages):<3} {t:20} [{by_id[t]['type']:9}] «{lab}»")
        if verbose:
            for p in sorted(pages):
                print(f"           {p}")

    hp = held_pairs(held)
    lines = [
        "Придержанные рёбра из related — решение, а не долг.",
        "Цель широкая, подпись равна названию узла без пояснения после тире:",
        "связь утверждается, но причина не названа.",
        f"Правило: scripts/related-edges.py, порог частоты {min_freq}.",
        "",
    ]
    for (t, lab), pages in sorted(hp.items(), key=lambda x: -len(x[1])):
        lines.append(f"{t}\t{by_id[t]['type']}\t«{lab}»\t×{len(pages)}")
        lines += [f"\t{p}" for p in sorted(pages)]
    held_txt = "\n".join(lines) + "\n"

    if not apply:
        print(f"\nread-only. Вставить: python3 scripts/related-edges.py --apply")
        return 0

    sp = os.environ.get("SCRATCHPAD")
    if sp:
        with open(os.path.join(sp, "held.txt"), "w", encoding="utf-8") as f:
            f.write(held_txt)
        print(f"\nпридержанное записано в {sp}/held.txt")

    p = os.path.join(ROOT, "data", "links.json")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    data = json.loads(src)
    if json.dumps(data, ensure_ascii=False, indent=2) != src:
        print("ОШИБКА: round-trip не совпал, править структурой нельзя.")
        return 1
    have = {(e["from"], e["to"]) for e in data["edges"]}
    added = 0
    for _, nid, t, _, _ in take:
        if (nid, t) in have:
            continue
        have.add((nid, t))
        data["edges"].append({"from": nid, "to": t})
        added += 1
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"добавлено рёбер: {added}   всего в графе: {len(data['edges'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
