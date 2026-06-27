#!/usr/bin/env python3
"""Anglicism + non-literary phrase detector — API judge + guardrails."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
ESSAYS = AUDIT.parent / "essays"
if str(AUDIT) not in sys.path:
    sys.path.insert(0, str(AUDIT))

from lang_judge import (
    ANCHORS,
    PROMPT_PASS_1,
    PROMPT_PASS_2,
    LangRow,
    findings_to_lang_rows,
    judge_batch_api,
    judge_batch_offline,
)
from problem_filter import anchor_tripwire, apply_filters_with_stats
from problem_find import Finding
from problem_html import parse_essay

OUT_CSV = AUDIT / "lang-findings.csv"
OUT_MD = AUDIT / "lang-weak-essays.md"
OUT_RAW = AUDIT / "_lang_raw.json"

BATCH_SIZE = 8
ANCHOR_PER_BATCH = 5


def load_all_slices() -> dict[str, str]:
    slugs = sorted(p.stem for p in ESSAYS.glob("*.html") if p.name != "index.html")
    out: dict[str, str] = {}
    for slug in slugs:
        path = ESSAYS / f"{slug}.html"
        if path.exists():
            out[slug] = parse_essay(path).prose_body
    return out


def make_batches(all_slugs: list[str]) -> list[list[str]]:
    """First batch: all anchors + filler; then rotate rest in chunks."""
    anchors = sorted(ANCHORS & set(all_slugs))
    rest = [s for s in all_slugs if s not in ANCHORS]
    batches: list[list[str]] = []
    first_fill = max(0, BATCH_SIZE - len(anchors))
    batches.append(anchors + rest[:first_fill])
    rest = rest[first_fill:]
    for i in range(0, len(rest), BATCH_SIZE):
        chunk = rest[i : i + BATCH_SIZE]
        if chunk:
            batches.append(chunk)
    return batches


def merge_filter_stats(acc: dict[str, int], part: dict[str, int]) -> None:
    for k, v in part.items():
        acc[k] = acc.get(k, 0) + v


def finding_key(f: Finding) -> tuple[str, str, str]:
    return (f.slug, f.category, f.span)


def dedupe_findings(items: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str]] = set()
    out: list[Finding] = []
    for f in items:
        k = finding_key(f)
        if k in seen:
            continue
        seen.add(k)
        out.append(f)
    return out


def run_judge(
    prose_bodies: dict[str, str],
    use_api: bool,
) -> tuple[list[Finding], list[Finding], list[Finding], list[Finding], str]:
    all_slugs = sorted(prose_bodies.keys())
    batches = make_batches(all_slugs)
    pass_a1: list[Finding] = []
    pass_a2: list[Finding] = []
    pass_b1: list[Finding] = []
    pass_b2: list[Finding] = []
    mode = "api" if use_api else "offline"

    for bi, batch in enumerate(batches):
        print(f"  batch {bi + 1}/{len(batches)}: {len(batch)} essays ({mode})")
        try:
            if use_api:
                a1, b1 = judge_batch_api(batch, prose_bodies, PROMPT_PASS_1, "a1")
                a2, b2 = judge_batch_api(batch, prose_bodies, PROMPT_PASS_2, "a2")
            else:
                a1, b1 = judge_batch_offline(batch, prose_bodies, "a1", 1)
                a2, b2 = judge_batch_offline(batch, prose_bodies, "a2", 2)
        except RuntimeError as e:
            if use_api:
                print(f"  API unavailable ({e}), falling back to offline for batch")
                a1, b1 = judge_batch_offline(batch, prose_bodies, "a1", 1)
                a2, b2 = judge_batch_offline(batch, prose_bodies, "a2", 2)
                mode = "offline-fallback"
            else:
                raise
        pass_a1.extend(a1)
        pass_a2.extend(a2)
        pass_b1.extend(b1)
        pass_b2.extend(b2)

    return (
        dedupe_findings(pass_a1),
        dedupe_findings(pass_a2),
        dedupe_findings(pass_b1),
        dedupe_findings(pass_b2),
        mode,
    )


def render_md(
    ranked: list[tuple[str, int, list[LangRow]]],
    calibration: str,
    anchor_counts: dict[str, int],
    filter_stats: dict[str, int],
    judge_mode: str,
    all_slugs: set[str],
) -> str:
    flagged_slugs = {slug for slug, n, _ in ranked if n > 0}
    clean = sorted(all_slugs - flagged_slugs)

    lines = [
        "# Lang weak essays — англицизмы + нелитературные фразы",
        "",
        f"**Калибровка:** {calibration}",
        f"**Судья:** {judge_mode} (gpt-4o-mini / offline-fallback, temperature 0, two-pass)",
        "",
        "## Фильтры (отсеянные находки)",
        "",
        f"- raw pass-1 (A+B): {filter_stats.get('raw_a', 0)}",
        f"- raw pass-2 (A+B): {filter_stats.get('raw_b', 0)}",
        f"- после two-pass intersection: {filter_stats.get('after_intersection', 0)}",
        f"- отсеяно span-verify: {filter_stats.get('dropped_span', 0)}",
        f"- отсеяно fix-nonempty: {filter_stats.get('dropped_fix', 0)}",
        f"- **выжило:** {filter_stats.get('survived', 0)}",
        "",
        "Ось A: bucket=replace only (keep/proper не в выходе).",
        "Ось B: calque · canc · agreement · neologism · rhythm.",
        "",
        f"Якоря: {', '.join(sorted(ANCHORS))}. Tripwire: >2 на якоре → MISCALIBRATED.",
        f"Якорные счётчики: {anchor_counts}",
        "",
    ]

    if calibration == "MISCALIBRATED":
        lines.append("⚠ Ранжирование отключено — разобрать калибровку перед правками.")
        lines.append("")

    for slug, count, rows in ranked:
        if count == 0:
            continue
        by_sub: dict[str, int] = defaultdict(int)
        for r in rows:
            by_sub[f"{r.axis}:{r.subtype}"] += 1
        breakdown = ", ".join(f"{k}×{v}" for k, v in sorted(by_sub.items()))
        lines.append(f"## `{slug}` · **{count}** ({breakdown})")
        lines.append("")
        for r in rows:
            label = f"{r.axis}/{r.subtype}"
            lines.append(f"- **{label}** · «{r.span}»")
            lines.append(f"  - → {r.fix}")
            if r.why:
                lines.append(f"  - why: {r.why}")
        lines.append("")

    lines.extend([
        "## Чистые",
        "",
        "0 выживших находок после фильтров.",
        "",
        ", ".join(f"`{s}`" for s in clean) or "_нет_",
        "",
    ])
    return "\n".join(lines)


def write_csv(rows: list[LangRow]) -> None:
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["essay", "axis", "subtype", "span", "ru_fix"],
        )
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x.slug, x.axis, x.span)):
            w.writerow({
                "essay": r.slug,
                "axis": r.axis,
                "subtype": r.subtype,
                "span": r.span,
                "ru_fix": r.fix,
            })


def main() -> int:
    ap = argparse.ArgumentParser(description="Anglicism + phrase detector")
    ap.add_argument("--offline", action="store_true", help="Rule-based judge (no API)")
    ap.add_argument("--slug", action="append", help="Limit to slug(s)")
    args = ap.parse_args()

    prose_bodies = load_all_slices()
    if args.slug:
        prose_bodies = {s: t for s, t in prose_bodies.items() if s in args.slug}

    use_api = not args.offline and bool(__import__("os").environ.get("OPENAI_API_KEY"))
    print(f"essays={len(prose_bodies)} judge={'api' if use_api else 'offline'}")

    pa1, pa2, pb1, pb2, judge_mode = run_judge(prose_bodies, use_api)

    # Filter axes separately then merge
    stats_a, stats_b = {}, {}
    surv_a, stats_a = apply_filters_with_stats(pa1, pa2, prose_bodies)
    surv_b, stats_b = apply_filters_with_stats(pb1, pb2, prose_bodies)
    survived = dedupe_findings(surv_a + surv_b)

    filter_stats = {
        "raw_a": stats_a.get("raw_a", 0) + stats_b.get("raw_a", 0),
        "raw_b": stats_a.get("raw_b", 0) + stats_b.get("raw_b", 0),
        "after_intersection": stats_a.get("after_intersection", 0) + stats_b.get("after_intersection", 0),
        "dropped_span": stats_a.get("dropped_span", 0) + stats_b.get("dropped_span", 0),
        "dropped_fix": stats_a.get("dropped_fix", 0) + stats_b.get("dropped_fix", 0),
        "survived": stats_a.get("survived", 0) + stats_b.get("survived", 0),
    }

    miscalibrated, anchor_counts = anchor_tripwire(survived, ANCHORS)
    calibration = "MISCALIBRATED" if miscalibrated else "OK"

    lang_rows = findings_to_lang_rows(survived)
    by_slug: dict[str, list[LangRow]] = defaultdict(list)
    for r in lang_rows:
        by_slug[r.slug].append(r)

    ranked: list[tuple[str, int, list[LangRow]]] = []
    for slug in sorted(prose_bodies.keys()):
        rows = by_slug.get(slug, [])
        ranked.append((slug, len(rows), rows))
    if calibration != "MISCALIBRATED":
        ranked.sort(key=lambda x: (-x[1], x[0]))

    OUT_RAW.write_text(
        json.dumps(
            {
                "calibration": calibration,
                "judge_mode": judge_mode,
                "filter_stats": filter_stats,
                "anchor_counts": anchor_counts,
                "pass_a1": [asdict(f) for f in pa1],
                "pass_a2": [asdict(f) for f in pa2],
                "pass_b1": [asdict(f) for f in pb1],
                "pass_b2": [asdict(f) for f in pb2],
                "survived": [asdict(f) for f in survived],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    OUT_MD.write_text(
        render_md(ranked, calibration, anchor_counts, filter_stats, judge_mode, set(prose_bodies)),
        encoding="utf-8",
    )
    write_csv(lang_rows)

    n_flagged = sum(1 for _, n, _ in ranked if n > 0)
    print(f"calibration={calibration} survived={len(survived)} flagged={n_flagged}")
    print(f"filter_stats={filter_stats}")
    print(f"wrote {OUT_MD.name}, {OUT_CSV.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
