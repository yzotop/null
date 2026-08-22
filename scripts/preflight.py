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
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SITE_PREFIX = "/null/"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from update_counts import (  # noqa: E402
        count_pages, collect_counts, build_rules, plural)
    COUNT_PAGES_OK = True
except Exception as exc:  # pragma: no cover - диагностика, не логика
    COUNT_PAGES_OK = False
    COUNT_PAGES_ERR = exc

# Даты и раскладку URL берёт сам generate_sitemap.py — второй реализации
# быть не должно. git_lastmod() читает всю историю одним вызовом git:
# 0.09 с против 2.4 с у 345 отдельных `git log -1` (мерено, не оценено).
try:
    from generate_sitemap import git_lastmod, to_loc, find_pages  # noqa: E402
    SITEMAP_API_OK = True
except Exception as exc:  # pragma: no cover
    SITEMAP_API_OK = False
    SITEMAP_API_ERR = exc

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


def indegree(d: dict) -> dict[str, int]:
    """Входящие по узлам. Рёбра в несуществующие узлы не считаются —
    иначе висячее ребро выглядело бы как «у узла кто-то есть»."""
    ids = {n["id"] for n in d["nodes"]}
    deg = {i: 0 for i in ids}
    for e in d["edges"]:
        if e["to"] in ids and e["from"] in ids:
            deg[e["to"]] += 1
    return deg


def show_list(items: list[str], head: str, tail: str = "") -> None:
    print(head)
    shown = items if VERBOSE else items[:LIST_CAP]
    for line in shown:
        print(f"      {line}")
    if len(shown) < len(items):
        print(f"      … и ещё {len(items) - len(shown)} — полный список: --verbose")
    if tail:
        print(tail)


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

    # Имена печатаются до любых ранних выходов: патч, заменяющий одно
    # ребро другим, даёт Δрёбер = 0 и при этом может уронить узел
    # в ноль входящих.
    name_changes(base, cur)

    if de == 0:
        print("   рёбра не менялись — отношение не считается.")
        return
    if de < 0:
        # Отношение считается только на добавлении: при удалении обе
        # дельты отрицательны, и −2/−1 = 2.00 читалось бы как
        # «достраивает симметрию» — ровно наоборот смыслу.
        print("   рёбра удалялись — отношение не расшифровывается.")
        print("   [индикатор, не блокер]")
        return
    ratio = dr / de
    print(f"   Δвзаимных / Δрёбер = {ratio:.2f}")
    if abs(ratio - 2.0) < 0.15:
        note = "патч достраивает симметрию к уже существующим рёбрам"
    elif abs(ratio - 1.0) < 0.15:
        note = "добавляются взаимные пары там, где не было ни одной стороны"
    elif ratio == 0:
        note = ("рёбра идут в одну сторону — проверьте, не останется ли "
                "чей-то блок backlinks без подтверждения (см. проверки 4 и 6)")
    else:
        note = "смесь: часть рёбер достраивает симметрию, часть уходит наружу"
    print(f"   → {note}")
    print("   [индикатор, не блокер]")


