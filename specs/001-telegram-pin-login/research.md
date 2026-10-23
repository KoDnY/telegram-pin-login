# Research: решения для локальной демонстрации

## 1. Топология и ngrok

**Decision**: API 127.0.0.1:3000, бот 127.0.0.1:8080, Flet обращается к API локально. ngrok http 8080 даёт публичный HTTPS URL webhook.
**Rationale**: Только Telegram требует доступ извне; один туннель без дополнительного прокси Express.
**Alternatives considered**: Туннель к Express с проксированием webhook добавляет ненужный переход; два туннеля не нужны.
Источник: https://ngrok.com/docs/getting-started/
Aiogram официально поддерживает aiohttp SimpleRequestHandler и secret_token:
https://docs.aiogram.dev/en/latest/dispatcher/webhook.html

## 2. PIN и временные данные

**Decision**: Express хранит состояние в памяти. PIN — строка ровно из шести ASCII-цифр, включая ведущие нули; генерация через crypto.randomInt, проверка коллизий среди активных кодов. При замене код должен отличаться от старого. Истечение: now >= issuedAt + 900000.
**Rationale**: Нет БД, достаточно одного процесса. Проверка и удаление кода до любого await обеспечивают одноразовость в рамках этого процесса.
**Alternatives considered**: Файлы/БД исключены; генерация PIN ботом распределяет логику проверки между компонентами.
При исчерпании пространства активных кодов вернуть ошибку выдачи, не перезаписывать чужой код.
Источник: https://nodejs.org/api/crypto.html#cryptorandomintmin-max-callback

## 3. Передача сообщений после входа

**Decision**: После auth сервер выдаёт случайный непрозрачный токен (crypto.randomBytes); хранит связь с пользователем в памяти. Клиент держит токен только в текущем процессе.
**Rationale**: Сообщения должны отправлять вошедшие пользователи; доверять переданному клиентом telegram_id недостаточно.
**Alternatives considered**: Повторный PIN для каждого сообщения нарушает одноразовый сценарий; JWT добавляет ненужную сложность.
Токен действует до перезапуска API; постоянный вход и отдельный logout не проектируются.
Источник: https://nodejs.org/api/crypto.html#cryptorandombytessize-callback

## 4. Бот и администратор

**Decision**: BOT_TOKEN только у Python-бота. API вызывает /internal/messages бота с INTERNAL_API_KEY. ADMIN_CHAT_ID задаётся в конфигурации бота; администратор предварительно запускает бота в Telegram.
**Rationale**: Отправка в Telegram сосредоточена в aiogram, токен Telegram не попадает в клиент и API.
**Alternatives considered**: Прямой sendMessage из Express потребует BOT_TOKEN в двух компонентах.
Поскольку ngrok публикует listener бота, /internal/messages обязательно проверяет ключ; webhook проверяет отдельный secret_token.
Источник: https://core.telegram.org/bots/api#sendmessage

## 5. Аватар

**Decision**: Бот получает уменьшенный вариант фото профиля, скачивает и передаёт base64 и MIME вместе с профилем. При отсутствии фото или ошибке загрузки — null; Flet показывает заглушку.
**Rationale**: Telegram file URL содержит bot token; передавать его клиенту нельзя.
**Alternatives considered**: URL Telegram непригоден для выдачи клиенту; отдельное постоянное файловое хранилище не нужно.
Источники: https://core.telegram.org/bots/api#getuserprofilephotos и https://core.telegram.org/bots/api#getfile

## 6. Ошибки, валидация и доставка

**Decision**: Express проверяет JSON на границе. Текст после trim: 1–3000 символов; бот отправляет текст без parse_mode, добавляя короткую подпись отправителя. HTTP body limit 2 MB, фото максимум 1 MB до base64. Пустая фамилия/username показываются как «Не указано».
**Rationale**: Умещаем текст и подпись в лимит Telegram 4096 символов, избегаем непреднамеренной разметки. Это технические границы, а не новые бизнес-функции.
**Alternatives considered**: Автоматически разбивать длинные сообщения сложнее и не требуется.
Успех только после ответа Telegram; timeout сообщает, что доставка не подтверждена, без автоматического retry.
Источники: https://expressjs.com/en/5x/api/ и https://core.telegram.org/bots/api#sendmessage

## 7. Инструменты разработки

**Decision**: Использованы готовые speckit-specify, graphify и speckit-plan. Для проверки документации использован готовый web tool; собственный MCP не создаётся. Если на защите нужен именно отдельный MCP разработки, выбрать доступный готовый документационный MCP при реализации и сохранить реальный пример его использования.
**Rationale**: Не подменять требование использованием самодельного инструмента и не заявлять ещё не выполненные вызовы.
**Alternatives considered**: Интеграция ИИ внутрь приложения выходит за согласованный объём.

Нерешённых проектных вопросов нет. BOT_TOKEN, ADMIN_CHAT_ID и публичный URL — значения настройки запуска, а не блокирующие вопросы спецификации.


## Проверка версий и API по официальной документации

Python3.12 соответствует минимальным требованиям Python3.10+ у aiogram3 и Flet.
Использовать актуальный API закреплённой версии Flet: ft.run(main), асинхронные обработчики и Image(src=base64_string), не переносить src_base64 из старых примеров без проверки.
Источники: https://docs.aiogram.dev/en/latest/ ,
https://flet.dev/docs/getting-started/installation/ ,
https://flet.dev/docs/cookbook/async-apps/ ,
https://flet.dev/docs/controls/image/

Node24 выбран как LTS; Express5 требует Node18+.
Для production-подобной проверки учебного сервера выполнить tsc, затем node dist/server.js.
Источники: https://nodejs.org/en/about/previous-releases ,
https://expressjs.com/en/starter/installing/ ,
https://www.typescriptlang.org/docs/handbook/compiler-options.html

Выбранная топология — наше проектное решение на основе возможностей библиотек, а не готовая архитектура, предписанная документацией.
