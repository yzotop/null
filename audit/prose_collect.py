#!/usr/bin/env python3
"""Mechanical prose metrics for null essays. Read-only."""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESSAYS = ROOT / "essays"
AUDIT = Path(__file__).resolve().parent
METRICS_CSV = AUDIT / "essays-metrics.csv"
OUT_CSV = AUDIT / "prose-metrics.csv"
OUT_EN_RAW = AUDIT / "_english_terms_raw.json"
OUT_MECH = AUDIT / "layer_prose" / "mechanical.json"
HUNSPELL_DIC = Path("/tmp/ru_RU.dic")

# Calibration anchors (literacy reference)
ANCHOR_HIGH = {"antifragile", "decisions-distance", "oshibki-po-pravilam", "bayes-four-faces", "forking-paths"}
ANCHOR_LOW = {"adtech", "bayesian", "clt", "benford", "poker-glossary"}

CANC_RE = re.compile(
    r"\b(является|являются|данный|данная|данное|данные|осуществляется|осуществляют|"
    r"в рамках|носит характер|является основой|в целях|посредством|ввиду того что)\b",
    re.I,
)
CRUTCH_RE = re.compile(
    r"(на практике это|в реальности это|именно поэтому|то есть|как известно|"
    r"стоит отметить|следует отметить|необходимо отметить|важно понимать что|"
    r"в конечном счёте|в конечном счете)",
    re.I,
)
INTENTIONAL_MOTIFS = {
    "решения на дистанции", "не потому что", "четыре лица", "от пасьянса к атомной",
    "покер как профи", "ошибка базовой частоты", "a b тестирование",
}
LATIN_TOKEN = re.compile(r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9\-']{1,})")
SKIP_EN = {
    "EV", "MDF", "GTO", "Nash", "Kelly", "Bayes", "Markov", "Taleb", "Google", "OpenAI",
    "GPT", "LLM", "LLMs", "MCMC", "CLT", "ROC", "AUC", "CTR", "CPM", "CPC", "CPA",
    "ROI", "KPI", "LTV", "CAC", "API", "URL", "HTML", "CSS", "JS", "SQL", "JSON",
    "CEO", "DSP", "SSP", "RTB", "eCPM", "PG", "MRC", "CVR", "AB", "UI", "UX", "iid",
    "pdf", "cdf", "PMF", "RNG", "CPU", "GPU", "xG", "Elo", "FIFA", "NBA", "NFL",
    "null", "NaN", "VCG", "NP", "RSA", "ZFC", "i", "e", "log", "sin", "cos", "min", "max",
}
SKIP_EN_NAMES = {
    "Fisher", "Pearson", "Bernoulli", "Pascal", "Fermat", "Neyman", "Kahneman", "Tversky",
    "Thaler", "Sunstein", "Knight", "Neumann", "Morgenstern", "Shannon", "Kolmogorov",
    "Gödel", "Godel", "Hilbert", "Euler", "Gauss", "Bezos", "Amazon", "Jeff", "Alpha",
    "Beta", "Gamma", "Delta", "Sigma", "Pi", "Phi", "Polymarket", "ChatGPT", "Wason",
    "Vickrey", "Vickery", "Bertand", "Bertand", "Sunstein", "Cohen", "Grünwald", "Ioannidis",
    "Trafimow", "Optimizely", "VWO", "Rubicon", "PubMatic", "Index", "Exchange", "OpenX",
    "AdX", "AdWords", "Trade", "Desk", "Manager", "Dynamic", "Yield", "Peek", "Prior",
    "Posterior", "Likelihood", "Bootstrap", "Freedman", "Jaynes", "Price", "Biden", "Royal",
    "Society", "Philosophical", "Transactions", "Cambridge", "Science", "Journal", "Press",
    "Basic", "Applied", "Social", "Psychology", "Medicine", "Finance", "Workers", "Why",
    "Most", "Published", "Findings", "Are", "False", "Statistical", "Methods", "Research",
    "Nassim", "Nicholas", "Antifragile", "Things", "Gain", "Disorder", "Probability",
    "Theory", "Logic", "Essay", "towards", "solving", "Problem", "Doctrine", "Chances",
    "An", "The", "And", "For", "With", "From", "That", "This", "Not", "But", "You",
    "Your", "Our", "Their", "They", "She", "His", "Her", "Its", "All", "One", "Two",
    "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Real", "Time",
    "Bidding", "bid", "request", "demand", "side", "platforms", "supply", "platform",
    "first", "price", "second", "header", "floor", "Second", "shading", "cost", "per",
    "mille", "click", "action", "effective", "through", "rate", "conversion", "Tension",
    "revenue", "retention", "load", "optimization", "threshold", "viewability", "brand",
    "safety", "frequency", "capping", "programmatic", "guaranteed", "unified", "pricing",
    "private", "marketplace", "open", "auction", "inventory", "awareness", "reach",
    "dominant", "strategy", "incentive", "compatibility", "Combinatorial", "auctions",
    "matching", "markets", "Counterspeculation", "Competitive", "Sealed", "Tenders",
    "stable", "expected", "utility", "Prospect", "prevalence", "relative", "uplift",
    "problem", "sequential", "testing", "values", "always", "valid", "values", "confidence",
    "guardrail", "metrics", "nwald", "Heide", "Koolen", "Shafer", "ad", "tech",
}


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def strip_html(html: str) -> str:
    ext = TextExtractor()
    ext.feed(html)
    return re.sub(r"\s+", " ", ext.text()).strip()


def extract_body(html: str) -> str:
    m = re.search(
        r'<div class="essay-body">(.*?)</div>\s*</div>\s*<(?:blockquote|aside|hr|section)',
        html,
        re.S,
    )
    if m:
        return strip_html(m.group(1))
    m = re.search(r'<div class="essay-body">(.*?)</div>', html, re.S)
    return strip_html(m.group(1)) if m else strip_html(html)


def extract_sections(html: str) -> list[tuple[str, str]]:
    body_m = re.search(r'<div class="essay-body">(.*?)</div>\s*</div>', html, re.S)
    if not body_m:
        return [("body", extract_body(html))]
    chunk = body_m.group(1)
    parts = re.split(r'<div class="sub-h">([^<]+)</div>', chunk)
    if len(parts) == 1:
        return [("body", strip_html(chunk))]
    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("lead", strip_html(parts[0])))
    for i in range(1, len(parts), 2):
        title = parts[i].strip()
        text = strip_html(parts[i + 1]) if i + 1 < len(parts) else ""
        sections.append((title, text))
    return sections


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?…])\s+(?=[А-ЯA-Z«\"(])", text)
    return [p.strip() for p in parts if p.strip()]


def word_count(s: str) -> int:
    return len(re.findall(r"[а-яёa-z]+", s, re.I))


def sentence_stats(sentences: list[str]) -> dict:
    lens = [word_count(s) for s in sentences]
    if not lens:
        return {"avg": 0, "short_pct": 0, "staccato_max": 0}
    short = sum(1 for l in lens if l < 5)
    max_run = cur = 0
    for l in lens:
        if l < 5:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 0
    return {
        "avg": round(sum(lens) / len(lens), 1),
        "short_pct": round(100 * short / len(lens), 1),
        "staccato_max": max_run,
    }


def find_staccato_runs(sentences: list[str], min_run: int = 4) -> list[dict]:
    runs = []
    cur: list[str] = []
    for s in sentences:
        if word_count(s) < 5:
            cur.append(s)
        else:
            if len(cur) >= min_run:
                runs.append({"quote": " ".join(cur[:6]), "count": len(cur)})
            cur = []
    if len(cur) >= min_run:
        runs.append({"quote": " ".join(cur[:6]), "count": len(cur)})
    return runs


def find_monotone(sentences: list[str], min_run: int = 3) -> list[dict]:
    def start(s: str) -> str:
        w = re.findall(r"[а-яёa-z]+", s.lower())
        return " ".join(w[:2]) if w else ""

    runs = []
    cur: list[str] = []
    cur_start = ""
    for s in sentences:
        st = start(s)
        if st and st == cur_start:
            cur.append(s)
        else:
            if len(cur) >= min_run:
                runs.append({"quote": cur[0][:120], "pattern": cur_start, "count": len(cur)})
            cur = [s]
            cur_start = st
    if len(cur) >= min_run:
        runs.append({"quote": cur[0][:120], "pattern": cur_start, "count": len(cur)})
    return runs


def find_pattern_spans(text: str, pattern: re.Pattern, label: str, window: int = 80) -> list[dict]:
    spans = []
    for m in pattern.finditer(text):
        start = max(0, m.start() - window)
        end = min(len(text), m.end() + window)
        quote = text[start:end].strip()
        if len(quote) > 200:
            quote = "…" + quote[m.start() - start - 20 : m.end() - start + 40] + "…"
        spans.append({"label": label, "quote": quote, "match": m.group(0)})
    return spans


def load_ru_dict() -> set[str]:
    words: set[str] = set()
    if HUNSPELL_DIC.exists():
        lines = HUNSPELL_DIC.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[1:]:
            w = line.split("/")[0].strip().lower()
            if w:
                words.add(w)
    return words


SPELL_OK = {
    "матожидание", "матожидания", "байесовский", "байесовская", "байесовское", "байесовские",
    "антихрупкость", "антихрупкости", "эргодичность", "эргодичности", "матжаргон",
    "апсайд", "даунсайд", "бэктест", "бэктестинг", "онлайн", "офлайн",
}

RU_DICT = load_ru_dict()
def hunspell_misses(words: list[str]) -> set[str]:
    if not words:
        return set()
    try:
        p = subprocess.run(
            ["hunspell", "-d", "/tmp/ru_RU", "-l"],
            input="\n".join(words) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {w.strip().lower() for w in p.stdout.splitlines() if w.strip()}
    except Exception:
        return {w for w in words if w.lower() not in RU_DICT}


def spellcheck_candidates(text: str) -> list[str]:
    tokens = re.findall(r"[а-яёА-ЯЁ]{5,}", text)
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        low = t.lower()
        if low in seen or low in SPELL_OK:
            continue
        seen.add(low)
        uniq.append(low)
    misses = hunspell_misses(uniq)
    return [t for t in tokens if t.lower() in misses][:15]


def extract_english(text: str) -> list[str]:
    found = []
    for m in LATIN_TOKEN.finditer(text):
        w = m.group(1)
        if w in SKIP_EN or w in SKIP_EN_NAMES or len(w) < 3:
            continue
        if w.isupper() and len(w) <= 4:
            continue
        found.append(w)
    return found


def section_imbalance(sections: list[tuple[str, str]]) -> dict | None:
    counts = [(t, word_count(txt)) for t, txt in sections if word_count(txt) > 30]
    counts = [(t, c) for t, c in counts if t not in ("body", "lead")]
    total = sum(c for _, c in counts)
    if total < 200 or len(counts) < 2:
        return None
    title, mx = max(counts, key=lambda x: x[1])
    pct = 100 * mx / total
    if pct > 40:
        return {"section": title, "pct": round(pct, 1), "words": mx, "total": total}
    return None


def literacy_score(
    slug: str,
    staccato_max: int,
    crutch_n: int,
    canc_n: int,
    short_pct: float,
    spell_n: int,
    eng_n: int,
) -> int:
    if slug in ANCHOR_HIGH:
        return 5
    if slug in ANCHOR_LOW:
        return max(2, 3)
    score = 4
    if staccato_max >= 5:
        score -= 1
    if crutch_n >= 4:
        score -= 1
    if canc_n >= 3:
        score -= 1
    if short_pct > 25:
        score -= 1
    if spell_n > 5:
        score -= 0.5
    if eng_n > 40:
        score -= 0.5
    return max(1, min(5, round(score)))


def load_word_counts() -> dict[str, int]:
    out = {}
    with open(METRICS_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["slug"]] = int(row.get("words") or 0)
    return out


def main() -> int:
    OUT_MECH.parent.mkdir(parents=True, exist_ok=True)
    word_counts = load_word_counts()
    english_corpus: Counter[str] = Counter()
    english_by_essay: dict[str, list[str]] = defaultdict(list)
    rows_out = []
    mechanical: dict[str, dict] = {}

    slugs = sorted(p.stem for p in ESSAYS.glob("*.html") if p.name != "index.html")

    for slug in slugs:
        path = ESSAYS / f"{slug}.html"
        if not path.exists():
            continue
        html = path.read_text(encoding="utf-8")
        body = extract_body(html)
        sections = extract_sections(html)
        sentences = split_sentences(body)
        stats = sentence_stats(sentences)
        words = word_counts.get(slug, word_count(body))

        length_flags = []
        if words < 600:
            length_flags.append(f"thin:{words}w")
        if words > 2500:
            length_flags.append(f"bloated:{words}w")
        imb = section_imbalance(sections)
        if imb:
            length_flags.append(f"section>{imb['pct']}%:{imb['section']}")

        staccato = find_staccato_runs(sentences)
        monotone = find_monotone(sentences)
        canc = find_pattern_spans(body, CANC_RE, "register-slip")
        crutch_matches = list(CRUTCH_RE.finditer(body))
        crutch_n = len(crutch_matches)
        crutch_spans = find_pattern_spans(body, CRUTCH_RE, "crutch")
        spell_bad = spellcheck_candidates(body)
        eng_tokens = extract_english(body)
        for t in eng_tokens:
            english_corpus[t] += 1
            english_by_essay[slug].append(t)

        lit = literacy_score(
            slug, stats["staccato_max"], crutch_n, len(canc),
            stats["short_pct"], len(spell_bad), len(eng_tokens),
        )

        flags = {
            "length": length_flags,
            "section_imbalance": imb,
            "register_slip": canc[:8],
            "staccato_run": [
                {"label": "staccato-run", "quote": r["quote"], "suggest": "связать в одно-два развёрнутых предложения"}
                for r in staccato[:3]
            ],
            "monotone": [
                {"label": "monotone", "quote": r["quote"], "pattern": r["pattern"],
                 "suggest": f"разнообразить зачин («{r['pattern']}…» ×{r['count']})"}
                for r in monotone[:3]
            ],
            "crutch": [
                {"label": "crutch", "quote": s["quote"], "match": s["match"],
                 "suggest": "убрать затычку или заменить конкретикой"}
                for s in crutch_spans[:6]
            ],
            "spell_candidates": spell_bad,
            "english_count": len(eng_tokens),
        }
        mechanical[slug] = flags

        rows_out.append({
            "slug": slug,
            "words": words,
            "sent_avg": stats["avg"],
            "sent_short_pct": stats["short_pct"],
            "staccato_max": stats["staccato_max"],
            "crutch_count": crutch_n,
            "canc_count": len(canc),
            "english_tokens": len(eng_tokens),
            "spell_candidates": len(spell_bad),
            "literacy_score": lit,
            "length_flags": ";".join(length_flags),
        })

    fieldnames = list(rows_out[0].keys())
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(sorted(rows_out, key=lambda r: r["slug"]))

    OUT_EN_RAW.write_text(
        json.dumps(
            {"corpus": dict(english_corpus.most_common()), "by_essay": dict(english_by_essay)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    OUT_MECH.write_text(json.dumps(mechanical, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"prose-metrics: {len(rows_out)} essays → {OUT_CSV}")
    print(f"english terms: {len(english_corpus)} unique")
    return 0


if __name__ == "__main__":
    sys.exit(main())
