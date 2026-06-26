#!/usr/bin/env python3
"""Assemble audit/revision-list.md from trusted signals only."""
from __future__ import annotations

import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESSAYS = ROOT / "essays"
AUDIT = Path(__file__).resolve().parent
ESSAY_METRICS = AUDIT / "essays-metrics.csv"
PROSE_METRICS = AUDIT / "prose-metrics.csv"
MATH_RAW = AUDIT / "_math_check_raw.json"
OUT = AUDIT / "revision-list.md"

WEIGHTS = {
    "math": 5,
    "readtime": 3,
    "footnotes": 3,
    "broken_links": 3,
    "vy_ty": 3,
    "staccato": 2,
    "section": 2,
    "en_bare": 1,
    "length": 1,
}

POKER_SLUGS = {p.stem for p in ESSAYS.glob("poker-*.html")}

EN_MERGE = [
    ("Monte", "Carlo"),
    ("Prisoner's", "Dilemma"),
    ("via", "negativa"),
    ("fat", "tails"),
    ("rule", "of", "thumb"),
    ("cold", "start"),
    ("self", "play"),
    ("tit", "for", "tat"),
    ("zero", "determinant"),
]

EN_KEEP = {
    "MCMC", "GTO", "EV", "MDF", "RTB", "VCG", "DSP", "SSP", "eCPM", "CPM", "CPC", "CPA",
    "CTR", "CVR", "ROI", "LTV", "CAC", "AB", "LLM", "LLMs", "GPT", "xG", "Elo", "iid",
    "lim", "mod", "PDF", "CDF", "PMF", "RNG", "CPU", "GPU", "API", "URL", "Nash",
    "Kelly", "Bayes", "Shannon", "AlphaGo", "PageRank", "Kalshi", "Polymarket",
    "bet", "pot", "raise", "odds", "call", "fold", "check", "bluff", "stack",
}

EN_BARE_SIGNAL = {
    "revenue", "retention", "inventory", "tension", "feedback", "default", "pipeline",
    "framework", "stakeholder", "benchmark", "baseline", "runtime", "workflow", "leverage",
    "hedge", "upside", "downside", "resulting", "game", "value", "random", "line",
    "effect", "seed", "precision", "optimization", "threshold", "load", "conversion",
    "awareness", "reach", "frequency", "guaranteed", "programmatic", "marketplace",
}

EN_DROP = {
    "the", "and", "for", "with", "from", "that", "this", "not", "but", "are", "was",
    "wissen", "werden", "ssen", "wir", "Carlo", "Dilemma", "negativa", "tails", "thumb",
    "Pavlov", "Nowak", "Nature", "University", "American", "Deep", "Blue", "Chain",
}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._math_depth = 0

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "")
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip += 1
        if any(x in cls for x in ("formula", "gl-formula", "katex", "math", "gl-formula")):
            self._math_depth += 1
        if tag in ("code", "pre"):
            self._math_depth += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self._skip:
            self._skip -= 1
        if tag in ("code", "pre"):
            self._math_depth = max(0, self._math_depth - 1)

    def handle_data(self, data):
        if not self._skip and self._math_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.parts)).strip()


def extract_prose_body(html: str) -> str:
    m = re.search(
        r'<div class="essay-body">(.*?)</div>\s*</div>\s*<(?:blockquote|aside|hr|section)',
        html,
        re.S,
    )
    if not m:
        m = re.search(r'<div class="essay-body">(.*?)</div>', html, re.S)
    chunk = m.group(1) if m else ""
    ext = TextExtractor()
    ext.feed(chunk)
    return ext.text()


