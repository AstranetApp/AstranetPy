# pylint: disable=invalid-name
"""
Global Astranet bot client.

Architecturally a drop-in for AminoLightPy's ``Client``: it mixes the realtime
event layer (``SSEHandler`` — the SSE replacement for Amino's websocket
``SocketHandler``) with :class:`AbstractClient` scoped to the global namespace
(``path="/g"``). Bots authenticate with a single token instead of email/password;
``get_me()`` (aliased ``login``) is the token-introspection equivalent of Amino's
``login``.

The familiar two-tier shape is preserved::

    from AstranetPy import Client, SubClient

    client = Client(token)
    client.get_me()                       # validate token + start SSE

    client.send_message(dmChatId, "hi")   # global / DM scope  (/g/s)

    sub = SubClient(comId, profile=client.profile)
    sub.send_message(chatId, "hi")        # community scope     (/x{comId}/s)

Event handlers register exactly as before::

    @client.event("on_text_message")
    def _(event):
        client.send_message(event.message.chatId, "pong")
"""

from .session import AstranetSession, DEFAULT_BASE_URL
from .sse import SSEHandler
from .abstract_client import AbstractClient
from .managers import Typing, Recording
from .lib.util import objects


class Client(SSEHandler, AbstractClient):
    "Global bot client. Community work goes through :class:`SubClient`."

    # The global/DM scope is community 0. get_account(0) returns the client
    # itself, so ported code that reads `sub_client.comId` (e.g. for logging)
    # must find it here too, not only on SubClient.
    comId = 0

    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL,
                 sse_enabled: bool = True, debug: bool = False):
        self.token = token
        self.session = AstranetSession(token, base_url)
        self.sse_enabled = sse_enabled

        AbstractClient.__init__(self, self.session, path="/g")
        SSEHandler.__init__(self, self, debug)

        # Identity, filled in by get_me().
        self.uid = None
        self.nickname = None
        self.icon = None
        self.aliases = []            # globally effective (ndc 0)
        self.requested_aliases = []  # what the developer enabled in BotFather
        self.aliases_changed_at = None
        self.alias_catalog = []      # server's full catalog (wire truth)
        self.authenticated = False

        # Per-community alias views, keyed by comId — filled by get_aliases()
        # and kept current by the aliases_changed / community_joined /
        # community_removed SSE events (see _apply_alias_event).
        self._community_aliases = {}

        # Amino parity: a `profile` whose `.client` back-reference lets
        # `SubClient(comId, profile=client.profile)` reach the session.
        self.profile = objects.UserProfile(None).UserProfile
        self.profile.client = self

        # Lazy per-community SubClient cache (see get_account / get_community).
        self._sub_clients = {}

    # ------------------------------------------------------------------ #
    # Auth / lifecycle
    # ------------------------------------------------------------------ #

    def get_me(self) -> dict:
        """
        Validate the bot token and load identity + effective aliases.

        GoMino: ``POST /g/s/auth/bot-login`` — introspection only, mints no
        session (the token stays the credential). Starts the SSE stream on first
        success when ``sse_enabled``.

        **Returns** the raw ``{"bot": {...}, "aliasCatalog": [...]}`` payload.
        """
        data = self.session.post("/g/s/auth/bot-login").json()
        bot = data.get("bot") or {}
        self.uid = bot.get("uid")
        self.nickname = bot.get("nickname")
        self.icon = bot.get("icon")
        self.aliases = bot.get("aliases") or []
        self.requested_aliases = bot.get("requestedAliases") or []
        self.aliases_changed_at = bot.get("aliasesChangedAt")
        self.alias_catalog = data.get("aliasCatalog") or []

        # Mirror identity onto the profile so SubClient sees a real userId.
        self.profile = objects.UserProfile(bot).UserProfile
        self.profile.userId = self.uid
        self.profile.nickname = self.nickname
        self.profile.icon = self.icon
        self.profile.client = self

        self.authenticated = True

        if self.sse_enabled and not self._running:
            self.run_sse()
        return data

    # Convenience alias mirroring AminoLightPy's `login`.
    login = get_me

    def has_alias(self, alias: str, comId: int = 0) -> bool:
        """
        Whether the bot actually holds a capability alias — in the community
        ``comId``, or (default) in the global / DM namespace.

        Per-community answers come from the cache maintained by
        :meth:`get_aliases` and the ``aliases_changed`` SSE event, so after the
        first fetch this is free and stays correct when a community admin
        flips the bot's permissions. The full key catalog lives in
        :mod:`AstranetPy.aliases`; ``requested_aliases`` is what the developer
        enabled overall.
        """
        if not comId:
            return alias in self.aliases
        entry = self._community_aliases.get(comId)
        if entry is None:
            entry = self.get_aliases(comId)
        return alias in (entry.get("aliases") or [])

    def get_aliases(self, comId: int = None, refresh: bool = False) -> dict:
        """
        The bot's real permission map.

        Without ``comId`` — the full overview in one call: the global
        effective set plus every community the bot is a member of, each with
        its effective ``aliases``, admin ``disabled``/``approved`` overrides
        and ``pendingApproval`` (requested powers that only need an admin's
        grant). Also refreshes ``self.aliases`` / ``self.requested_aliases``
        and primes the per-community cache. Call it once at startup —
        ``get_me()`` deliberately carries no per-community state.

        With ``comId`` — that community's view only (served from cache unless
        ``refresh=True``), including a ``member`` flag.

        GoMino: ``GET /g/s/bot/me/aliases`` and
        ``GET /x{comId}/s/bot/me/aliases``.
        """
        if comId:
            if not refresh:
                cached = self._community_aliases.get(comId)
                if cached is not None:
                    return cached
            data = self.session.get(f"/x{comId}/s/bot/me/aliases").json()
            self._community_aliases[comId] = data
            return data

        data = self.session.get("/g/s/bot/me/aliases").json()
        self.requested_aliases = data.get("requestedAliases") or []
        self.aliases = (data.get("global") or {}).get("aliases") or []
        for entry in data.get("communities") or []:
            ndc = entry.get("ndcId")
            if ndc:
                self._community_aliases[ndc] = entry
        return data

    def _apply_alias_event(self, event_type: str, payload: dict):
        """
        Fold an alias/membership SSE event into the local caches (called by
        :class:`Callbacks` before user handlers run, so a handler that asks
        ``has_alias(...)`` already sees the new state).
        """
        ndc = payload.get("ndcId") or 0
        if event_type == "aliases_changed":
            if ndc:
                # A community admin changed this community's overrides — the
                # payload is the fresh per-community view.
                self._community_aliases[ndc] = payload
            else:
                # The developer changed the requested set in BotFather: every
                # community's effective set may have shifted. Drop the cache
                # wholesale; entries refill lazily on the next has_alias().
                self.requested_aliases = payload.get("requestedAliases") or self.requested_aliases
                self.aliases = payload.get("aliases") or []
                self._community_aliases.clear()
        elif event_type == "community_joined" and ndc:
            self._community_aliases[ndc] = payload
        elif event_type == "community_removed" and ndc:
            self._community_aliases.pop(ndc, None)

    # ------------------------------------------------------------------ #
    # Communities (global scope)
    # ------------------------------------------------------------------ #

    # NOTE: Amino's `sub_clients()` (list of joined communities) is deliberately
    # absent: bots don't join communities themselves — admins add them — and
    # /g/s/community/joined is RequireNotBot. The bot's own community list
    # (with its per-community permissions) is get_aliases(); reactively, the
    # `comId` carried by every event still works (see get_account).

    def get_community_info(self, comId: int) -> objects.Community:
        """
        Information about a community.

        **Returns** :class:`Community`.

        GoMino: ``GET /g/s-x{comId}/community`` → ``{"community": {...}}``.
        """
        response = self.session.get(f"/g/s-x{comId}/community")
        return objects.Community(response.json()["community"]).Community

    def get_public_communities(self, start: int = 0, size: int = 25) -> objects.CommunityList:
        """
        Featured / public communities.

        **Returns** :class:`CommunityList`.

        GoMino: ``GET /g/s/community/featured`` → ``{"communityList": [...]}``.
        (Replaces Amino's topic-feed discovery, which has no Astranet equivalent.)
        """
        response = self.session.get(
            "/g/s/community/featured", params={"start": start, "size": size})
        return objects.CommunityList(response.json().get("communityList") or []).CommunityList

    def search(self, query: str) -> dict:
        """
        Global search (users / communities / chats).

        Returns the raw result payload — its shape mirrors the web client.

        GoMino: ``GET /g/s/search?q=...``.
        """
        return self.session.get("/g/s/search", params={"q": query}).json()

    def get_supported_languages(self):
        "Tuple of languages Astranet content can be tagged with."
        return ("en", "es", "pt", "ar", "ru", "fr", "de")

    def get_from_code(self, code: str) -> objects.FromCode:
        """
        Amino-compat: resolve a share link to its object.

        GoMino has no link-resolution endpoint, so Astranet share URLs are
        parsed **client-side** (no request). Recognized shapes (see
        internal/api/opengraph):

        - ``…/c/{comId}``                → community  (objectType 16)
        - ``…/c/{comId}/t/{threadId}``   → chat       (objectType 12)
        - ``…/t/{threadId}``             → global chat
        - ``…/c/{comId}/p/{postId}``     → post/blog  (objectType 1)
        - ``…/u/{userId}`` / ``…/c/{comId}/u/{userId}`` → user (objectType 0)

        **Returns** :class:`FromCode` with ``comId`` / ``objectId`` /
        ``objectType`` filled in; raises ``ValueError`` for URLs it cannot
        parse (including aminoapps.com links).
        """
        from urllib.parse import urlparse
        path = urlparse(code).path if "://" in code else code
        parts = [p for p in path.split("/") if p]

        comId, objectId, objectType = None, None, None
        i = 0
        while i < len(parts):
            seg = parts[i]
            nxt = parts[i + 1] if i + 1 < len(parts) else None
            if seg == "c" and nxt and nxt.isdigit():
                comId = int(nxt)
                objectId, objectType = None, 16
                i += 2
                continue
            if seg == "t" and nxt:
                objectId, objectType = nxt, 12
                i += 2
                continue
            if seg == "p" and nxt:
                objectId, objectType = nxt, 1
                i += 2
                continue
            if seg == "u" and nxt:
                objectId, objectType = nxt, 0
                i += 2
                continue
            i += 1

        if comId is None and objectId is None:
            raise ValueError(f"not an Astranet share link: {code!r}")

        link_info = {
            "objectId": objectId if objectId is not None else str(comId),
            "objectType": objectType,
            "ndcId": comId,
            "fullPath": path,
        }
        return objects.FromCode(
            {"path": path, "extensions": {"linkInfo": link_info}}).FromCode

    # ------------------------------------------------------------------ #
    # Community helpers
    # ------------------------------------------------------------------ #

    def get_account(self, comId: int = 0):
        """
        The scope object for ``comId``: the client itself for the global / DM
        scope (``comId`` 0 or ``None``, prefix ``/g``) or a cached
        :class:`SubClient` for a community (prefix ``/x{comId}``).

        This is the bridge between Astranet's single-token model and the
        per-event ``comId`` carried by chat events::

            client.get_account(event.comId).send_message(chatId, "hi")
        """
        if not comId:
            return self
        sub = self._sub_clients.get(comId)
        if sub is None:
            from .sub_client import SubClient
            sub = SubClient(comId, profile=self.profile)
            self._sub_clients[comId] = sub
        return sub

    # Amino-friendly alias; always returns a SubClient (even for comId 0).
    def get_community(self, comId: int):
        "Build/return a :class:`SubClient` bound to ``comId`` (see :meth:`get_account`)."
        from .sub_client import SubClient
        if not comId:
            return SubClient(comId, profile=self.profile)
        return self.get_account(comId)

    # ------------------------------------------------------------------ #
    # Presence (no-op on GoMino — kept for source compatibility)
    # ------------------------------------------------------------------ #

    def typing(self, chatId: str, comId: int = None) -> Typing:
        """
        Context manager mirroring Amino's typing indicator. GoMino exposes no
        bot presence endpoint, so this is a no-op kept so ``with client.typing():``
        blocks don't break ported code.
        """
        return Typing(self, chatId=chatId, comId=comId)

    def recording(self, chatId: str, comId: int = None) -> Recording:
        "No-op recording indicator (see :meth:`typing`)."
        return Recording(self, chatId=chatId, comId=comId)