def name_changes(base: dict, cur: dict) -> None:
    """Кто именно сдвинулся — а не только на сколько.

    Счётчик «без входящих» в build-backlinks.js двигается ровно на этих
    переходах, и без имён его сдвиг приходится объяснять догадками.
    Один раз так и объяснили — неверным узлом.
    """
    nb, na = indegree(base), indegree(cur)
    titles = {n["id"]: n.get("title", "") for n in cur["nodes"]}
    titles.update({n["id"]: n.get("title", "") for n in base["nodes"]
                   if n["id"] not in titles})
    pairs_b = {(e["from"], e["to"]) for e in base["edges"]}
    pairs_a = {(e["from"], e["to"]) for e in cur["edges"]}
    added, removed = pairs_a - pairs_b, pairs_b - pairs_a

    # ── появились входящие там, где их не было ──
    gained = sorted(i for i in na if na[i] > 0 and nb.get(i, 0) == 0)
    if gained:
        rows = []
        for i in gained:
            src = sorted(a for a, b in added if b == i) or ["?"]
            rows.append(f"{i} «{titles.get(i, '')[:34]}»  ← {', '.join(src)}")
        show_list(rows, f"   появились входящие ({len(gained)}):",
                  "   На столько же уменьшится «без входящих» у build-backlinks.js.")

    # ── входящие пропали: узел выпал из блоков backlinks ──
    lost = sorted(i for i in na if na[i] == 0 and nb.get(i, 0) > 0)
    if lost:
        rows = []
        for i in lost:
            src = sorted(a for a, b in removed if b == i) or ["?"]
            rows.append(f"{i} «{titles.get(i, '')[:34]}»  ✗ {', '.join(src)}")
        show_list(rows, f"   ВХОДЯЩИЕ ПРОПАЛИ ({len(lost)}):",
                  "   Блок «упоминается в» у этих узлов генератор больше не тронет:\n"
                  "   файл узла без входящих он не открывает. Снимать руками.")
        warnings.append(f"узлы потеряли все входящие: {len(lost)}")

    # ── новое ребро оказалось обратной стороной уже бывшего ──
    mutual = sorted((a, b) for a, b in added if (b, a) in pairs_b)
    if mutual:
        show_list([f"{a} → {b}   (обратное {b} → {a} уже было)" for a, b in mutual],
                  f"   стали взаимными к существовавшим рёбрам ({len(mutual)}):")


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

    check_lastmod_fresh()


def check_lastmod_fresh() -> None:
    """<lastmod> против даты последнего коммита, тронувшего страницу.

    lastmod меняется от ЛЮБОЙ правки файла, включая машинную: прогон
    build-backlinks.js сменил дату 57 страницам, ничего не добавив.
    Правило «карта после коммита» шире, чем «карта после новой страницы».

    Не блокер: в момент запуска preflight правки ещё не закоммичены, и
    расхождение — нормальное рабочее состояние. Смысл в другом — увидеть
    карту, отставшую от УЖЕ сделанных коммитов.
    """
    if not SITEMAP_API_OK:
        print(f"   generate_sitemap не импортировался ({SITEMAP_API_ERR}) —")
        print("   свежесть <lastmod> не проверена.")
        warnings.append("свежесть lastmod не проверена")
        return
    sm = os.path.join(ROOT, "sitemap.xml")
    if not os.path.isfile(sm):
        return
    with open(sm, encoding="utf-8") as f:
        text = f.read()

    dates = git_lastmod()
    loc2rel = {to_loc(rel): rel for rel in find_pages()}

    stale, orphan = [], []
    for u in re.findall(r"<url>.*?</url>", text, re.S):
        loc = re.search(r"<loc>(.*?)</loc>", u).group(1)
        lm = re.search(r"<lastmod>(.*?)</lastmod>", u)
        rel = loc2rel.get(loc)
        if rel is None:
            orphan.append(loc)
            continue
        actual = dates.get(rel)
        if actual and lm and lm.group(1) != actual:
            stale.append((rel, lm.group(1), actual))

    if orphan:
        print(f"   URL в карте без файла на диске: {len(orphan)}")
        for loc in orphan[:LIST_CAP]:
            print(f"      {loc}")
        if len(orphan) > LIST_CAP:
            print(f"      … и ещё {len(orphan) - LIST_CAP} — полный список: --verbose"
                  if not VERBOSE else "")
        warnings.append(f"URL в карте без файла: {len(orphan)}")

    if not stale:
        print("   <lastmod> совпадает с датами коммитов ✓")
        return
    print(f"   карта отстала от коммитов — страниц: {len(stale)}")
    shown = stale if VERBOSE else stale[:LIST_CAP]
    for rel, was, now in shown:
        print(f"      {rel}  {was} → {now}")
    if len(shown) < len(stale):
        print(f"      … и ещё {len(stale) - len(shown)} — полный список: --verbose")
    print("   Нужен прогон generate_sitemap.py ПОСЛЕ коммита: <lastmod>")
    print("   меняется от любой правки файла, не только от новой страницы.")
    print("   [предупреждение, не блокер]")
    warnings.append(f"lastmod отстал: {len(stale)}")


