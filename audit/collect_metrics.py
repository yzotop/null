#!/usr/bin/env python3
"""Layer A mechanical metrics for null essays. Read-only."""
from __future__ import annotations

import csv
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESSAYS = ROOT / "essays"
INDEX = ESSAYS / "index.html"
LINKS = ROOT / "data" / "links.json"
OUT_CSV = Path(__file__).resolve().parent / "essays-metrics.csv"
OUT_TEXT = Path(__file__).resolve().parent / "_texts"

# Russian equivalents for common untranslated terms
EN_CANDIDATES = {
    "skin in the game", "via negativa", "expected value", "expected utility",
    "black swan", "antifragile", "optionality", "flaneur", "flâneur",
    "bootstrap", "feedback", "default", "benchmark", "pipeline", "framework",
    "stakeholder", "insight", "trade-off", "tradeoff", "edge case",
    "overfitting", "underfitting", "backtest", "backtesting", "dataset",
    "baseline", "prior", "posterior", "likelihood", "runtime", "offline",
    "online", "workflow", "stake", "stack", "leverage", "hedge",
    "upside", "downside", "tail risk", "skin-in-the-game",
}

TYPO_PATTERNS = {
    "straight_double_quote": re.compile(r'(?<![=/>])\s"[^"]+"'),
    "straight_single_quote": re.compile(r"(?<=\s)'[^']+'"),
    "hyphen_instead_em": re.compile(r"\w\s-\s\w"),
    "double_space": re.compile(r"  +"),
    "three_dots": re.compile(r"\.\.\.(?!\.)"),
    "space_dash_space": re.compile(r" \- "),
}

FORMULA_PATTERNS = [
    re.compile(r"<span[^>]*class=\"[^\"]*(?:formula|gl-formula|math)[^\"]*\"", re.I),
    re.compile(r"class=\"[^\"]*katex[^\"]*\"", re.I),
    re.compile(r"\$[^$]+\$"),
    re.compile(r"\\\[[\s\S]*?\\\]"),
    re.compile(r"\\\([\s\S]*?\\\)"),
]

IMAGE_PATTERNS = [
    re.compile(r"<svg\b", re.I),
    re.compile(r"<img\b", re.I),
    re.compile(r"chart\.js", re.I),
    re.compile(r"<canvas\b", re.I),
]

LATIN_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9\-']{1,})(?![A-Za-z0-9_])"
)

SKIP_LATIN = {
    "EV", "MDF", "GTO", "Nash", "Kelly", "Bayes", "Markov", "Taleb", "Bezos",
    "Amazon", "Jeff", "Google", "OpenAI", "GPT", "LLM", "LLMs", "Alpha", "Beta",
    "Gamma", "Delta", "Sigma", "Pi", "Phi", "Euler", "Gauss", "Fisher", "Pearson",
    "Bernoulli", "Pascal", "Fermat", "Neyman", "Freedman", "Kahneman", "Tversky",
    "Thaler", "Sunstein", "Knight", "von", "Neumann", "Morgenstern", "Nash",
    "Shannon", "Kolmogorov", "Gödel", "Godel", "Hilbert", "RSA", "ZFC", "MCMC",
    "CLT", "iid", "i", "e", "log", "sin", "cos", "tan", "min", "max", "avg",
    "std", "var", "pdf", "cdf", "ROC", "AUC", "FPR", "TPR", "AB", "UI", "UX",
    "API", "HTTP", "HTML", "CSS", "JS", "URL", "ID", "PMF", "CDF", "RNG",
    "CPU", "GPU", "SQL", "JSON", "XML", "RSS", "CEO", "CFO", "IPO", "VC",
    "B2B", "B2C", "SaaS", "CTR", "CPM", "CPC", "ROI", "KPI", "LTV", "CAC",
    "ARPU", "DAU", "MAU", "NPS", "OKR", "A", "B", "C", "D", "E", "F", "G",
    "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U",
    "V", "W", "X", "Y", "Z", "null", "NaN", "Inf", "Polymarket", "ChatGPT",
    "xG", "Elo", "FIFA", "UEFA", "NFL", "NBA", "MLB", "ATP", "WTA",
}

