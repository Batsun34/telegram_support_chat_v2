# PROJECT MAP — Telegram Support Chat v2.2

Этот файл рассчитан в том числе на передачу проекта в Codex/другому разработчику.

## Архитектура

```text
Telegram update
    │
    ▼
aiogram Dispatcher
    │
    ├─ DbSessionMiddleware ── AsyncSession per update
    ├─ ModeratorSerialMiddleware ── strict per-moderator update order
    │
    ├─ handlers/common.py    /start
    ├─ handlers/moderator.py moderator UI + relay
    └─ handlers/user.py      user input
              │
              ▼
         ChatService
         │   │
         │   └─ SQLAlchemy / SQLite
         │
         ├─ NotificationDebouncer ── 10 sec burst aggregation
         │          │
         │          └─ ViewService
         │
         └─ ViewService ── ephemeral moderator workspace
                    │
                    └─ Telegram Bot API
```

## Дерево

```text
app/
  config.py                 env/settings
  filters.py                moderator/user routing filters
  main.py                   dependency wiring + polling
  middlewares.py            DB session + per-moderator serialization
  db/
    base.py                 DeclarativeBase
    models.py               all persistent entities
    session.py              async SQLite engine + WAL pragmas
  domain/
    enums.py                sender/kind/list enums
    chat_rules.py           pure list classification rules
    rendering.py            grouping same-author source text into logical UI blocks
  handlers/
    common.py               /start
    user.py                 text/photo ingestion
    moderator.py            lists, paging, info, ban, message relay
  keyboards/
    moderator.py            all inline keyboards/callback formats
  services/
    chats.py                DB/business operations
    notifier.py             10-second debounce and notifications
    views.py                open/render/delete moderator workspace
    housekeeping.py         23-hour automatic cleanup
  utils/
    html.py                 escaping/truncation
    text.py                 safe split by escaped Telegram length
    time.py                 UTC helpers
alembic/
  versions/0001_initial.py  v2 schema from scratch
scripts/
  setup_venv.*              create .venv + install dependencies
  run.*                     migrate then launch
 tests/
  test_chat_rules.py
  test_rendering.py
  test_schema.py
```

## Database

### users
One row = one permanent support chat.

Important columns:

- `telegram_id` PK;
- `is_banned`;
- `created_at`;
- `last_user_message_at`;
- `last_support_message_at`.

There is deliberately no `tickets`/`conversations` table. The user's Telegram ID is the permanent conversation key.

### support_messages
Immutable-ish source history. One Telegram message from a human = one DB row.

- `user_id` — permanent chat;
- `sender_type`: `user|moderator`;
- `sender_telegram_id`;
- `sender_alias` — moderator alias at send time;
- `kind`: `text|photo`;
- `text` — text or photo caption;
- `photo_file_id` — Telegram reusable file_id;
- `telegram_message_id` — original incoming message ID;
- `notification_dispatched_at` — null while a user message belongs to an unflushed burst;
- `created_at`.

UI grouping must NEVER rewrite these rows.

### moderator_participants
Materialized participation relation for the `Мои` list.

Unique `(user_id, moderator_id)`, plus first/last reply time and reply count.

### moderator_sessions
Current ephemeral moderator state.

- `moderator_id` PK;
- `active_user_id` — null outside a user chat;
- `active_page` — 0 is newest page;
- `last_rendered_message_id` — prevents duplicate live rendering;
- `opened_at`;
- `last_activity_at`.

There is **no lock/assignment semantics** in this table. Multiple rows may have the same `active_user_id`.

### moderator_view_messages
Every Telegram message ID that belongs to a temporary rendered workspace. On switch/exit the bot deletes these IDs and removes the rows.

### audit_logs
Currently records moderator replies and ban/unban operations. Expand here for future moderation/audit actions.

## Key invariants

1. One user = one permanent history.
2. No ticket lifecycle and no close/reopen.
3. No chat owner/assignee.
4. Multiple moderators may simultaneously answer the same user.
5. Only text/photo are user-support payloads.
6. Raw source messages are persisted before UI aggregation.
7. Text grouping/packing is render-only.
8. Same-author text first becomes logical blocks; adjacent text blocks from different authors may then share one Telegram message while retaining separate labels.
9. Photos are never merged into a text render block and always break text packing.
10. User-facing moderator identity is the configured alias saved on the message.
11. `Мои` means active + participant relation, not ownership.
12. `last_rendered_message_id` is per moderator, not global.
13. A moderator reply marks the currently pending user burst as dispatched.
14. Telegram read state is never fabricated; no proxy delivery/read marker is rendered.
15. Workspace deletion failures must not block switching chats.
16. Per-moderator asyncio locks serialize render/delete operations inside one polling process.
17. `ModeratorSerialMiddleware` serializes all message/callback updates from the same moderator, so rapid replies cannot reorder.

