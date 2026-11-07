# pylint: disable=invalid-name
"""
Shared client surface for Astranet bots.

Mirrors AminoLightPy's ``AbstractClient``: a base class holding every method that
is identical between the *global* scope (:class:`~AstranetPy.client.Client`,
``path="/g"``) and a *community* scope (:class:`~AstranetPy.sub_client.SubClient`,
``path="/x{comId}"``). The only difference between the two is the URL prefix,
captured once in ``self.path`` — exactly as in AminoLightPy, so bots written
against the old ``client.send_message(chatId, ...)`` /
``sub_client.send_message(chatId, ...)`` API keep working.

Each method is ported one-to-one from AminoLightPy and re-pointed at the GoMino
backend. Methods whose Amino endpoint does not exist for bots on GoMino (or is
blocked by ``RequireNotBot``) are intentionally absent — see MIGRATION_PLAN.md.
"""

from typing import BinaryIO

from requests import Session

from .session import upload_media
from .lib.util import exceptions, objects


# File-kind -> Astranet chat message type (internal/models/chat/message.go).
# Image is the default for a raw upload.
_FILETYPE_TO_TYPE = {
    "image": 3,
    "voice": 2,
    "audio": 2,
    "video": 4,
}


def _coerce_keyboard(keyboard):
    """
    Normalize any accepted keyboard form to the bare 2-D array that goes into
    ``extensions.inlineKeyboard`` (``[[button, ...], ...]``).

    Accepts an ``InlineKeyboard`` (via ``to_keyboard()``), a ``{"rows": [...]}``
    dict, or an already-bare 2-D list of button dicts.
    """
    if hasattr(keyboard, "to_keyboard"):
        return keyboard.to_keyboard()
    if isinstance(keyboard, dict) and "rows" in keyboard:
        return keyboard["rows"]
    return keyboard


