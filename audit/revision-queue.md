# audit/revision-queue.md — очередь доработки (канон)

Источник: доверенные сигналы Stage 1 (staccato-проза, регистр вы→ты, диспропорция,
голые EN, длина, math). Балл/hunspell/плотность — НЕ источник. Вердикт — от чтения.
Статус: ☐ не прочитано · ◐ прочитано (вердикт есть) · ☑ исправлено-закоммичено

## Счётчик
- Очередь чтения: 10 · прочитано 6 · исправлено 2 · снято-как-чистое 2
- Сквозные пакеты: 2 (0 готово)
- Пулы на спот-чек: factual 234 · «то есть» 8
- Уже закрыто в этом треде: 6 контент-фиксов + механический проход

## A. Структурная подочередь (сначала решение о роли, потом проза)
Сателлиты, дублирующие капстоуны oshibki / decisions-distance.
- ◐ two-systems · dup oshibki (System 1/2 несущий) + ошибка bat→бита · → сузить до праймера; bat-фикс готов · статус: bat ☐, сужение — решение
- ◐ good-decisions · перекрывает decisions-distance (resulting, EV-дистанция); staccato 61% · → решить: «resulting-праймер» или свернуть · статус: решение
- ☐ prospect-theory · thin 566; рядом раздел prospect в oshibki · → проверить роль
- ☐ nudge · thin 507; в том же кластере · → проверить роль

## B. Прозовая подочередь (standalone, только полировка)
- ☑ clt — исправлено (04af50d)
- ☑ markov-deep — MCMC-фикс; staccato оправдана · статус: закоммичено
- ◐ math-music — чисто, правок нет · статус: снято
- ◐ five-letters — чисто, правок нет · статус: снято
- ☐ benford · staccato 4/42%
- ☐ primes-mystery · staccato 4/47%

## C. Сквозные пакеты (механика, один промпт на пакет — не поэссейное чтение)
- ☐ Регистр вы→ты (8): adtech, ab-testing, auctions, bayesian, base-rate, fibonacci-nature, expected-utility, probability-paradoxes
- ☐ EN-якоря (7): evolution-of-cooperation, hidden-layer, game-theory-distance, who-sets-odds, conditions-for-cooperation, terminal, value-betting · (poker-glossary = keep, жаргон)

## D. Пулы на спот-чек (отдельная метрика, не очередь)
- factual-worklist: 234 утверждения · начинать с «впервые/первый» и атрибуций
- «то есть»/«именно поэтому»: 8 спанов · каждый глазами (в xg связка работает — не трогать)

## Закрыто (этот тред)
deck-of-cards (52!, 70→68), gamblers-fallacy (137M), pseudorandom (10⁶⁰⁰²),
monte-carlo (MCMC + Паста), markov-deep (MCMC≠LLM), markov-chains (MCMC≠нейросети),
games-that-train-machines (актуальность + EN),
cognitive-biases (слит → oshibki); + механический проход (заголовки/сноски/типографика/время).