def word_count(s: str) -> int:
    return len(re.findall(r"[а-яёa-z]+", s, re.I))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+(?=[А-ЯA-Z«\"(])", text)
    return [p.strip() for p in parts if p.strip()]


def staccato_prose(slug: str, html: str) -> tuple[int, float]:
    body = extract_prose_body(html)
    if len(body) < 80:
        return 0, 0.0
    sents = split_sentences(body)
    lens = [word_count(s) for s in sents]
    if not lens:
        return 0, 0.0
    short_pct = 100 * sum(1 for l in lens if l < 5) / len(lens)
    max_run = cur = 0
    for l in lens:
        if l < 5:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 0
    return max_run, short_pct


def prose_staccato_flag(max_run: int, short_pct: float) -> bool:
    return max_run >= 5 or (max_run >= 4 and short_pct >= 40)


def count_vy_ty(html: str) -> int:
    body = extract_prose_body(html)
    if len(body) < 50:
        return 0
    if not re.search(r"(?<![а-яё])ты(?![а-яё])", body, re.I):
        return 0
    pat = re.compile(
        r"(?<![а-яё])(вы|вам|вас|ваш|ваша|ваше|ваши|возьмите|посмотрите|откройте|"
        r"представьте|запомните|сделайте|нажмите)(?![а-яё])",
        re.I,
    )
    return len(pat.findall(body))


def merge_en_tokens(tokens: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(tokens):
        merged = None
        for seq in EN_MERGE:
            if tokens[i : i + len(seq)] == list(seq):
                merged = " ".join(seq)
                i += len(seq)
                break
        if merged:
            out.append(merged)
        else:
            out.append(tokens[i])
            i += 1
    return out


def bare_english_count(slug: str, html: str) -> int:
    body = extract_prose_body(html)
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]{1,}", body)
    tokens = merge_en_tokens(tokens)
    n = 0
    for t in tokens:
        low = t.lower()
        if low in EN_DROP or t in EN_KEEP or low in {k.lower() for k in EN_KEEP}:
            continue
        if t in EN_BARE_SIGNAL or low in EN_BARE_SIGNAL:
            if slug in POKER_SLUGS and low in {"bet", "pot", "odds", "line", "game", "value", "random"}:
                continue
            n += 1
    return n


def section_pct_over_50(length_flags: str) -> float | None:
    for part in length_flags.split(";"):
        if part.startswith("section>") and ":" in part:
            m = re.search(r"section>([\d.]+)%", part)
            if m:
                return float(m.group(1))
    return None


@dataclass
class EssaySignals:
    slug: str
    score: int = 0
    profile: list[str] = field(default_factory=list)
    tier: int = 2
    math: bool = False
    factual: bool = False


def load_math_slugs() -> set[str]:
    if not MATH_RAW.exists():
        return set()
    data = json.loads(MATH_RAW.read_text(encoding="utf-8"))
    return {m["slug"] for m in data.get("mismatches", [])}


def load_factual_slugs() -> set[str]:
    p = AUDIT / "factual-worklist.md"
    if not p.exists():
        return set()
    return set(re.findall(r"^## (\S+)", p.read_text(encoding="utf-8"), re.M))


def build_signals() -> list[EssaySignals]:
    essay_rows = {r["slug"]: r for r in csv.DictReader(ESSAY_METRICS.open(encoding="utf-8"))}
    prose_rows = {r["slug"]: r for r in csv.DictReader(PROSE_METRICS.open(encoding="utf-8"))}
    math_slugs = load_math_slugs()
    factual_slugs = load_factual_slugs()

    results: list[EssaySignals] = []
    seen: set[str] = set()

    for slug in sorted(essay_rows):
        er = essay_rows[slug]
        pr = prose_rows.get(slug, {})
        path = ESSAYS / f"{slug}.html"
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        sig = EssaySignals(slug=slug)

        if slug in math_slugs:
            sig.math = True
            sig.score += WEIGHTS["math"]
            sig.profile.append("math×1")

        if slug in factual_slugs:
            sig.factual = True

        if er.get("flag_readtime") == "yes":
            sig.score += WEIGHTS["readtime"]
            sig.profile.append(
                f"readtime {er.get('read_min_declared')}≠{er.get('read_min_calc')}"
            )

        if er.get("flag_footnotes") == "yes":
            sig.score += WEIGHTS["footnotes"]
            sig.profile.append("footnotes≠markers")

        bl = int(er.get("broken_links_count") or 0)
        if bl > 0:
            sig.score += WEIGHTS["broken_links"]
            sig.profile.append(f"broken_links={bl}")

        vy = count_vy_ty(html)
        if vy > 0:
            sig.score += WEIGHTS["vy_ty"]
            sig.profile.append(f"вы→ты×{vy}")

        st_max, st_pct = staccato_prose(slug, html)
        if prose_staccato_flag(st_max, st_pct):
            sig.score += WEIGHTS["staccato"]
            sig.profile.append(f"staccato {st_max}/{st_pct:.0f}%")

        sec = section_pct_over_50(pr.get("length_flags", ""))
        if sec and sec > 50:
            sig.score += WEIGHTS["section"]
            sig.profile.append(f"section>{sec:.0f}%")

        en = bare_english_count(slug, html)
        if en > 0:
            sig.score += WEIGHTS["en_bare"]
            sig.profile.append(f"EN×{en}")

        words = int(pr.get("words") or er.get("words") or 0)
        if words and (words < 600 or words > 2500):
            sig.score += WEIGHTS["length"]
            tag = "thin" if words < 600 else "bloated"
            sig.profile.append(f"{tag} {words}w")

        if not sig.profile and not sig.factual:
            continue

        if sig.math or sig.factual:
            sig.tier = 0
            if sig.factual and not sig.profile:
                sig.profile.append("factual-worklist")
        elif sig.score >= 4:
            sig.tier = 1
        else:
            sig.tier = 2

        results.append(sig)
        seen.add(slug)

    for slug in sorted(factual_slugs - seen):
        if slug not in essay_rows:
            continue
        results.append(
            EssaySignals(slug=slug, tier=0, factual=True, profile=["factual-worklist"])
        )

    return results


def render(signals: list[EssaySignals], all_slugs: set[str]) -> str:
    flagged = {s.slug for s in signals}
    clean = sorted(all_slugs - flagged)

    lines = [
        "# Revision list — очередь доработки эссе",
        "",
        "Порядок = **триаж-балл** по доверенным сигналам (math-check, readtime/footnotes,",
        "вы→ты, прозовая рубка, диспропорция секций, голые EN, выбросы длины).",
        "Исключены: literacy_score, canc_count, плотность prose-flags, hunspell.",
        "Вердикт по материалу/литературности — заполняется чтением.",
        "",
        "## Тир 0 — критический",
        "",
        "Мат-расхождение (math-check) или эссе в factual-worklist.",
        "",
    ]

    t0 = sorted(
        [s for s in signals if s.tier == 0],
        key=lambda x: (
            0 if x.math else 1,
            0 if x.profile != ["factual-worklist"] else 2,
            -x.score,
            x.slug,
        ),
    )
    for s in t0:
        prof = "; ".join(s.profile) if s.profile else ("factual-worklist" if s.factual else "")
        lines.append(
            f"- `{s.slug}` · **{s.score}** · {prof} · "
            f"**вердикт (чтение): _____** · **тип правки: _____** · **статус: _____**"
        )
    if not t0:
        lines.append("_нет_")

    lines.extend(["", "## Тир 1 — мультисигнал (балл ≥ 4)", ""])
    t1 = sorted([s for s in signals if s.tier == 1], key=lambda x: (-x.score, x.slug))
    for s in t1:
        lines.append(
            f"- `{s.slug}` · **{s.score}** · {'; '.join(s.profile)} · "
            f"**вердикт (чтение): _____** · **тип правки: _____** · **статус: _____**"
        )
    if not t1:
        lines.append("_нет_")

    lines.extend(["", "## Тир 2 — одиночный сигнал", ""])
    t2 = sorted([s for s in signals if s.tier == 2], key=lambda x: (-x.score, x.slug))
    for s in t2:
        lines.append(
            f"- `{s.slug}` · **{s.score}** · {'; '.join(s.profile)} · "
            f"**вердикт (чтение): _____** · **тип правки: _____** · **статус: _____**"
        )
    if not t2:
        lines.append("_нет_")

    lines.extend([
        "",
        "## Чистые",
        "",
        "Без доверенных сигналов (кроме попадания только в factual-worklist без math — см. тир 0).",
        "",
        ", ".join(f"`{s}`" for s in clean) or "_нет_",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    essay_rows = list(csv.DictReader(ESSAY_METRICS.open(encoding="utf-8")))
    all_slugs = {r["slug"] for r in essay_rows}
    signals = build_signals()
    OUT.write_text(render(signals, all_slugs), encoding="utf-8")
    print(f"revision-list: {len(signals)} flagged, {len(all_slugs)-len({s.slug for s in signals})} clean")
    print(f"tier0={sum(1 for s in signals if s.tier==0)} tier1={sum(1 for s in signals if s.tier==1)} tier2={sum(1 for s in signals if s.tier==2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