class AbstractClient:
    "Methods common to the global client and every community sub-client."

    def __init__(self, session: Session, path: str = "/g"):
        # ``path`` is the scope prefix: "/g" (global / DM) or "/x{comId}".
        self.path = path
        self.session = session

    # ------------------------------------------------------------------ #
    # People
    # ------------------------------------------------------------------ #

    def get_user_info(self, userId: str) -> objects.UserProfile:
        """
        Information about a user.

        **Parameters**
            - **userId** : ID of the user.

        **Returns**
            - :class:`UserProfile <AstranetPy.lib.util.objects.UserProfile>`

        GoMino: ``GET {path}/s/user-profile/{userId}`` (OptionalAuth) →
        ``{"userProfile": {...}}``. Identical shape and route to Amino.
        """
        response = self.session.get(f"{self.path}/s/user-profile/{userId}")
        return objects.UserProfile(response.json()["userProfile"]).UserProfile

    # ------------------------------------------------------------------ #
    # Chat threads (read)
    # ------------------------------------------------------------------ #

    def get_chat_thread(self, chatId: str) -> objects.Thread:
        """
        Metadata for a chat thread (title, type, members count, …).

        **Parameters**
            - **chatId** : ID of the chat.

        **Returns**
            - :class:`Thread <AstranetPy.lib.util.objects.Thread>`

        GoMino: ``GET {path}/s/chat/thread/{chatId}`` → ``{"thread": {...}}`` —
        identical to Amino.
        """
        response = self.session.get(f"{self.path}/s/chat/thread/{chatId}")
        return objects.Thread(response.json()["thread"]).Thread

    def get_chat_threads(self, start: int = 0, size: int = 25) -> objects.ThreadList:
        """
        Chats the bot is a member of.

        **Parameters**
            - *start* : Where to start the list.
            - *size* : Size of the list.

        **Returns**
            - :class:`ThreadList <AstranetPy.lib.util.objects.ThreadList>`

        GoMino: ``GET {path}/s/chat/thread?type=joined-all`` → ``{"threadList"}``.
        Amino's ``joined-me`` filter is renamed ``joined-all`` server-side; the
        result shape is unchanged.
        """
        params = {"type": "joined-all", "start": start, "size": size}
        response = self.session.get(f"{self.path}/s/chat/thread", params=params)
        return objects.ThreadList(response.json()["threadList"]).ThreadList

    def get_chat_users(self, chatId: str, start: int = 0, size: int = 25,
                       q: str = None) -> objects.UserProfileList:
        """
        Members of a chat thread.

        **Parameters**
            - **chatId** : ID of the chat.
            - *start* / *size* : pagination.
            - *q* : optional nickname filter (Astranet extension; Amino ignored it).

        **Returns**
            - :class:`UserProfileList <AstranetPy.lib.util.objects.UserProfileList>`

        GoMino: ``GET {path}/s/chat/thread/{chatId}/member`` → ``{"memberList"}``,
        where each entry is a flat author object (``role``/``alertOption`` are
        extra top-level fields), so the list feeds straight into UserProfileList.
        """
        params = {"start": start, "size": size}
        if q:
            params["q"] = q
        response = self.session.get(
            f"{self.path}/s/chat/thread/{chatId}/member", params=params)
        member_list = response.json().get("memberList") or []
        return objects.UserProfileList(member_list).UserProfileList

    # ------------------------------------------------------------------ #
    # Messaging
    # ------------------------------------------------------------------ #

    def send_message(self, chatId: str, message: str = None, messageType: int = 0,
                     file: BinaryIO = None, fileType: str = None, replyTo: str = None,
                     mentionUserIds: list = None, stickerId: str = None,
                     keyboard=None, mediaValue: str = None, clientRefId: int = None,
                     embedId: str = None, embedType: int = None, embedLink: str = None,
                     embedTitle: str = None, embedContent: str = None,
                     embedImage: BinaryIO = None, linkSnippet: list = None) -> objects.Message:
        """
        Send a message to a chat thread.

        **Parameters** (Amino-compatible)
            - **chatId** : ID of the chat.
            - **message** : text content.
            - **messageType** : message type (defaults to 0/text).
            - **file** : a binary file to upload and send (image/voice/video).
            - **fileType** : ``"image"`` (default), ``"voice"``/``"audio"`` or ``"video"``.
            - **replyTo** : message ID to reply to.
            - **mentionUserIds** : list of user IDs to mention (use ``@`` in text).
            - **stickerId** : sticker ID to send.

        **Astranet additions**
            - **keyboard** : inline keyboard — an ``InlineKeyboard`` (``to_keyboard()``),
              a raw 2-D list of button dicts, or ``{"rows": [...]}``. Requires the
              ``inline.keyboards`` alias (default-on); stripped server-side otherwise.

        **Aliases** (enforced server-side): any send needs ``messages.send``;
        media/sticker sends additionally need ``media.send``. Both are basic
        (default-on) but a community admin can switch them off, and in the home
        community ``media.send`` is inert without approval.
            - **mediaValue** : a pre-uploaded media value (skip the upload step).
            - **clientRefId** : client-side dedup id echoed back on the message.

        **Not supported on Astranet** (accepted for source compatibility, ignored):
        ``embedId``/``embedType``/``embedLink``/``embedTitle``/``embedContent``/
        ``embedImage``/``linkSnippet`` — GoMino has no attached-object/link-snippet
        message field.

        **Returns**
            - :class:`Message <AstranetPy.lib.util.objects.Message>`
        """
        data = {"type": messageType, "content": message}

        if clientRefId is not None:
            data["clientRefId"] = clientRefId
        if replyTo:
            data["replyMessageId"] = replyTo

        if stickerId:
            # Astranet: sticker is type 100 (Amino used type 3).
            data["content"] = None
            data["type"] = 100
            data["stickerId"] = stickerId

        if file is not None or mediaValue is not None:
            data["content"] = None
            data["mediaValue"] = mediaValue if mediaValue is not None else upload_media(self.session, file)
            data["type"] = _FILETYPE_TO_TYPE.get((fileType or "image").lower(), 3)

        extensions = {}
        if mentionUserIds:
            extensions["mentionedArray"] = [{"uid": uid} for uid in mentionUserIds]
        if keyboard is not None:
            extensions["inlineKeyboard"] = _coerce_keyboard(keyboard)
        if extensions:
            data["extensions"] = extensions

        response = self.session.post(
            url=f"{self.path}/s/chat/thread/{chatId}/message",
            json=data,
        )
        return objects.Message(response.json()["message"]).Message

    def send_web_message(self, chatId: str, message: str = None, messageType: int = 0,
                         icon: str = None, **kwargs) -> objects.Message:
        """
        Amino-compat shim: aminofix's ``send_web_message`` (the web-API send,
        used by old bots to dodge message signing). Astranet has no signing and
        no separate web endpoint, so this simply delegates to
        :meth:`send_message`. ``icon`` is accepted and ignored.
        """
        return self.send_message(chatId, message=message, messageType=messageType, **kwargs)

    def send_image(self, chatId: str, file: BinaryIO, **kwargs) -> objects.Message:
        "Shorthand for ``send_message(..., file=file, fileType='image')``."
        return self.send_message(chatId, file=file, fileType="image", **kwargs)

    def send_voice(self, chatId: str, file: BinaryIO, **kwargs) -> objects.Message:
        "Shorthand for ``send_message(..., file=file, fileType='voice')``."
        return self.send_message(chatId, file=file, fileType="voice", **kwargs)

    def send_video(self, chatId: str, file: BinaryIO, **kwargs) -> objects.Message:
        "Shorthand for ``send_message(..., file=file, fileType='video')``."
        return self.send_message(chatId, file=file, fileType="video", **kwargs)

    def send_sticker(self, chatId: str, stickerId: str, **kwargs) -> objects.Message:
        "Shorthand for ``send_message(..., stickerId=stickerId)``."
        return self.send_message(chatId, stickerId=stickerId, **kwargs)

    def edit_message(self, chatId: str, messageId: str, content: str = None,
                     keyboard=None, extensions: dict = None) -> objects.Message:
        """
        Edit a message's text and/or inline keyboard. **New on Astranet** — Amino
        had no message editing.

        Only the author (the bot itself) may edit. Editing just the keyboard
        (``content=None``) swaps the buttons in place; passing ``keyboard=[]``
        removes them.

        **Parameters**
            - **chatId** : ID of the chat.
            - **messageId** : ID of the message to edit.
            - **content** : new text (leave ``None`` to keep / keyboard-only edit).
            - **keyboard** : new inline keyboard (any form accepted by send_message).
            - **extensions** : extra extensions to merge into the request.

        **Returns**
            - :class:`Message <AstranetPy.lib.util.objects.Message>`

        GoMino: ``POST {path}/s/chat/thread/{chatId}/message/{messageId}`` →
        ``{"message": {...}}``.
        """
        data = {}
        if content is not None:
            data["content"] = content
        ext = dict(extensions) if extensions else {}
        if keyboard is not None:
            ext["inlineKeyboard"] = _coerce_keyboard(keyboard)
        if ext:
            data["extensions"] = ext

        response = self.session.post(
            url=f"{self.path}/s/chat/thread/{chatId}/message/{messageId}",
            json=data,
        )
        return objects.Message(response.json()["message"]).Message

    def delete_message(self, chatId: str, messageId: str, asStaff: bool = False,
                       reason: str = None) -> int:
        """
        Delete a message from a chat.

        **Parameters**
            - **chatId** : ID of the chat.
            - **messageId** : ID of the message.
            - *asStaff* / *reason* : accepted for Amino source compatibility but
              ignored — GoMino has no separate ``/admin`` delete endpoint yet.

        Deleting another member's message requires the ``moderation.delete`` alias
        (approved in the community); the bot's own messages always delete.

        **Returns** the HTTP status code (200 on success).

        GoMino: ``DELETE {path}/s/chat/thread/{chatId}/message/{messageId}``.
        """
        return self.session.delete(
            f"{self.path}/s/chat/thread/{chatId}/message/{messageId}"
        ).status_code

    def get_chat_messages(self, chatId: str, size: int = 25, pageToken: str = None,
                          start: int = 0, before: str = None, after: str = None,
                          around: str = None) -> objects.GetMessages:
        """
        Message history for a chat.

        **Parameters**
            - **chatId** : ID of the chat.
            - *size* : page size.
            - *pageToken* : accepted for Amino compatibility but **ignored** —
              GoMino paginates by ``start`` / time cursors, not opaque tokens.
            - *start* : offset (GoMino).
            - *before* / *after* : ISO-8601 timestamps (RFC3339) — messages
              before/after that time.
            - *around* : a messageId to center the window on (jump-to-message).

        **Returns**
            - :class:`GetMessages <AstranetPy.lib.util.objects.GetMessages>`

        GoMino: ``GET {path}/s/chat/thread/{chatId}/message`` → ``{"messageList"}``.
        """
        params = {"start": start, "size": size}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        if around:
            params["around"] = around
        response = self.session.get(
            f"{self.path}/s/chat/thread/{chatId}/message", params=params)
        return objects.GetMessages(response.json()).GetMessages

    def get_message_info(self, chatId: str, messageId: str) -> objects.Message:
        """
        Information about a single message.

        GoMino has no GET-single-message route, so this is emulated: it requests
        the window *around* ``messageId`` and returns the matching message. Raises
        :class:`NotFound` if it isn't in the returned window.

        **Returns**
            - :class:`Message <AstranetPy.lib.util.objects.Message>`
        """
        response = self.session.get(
            f"{self.path}/s/chat/thread/{chatId}/message",
            params={"around": messageId, "size": 25},
        )
        for raw in response.json().get("messageList") or []:
            if raw.get("messageId") == messageId:
                return objects.Message(raw).Message
        raise exceptions.UnexistentData

    def mark_as_read(self, chatId: str, messageId: str = None) -> int:
        """
        Mark a chat as read (clears unread / mention counters).

        ``messageId`` is accepted for Amino compatibility; GoMino marks the whole
        thread read and does not need it.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/chat/thread/{chatId}/mark-as-read``.
        """
        return self.session.post(
            f"{self.path}/s/chat/thread/{chatId}/mark-as-read"
        ).status_code

    # ------------------------------------------------------------------ #
    # Membership
    # ------------------------------------------------------------------ #

    def join_chat(self, chatId: str) -> int:
        """
        Join a chat as the bot itself.

        Self-join works for public threads and DMs; non-public threads require an
        invite from a host/co-host (server-enforced).

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/chat/thread/{chatId}/member/{botUid}``.
        """
        return self.session.post(
            f"{self.path}/s/chat/thread/{chatId}/member/{self.uid}"
        ).status_code

    def leave_chat(self, chatId: str) -> int:
        """
        Leave a chat.

        **Returns** the HTTP status code.

        GoMino: ``DELETE {path}/s/chat/thread/{chatId}/member/{botUid}``.
        """
        return self.session.delete(
            f"{self.path}/s/chat/thread/{chatId}/member/{self.uid}"
        ).status_code

    def start_chat(self, userId, message: str = None, title: str = None,
                   content: str = None, isGlobal: bool = False,
                   publishToGlobal: bool = False) -> objects.Thread:
        """
        Start a chat with a user or a list of users.

        Thread type is inferred to fit GoMino's model: a single invitee →
        **DM (type 1)** (an existing DM is reused); ``isGlobal``/``publishToGlobal``
        → **public (type 2)**; otherwise → **group (type 0)**. Opening a DM with a
        user who hasn't messaged first needs the ``users.dm`` alias; creating any
        non-DM thread (group/public) needs the ``chats.create`` alias — both are
        opt-in, enabled by the developer in BotFather.

        ``message`` has no dedicated field on GoMino's create endpoint, so when
        given it is sent as a follow-up message into the new thread.

        **Returns**
            - :class:`Thread <AstranetPy.lib.util.objects.Thread>`

        GoMino: ``POST {path}/s/chat/thread`` → ``{"thread": {...}}``.
        """
        if isinstance(userId, str):
            inviteeUids = [userId]
        elif isinstance(userId, (list, tuple)):
            inviteeUids = list(userId)
        else:
            raise exceptions.WrongType(type(userId))

        if isGlobal or publishToGlobal:
            threadType = 2
        elif len(inviteeUids) == 1:
            threadType = 1
        else:
            threadType = 0

        data = {
            "type": threadType,
            "title": title or "",
            "content": content or "",
            "inviteeUids": inviteeUids,
        }
        response = self.session.post(f"{self.path}/s/chat/thread", json=data)
        thread = objects.Thread(response.json()["thread"]).Thread

        if message and thread.chatId:
            self.send_message(thread.chatId, message)

        return thread

    def invite_to_chat(self, userId, chatId: str) -> int:
        """
        Invite a user or list of users to a chat.

        **Parameters**
            - **userId** : a single user id or a list of ids.
            - **chatId** : ID of the chat.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/chat/thread/{chatId}/member/invite`` with
        ``{"uids": [...]}``.
        """
        if isinstance(userId, str):
            userIds = [userId]
        elif isinstance(userId, (list, tuple)):
            userIds = list(userId)
        else:
            raise exceptions.WrongType(type(userId))

        return self.session.post(
            url=f"{self.path}/s/chat/thread/{chatId}/member/invite",
            json={"uids": userIds},
        ).status_code

    def kick(self, userId: str, chatId: str, allowRejoin: bool = True) -> int:
        """
        Kick a member from a chat.

        **Parameters**
            - **userId** : ID of the user to kick.
            - **chatId** : ID of the chat.
            - *allowRejoin* : if ``False``, also bans them from rejoining.

        Requires the bot to be host/co-host of the thread (server-enforced).

        **Returns** the HTTP status code.

        GoMino: ``DELETE {path}/s/chat/thread/{chatId}/member/{userId}?allowRejoin=``.
        """
        params = {"allowRejoin": int(allowRejoin)}
        return self.session.delete(
            url=f"{self.path}/s/chat/thread/{chatId}/member/{userId}",
            params=params,
        ).status_code

    def delete_chat(self, chatId: str) -> int:
        """
        Delete a chat (host only).

        **Returns** the HTTP status code.

        GoMino: ``DELETE {path}/s/chat/thread/{chatId}``.
        """
        return self.session.delete(f"{self.path}/s/chat/thread/{chatId}").status_code

    def transfer_organizer(self, chatId: str, userIds) -> int:
        """
        Transfer thread ownership (host) to another member.

        **Parameters**
            - **chatId** : ID of the chat.
            - **userIds** : the new host's id (a list is accepted for Amino
              compatibility — only the first id is used, since GoMino transfers to
              exactly one user).

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/chat/thread/{chatId}/member/transfer-organizer``
        with ``{"uid": "..."}``. (Amino used ``/transfer-organizer`` + ``uidList``;
        ``accept_host`` has no GoMino equivalent and is not provided.)
        """
        uid = userIds[0] if isinstance(userIds, (list, tuple)) else userIds
        return self.session.post(
            url=f"{self.path}/s/chat/thread/{chatId}/member/transfer-organizer",
            json={"uid": uid},
        ).status_code

    # Amino alias.
    transfer_host = transfer_organizer

    # ------------------------------------------------------------------ #
    # Chat moderation
    # ------------------------------------------------------------------ #

    def set_view_only(self, chatId: str, viewOnly: bool = True) -> int:
        """
        Toggle a thread's view-only (read-only) mode.

        Allowed for the thread host/co-host, a community curator+, or a bot
        holding the ``moderation.readonly`` alias.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/chat/thread/{chatId}/view-only/{enable|disable}``.
        """
        action = "enable" if viewOnly else "disable"
        return self.session.post(
            f"{self.path}/s/chat/thread/{chatId}/view-only/{action}"
        ).status_code

    def pin_message(self, chatId: str, messageId: str) -> int:
        """
        Pin a message in a thread.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/chat/thread/{chatId}/message/{messageId}/pin``.
        """
        return self.session.post(
            f"{self.path}/s/chat/thread/{chatId}/message/{messageId}/pin"
        ).status_code

    def unpin_message(self, chatId: str, messageId: str) -> int:
        """
        Unpin a message.

        **Returns** the HTTP status code.

        GoMino: ``DELETE {path}/s/chat/thread/{chatId}/message/{messageId}/pin``.
        """
        return self.session.delete(
            f"{self.path}/s/chat/thread/{chatId}/message/{messageId}/pin"
        ).status_code

    # ------------------------------------------------------------------ #
    # Following / blocking
    # ------------------------------------------------------------------ #

    def get_user_following(self, userId: str, start: int = 0,
                           size: int = 25) -> objects.UserProfileList:
        """
        Users that ``userId`` is following.

        **Returns** :class:`UserProfileList`.

        GoMino: ``GET {path}/s/user-profile/{userId}/joined`` → ``{"userProfileList"}``.
        """
        response = self.session.get(
            f"{self.path}/s/user-profile/{userId}/joined",
            params={"start": start, "size": size},
        )
        return objects.UserProfileList(response.json()["userProfileList"]).UserProfileList

    def get_user_followers(self, userId: str, start: int = 0,
                           size: int = 25) -> objects.UserProfileList:
        """
        Users that follow ``userId``.

        **Returns** :class:`UserProfileList`.

        GoMino: ``GET {path}/s/user-profile/{userId}/member`` → ``{"userProfileList"}``.
        """
        response = self.session.get(
            f"{self.path}/s/user-profile/{userId}/member",
            params={"start": start, "size": size},
        )
        return objects.UserProfileList(response.json()["userProfileList"]).UserProfileList

    def get_blocked_users(self, start: int = 0, size: int = 25) -> objects.UserProfileList:
        """
        Users the bot has blocked.

        **Returns** :class:`UserProfileList`.

        GoMino: ``GET {path}/s/user-profile/blocked`` → ``{"userList": [...]}``
        (each entry exposes ``uid``/``nickname``/``icon``).
        """
        response = self.session.get(
            f"{self.path}/s/user-profile/blocked",
            params={"start": start, "size": size},
        )
        return objects.UserProfileList(response.json().get("userList") or []).UserProfileList

    def block(self, userId: str) -> int:
        """
        Block a user.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/user-profile/{userId}/block`` (allowed for bots).
        """
        return self.session.post(f"{self.path}/s/user-profile/{userId}/block").status_code

    def unblock(self, userId: str) -> int:
        """
        Unblock a user.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/user-profile/{userId}/unblock`` (POST, not DELETE
        as in Amino).
        """
        return self.session.post(f"{self.path}/s/user-profile/{userId}/unblock").status_code

    def is_blocked(self, userId: str) -> bool:
        """
        Whether ``userId`` is blocked by the bot.

        GoMino: ``GET {path}/s/user-profile/{userId}/blocked-status`` →
        ``{"isBlocked": bool}``. (New convenience — no Amino equivalent.)
        """
        response = self.session.get(f"{self.path}/s/user-profile/{userId}/blocked-status")
        return bool(response.json().get("isBlocked"))

    def edit_profile(self, nickname: str = None, content: str = None,
                     icon: BinaryIO = None) -> int:
        """
        Edit the bot's own profile (nickname / bio / avatar).

        **Parameters**
            - **nickname** : new display name.
            - **content** : profile bio/description.
            - **icon** : an open image file (uploaded) or a pre-uploaded media value.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/user-profile/{botUid}`` with any of
        ``nickname``/``content``/``icon``.
        """
        data = {}
        if nickname is not None:
            data["nickname"] = nickname
        if content is not None:
            data["content"] = content
        if icon is not None:
            data["icon"] = icon if isinstance(icon, str) else upload_media(self.session, icon)
        return self.session.post(
            f"{self.path}/s/user-profile/{self.uid}", json=data
        ).status_code

    # ------------------------------------------------------------------ #
    # Profile wall comments
    # ------------------------------------------------------------------ #

    def comment(self, message: str, userId: str, replyTo: str = None,
                image: BinaryIO = None) -> int:
        """
        Comment on a user's profile wall.

        (Amino's ``comment`` also took ``blogId``/``wikiId``; those are
        community-only on Astranet — use the SubClient blog/wiki comment helpers.)

        **Parameters**
            - **message** : comment text.
            - **userId** : whose wall to comment on.
            - *replyTo* : a comment id to reply to.
            - *image* : an image file (uploaded) — sends a media comment.

        **Returns** the HTTP status code.

        GoMino: ``POST {path}/s/user-profile/{userId}/g-comment``.
        """
        data = {"content": message, "type": 0}
        if image is not None:
            value = image if isinstance(image, str) else upload_media(self.session, image)
            data["type"] = 2
            data["mediaList"] = [[100, value, None]]
        if replyTo:
            data["respondTo"] = replyTo
        return self.session.post(
            f"{self.path}/s/user-profile/{userId}/g-comment", json=data
        ).status_code

    # Amino alias for replying on a wall.
    def reply_wall(self, userId: str, commentId: str, message: str) -> int:
        "Reply to a wall comment (``comment`` with ``replyTo``)."
        return self.comment(message, userId=userId, replyTo=commentId)

    def get_wall_comments(self, userId: str, sorting: str = "newest",
                          start: int = 0, size: int = 25) -> objects.CommentList:
        """
        Comments on a user's profile wall.

        **Parameters**
            - **userId** : whose wall.
            - *sorting* : ``newest`` / ``oldest`` / ``top``.

        **Returns** :class:`CommentList`.

        GoMino: ``GET {path}/s/user-profile/{userId}/g-comment`` → ``{"commentList"}``.
        """
        sorting_map = {"newest": "newest", "oldest": "oldest", "top": "vote"}
        if sorting not in sorting_map:
            raise exceptions.WrongType(sorting)
        params = {"sort": sorting_map[sorting], "start": start, "size": size}
        response = self.session.get(
            f"{self.path}/s/user-profile/{userId}/g-comment", params=params)
        return objects.CommentList(response.json()["commentList"]).CommentList

    def delete_comment(self, commentId: str, userId: str) -> int:
        """
        Delete a wall comment.

        **Returns** the HTTP status code.

        GoMino: ``DELETE {path}/s/user-profile/{userId}/comment/{commentId}``.
        """
        return self.session.delete(
            f"{self.path}/s/user-profile/{userId}/comment/{commentId}"
        ).status_code