SOURCE_HINT = re.compile(
    r"(\d{3,4}\b|[«\"][^»\"]+[»\"]|·|—|\bISBN\b|\bvol\.|\bpp\.|\bJournal\b|\bPress\b)",
    re.I,
)


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


def load_categories() -> dict[str, tuple[str, str]]:
    html = INDEX.read_text(encoding="utf-8")
    cat_map: dict[str, tuple[str, str]] = {}
    sections = re.split(r'<div class="essay-section-header"', html)
    for sec in sections[1:]:
        sid_m = re.search(r'id="(s\d+)"', sec)
        title_m = re.search(r'essay-section-ttl">([^<]+)', sec)
        if not sid_m:
            continue
        sid, title = sid_m.group(1), (title_m.group(1).strip() if title_m else sid_m.group(1))
        for href in re.findall(r'<a class="essay-item" href="([^"]+\.html)"', sec):
            cat_map[Path(href).stem] = (sid, title)
    return cat_map


def load_valid_targets() -> set[str]:
    with open(LINKS, encoding="utf-8") as f:
        data = json.load(f)
    valid: set[str] = set()
    for n in data["nodes"]:
        valid.add(n["id"])
        url = n.get("url", "")
        if url:
            for v in (url, url.lstrip("/"), Path(url).name, Path(url).stem):
                valid.add(v)
    # known site sections (not graph nodes but valid targets)
    for extra in (
        "/null/books/", "/null/visuals/charts/", "/null/map.html", "/null/find.html",
        "/null/man.html", "books/", "visuals/charts/",
    ):
        valid.add(extra)
    for p in ROOT.rglob("*.html"):
        rel = p.relative_to(ROOT)
        valid.add(str(rel))
        valid.add("/null/" + str(rel).replace("\\", "/"))
        valid.add(p.name)
        valid.add(p.stem)
        valid.add("../" + str(rel).replace("\\", "/"))
    return valid


def strip_html(html: str) -> str:
    ext = TextExtractor()
    ext.feed(html)
    return re.sub(r"\s+", " ", ext.text()).strip()


def extract_body_html(html: str) -> str:
    m = re.search(r'<div class="essay-body">(.*?)</div>\s*</div>\s*<(?:blockquote|hr|section|div class="note")',
                  html, re.S)
    if m:
        return m.group(1)
    m = re.search(r"<article>(.*)</article>", html, re.S)
    return m.group(1) if m else html


def parse_meta(html: str) -> dict:
    label_m = re.search(r'class="essay-label"[^>]*>([^<]+)', html)
    label = label_m.group(1) if label_m else ""
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    h1 = re.sub(r"<[^>]+>", "", h1_m.group(1)).strip() if h1_m else ""
    date_m = re.search(r"(\d{4}\.\d{2})", label)
    date = date_m.group(1) if date_m else ""
    read_m = re.search(r"~(\d+)\s*мин", label, re.I)
    if not read_m:
        read_m = re.search(r"(\d+)\s*мин", label, re.I)
    read_declared = int(read_m.group(1)) if read_m else None
    return {"label": label, "h1": h1, "date": date, "read_declared": read_declared}


def count_footnotes(html: str) -> tuple[int, int, int, bool]:
    markers = [int(x) for x in re.findall(r'<em class="fn">(\d+)</em>', html)]
    defs = [int(x) for x in re.findall(r'<span class="n">\[(\d+)\]</span>', html)]
    marker_n = len(markers)
    def_n = len(defs)
    flag = sorted(markers) != sorted(defs)
    without_source = 0
    for block in re.findall(r'<div class="note">(.*?)</div>', html, re.S):
        text = strip_html(block)
        if not SOURCE_HINT.search(text):
            without_source += 1
    return marker_n, def_n, without_source, flag


