#!/usr/bin/env python3
"""Keep the "N слов · M мин" part of .essay-label honest.

Usage:  python3 scripts/update_reading_time.py [--check] [--dry-run] [--all]
                                               [--tolerance 0.15] [--wpm 125]

Reads:  objects/**/*.html, essays/*.html — всё, где есть <div class="essay-label">
Writes: in-place, только числа внутри этой метки. Остальная её часть
        ("объект · математик · ") и тильда перед числом сохраняются как есть.

Что считается словом. Видимый текст внутри <main>, из которого вычтена
обвязка: breadcrumb, related, backlinks, topbar, footer, nav. Сама метка
из подсчёта НЕ исключается — и это не недосмотр: авторские числа считаны
вместе с ней. На cantor, loss-aversion, demoivre, 1729 и godel счёт с
меткой сходится до единицы (420/420, 400/400, 499/500, 479/480, 421/420),
а без неё стабильно недобирает ровно 7 слов — столько в самой метке.
Исключать её значило бы молча сдвинуть весь корпус на десяток вниз.

Считать по одним <p> нельзя — у объектов половина текста живёт в таблицах
и врезках.

Оговорка про идемпотентность: в метке вида "1 200 слов" разделитель тысяч
даёт лишнее слово, после перезаписи на "410" его не станет. Разница в одно
слово, внутри любого разумного порога; после первого прохода корпус
стабилен.

Конвенция автора, восстановленная по 166 меткам. Все объявленные числа
кратны десяти, минуты ≈ ceil(слова / 125) — правило совпадает на 112 из
166, и это лучшее, что вообще прослеживается. Точных совпадений «метка =
подсчёт» немного, но систематического сдвига нет: на неразъехавшихся
страницах медиана отношения 1.017. Авторские числа приблизительные, в
метках стоит тильда, — скрипт эту приблизительность сохраняет и правит
только то, что уехало далеко. --wpm меняется флагом.

По умолчанию трогает только те страницы, где число СЛОВ разъехалось
больше чем на --tolerance (15%); минуты пересчитываются заодно, но сами
по себе поводом для правки не служат. Страницы, где всё в порядке,
остаются нетронутыми — генератор здесь не хозяин региона, а корректор.
--all нормализует вообще всё, включая минуты.

--check ничего не пишет и возвращает 1, если есть расхождения. Для CI.

Fails loudly: сначала разбираются все файлы, и только потом пишется
хоть один. Непонятная структура — отчёт и выход с ненулевым кодом,
дерево остаётся нетронутым.
"""
from __future__ import annotations

import math
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

TARGETS = ("objects", "essays")

WPM_DEFAULT = 125
TOLERANCE_DEFAULT = 0.15
ROUND_TO = 10

LABEL_RE = re.compile(r'<div class="essay-label">([^<]*)</div>')
NUM_RE = re.compile(r"(~?\s*)([\d\s]+?)(\s*слов\s*·\s*)(\d+)(\s*мин)")

MAIN_RE = re.compile(r"<main[^>]*>(.*?)</main>", re.S)
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.S)
CHROME_OPEN = re.compile(
    r"<(section|div|nav|footer|header)[^>]*class=\"[^\"]*"
    r"(?:related|backlinks|breadcrumb|topbar|footer|nav)[^\"]*\"[^>]*>", re.I)
TAG_RE = re.compile(r"<[^>]+>")


def drop_chrome(html: str) -> str:
    """Вырезать блоки обвязки вместе с вложенностью.

    Нежадное .*?</tag> закрывалось бы на первом же </div>, и вложенный
    блок внутри related или breadcrumb оставил бы хвост в подсчёте. Здесь
    закрывающий тег ищется по глубине, а не по первому совпадению.
    """
    html = SCRIPT_RE.sub(" ", html)
    while True:
        m = CHROME_OPEN.search(html)
        if not m:
            return html
        tag = m.group(1)
        depth, pos, end = 1, m.end(), None
        for t in re.finditer(rf"<{tag}\b[^>]*>|</{tag}\s*>", html[m.end():], re.I):
            depth += 1 if not t.group(0).startswith("</") else -1
            if depth == 0:
                end = m.end() + t.end()
                break
        html = html[:m.start()] + " " + html[end if end else len(html):]


def is_redirect(text: str) -> bool:
    """Заглушка-редирект: считать в ней нечего."""
    return 'http-equiv="refresh"' in text[:1024]


def count_words(text: str) -> int | None:
    m = MAIN_RE.search(text)
    if not m:
        return None
    return len(TAG_RE.sub(" ", drop_chrome(m.group(1))).split())