# ── 3 · согласованность essays/index.html ───────────────────────────
def check_essay_index() -> None:
    head("3 · счётчики на страницах")
    print("   ── essays/index.html: правятся руками ──")
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
    check_script_counts()


def check_script_counts() -> None:
    """Позиции, за которые отвечает update_counts.py.

    Расхождение значит одно: скрипт не гонялся после правки, и страница
    показывает вчерашнее число. Именно так index.html и man.html
    продержали 1710 рёбер при 1968 в графе.

    Правила и подсчёт импортируются из update_counts.py — второй
    реализации быть не должно, иначе разойдутся именно они.
    """
    print("   ── index.html и man.html: считает update_counts.py ──")
    if not COUNT_PAGES_OK:
        print("   update_counts не импортировался — позиции не сверены.")
        warnings.append("позиции update_counts не сверены")
        return
    counts = collect_counts()
    files: dict[str, str] = {}
    stale, missing = [], []
    for fname, label, pattern, key, forms in build_rules(counts):
        if fname not in files:
            with open(os.path.join(ROOT, fname), encoding="utf-8") as f:
                files[fname] = f.read()
        m = re.compile(pattern, re.S).search(files[fname])
        if not m:
            missing.append(label)
            continue
        was, now = int(m.group(2)), counts[key]
        tail_was = m.group(3)
        tail_now = (" " + plural(now, forms)) if forms else tail_was
        if was != now or tail_was != tail_now:
            stale.append((label, f"{was}{tail_was}", f"{now}{tail_now}"))

    if missing:
        print(f"   БЛОКЕР: шаблонов не найдено — {len(missing)}: {', '.join(missing)}")
        blockers.append("update_counts: шаблоны не найдены")
    if stale:
        print(f"   БЛОКЕР: позиций отстало — {len(stale)}:")
        for label, was, now in (stale if VERBOSE else stale[:LIST_CAP]):
            print(f"      {label:<22} {was} → должно быть {now}")
        if not VERBOSE and len(stale) > LIST_CAP:
            print(f"      … и ещё {len(stale) - LIST_CAP} — полный список: --verbose")
        print("   Лечится прогоном: python3 scripts/update_counts.py")
        blockers.append(f"update_counts: отстало позиций {len(stale)}")
    if not stale and not missing:
        print(f"   все {len(build_rules(counts))} позиций совпадают с фактом ✓")


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
    stale, absent = [], []

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
                # Генератор вставляет блок ПОСЛЕ <section class="related">.
                # Нет якоря — нет вставки: [skip] no related section.
                anchored = '<section class="related">' in html
                absent.append((rel, len(want), anchored))
            continue
        got = set(re.findall(r'href="([^"]+)"', m.group(0)))
        if not want:
            continue  # разбирается в проверке 6: генератор такой файл не открывает
        if got != want:
            stale.append((rel, sorted(got - want), sorted(want - got)))

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

    will = [a for a in absent if a[2]]
    cant = [a for a in absent if not a[2]]
    if will:
        print(f"   входящие рёбра есть, блока нет — {len(will)}:")
        shown = will if VERBOSE else will[:LIST_CAP]
        for rel, k, _ in shown:
            print(f"      {rel}  (появится ссылок: {k})")
        if len(shown) < len(will):
            print(f"      … и ещё {len(will) - len(shown)} — полный список: --verbose")
        print("   build-backlinks.js добавит блок. [информация, не блокер]")
    if cant:
        print(f"   входящие рёбра есть, но вставить блок некуда — {len(cant)}:")
        shown = cant if VERBOSE else cant[:LIST_CAP]
        for rel, k, _ in shown:
            print(f"      {rel}  (потеряно ссылок: {k})")
        if len(shown) < len(cant):
            print(f"      … и ещё {len(cant) - len(shown)} — полный список: --verbose")
        print("   На странице нет <section class=\"related\">, а генератор")
        print("   вставляет блок только после неё — он их пропускает")
        print("   ([skip] no related section). Эти связи на страницах не видны.")
        warnings.append(f"backlinks некуда вставить: {len(cant)}")

    if not (stale or absent):
        print("   блоки совпадают с графом ✓")
    print("   Заголовки и порядок ссылок — дело генератора, здесь не сверяются:")
    print("   сравнивается только набор адресов.")


