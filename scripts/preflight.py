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
    from update_counts import count_pages  # noqa: E402
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
# Ссылки в related, ведущие не на узел графа. Это разделы и карта —
# законные адресаты, но подтвердить ребром их нечем: узла нет.
# Список явный, чтобы проверка сходилась в ноль, а не в «семь всегда».
RELATED_NON_NODE = {
    "objects/numbers/constants/",   # раздел констант
    "music",                        # раздел музыки
    "visuals",                      # раздел визуалов
    "map.html",                     # карта связей
}


def check_related_vs_out() -> None:
    """related ⊆ исходящие рёбра.

    Зеркало проверки 4: та сверяет backlinks против входящих, эта —
    related против исходящих. Асимметрия намеренная:
      ссылка без ребра  — дефект (страница утверждает связь, которой
                          нет на карте и не будет в чужих backlinks);
      ребро без ссылки  — норма (секция курируется автором).

    Ключ — пара (узел, полный href): #pavlov и #generous-tit-for-tat
    ведут на один файл, но это разные адресаты, и склеивать их нельзя.

    Предупреждение, не блокер: долг накоплен и разбирается порциями.
    """
    head("5 · related против исходящих рёбер")
    with open(os.path.join(ROOT, "data", "links.json"), encoding="utf-8") as f:
        d = json.load(f)
    by_url = {n["url"]: n["id"] for n in d["nodes"]}
    out: dict[str, set[str]] = {}
    for e in d["edges"]:
        out.setdefault(e["from"], set()).add(e["to"])
    rel_re = re.compile(r'<section class="related">.*?</section>', re.S)
    link_re = re.compile(r'<a href="([^"]+)">(.*?)\s*→</a>')

    missing, stray = [], []
    for n in d["nodes"]:
        url = n.get("url", "")
        if not url.startswith(SITE_PREFIX):
            continue
        rel = url[len(SITE_PREFIX):]
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            m = rel_re.search(f.read())
        if not m:
            continue
        base = os.path.dirname(rel)
        seen = set()
        for href, label in link_re.findall(m.group(0)):
            p = (href[len(SITE_PREFIX):] if href.startswith(SITE_PREFIX)
                 else os.path.normpath(os.path.join(base, href)))
            p = p.split("#")[0]
            target = by_url.get(SITE_PREFIX + p)
            if target is None:
                if p not in RELATED_NON_NODE:
                    stray.append((rel, href))
                continue
            if (target, href) in seen:
                continue
            seen.add((target, href))
            if target not in out.get(n["id"], set()):
                missing.append((rel, n["id"], target, label))

    if stray:
        print(f"   ссылки не на узел и не в белом списке — {len(stray)}:")
        for r, h in stray[:LIST_CAP]:
            print(f"      {r}  →  {h}")
        if len(stray) > LIST_CAP:
            print(f"      … и ещё {len(stray) - LIST_CAP} — полный список: --verbose")
        warnings.append(f"related: ссылки не на узел: {len(stray)}")
    else:
        print("   ссылки не на узел: все в белом списке ✓")

    if not missing:
        print("   каждая ссылка в related подтверждена ребром ✓")
        return
    pages = {x[0] for x in missing}
    rows = [f"{r}  {a} → {b}  «{lab[:34]}»" for r, a, b, lab in sorted(missing)]
    show_list(rows, f"   ссылок без ребра: {len(missing)} на {len(pages)} страницах:")
    print("   Страница утверждает связь, которой нет на карте.")
    print("   Обратное (ребро без ссылки) — норма: related курируется.")
    print("   [предупреждение, не блокер]")
    warnings.append(f"related без ребра: {len(missing)}")


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


# ── 8 · итог ────────────────────────────────────────────────────────
def summary() -> int:
    head("8 · итог")
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
    return summary()


if __name__ == "__main__":
    raise SystemExit(main())
