# pylint: disable=invalid-name
"""
Community-scoped Astranet bot client.

A drop-in for AminoLightPy's ``SubClient``: same constructor
(``SubClient(comId, profile=client.profile)``) and the same inherited chat /
people methods, but every request is prefixed with ``/x{comId}`` instead of
``/g``. Community-only methods (posts, wiki, moderation, leaderboards, …) live
here, ported from AminoLightPy and re-pointed at GoMino.

    client = Client(token); client.get_me()
    sub = SubClient(comId, profile=client.profile)
    sub.send_message(chatId, "hello from a community")
"""

from .abstract_client import AbstractClient
from .managers import Typing, Recording
from .live import LiveJoin, VOICE
from .lib.util import exceptions, objects


class SubClient(AbstractClient):
    "Bot client bound to a single community (``comId``)."

    def __init__(self, comId: int = None, *, profile: objects.UserProfile):
        self.profile = profile
        self.client = self.profile.client
        self.session = self.client.session

        super().__init__(self.session, f"/x{comId}")

        self.comId = comId

    @property
    def uid(self):
        "The bot's own user id, resolved from the parent client (after get_me)."
        return self.client.uid

    # ------------------------------------------------------------------ #
    # Own permissions in this community
    # ------------------------------------------------------------------ #

    def get_my_aliases(self, refresh: bool = False) -> dict:
        """
        What the bot may actually do in THIS community: effective ``aliases``,
        the admin's ``disabled``/``approved`` overrides, ``pendingApproval``
        (requested powers awaiting an admin's grant — the "ask the leaders for
        these" list) and a ``member`` flag. Cached on the parent client and
        kept current by the ``aliases_changed`` SSE event; ``refresh=True``
        forces a re-fetch.

        GoMino: ``GET /x{comId}/s/bot/me/aliases``.
        """
        return self.client.get_aliases(self.comId, refresh=refresh)

    def has_alias(self, alias: str) -> bool:
        """
        Whether the bot holds ``alias`` in THIS community (community-effective,
        not the global set — a power can be enabled here and absent elsewhere).
        First call fetches, then it's answered from cache.
        """
        return self.client.has_alias(alias, comId=self.comId)

    # ------------------------------------------------------------------ #
    # Presence (no-op — see managers.py)
    # ------------------------------------------------------------------ #

    def typing(self, chatId: str) -> Typing:
        return self.client.typing(chatId=chatId, comId=self.comId)

    def recording(self, chatId: str) -> Recording:
        return self.client.recording(chatId=chatId, comId=self.comId)

    # ================================================================== #
    # Members & public chats
    # ================================================================== #

    def get_all_users(self, type: str = "recent", start: int = 0, size: int = 25,
                      **kwargs) -> objects.UserProfileList:
        """
        Community members.

        ``type`` is passed through: GoMino supports ``leaders`` / ``curators``
        / ``members``; anything else (Amino's ``recent``/``banned``/…) returns
        the unfiltered roster. Extra kwargs (Amino's ``session=``) are ignored.

        GoMino: ``GET /x{comId}/s/community/member`` → ``{"userProfileList"}``.
        The result also answers ``.profile`` (Amino ``UserProfileCountList``
        compat), so ``get_all_users(...).profile.userId`` keeps working.
        """
        params = {"start": start, "size": size}
        if type:
            params["type"] = type
        response = self.session.get(
            f"/x{self.comId}/s/community/member", params=params)
        return objects.UserProfileList(response.json()["userProfileList"]).UserProfileList

    def get_public_chat_threads(self, type: str = "recommended", start: int = 0,
                                size: int = 25) -> objects.ThreadList:
        """
        Public chats of the community.

        GoMino: ``GET /x{comId}/s/chat/thread?type=public-all&filterType=...`` →
        ``{"threadList"}``.
        """
        params = {"type": "public-all", "filterType": type, "start": start, "size": size}
        response = self.session.get(f"/x{self.comId}/s/chat/thread", params=params)
        return objects.ThreadList(response.json()["threadList"]).ThreadList

    def search_users(self, nickname: str, start: int = 0, size: int = 25) -> dict:
        """
        Search members by nickname.

        GoMino: ``GET /x{comId}/s/search?q=...`` — returns the raw search payload
        (its shape mirrors the web client).
        """
        return self.session.get(
            f"/x{self.comId}/s/search",
            params={"q": nickname, "start": start, "size": size},
        ).json()

    # ================================================================== #
    # Blogs (posts)
    # ================================================================== #

    def post_blog(self, title: str, content: str, imageList: list = None,
                  captionList: list = None) -> int:
        """
        Publish a blog post.

        ``imageList`` are open image files (uploaded); ``captionList`` optionally
        pairs a caption with each. Returns the HTTP status code.

        Requires the ``posts.create`` alias (opt-in, enabled in BotFather).

        GoMino: ``POST /x{comId}/s/blog`` with ``{title, content, mediaList}``.
        """
        from .session import upload_media
        mediaList = []
        if imageList:
            if captionList:
                for image, caption in zip(imageList, captionList):
                    mediaList.append([100, upload_media(self.session, image), caption])
            else:
                for image in imageList:
                    mediaList.append([100, upload_media(self.session, image), None])
        data = {"title": title, "content": content, "mediaList": mediaList}
        return self.session.post(f"/x{self.comId}/s/blog", json=data).status_code

    def edit_blog(self, blogId: str, title: str = None, content: str = None) -> int:
        "Edit a blog's title/content. GoMino: ``POST /x{comId}/s/blog/{blogId}``."
        data = {}
        if title is not None:
            data["title"] = title
        if content is not None:
            data["content"] = content
        return self.session.post(f"/x{self.comId}/s/blog/{blogId}", json=data).status_code

    def delete_blog(self, blogId: str) -> int:
        "Delete a blog. GoMino: ``DELETE /x{comId}/s/blog/{blogId}``."
        return self.session.delete(f"/x{self.comId}/s/blog/{blogId}").status_code

    def get_recent_blogs(self, start: int = 0, size: int = 25) -> objects.BlogList:
        "Recent community blogs. GoMino: ``GET /x{comId}/s/feed/blog-all`` → ``{blogList}``."
        response = self.session.get(
            f"/x{self.comId}/s/feed/blog-all", params={"start": start, "size": size})
        return objects.BlogList(response.json()["blogList"]).BlogList

    def get_user_blogs(self, userId: str, start: int = 0, size: int = 25) -> objects.BlogList:
        "A user's blogs. GoMino: ``GET /x{comId}/s/blog?type=user&q={userId}``."
        params = {"type": "user", "q": userId, "start": start, "size": size}
        response = self.session.get(f"/x{self.comId}/s/blog", params=params)
        return objects.BlogList(response.json()["blogList"]).BlogList

    def like_blog(self, blogId: str) -> int:
        "Like a blog. GoMino: ``POST /x{comId}/s/blog/{blogId}/g-vote`` ``{value:1}``."
        return self.session.post(
            f"/x{self.comId}/s/blog/{blogId}/g-vote", json={"value": 1}).status_code

    def unlike_blog(self, blogId: str) -> int:
        "Remove a blog like. GoMino: ``POST .../g-vote`` ``{value:0}``."
        return self.session.post(
            f"/x{self.comId}/s/blog/{blogId}/g-vote", json={"value": 0}).status_code

    def vote_poll(self, blogId: str, optionId: str) -> int:
        "Vote in a poll. GoMino: ``POST /x{comId}/s/blog/{blogId}/poll-vote`` ``{optionId}``."
        return self.session.post(
            f"/x{self.comId}/s/blog/{blogId}/poll-vote", json={"optionId": optionId}).status_code

    # ================================================================== #
    # Wiki (items)
    # ================================================================== #

    def get_user_wikis(self, userId: str, start: int = 0, size: int = 25) -> objects.WikiList:
        """
        A user's wiki entries (Astranet items). Amino-compat: the returned
        objects expose ``wikiId`` (= itemId) and ``title`` (= label).

        GoMino: ``GET /x{comId}/s/item?uid={userId}`` → ``{"itemList"}``.
        """
        params = {"uid": userId, "start": start, "size": size}
        response = self.session.get(f"/x{self.comId}/s/item", params=params)
        return objects.WikiList(response.json().get("itemList") or []).WikiList

    def get_wiki_info(self, wikiId: str) -> objects.Wiki:
        "One wiki entry. GoMino: ``GET /x{comId}/s/item/{itemId}`` → ``{\"item\"}``."
        response = self.session.get(f"/x{self.comId}/s/item/{wikiId}")
        return objects.Wiki(response.json().get("item") or {}).Wiki

    def comment_wiki(self, wikiId: str, message: str, replyTo: str = None) -> int:
        """
        Comment on a wiki entry. Requires the ``comments.write`` alias (opt-in).

        GoMino: ``POST /x{comId}/s/item/{itemId}/comment``.
        """
        data = {"content": message, "type": 0}
        if replyTo:
            data["respondTo"] = replyTo
        return self.session.post(
            f"/x{self.comId}/s/item/{wikiId}/comment", json=data).status_code

    # ================================================================== #
    # Blog comments
    # ================================================================== #

    def comment_blog(self, blogId: str, message: str, replyTo: str = None) -> int:
        """
        Comment on a blog. Requires the ``comments.write`` alias (opt-in).

        GoMino: ``POST /x{comId}/s/blog/{blogId}/comment``.
        """
        data = {"content": message, "type": 0}
        if replyTo:
            data["respondTo"] = replyTo
        return self.session.post(f"/x{self.comId}/s/blog/{blogId}/comment", json=data).status_code

    def get_blog_comments(self, blogId: str, start: int = 0, size: int = 25) -> objects.CommentList:
        "Blog comments. GoMino: ``GET /x{comId}/s/blog/{blogId}/comment`` → ``{commentList}``."
        response = self.session.get(
            f"/x{self.comId}/s/blog/{blogId}/comment", params={"start": start, "size": size})
        return objects.CommentList(response.json()["commentList"]).CommentList

    def delete_blog_comment(self, blogId: str, commentId: str) -> int:
        "Delete a blog comment. GoMino: ``DELETE /x{comId}/s/blog/{blogId}/comment/{commentId}``."
        return self.session.delete(
            f"/x{self.comId}/s/blog/{blogId}/comment/{commentId}").status_code

    def upvote_comment(self, blogId: str, commentId: str) -> int:
        "Like a blog comment. GoMino: ``POST .../comment/{commentId}/g-vote`` ``{value:1}``."
        return self.session.post(
            f"/x{self.comId}/s/blog/{blogId}/comment/{commentId}/g-vote",
            json={"value": 1}).status_code

    def unvote_comment(self, blogId: str, commentId: str) -> int:
        "Remove a blog-comment like. GoMino: ``POST .../g-vote`` ``{value:0}``."
        return self.session.post(
            f"/x{self.comId}/s/blog/{blogId}/comment/{commentId}/g-vote",
            json={"value": 0}).status_code

    # ================================================================== #
    # Notifications
    # ================================================================== #

    def get_notifications(self, start: int = 0, size: int = 25) -> objects.NotificationList:
        "Community notifications. GoMino: ``GET /x{comId}/s/notification`` → ``{notificationList}``."
        response = self.session.get(
            f"/x{self.comId}/s/notification", params={"start": start, "size": size})
        return objects.NotificationList(response.json()["notificationList"]).NotificationList

    def check_notifications(self) -> int:
        "Mark all notifications read. GoMino: ``POST /x{comId}/s/notification/checked``."
        return self.session.post(f"/x{self.comId}/s/notification/checked").status_code

    def delete_notification(self, notificationId: str) -> int:
        "Delete one notification. GoMino: ``DELETE /x{comId}/s/notification/{id}``."
        return self.session.delete(
            f"/x{self.comId}/s/notification/{notificationId}").status_code

    def clear_notifications(self) -> int:
        "Delete all notifications. GoMino: ``DELETE /x{comId}/s/notification``."
        return self.session.delete(f"/x{self.comId}/s/notification").status_code

    # ================================================================== #
    # Moderation (curator+/leader+, or via approved bot aliases)
    # ================================================================== #

    def ban(self, userId: str, reason: str = None) -> dict:
        """
        Ban a member from the community.

        GoMino: ``POST /x{comId}/s/user-profile/{userId}/ban`` with
        ``{"note": {"content": reason}}``. Requires curator+/leader+.
        """
        data = {"note": {"content": reason or ""}}
        return self.session.post(
            f"/x{self.comId}/s/user-profile/{userId}/ban", json=data).json()

    def unban(self, userId: str, reason: str = None) -> dict:
        "Unban a member. GoMino: ``POST /x{comId}/s/user-profile/{userId}/unban``."
        data = {"note": {"content": reason or ""}}
        return self.session.post(
            f"/x{self.comId}/s/user-profile/{userId}/unban", json=data).json()

    def warn(self, userId: str, reason: str = None, enableReadMode: bool = False,
             readModeDurationMinutes: int = 0) -> dict:
        """
        Warn a member, optionally putting them into read-mode.

        GoMino: ``POST /x{comId}/s/user-profile/{userId}/warn`` with
        ``{reason, enableReadMode, readModeDurationMinutes}``.
        """
        data = {"reason": reason or ""}
        if enableReadMode:
            data["enableReadMode"] = True
            data["readModeDurationMinutes"] = readModeDurationMinutes
        return self.session.post(
            f"/x{self.comId}/s/user-profile/{userId}/warn", json=data).json()

    # Amino strike durations (index 1–5) → read-mode minutes.
    _STRIKE_MINUTES = {1: 60, 2: 180, 3: 360, 4: 720, 5: 1440}

    def strike(self, userId: str, time: int = 1, title: str = None,
               reason: str = None) -> dict:
        """
        Amino-compat: a strike = warn + timed read-mode. Maps Amino's
        ``time`` code (1→1h, 2→3h, 3→6h, 4→12h, 5→24h) onto
        :meth:`warn` with ``enableReadMode``. ``title`` is ignored.
        """
        minutes = self._STRIKE_MINUTES.get(time, 60)
        return self.warn(userId, reason=reason or title,
                         enableReadMode=True, readModeDurationMinutes=minutes)

    def feature(self, blogId: str, days: int = 1) -> int:
        """
        Feature a blog for ``days`` (1–4).

        GoMino: ``POST /x{comId}/s/blog/{blogId}/feature`` with ``{days}``.
        (Amino's user/chat/wiki featuring isn't exposed — blogs only.)
        """
        return self.session.post(
            f"/x{self.comId}/s/blog/{blogId}/feature", json={"days": days}).status_code

    def unfeature(self, blogId: str) -> int:
        "Unfeature a blog. GoMino: ``DELETE /x{comId}/s/blog/{blogId}/feature``."
        return self.session.delete(f"/x{self.comId}/s/blog/{blogId}/feature").status_code

    def hide(self, blogId: str = None, userId: str = None, chatId: str = None,
             wikiId: str = None, reason: str = None) -> int:
        """
        Hide an object (curator+). Pass exactly one of
        ``blogId``/``userId``/``chatId``/``wikiId``.

        GoMino: ``POST .../blog/{blogId}/hide`` · ``.../user-profile/{userId}/hide``
        · ``.../chat/thread/{chatId}/hide`` · ``.../item/{wikiId}/hide``.
        """
        data = {"reason": reason} if reason else {}
        if blogId:
            url = f"/x{self.comId}/s/blog/{blogId}/hide"
        elif userId:
            url = f"/x{self.comId}/s/user-profile/{userId}/hide"
        elif chatId:
            url = f"/x{self.comId}/s/chat/thread/{chatId}/hide"
        elif wikiId:
            url = f"/x{self.comId}/s/item/{wikiId}/hide"
        else:
            raise exceptions.SpecifyType
        return self.session.post(url, json=data).status_code

    def unhide(self, blogId: str = None, userId: str = None, chatId: str = None,
               wikiId: str = None, reason: str = None) -> int:
        "Unhide an object (mirror of :meth:`hide`)."
        data = {"reason": reason} if reason else {}
        if blogId:
            url = f"/x{self.comId}/s/blog/{blogId}/unhide"
        elif userId:
            url = f"/x{self.comId}/s/user-profile/{userId}/unhide"
        elif chatId:
            url = f"/x{self.comId}/s/chat/thread/{chatId}/unhide"
        elif wikiId:
            url = f"/x{self.comId}/s/item/{wikiId}/unhide"
        else:
            raise exceptions.SpecifyType
        return self.session.post(url, json=data).status_code

    def edit_titles(self, userId: str, titles: list) -> int:
        """
        Replace a member's custom titles (звания).

        ``titles`` is a list of ``{"title": str, "color": "#rrggbb"}`` dicts.

        GoMino: ``PUT /x{comId}/s/user-profile/{userId}/custom-title`` with
        ``{"titles": [...]}`` (replace-all).
        """
        return self.session.put(
            f"/x{self.comId}/s/user-profile/{userId}/custom-title",
            json={"titles": titles}).status_code

    def moderation_history(self, start: int = 0, size: int = 25) -> objects.AdminLogList:
        """
        Community moderation log.

        GoMino: ``GET /x{comId}/s/admin/operation`` → ``{"adminLogList"}``.
        """
        response = self.session.get(
            f"/x{self.comId}/s/admin/operation", params={"start": start, "size": size})
        return objects.AdminLogList(response.json()["adminLogList"]).AdminLogList

    # ================================================================== #
    # Chat bubbles & misc
    # ================================================================== #

    def apply_bubble(self, bubbleId: str, chatId: str, applyToAll: bool = False) -> int:
        """
        Apply a chat bubble to a thread (or all of the bot's chats).

        GoMino: ``POST /x{comId}/s/chat/thread/{chatId}/apply-bubble``.
        """
        data = {"bubbleId": bubbleId, "threadId": chatId, "applyToAll": int(applyToAll)}
        return self.session.post(
            f"/x{self.comId}/s/chat/thread/{chatId}/apply-bubble", json=data).status_code

    # ================================================================== #
    # Live rooms (voice / video / cinema) — needs the ``live.rooms`` alias
    # ================================================================== #

    def _live(self, chatId: str, roomId: str = None) -> str:
        base = f"/x{self.comId}/s/chat/thread/{chatId}/live-room"
        return f"{base}/{roomId}" if roomId else base

    def _track_live(self, chatId: str, joined: bool) -> None:
        # AminoLightBots compat: Bot.active_live_chats lists chats whose room
        # the bot is currently in.
        live = getattr(self.client, "active_live_chats", None)
        if isinstance(live, set) and chatId:
            if joined:
                live.add(chatId)
            else:
                live.discard(chatId)

    def _room_id(self, chatId: str, roomId: str = None) -> str:
        if roomId:
            return roomId
        room = self.get_live_room(chatId)
        if room is None:
            raise exceptions.UnknownError(f"no active live room in chat {chatId}")
        return room.roomId

    def get_live_room(self, chatId: str):
        """
        The chat's active live room, or ``None``.

        GoMino: ``GET /x{comId}/s/chat/thread/{chatId}/live-room`` →
        ``{"liveRoom": {...} | null, "url"}``.
        """
        data = self.session.get(self._live(chatId)).json()
        if not data.get("liveRoom"):
            return None
        return objects.LiveRoom(data["liveRoom"]).LiveRoom

    def start_live_room(self, chatId: str, type: int = VOICE, title: str = None) -> LiveJoin:
        """
        Start a live room in a chat the bot is a member of and enter it as the
        host. ``type``: 1 voice, 2 video, 3 cinema (see ``AstranetPy.live``).
        Everyone in the chat gets a system message and a push, which is why
        this is an opt-in alias.

        GoMino: ``POST /x{comId}/s/chat/thread/{chatId}/live-room`` with
        ``{type, title}`` → ``{"liveRoom", "token", "url"}``.
        """
        data = {"type": type}
        if title:
            data["title"] = title
        response = self.session.post(self._live(chatId), json=data)
        self._track_live(chatId, True)
        return LiveJoin(response.json(), self.comId, chatId)

    def join_live_room(self, chatId: str, roomId: str = None,
                       as_listener: bool = False) -> LiveJoin:
        """
        Enter the chat's live room (the active one when ``roomId`` is omitted).

        ``as_listener=True`` gets a subscribe-only token; otherwise the server
        decides by the room's join policy whether the bot may publish.

        GoMino: ``POST .../live-room/{roomId}/join[?as=listener]`` →
        ``{"liveRoom", "token", "url"}``.
        """
        roomId = self._room_id(chatId, roomId)
        params = {"as": "listener"} if as_listener else None
        response = self.session.post(f"{self._live(chatId, roomId)}/join",
                                     json={}, params=params)
        self._track_live(chatId, True)
        return LiveJoin(response.json(), self.comId, chatId)

    def leave_live_room(self, chatId: str, roomId: str = None) -> dict:
        """
        Leave the room (also ends it when the bot was the last one inside).
        Always call this after disconnecting from LiveKit — the server keeps
        the seat otherwise.

        GoMino: ``POST .../live-room/{roomId}/leave``.
        """
        roomId = self._room_id(chatId, roomId)
        response = self.session.post(f"{self._live(chatId, roomId)}/leave", json={})
        self._track_live(chatId, False)
        return response.json()

    def end_live_room(self, chatId: str, roomId: str = None) -> dict:
        "End the room for everyone (host / co-host). GoMino: ``POST .../end``."
        roomId = self._room_id(chatId, roomId)
        response = self.session.post(f"{self._live(chatId, roomId)}/end", json={})
        self._track_live(chatId, False)
        return response.json()

    def become_speaker(self, chatId: str, roomId: str = None):
        """
        Upgrade the bot from listener to speaker: always for host/co-host, for
        others only under the "open" join policy. The live LiveKit participant
        gets publish rights in place — keep using the same connection.

        GoMino: ``POST .../become-speaker`` → ``{"liveRoom"}``.
        """
        roomId = self._room_id(chatId, roomId)
        response = self.session.post(f"{self._live(chatId, roomId)}/become-speaker", json={})
        return objects.LiveRoom(response.json().get("liveRoom")).LiveRoom

    def request_speak(self, chatId: str, roomId: str = None) -> dict:
        "Ask the host for the floor (\"by request\" policy). GoMino: ``POST .../request-speak``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(f"{self._live(chatId, roomId)}/request-speak", json={}).json()

    def accept_speak_invite(self, chatId: str, roomId: str = None) -> dict:
        "Accept the host's invitation to speak. GoMino: ``POST .../accept-invite``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(f"{self._live(chatId, roomId)}/accept-invite", json={}).json()

    def decline_speak_invite(self, chatId: str, roomId: str = None) -> dict:
        "Decline the host's invitation to speak. GoMino: ``POST .../decline-invite``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(f"{self._live(chatId, roomId)}/decline-invite", json={}).json()

    # -- host / co-host controls ----------------------------------------- #

    def get_speak_requests(self, chatId: str, roomId: str = None) -> list:
        """Pending requests to speak. GoMino: ``GET .../speak-requests`` → ``{"speakRequests"}``."""
        roomId = self._room_id(chatId, roomId)
        response = self.session.get(f"{self._live(chatId, roomId)}/speak-requests")
        return response.json().get("speakRequests") or []

    def approve_speak(self, chatId: str, userId: str, roomId: str = None) -> dict:
        "GoMino: ``POST .../speak-requests/{userId}/approve``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/speak-requests/{userId}/approve", json={}).json()

    def deny_speak(self, chatId: str, userId: str, roomId: str = None) -> dict:
        "GoMino: ``POST .../speak-requests/{userId}/deny``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/speak-requests/{userId}/deny", json={}).json()

    def invite_to_speak(self, chatId: str, userId: str, roomId: str = None) -> dict:
        "GoMino: ``POST .../invite/{userId}``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(f"{self._live(chatId, roomId)}/invite/{userId}", json={}).json()

    def set_live_join_policy(self, chatId: str, policy: int, roomId: str = None) -> dict:
        "1 open, 2 by request, 3 invite only. GoMino: ``POST .../policy`` with ``{policy}``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/policy", json={"policy": policy}).json()

    def set_live_room_type(self, chatId: str, type: int, roomId: str = None) -> dict:
        "Switch voice / video / cinema. GoMino: ``POST .../mode`` with ``{type}``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/mode", json={"type": type}).json()

    def lock_live_room(self, chatId: str, lock: bool = True, roomId: str = None) -> dict:
        "Close / reopen the room for new people. GoMino: ``POST .../lock`` with ``{lock}``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/lock", json={"lock": lock}).json()

    def kick_from_live_room(self, chatId: str, userId: str, roomId: str = None) -> dict:
        "Remove a participant from the room (not from the chat). GoMino: ``POST .../member/{userId}/kick``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/member/{userId}/kick", json={}).json()

    def ban_from_live_room(self, chatId: str, userId: str, roomId: str = None) -> dict:
        "Keep a participant from speaking in this room. GoMino: ``POST .../member/{userId}/ban``."
        roomId = self._room_id(chatId, roomId)
        return self.session.post(
            f"{self._live(chatId, roomId)}/member/{userId}/ban", json={}).json()

