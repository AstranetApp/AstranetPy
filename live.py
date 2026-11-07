"""
Live rooms (voice / video / cinema) for Astranet bots.

Requires the ``live.rooms`` alias (opt-in, enabled in BotFather). The REST side
lives on :class:`~AstranetPy.sub_client.SubClient` (``start_live_room``,
``join_live_room``, …); those calls return a :class:`LiveJoin` — the room plus
a LiveKit access token and server URL. The media side is plain LiveKit: hand
the token to any LiveKit SDK, or call :meth:`LiveJoin.connect` to get a
connected ``livekit.rtc.Room`` (``pip install livekit``).

    sub = SubClient(comId, profile=client.profile)
    join = sub.join_live_room(chatId)          # or start_live_room(chatId)
    room = await join.connect()                # livekit.rtc.Room
    ...
    await room.disconnect()
    sub.leave_live_room(chatId, join.roomId)   # free the seat server-side

The token's identity is the bot's uid. It is valid for 24 hours and carries
publish rights only when the bot entered as a speaker (``join_live_room(...,
as_listener=False)``, the host, or after ``become_speaker`` — the server then
upgrades the live participant, no new token needed). Data packets are always
allowed.

LiveKit Agents (``livekit-agents``) work in *standalone* mode: connect the room
yourself with :meth:`LiveJoin.connect` and pass it to
``AgentSession.start(room=...)``. The worker/dispatch mode (``cli.run_app``)
needs the LiveKit server's API key and secret, which bots never get.
See ``examples/live_agent.py`` in the AstranetBots repository.
"""

from .lib.util import objects

# LiveRoom.type
VOICE = 1
VIDEO = 2
CINEMA = 3

# LiveRoom.joinPolicy (who may become a speaker)
POLICY_OPEN = 1
POLICY_BY_REQUEST = 2
POLICY_INVITE_ONLY = 3


def normalize_url(url: str) -> str:
    """
    LiveKit signalling URL as ``wss://host``. The API returns whatever the
    server was configured with — on production a bare host without a scheme.
    """
    url = (url or "").strip().rstrip("/")
    if "://" in url:
        scheme, rest = url.split("://", 1)
        if scheme in ("ws", "wss"):
            return url
        url = rest
    return f"wss://{url}"


class LiveJoin:
    "Result of starting or joining a live room: the room + LiveKit credentials."

    __slots__ = ("json", "room", "token", "url", "comId", "chatId", "roomId")

    def __init__(self, data: dict, comId: int = None, chatId: str = None):
        data = data or {}
        self.json = data
        self.room = objects.LiveRoom(data.get("liveRoom")).LiveRoom
        self.token = data.get("token")
        self.url = normalize_url(data.get("url"))
        self.comId = comId
        self.chatId = self.room.chatId or chatId
        self.roomId = self.room.roomId

    async def connect(self, room=None, options=None):
        """
        Connect to the LiveKit room and return the ``livekit.rtc.Room``.

        Pass your own ``room`` (to register event handlers before connecting)
        and/or ``options`` (``rtc.RoomOptions``). Needs ``pip install livekit``.
        """
        try:
            from livekit import rtc
        except ImportError as e:
            raise ImportError(
                "LiveJoin.connect() needs the LiveKit SDK: pip install livekit") from e
        if not self.token:
            raise ValueError("no LiveKit token in this response")
        if room is None:
            room = rtc.Room()
        if options is None:
            await room.connect(self.url, self.token)
        else:
            await room.connect(self.url, self.token, options)
        return room

    def __repr__(self):
        return f"<LiveJoin roomId={self.roomId!r} chatId={self.chatId!r} url={self.url!r}>"
