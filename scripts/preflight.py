#!/usr/bin/env python3
"""Предполётная проверка перед пушем. Read-only, без зависимостей.

Usage:  python3 scripts/preflight.py [--verbose]

Reads:  data/links.json (рабочее дерево и HEAD), essays/index.html,
        sitemap.xml, git ls-files, страницы узлов графа
Writes: ничего. Только печатает.

Выход: 0 если блокеров нет и graph-health.py доволен, иначе 1.

Ловит класс процедурных ошибок, который проходит мимо всех остальных
скриптов: не «сайт неправильный», а «сайт правильный, но набор шагов
выполнен в неверном порядке или не до конца».

Счётчики страниц не переизобретаются: count_pages/is_redirect
импортируются из update_counts.py, чтобы две реализации не разъехались.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PREFIX = "/null/"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from update_counts import count_pages  # noqa: E402
    COUNT_PAGES_OK = True
except Exception as exc:  # pragma: no cover - диагностика, не логика
    COUNT_PAGES_OK = False
    COUNT_PAGES_ERR = exc

# Списки длинных находок печатаются урезанными: preflight должен читаться
# целиком, а не прокручиваться. Урезание всегда объявляется в выводе —
# молча спрятанная находка хуже, чем её отсутствие.
VERBOSE = "--verbose" in sys.argv[1:]
LIST_CAP = 8

blockers: list[str] = []
warnings: list[str] = []


def head(title: str) -> None:
    print(f"\n{title}")
    print("─" * 66)


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout


def graph_stats(d: dict) -> tuple[int, int, int]:
    pairs = {(e["from"], e["to"]) for e in d["edges"]}
    recip = sum(1 for a, b in pairs if (b, a) in pairs)
    return len(d["nodes"]), len(d["edges"]), recip


# ── 1 · дельта графа против HEAD ────────────────────────────────────
def check_graph_delta() -> None:
    head("1 · дельта графа против HEAD")
    rc, base_src = git("show", "HEAD:data/links.json")
    if rc != 0:
        print("   HEAD:data/links.json недоступен — сравнивать не с чем.")
        return
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        cur = json.load(f)
    base = json.loads(base_src)

    bn, be, br = graph_stats(base)
    cn, ce, cr = graph_stats(cur)
    dn, de, dr = cn - bn, ce - be, cr - br

    print(f"   узлы          {bn} → {cn}   (Δ {dn:+d})")
    print(f"   рёбра         {be} → {ce}   (Δ {de:+d})")
    print(f"   взаимных      {br} → {cr}   (Δ {dr:+d})")

    if de == 0:
        print("   рёбра не менялись — отношение не считается.")
        return
    ratio = dr / de
    print(f"   Δвзаимных / Δрёбер = {ratio:.2f}")
    if abs(ratio - 2.0) < 0.15:
        note = "патч достраивает симметрию к существующим рёбрам"
    elif ratio == 0:
        note = ("рёбра идут в одну сторону — проверьте, не останется ли "
                "чей-то блок backlinks без подтверждения (см. проверку 4)")
    else:
        note = "заводится новый узел наружу"
    print(f"   → {note}")
    print("   [индикатор, не блокер]")


# ── 2 · новые страницы без даты в git ───────────────────────────────
def check_new_pages() -> None:
    head("2 · новые страницы и <lastmod>")
    # --others --exclude-standard = неотслеживаемые, но НЕ игнорируемые.
    # Обходить диск руками нельзя: под .gitignore лежат страницы, которые
    # в git не попадут никогда (прототипы в tools/), и они не дефект.
    rc, out = git("ls-files", "--others", "--exclude-standard", "*.html")
    if rc != 0:
        print("   git ls-files не отработал — проверка пропущена.")
        warnings.append("проверка 2 не отработала")
        return
    new = sorted(out.split())
    if not new:
        print("   новых страниц вне git: 0 ✓")
    else:
        print(f"   новых страниц вне git: {len(new)}")
        for rel in new:
            print(f"      {rel} — lastmod появится только после коммита")

    # Прямая проверка самого дефекта, а не его признака: запись без даты.
    sm = os.path.join(ROOT, "sitemap.xml")
    if os.path.isfile(sm):
        with open(sm, encoding="utf-8") as f:
            text = f.read()
        missing = [
            re.search(r"<loc>(.*?)</loc>", u).group(1)
            for u in re.findall(r"<url>.*?</url>", text, re.S)
            if "<lastmod>" not in u
        ]
        if missing:
            print(f"   БЛОКЕР: записей без <lastmod> в sitemap.xml — {len(missing)}:")
            for loc in missing[:10]:
                print(f"      {loc}")
            if len(missing) > 10:
                print(f"      … и ещё {len(missing) - 10}")
            print("   Карта сгенерирована до коммита. Закоммитьте страницы")
            print("   и прогоните generate_sitemap.py заново.")
            blockers.append("sitemap: записи без <lastmod>")
        else:
            print("   записей без <lastmod>: 0 ✓")

    if new:
        rc_sm, _ = git("diff", "--quiet", "HEAD", "--", "sitemap.xml")
        if rc_sm != 0:
            print("   БЛОКЕР: есть незакоммиченные страницы, а sitemap.xml уже изменён —")
            print("   карту сгенерировали рано.")
            blockers.append("sitemap сгенерирован до коммита новых страниц")


# ── 3 · согласованность essays/index.html ───────────────────────────
def check_essay_index() -> None:
    head("3 · счётчики essays/index.html")
    path = os.path.join(ROOT, "essays", "index.html")
    with open(path, encoding="utf-8") as f:
        s = f.read()

    sec: dict[str, int] = {}
    for sid in re.findall(r'id="(s\d+)"', s):
        m = re.compile(r'<span class="essay-section-count">(\d+)</span>').search(
            s, s.index(f'id="{sid}"'))
        if m:
            sec[sid] = int(m.group(1))
    card: dict[str, int] = {}
    for sid in re.findall(r'href="#(s\d+)"', s):
        m = re.compile(r'<div class="card-num">(\d+) эссе</div>').search(
            s, s.index(f'href="#{sid}"'))
        if m:
            card[sid] = int(m.group(1))

    bad = [(k, sec[k], card.get(k)) for k in sorted(sec) if sec[k] != card.get(k)]
    print(f"   секций: {len(sec)}, карточек: {len(card)}")
    if bad:
        print(f"   БЛОКЕР: расхождений заголовок/карточка — {len(bad)}:")
        for sid, a, b in bad:
            print(f"      §{sid[1:]}: заголовок {a} ≠ карточка {b}")
        blockers.append("essays/index.html: счётчик секции ≠ карточке")
    else:
        print("   заголовок = карточка во всех секциях ✓")

    total = sum(sec.values())
    if not COUNT_PAGES_OK:
        print(f"   count_pages не импортировался ({COUNT_PAGES_ERR}).")
        print(f"   сумма счётчиков — {total}. СВЕРИТЬ РУКАМИ с числом эссе.")
        warnings.append("count_pages не импортировался, сумма не сверена")
        return
    essays = count_pages("essays")
    print(f"   сумма счётчиков {total} vs эссе на диске {essays}", end="   ")
    if total == essays:
        print("✓")
    else:
        print("✗")
        print("   БЛОКЕР: сумма счётчиков секций ≠ числу не-редиректных страниц")
        print("   в essays/. Записи, ведущие в objects/, в счётчик не входят —")
        print("   если расхождение равно их числу, поправьте счётчик секции.")
        blockers.append("essays/index.html: сумма счётчиков ≠ числу эссе")


# ── 4 · блок backlinks против графа ─────────────────────────────────
def check_backlinks() -> None:
    head("4 · блок backlinks против входящих рёбер")
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        d = json.load(f)
    by_id = {n["id"]: n for n in d["nodes"]}
    incoming: dict[str, set[str]] = {i: set() for i in by_id}
    for e in d["edges"]:
        if e["to"] in incoming and e["from"] in by_id:
            incoming[e["to"]].add(e["from"])

    block_re = re.compile(r'<section class="backlinks">.*?</section>', re.S)
    stale, unbacked, absent = [], [], []

    for nid, n in by_id.items():
        url = n.get("url", "")
        if not url.startswith(SITE_PREFIX):
            continue
        rel = url[len(SITE_PREFIX):]
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            html = f.read()
        m = block_re.search(html)
        want = {by_id[s]["url"] for s in incoming[nid]}

        if m is None:
            if want:
                absent.append((rel, len(want)))
            continue
        got = set(re.findall(r'href="([^"]+)"', m.group(0)))
        if not want:
            unbacked.append((rel, len(got)))
        elif got != want:
            stale.append((rel, sorted(got - want), sorted(want - got)))

    if unbacked:
        print(f"   блок есть, входящих рёбер нет — {len(unbacked)}:")
        for rel, k in unbacked:
            print(f"      {rel}  ({k} ссылок)")
        print("   build-backlinks.js такой файл пропускает: блок остаётся,")
        print("   но графом не подтверждён и синхронизироваться не будет.")
        print("   Эти связи не видны на карте. Нужны входящие рёбра.")
        warnings.append(f"backlinks без входящих рёбер: {len(unbacked)}")

    if stale:
        print(f"   набор ссылок разошёлся с графом — {len(stale)}:")
        shown = stale if VERBOSE else stale[:LIST_CAP]
        for rel, extra, miss in shown:
            bits = []
            if miss:
                bits.append(f"+{len(miss)} нет в блоке")
            if extra:
                bits.append(f"-{len(extra)} лишних")
            print(f"      {rel}  ({', '.join(bits)})")
            if VERBOSE:
                for x in miss:
                    print(f"         нет в блоке:    {x}")
                for x in extra:
                    print(f"         лишняя в блоке: {x}")
        if len(shown) < len(stale):
            print(f"      … и ещё {len(stale) - len(shown)} — полный список: --verbose")
        print("   build-backlinks.js перепишет блок по графу.")
        print("   Лечится прогоном: node data/build-backlinks.js")
        warnings.append(f"backlinks разошлись с графом: {len(stale)}")

    if absent:
        print(f"   входящие рёбра есть, блока нет — {len(absent)}:")
        shown = absent if VERBOSE else absent[:LIST_CAP]
        for rel, k in shown:
            print(f"      {rel}  (появится ссылок: {k})")
        if len(shown) < len(absent):
            print(f"      … и ещё {len(absent) - len(shown)} — полный список: --verbose")
        print("   build-backlinks.js добавит блок. [информация, не блокер]")

    if not (unbacked or stale or absent):
        print("   блоки совпадают с графом ✓")
    print("   Заголовки и порядок ссылок — дело генератора, здесь не сверяются:")
    print("   сравнивается только набор адресов.")


# ── 5 · graph-health.py ─────────────────────────────────────────────
def check_graph_health() -> int:
    head("5 · graph-health.py")
    gh = os.path.join(ROOT, "graph-health.py")
    if not os.path.isfile(gh):
        print("   graph-health.py не найден в корне.")
        warnings.append("graph-health.py отсутствует")
        return 0
    p = subprocess.run([sys.executable, gh], cwd=ROOT, capture_output=True, text=True)
    for line in p.stdout.rstrip("\n").split("\n"):
        print(f"   {line}")
    if p.returncode != 0:
        blockers.append("graph-health.py вернул ненулевой код")
    return p.returncode


# ── 6 · итог ────────────────────────────────────────────────────────
def summary() -> int:
    head("6 · итог")
    if warnings:
        print(f"   предупреждений: {len(warnings)}")
        for w in warnings:
            print(f"      · {w}")
    if blockers:
        print(f"   БЛОКЕРОВ: {len(blockers)}")
        for b in blockers:
            print(f"      ✗ {b}")
        print("\n   Пушить нельзя, пока блокеры не сняты.")
    else:
        print("   блокеров нет ✓")

    print("""
   Порядок при добавлении страницы:

      скрипты → commit → generate_sitemap.py → commit --amend → push

   update_meta.py и update_counts.py гоняются ДО коммита.
   generate_sitemap.py — ПОСЛЕ: он берёт lastmod из git, и у
   незакоммиченной страницы даты нет.
   Счётчики в essays/index.html правятся руками, два числа на секцию.""")
    return 1 if blockers else 0


def main() -> int:
    print("preflight · предполётная проверка null")
    check_graph_delta()
    check_new_pages()
    check_essay_index()
    check_backlinks()
    check_graph_health()
    return summary()


if __name__ == "__main__":
    raise SystemExit(main())