def count_section_blocks(html: str) -> tuple[int, int, int]:
    na = len(re.findall(r'<div class="mh">на полях</div>', html, re.I))
    svy = 1 if re.search(r'<section class="related">', html) else 0
    upo = 1 if re.search(r'<section class="backlinks">', html) else 0
    return na, svy, upo


def article_html(html: str) -> str:
    m = re.search(r"<article>(.*)</article>", html, re.S)
    return m.group(1) if m else html


def extract_links(html: str) -> list[str]:
    hrefs = re.findall(r'href="([^"#]+)"', article_html(html))
    out = []
    for h in hrefs:
        if h.startswith("http") or h.startswith("mailto:"):
            continue
        if h.endswith((".html", "/")) or "/null/" in h or h.startswith("../"):
            out.append(h)
    return out


def link_broken(href: str, valid: set[str]) -> bool:
    if href in valid:
        return False
    name = Path(href.split("?")[0]).name
    stem = Path(href.split("?")[0]).stem
    if name in valid or stem in valid:
        return False
    # normalize /null/ prefix
    h = href.lstrip("/")
    if h in valid:
        return False
    if h.startswith("null/"):
        if h in valid or h[5:] in valid:
            return False
    return True


def check_headings(html: str) -> tuple[bool, list[str]]:
  violations = []
  for h in re.findall(r'<div class="sub-h">([^<]+)</div>', html):
      t = h.strip()
      if t != t.lower():
          violations.append(t)
  for h in re.findall(r"<h[2-4][^>]*>(.*?)</h[2-4]>", html, re.S):
      t = re.sub(r"<[^>]+>", "", h).strip()
      if t and t != t.lower() and "essay" not in t.lower():
          violations.append(t)
  return len(violations) == 0, violations


def latin_tokens(text: str) -> tuple[list[str], list[str]]:
    found: list[str] = []
    candidates: list[str] = []
    for m in LATIN_TOKEN.finditer(text):
        w = m.group(1)
        if w in SKIP_LATIN or len(w) < 3:
            continue
        # skip if inside obvious formula/code context - rough: surrounded by digits/symbols
        if re.fullmatch(r"[A-Z]{2,5}", w):
            continue
        wl = w.lower()
        if wl not in {x.lower() for x in found}:
            found.append(w)
        for cand in EN_CANDIDATES:
            if cand.lower() in wl or wl in cand.lower():
                if w not in candidates:
                    candidates.append(w)
    return found, candidates


def typo_counts(text: str) -> dict[str, int]:
    counts = {}
    for name, pat in TYPO_PATTERNS.items():
        counts[name] = len(pat.findall(text))
    return counts


def count_formulas(html: str) -> int:
    n = 0
    for pat in FORMULA_PATTERNS:
        n += len(pat.findall(html))
    return n


def has_image(html: str) -> bool:
    return any(p.search(html) for p in IMAGE_PATTERNS)