## History render packing

`ChatService.history()` pages by **10 raw `support_messages` rows**. `domain/rendering.py` first groups consecutive text from the same logical author. `ViewService._render_page()` then buffers all adjacent text blocks until a photo or page end and packs their rendered HTML sections into as few Telegram `sendMessage` calls as possible.

The packer counts **visible text after HTML entity parsing** and fills Telegram messages up to the Bot API 4096-character text limit. There are no artificial 2800/3000/3900 render ceilings. Every section keeps its own `👤/🛡` label and timestamp. Delivery/read proxy markers are not rendered. A photo is always sent separately and flushes the pending text run.

## Moderator UI protocol

Inline callbacks are used for list navigation and opening a chat:

```text
menu
bucket:<new|active|mine|old>:<page>
chat:open:<user_id>:<history_page>
noop
```

Old `chat:page:*` / `chat:back` / `chat:info:*` callbacks are accepted only as v2.1 compatibility for already-rendered workspaces; v2.2 does not create them.

Inside an open chat, controls are a persistent reply keyboard. Reserved texts include `⬅️ Старее`, `📄 X/Y`, `Новее ➡️`, `ℹ️ Инфо`, `🚫 Бан` / `✅ Разбанить`, `◀️ К спискам`, plus ban confirmation/cancel. These handlers run before the generic moderator message handler, so control texts cannot leak to the user.

## Incoming user path

1. `handlers/user.py` upserts profile.
2. Reject if banned.
3. Reject unsupported payload.
4. Insert one `support_messages` row.
5. Update `last_user_message_at`.
6. Commit the source message.
7. `NotificationDebouncer.deliver_live()` immediately appends it to every moderator workspace currently opened on this user, without reopening the chat.
8. `NotificationDebouncer.enqueue(user_id)` moves the compact-notification deadline to now + 10 sec.
9. Worker flushes after silence; open viewers only get a recovery live-render attempt, while other moderators get one compact notification and `Открыть диалог`.
10. Selected source rows get `notification_dispatched_at`.

Recovery: on process startup, `recover_pending()` finds saved but unflushed user rows and schedules them again.

## Moderator reply path

1. Resolve `moderator_sessions.active_user_id`.
2. Validate text/photo and ban state.
3. Send to user as bot with `🛡 alias` formatting.
4. Insert source history row and update participant relation.
5. Mark existing unflushed user rows as dispatched (the reply handled that burst).
6. Commit DB to release SQLite write lock.
7. Delete moderator's raw incoming Telegram message when possible.
8. Broadcast formatted history representation to every moderator currently viewing this user on page 0.
9. If sender replied while browsing an older page, switch the sender to page 0 after sending.

## Concurrency notes

SQLite is configured with:

- WAL;
- `synchronous=NORMAL`;
- `busy_timeout=10000`;
- foreign keys enabled.

`ModeratorSerialMiddleware` serializes all incoming updates from one moderator, preserving the order of rapid replies and UI actions. `ViewService` additionally has one in-process `asyncio.Lock` per moderator so `open_chat`, cleanup, live user rendering and moderator broadcasts do not interleave destructively in a single polling process. Different moderators remain concurrent.

For multiple application processes, replace these local locks and the in-memory debounce scheduler with distributed coordination (Redis is the obvious next step).

## Telegram deletion limit

Bot API can delete incoming and outgoing private-chat messages only within its documented deletion window. `VIEW_TTL_HOURS=23` plus `HousekeepingService` keeps normal moderator workspaces safely below that window.

If the process is offline past Telegram's deletion limit, old workspace messages may remain in a moderator's Telegram chat. DB state is still cleaned so the application can continue.

## Best v3 extensions

- full-text search over support history;
- internal moderator notes not visible to user;
- configurable retention/export;
- Redis debounce/locks for multi-instance deployment;
- web admin panel;
- moderator analytics;
- canned replies;
- per-user tags;
- optional photo album rendering.
