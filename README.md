# AstranetPy

Низкоуровневый Python-SDK для ботов [Astranet](https://astranetapp.com).

Обёртка над REST API бэкенда и потоком событий SSE: чаты, сообщения, медиа,
посты и вики сообществ, модерация, права бота (алиасы) и эфиры LiveKit.
Высокоуровневый фреймворк с декораторами и фильтрами лежит в соседнем репозитории
[AstranetBots](https://github.com/AstranetApp/AstranetBots), и для большинства ботов
лучше брать его.

API повторяет AminoLightPy (`Client` / `SubClient` / `objects.*`), поэтому
Amino-боты переносятся почти без правок.

## Требования

- Python 3.10+
- `requests`
- `livekit` (необязательно, нужен только для `LiveJoin.connect()` в эфирах)

## Установка

Пакет ставится клонированием: каталог репозитория и есть пакет.

```bash
mkdir mybot && cd mybot
git clone git@github.com:AstranetApp/AstranetPy.git
pip install requests
```

Скрипт бота кладётся в `mybot/` рядом с каталогом `AstranetPy/`. Если бот лежит
в другом месте, добавьте `mybot/` в `PYTHONPATH`.

## Токен

Бот создаётся в чате с **BotFather** в приложении Astranet. Токен имеет вид
`<uid>:<secret>` и передаётся в `Authorization: Bot …`. Почта и пароль ботам не нужны.

## Быстрый старт

```python
from AstranetPy import Client

client = Client("<uid>:<secret>")

@client.event("on_text_message")
def on_text(event):
    msg = event.message
    if msg.author.userId == client.uid:
        return
    if msg.content == "!ping":
        # Client для личек (/g) или SubClient для чата сообщества (/x{comId})
        client.get_account(event.comId).send_message(msg.chatId, "pong")

client.get_me()   # проверяет токен и запускает поток SSE
```

- `Client` работает в глобальной области (`/g/s`).
- `SubClient(comId, profile=client.profile)` работает в сообществе
  (`/x{comId}/s`). Боты работают в чатах сообществ, куда их добавили.

Полный пример — бот-викторина на сырых событиях с inline-кнопками:
[`examples/quiz_bot.py`](examples/quiz_bot.py).

## Права бота (алиасы)

Возможности бота задаются алиасами, список дублирует серверный каталог
(`AstranetPy.aliases`):

| Уровень | Что это | Примеры |
|---|---|---|
| Базовые | выдаются при создании бота | `messages.send`, `messages.reply`, `inline.keyboards`, `media.send` |
| Дополнительные | включаются владельцем в BotFather → 🔐 Permissions | `users.dm`, `chats.create`, `posts.create`, `comments.write`, `live.rooms` |
| Администраторские | работают только после одобрения лидерами сообщества | `moderation.delete`, `moderation.kick`, `moderation.readonly` |

Права меняются не чаще раза в 30 дней. Проверить права из кода:

```python
from AstranetPy import aliases

client.has_alias(aliases.USERS_DM)             # глобально
client.get_aliases()                           # все сообщества одним вызовом
sub.has_alias(aliases.MODERATION_DELETE)       # в конкретном сообществе
```

События SSE `aliases_changed`, `community_joined` и `community_removed` держат
эти ответы в актуальном состоянии.

## Эфиры (LiveKit)

Нужен алиас `live.rooms`. REST-вызовы возвращают `LiveJoin`: комнату, токен
LiveKit и адрес сервера.

```python
join = sub.join_live_room(chatId)      # или sub.start_live_room(chatId)
room = await join.connect()            # livekit.rtc.Room, нужен pip install livekit
...
await room.disconnect()
sub.leave_live_room(chatId, join.roomId)
```

Токен живёт 24 часа. Публиковать звук и видео можно, если бот зашёл спикером
(`as_listener=False`), стал хостом или вызвал `become_speaker`. LiveKit Agents
работают только в автономном режиме: подключите комнату сами и передайте её в
`AgentSession.start(room=...)`. Пример голосового ИИ-бота лежит в
[AstranetBots/examples/live_agent.py](https://github.com/AstranetApp/AstranetBots/blob/main/examples/live_agent.py).

## Структура

| Файл | Содержимое |
|---|---|
| `client.py` | `Client`: глобальная область, вход по токену, SSE |
| `sub_client.py` | `SubClient`: методы сообщества, модерация, эфиры |
| `abstract_client.py` | общие методы чатов и профилей |
| `session.py` | HTTP-сессия, загрузка медиа, `DEFAULT_BASE_URL` |
| `sse.py`, `events.py` | поток событий и разбор их по колбэкам |
| `aliases.py` | каталог прав бота |
| `live.py` | эфиры, `LiveJoin` |
| `lib/util/objects.py` | модели ответов API |
| `lib/util/exceptions.py` | исключения по `api:statuscode` |