# ── 5 · related против исходящих рёбер ──────────────────────────────
def check_related_vs_out() -> None:
    """related ⊆ исходящие рёбра.

    Зеркало проверки 4: та сверяет backlinks против входящих, эта —
    related против исходящих. Асимметрия намеренная:
      ссылка без ребра  — дефект (страница утверждает связь, которой
                          нет на карте и не будет в чужих backlinks);
      ребро без ссылки  — норма (секция курируется автором).

    Правило отбора и белый список не дублируются: и то и другое
    импортируется из scripts/related-edges.py. Придержанное по правилу
    считается отдельной строкой — это принятое решение, а не долг,
    и основное число обязано сходиться в ноль. Проверка, которая
    навсегда застыла на ненулевом остатке, перестаёт читаться.
    """
    head("5 · related против исходящих рёбер")
    try:
        import importlib.util
        # Имя файла с дефисом не импортируется обычным import.
        spec = importlib.util.spec_from_file_location(
            "related_edges", os.path.join(ROOT, "scripts", "related-edges.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  # pragma: no cover
        print(f"   related-edges.py не загрузился ({exc}) — проверка пропущена.")
        warnings.append("проверка 5 не отработала")
        return

    cand, stray, g = mod.scan()
    take, held, _ = mod.classify(cand, g["by_id"], mod.MIN_FREQ_DEFAULT)

    if stray:
        print(f"   ссылки не на узел и не в белом списке — {len(stray)}:")
        for rel, href in (stray if VERBOSE else stray[:LIST_CAP]):
            print(f"      {rel}  →  {href}")
        if not VERBOSE and len(stray) > LIST_CAP:
            print(f"      … и ещё {len(stray) - LIST_CAP} — полный список: --verbose")
        warnings.append(f"related: ссылки не на узел: {len(stray)}")
    else:
        print("   ссылки не на узел: все в белом списке ✓")

    if held:
        pairs = mod.held_pairs(held)
        print(f"   придержано по правилу: {len(held)} рёбер в {len(pairs)} парах")
        print("      цель широкая, подпись равна названию узла без пояснения")
        print("      список с частотой и страницами — held.txt")
        if VERBOSE:
            for (t, lab), pages in sorted(pairs.items(), key=lambda x: -len(x[1])):
                print(f"      ×{len(pages):<3} {t:20} «{lab}»")

    if not take:
        print("   ссылок без ребра, не покрытых правилом: 0 ✓")
        return
    rows = [f"{r}  {a} → {b}  «{lab[:34]}»" for r, a, b, _, lab in sorted(take)]
    show_list(rows, f"   ссылок без ребра: {len(take)} — новые, правилом не покрыты:")
    print("   Лечится прогоном: python3 scripts/related-edges.py --apply")
    warnings.append(f"related без ребра: {len(take)}")


# ── 6 · расхождение с генератором backlinks ─────────────────────────
def node_pages() -> tuple[dict, dict[str, str]]:
    """Граф и {repo-path: node-id} для узлов, чьи файлы существуют."""
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        d = json.load(f)
    pages = {}
    for n in d["nodes"]:
        url = n.get("url", "")
        if url.startswith(SITE_PREFIX):
            rel = url[len(SITE_PREFIX):]
            if os.path.isfile(os.path.join(ROOT, rel)):
                pages[rel] = n["id"]
    return d, pages


def check_generator_drift() -> None:
    head("6 · расхождение с генератором backlinks")
    d, pages = node_pages()
    block_re = re.compile(r'<section class="backlinks">.*?</section>', re.S)

    # ── часть 2: блок при нуле входящих рёбер ──
    # Считается без node: это чистый анализ графа и HTML, и потерять его
    # из-за отсутствия node нельзя — генератор такие файлы не открывает
    # вовсе (if (!block) continue стоит раньше удаления старого блока),
    # значит больше это нигде не всплывёт.
    by_id = {n["id"]: n for n in d["nodes"]}
    indeg = {i: 0 for i in by_id}
    for e in d["edges"]:
        if e["to"] in indeg and e["from"] in by_id:
            indeg[e["to"]] += 1
    dead = []
    for rel, nid in pages.items():
        if indeg[nid]:
            continue
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            m = block_re.search(f.read())
        if m:
            dead.append((rel, len(re.findall(r'href="', m.group(0)))))
    if dead:
        print(f"   блок есть, входящих рёбер нет — {len(dead)}:")
        for rel, k in dead:
            print(f"      {rel}  (ссылок в блоке: {k})")
        print("   Генератор такой файл не открывает: блок остаётся навсегда,")
        print("   графом не подтверждён, на карте этих связей нет.")
        print("   Прогон не лечит — снимать руками или заводить рёбра.")
        warnings.append(f"backlinks при нуле входящих: {len(dead)}")
    else:
        print("   блоков при нуле входящих рёбер: 0 ✓")

    # ── часть 1: что переписал бы прогон генератора ──
    gen = os.path.join(ROOT, "data", "build-backlinks.js")
    if not os.path.isfile(gen):
        print("   data/build-backlinks.js не найден — сравнивать нечем.")
        return
    if shutil.which("node") is None:
        print("   node в системе нет — расхождение с генератором не проверено.")
        return

    with tempfile.TemporaryDirectory(prefix="preflight-backlinks-") as tmp:
        # Копируется только то, что генератор читает и пишет: сам скрипт,
        # граф и страницы узлов. Портреты в objects/ весят больше всего
        # остального вместе взятого и генератору не нужны.
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        shutil.copy2(gen, os.path.join(tmp, "data", "build-backlinks.js"))
        shutil.copy2(os.path.join(ROOT, "data", "links.json"),
                     os.path.join(tmp, "data", "links.json"))
        for rel in pages:
            dst = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, rel), dst)

        r = subprocess.run(
            ["node", os.path.join(tmp, "data", "build-backlinks.js")],
            cwd=tmp, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print("   прогон генератора в копии не удался:")
            for line in (r.stderr or "").strip().split("\n")[:5]:
                print(f"      {line}")
            warnings.append("генератор не отработал в копии")
            return

        drift = []
        for rel in sorted(pages):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                a = f.read()
            with open(os.path.join(tmp, rel), encoding="utf-8") as f:
                b = f.read()
            if a != b:
                drift.append(rel)

    if not drift:
        print("   дерево совпадает с выводом генератора ✓")
        return
    print(f"   генератор переписал бы файлов: {len(drift)}")
    shown = drift if VERBOSE else drift[:LIST_CAP]
    for rel in shown:
        print(f"      {rel}")
    if len(shown) < len(drift):
        print(f"      … и ещё {len(drift) - len(shown)} — полный список: --verbose")
    print("   Лечится прогоном: node data/build-backlinks.js")
    print("   [предупреждение, не блокер: прогон — осознанное действие,")
    print("    а не то, что делается перед каждым пушем]")
    warnings.append(f"расхождение с генератором backlinks: {len(drift)}")


# ── 7 · graph-health.py ─────────────────────────────────────────────
def check_graph_health() -> int:
    head("7 · graph-health.py")
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


# ── 8 · мета-блоки эссе ─────────────────────────────────────────────
def check_meta() -> None:
    """Гонялся ли update_meta.py.

    Скрипт надёжен сам по себе: валидирует все файлы до записи и падает
    с точным диагнозом при кривых маркерах или заголовке. Но его результат
    не сверял никто — страница, добавленная без прогона, тихо остаётся
    без canonical и og-разметки. В браузере это не видно, в выдаче — да.

    Правила импортируются из update_meta.py: своей копии meta_block()
    тут быть не должно, иначе разойдутся именно они.
    """
    head("8 · мета-блоки эссе")
    try:
        import update_meta as um
    except Exception as exc:  # pragma: no cover
        print(f"   update_meta не импортировался ({exc}) — проверка пропущена.")
        warnings.append("мета-блоки не сверены")
        return

    src = os.path.join(ROOT, um.TARGET_DIR)
    files = []
    for fn in sorted(os.listdir(src)):
        if not fn.endswith(".html") or fn == "index.html":
            continue
        with open(os.path.join(src, fn), encoding="utf-8") as f:
            text = f.read()
        if um.is_redirect(text):
            continue
        files.append((f"{um.TARGET_DIR}/{fn}", text))

    # ── якорь не найден: структура файла не та, что скрипт ожидает ──
    broken = []
    for rel, text in files:
        for e in um.validate(rel, text):
            broken.append(f"{rel}: {e}")
    if broken:
        n = len({b.split(":")[0] for b in broken})
        show_list(broken, f"   БЛОКЕР: страниц с непредвиденной структурой — {n}:")
        print("   update_meta.py на таком дереве не запишет ничего.")
        blockers.append("update_meta: структура страниц не та")
        return

    # ── результат отстал: скрипт не гонялся ──
    stale = []
    for rel, text in files:
        title = um.TITLE_RE.search(text).group(1).strip()
        topic = title[: -len(um.TITLE_SUFFIX)]
        block = um.meta_block(topic, um.to_loc(rel))
        if um.BLOCK_RE.search(text):
            if um.BLOCK_RE.sub(lambda _: block, text, count=1) != text:
                stale.append(f"{rel} — блок устарел")
        else:
            stale.append(f"{rel} — блока нет")

    print(f"   эссе с мета-блоком: {len(files)}")
    if stale:
        show_list(stale, f"   БЛОКЕР: страниц не в актуальном состоянии — {len(stale)}:")
        print("   Лечится прогоном: python3 scripts/update_meta.py")
        blockers.append(f"update_meta: отстало страниц {len(stale)}")
    else:
        print("   все совпадают с тем, что записал бы update_meta.py ✓")


# ── 9 · итог ────────────────────────────────────────────────────────
def summary() -> int:
    head("9 · итог")
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
   Порядок при любой правке *.html:

      скрипты → commit → generate_sitemap.py → commit --amend → push

   update_meta.py и update_counts.py гоняются ДО коммита.
   generate_sitemap.py — ПОСЛЕ: он берёт lastmod из git, и у
   незакоммиченной страницы даты нет.

   Карту надо перегенерировать после ЛЮБОГО коммита, меняющего *.html,
   а не только после новой страницы: lastmod меняется от любой правки
   файла, включая машинную (прогон build-backlinks.js).

   Счётчики в essays/index.html правятся руками, два числа на секцию.""")
    return 1 if blockers else 0


def main() -> int:
    print("preflight · предполётная проверка null")
    check_graph_delta()
    check_new_pages()
    check_essay_index()
    check_backlinks()
    check_related_vs_out()
    check_generator_drift()
    check_graph_health()
    check_meta()
    return summary()


if __name__ == "__main__":
    raise SystemExit(main())
