# null

Личный статичный архив математических объектов, эссе и алгоритмических скетчей.

## Структура

```
null/
├── index.html              сетка карточек объектов
├── styles/main.css         единственная таблица стилей
├── objects/                страницы констант (π, e, φ)
├── essays/                 прозаические заметки
├── sketches/               sonic pi треки
├── man.html                руководство в формате man-page
└── feed.xml                RSS
```

## Дизайн-система

CSS-переменные определены в `:root` в `styles/main.css`.
Шрифты подгружаются с Google Fonts: Inter, JetBrains Mono, IM Fell English.

## Локальный запуск

```sh
cd null
python3 -m http.server 8765
```

Затем открыть http://localhost:8765/

## Зависимости

Только Google Fonts. Никакого JS.
