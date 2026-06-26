#!/usr/bin/env python3
"""One-shot mechanical essay fixes from audit."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "essays"

# sub-h: old -> new (exact match inside <div class="sub-h">)
HEADING_FIXES: dict[str, dict[str, str]] = {
    "ab-testing": {"теорема Байеса объясняет почему": "теорема Байеса объясняет почему"},
    "adtech": {
        "CPM vs CPC vs CPA": "CPM vs CPC vs CPA",
        "Дзен и параллельные аукционы": "дзен и параллельные аукционы",
    },
    "auctions": {"вторая цена · Викри": "вторая цена · Викри"},
    "bayesian": {"применение в A/B тестировании": "применение в A/B тестировании"},
    "black-swan": {"два мира: Mediocristan и Extremistan": "два мира: mediocristan и extremistan"},
    "bookmaker-bayes": {"где Байес заканчивается · бизнес": "где Байес заканчивается · бизнес"},
    "causality": {"золотой стандарт — A/B": "золотой стандарт — A/B"},
    "clt": {"что ЦПТ не говорит": "что ЦПТ не говорит"},
    "expected-utility": {"парадокс Алле": "парадокс Алле"},
    "expected-value": {"Келли": "келли", "A/B и байесовский подход": "A/B и байесовский подход"},
    "gamblers-fallacy": {"Монте-Карло 1913": "монте-карло 1913"},
    "game-theory": {"турнир Аксельрода": "турнир Аксельрода"},
    "games-and-math": {
        "кости · ~1560 · Кардано": "кости · ~1560 · Кардано",
        "карты · 1654 · Паскаль и Ферма": "карты · 1654 · Паскаль и Ферма",
        "рулетка · 1718 · де Муавр": "рулетка · 1718 · де Муавр",
        "лотерея · 1738 · Даниэль Бернулли": "лотерея · 1738 · Даниэль Бернулли",
        "нарды · IX век · арабские математики": "нарды · IX век · арабские математики",
        "пасьянс · 1946 · Улам": "пасьянс · 1946 · Улам",
        "покер · 1944 · фон Нейман": "покер · 1944 · фон Нейман",
        "шахматы · 1950 · Шеннон": "шахматы · 1950 · Шеннон",
    },
    "good-decisions": {"EV и дистанция": "EV и дистанция"},
    "infinity-paradoxes": {
        "отель Гильберта": "отель Гильберта",
        "парадокс Банаха–Тарского": "парадокс Банаха–Тарского",
        "парадокс Рассела": "парадокс Рассела",
    },
    "is-forecast-right": {"шкала Бриера · одно честное число": "шкала Бриера · одно честное число"},
    "kolmogorov": {
        "три определения до Колмогорова": "три определения до Колмогорова",
        "сложность Колмогорова": "сложность Колмогорова",
    },
    "llm-eval": {"LLM-as-judge": "LLM-as-judge"},
    "poker-kelly": {"полный Келли против дробного": "полный Келли против дробного"},
    "probability-paradoxes": {
        "парадокс Монти Холла": "парадокс Монти Холла",
        "парадокс Симпсона": "парадокс Симпсона",
        "парадокс Бертрана": "парадокс Бертрана",
    },
    "two-sided-markets": {"модель Роше–Тироля": "модель Роше–Тироля"},
    "two-systems": {"когда Система 1 ошибается": "когда система 1 ошибается"},
    "unit-economics": {
        "LTV и CAC": "LTV и CAC",
        "LTV через когорты": "LTV через когорты",
        "от юнита к PnL": "от юнита к PnL",
    },
    "value-betting": {
        "сколько ставить · критерий Келли": "сколько ставить · критерий Келли",
        "откуда взялся Келли · теория информации": "откуда взялся Келли · теория информации",
        "почему полный Келли опасен": "почему полный Келли опасен",
    },
}

READ_TIME: dict[str, int] = {
    "antifragile": 11,
    "black-swan": 11,
    "decisions-distance": 14,
    "five-letters": 5,
    "flaneur": 8,
    "gambling-math": 5,
    "monte-carlo": 5,
    "optionality": 8,
    "skin-in-the-game": 8,
    "uncertainty-knight": 11,
    "via-negativa": 7,
}


def fix_headings(html: str, slug: str) -> str:
    fixes = HEADING_FIXES.get(slug, {})
    for old, new in fixes.items():
        if old == new:
            continue
        html = html.replace(f'<div class="sub-h">{old}</div>', f'<div class="sub-h">{new}</div>')
    return html


def fix_read_time(html: str, slug: str) -> str:
    mins = READ_TIME.get(slug)
    if not mins:
        return html
    label = f"~{mins} минут"
    html = re.sub(
        r'(<div class="essay-label">[^<]*?)~?\d+\s*мин(?:ут)?',
        rf"\1{label}",
        html,
        count=1,
    )
    html = re.sub(
        r'(<td class="k">читать</td>\s*<td class="v">)~?\d+\s*мин(?:ут)?',
        rf"\1{label}",
        html,
        count=1,
    )
    return html


def fix_kolmogorov(html: str) -> str:
    return html.replace("...", "…")


def fix_xg(html: str) -> str:
    old = "после прострела или в контратаке<em class=\"fn\">1</em><em class=\"fn\">3</em>"
    new = "после прострела или в контратаке<em class=\"fn\">3</em>"
    return html.replace(old, new)


def fix_fibonacci(html: str) -> str:
    old = "без глобального плана.</p>"
    new = "без глобального плана<em class=\"fn\">1</em>.</p>"
    return html.replace(old, new, 1)


def fix_two_systems(html: str) -> str:
    old = "Канеман не говорит что Система 1 плохая."
    new = "Канеман не говорит что Система 1 плохая<em class=\"fn\">3</em>."
    return html.replace(old, new, 1)


def fix_zero_history(html: str) -> str:
    # Split combined [1] into Maya [1] and BrahmaGupta [5]
    html = html.replace(
        '<span class="t">Брахмагупта · «Брахмаспхутасиддханта» · 628 н.э. — первая систематическая арифметика нуля. Майя независимо изобрели ноль около IV в. н.э., символ — стилизованная ракушка.</span>',
        '<span class="t">Майя независимо изобрели ноль около IV в. н.э., символ — стилизованная ракушка.</span>',
    )
    html = html.replace(
        'a × 0 = 0<em class="fn">1</em>.</p>',
        'a × 0 = 0<em class="fn">5</em>.</p>',
    )
    insert = '''      <div class="note">
        <span class="n">[5]</span>
        <span class="t">Брахмагупта · «Брахмаспхутасиддханта» · 628 н.э. — первая систематическая арифметика нуля.</span>
      </div>
'''
    html = html.replace(
        '      <div class="note">\n        <span class="n">[2]</span>',
        insert + '      <div class="note">\n        <span class="n">[2]</span>',
    )
    return html


def remove_duplicate_footnote_marker(html: str, marker: str, occurrence: int) -> str:
    """Remove the nth occurrence of a footnote marker (1-based)."""
    pat = re.compile(rf'<em class="fn">{marker}</em>')
    n = 0
    def repl(m):
        nonlocal n
        n += 1
        return "" if n == occurrence else m.group(0)
    return pat.sub(repl, html)


def fix_bookshelf(html: str) -> str:
    # Remove 2nd marker [2] and 2nd marker [4]
    html = remove_duplicate_footnote_marker(html, "2", 2)
    html = remove_duplicate_footnote_marker(html, "4", 2)
    return html


def fix_terminal(html: str) -> str:
    return remove_duplicate_footnote_marker(html, "2", 2)


FOOTNOTE_FIXERS = {
    "xg": fix_xg,
    "fibonacci-nature": fix_fibonacci,
    "two-systems": fix_two_systems,
    "zero-history": fix_zero_history,
    "bookshelf": fix_bookshelf,
    "terminal": fix_terminal,
}


def main():
    slugs = set(HEADING_FIXES) | set(READ_TIME) | set(FOOTNOTE_FIXERS) | {"kolmogorov"}
    for slug in sorted(slugs):
        path = ROOT / f"{slug}.html"
        if not path.exists():
            print("skip missing", slug)
            continue
        html = path.read_text(encoding="utf-8")
        html = fix_headings(html, slug)
        html = fix_read_time(html, slug)
        if slug == "kolmogorov":
            html = fix_kolmogorov(html)
        if slug in FOOTNOTE_FIXERS:
            html = FOOTNOTE_FIXERS[slug](html)
        path.write_text(html, encoding="utf-8")
        print("fixed", slug)


if __name__ == "__main__":
    main()
