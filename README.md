# null
Status: active

Личный статичный архив математических объектов, эссе и алгоритмических скетчей.

## Структура

```
null/
├── index.html              сетка карточек разделов
├── styles/main.css         единственная таблица стилей
├── objects/                130 объектов: числа, идеи, нотация, статистика
├── essays/                 108 эссе
├── visuals/                36 интерактивных визуализаций
├── books/                  16 книг
├── music/                  10 альбомов
├── man.html                руководство в формате man-page
├── map.html                граф связей
├── find.html               поиск
├── sitemap.xml             карта сайта, генерируется
└── scripts/                update_counts.py, generate_sitemap.py, update_meta.py
```

Числа в `man.html` и `index.html` поддерживает `scripts/update_counts.py` —
править их руками не нужно.

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