def minutes(words: int, wpm: int) -> int:
    return max(1, math.ceil(words / wpm))


def rounded(words: int) -> int:
    return max(ROUND_TO, int(round(words / ROUND_TO) * ROUND_TO))


def collect() -> list[tuple[str, str]]:
    out = []
    for top in TARGETS:
        base = os.path.join(ROOT, top)
        if not os.path.isdir(base):
            continue
        for dirpath, _, names in os.walk(base):
            for fn in sorted(names):
                if not fn.endswith(".html") or fn == "index.html":
                    continue
                path = os.path.join(dirpath, fn)
                with open(path, encoding="utf-8") as f:
                    text = f.read()
                if is_redirect(text):
                    continue
                if LABEL_RE.search(text) is None:
                    continue
                out.append((os.path.relpath(path, ROOT).replace(os.sep, "/"), text))
    return out


def main() -> int:
    argv = sys.argv[1:]
    check = "--check" in argv
    dry = "--dry-run" in argv
    every = "--all" in argv
    wpm = int(argv[argv.index("--wpm") + 1]) if "--wpm" in argv else WPM_DEFAULT
    tol = float(argv[argv.index("--tolerance") + 1]) if "--tolerance" in argv else TOLERANCE_DEFAULT
    if every:
        tol = 0.0

    files = collect()
    if not files:
        print("ОШИБКА: не найдено ни одной страницы с .essay-label.")
        return 1

    # ── сначала разбираем всё, потом пишем ──
    parsed, broken, skipped = [], [], 0
    for rel, text in files:
        label = LABEL_RE.search(text).group(1)
        num = NUM_RE.search(label)
        if num is None:
            skipped += 1          # метка без чисел — законный случай
            continue
        real = count_words(text)
        if real is None:
            broken.append(f"{rel}: нет <main>, считать нечего")
            continue
        if real < 20:
            broken.append(f"{rel}: в <main> всего {real} слов — похоже на нестандартную вёрстку")
            continue
        parsed.append((rel, text, label, num, real))

    if broken:
        print(f"ОШИБКА: файлов с непредвиденной структурой — {len(broken)}")
        for line in broken[:20]:
            print(f"   {line}")
        if len(broken) > 20:
            print(f"   … и ещё {len(broken) - 20}")
        print("Ничего не записано.")
        return 1

    drifted, pending = [], []
    for rel, text, label, num, real in parsed:
        claimed = int(re.sub(r"\s", "", num.group(2)))
        claimed_min = int(num.group(4))
        want_w = rounded(real)
        want_m = minutes(want_w, wpm)
        dev = abs(claimed - real) / real
        # Минуты сами по себе файл не трогают: правило ceil(слова/125)
        # восстановлено лишь на 2/3 корпуса, и расхождение в минуту
        # вполне может быть авторским решением. Поводом переписать
        # метку служит разъехавшееся число слов — минуты тогда
        # пересчитываются заодно.
        if dev <= tol:
            continue
        drifted.append((rel, claimed, claimed_min, want_w, want_m, dev))
        new_label = label[: num.start()] + (
            f"{num.group(1)}{want_w}{num.group(3)}{want_m}{num.group(5)}"
        ) + label[num.end():]
        pending.append((rel, text.replace(
            f'<div class="essay-label">{label}</div>',
            f'<div class="essay-label">{new_label}</div>', 1)))

    print(f"страниц с меткой:  {len(parsed)}")
    print(f"без чисел:         {skipped}")
    print(f"расходится:        {len(drifted)}  (порог {tol:.0%}, {wpm} слов/мин)")

    if drifted:
        print()
        for rel, cw, cm, ww, wm, dev in sorted(drifted, key=lambda x: -x[5])[:15]:
            print(f"   {rel:<52} {cw:>5} слов/{cm:>2} мин → {ww:>5}/{wm:<2}  ({dev:.0%})")
        if len(drifted) > 15:
            print(f"   … и ещё {len(drifted) - 15}")

    if check:
        print()
        if drifted:
            print(f"--check: расхождений — {len(drifted)}. Прогоните скрипт без --check.")
            return 1
        print("--check: метки сходятся ✓")
        return 0

    if dry:
        print(f"\n--dry-run: файлов изменилось бы — {len(pending)}. Ничего не записано.")
        return 0
    if not pending:
        print("\nВсё уже актуально, записывать нечего.")
        return 0

    for rel, new in pending:
        with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
            f.write(new)
    print(f"\nзаписано файлов: {len(pending)}")
    print("Не забудьте порядок: скрипты → commit → generate_sitemap.py → commit --amend → push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
