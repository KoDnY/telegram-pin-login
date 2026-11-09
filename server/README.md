# Telegram PIN Login — сервер

Самостоятельный серверный проект: TypeScript/Express API, Python/aiogram-бот и ngrok. Flet-клиент здесь не устанавливается и не запускается.

## Требования

- Python 3.12;
- Node.js 24 LTS и npm;
- GNU Make для запуска через Makefile;
- ngrok с настроенным authtoken;
- Telegram-бот, созданный через [BotFather](https://t.me/BotFather).

Все команды ниже выполняются **из папки server**. Для переноса достаточно этой папки; клиентская папка и родительский launcher не нужны.

## Установка на новом компьютере

На уже настроенном ноутбуке переходите к разделу запуска. Из папки `server` установите зависимости:

```powershell
make install
```

Команда создаст отсутствующее окружение, установит зависимости Python и npm и скопирует `.env.example` в `.env`, если `.env` ещё нет. Затем заполните настройки ниже. Существующий `.env` не перезаписывается.

Вариант без Make:

```powershell
py -3.12 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
npm.cmd --prefix api ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Используется только одно Python-окружение `server/.venv`. Зависимости Express устанавливаются отдельно в `api/node_modules` средствами npm.

## Общий .env

API и бот читают один файл `.env` в корне сервера:

| Переменная | Что указать |
| --- | --- |
| `API_PORT` | `3000` |
| `BOT_PORT` | `8080` |
| `API_BASE_URL` | `http://127.0.0.1:3000` |
| `BOT_INTERNAL_URL` | `http://127.0.0.1:8080` |
| `INTERNAL_API_KEY` | случайный секрет внутренней связи API и бота |
| `BOT_TOKEN` | токен от BotFather |
| `WEBHOOK_SECRET` | другой случайный секрет webhook |
| `PUBLIC_BASE_URL` | launcher автоматически запишет HTTPS-адрес ngrok |
| `ADMIN_CHAT_ID` | ID личного чата администратора; можно заполнить после первого /start |

Создать секрет можно командой ниже, выполнив её дважды для двух разных значений:

```powershell
./.venv/Scripts/python.exe -c "import secrets; print(secrets.token_hex(32))"
```

Не публикуйте `.env`, токены и журналы. Клиенту нужны только адрес API и публичный username бота.

## Ngrok

[Установите ngrok](https://ngrok.com/download/windows) и один раз настройте authtoken своего аккаунта:

```powershell
ngrok config add-authtoken "ВАШ_NGROK_AUTHTOKEN"
```

Портативный `ngrok.exe` можно положить в `tools/`: тогда команда настройки будет `./tools/ngrok.exe config add-authtoken "ВАШ_NGROK_AUTHTOKEN"`. Authtoken ngrok отличается от BOT_TOKEN.

## Запуск через Makefile (Windows)

Проверьте доступность GNU Make командой `make --version`. На Windows с winget его можно установить командой `winget install --id ezwinports.make --exact --source winget`, затем открыть новый терминал. Если команда не появилась во встроенном терминале, полностью перезапустите IDE. Makefile использует `cmd.exe`.

Из папки `server` выполните:

```powershell
make run
```

Из общей папки используйте `make -C server run`. Дождитесь **«Сервер готов»**, затем в другом терминале запустите клиент командой `make -C client run`. Оставьте терминал сервера открытым. Для остановки сервера нажмите `Ctrl+C`; клиента — закройте его окно.

На новом компьютере сначала выполните `make install`, затем заполните `.env`.
Существующий `.env` и окружение при этом сохраняются. `make help` покажет команды.

## Другие способы запуска

Дважды нажмите `start.bat` либо выполните:

```powershell
./start.bat
```

Альтернатива:

```powershell
./.venv/Scripts/python.exe -u run.py
```

Launcher собирает API, запускает API и ngrok, обновляет PUBLIC_BASE_URL в общем `.env`, запускает бота и проверяет webhook Telegram. Дальше сервер работает до `Ctrl+C`. Клиент запускается отдельно и может закрываться независимо.

Перед общим серверным запуском остановите старые вручную запущенные API/бот, если они занимают порты. Уже работающий подходящий туннель ngrok может использоваться повторно; сервер не остановит чужой процесс при завершении.

Проверка API: откройте [http://127.0.0.1:3000/health](http://127.0.0.1:3000/health). Ожидается `{"status":"ok"}`. Это проверка только API, не Telegram.

## ADMIN_CHAT_ID

Напишите своему боту `/start`. Откройте [инспектор ngrok](http://127.0.0.1:4040), найдите собственный `POST /telegram/webhook` и возьмите из JSON `message.chat.id`. Запишите его в общий `.env` как ADMIN_CHAT_ID и перезапустите сервер. Пока ID не заполнен, вход работает, а отправка администратору отклоняется.

## Ручной запуск

В отдельных терминалах из server:

```powershell
npm.cmd --prefix api run build
node api/dist/server.js
```

```powershell
ngrok http 8080
```

При ручном запуске сохраните HTTPS-адрес туннеля в PUBLIC_BASE_URL, затем:

```powershell
./.venv/Scripts/python.exe -m bot.app.main
```

Бот использует webhook `/telegram/webhook`; polling не запускается.

## Проверки

```powershell
make test
```

Тесты сервера не зависят от исходников клиента. Сценарий совместной работы с настоящим клиентским HTTP-классом находится отдельно, в общей рабочей папке `tests/local_smoke.py`.

## Диагностика

- Занят 3000/8080: остановите предыдущий сервер; launcher чужие процессы не завершает.
- Нет ngrok: добавьте его в PATH или положите tools/ngrok.exe.
- Нет PIN: проверьте BOT_TOKEN, доступ в интернет и состояние ngrok; отправьте новый /start.
- INTERNAL_AUTH_FAILED: общий INTERNAL_API_KEY должен быть заполнен; открытие внутреннего маршрута в браузере без ключа закономерно запрещено.
- Ошибка отправки: проверьте ADMIN_CHAT_ID и что администратор ранее написал боту.
- После перезапуска API прежние PIN и сессии недействительны.

API и webhook по умолчанию слушают loopback для локальной демонстрации. Туннель ngrok публикует бот, не порт API. Для удалённого клиента адрес API должен быть доступен ему по сети; эта настройка не равна PUBLIC_BASE_URL.
