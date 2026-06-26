#!/usr/bin/env python3
"""Merge mechanical + layer prose judgments into audit output files."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
ESSAYS = ROOT / "essays"
MECH = AUDIT / "layer_prose" / "mechanical.json"
LAYER_DIR = AUDIT / "layer_prose"
METRICS = AUDIT / "prose-metrics.csv"
EN_RAW = AUDIT / "_english_terms_raw.json"
OUT_FLAGS = AUDIT / "prose-flags.md"
OUT_EN = AUDIT / "english-terms.md"
OUT_PRIORITY = AUDIT / "prose-priority.md"

ANCHOR_HIGH = {"antifragile", "decisions-distance", "oshibki-po-pravilam", "bayes-four-faces", "forking-paths"}
ANCHOR_LOW = {"adtech", "bayesian", "clt", "benford", "poker-glossary"}

SPELL_OK = {
    "матожидание", "матожидания", "матожиданию", "байесовский", "байесовская", "байесовское",
    "байесовские", "антихрупкость", "антихрупкости", "антихрупкое", "эргодичность", "эргодичности",
    "поглощающее", "поглощающего", "переоцениваем", "невозвратно", "невозвратные", "логарифмирование",
    "детерминированность", "недооцениваем", "переобучение", "недообучение", "распределённость",
    "квази", "микро", "макро", "супер", "гипер", "мульти", "онлайн", "офлайн", "бэктест", "бэктестинг",
    "подвыборка", "переподгонка", "переобучен", "переобучена", "кросс", "валидация",
}

SLANG_RE = re.compile(
    r"(?<![а-яё])(типа|короче|ваще|вобщем|в общем|окей|круто|крутой|лол|чувак|норм|зашло|фигня|фигню)(?![а-яё])",
    re.I,
)
VY_RE = re.compile(
    r"(?<![а-яё])(вы|вам|вас|ваш|ваша|ваше|ваши)(?![а-яё])",
    re.I,
)
CALQUE_RE = [
    (re.compile(r"(?<![а-яё])имеет место(?![а-яё])", re.I), "calque", "кальки «имеет место»", "происходит / есть"),
    (re.compile(r"(?<![а-яё])в данном контексте(?![а-яё])", re.I), "calque", "канцелярит", "здесь / в этой задаче"),
    (re.compile(r"(?<![а-яё])осуществля\w+(?![а-яё])", re.I), "register-slip", "канцелярит", "делать / проводить"),
    (re.compile(r"(?<![а-яё])является(?![а-яё])", re.I), "register-slip", "канцелярит «является»", "— / это"),
]

EN_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "not", "but", "are", "was", "were", "have",
    "has", "had", "will", "can", "may", "essays", "essay", "journal", "press", "science", "nature",
    "university", "american", "philosophical", "transactions", "society", "cambridge", "london",
    "new", "york", "vol", "pp", "doi", "http", "https", "www", "com", "org", "edu", "pdf", "html",
}

EN_KEEP = {
    "MCMC", "GTO", "EV", "MDF", "AUC", "ROC", "CTR", "CPM", "CPC", "CPA", "eCPM", "ROI", "LTV",
    "DSP", "SSP", "RTB", "AB", "LLM", "LLMs", "GPT", "xG", "Elo", "p-value", "p-hacking", "self-play",
    "credit assignment", "alpha-beta", "zero-determinant", "tit-for-tat", "win-stay", "lose-shift",
    "PageRank", "bootstrap", "prior", "posterior", "likelihood", "overfitting", "underfitting",
    "backtest", "backtesting", "feedback", "default", "pipeline", "framework", "stakeholder",
    "benchmark", "baseline", "runtime", "offline", "online", "workflow", "leverage", "hedge",
    "upside", "downside", "skin in the game", "via negativa", "barbell", "nudge", "peek problem",
    "bid shading", "header bidding", "cold start", "brand safety", "viewability", "frequency capping",
    "programmatic", "Kalshi", "Polymarket", "AlphaGo", "Pluribus", "Diplomacy", "Deep Blue",
    "Monte Carlo", "Chain rule", "Prisoner's Dilemma", "Nash equilibrium", "minimax", "maximin",
}

EN_TRANSLATE = {
    "feedback": "обратная связь",
    "default": "по умолчанию",
    "pipeline": "конвейер / цепочка обработки",
    "framework": "каркас / схема",
    "stakeholder": "заинтересованная сторона",
    "benchmark": "эталон / бенчмарк",
    "baseline": "базовая линия / контроль",
    "runtime": "время выполнения",
    "workflow": "рабочий процесс",
    "leverage": "рычаг / усиление",
    "hedge": "хедж / страховка",
    "upside": "апсайд → выгода сверху",
    "downside": "даунсайд → риск снизу",
    "resulting": "resulting bias → ошибка исхода",
    "effect": "эффект (если не устоялось)",
    "value": "ценность / значение",
    "game": "игра",
    "random": "случайный",
    "line": "линия",
    "bet": "ставка",
    "odds": "котировки / шансы",
    "mod": "модуль / mod (уточнить)",
    "seed": "зерно генератора / seed",
    "precision": "точность",
    "grim": "grim trigger → мрачный триггер",
    "extortion": "вымогательство (ZD)",
    "overround": "оверраунд / маржа букмекера",
    "implied-": "implied probability → подразумеваемая вероятность",
}

CONCEPT_PAIRS = [
    ("prior", "априор"),
    ("posterior", "апостериор"),
    ("cold start", "холодный старт"),
    ("expected value", "матожидание"),
    ("loss aversion", "неприятие потерь"),
    ("base rate", "базовая частота"),
    ("confirmation bias", "подтверждающее искажение"),
    ("sunk cost", "невозвратные затраты"),
]


def extract_body(html: str) -> str:
    m = re.search(
        r'<div class="essay-body">(.*?)</div>\s*</div>\s*<(?:blockquote|aside|hr|section)',
        html,
        re.S,
    )
    if not m:
        m = re.search(r'<div class="essay-body">(.*?)</div>', html, re.S)
    chunk = m.group(1) if m else html
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    return re.sub(r"\s+", " ", chunk).strip()


def sentence_at(text: str, pos: int) -> str:
    left = text.rfind(".", 0, pos)
    left = max(left, text.rfind("!", 0, pos), text.rfind("?", 0, pos))
    right = len(text)
    for ch in ".!?":
        r = text.find(ch, pos)
        if r != -1:
            right = min(right, r + 1)
    return text[left + 1 : right].strip()


def load_layer() -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for p in sorted(LAYER_DIR.glob("batch_*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        merged.update(data)
    return merged


def enrich_spell(slug: str, candidates: list[str]) -> list[dict]:
    out = []
    for w in candidates:
        low = w.lower()
        if low in SPELL_OK:
            continue
        if re.match(r"^[А-ЯЁ]+$", w) and len(w) <= 5:
            continue
        # skip obvious inflections hunspell might miss without aff
        if len(low) > 8 and any(low.endswith(s) for s in ("ость", "ение", "ание", "иров", "еск")):
            continue
        out.append({
            "label": "word-usability",
            "quote": w,
            "why": "не в hunspell ru_RU — проверить (возможен термин/опечатка)",
            "suggest": "—",
        })
    return out[:6]


def enrich_vy(body: str) -> list[dict]:
    flags = []
    for m in VY_RE.finditer(body):
        if m.group(0).lower() == "вы" and "вы " in body[:80].lower():
            continue
        sent = sentence_at(body, m.start())
        if len(sent) < 20:
            continue
        flags.append({
            "label": "register-slip",
            "quote": sent[:180],
            "why": "обращение на «вы» в серии с регистром «ты»",
            "suggest": sent.replace("вы", "ты").replace("Вы", "Ты")[:180],
        })
        break
    return flags


def enrich_slang(body: str) -> list[dict]:
    return [
        {
            "label": "register-slip",
            "quote": sentence_at(body, m.start())[:180],
            "why": f"разговорное «{m.group(0)}»",
            "suggest": "заменить нейтральным литературным",
        }
        for m in SLANG_RE.finditer(body)
    ][:4]


def enrich_calques(body: str) -> list[dict]:
    out = []
    for pat, label, why, suggest in CALQUE_RE:
        for m in pat.finditer(body):
            out.append({
                "label": label,
                "quote": sentence_at(body, m.start())[:200],
                "why": why,
                "suggest": suggest,
            })
    return out[:6]


def literacy_from_flags(slug: str, base: int, flag_count: int) -> int:
    if slug in ANCHOR_HIGH:
        return 5
    if slug in ANCHOR_LOW and base >= 4:
        return 3
    adj = base
    if flag_count >= 8:
        adj -= 1
    if flag_count >= 15:
        adj -= 1
    return max(1, min(5, adj))


def build_english_table(corpus: Counter[str], by_essay: dict) -> str:
    lines = [
        "# Английские термины (корпус эссе)",
        "",
        "Механика: латинские токены из `essay-body`, без сносок/формул. Вердикт — по устойчивости в серии.",
        "",
        "| термин | частота | вердикт | русский вариант |",
        "|--------|---------|---------|-----------------|",
    ]
    rows = []
    for term, freq in corpus.most_common():
        low = term.lower()
        if low in EN_STOP or len(term) < 3:
            continue
        if freq < 2 and term not in EN_KEEP:
            continue
        if term in EN_KEEP or low in {k.lower() for k in EN_KEEP}:
            verdict, ru = "keep", "—"
        elif term in EN_TRANSLATE or low in {k.lower() for k in EN_TRANSLATE}:
            verdict, ru = "translate", EN_TRANSLATE.get(term, EN_TRANSLATE.get(low, "—"))
        elif re.search(r"[A-Z]{2,}", term):
            verdict, ru = "keep", "аббревиатура"
        elif term[0].isupper() and freq <= 3:
            continue
        else:
            verdict, ru = "keep", "— (проверить контекст)"
        rows.append((term, freq, verdict, ru))

    for term, freq, verdict, ru in sorted(rows, key=lambda x: (-x[1], x[0].lower())):
        lines.append(f"| {term} | {freq} | {verdict} | {ru} |")

    lines.extend(["", "## Непоследовательность (один концепт — разные языки)", ""])
    for en, ru in CONCEPT_PAIRS:
        en_slugs = [s for s, toks in by_essay.items() if any(en.lower() in t.lower() for t in toks)]
        ru_slugs = []
        for s in by_essay:
            p = ESSAYS / f"{s}.html"
            if p.exists() and ru.lower() in extract_body(p.read_text(encoding="utf-8")).lower():
                ru_slugs.append(s)
        if en_slugs and ru_slugs and len(set(en_slugs) - set(ru_slugs)) > 2:
            lines.append(f"- **{en}** / **{ru}**: EN в {len(en_slugs)} эссе, RU в {len(ru_slugs)} — выровнять")
    return "\n".join(lines) + "\n"


def essay_block(slug: str, mech: dict, layer: dict, metrics: dict) -> str | None:
    path = ESSAYS / f"{slug}.html"
    if not path.exists():
        return None
    body = extract_body(path.read_text(encoding="utf-8"))
    if len(body) < 100:
        return None
    parts: list[str] = []

    length = [x for x in mech.get("length", []) if "section>100%:body" not in x]
    imb = mech.get("section_imbalance")
    if imb and imb.get("section") == "body":
        imb = None
    if length or imb:
        parts.append("### Ось 1 — длина")
        if length:
            parts.append("- " + "; ".join(length))
        if imb:
            parts.append(
                f"- диспропорция: секция «{imb['section']}» — {imb['pct']}% ({imb['words']}/{imb['total']} слов)"
            )

    axis2 = []
    if slug not in ANCHOR_HIGH:
        for item in mech.get("register_slip", []):
            axis2.append({**item, "why": "канцелярит", "suggest": "переформулировать проще"})
    axis2.extend(mech.get("staccato_run", []))
    if slug not in ANCHOR_HIGH:
        axis2.extend(mech.get("monotone", []))
    axis2.extend(mech.get("crutch", []))
    # drop trivial single staccato unless layer confirms
    if not layer.get("axis2") and len(axis2) == 1 and axis2[0].get("label") == "staccato-run":
        if axis2[0].get("count", 0) < 4:
            axis2 = []
    axis2.extend(enrich_vy(body))
    axis2.extend(enrich_slang(body))
    axis2.extend(enrich_calques(body))
    axis2.extend(layer.get("axis2", []))

    axis3 = enrich_spell(slug, mech.get("spell_candidates", []))
    axis3.extend(layer.get("axis3", []))
    if not layer.get("axis3"):
        axis3 = [f for f in axis3 if re.search(r"[^а-яё\-]", f.get("quote", "").lower()) or len(f.get("quote", "")) > 12]

    axis4 = layer.get("axis4", [])

    axis5 = layer.get("axis5", [])

    if slug in ANCHOR_HIGH and not layer:
        return None

    substantive = bool(axis2 or axis3 or axis4 or axis5)
    length_note = bool(
        any(x.startswith("thin:") or x.startswith("bloated:") for x in length)
        or imb
    )
    if not substantive and not length_note:
        return None

    lit = literacy_from_flags(slug, int(metrics.get("literacy_score", 3)), len(axis2) + len(axis3) + len(axis4))
    title = slug.replace("-", " ")
    out = [f"## {slug}", f"*{title}* · литературность {lit}/5 (вторично)", ""]

    if parts:
        out.extend(parts)
        out.append("")

    if axis2:
        out.append("### Ось 2 — литературность")
        for f in axis2[:12]:
            lbl = f.get("label", "flag")
            q = f.get("quote", "")[:220]
            why = f.get("why", "")
            sug = f.get("suggest", "")
            out.append(f"- **{lbl}**: «{q}»")
            if why:
                out.append(f"  - почему: {why}")
            if sug:
                out.append(f"  - правка: {sug}")
        out.append("")

    if axis3:
        out.append("### Ось 3 — слова")
        for f in axis3[:8]:
            out.append(f"- **{f.get('label','word')}**: «{f.get('quote','')}» — {f.get('why','')}; → {f.get('suggest','—')}")
        out.append("")

    if axis4:
        out.append("### Ось 4 — странные обороты")
        for f in axis4[:8]:
            out.append(f"- «{f.get('quote','')}» — {f.get('why','')}; → {f.get('suggest','')}")
        out.append("")

    if axis5:
        out.append("### Ось 5 — английские термины (эссе)")
        for f in axis5[:6]:
            out.append(f"- {f}")
        out.append("")

    return "\n".join(out)


def build_priority(rows: list[dict], flags_count: dict[str, int]) -> str:
    lines = [
        "# Приоритеты — проход по языку",
        "",
        "Сортировка по механике + плотности флагов. Эссе без записей в `prose-flags.md` — без существенных флагов (16 из 93).",
        "",
    ]

    def top(key, n=15, reverse=True):
        sorted_rows = sorted(rows, key=lambda r: float(r.get(key, 0) or 0), reverse=reverse)
        return sorted_rows[:n]

    lines.append("## Самые рубленые (staccato_max)")
    for r in top("staccato_max"):
        lines.append(f"- `{r['slug']}` — серия {r['staccato_max']}, коротких {r['sent_short_pct']}%")
    lines.append("")

    lines.append("## Больше канцелярита (canc_count)")
    for r in top("canc_count"):
        if int(r["canc_count"]) > 0:
            lines.append(f"- `{r['slug']}` — {r['canc_count']}")
    lines.append("")

    lines.append("## Больше затычек (crutch_count)")
    for r in top("crutch_count"):
        if int(r["crutch_count"]) > 0:
            lines.append(f"- `{r['slug']}` — {r['crutch_count']}")
    lines.append("")

    lines.append("## Больше англо-токенов")
    for r in top("english_tokens"):
        if int(r["english_tokens"]) > 5:
            lines.append(f"- `{r['slug']}` — {r['english_tokens']}")
    lines.append("")

    lines.append("## Тонкие (<600 слов)")
    for r in sorted(rows, key=lambda x: int(x["words"])):
        if int(r["words"]) < 600:
            lines.append(f"- `{r['slug']}` — {r['words']} слов")
    lines.append("")

    lines.append("## Раздутые (>2500 слов)")
    for r in top("words"):
        if int(r["words"]) > 2500:
            lines.append(f"- `{r['slug']}` — {r['words']} слов")
    lines.append("")

    lines.append("## Плотность флагов (все оси)")
    for slug, n in sorted(flags_count.items(), key=lambda x: -x[1])[:20]:
        if n > 0:
            lines.append(f"- `{slug}` — {n}")
    lines.append("")

    lines.append("## Низкая литературность (вторичный балл)")
    for r in sorted(rows, key=lambda x: (int(x["literacy_score"]), -int(x.get("canc_count", 0)))):
        if int(r["literacy_score"]) <= 3:
            lines.append(f"- `{r['slug']}` — {r['literacy_score']}/5")
    return "\n".join(lines) + "\n"


def main() -> int:
    mech = json.loads(MECH.read_text(encoding="utf-8"))
    layer = load_layer()
    en_data = json.loads(EN_RAW.read_text(encoding="utf-8"))
    rows = list(csv.DictReader(METRICS.open(encoding="utf-8")))

    flag_blocks: list[str] = []
    flags_count: dict[str, int] = {}

    header = """# Prose flags — проход по языку (read-only)

Калибровка: 5/5 — antifragile, decisions-distance, oshibki-po-pravilam, bayes-four-faces, forking-paths.
Слабый край ≤3 — adtech, bayesian, clt, benford, poker-glossary.

Размеченные места: цитата · метка · почему · предложенная правка. Балл литературности вторичен.
Эссе без записей ниже — без существенных флагов.

"""
    for row in rows:
        slug = row["slug"]
        block = essay_block(slug, mech.get(slug, {}), layer.get(slug, {}), row)
        if block:
            flag_blocks.append(block)
            flags_count[slug] = block.count("**")

    OUT_FLAGS.write_text(header + "\n---\n\n".join(flag_blocks), encoding="utf-8")
    OUT_EN.write_text(build_english_table(Counter(en_data["corpus"]), en_data["by_essay"]), encoding="utf-8")
    OUT_PRIORITY.write_text(build_priority(rows, flags_count), encoding="utf-8")
    print(f"prose-flags: {len(flag_blocks)} essays with flags")
    print(f"english-terms: {OUT_EN}")
    print(f"prose-priority: {OUT_PRIORITY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
