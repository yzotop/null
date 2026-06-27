# Lang weak essays — англицизмы + нелитературные фразы

**Калибровка:** OK
**Судья:** offline (gpt-4o-mini / offline-fallback, temperature 0, two-pass)

## Фильтры (отсеянные находки)

- raw pass-1 (A+B): 9
- raw pass-2 (A+B): 9
- после two-pass intersection: 9
- отсеяно span-verify: 0
- отсеяно fix-nonempty: 0
- **выжило:** 9

Ось A: bucket=replace only (keep/proper не в выходе).
Ось B: calque · canc · agreement · neologism · rhythm.

Якоря: antifragile, bayes-four-faces, decisions-distance, forking-paths, oshibki-po-pravilam. Tripwire: >2 на якоре → MISCALIBRATED.
Якорные счётчики: {'decisions-distance': 0, 'bayes-four-faces': 0, 'oshibki-po-pravilam': 0, 'antifragile': 0, 'forking-paths': 0}

## `confusion-matrix` · **1** (A:replace×1)

- **A/replace** · «Точность среди пойманных — какая часть сигналов настоящая (precision).»
  - → Точность среди пойманных — какая часть сигналов настоящая (точность).
  - why: precision

## `good-decisions` · **1** (A:replace×1)

- **A/replace** · «В покере это называется resulting1 — ошибка оценивать качество решения по качеству исхода.»
  - → В покере это называется итоговый1 — ошибка оценивать качество решения по качеству исхода.
  - why: resulting

## `nudge` · **1** (A:replace×1)

- **A/replace** · «default effect»
  - → значение по умолчанию effect
  - why: default

## `poker-distance` · **1** (A:replace×1)

- **A/replace** · «Энни Дьюк назвала ошибку смешивать одно с другим «resulting»1 — и отучиться от неё труднее всего, потому что мир вознаграждает за результат, а не за качество решения.»
  - → Энни Дьюк назвала ошибку смешивать одно с другим «итоговый»1 — и отучиться от неё труднее всего, потому что мир вознаграждает за результат, а не за качество решения.
  - why: resulting

## `pseudorandom` · **1** (A:replace×1)

- **A/replace** · «x0 — seed, начальное значение.»
  - → x0 — зерно, начальное значение.
  - why: seed

## `simulation` · **1** (A:replace×1)

- **A/replace** · «Сказать «модель дура, Испания вылетела» — это resulting: оценка по единственному исходу того, что было про распределение.»
  - → Сказать «модель дура, Испания вылетела» — это итоговый: оценка по единственному исходу того, что было про распределение.
  - why: resulting

## `skin-in-the-game` · **1** (A:replace×1)

- **A/replace** · «Skin in the game — шкура на кону — это симметрия: тот, кто получает выгоду от решения, должен нести и его убыток.»
  - → Skin in the игра — шкура на кону — это симметрия: тот, кто получает выгоду от решения, должен нести и его убыток.
  - why: game

## `xg` · **1** (A:replace×1)

- **A/replace** · «Это resulting наоборот: вместо «оценим решение по тому, чем оно кончилось» — «оценим по качеству самого момента».»
  - → Это итоговый наоборот: вместо «оценим решение по тому, чем оно кончилось» — «оценим по качеству самого момента».
  - why: resulting

## `zfc-independence` · **1** (B:canc×1)

- **B/canc** · «Она не истинна и не ложна в рамках стандартной математики.»
  - → Она не истинна и не ложна в стандартной математики.
  - why: канцелярит «в рамках»

## Чистые

0 выживших находок после фильтров.

`ab-testing`, `adtech`, `antifragile`, `auctions`, `base-rate`, `bayes-four-faces`, `bayesian`, `benford`, `black-swan`, `bookmaker-bayes`, `bookshelf`, `bootstrap`, `buffon`, `causality`, `clt`, `cognitive-biases`, `conditions-for-cooperation`, `decisions-distance`, `deck-of-cards`, `elo`, `ergodicity`, `euler-formula`, `evolution-of-cooperation`, `expected-utility`, `expected-value`, `fibonacci-nature`, `five-letters`, `flaneur`, `focal-point`, `forking-paths`, `gamblers-fallacy`, `gambling-math`, `game-theory`, `game-theory-distance`, `games-and-math`, `games-that-train-machines`, `good-name`, `hawks-and-doves`, `hidden-layer`, `hilbert-godel`, `honest-signal`, `infinity`, `infinity-paradoxes`, `infinity-types`, `invented-or-discovered`, `is-forecast-right`, `kolmogorov`, `live-to-next-round`, `llm-eval`, `markov-chains`, `markov-deep`, `math-music`, `mcmc`, `millennium-problems`, `monte-carlo`, `multiplication-table`, `optionality`, `oshibki-po-pravilam`, `penalty`, `pi-in-gaussian`, `poker-basics`, `poker-bayes`, `poker-exploit`, `poker-glossary`, `poker-kelly`, `poker-solvers`, `popularizers`, `primes-mystery`, `probability-paradoxes`, `proof`, `prospect-theory`, `regression-to-mean`, `replication-crisis`, `rsa-primes`, `simpson`, `small-numbers`, `terminal`, `trust-but-verify`, `two-alphabets`, `two-sided-markets`, `two-systems`, `uncertainty-knight`, `underdogs`, `unit-economics`, `value-betting`, `via-negativa`, `who-sets-odds`, `why-simulation`, `zero-history`, `zero-point-nine`
