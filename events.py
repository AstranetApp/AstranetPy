"""
Event dispatch for Astranet bots.

Astranet delivers events over SSE (see ``sse.py``). Each SSE frame carries an
event *type* (the ``event:`` line) and a JSON *payload* (the ``data:`` line).

The payload of ``new_message`` / ``message_edited`` mirrors the legacy Amino
websocket frame — ``{"t": 1000, "o": {"chatMessage": {...}, "ndcId": ...}}`` —
so the resolution logic below stays close to the original AminoLightPy code.
``callback_query`` is Astranet-specific (inline-keyboard taps) and has a flat
payload ``{"threadId", "messageId", "ndcId", "fromUid", "callbackData"}``.
"""

from .lib import Event
from .lib.util.objects import ChatEvent

# Astranet chat-message ``type`` -> handler event name.
#
# Astranet encodes the message kind in ``type`` directly (unlike Amino, which
# overloaded type 0 with mediaType), so we key on ``type`` alone and ignore
# ``mediaType``. Codes come from internal/models/chat/message.go:
#   0 text · 2 voice · 3 image · 4 video · 100 sticker
#   101 joined · 102 left · 103 deleted · 104 pinned · 105 unpinned
#   106 view-only on · 107 view-only off
CHAT_EVENT_MAP = {
    0:   ChatEvent.TEXT_MESSAGE,
    2:   ChatEvent.VOICE_MESSAGE,
    3:   ChatEvent.IMAGE_MESSAGE,
    4:   "on_video_message",
    100: ChatEvent.STICKER_MESSAGE,
    101: ChatEvent.USER_JOINED,
    102: ChatEvent.USER_LEFT,
    103: ChatEvent.MESSAGE_DELETED,
    104: "on_message_pinned",
    105: "on_message_unpinned",
    106: ChatEvent.CHAT_VIEW_ONLY_ENABLED,
    107: ChatEvent.CHAT_VIEW_ONLY_DISABLED,
}


class Callbacks:
    """
    Registry of user handlers plus the resolver that turns an incoming SSE
    event into one or more handler calls.

    A client (or bot) mixes this in and registers handlers with ``event``::

        @client.event("on_text_message")
        def _(event):
            ...

    Every resolved event also fires the ``"all"`` handler bucket; unknown event
    types fire ``"default"``.
    """

    def __init__(self):
        self.handlers = {}
        # SSE event type -> resolver method.
        self.event_resolvers = {
            "new_message":       self._resolve_chat_message,
            "message_edited":    self._resolve_message_edited,
            "callback_query":    self._resolve_callback_query,
            "aliases_changed":   self._resolve_aliases_changed,
            "community_joined":  self._resolve_community_joined,
            "community_removed": self._resolve_community_removed,
        }

    # -- registration ------------------------------------------------------

    def event(self, type):
        """Decorator registering ``handler`` under the event name ``type``."""
        def register(handler):
            self.handlers.setdefault(type, []).append(handler)
            return handler
        return register

    def call(self, type, data):
        for handler in self.handlers.get(type, []):
            handler(data)

    # -- dispatch ----------------------------------------------------------

    def dispatch(self, event_type, payload):
        """
        Entry point from the SSE transport. ``payload`` is the already-parsed
        JSON body of the ``data:`` line (the event-specific payload, not the
        delivery envelope — the transport strips queueId/type for us).
        """
        resolver = self.event_resolvers.get(event_type)
        if resolver is not None:
            resolver(payload)
        else:
            self.call("default", payload)

    def _resolve_chat_message(self, payload):
        # payload == {"t": 1000, "o": {"chatMessage": {...}, "ndcId": ...}}
        o = payload.get("o") or {}
        chat_message = o.get("chatMessage") or {}
        event_name = CHAT_EVENT_MAP.get(chat_message.get("type", 0), "default")
        self._trigger_event(event_name, o)

    def _resolve_message_edited(self, payload):
        o = payload.get("o") or {}
        self._trigger_event("on_message_edited", o)

    def _resolve_callback_query(self, payload):
        # Flat payload — no Amino t/o envelope, so deliver the dict as-is.
        self.call("on_callback_query", payload)
        self.call("all", payload)

    # -- bot state (aliases / membership) ----------------------------------
    #
    # Flat payloads describing the bot itself: a community admin changed its
    # permissions (``aliases_changed`` with the community's ndcId; ndcId 0
    # means the developer edited the requested set in BotFather), the bot was
    # invited to a community, or removed from one. The client folds each event
    # into its alias cache BEFORE user handlers run, so ``has_alias`` inside a
    # handler already reflects the change.

    def _resolve_aliases_changed(self, payload):
        self._sync_alias_state("aliases_changed", payload)
        self.call("on_aliases_changed", payload)
        self.call("all", payload)

    def _resolve_community_joined(self, payload):
        self._sync_alias_state("community_joined", payload)
        self.call("on_community_joined", payload)
        self.call("all", payload)

    def _resolve_community_removed(self, payload):
        self._sync_alias_state("community_removed", payload)
        self.call("on_community_removed", payload)
        self.call("all", payload)

    def _sync_alias_state(self, event_type, payload):
        # Callbacks is a mixin: when mixed into Client, _apply_alias_event
        # exists and maintains the per-community alias cache. Stand-alone use
        # (tests, custom hosts) simply has no cache to update.
        apply = getattr(self, "_apply_alias_event", None)
        if apply is not None:
            apply(event_type, payload)

    def _trigger_event(self, event_name, o):
        event = Event(o).Event
        self.call(event_name, event)
        self.call("all", event)

    def default(self, payload):
        self.call("default", payload)
