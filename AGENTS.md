# AGENTS.md

## Проект

Telegram-бот «Тайный Санта» для групп. Русскоязычный интерфейс.

Стек: Python 3.12+, aiogram 3, SQLAlchemy 2 async, SQLite (aiosqlite),
pydantic-settings. Деплой — Docker / docker compose.

## Команды

```bash
python -m bot.main                 # запуск (нужен .env с BOT_TOKEN)
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest
python -m compileall -q bot
```

## Структура

- `bot/main.py` — запуск, polling, установка меню команд.
- `bot/config.py` — настройки из `.env`.
- `bot/constants.py` — статусы игр, лимиты.
- `bot/db/models.py` — модели: `Chat`, `User`, `Game`, `Participant`,
  `Assignment`, `ChatMember`.
- `bot/db/repo.py` — все запросы к БД. Новые запросы добавлять сюда, не
  размазывать по хендлерам.
- `bot/db/session.py` — engine и фабрика сессий, `init_db`.
- `bot/handlers/membership.py` — `my_chat_member`, `chat_member`.
- `bot/handlers/group.py` — команды в группах.
- `bot/handlers/dm.py` — личка, deep-link, вишлист, статистика.
- `bot/services/membership.py` — проверка членства, кэш, rate limit.
- `bot/services/draw.py` — жеребьёвка.
- `bot/services/texts.py` — тексты (HTML, экранирование).
- `bot/keyboards/inline.py` — inline-клавиатуры.
- `bot/middlewares/db.py` — сессия БД на апдейт, коммит после хендлера.

## Правила домена

- Одна активная игра на группу (`recruiting` или `started`).
- Новая игра возможна только после `/endgame` (или `/cancelgame`).
- Минимум участников для жеребьёвки — 3.
- Вишлист общий на пользователя (не на игру).
- При вступлении отдельное сообщение в группу не отправляется — только
  редактируется анонс. Список участников публикуется при старте игры.
- Жеребьёвка — алгоритм Саттоло: одна цепочка, без самоподарков.
- Бот должен быть администратором группы: иначе нет `chat_member` и
  невозможно надёжно отслеживать состав.

## Конвенции

- Все пользовательские строки в HTML-сообщениях пропускать через `esc()`.
- Сессию БД получать через middleware (`session` в аргументах хендлера).
  Middleware коммитит транзакцию после хендлера; явный `commit()` нужен,
  только если между записью и отправкой сообщений есть долгие API-вызовы.
- Проверку членства делать через `bot/services/membership.py`, не вызывать
  `get_chat_member` напрямую: там кэш и rate limit.
- Свежая проверка нужна при вступлении в игру и перед жеребьёвкой; для
  отображения списка достаточно кэша.
- Секреты только в `.env` (в git не попадают).
- Не добавлять зависимости без необходимости; стек зафиксирован в
  `requirements.txt`.

## Схема БД (кратко)

- `chats` — известные группы, `is_admin`, `is_active`.
- `users` — профиль и `wishlist`.
- `games` — игра, `status`, `announcement_msg_id`.
- `participants` — уникальная пара `(game_id, user_id)`.
- `assignments` — `(game_id, giver_id) -> receiver_id`, флаг `notified`.
- `chat_members` — кэш членства `(chat_id, user_id, status, updated_at)`.
