#!/usr/bin/env python3
"""Stage 2 — localized findings (dual pass). Rule-based default; optional LLM."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import Callable

from problem_html import EssaySlice, expand_span, normalize_prose
from problem_signals import (
    CANC_RE,
    CRUTCH_RE,
    VY_TY_RE,
    bare_english_tokens,
    is_algebra_sentence,
    split_sentences,
    word_count,
)

CATEGORIES = frozenset({"calque", "register", "word", "monotone", "staccato", "transition", "math"})

REGISTER_FIX = {
    "является": "—",
    "являются": "—",
    "данный": "этот",
    "данная": "эта",
    "данное": "это",
    "данные": "эти",
    "в рамках": "в",
    "осуществляется": "делается",
    "осуществляют": "делают",
    "носит характер": "похоже на",
    "в целях": "чтобы",
    "посредством": "через",
    "ввиду того что": "потому что",
}

CALQUE_RU = {
    "feedback": "обратная связь",
    "default": "значение по умолчанию",
    "pipeline": "конвейер",
    "framework": "каркас",
    "benchmark": "эталон",
    "baseline": "базовый уровень",
    "runtime": "время выполнения",
    "workflow": "рабочий процесс",
    "leverage": "рычаг",
    "hedge": "хедж",
    "upside": "апсайд",
    "downside": "даунсайд",
    "stakeholder": "заинтересованная сторона",
    "inventory": "инвентарь",
    "retention": "удержание",
    "revenue": "выручка",
    "tension": "напряжение",
    "threshold": "порог",
    "optimization": "оптимизация",
    "precision": "точность",
    "conversion": "конверсия",
    "awareness": "узнаваемость",
    "frequency": "частота",
    "programmatic": "программатик",
    "marketplace": "маркетплейс",
    "guaranteed": "гарантированный",
    "reach": "охват",
    "load": "нагрузка",
    "effect": "эффект",
    "seed": "зерно",
    "random": "случайный",
    "resulting": "итоговый",
}


@dataclass
class Finding:
    slug: str
    span: str
    category: str
    why: str
    fix: str
    pass_id: str  # "a" | "b"


def _sentence_starts(sentences: list[str]) -> list[tuple[str, list[str]]]:
    runs: list[tuple[str, list[str]]] = []
    cur: list[str] = []
    cur_start = ""
    for s in sentences:
        words = re.findall(r"[а-яёa-z]+", s.lower())
        st = " ".join(words[:2]) if words else ""
        if st and st == cur_start:
            cur.append(s)
        else:
            if len(cur) >= 3:
                runs.append((cur_start, cur))
            cur = [s]
            cur_start = st
    if len(cur) >= 3:
        runs.append((cur_start, cur))
    return runs


def _staccato_runs(sentences: list[str], min_run: int) -> list[str]:
    spans: list[str] = []
    cur: list[str] = []
    for s in sentences:
        if word_count(s) < 5 and not is_algebra_sentence(s):
            cur.append(s)
        else:
            if len(cur) >= min_run:
                spans.append(normalize_prose(" ".join(cur)))
            cur = []
    if len(cur) >= min_run:
        spans.append(normalize_prose(" ".join(cur)))
    return spans


def _register_findings(slug: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in CANC_RE.finditer(text):
        span = expand_span(text, m.start(), m.end())
        if span not in text and span not in {f.span for f in out}:
            continue
        word = m.group(1).lower()
        fix_word = REGISTER_FIX.get(word, "")
        fix = span.replace(m.group(0), fix_word).strip() if fix_word else re.sub(
            re.escape(m.group(0)), "", span, count=1, flags=re.I
        ).strip()
        fix = re.sub(r"\s+", " ", fix).strip(" —")
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="register",
                why=f"канцелярит «{m.group(0)}»",
                fix=fix or span + " [убрать канцелярит]",
                pass_id="",
            )
        )
    return out


def _calque_findings(slug: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    for tok in bare_english_tokens(slug, text):
        for m in re.finditer(re.escape(tok), text):
            span = expand_span(text, m.start(), m.end())
            ru = CALQUE_RU.get(tok.lower(), f"«{tok}» → русский эквивалент")
            fix = span.replace(tok, ru) if tok in span else span + f" → {ru}"
            out.append(
                Finding(
                    slug=slug,
                    span=span,
                    category="calque",
                    why=f"голое EN «{tok}»",
                    fix=fix,
                    pass_id="",
                )
            )
            break
    return out


def _word_findings(slug: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in CRUTCH_RE.finditer(text):
        span = expand_span(text, m.start(), m.end())
        fix = re.sub(re.escape(m.group(0)), "", span, count=1, flags=re.I)
        fix = re.sub(r"\s+", " ", fix).strip(" ,—")
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="word",
                why=f"затычка «{m.group(0)}»",
                fix=fix or span.replace(m.group(0), "").strip(),
                pass_id="",
            )
        )
    return out


def _transition_findings(slug: str, text: str) -> list[Finding]:
    trans = re.compile(
        r"\b(и вот|а теперь|таким образом|в итоге|с другой стороны|во-первых|во-вторых)\b",
        re.I,
    )
    out: list[Finding] = []
    counts: dict[str, int] = {}
    for m in trans.finditer(text):
        counts[m.group(0).lower()] = counts.get(m.group(0).lower(), 0) + 1
    for m in trans.finditer(text):
        if counts[m.group(0).lower()] < 2:
            continue
        span = expand_span(text, m.start(), m.end())
        fix = re.sub(re.escape(m.group(0)), "", span, count=1, flags=re.I)
        fix = re.sub(r"\s+", " ", fix).strip()
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="transition",
                why=f"частый переход «{m.group(0)}»",
                fix=fix or span,
                pass_id="",
            )
        )
        break
    return out


def _staccato_findings(slug: str, text: str, min_run: int) -> list[Finding]:
    sents = [s for s in split_sentences(text) if not is_algebra_sentence(s)]
    out: list[Finding] = []
    for span in _staccato_runs(sents, min_run):
        if span not in text:
            continue
        merged = normalize_prose(
            span.replace(". ", ", ").rstrip(".") + "."
        )
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="staccato",
                why=f"серия коротких предложений (<5 слов, ≥{min_run})",
                fix=merged,
                pass_id="",
            )
        )
    return out


def _monotone_findings(slug: str, text: str) -> list[Finding]:
    sents = split_sentences(text)
    out: list[Finding] = []
    for pattern, group in _sentence_starts(sents):
        span = normalize_prose(group[0])
        if span not in text:
            span = group[0]
        fix = normalize_prose(
            group[1] if len(group) > 1 else group[0]
        )
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="monotone",
                why=f"монотонный зачин «{pattern}…» ×{len(group)}",
                fix=fix,
                pass_id="",
            )
        )
    return out


def _vy_ty_findings(slug: str, text: str) -> list[Finding]:
    if not re.search(r"(?<![а-яё])ты(?![а-яё])", text, re.I):
        return []
    out: list[Finding] = []
    for m in VY_TY_RE.finditer(text):
        span = expand_span(text, m.start(), m.end())
        repl = {
            "вы": "ты", "вам": "тебе", "вас": "тебя", "ваш": "твой", "ваша": "твоя",
            "ваше": "твоё", "ваши": "твои", "возьмите": "возьми", "посмотрите": "посмотри",
            "откройте": "открой", "представьте": "представь", "запомните": "запомни",
            "сделайте": "сделай", "нажмите": "нажми",
        }
        w = m.group(0).lower()
        fix = span.replace(m.group(0), repl.get(w, "ты"), 1)
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="register",
                why=f"«ты»-эссе, но «{m.group(0)}»",
                fix=fix,
                pass_id="",
            )
        )
    return out


def _math_findings(slug: str, text: str) -> list[Finding]:
    from math_check import dedupe_mismatches, run_checks

    mm, _ = run_checks(slug, text)
    out: list[Finding] = []
    for it in dedupe_mismatches(mm):
        quote = it.quote.strip()
        span = quote if quote in text else ""
        if not span:
            for m in re.finditer(re.escape(it.stated[:20]), text):
                span = expand_span(text, m.start(), m.end())
                break
        if not span or span not in text:
            pos = text.find(it.stated.split()[0][:8]) if it.stated else -1
            if pos >= 0:
                span = expand_span(text, pos, pos + len(it.stated))
        if not span:
            continue
        fix = span.replace(it.stated, it.computed) if it.stated in span else f"{span} → {it.computed}"
        out.append(
            Finding(
                slug=slug,
                span=span,
                category="math",
                why=it.note,
                fix=fix,
                pass_id="",
            )
        )
    return out


def _dedupe_findings(items: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, str]] = set()
    out: list[Finding] = []
    for f in items:
        key = (f.category, f.span)
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def pass_a_findings(slug: str, slice_: EssaySlice) -> list[Finding]:
    """Pass A — register, wording, calque, math."""
    text = slice_.prose_body
    items: list[Finding] = []
    items.extend(_math_findings(slug, text))
    items.extend(_register_findings(slug, text))
    items.extend(_vy_ty_findings(slug, text))
    items.extend(_calque_findings(slug, text))
    items.extend(_word_findings(slug, text))
    for f in items:
        f.pass_id = "a"
    return _dedupe_findings(items)


def pass_b_findings(slug: str, slice_: EssaySlice) -> list[Finding]:
    """Pass B — rhythm, transitions, staccato (stricter run threshold)."""
    text = slice_.prose_body
    items: list[Finding] = []
    items.extend(_math_findings(slug, text))
    items.extend(_staccato_findings(slug, text, min_run=4))
    items.extend(_monotone_findings(slug, text))
    items.extend(_transition_findings(slug, text))
    items.extend(_word_findings(slug, text))
    for f in items:
        f.pass_id = "b"
    return _dedupe_findings(items)


PROMPT_A = """Ты редактор русскоязычных эссе. Прочитай prose_body и верни JSON-массив находок.
Каждая запись: {{"span": "<дословный кусок из текста>", "category": "<calque|register|word>",
"why": "<кратко>", "fix": "<переписанный кусок>"}}.
Ищи: канцелярит, кальки, неудачные слова. span — точная подстрока prose_body. Только JSON."""

PROMPT_B = """Ты редактор ритма прозы. Прочитай prose_body и верни JSON-массив находок.
Каждая запись: {{"span": "<дословный кусок>", "category": "<monotone|staccato|transition>",
"why": "<кратко>", "fix": "<переписанный кусок>"}}.
Ищи: рубку, монотонные зачины, слабые переходы. Не трогай формулы. span — точная подстрока. Только JSON."""


def _openai_findings(slug: str, prose: str, prompt: str, pass_id: str) -> list[Finding]:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return []
    body = json.dumps(
        {
            "model": os.environ.get("PROBLEM_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"slug: {slug}\n\nprose_body:\n{prose[:12000]}"},
            ],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\[[\s\S]*\]", content)
        if not m:
            return []
        raw = json.loads(m.group(0))
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError):
        return []
    out: list[Finding] = []
    for row in raw:
        cat = row.get("category", "")
        if cat not in CATEGORIES:
            continue
        out.append(
            Finding(
                slug=slug,
                span=row.get("span", ""),
                category=cat,
                why=row.get("why", ""),
                fix=row.get("fix", ""),
                pass_id=pass_id,
            )
        )
    return out


def run_dual_pass(
    slug: str,
    slice_: EssaySlice,
    use_llm: bool = False,
) -> tuple[list[Finding], list[Finding]]:
    if use_llm and os.environ.get("OPENAI_API_KEY"):
        a = _openai_findings(slug, slice_.prose_body, PROMPT_A, "a")
        b = _openai_findings(slug, slice_.prose_body, PROMPT_B, "b")
        if a or b:
            return a, b
    return pass_a_findings(slug, slice_), pass_b_findings(slug, slice_)


def findings_to_json(findings: list[Finding]) -> list[dict]:
    return [asdict(f) for f in findings]
