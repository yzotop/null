#!/usr/bin/env python3
"""Stage 3 — filter localized findings."""
from __future__ import annotations

import re

from problem_find import Finding

VAGUE_FIX = re.compile(
    r"^(переформулировать|упростить|переписать|сократить|улучшить)",
    re.I,
)

ANCHOR_TRIPWIRE = 2


def spans_overlap(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa or not wb:
        return False
    inter = len(wa & wb)
    return inter / min(len(wa), len(wb)) >= 0.55


def span_verify(f: Finding, prose: str) -> bool:
    return bool(f.span) and f.span in prose


def fix_nonempty(f: Finding) -> bool:
    fix = (f.fix or "").strip()
    span = (f.span or "").strip()
    if not fix or fix == span:
        return False
    if VAGUE_FIX.match(fix):
        return False
    if fix.lower() in {"переформулировать проще", "переформулировать", "упростить"}:
        return False
    return True


def two_pass_survivors(pass_a: list[Finding], pass_b: list[Finding]) -> list[Finding]:
    """Keep findings whose span overlaps with a finding from the other pass."""
    survivors: list[Finding] = []
    for fa in pass_a:
        for fb in pass_b:
            if fa.slug != fb.slug:
                continue
            if spans_overlap(fa.span, fb.span):
                merged = Finding(
                    slug=fa.slug,
                    span=fa.span if len(fa.span) >= len(fb.span) else fb.span,
                    category=fa.category if fa.category != "math" else fb.category,
                    why=fa.why or fb.why,
                    fix=fa.fix if fa.fix != fa.span else fb.fix,
                    pass_id="both",
                )
                if merged.category == "math" or fa.category == "math":
                    merged.category = "math"
                survivors.append(merged)
                break
    return survivors


def apply_filters(
    pass_a: list[Finding],
    pass_b: list[Finding],
    prose_bodies: dict[str, str],
) -> list[Finding]:
    merged = two_pass_survivors(pass_a, pass_b)
    out: list[Finding] = []
    seen: set[tuple[str, str, str]] = set()
    for f in merged:
        prose = prose_bodies.get(f.slug, "")
        if not span_verify(f, prose):
            continue
        if not fix_nonempty(f):
            continue
        key = (f.slug, f.category, f.span)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def anchor_tripwire(
    findings: list[Finding],
    anchors: set[str],
    limit: int = ANCHOR_TRIPWIRE,
) -> tuple[bool, dict[str, int]]:
    counts: dict[str, int] = {a: 0 for a in anchors}
    for f in findings:
        if f.slug in counts:
            counts[f.slug] += 1
    miscalibrated = any(n > limit for n in counts.values())
    return miscalibrated, counts
