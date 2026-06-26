#!/usr/bin/env python3
"""Located-findings detector — stages 0–4. Read-only; writes audit/ only."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
ESSAYS = AUDIT.parent / "essays"
if str(AUDIT) not in sys.path:
    sys.path.insert(0, str(AUDIT))

from problem_filter import anchor_tripwire, apply_filters
from problem_find import Finding, run_dual_pass
from problem_html import parse_essay
from problem_signals import ANCHORS, collect_candidates

OUT_MD = AUDIT / "problem-essays.md"
OUT_CSV = AUDIT / "problem-findings.csv"
OUT_RAW = AUDIT / "_problem_raw.json"

CATEGORY_WEIGHTS = {
    "math": 5,
    "register": 3,
    "word": 2,
    "calque": 2,
    "staccato": 2,
    "monotone": 1,
    "transition": 1,
}


def triage_score(findings: list[Finding], det_bonus: int) -> int:
    return sum(CATEGORY_WEIGHTS.get(f.category, 0) for f in findings) + det_bonus


def rank_essays(
    findings_by_slug: dict[str, list[Finding]],
    signals_map: dict,
    all_slugs: set[str],
    miscalibrated: bool,
) -> list[tuple[str, int, list[Finding], int]]:
    rows: list[tuple[str, int, list[Finding], int]] = []
    for slug in all_slugs:
        findings = findings_by_slug.get(slug, [])
        det = signals_map[slug].det_bonus if slug in signals_map else 0
        score = triage_score(findings, det)
        rows.append((slug, score, findings, det))
    if miscalibrated:
        return sorted(rows, key=lambda x: x[0])
    return sorted(rows, key=lambda x: (-x[1], x[0]))


def render_md(
    ranked: list[tuple[str, int, list[Finding], int]],
    calibration: str,
    anchor_counts: dict[str, int],
    candidate_count: int,
    excluded: list[str],
) -> str:
    lines = [
        "# Problem essays — локализованные находки",
        "",
        f"**Калибровка:** {calibration}",
        "",
        "Пороги: staccato ≥4 при short≥40% или run≥5; section>50%; readtime ±4 мин;",
        "footnotes markers≠defs; length <600 или >2500 слов; vy/ты; bare EN; math-recompute.",
        "",
        "Ранжирование: math 5 · register 3 · word 2 · calque 2 · staccato 2 ·",
        "monotone 1 · transition 1 · (+ детерминированные длина/диспропорция 1).",
        "",
        "Исключено из прозового прохода: literacy_score, canc_count (голый), hunspell,",
        "factual-worklist (отдельный пул), холистический prose-flags.",
        "",
        f"Кандидатов (сигнал ≥1 + якоря): {candidate_count}. Якоря: {', '.join(sorted(ANCHORS))}.",
        "",
    ]
    if calibration == "MISCALIBRATED":
        lines.append(
            f"⚠ Якорный tripwire: >2 находок на якоре — {anchor_counts}. Ранжирование отключено."
        )
        lines.append("")

    flagged = [r for r in ranked if r[2]]
    clean = [r[0] for r in ranked if not r[2]]

    for slug, score, findings, det in flagged:
        if not findings:
            continue
        det_note = f"; det+{det}" if det else ""
        lines.append(f"## `{slug}` · **{score}**{det_note}")
        lines.append("")
        for f in findings:
            lines.append(f"- **{f.category}** · «{f.span}»")
            lines.append(f"  - fix: {f.fix}")
            lines.append(f"  - why: {f.why}")
        lines.append(
            "- **вердикт (чтение):** _____ · **статус:** _____"
        )
        lines.append("")

    lines.extend([
        "## Чистые",
        "",
        "0 выживших находок после фильтров (попадание в factual-worklist не учитывается).",
        "",
        ", ".join(f"`{s}`" for s in clean) or "_нет_",
        "",
    ])
    return "\n".join(lines)


def write_csv(findings_by_slug: dict[str, list[Finding]]) -> None:
    rows: list[dict[str, str]] = []
    for slug in sorted(findings_by_slug):
        for f in findings_by_slug[slug]:
            rows.append({
                "essay": slug,
                "category": f.category,
                "span": f.span,
                "fix": f.fix,
            })
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["essay", "category", "span", "fix"])
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Located-findings detector")
    ap.add_argument("--llm", action="store_true", help="Use OpenAI for stage 2 (needs OPENAI_API_KEY)")
    ap.add_argument("--slug", action="append", help="Limit to slug(s)")
    args = ap.parse_args()

    slugs = args.slug if args.slug else None
    slices, signals, candidates = collect_candidates(slugs)
    all_slugs = set(slices.keys())
    prose_bodies = {s: sl.prose_body for s, sl in slices.items()}

    pass_a_all: list[Finding] = []
    pass_b_all: list[Finding] = []

    for slug in candidates:
        if slug not in slices:
            continue
        a, b = run_dual_pass(slug, slices[slug], use_llm=args.llm)
        pass_a_all.extend(a)
        pass_b_all.extend(b)

    survived = apply_filters(pass_a_all, pass_b_all, prose_bodies)
    miscalibrated, anchor_counts = anchor_tripwire(survived, ANCHORS)
    calibration = "MISCALIBRATED" if miscalibrated else "OK"

    findings_by_slug: dict[str, list[Finding]] = {}
    for f in survived:
        findings_by_slug.setdefault(f.slug, []).append(f)

    ranked = rank_essays(findings_by_slug, signals, all_slugs, miscalibrated)

    OUT_RAW.write_text(
        json.dumps(
            {
                "calibration": calibration,
                "anchor_counts": anchor_counts,
                "candidates": candidates,
                "pass_a": [asdict(f) for f in pass_a_all],
                "pass_b": [asdict(f) for f in pass_b_all],
                "survived": [asdict(f) for f in survived],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    OUT_MD.write_text(
        render_md(
            ranked,
            calibration,
            anchor_counts,
            len(candidates),
            excluded=[
                "literacy_score",
                "canc_count",
                "hunspell",
                "factual-worklist",
                "prose-flags holistic",
            ],
        ),
        encoding="utf-8",
    )
    write_csv(findings_by_slug)

    n_flagged = sum(1 for _, _, f, _ in ranked if f)
    print(f"calibration={calibration} candidates={len(candidates)} survived={len(survived)} flagged={n_flagged}")
    print(f"anchor_counts={anchor_counts}")
    print(f"wrote {OUT_MD.name}, {OUT_CSV.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
