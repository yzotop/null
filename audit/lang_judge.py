#!/usr/bin/env python3
"""API / offline judge for anglicisms (axis A) and non-literary phrases (axis B)."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from problem_find import Finding
from problem_html import expand_span, normalize_prose
from problem_signals import bare_english_tokens

ANCHORS = frozenset({
    "antifragile",
    "bayes-four-faces",
    "decisions-distance",
    "forking-paths",
    "oshibki-po-pravilam",
})

B_SUBTYPES = frozenset({"calque", "canc", "agreement", "neologism", "rhythm"})

# Offline: без «данные» (часто = data, не канцелярит)
CANC_OFFLINE = re.compile(
    r"\b(является|являются|данный|данная|данное|осуществляется|осуществляют|"
    r"в рамках|носит характер|является основой|в целях|посредством|ввиду того что)\b",
    re.I,
)

CALQUE_RU = {
    "revenue": "выручка",
    "retention": "удержание",
    "inventory": "инвентарь",
    "tension": "напряжение",
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
    "game": "игра",
    "value": "ценность",
    "line": "линия",
}

REGISTER_FIX = {
    "является": "",
    "являются": "",
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

PROMPT_PASS_1 = """Ты лингвистический аудитор русскоязычных эссе. Для КАЖДОГО эссе ниже анализируй только prose_body.

Верни JSON: {"essays": {"<slug>": {"anglicisms": [...], "phrases": [...]}}}

## Ось A — anglicisms
Для каждого латинского вкрапления:
{"term": "...", "span": "<дословная фраза-носитель из prose_body>", "bucket": "keep|proper|replace", "ru": "<русская замена, только если replace>"}

Корзины:
- keep: устоявшийся термин без русского обихода (self-play, MCMC, p-value, GTO, EV, Bayes, Kelly, PageRank, fat tails как термин после якоря)
- proper: имя, аббревиатура, код, нотация, не-английское (Taleb, Google, DSP, xG)
- replace: ГОЛОЕ обиходное слово с естественным русским (revenue→выручка, retention→удержание, value→ценность, game→игра, fat tails→толстые хвосты без скобок)

В массив anglicisms включай ТОЛЬКО bucket=replace.

## Ось B — phrases
{"span": "<дословная фраза из prose_body>", "subtype": "calque|canc|agreement|neologism|rhythm", "why": "<≤12 слов>", "fix": "<переписанная фраза>"}

Подкатегории: calque (калька), canc (канцелярит), agreement (согласование), neologism (неологизм), rhythm (сломанный ритм/обрыв без приёма).

Запреты: без «звучит слабо», баллов, холистики. Нет дословного span — нет записи. fix должен отличаться от span.

Только JSON, без markdown."""

PROMPT_PASS_2 = """Ты строгий редактор русской прозы. Повторный проход — другой угол зрения.

Для каждого эссе (prose_body) верни JSON: {"essays": {"<slug>": {"anglicisms": [...], "phrases": [...]}}}

Ось A: найди англицизмы, которые можно заменить русским без потери смысла. Формат:
{"term", "span" (дословно из текста), "bucket": "replace", "ru"}
Не включай keep/proper — только replace-кандидаты с готовой русской заменой.

Ось B: только конкретные нелитературные фразы с цитатой:
{"span", "subtype": calque|canc|agreement|neologism|rhythm, "why" (≤12 слов), "fix"}
Никаких общих замечаний. fix ≠ span.

