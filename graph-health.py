#!/usr/bin/env python3
"""
Проверка здоровья графа null. Read-only, без зависимостей.
Запуск из корня репозитория:  python3 graph-health.py
Выход: 0 если критичных проблем нет (сироты/висячие рёбра/распад на острова), иначе 1.
"""
import json, sys, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent
LJ = ROOT / "data" / "links.json"
if not LJ.exists():                     # если скрипт лежит не в корне
    cand = list(ROOT.rglob("data/links.json"))
    LJ = cand[0] if cand else LJ

d = json.loads(LJ.read_text(encoding="utf-8"))
N = {n["id"]: n for n in d["nodes"]}
E = d["edges"]
pairs = set((e["from"], e["to"]) for e in E)
und = defaultdict(set)
for a, b in pairs:
    if a in N and b in N:
        und[a].add(b); und[b].add(a)

problems = 0

# 1. висячие рёбра (endpoint не существует)
dangling = [(e["from"], e["to"]) for e in E if e["from"] not in N or e["to"] not in N]
print(f"висячие рёбра:        {len(dangling)}")
for a, b in dangling:
    print(f"   {a} → {b}  (нет узла: {a if a not in N else b})")
problems += len(dangling)

# 2. сироты
orphans = [i for i in N if len(und[i]) == 0]
print(f"сироты (0 связей):    {len(orphans)}")
for i in orphans: print(f"   {N[i]['type']}:{i}")
problems += len(orphans)

# 3. компоненты связности
seen, comps = set(), 0
for i in N:
    if i in seen: continue
    comps += 1; stack = [i]
    while stack:
        x = stack.pop()
        if x in seen: continue
        seen.add(x); stack += [y for y in und[x] if y not in seen]
print(f"компоненты:           {comps}  ({'ок, один кусок' if comps==1 else 'РАСПАД НА ОСТРОВА'})")
if comps != 1: problems += 1

# 4. взаимность
recip = sum(1 for a, b in pairs if (b, a) in pairs)
print(f"взаимность:           {recip}/{len(pairs)}  ({100*recip//max(len(pairs),1)}%)")

# 4b. узлы, на которые никто не ссылается (мягкое предупреждение)
# build-backlinks.js такой узел пропускает целиком: блок "упоминается в"
# не появится, а выписанный руками останется неподтверждённым графом.
indeg = defaultdict(int); outdeg = defaultdict(int)
for a, b in pairs:
    if a in N and b in N:
        outdeg[a] += 1; indeg[b] += 1
noinc = sorted(i for i in N if indeg[i] == 0 and outdeg[i] > 0)
print(f"нет входящих рёбер:   {len(noinc)}  [ручная триажировка, не блокер]")
for i in noinc:
    print(f"   {N[i]['type']:<10} {i:<20} исходящих: {outdeg[i]}")

# 5. degree-1 (мягкое предупреждение, не критично)
deg1 = sorted(i for i in N if len(und[i]) == 1)
print(f"на одном ребре (deg=1): {len(deg1)}  [ручная триажировка, не блокер]")
for i in deg1:
    print(f"   {N[i]['type']:<10} {i:<16} → {next(iter(und[i]))}")

print("\nИТОГ:", "всё зелёное ✓" if problems == 0 else f"критичных проблем: {problems}")
sys.exit(0 if problems == 0 else 1)
