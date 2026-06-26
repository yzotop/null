#!/usr/bin/env python3
"""Merge Layer B into CSV; generate flags, priority, repeats."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
ROOT = AUDIT.parent
CSV_IN = AUDIT / "essays-metrics.csv"
CSV_OUT = AUDIT / "essays-metrics.csv"
TEXTS = AUDIT / "_texts"
FLAGS = AUDIT / "essays-flags.md"
PRIORITY = AUDIT / "priority.md"
REPEATS = AUDIT / "repeats.md"
LAYER_B_DIR = AUDIT / "layer_b"


def normalize_field(val) -> str:
    if val is None or val == "":
        return ""
    if isinstance(val, list):
        return " | ".join(str(x) for x in val)
    return str(val).strip()


def load_layer_b() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(LAYER_B_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for row in data:
                out[row["slug"]] = row
    return out


def has_flags(row: dict) -> bool:
    checks = [
        row.get("factcheck_flags"),
        row.get("weird_phrasings"),
        row.get("grammar"),
        row.get("flag_footnotes") == "yes",
        int(row.get("broken_links_count") or 0) > 0,
        int(row.get("typo_total") or 0) > 0,
        row.get("actuality_refs"),
        row.get("lowercase_headings_ok") == "no",
        int(row.get("footnotes_without_source") or 0) > 0,
        row.get("flag_readtime") == "yes",
    ]
    return any(c for c in checks if c)


def ngrams(text: str, n: int) -> list[str]:
    words = re.findall(r"[а-яёa-z]+", text.lower())
    if len(words) < n:
        return []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def build_repeats(rows: list[dict]) -> str:
    gram_counts: Counter[str] = Counter()
    gram_essays: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        p = TEXTS / f"{row['slug']}.txt"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for n in (3, 4):
            for g in ngrams(text, n):
                if len(g) < 12:
                    continue
                gram_counts[g] += 1
                gram_essays[g].add(row["slug"])
    shared = [(g, len(gram_essays[g]), sorted(gram_essays[g])) for g, c in gram_counts.items() if len(gram_essays[g]) >= 5]
    shared.sort(key=lambda x: (-x[1], -len(x[0])))

    motifs = {
        "на дистанции", "дверь в одну", "двери в одну", "дверь в две",
        "шкура на кону", "skin in the", "чёрный лебедь", "черный лебедь",
        "матожидание", "на полях", "via negativa", "опциональность",
        "обратимость", "resulting", "базовая частота", "не знаешь будущего",
    }
    motif_hits: list[tuple] = []
    cliche_hits: list[tuple] = []
    transition_starts = ("итого", "практический вывод", "главное", "вывод простой", "сложим всё", "заметь")

    for g, cnt, slugs in shared[:80]:
        is_motif = any(m in g for m in motifs)
        is_cliche = any(g.startswith(t) for t in transition_starts) or g in {
            "в реальности это", "на практике это", "это не баг", "это значит что",
            "если ты не", "если вы не", "вопрос не в", "дело не в",
        }
        entry = (g, cnt, slugs[:8])
        if is_motif:
            motif_hits.append(entry)
        elif is_cliche:
            cliche_hits.append(entry)

    lines = [
        "# Межэссейные повторы (3–4-граммы в ≥5 эссе)",
        "",
        f"Проанализировано {len(rows)} эссе, тексты из `audit/_texts/`.",
        "",
        "## Намеренные мотивы (сквозные образы серии)",
        "",
    ]
    if motif_hits:
        for g, cnt, slugs in motif_hits[:25]:
            lines.append(f"- **«{g}»** — {cnt} эссе: {', '.join(slugs)}")
    else:
        manual: dict[str, list[str]] = defaultdict(list)
        motif_keys = (
            "на дистанции", "дверь в одну", "шкура на кону", "чёрный лебедь",
            "черный лебедь", "via negativa", "опциональность", "resulting",
        )
        for row in rows:
            p = TEXTS / f"{row['slug']}.txt"
            if not p.exists():
                continue
            t = p.read_text(encoding="utf-8").lower()
            for m in motif_keys:
                if m in t:
                    manual[m].append(row["slug"])
        for m, sl in sorted(manual.items(), key=lambda x: -len(x[1])):
            if len(sl) >= 3:
                lines.append(f"- **«{m}»** — {len(sl)} эссе: {', '.join(sl[:10])}")

    lines += ["", "## Клише / переходы (кандидаты на сокращение)", ""]
    if cliche_hits:
        for g, cnt, slugs in cliche_hits[:20]:
            lines.append(f"- «{g}» — {cnt} эссе: {', '.join(slugs)}")
    else:
        for g, cnt, slugs in shared[:15]:
            if cnt >= 6:
                lines.append(f"- «{g}» — {cnt} эссе: {', '.join(slugs[:6])}")

    lines += [
        "",
        "## Топ-20 4-грамм по охвату",
        "",
    ]
    four = [(g, len(gram_essays[g]), sorted(gram_essays[g])) for g in gram_counts if len(g.split()) == 4 and len(gram_essays[g]) >= 5]
    four.sort(key=lambda x: -x[1])
    for g, cnt, slugs in four[:20]:
        lines.append(f"- «{g}» — {cnt}: {', '.join(slugs[:6])}{'…' if len(slugs)>6 else ''}")

    return "\n".join(lines) + "\n"


def main():
    layer_b = load_layer_b()
    rows = list(csv.DictReader(CSV_IN.open(encoding="utf-8")))
    fieldnames = rows[0].keys() if rows else []

    for row in rows:
        b = layer_b.get(row["slug"], {})
        for k in ("literacy", "material", "actuality", "literacy_note", "material_note",
                  "actuality_note", "actuality_refs", "weird_phrasings", "factcheck_flags", "grammar"):
            if k in b:
                row[k] = normalize_field(b[k])

    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # flags.md
    flag_lines = ["# Флаги по эссе (только где есть что чинить)", ""]
    for row in sorted(rows, key=lambda r: r["slug"]):
        if not has_flags(row):
            continue
        flag_lines.append(f"## {row['slug']} — {row['title']}")
        flag_lines.append(f"§{row['category_sec']} · {row['date']} · L{row.get('literacy','')}/M{row.get('material','')}/A{row.get('actuality','')}")
        flag_lines.append("")
        if row.get("flag_readtime") == "yes":
            flag_lines.append(f"- **время чтения:** calc {row['read_min_calc']} vs declared {row['read_min_declared']}")
        if row.get("flag_footnotes") == "yes":
            flag_lines.append(f"- **сноски:** markers {row['footnote_markers']} ≠ defs {row['footnote_defs']}")
        if int(row.get("footnotes_without_source") or 0):
            flag_lines.append(f"- **сноски без источника:** {row['footnotes_without_source']}")
        if row.get("lowercase_headings_ok") == "no":
            flag_lines.append(f"- **заголовки:** {row['lowercase_violations']}")
        if int(row.get("broken_links_count") or 0):
            flag_lines.append(f"- **битые ссылки:** {row['broken_links']}")
        if int(row.get("typo_total") or 0):
            flag_lines.append(f"- **типографика:** straight\"={row['typo_straight_double']} straight'={row['typo_straight_single']} hyphen={row['typo_hyphen_em']} dblsp={row['typo_double_space']} ...={row['typo_three_dots']}")
        if row.get("actuality_refs"):
            flag_lines.append(f"- **протухающие отсылки:** {row['actuality_refs']}")
        if row.get("factcheck_flags"):
            flag_lines.append(f"- **фактчек:** {row['factcheck_flags']}")
        if row.get("weird_phrasings"):
            flag_lines.append(f"- **обороты:** {row['weird_phrasings']}")
        if row.get("grammar"):
            flag_lines.append(f"- **грамматика:** {row['grammar']}")
        flag_lines.append("")

    FLAGS.write_text("\n".join(flag_lines), encoding="utf-8")

    # priority.md
    def score_int(r, k):
        try:
            return int(r.get(k) or 99)
        except ValueError:
            return 99

    def fc_count(r):
        return len([x for x in (r.get("factcheck_flags") or "").split("|") if x.strip()])

    pri = [
        "# Приоритеты разбора",
        "",
        f"Корпус: **{len(rows)}** эссе. CURSOR-context.md не найден; категории из `essays/index.html`, граф из `data/links.json`.",
        "",
        "## Литературность ≤ 2",
        "",
    ]
    low_lit = [r for r in rows if score_int(r, "literacy") <= 2]
    pri.append("_(нет)_" if not low_lit else "\n".join(f"- **{r['slug']}** ({r['literacy']}) — {r.get('literacy_note','')}" for r in sorted(low_lit, key=lambda x: score_int(x, "literacy"))))

    pri += ["", "## Материал ≤ 2", ""]
    low_mat = [r for r in rows if score_int(r, "material") <= 2]
    pri.append("_(нет)_" if not low_mat else "\n".join(f"- **{r['slug']}** ({r['material']}) — {r.get('material_note','')}" for r in sorted(low_mat, key=lambda x: score_int(x, "material"))))

    pri += ["", "## Больше всего фактчек-флагов", ""]
    for r in sorted(rows, key=fc_count, reverse=True)[:15]:
        if fc_count(r):
            pri.append(f"- **{r['slug']}** ({fc_count(r)})")

    pri += ["", "## Рассинхрон времени чтения (|calc−decl| > 4 мин)", ""]
    for r in sorted(rows, key=lambda x: abs(int(x.get("read_min_calc") or 0) - int(x.get("read_min_declared") or 0) if x.get("read_min_declared") else 0), reverse=True):
        if r.get("flag_readtime") == "yes":
            pri.append(f"- **{r['slug']}** — calc {r['read_min_calc']} vs declared {r['read_min_declared']}")

    pri += ["", "## Англицизмы-кандидаты (топ по eng_candidates_count)", ""]
    for r in sorted(rows, key=lambda x: int(x.get("eng_candidates_count") or 0), reverse=True)[:15]:
        if int(r.get("eng_candidates_count") or 0):
            pri.append(f"- **{r['slug']}** ({r['eng_candidates_count']}): {r.get('eng_candidates','')[:120]}")

    pri += ["", "## Сноски без источника", ""]
    for r in sorted(rows, key=lambda x: int(x.get("footnotes_without_source") or 0), reverse=True):
        if int(r.get("footnotes_without_source") or 0):
            pri.append(f"- **{r['slug']}** — {r['footnotes_without_source']}")

    pri += ["", "## Самые старые даты (ревизия актуальности)", ""]
    dated = [r for r in rows if r.get("date")]
    for r in sorted(dated, key=lambda x: x["date"])[:15]:
        pri.append(f"- **{r['slug']}** — {r['date']}")

    pri += ["", "## Самые короткие (< 600 слов)", ""]
    for r in sorted(rows, key=lambda x: int(x.get("words") or 0))[:10]:
        if int(r["words"]) < 600:
            pri.append(f"- **{r['slug']}** — {r['words']} слов")

    pri += ["", "## Самые длинные (> 3500 слов)", ""]
    long = [r for r in rows if int(r.get("words") or 0) > 3500]
    pri.append("_(нет)_" if not long else "\n".join(f"- **{r['slug']}** — {r['words']} слов" for r in sorted(long, key=lambda x: -int(x["words"]))))

    pri += ["", "## Актуальность ≤ 3 (датированные отсылки)", ""]
    for r in sorted(rows, key=lambda x: score_int(x, "actuality")):
        if score_int(r, "actuality") <= 3:
            pri.append(f"- **{r['slug']}** ({r['actuality']}) — {r.get('actuality_refs','')[:100]}")

    PRIORITY.write_text("\n".join(pri) + "\n", encoding="utf-8")
    REPEATS.write_text(build_repeats(rows), encoding="utf-8")
    print(f"merged {len(layer_b)} layer B rows into {CSV_OUT}")
    print(f"wrote {FLAGS.name}, {PRIORITY.name}, {REPEATS.name}")


if __name__ == "__main__":
    main()
