# VALIDATION — Telegram Support Chat v2.2

Дата проверки: 2026-08-09.

## Что реально проверено в сборочной среде

### Unit / service tests

```text
pytest -q
...............s                                                         [100%]
15 passed, 1 skipped
```

В этой сборочной среде `aiogram` недоступен, поэтому отдельный тест фактического объекта `ReplyKeyboardMarkup` пропущен через `pytest.importorskip`. Остальные 15 тестов проходят и покрывают:

- классификацию `Новые / Активные / Старые / Мои`;
- `Мои` = активный чат + текущий модератор уже отвечал;
- группировку последовательного текста и разрыв групп фото;
- отсутствие искусственного разрезания длинного source message на 2800/3000 символов;
- упаковку секций разных авторов в одно Telegram-сообщение;
- подсчёт лимита по видимому тексту после HTML entities, а не по длине строки с тегами/`&amp;`;
- отсутствие `↩️ после этого пользователь ответил` и `✓ отправлено` в истории;
- отсутствие inline history-controls в рендере;
- дефолтную страницу истории = 10 исходных сообщений;
- создание всех таблиц новой схемы SQLAlchemy.

### Python compile check

```bash
python -m compileall -q app alembic tests
```

Проходит без синтаксических ошибок.

### SQLite schema check

`Base.metadata.create_all()` на чистом `sqlite:///:memory:` успешно создаёт 6 таблиц:

```text
audit_logs
moderator_participants
moderator_sessions
moderator_view_messages
support_messages
users
```

В схеме намеренно отсутствуют `tickets` и `conversations`.

### Alembic

Offline-прогон первой миграции:

```bash
BOT_TOKEN='123456:TESTTOKEN' MODERATORS_JSON='{"1":"Test"}' \
  alembic upgrade head --sql
```

успешно строит SQLite DDL и перевод `alembic_version` на `0001_initial`.

## Проверенные Telegram/aiogram допущения

Перед реализацией сверены актуальные API aiogram/Bot API:

- проект ориентирован на aiogram `3.30.0`;
- custom dependencies через `Dispatcher` workflow data подходят для `settings`, сервисов и фабрик;
- `deleteMessage`/`deleteMessages` позволяют удалять сообщения рабочего окна в личном чате в пределах ограничений Telegram;
- обычное удаление ограничено возрастом сообщения, поэтому workspace TTL установлен в 23 часа;
- callback queries всегда получают `answer()`;
- обычный Bot API не используется для выдуманного read receipt: v2.2 вообще не рисует delivery/read proxy markers;
- `sendMessage.text` допускает 1–4096 символов после entity parsing, поэтому история пакуется по видимой длине;
- reply controls реализованы через `ReplyKeyboardMarkup` (`is_persistent`, `resize_keyboard`, `input_field_placeholder`).

## Ограничение этой среды

Полный runtime-smoke-test с настоящим Telegram stack в текущем sandbox выполнить нельзя: системное окружение не содержит `aiogram` и `aiosqlite`, а доступный package mirror не отдаёт `aiogram==3.30.0`. Поэтому Telegram polling и async SQLite engine здесь не запускаются. При этом sync schema-test из pytest проходит, а схема БД в v2.2 не менялась.

Это означает, что здесь **не заявляется** полноценный запуск polling против Telegram. Исходники, тестируемая доменная/DB-логика, Alembic DDL и Python syntax проверены; использованные aiogram API сверены с актуальной документацией.

## Что прогнать локально после распаковки

```bash
cp .env.example .env
# заполнить BOT_TOKEN и MODERATORS_JSON
./scripts/setup_venv.sh
source .venv/bin/activate
pytest -q
ruff check .
alembic upgrade head
python -m app.main
```

На Windows те же операции автоматизированы `scripts/setup_venv.ps1` и `scripts/run.ps1`.

Для реального smoke-test рекомендуется два Telegram-аккаунта модераторов + один пользователь и сценарии:

1. пользователь отправляет 3 коротких сообщения за <10 секунд: модератор с открытым чатом получает их сразу, остальные получают один compact burst после debounce;
2. оба модератора одновременно открывают пользователя;
3. первый отвечает — ответ появляется у пользователя и во втором модераторском workspace;
4. второй отвечает — пользователь видит его отдельный псевдоним;
5. переключение чата удаляет временную историю и открывает новую;
6. возврат восстанавливает последние 10 source messages из SQLite;
7. переход по страницам выполняется reply-кнопками; текстовые секции разных авторов на странице упаковываются вместе до реального лимита 4096 видимых символов, фото остаются отдельно;
8. `Инфо`, `Бан/Разбанить`, `К спискам` и навигация находятся в reply keyboard и не пересылаются пользователю;
9. бан блокирует новые пользовательские сообщения, разбан возвращает доступ.
