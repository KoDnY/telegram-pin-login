# Telegram PIN Login

Учебное клиент-серверное приложение для входа по одноразовому PIN из Telegram. После входа показывает профиль и позволяет отправить текст администратору в Telegram.

- **Клиент:** Python и Flet, отдельное настольное окно.
- **API:** TypeScript и Express.
- **Telegram-бот:** Python и aiogram, получение событий через webhook.
- **ngrok:** публичный HTTPS-туннель к локальному боту.
- **PIN:** шесть цифр, действует 15 минут, используется один раз. Новый `/start` отменяет предыдущий PIN пользователя.

Базы данных нет. Профили, PIN и сессии хранятся в памяти API и теряются при его перезапуске. Ответы администратора в приложение не возвращаются.

## Как это работает

```text
Telegram → ngrok → бот → API → PIN в Telegram
Flet → API: PIN → профиль и токен доступа
Flet → API: сообщение → бот → администратор в Telegram
```

PIN нужен для входа. Полученный после входа токен используется для отправки сообщений. Внутренний ключ API и секрет webhook клиенту не передаются.

## Требования

- Windows и PowerShell для команд ниже;
- Python 3.12 с командой `py -3.12`;
- Node.js 24 LTS и npm;
- [ngrok](https://ngrok.com/download/windows) и учётная запись ngrok;
- Telegram-бот, созданный через [@BotFather](https://t.me/BotFather).

Все команды выполняются **из корня проекта**. Python-компоненты используют отдельные виртуальные окружения; активировать их вручную не требуется.

## Установка зависимостей

```powershell
npm.cmd --prefix api ci
py -3.12 -m venv bot/.venv
py -3.12 -m venv client/.venv
./bot/.venv/Scripts/python.exe -m pip install -r bot/requirements.txt
./client/.venv/Scripts/python.exe -m pip install -r client/requirements.txt
```

При первом открытии Flet может понадобиться интернет для загрузки настольного runtime.

## Подготовка настроек

Создайте локальные файлы из примеров. Команда сохраняет уже существующие `.env`:

```powershell
foreach ($component in 'api', 'bot', 'client') {
    if (-not (Test-Path "$component/.env")) {
        Copy-Item "$component/.env.example" "$component/.env"
    }
}
```

Создайте **два разных секрета**, дважды выполнив:

```powershell
./bot/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Первый результат используйте как `INTERNAL_API_KEY` в **обоих** файлах `api/.env` и `bot/.env`. Второй — как `WEBHOOK_SECRET` в `bot/.env`.

| Файл | Переменная | Значение |
| --- | --- | --- |
| `api/.env` | `INTERNAL_API_KEY` | Общий секрет API и бота |
| `api/.env` | `PORT` | `3000` |
| `api/.env` | `BOT_INTERNAL_URL` | `http://127.0.0.1:8080` |
| `bot/.env` | `BOT_TOKEN` | Токен от BotFather |
| `bot/.env` | `INTERNAL_API_KEY` | Тот же секрет, что в API |
| `bot/.env` | `WEBHOOK_SECRET` | Второй, отдельный секрет |
| `bot/.env` | `PUBLIC_BASE_URL` | HTTPS-адрес ngrok, без пути и завершающего `/` |
| `bot/.env` | `API_BASE_URL` | `http://127.0.0.1:3000` |
| `bot/.env` | `PORT` | `8080` |
| `bot/.env` | `ADMIN_CHAT_ID` | Числовой ID чата администратора; порядок получения ниже |
| `client/.env` | `API_BASE_URL` | `http://127.0.0.1:3000` |
| `client/.env` | `BOT_USERNAME` | Username созданного бота без `@` |

В BotFather отправьте `/newbot`, задайте имя и username с окончанием `bot`, сохраните выданный токен в `BOT_TOKEN`.

**Не публикуйте `.env`, токены, внутренние ключи или снимки инспектора ngrok с секретами.** В Git добавляются `.env.example` с примерами. Authtoken ngrok и токен Telegram-бота — разные значения.

## Настройка ngrok

Установите ngrok по [официальной инструкции](https://ngrok.com/docs/getting-started/), затем один раз подключите authtoken из [личного кабинета](https://dashboard.ngrok.com/get-started/your-authtoken):

```powershell
ngrok config add-authtoken "ВАШ_NGROK_AUTHTOKEN"
```

Если используете портативный файл, например `tools/ngrok.exe`, заменяйте `ngrok` на `./tools/ngrok.exe`. Исполняемый файл ngrok в репозиторий не входит.

## Запуск проекта

Запустите компоненты в **четырёх отдельных терминалах**, каждый из корня проекта. Оставляйте их работающими во время демонстрации.

### 1. API

```powershell
npm.cmd --prefix api run build
node api/dist/server.js
```

Проверка в другом терминале:

```powershell
Invoke-RestMethod http://127.0.0.1:3000/health
```

Ответ должен содержать `status: ok`. Для разработки вместо сборки и `node` можно использовать `npm.cmd --prefix api run dev`.

### 2. Ngrok

```powershell
ngrok http 8080
```

В строке `Forwarding` найдите HTTPS-адрес слева от стрелки и вставьте **только адрес** в `bot/.env`:

```dotenv
PUBLIC_BASE_URL=https://example.ngrok-free.app
```

Не добавляйте `/telegram/webhook` и не записывайте команду запуска в `.env`. Состояние `online` и панель [127.0.0.1:4040](http://127.0.0.1:4040) помогают проверить туннель.

### 3. Бот

```powershell
./bot/.venv/Scripts/python.exe -m bot.app.main
```

Бот слушает порт `8080`, сам регистрирует webhook `<PUBLIC_BASE_URL>/telegram/webhook` и проверяет регистрацию. Polling не используется. Пока `ADMIN_CHAT_ID` пустой, вход работает, но сообщение администратору отправить нельзя.

### 4. Клиент

```powershell
./client/.venv/Scripts/python.exe -m client.app.main
```

Отправьте боту `/start`, введите последний PIN в приложении и нажмите «Войти». Откроется профиль: имя, фамилия, username и аватар либо заглушки для отсутствующих данных.

### Чат администратора

Чтобы получать сообщения самому:

1. Напишите `/start` своему боту из личного аккаунта.
2. Откройте [инспектор ngrok](http://127.0.0.1:4040).
3. Найдите `POST /telegram/webhook` от этого сообщения. В JSON тела возьмите число `message.chat.id`.
4. Запишите его в `bot/.env` как `ADMIN_CHAT_ID`.
5. Перезапустите бота и отправьте текст из приложения.

Администратор получает текст с подписью отправителя. Приложение показывает успех после подтверждения отправки Telegram. При сетевом таймауте результат может быть неизвестен; автоматической повторной отправки нет.

### Остановка и повторный запуск

Нажмите `Ctrl+C` в терминалах компонентов; окно клиента закройте. Штатная остановка бота удаляет webhook. Если адрес ngrok изменился, обновите `PUBLIC_BASE_URL` и перезапустите бота. После перезапуска API получите новый PIN: прежние PIN и токены входа уже недействительны.

## HTTP API

API работает на `http://127.0.0.1:3000`, бот — на `http://127.0.0.1:8080`.

| Компонент | Метод и маршрут | Назначение |
| --- | --- | --- |
| API | `GET /health` | Проверка API, `200 {"status":"ok"}` |
| API | `POST /internal/pins` | Выдача PIN по профилю Telegram; заголовок `X-Internal-Key`, успех `201` |
| API | `POST /auth` | Вход: `{"key":"123456"}`; возвращает профиль и `accessToken`, успех `200` |
| API | `POST /messages` | `{"text":"Привет!"}`; заголовок `Authorization: Bearer <accessToken>`, успех `200` |
| Бот | `POST /internal/messages` | Доставка сообщения администратору; заголовок `X-Internal-Key`, успех `200` |
| Бот | `POST /telegram/webhook` | Telegram updates через ngrok; проверка `X-Telegram-Bot-Api-Secret-Token` |

PIN передаётся строкой, чтобы сохранить ведущий ноль. Текст после удаления пробелов по краям ограничен 3000 единицами UTF-16. Ошибки имеют форму `{"error":{"code":"...","message":"..."}}`.

Открывать `/internal/pins` в адресной строке браузера для выдачи PIN нельзя: браузер не отправляет нужный POST-запрос и внутренний ключ. Для простой проверки доступен `/health`. Полные тела запросов, ответы и статусы ошибок: [HTTP-контракт](specs/001-telegram-pin-login/contracts/http.md).

## Проверки

```powershell
npm.cmd --prefix api run build
npm.cmd --prefix api test
./bot/.venv/Scripts/python.exe -m pytest bot/tests -q
./bot/.venv/Scripts/python.exe tests/local_smoke.py
```

В локальной проверке от 20 октября 2026 года прошли **33 теста API и 21 тест бота**, а также сквозной HTTP-сценарий. Последний запускает компоненты с тестовой Telegram-сессией и не отправляет сообщения настоящему админу. Он не проверяет внешний Telegram, ngrok или внешний вид окна. Подробности и границы проверки сохранены в [validation.md](specs/001-telegram-pin-login/validation.md).

Для ручной проверки пройдите вход и отправку сообщения, затем убедитесь, что использованный PIN и старый PIN после нового `/start` отклоняются. Отдельно проверьте истечение 15 минут и новый вход после перезапуска API.

## Диагностика

| Проблема | Что проверить |
| --- | --- |
| `ngrok` не распознан | Установка и `PATH`; для портативного файла используйте полный относительный путь |
| API или бот не запускается | Зависимости, `.env`, свободные порты `3000` и `8080` |
| `INTERNAL_AUTH_FAILED` | Совпадение `INTERNAL_API_KEY` API и бота; в браузере на внутреннем адресе отказ ожидаем |
| Бот не выдаёт PIN | API и бот работают, ngrok online, HTTPS-адрес совпадает с `PUBLIC_BASE_URL`; отправьте новый `/start` |
| PIN отклонён | Ровно шесть цифр, последний код, не старше 15 минут, ещё не использован; API не перезапускался |
| Сообщение не отправляется | `ADMIN_CHAT_ID` заполнен, администратор уже начал чат с ботом, бот работает |
| Сообщение имеет неизвестный результат | Сетевой таймаут; сначала проверьте Telegram, прежде чем отправлять повторно |
| Нет фамилии или аватара | Эти данные могут отсутствовать в Telegram; приложение отображает заглушку |

`/health` подтверждает работу API, но не проверяет Telegram. После изменения настроек перезапускайте соответствующий компонент.

## Структура и документация

| Каталог | Содержимое |
| --- | --- |
| `api/` | Express API, временное хранилище PIN и сессий, тесты |
| `bot/` | aiogram-бот, webhook-сервер aiohttp, тесты |
| `client/` | Flet-клиент и HTTP-клиент |
| `tests/` | Локальная сквозная проверка |
| `specs/001-telegram-pin-login/` | Спецификация, план, задачи, контракты и инструкции |

- [Спецификация](specs/001-telegram-pin-login/spec.md)
- [Ограничения проекта](specs/001-telegram-pin-login/constraints.md)
- [План](specs/001-telegram-pin-login/plan.md)
- [Задачи](specs/001-telegram-pin-login/tasks.md)
- [Подробная настройка](specs/001-telegram-pin-login/quickstart.md)

При разработке использованы готовые навыки Spec Kit, Graphify и отдельные субагенты для задач. Собственные Skills и MCP-серверы не создавались.