span обязан быть точной подстрокой prose_body. Только JSON."""


@dataclass
class LangRow:
    slug: str
    axis: str
    subtype: str
    span: str
    fix: str
    why: str = ""
    term: str = ""


def _openai_chat(prompt: str, user: str) -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    body = json.dumps(
        {
            "model": os.environ.get("LANG_MODEL", "gpt-4o-mini"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ],
        },
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def _parse_batch(raw: str) -> dict[str, dict]:
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    data = json.loads(m.group(0))
    essays = data.get("essays") or data
    if not isinstance(essays, dict):
        return {}
    return essays


def _a_to_finding(slug: str, row: dict, pass_id: str) -> Finding | None:
    bucket = (row.get("bucket") or "").lower()
    if bucket != "replace":
        return None
    span = normalize_prose(row.get("span") or "")
    term = (row.get("term") or "").strip()
    ru = (row.get("ru") or "").strip()
    if not span or not term or not ru:
        return None
    fix = span.replace(term, ru) if term in span else ru
    if fix == span:
        return None
    return Finding(
        slug=slug,
        span=span,
        category="A:replace",
        why=term,
        fix=fix,
        pass_id=pass_id,
    )


def _b_to_finding(slug: str, row: dict, pass_id: str) -> Finding | None:
    span = normalize_prose(row.get("span") or "")
    subtype = (row.get("subtype") or "").lower()
    fix = normalize_prose(row.get("fix") or "")
    why = (row.get("why") or "").strip()
    if subtype not in B_SUBTYPES or not span or not fix:
        return None
    return Finding(
        slug=slug,
        span=span,
        category=f"B:{subtype}",
        why=why,
        fix=fix,
        pass_id=pass_id,
    )


def batch_to_findings(batch: dict[str, dict], pass_id: str) -> tuple[list[Finding], list[Finding]]:
    a_out: list[Finding] = []
    b_out: list[Finding] = []
    for slug, payload in batch.items():
        for row in payload.get("anglicisms") or []:
            f = _a_to_finding(slug, row, pass_id)
            if f:
                a_out.append(f)
        for row in payload.get("phrases") or []:
            f = _b_to_finding(slug, row, pass_id)
            if f:
                b_out.append(f)
    return a_out, b_out


def format_batch_input(slugs: list[str], prose_bodies: dict[str, str], max_chars: int = 9000) -> str:
    parts = []
    for slug in slugs:
        prose = prose_bodies.get(slug, "")
        if len(prose) > max_chars:
            prose = prose[: max_chars - 20] + "…[truncated]"
        parts.append(f"### {slug}\nprose_body:\n{prose}\n")
    return "\n".join(parts)


def judge_batch_api(
    slugs: list[str],
    prose_bodies: dict[str, str],
    prompt: str,
    pass_id: str,
) -> tuple[list[Finding], list[Finding]]:
    user = format_batch_input(slugs, prose_bodies)
    raw = _openai_chat(prompt, user)
    batch = _parse_batch(raw)
    return batch_to_findings(batch, pass_id)


def judge_batch_offline(
    slugs: list[str],
    prose_bodies: dict[str, str],
    pass_id: str,
    pass_num: int,
) -> tuple[list[Finding], list[Finding]]:
    """Rule-based fallback when API unavailable; dual-pass via span width."""
    a_out: list[Finding] = []
    b_out: list[Finding] = []
    for slug in slugs:
        text = prose_bodies.get(slug, "")
        if not text:
            continue
        for tok in bare_english_tokens(slug, text):
            ru = CALQUE_RU.get(tok.lower())
            if not ru:
                continue
            if tok.lower() == "random" and re.search(r"\brandom\s*\(", text):
                continue
            for m in re.finditer(re.escape(tok), text, re.I):
                if pass_num == 1:
                    span = expand_span(text, m.start(), m.end())
                else:
                    span = expand_span(text, m.start(), m.end(), max_len=120)
                fix = span.replace(tok, ru) if tok in span else span.replace(m.group(0), ru)
                if span and fix != span:
                    a_out.append(
                        Finding(slug=slug, span=span, category="A:replace", why=tok, fix=fix, pass_id=pass_id)
                    )
                break
        for m in CANC_OFFLINE.finditer(text):
            word = m.group(0)
            repl = REGISTER_FIX.get(word.lower(), "")
            if pass_num == 1:
                span = expand_span(text, m.start(), m.end())
            else:
                span = expand_span(text, m.start(), m.end(), max_len=100)
            fix = re.sub(re.escape(word), repl, span, count=1, flags=re.I)
            fix = re.sub(r"\s+", " ", fix).strip(" ,—")
            if span and fix and fix != span:
                b_out.append(
                    Finding(
                        slug=slug,
                        span=span,
                        category="B:canc",
                        why=f"канцелярит «{word}»",
                        fix=fix,
                        pass_id=pass_id,
                    )
                )
    return a_out, b_out


def findings_to_lang_rows(findings: list[Finding]) -> list[LangRow]:
    rows: list[LangRow] = []
    for f in findings:
        if f.category.startswith("A:"):
            rows.append(
                LangRow(slug=f.slug, axis="A", subtype="replace", span=f.span, fix=f.fix, why=f.why, term=f.why)
            )
        elif f.category.startswith("B:"):
            rows.append(
                LangRow(
                    slug=f.slug,
                    axis="B",
                    subtype=f.category.split(":", 1)[1],
                    span=f.span,
                    fix=f.fix,
                    why=f.why,
                )
            )
    return rows
