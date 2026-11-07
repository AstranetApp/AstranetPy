import time
from AstranetPy import Client, aliases

TOKEN = ""

client = Client(TOKEN)

QUESTIONS = [
    {"q": "Столица Австралии?",            "options": ["Сидней", "Канберра", "Мельбурн"], "answer": 1},
    {"q": "Сколько будет 2 + 2 * 2?",      "options": ["8", "6", "4"],                    "answer": 1},
    {"q": "На чём написан бэкенд Astranet?", "options": ["Python", "Go", "Rust"],          "answer": 1},
    {"q": "Что заменяет вебсокеты у ботов?", "options": ["SSE", "Long-poll", "gRPC"],      "answer": 0},
]

sessions = {}


def question_view(uid):
    "Текст и сырая клавиатура текущего вопроса игрока."
    s = sessions[uid]
    q = QUESTIONS[s["q"]]
    kb = [[{"text": opt, "callback_data": f"ans:{i}"}] for i, opt in enumerate(q["options"])]
    return f"❓ Вопрос {s['q'] + 1}/{len(QUESTIONS)}\n\n{q['q']}", kb


@client.event("on_text_message")
def on_text(event):
    msg = event.message

    if msg.author.userId == client.uid:
        return

    text = (msg.content or "").strip()
    cmd = text[1:].split()[0] if text.startswith("/") else ""
    if cmd in ("quiz", "start"):
        sessions[msg.author.userId] = {"q": 0, "score": 0}
        body, kb = question_view(msg.author.userId)
        # get_account(comId) -> the Client itself for DMs (/g) or a SubClient
        # for a community thread (/x{comId}); both expose the Amino-style
        # send_message(chatId, message, ...).
        client.get_account(event.comId).send_message(
            msg.chatId, body, replyTo=msg.messageId, keyboard=kb)
        return

    if cmd in ("rights", "aliases"):
        # Права бота именно ТУТ: в сообществе — get_aliases(comId) (кэшируется
        # и сам обновляется по SSE-событию aliases_changed), в ЛС — глобальный
        # набор из bot-login. pendingApproval — что заработает, как только
        # лидеры сообщества одобрят.
        if event.comId:
            view = client.get_aliases(event.comId)
            body = "Мои права здесь: " + (", ".join(view["aliases"]) or "никаких")
            if view.get("pendingApproval"):
                body += "\n⏳ Ждут одобрения лидеров: " + ", ".join(view["pendingApproval"])
        else:
            body = "Глобально активно: " + (", ".join(client.aliases) or "ничего")
        client.get_account(event.comId).send_message(
            msg.chatId, body, replyTo=msg.messageId)


@client.event("on_callback_query")
def on_callback(payload):
    data = payload.get("callback_data") or payload.get("callbackData")
    uid = payload.get("fromUid")
    com_id = payload.get("ndcId")
    chat_id = payload.get("threadId")
    message_id = payload.get("messageId")

    def edit(body, kb=None):
        client.get_account(com_id).edit_message(
            chat_id, message_id, content=body, keyboard=kb)

    if data == "restart":
        sessions[uid] = {"q": 0, "score": 0}
        body, kb = question_view(uid)
        edit(body, kb)
        return

    s = sessions.get(uid)
    if s is None:
        edit("Сессия истекла. Набери /quiz заново.")
        return

    if data == "next":
        s["q"] += 1
        body, kb = question_view(uid)
        edit(body, kb)
        return

    if data.startswith("ans:"):
        chosen = int(data.split(":")[1])
        q = QUESTIONS[s["q"]]
        if chosen == q["answer"]:
            s["score"] += 1
            head = "✅ Верно!"
        else:
            head = f"❌ Неверно. Правильный ответ: {q['options'][q['answer']]}"

        if s["q"] == len(QUESTIONS) - 1:
            edit(f"{head}\n\n🏁 Итог: {s['score']}/{len(QUESTIONS)}",
                 [[{"text": "🔄 Заново", "callback_data": "restart"}]])
        else:
            edit(f"{head}\n\nСчёт: {s['score']}/{len(QUESTIONS)}",
                 [[{"text": "➡️ Дальше", "callback_data": "next"}]])


# ── События о самом боте (приходят по SSE, кэш прав уже обновлён) ──────────

@client.event("on_aliases_changed")
def on_aliases_changed(payload):
    # ndcId 0 — владелец пересобрал набор в BotFather (кэш сброшен целиком),
    # иначе — админы сообщества payload["ndcId"] изменили overrides.
    where = "BotFather" if not payload.get("ndcId") else f"x{payload['ndcId']}"
    print(f"🔧 Права изменены ({where}): активно {', '.join(payload.get('aliases') or []) or 'ничего'}")


@client.event("on_community_joined")
def on_community_joined(payload):
    print(f"➕ Добавили в «{payload.get('name') or payload['ndcId']}» "
          f"(x{payload['ndcId']}): {', '.join(payload.get('aliases') or []) or 'ничего'}")
    if payload.get("pendingApproval"):
        print("   ⏳ попросите лидеров одобрить:", ", ".join(payload["pendingApproval"]))


@client.event("on_community_removed")
def on_community_removed(payload):
    print(f"➖ Убрали из x{payload['ndcId']}")


if __name__ == "__main__":
    client.get_me()  # валидация токена + старт SSE
    print(f"Запущен @{client.nickname} ({client.uid})")

    # Полная карта прав одним вызовом: все сообщества, где бот состоит, и что
    # реально активно в каждом. bot-login этого намеренно не отдаёт — он
    # только "getMe"; карта живёт на GET /g/s/bot/me/aliases.
    overview = client.get_aliases()
    print(f"Сообществ: {len(overview['communities'])}")
    for com in overview["communities"]:
        line = f"  x{com['ndcId']} «{com['name'] or '?'}»: {', '.join(com['aliases']) or '—'}"
        if com["pendingApproval"]:
            line += f" | ждут одобрения: {', '.join(com['pendingApproval'])}"
        print(line)
    if client.has_alias(aliases.USERS_DM):
        print("Могу писать пользователям первым (users.dm включён глобально)")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        client.stop_sse()
