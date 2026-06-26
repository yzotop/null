#!/usr/bin/env python3
"""Deterministic math verification across null essays. Read-only."""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESSAYS = ROOT / "essays"
AUDIT = Path(__file__).resolve().parent
OUT_MD = AUDIT / "math-check.md"
OUT_FACTUAL = AUDIT / "factual-worklist.md"
OUT_JSON = AUDIT / "_math_check_raw.json"

REL_TOL = 0.02  # 2% relative tolerance for floats
EXP_TOL = 1  # log10 exponent tolerance


@dataclass
class Mismatch:
    slug: str
    quote: str
    stated: str
    computed: str
    note: str


@dataclass
class FactualItem:
    slug: str
    quote: str
    check: str


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip += 1
        if tag == "sup":
            self.parts.append("^(")
        if tag == "sub":
            self.parts.append("_(")
        if tag == "em" and any(k == "class" and "fn" in v for k, v in attrs):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self._skip:
            self._skip -= 1
        if tag in ("sup", "sub"):
            self.parts.append(")")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def extract_article_text(html: str) -> str:
    m = re.search(r"<article>(.*)</article>", html, re.S)
    chunk = m.group(1) if m else html
    ext = TextExtractor()
    ext.feed(chunk)
    return ext.text()


SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def normalize_math_text(text: str) -> str:
    t = text.translate(SUPERSCRIPT)
    t = re.sub(r"\^?\((\d+)\)", r"^\1", t)
    t = re.sub(r"(\d)\^(\d)", r"\1^\2", t)  # already ok
    t = re.sub(r"(\d)/(\d)\^(\d+)", r"(\1/\2)^\3", t)
    t = re.sub(r"(\d)/(\d)\)\^(\d+)", r"(\1/\2)^\3", t)
    return t


def close_enough(a: float, b: float, rel: float = REL_TOL) -> bool:
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return abs(a - b) < 1e-9
    return abs(a - b) / max(abs(a), abs(b)) <= rel


def exp10(x: float) -> int:
    return int(math.floor(math.log10(abs(x)))) if x else 0


