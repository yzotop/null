#!/usr/bin/env python3
"""Stage 1 — deterministic signals on prose_body only."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

from problem_html import EssaySlice, normalize_prose, parse_essay, sentence_at, expand_span

AUDIT = Path(__file__).resolve().parent
ESSAYS = AUDIT.parent / "essays"

ANCHORS = frozenset({
    "antifragile",
    "decisions-distance",
    "oshibki-po-pravilam",
    "bayes-four-faces",
    "forking-paths",
})

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
    "wissen", "werden", "Carlo", "Dilemma", "negativa", "tails", "thumb",
    "Pavlov", "Nowak", "Nature", "University", "American", "Deep", "Blue", "Chain",
}

POKER_SLUGS = {p.stem for p in ESSAYS.glob("poker-*.html")}

CANC_RE = re.compile(
    r"\b(является|являются|данный|данная|данное|данные|осуществляется|осуществляют|"
    r"в рамках|носит характер|является основой|в целях|посредством|ввиду того что)\b",
    re.I,
)
CRUTCH_RE = re.compile(
    r"(на практике это|в реальности это|(?<![а-яё])именно поэтому(?![а-яё])|"
    r"(?<![а-яё])то есть(?![а-яё])|как известно|"
    r"стоит отметить|следует отметить|необходимо отметить|важно понимать что|"
    r"в конечном счёте|в конечном счете|(?<![а-яё])таким образом(?![а-яё])|"
    r"в итоге получается)",
    re.I,
)
VY_TY_RE = re.compile(
    r"(?<![а-яё])(вы|вам|вас|ваш|ваша|ваше|ваши|возьмите|посмотрите|откройте|"
    r"представьте|запомните|сделайте|нажмите)(?![а-яё])",
    re.I,
)


@dataclass
class Signals:
    slug: str
    fired: list[str] = field(default_factory=list)
    words: int = 0
    read_declared: int | None = None
    read_calc: int = 0
    staccato_max: int = 0
    short_pct: float = 0.0
    section_pct: float | None = None
    vy_ty_count: int = 0
    bare_en_count: int = 0
    math_mismatches: int = 0
    footnote_markers: int = 0
    footnote_defs: int = 0
    det_bonus: int = 0  # length / disproportion


def word_count(s: str) -> int:
    return len(re.findall(r"[а-яёa-z]+", s, re.I))


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+(?=[А-ЯA-Z«\"(])", text)
    return [p.strip() for p in parts if p.strip()]


def is_algebra_sentence(s: str) -> bool:
    t = s.strip()
    low = t.lower()
    if re.search(r"(?<![а-яё])x\s*=", t, re.I):
        return True
    if re.search(r"\d+x\s*=", t, re.I):
        return True
    if re.search(r"пусть\s+\w+\s*=", low):
        return True
    if re.search(r"тогда\s+\d", low):
        return True
    if "вычитаем" in low and "=" in t:
        return True
    if re.search(r"слева\s+\d", low):
        return True
    if re.match(r"значит\s+", low) and "=" in t:
        return True
    if re.search(r"0\.\d+", t) and "=" in t and word_count(s) <= 6:
        return True
    if word_count(s) <= 3 and re.search(r"[=+\-−/·\d]", t):
        return True
    return False


def staccato_stats(text: str) -> tuple[int, float]:
    sents = [s for s in split_sentences(text) if not is_algebra_sentence(s)]
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


def extract_sections(html: str) -> list[tuple[str, str]]:
    body_m = re.search(r'<div class="essay-body">(.*?)</div>\s*</div>', html, re.S)
    if not body_m:
        return []
    chunk = body_m.group(1)
    parts = re.split(r'<div class="sub-h">([^<]+)</div>', chunk)
    if len(parts) == 1:
        return []
    sections: list[tuple[str, str]] = []
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        raw = parts[i + 1] if i + 1 < len(parts) else ""
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)).strip()
        sections.append((title, text))
    return sections


def section_pct_max(html: str) -> float | None:
    sections = extract_sections(html)
    counts = [(t, word_count(txt)) for t, txt in sections if word_count(txt) > 30]
    total = sum(c for _, c in counts)
    if total < 200 or len(counts) < 2:
        return None
    mx = max(c for _, c in counts)
    return 100 * mx / total


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


def bare_english_tokens(slug: str, text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]{1,}", text)
    tokens = merge_en_tokens(tokens)
    found: list[str] = []
    for t in tokens:
        low = t.lower()
        if low in EN_DROP or t in EN_KEEP or low in {k.lower() for k in EN_KEEP}:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z'\-]+", t):
            continue
        if t in EN_BARE_SIGNAL or low in EN_BARE_SIGNAL:
            if slug in POKER_SLUGS and low in {"bet", "pot", "odds", "line", "game", "value", "random"}:
                continue
            found.append(t)
    return found


def count_footnotes(html: str) -> tuple[int, int, bool]:
    markers = [int(x) for x in re.findall(r'<em class="fn">(\d+)</em>', html)]
    defs = [int(x) for x in re.findall(r'<span class="n">\[(\d+)\]</span>', html)]
    flag = sorted(markers) != sorted(defs)
    return len(markers), len(defs), flag


def math_mismatch_count(slug: str, prose: str) -> int:
    from math_check import dedupe_mismatches, run_checks

    mm, _ = run_checks(slug, prose)
    return len(dedupe_mismatches(mm))


def compute_signals(slug: str, slice_: EssaySlice, html: str) -> Signals:
    text = slice_.prose_body
    sig = Signals(slug=slug)
    sig.words = word_count(text)
    sig.read_declared = slice_.read_declared
    sig.read_calc = round(sig.words / 150) if sig.words else 0
    sig.staccato_max, sig.short_pct = staccato_stats(text)
    sig.section_pct = section_pct_max(html)
    sig.vy_ty_count = (
        len(VY_TY_RE.findall(text))
        if re.search(r"(?<![а-яё])ты(?![а-яё])", text, re.I)
        else 0
    )
    sig.bare_en_count = len(bare_english_tokens(slug, text))
    sig.math_mismatches = math_mismatch_count(slug, text)
    fm, fd, fn_flag = count_footnotes(html)
    sig.footnote_markers = fm
    sig.footnote_defs = fd

    if sig.words and (sig.words < 600 or sig.words > 2500):
        sig.fired.append(f"length:{sig.words}w")
        sig.det_bonus += 1
    if slice_.read_declared is not None and abs(sig.read_calc - slice_.read_declared) > 4:
        sig.fired.append(f"readtime:{slice_.read_declared}≠{sig.read_calc}")
    if fn_flag:
        sig.fired.append(f"footnotes:{fm}≠{fd}")
    if sig.staccato_max >= 5 or (sig.staccato_max >= 4 and sig.short_pct >= 40):
        sig.fired.append(f"staccato:{sig.staccato_max}/{sig.short_pct:.0f}%")
    if sig.short_pct >= 45 and sig.staccato_max >= 3:
        sig.fired.append(f"short_pct:{sig.short_pct:.0f}%")
    if sig.section_pct and sig.section_pct > 50:
        sig.fired.append(f"section>{sig.section_pct:.0f}%")
        sig.det_bonus += 1
    if sig.vy_ty_count > 0:
        sig.fired.append(f"vy_ty×{sig.vy_ty_count}")
    if sig.bare_en_count > 0:
        sig.fired.append(f"bare_en×{sig.bare_en_count}")
    if sig.math_mismatches > 0:
        sig.fired.append(f"math×{sig.math_mismatches}")

    return sig


def is_candidate(sig: Signals) -> bool:
    return len(sig.fired) > 0


def collect_candidates(slugs: list[str] | None = None) -> tuple[dict[str, EssaySlice], dict[str, Signals], list[str]]:
    """Return slices, signals, and candidate slug list (signals + anchors)."""
    if slugs is None:
        slugs = sorted(p.stem for p in ESSAYS.glob("*.html") if p.name != "index.html")
    slices: dict[str, EssaySlice] = {}
    signals: dict[str, Signals] = {}
    candidates: set[str] = set(ANCHORS)
    for slug in slugs:
        path = ESSAYS / f"{slug}.html"
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        sl = parse_essay(path)
        slices[slug] = sl
        sig = compute_signals(slug, sl, html)
        signals[slug] = sig
        if is_candidate(sig):
            candidates.add(slug)
    return slices, signals, sorted(candidates)
