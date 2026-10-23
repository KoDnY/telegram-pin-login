# HTTP contracts

UTF-8 JSON. API: http://127.0.0.1:3000. Bot: http://127.0.0.1:8080.
Ошибка: {"error":{"code":"...","message":"..."}}. Успех — только указанные ниже статусы.
INTERNAL_API_KEY — общий секрет API и бота, заголовок X-Internal-Key.
Он не передаётся Flet. WEBHOOK_SECRET — отдельный секрет Telegram webhook.

## GET /health (API)

Без авторизации. 200 {"status":"ok"}. Проверяет работу API, не гарантирует доступность Telegram.

## POST /internal/pins (API, bot only)

X-Internal-Key обязателен.
Тело: {"user":{"telegramId":123,"firstName":"Иван","lastName":null,"username":null,"avatar":null}}
Поля соответствуют data-model.md.
201 {"pin":"012345","expiresAt":"ISO-8601 UTC"}.
Заменяет предыдущий PIN того же пользователя.
400 INVALID_PROFILE; 403 INTERNAL_AUTH_FAILED; 503 PIN_CAPACITY_EXCEEDED.

## POST /auth (API, client)

Тело: {"key":"012345"}.
200 {"user":UserProfile,"accessToken":"opaque-random-token"}.
400 INVALID_PIN_FORMAT; 401 INVALID_PIN для неизвестного, истёкшего, заменённого или использованного кода.
Потребление PIN и создание сессии синхронны, до любых сетевых await.

## POST /messages (API, client after login)

Authorization: Bearer <accessToken>.
Тело: {"text":"Привет!"}. После удаления пробелов по краям допустимо от 1 до 3000 единиц UTF-16; обычная буква занимает одну, большинство emoji — две. Некорректный Unicode отклоняется.
200 {"status":"sent"} после подтверждённого ответа Telegram.
400 INVALID_TEXT; 401 UNAUTHORIZED; 502 DELIVERY_FAILED; 504 DELIVERY_UNCONFIRMED.
При timeout нельзя сообщать, что сообщение точно не доставлено: результат неизвестен.
Повторного автоматического запроса клиент не делает.

## POST /internal/messages (bot, API only)

X-Internal-Key обязателен даже при обращении через ngrok.
Тело: {"sender":{"telegramId":123,"firstName":"Иван","username":null},"text":"Привет!"}.
200 {"status":"sent","telegramMessageId":1234}.
400 INVALID_TEXT; 403 INTERNAL_AUTH_FAILED; 502 TELEGRAM_DELIVERY_FAILED; 504 DELIVERY_UNCONFIRMED.
Бот отправляет подпись отправителя и текст в ADMIN_CHAT_ID без parse_mode.
Обработчик ждёт Telegram sendMessage и лишь затем возвращает успех.

## POST /telegram/webhook (bot, Telegram)

Публичный URL: <PUBLIC_BASE_URL>/telegram/webhook.
X-Telegram-Bot-Api-Secret-Token проверяется SimpleRequestHandler.
Тело: Telegram Update. 200 — update принят обработчиком, это не подтверждение отправки PIN.
Использовать фоновую обработку, чтобы быстрый webhook ack не ждал цепочку Telegram → API → Telegram.
Дедупликация одновременно обрабатываемых/завершённых update_id в памяти бота предотвращает повторную выдачу PIN при повторе webhook; список очищается и теряется при перезапуске.
Ошибку выдачи PIN бот сообщает пользователю; polling не запускается.

## Таймауты и доступ

Внутренние вызовы и Telegram: 10 секунд. Клиент и API→bot: 15 секунд; конечный результат может быть неопределён при сетевом обрыве.
API и бот слушают loopback. ngrok публикует порт8080.
Webhook и внутренний маршрут имеют разные секреты. Ключи, PIN, accessToken и BOT_TOKEN не журналировать.