def sentence_window(text: str, pos: int, width: int = 140) -> str:
    start = max(0, pos - width // 2)
    end = min(len(text), pos + width // 2)
    return text[start:end].strip()


def add_mismatch(
    out: list[Mismatch], slug: str, text: str, pos: int, stated: str, computed: str, note: str
) -> None:
    out.append(
        Mismatch(
            slug=slug,
            quote=sentence_window(text, pos),
            stated=stated,
            computed=computed,
            note=note,
        )
    )


def parse_sci_notation(text: str) -> list[tuple[float, int, int]]:
    """Return list of (coeff, exponent, position) for coeff·10^exp and bare 10^exp."""
    t = normalize_math_text(text)
    out: list[tuple[float, int, int]] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[·*]\s*10\^(\d+)", t):
        out.append((float(m.group(1)), int(m.group(2)), m.start()))
    for m in re.finditer(r"10\^(\d+)", t):
        out.append((1.0, int(m.group(1)), m.start()))
    return out


def check_factorial_consistency(slug: str, text: str, out: list[Mismatch]) -> None:
    t = normalize_math_text(text)
    for m in re.finditer(r"(?<![0-9])(\d{1,3})!(?!\d)", t):
        n = int(m.group(1))
        if n > 170:
            continue
        fact = math.factorial(n)
        true_exp = exp10(fact)
        window_start = m.start()
        window_end = min(len(t), m.end() + 80)
        window = t[window_start:window_end]
        order_window = t[m.end() : min(len(t), m.end() + 60)]
        exps = [(c, e) for c, e, _ in parse_sci_notation(order_window)]
        if not exps:
            exps = [(c, e) for c, e, _ in parse_sci_notation(window) if e != 120]  # skip Shannon scale
        any_close = any(close_enough(fact, c * 10**e, rel=0.12) for c, e in exps)
        for coeff, exp in exps:
            stated_val = coeff * 10**exp
            if any_close and close_enough(fact, stated_val, rel=0.25):
                continue
            if abs(exp - true_exp) >= 1 or not close_enough(fact, stated_val, rel=0.12):
                add_mismatch(
                    out, slug, text, m.start(),
                    f"{coeff:g}·10^{exp}" if coeff != 1 else f"10^{exp}",
                    f"{fact:.3e} (~10^{true_exp})",
                    f"{n}! порядок величины",
                )
        # digit count
        dm = re.search(
            r"(\d+|семьдесят|шестьдесят|пятьдесят)\s+знак\w*",
            t[m.start() : min(len(t), m.start() + 320)],
            re.I,
        )
        if dm:
            word = dm.group(1).lower()
            claimed = {"семьдесят": 70, "шестьдесят": 60, "пятьдесят": 50}.get(word, int(word) if word.isdigit() else 0)
            actual = len(str(fact))
            if claimed and abs(claimed - actual) > 1:
                add_mismatch(out, slug, text, m.start(), f"{claimed} знаков", f"{actual} знаков", f"{n}!")


def check_roulette_probability(slug: str, text: str, out: list[Mismatch]) -> None:
    t = normalize_math_text(text)
    for m in re.finditer(r"\((\d+)/(\d+)\)\^(\d+)", t.replace(" ", "")):
        a, b, n = int(m.group(1)), int(m.group(2)), int(m.group(3))
        p = (a / b) ** n
        window = t[m.end() : m.end() + 120]
        inv = re.search(r"1\s*/\s*(\d+)\s+миллион", window, re.I)
        inv2 = re.search(r"1\s+из\s+(\d+)\s+миллион", window, re.I)
        if inv:
            stated_n = int(inv.group(1)) * 1_000_000
            computed_n = round(1 / p)
            if not close_enough(stated_n, computed_n, rel=0.08):
                add_mismatch(
                    out, slug, text, m.start(),
                    f"1/{inv.group(1)} млн",
                    f"1/{computed_n/1e6:.0f} млн",
                    f"({a}/{b})^{n}",
                )
        if inv2:
            stated_n = int(inv2.group(1)) * 1_000_000
            computed_n = round(1 / p)
            if not close_enough(stated_n, computed_n, rel=0.08):
                add_mismatch(
                    out, slug, text, m.start(),
                    f"1 из {inv2.group(1)} млн",
                    f"1 из {computed_n/1e6:.0f} млн",
                    f"({a}/{b})^{n}",
                )


def check_ev_coin_flip(slug: str, text: str, out: list[Mismatch]) -> None:
    m = re.search(
        r"50/50\s+выиграть\s+(\d+)\s+vs\s+потерять\s+(\d+).*?EV\s*=\s*\+?(\d+)",
        text,
        re.I | re.S,
    )
    if m:
        win, lose, ev = float(m.group(1)), float(m.group(2)), float(m.group(3))
        computed = 0.5 * win - 0.5 * lose
        if not close_enough(computed, ev, rel=0.01):
            add_mismatch(
                out, slug, text, m.start(),
                f"EV={ev}",
                f"EV={computed}",
                "50/50 матожидание",
            )


def check_odds_ratio_multiply(slug: str, text: str, out: list[Mismatch]) -> None:
    m = re.search(
        r"(\d+):(\d+)\s*=\s*(\d+):(\d+)\s*×\s*([\d.]+)",
        text.replace(" ", ""),
    )
    if m:
        a, b, c, d, k = map(float, m.groups())
        left = a / b
        right = (c / d) * k
        if not close_enough(left, right, rel=0.03):
            add_mismatch(
                out, slug, text, m.start(),
                f"{int(a)}:{int(b)}={int(c)}:{int(d)}×{k}",
                f"{int(a)}:{int(b)} vs {c/d*k:.3f}",
                "соотношение шансов",
            )


def check_percent_of(slug: str, text: str, out: list[Mismatch]) -> None:
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*%\s+.{0,40}?на\s+миллион",
        text,
        re.I,
    )
    if m:
        pct = float(m.group(1)) / 100
        # find "десять тысяч" or number
        window = text[m.end() : m.end() + 80]
        nm = re.search(r"(\d[\d\s]*)\s+ложн", window)
        if nm:
            stated = int(nm.group(1).replace(" ", ""))
            computed = int(pct * 1_000_000)
            if stated != computed:
                add_mismatch(
                    out, slug, text, m.start(),
                    f"{stated} ложных",
                    f"{computed} (1%×1M)",
                    "ложные срабатывания",
                )


def check_pot_odds_formula(slug: str, text: str, out: list[Mismatch]) -> None:
    m = re.search(
        r"(\d+)\s*/\s*\(\s*(\d+)\s*\+\s*(\d+)\s*\+\s*(\d+)\s*\)\s*=\s*(\d+)\s*%",
        text.replace("$", "").replace(" ", ""),
    )
    if m:
        num, a, b, c, pct = map(int, m.groups())
        val = num / (a + b + c) * 100
        correct = num / (a + b + num) * 100  # standard pot odds
        if abs(pct - val) < 0.5 and abs(pct - correct) > 2:
            add_mismatch(
                out, slug, text, m.start(),
                f"{num}/({a}+{b}+{c})={pct}%",
                f"колл/(банк+колл)={correct:.0f}%",
                "pot odds формула",
            )


def check_power_products(slug: str, text: str, out: list[Mismatch]) -> None:
    t = normalize_math_text(text)
    for m in re.finditer(
        r"10\^(\d+)\s*[·*]\s*(\d+(?:\.\d+)?)\s*[·*]\s*10\^(\d+)\s*≈\s*(\d+(?:\.\d+)?)\s*[·*]\s*10\^(\d+)",
        t,
    ):
        e1, a, e2, rc, re_ = int(m.group(1)), float(m.group(2)), int(m.group(3)), float(m.group(4)), int(m.group(5))
        left = (10**e1) * a * (10**e2)
        right = rc * 10**re_
        if not close_enough(left, right, rel=0.05):
            add_mismatch(
                out, slug, text, m.start(),
                f"{10**e1}·{a}·10^{e2} ≈ {rc}·10^{re_}",
                f"лево={left:.2e}, право={right:.2e}",
                "произведение степеней",
            )


def check_fraction_powers(slug: str, text: str, out: list[Mismatch]) -> None:
    for m in re.finditer(r"\((\d+)\s*/\s*(\d+)\)\^(\d+)", text.replace(" ", "")):
        a, b, n = int(m.group(1)), int(m.group(2)), int(m.group(3))
        p = (a / b) ** n
        # look for "1 из N" or "1/N" nearby
        window = text[m.end() : m.end() + 200]
        inv = re.search(r"1\s+из\s+([\d\s]+(?:миллион|млн|тысяч)?)", window, re.I)
        if inv:
            raw = inv.group(1).replace(" ", "")
            mult = 1
            if "миллион" in inv.group(1) or "млн" in inv.group(1):
                mult = 1_000_000
            num = re.sub(r"\D", "", raw)
            if num:
                stated_n = int(num) * mult
                computed_n = round(1 / p)
                if not close_enough(stated_n, computed_n, rel=0.15):
                    add_mismatch(
                        out, slug, text, m.start(),
                        f"1 из {stated_n:,}".replace(",", " "),
                        f"1 из {computed_n:,}".replace(",", " "),
                        f"({a}/{b})^{n}",
                    )


def check_one_in_n(slug: str, text: str, out: list[Mismatch]) -> None:
    for m in re.finditer(r"1\s+из\s+([\d\s]+)(миллион|млн|тысяч|млрд|миллиард)?", text, re.I):
        raw = m.group(1).replace(" ", "")
        if not raw.isdigit():
            continue
        n = int(raw)
        mult_word = (m.group(2) or "").lower()
        if "миллион" in mult_word or "млн" in mult_word:
            n *= 1_000_000
        elif "млрд" in mult_word or "миллиард" in mult_word:
            n *= 1_000_000_000
        elif "тысяч" in mult_word:
            n *= 1000
        # find probability fraction in prior 100 chars
        before = text[max(0, m.start() - 120) : m.start()]
        fp = re.search(r"\((\d+)\s*/\s*(\d+)\)\^(\d+)", before.replace(" ", ""))
        if fp:
            p = (int(fp.group(1)) / int(fp.group(2))) ** int(fp.group(3))
            computed_n = round(1 / p)
            if not close_enough(n, computed_n, rel=0.12):
                add_mismatch(
                    out, slug, text, m.start(),
                    f"1 из {n:,}".replace(",", " "),
                    f"1 из {computed_n:,}".replace(",", " "),
                    "вероятность vs «1 из N»",
                )


def check_bayes_disease(slug: str, text: str, out: list[Mismatch]) -> None:
    if "P(болен | +)" not in text and "P(болен|+)" not in text.replace(" ", ""):
        return
    sens = spec = prev = None
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", text):
        val = float(m.group(1)) / 100
        ctx = text[max(0, m.start() - 60) : m.start() + 40].lower()
        if "популяц" in ctx or "встречается" in ctx:
            prev = val
        elif "чувствитель" in ctx or "находит" in ctx:
            sens = val
        elif "специфич" in ctx or "отрицает" in ctx:
            spec = val
    if sens and spec and prev:
        p_pos = sens * prev + (1 - spec) * (1 - prev)
        p_dis = sens * prev / p_pos
        # look for 50% or 0.5 claim
        if re.search(r"\b50\s*%|\b0[,.]5\b", text):
            if not close_enough(p_dis, 0.5, rel=0.02):
                add_mismatch(
                    out, slug, text, 0,
                    "50%",
                    f"{p_dis*100:.1f}%",
                    "болезнь 1% / тест 99%/99%",
                )


def check_elo_winrate(slug: str, text: str, out: list[Mismatch]) -> None:
    for m in re.finditer(r"(\d+)\s*(?:очк|пункт).{0,30}?(\d+)\s*%", text, re.I):
        diff, pct = int(m.group(1)), int(m.group(2))
        if diff not in (100, 200, 400):
            continue
        expected = 1 / (1 + 10 ** (-diff / 400)) * 100
        if not close_enough(pct, expected, rel=0.03):
            add_mismatch(
                out, slug, text, m.start(),
                f"{diff} → {pct}%",
                f"{diff} → {expected:.1f}%",
                "формула Эло",
            )


def check_prospect_lambda(slug: str, text: str, out: list[Mismatch]) -> None:
    # +120 / -100 with 50/50 → certainty equivalent
    if "+120" in text and "−100" in text or "+120" in text and "-100" in text:
        pass  # qualitative — skip unless explicit CE stated


def check_pot_odds(slug: str, text: str, out: list[Mismatch]) -> None:
    # pot 100 call 25 → need 20% equity stated as 25%
    for m in re.finditer(
        r"банк.{0,20}?(\d+).{0,40}?колл.{0,20}?(\d+).{0,80}?(\d+)\s*%",
        text,
        re.I | re.S,
    ):
        pot, call, pct = float(m.group(1)), float(m.group(2)), float(m.group(3))
        need = call / (pot + call) * 100
        if not close_enough(pct, need, rel=0.05):
            add_mismatch(
                out, slug, text, m.start(),
                f"{pct}%",
                f"{need:.1f}% (колл/(банк+колл))",
                "pot odds",
            )


def check_log2_bits(slug: str, text: str, out: list[Mismatch]) -> None:
    for m in re.finditer(r"−?log[₂2]\s*\(\s*0?\.(\d+)\s*\)\s*≈\s*(\d+(?:\.\d+)?)", text):
        p = float("0." + m.group(1))
        stated = float(m.group(2))
        computed = -math.log2(p)
        if not close_enough(stated, computed, rel=0.05):
            add_mismatch(
                out, slug, text, m.start(),
                f"≈{stated}",
                f"≈{computed:.2f}",
                f"−log₂({p})",
            )


def check_penalty_3of4(slug: str, text: str, out: list[Mismatch]) -> None:
    if "3 из 4" in text or "три из четырёх" in text.lower():
        for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", text):
            ctx = text[max(0, m.start() - 50) : m.end() + 50]
            if "пенальт" in ctx.lower():
                val = float(m.group(1))
                if abs(val - 75) > 2 and abs(val - 80) < 2:
                    add_mismatch(out, slug, text, m.start(), f"{val}%", "75% (3/4)", "3 из 4")


def check_ratio_division(slug: str, text: str, out: list[Mismatch]) -> None:
    # explicit a/b = c when c stated
    for m in re.finditer(
        r"0?\.(\d+)\s*×\s*0?\.(\d+)\s*/\s*0?\.(\d+)\s*=\s*0?\.(\d+)",
        text.replace(",", "."),
    ):
        a, b, c, r = [float("0." + g) for g in m.groups()]
        computed = a * b / c
        if not close_enough(computed, r, rel=0.02):
            add_mismatch(
                out, slug, text, m.start(),
                f"={r}",
                f"={computed:.4f}",
                "арифметика",
            )


def check_power_of_two(slug: str, text: str, out: list[Mismatch]) -> None:
    for m in re.finditer(r"2\^(\d+)", text.replace(" ", "")):
        exp = int(m.group(1))
        if exp > 5000:
            continue
        val = 2**exp
        window = text[m.start() : m.start() + 100]
        om = re.search(r"10\^?\(?(\d+)\)?", window)
        if om:
            stated_exp = int(om.group(1))
            actual_exp = exp10(val)
            if abs(stated_exp - actual_exp) > EXP_TOL:
                add_mismatch(
                    out, slug, text, m.start(),
                    f"2^{exp} ~ 10^{stated_exp}",
                    f"2^{exp} ~ 10^{actual_exp}",
                    "порядок степени двойки",
                )


def check_deck_ratio(slug: str, text: str, out: list[Mismatch]) -> None:
    if slug != "deck-of-cards":
        return
    # 8e67 / 4e28 ~ 1e39
    f52 = math.factorial(52)
    t = normalize_math_text(text)
    if "10^39" in t.replace(" ", ""):
        shuffles = 1e11 * 4 * 1e17
        ratio_exp = exp10(f52 / shuffles)
        if abs(ratio_exp - 39) > 2:
            add_mismatch(out, slug, text, 0, "10^39", f"10^{ratio_exp}", "52!/тасования")


def extract_factual(slug: str, text: str) -> list[FactualItem]:
    items: list[FactualItem] = []
    patterns = [
        (r".{0,80}\b(впервые|в первые|первый раз|первым)\b.{0,80}", "приоритет «впервые/первый»"),
        (r".{0,60}\b(19|20)\d{2}\s+год", "дата + контекст"),
        (r".{0,80}\b(доказал|доказали|опубликовал|изобрёл|изобрел|основал|получил Нобел)\b.{0,80}", "атрибуция/событие"),
        (r".{0,80}\b(единственн\w+|награждён|награжден)\b.{0,60}", "уникальность/награда"),
    ]
    seen: set[str] = set()
    for pat, kind in patterns:
        for m in re.finditer(pat, text, re.I):
            q = m.group(0).strip()
            if len(q) < 20 or q in seen:
                continue
            seen.add(q)
            items.append(FactualItem(slug=slug, quote=q[:200], check=kind))
    return items[:25]


def run_checks(slug: str, text: str) -> tuple[list[Mismatch], list[FactualItem]]:
    mismatches: list[Mismatch] = []
    check_factorial_consistency(slug, text, mismatches)
    check_roulette_probability(slug, text, mismatches)
    check_ev_coin_flip(slug, text, mismatches)
    check_odds_ratio_multiply(slug, text, mismatches)
    check_percent_of(slug, text, mismatches)
    check_pot_odds_formula(slug, text, mismatches)
    check_power_products(slug, text, mismatches)
    check_bayes_disease(slug, text, mismatches)
    check_elo_winrate(slug, text, mismatches)
    check_log2_bits(slug, text, mismatches)
    check_ratio_division(slug, text, mismatches)
    check_power_of_two(slug, text, mismatches)
    check_deck_ratio(slug, text, mismatches)
    factual = extract_factual(slug, text)
    return mismatches, factual


def dedupe_mismatches(items: list[Mismatch]) -> list[Mismatch]:
    seen: set[tuple] = set()
    out: list[Mismatch] = []
    for it in items:
        key = (it.slug, it.stated, it.computed, it.note)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def render_math_md(items: list[Mismatch]) -> str:
    lines = [
        "# Math-check — детерминированная сверка",
        "",
        "Пересчёт Python по самодостаточным утверждениям в `essay-body` (+ inline в article).",
        "Внешние факты — в `factual-worklist.md`.",
        "",
    ]
    if not items:
        lines.append("_Расхождений не найдено._")
        return "\n".join(lines) + "\n"

    by_slug: dict[str, list[Mismatch]] = {}
    for it in items:
        by_slug.setdefault(it.slug, []).append(it)

    for slug in sorted(by_slug):
        lines.append(f"## {slug}")
        for it in by_slug[slug]:
            lines.append(f"- «{it.quote}»")
            lines.append(f"  - в тексте: {it.stated}")
            lines.append(f"  - посчитано: {it.computed}")
            lines.append(f"  - расхождение: {it.note}")
        lines.append("")
    return "\n".join(lines)


def render_factual_md(items: list[FactualItem]) -> str:
    lines = [
        "# Factual worklist — для ручной/веб-проверки",
        "",
        "Не судили автоматически: даты, атрибуции, «впервые», приоритеты.",
        "",
    ]
    by_slug: dict[str, list[FactualItem]] = {}
    for it in items:
        by_slug.setdefault(it.slug, []).append(it)
    for slug in sorted(by_slug):
        lines.append(f"## {slug}")
        for it in by_slug[slug]:
            lines.append(f"- «{it.quote}» — *{it.check}*")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    all_mismatch: list[Mismatch] = []
    all_factual: list[FactualItem] = []

    slugs = sorted(p.stem for p in ESSAYS.glob("*.html") if p.name != "index.html")
    for slug in slugs:
        path = ESSAYS / f"{slug}.html"
        html = path.read_text(encoding="utf-8")
        text = extract_article_text(html)
        if len(text) < 80:
            continue
        mm, fc = run_checks(slug, text)
        all_mismatch.extend(mm)
        all_factual.extend(fc)

    all_mismatch = dedupe_mismatches(all_mismatch)

    OUT_JSON.write_text(
        json.dumps(
            {
                "mismatches": [asdict(m) for m in all_mismatch],
                "factual_counts": {slug: sum(1 for f in all_factual if f.slug == slug) for slug in slugs},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    OUT_MD.write_text(render_math_md(all_mismatch), encoding="utf-8")
    OUT_FACTUAL.write_text(render_factual_md(all_factual), encoding="utf-8")
    print(f"math mismatches: {len(all_mismatch)} across {len({m.slug for m in all_mismatch})} essays")
    print(f"factual items: {len(all_factual)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
