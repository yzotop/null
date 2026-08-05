#!/usr/bin/env python3
"""Maintain the generated <meta> block in every essay of null.

Usage:  python3 scripts/update_meta.py [--dry-run]

Reads:  essays/*.html — <title> is the single source for og:title
Writes: in-place, only the region between the two markers below

Idempotent: the script owns the marked region and rewrites it whole on
every run, the same way data/build-backlinks.js owns its backlinks
section. Adding a tag means adding a line to meta_block() and running
again — no second pass over the files by hand.

URL building is imported from generate_sitemap.py, not reimplemented,
so <link rel=canonical>, og:url and the sitemap entry cannot drift apart.

og:title is the topic without the "— null/essays" suffix: og:site_name
already carries "null", and repeating it inside the title reads badly
in a preview card.

Fails loudly: every file is validated before anything is written. One
bad file and the script reports it and exits non-zero having written
nothing — no partially updated tree.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_sitemap import SITE_ORIGIN, SITE_PREFIX, to_loc  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Пока только эссе. Объекты и визуалы — отдельным решением: у них
# другая структура заголовка, og:type там был бы не "article".
TARGET_DIR = "essays"

AUTHOR = "Александр Давыдов"
TITLE_SUFFIX = " — null/essays"

MARK_OPEN = "<!-- meta: scripts/update_meta.py -->"
MARK_CLOSE = "<!-- /meta -->"
BLOCK_RE = re.compile(
    re.escape(MARK_OPEN) + r".*?" + re.escape(MARK_CLOSE) + r"\n?",
    re.S,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>\n", re.S)


def is_redirect(text: str) -> bool:
    """Заглушка-редирект: у неё уже есть свой canonical на цель."""
    return 'http-equiv="refresh"' in text[:1024]


# Пути к иконкам и карточке — абсолютные от корня origin, а не
# относительные: блок может однажды поехать на объекты, которые лежат
# на три уровня глубже эссе.
OG_IMAGE = SITE_ORIGIN + SITE_PREFIX + "assets/og.png"
OG_W, OG_H = "1200", "630"
FAVICON = SITE_PREFIX + "favicon.svg"
TOUCH_ICON = SITE_PREFIX + "favicon-180.png"


def meta_block(topic: str, url: str) -> str:
    lines = [
        MARK_OPEN,
        f'<link rel="canonical" href="{url}">',
        f'<link rel="icon" href="{FAVICON}" type="image/svg+xml">',
        f'<link rel="apple-touch-icon" href="{TOUCH_ICON}">',
        f'<meta name="author" content="{AUTHOR}">',
        '<meta property="og:type" content="article">',
        '<meta property="og:site_name" content="null">',
        '<meta property="og:locale" content="ru_RU">',
        f'<meta property="og:title" content="{topic}">',
        f'<meta property="og:url" content="{url}">',
        f'<meta property="og:image" content="{OG_IMAGE}">',
        f'<meta property="og:image:width" content="{OG_W}">',
        f'<meta property="og:image:height" content="{OG_H}">',
        '<meta name="twitter:card" content="summary_large_image">',
        MARK_CLOSE,
    ]
    return "\n".join(lines) + "\n"


def validate(rel: str, text: str) -> list[str]:
    """Всё, что должно быть верно до записи. Пустой список — файл годен."""
    errs = []
    if "<head>" not in text or "</head>" not in text:
        errs.append("нет <head>")
    n_title = text.count("<title>")
    if n_title != 1:
        errs.append(f"<title> встречается {n_title} раз, ожидался 1")
    elif not TITLE_RE.search(text):
        errs.append("<title> не заканчивается переводом строки — точка вставки неизвестна")
    else:
        title = TITLE_RE.search(text).group(1).strip()
        if not title.endswith(TITLE_SUFFIX):
            errs.append(f'заголовок не оканчивается на "{TITLE_SUFFIX}": {title!r}')
        else:
            topic = title[: -len(TITLE_SUFFIX)]
            if not topic:
                errs.append("тема пустая после отрезания суффикса")
            if '"' in topic:
                errs.append("двойная кавычка в теме — сломает атрибут content")
            if re.search(r"[<>]", topic):
                errs.append("неэкранированная угловая скобка в теме")
    n_open, n_close = text.count(MARK_OPEN), text.count(MARK_CLOSE)
    if n_open != n_close:
        errs.append(f"маркеры не парные: открывающих {n_open}, закрывающих {n_close}")
    elif n_open > 1:
        errs.append(f"блок встречается {n_open} раз, ожидался 0 или 1")
    elif n_open == 1 and not BLOCK_RE.search(text):
        errs.append("маркеры есть, но закрывающий раньше открывающего")
    return errs


def main() -> int:
    dry = "--dry-run" in sys.argv[1:]
    src = os.path.join(ROOT, TARGET_DIR)

    files = []
    for fn in sorted(os.listdir(src)):
        if not fn.endswith(".html") or fn == "index.html":
            continue
        rel = f"{TARGET_DIR}/{fn}"
        with open(os.path.join(src, fn), encoding="utf-8") as f:
            text = f.read()
        if is_redirect(text):
            continue
        files.append((rel, text))

    # ── сначала проверяем всё, только потом пишем хоть что-то ──
    failed = []
    for rel, text in files:
        for e in validate(rel, text):
            failed.append(f"{rel}: {e}")
    if failed:
        print(f"ОШИБКА: файлов с непредвиденной структурой — {len({f.split(':')[0] for f in failed})}")
        for line in failed[:20]:
            print(f"   {line}")
        if len(failed) > 20:
            print(f"   … и ещё {len(failed) - 20}")
        print("Ничего не записано.")
        return 1

    added = updated = same = 0
    pending = []
    for rel, text in files:
        title = TITLE_RE.search(text).group(1).strip()
        topic = title[: -len(TITLE_SUFFIX)]
        block = meta_block(topic, to_loc(rel))

        if BLOCK_RE.search(text):
            new = BLOCK_RE.sub(lambda _: block, text, count=1)
            if new == text:
                same += 1
                continue
            updated += 1
        else:
            new = TITLE_RE.sub(lambda m: m.group(0) + block, text, count=1)
            added += 1
        pending.append((rel, new))

    print(f"эссе обработано:   {len(files)}")
    print(f"блок добавлен:     {added}")
    print(f"блок обновлён:     {updated}")
    print(f"без изменений:     {same}")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
