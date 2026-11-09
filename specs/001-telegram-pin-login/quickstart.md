# Настройка после разделения проектов

Сервер и клиент запускаются независимо. Актуальные пошаговые инструкции:

- [server/README.md](../../server/README.md) — API, бот, ngrok, единый серверный .env и server/.venv;
- [client/README.md](../../client/README.md) — Flet, QR, client/.env и client/.venv.

На уже настроенном ноутбуке:

1. Запустите `server/start.bat`, дождитесь готовности API и бота.
2. Запустите `client/start.bat`.
3. Перейдите к боту через QR или кнопку, отправьте /start и введите новый PIN.

Сервер не открывает Flet; закрытие клиента не останавливает сервер. Для остановки сервера используйте Ctrl+C в его терминале.

## Проверка из общей рабочей папки

```powershell
npm.cmd --prefix server/api run build
npm.cmd --prefix server/api test
./server/.venv/Scripts/python.exe -m pytest server/bot/tests server/tests -q
./server/.venv/Scripts/python.exe tests/local_smoke.py
```

Последний сценарий проверяет интеграцию двух проектов с тестовой Telegram-сессией. Реальные сообщения не отправляются.

При переносе проекта создавайте его .venv заново из собственного requirements.txt. Не переносите и не публикуйте .env. Серверные секреты клиенту не нужны.
