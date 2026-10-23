# Implementation Plan: Вход через Telegram и сообщение администратору

**Branch**: Git-репозитория нет; setup-plan вернул идентификатор 001-telegram-pin-login, это не созданная ветка.
**Date**: 2026-10-20
**Spec**: [spec.md](spec.md)

## Summary

Три локальных процесса: Flet-клиент, Express API и aiogram-бот с aiohttp.
Telegram доставляет webhook через ngrok непосредственно боту.
Бот передаёт профиль в API и получает PIN. Клиент обменивает PIN на профиль и временный токен доступа.
После входа клиент отправляет текст API, API просит бота доставить его настроенному администратору.
База данных отсутствует. Решения ниже относятся к реализации подтверждённых сценариев, а не к расширению продукта.

## Technical Context

**Language/Version**: Python 3.12 как базовая совместимая версия; Node.js 24 LTS, TypeScript 5.x. Фактическую доступность интерпретаторов проверить при реализации.
**Primary Dependencies**: Express 5, aiogram 3 + aiohttp, Flet, httpx, python-dotenv; tsx для разработки, TypeScript compiler, Node test runner и Supertest для API.
Точные версии закрепить после проверки совместимости установкой и сохранить lockfile/requirements.
**Storage**: Один процесс Express; Map для профилей, PIN и токенов доступа. Состояние теряется при перезапуске. Файловой персистентности нет.
**Testing**: API unit/integration tests с управляемыми часами и подменой доставки; pytest для обработчиков бота; ручная проверка Flet и сквозного webhook.
**Target Platform**: Windows, локальный запуск.
**Project Type**: Desktop client + HTTP API + webhook bot.
**Performance Goals**: Продуктовые численные цели не заданы; проверить успешный сценарий и корректные ошибки без зависания UI.
**Constraints**: PIN 6 цифр / 15 минут / одноразовый; новый /start отменяет старый PIN; один ngrok tunnel; готовые Skills/MCP.
**Scale/Scope**: Учебная демонстрация на одном компьютере; несколько пользователей для проверки изоляции; без горизонтального масштабирования.

## Constitution Check

До исследования: constitution.md — незаполненный шаблон; утверждённых принципов нет. Примеры TDD и иных правил не считаются обязательными.
Проверены явные ограничения пользователя: два языка, webhook, ngrok, отсутствие БД, готовые инструменты, односторонние сообщения.
После проектирования: ограничения соблюдены. Дополнительные серверные токены — технический способ связать сообщения с уже выполненным входом.
Hooks before_plan/after_plan отсутствуют: .specify/extensions.yml не существует.

## Project Structure

### Documentation (this feature)

spec.md, constraints.md, plan.md, research.md, data-model.md, contracts/http.md, quickstart.md.
tasks.md создаётся отдельной фазой speckit-tasks.

### Source Code (repository root)

Планируемая структура, каталоги приложения пока не созданы:

    api/
      package.json
      package-lock.json
      tsconfig.json
      .env.example
      src/app.ts
      src/server.ts
      src/store.ts
      src/bot-client.ts
      test/auth.test.ts
      test/messages.test.ts
    bot/
      requirements.txt
      .env.example
      app/main.py
      app/handlers.py
      app/api_client.py
      tests/test_handlers.py
    client/
      requirements.txt
      .env.example
      app/main.py
      app/api_client.py
    README.md

**Structure Decision**: По одному небольшому каталогу на запускаемый компонент, без ORM и лишних слоёв. Текущий main.py — стартовый пример PyCharm; не считать реализацией.

## Implementation Sequence

1. Express /health, конфигурация и единый формат ошибок.
2. Временное хранилище и проверка PIN; тесты срока, одноразовости, отмены и изоляции.
3. Aiogram /start, получение профиля/аватара, связь с API и webhook через ngrok.
4. Flet: вход, запрос auth, отображение профиля.
5. Отправка текста после входа: Flet → API → bot → Telegram admin.
6. Сквозная проверка и README с командами для Windows.

## Validation

Покрыть FR-001–FR-014 и SC-001–SC-007 сценариями из quickstart.md.
Особенно проверить две одновременные попытки входа, ведущий ноль PIN, границу 15 минут и недоставленное сообщение.
Успех Telegram sendMessage означает принятие Telegram, не прочтение администратором.
Не выполнять автоматические повторные отправки при неопределённом сетевом исходе.