def analyze_essay(path: Path, categories: dict, valid: set[str]) -> dict:
    html = path.read_text(encoding="utf-8")
    slug = path.stem
    meta = parse_meta(html)
    body_html = extract_body_html(html)
    body_text = strip_html(body_html)
    chars_no_spaces = len(re.sub(r"\s", "", body_text))
    words = len(body_text.split()) if body_text else 0
    read_calc = round(words / 150) if words else 0
    read_decl = meta["read_declared"]
    flag_read = False
    if read_decl is not None:
        flag_read = abs(read_calc - read_decl) > 4
    fm, fd, fws, flag_fn = count_footnotes(html)
    na, svy, upo = count_section_blocks(html)
    hrefs = extract_links(html)
    broken = [h for h in hrefs if link_broken(h, valid)]
    links_out = len(hrefs)
    formulas = count_formulas(html)
    img = has_image(html)
    lh_ok, lh_viol = check_headings(html)
    lat, lat_cand = latin_tokens(body_text)
    typos = typo_counts(body_text)
    typo_total = sum(typos.values())
    cat = categories.get(slug, ("", ""))
    return {
        "slug": slug,
        "title": meta["h1"],
        "category_sec": cat[0],
        "category_title": cat[1],
        "date": meta["date"],
        "chars_no_spaces": chars_no_spaces,
        "words": words,
        "read_min_calc": read_calc,
        "read_min_declared": read_decl if read_decl is not None else "",
        "flag_readtime": "yes" if flag_read else "no",
        "footnote_markers": fm,
        "footnote_defs": fd,
        "flag_footnotes": "yes" if flag_fn else "no",
        "footnotes_without_source": fws,
        "na_polyah": na,
        "svyazannoe": svy,
        "upominaetsya_v": upo,
        "links_out": links_out,
        "broken_links": ";".join(sorted(set(broken))),
        "broken_links_count": len(set(broken)),
        "formulas": formulas,
        "has_image": "yes" if img else "no",
        "lowercase_headings_ok": "yes" if lh_ok else "no",
        "lowercase_violations": "; ".join(lh_viol[:10]),
        "eng_latin_tokens": "; ".join(lat[:40]),
        "eng_latin_count": len(lat),
        "eng_candidates": "; ".join(lat_cand[:20]),
        "eng_candidates_count": len(lat_cand),
        "typo_straight_double": typos.get("straight_double_quote", 0),
        "typo_straight_single": typos.get("straight_single_quote", 0),
        "typo_hyphen_em": typos.get("hyphen_instead_em", 0),
        "typo_double_space": typos.get("double_space", 0),
        "typo_three_dots": typos.get("three_dots", 0),
        "typo_space_dash": typos.get("space_dash_space", 0),
        "typo_total": typo_total,
        # Layer B placeholders
        "literacy": "",
        "material": "",
        "actuality": "",
        "weird_phrasings": "",
        "factcheck_flags": "",
        "grammar": "",
        "actuality_refs": "",
        "literacy_note": "",
        "material_note": "",
        "actuality_note": "",
        "_body_text": body_text[:12000],
    }


FIELDNAMES = [
    "slug", "title", "category_sec", "category_title", "date",
    "chars_no_spaces", "words", "read_min_calc", "read_min_declared", "flag_readtime",
    "footnote_markers", "footnote_defs", "flag_footnotes", "footnotes_without_source",
    "na_polyah", "svyazannoe", "upominaetsya_v",
    "links_out", "broken_links_count", "broken_links",
    "formulas", "has_image", "lowercase_headings_ok", "lowercase_violations",
    "eng_latin_count", "eng_latin_tokens", "eng_candidates_count", "eng_candidates",
    "typo_straight_double", "typo_straight_single", "typo_hyphen_em",
    "typo_double_space", "typo_three_dots", "typo_space_dash", "typo_total",
    "literacy", "literacy_note", "material", "material_note",
    "actuality", "actuality_note", "actuality_refs",
    "weird_phrasings", "factcheck_flags", "grammar",
]


def write_batch(rows: list[dict], append: bool) -> None:
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append and OUT_CSV.exists() else "w"
    with open(OUT_CSV, mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    batch_idx = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    categories = load_categories()
    valid = load_valid_targets()
    files = sorted(
        p for p in ESSAYS.glob("*.html")
        if p.name != "index.html"
    )
    if batch_size:
        start = batch_idx * batch_size
        files = files[start : start + batch_size]
        append = batch_idx > 0
    else:
        append = False

    OUT_TEXT.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in files:
        row = analyze_essay(path, categories, valid)
        (OUT_TEXT / f"{row['slug']}.txt").write_text(row.pop("_body_text"), encoding="utf-8")
        rows.append(row)
        print(f"  {row['slug']}: {row['words']} words, broken={row['broken_links_count']}")

    write_batch(rows, append)
    print(f"wrote {len(rows)} rows -> {OUT_CSV}")


if __name__ == "__main__":
    main()
