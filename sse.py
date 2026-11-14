"""
SSE transport for Astranet bots.

Replaces Amino's websocket layer (``amino_socket.py``). Bots cannot hold a
WebSocket on Astranet; instead they consume a Server-Sent Events stream at
``GET /g/s/bot/updates`` (authenticated with the same ``Authorization: Bot``
header as every other request).

Wire format (one event per blank-line-terminated block)::

    id: <queue row id>        # optional; server acks the row itself, we ignore
    event: <type>             # new_message | message_edited | callback_query
    data: <json payload>      # the event-specific payload (no extra envelope)

Comment lines (``: connected``, ``: ping`` heartbeats every 25s) are ignored.

Skipping the offline backlog: set ``client.drop_pending = True`` before the
stream starts (``Bot.polling(skip_pending=True)`` does this). The first
successful connect then sends ``?dropPending=1`` and the server discards
everything queued while the bot was offline. Reconnects never send it, so
nothing that arrives during a network gap is lost.

The payload for ``new_message`` / ``message_edited`` is the Amino-style
``{"t": ..., "o": {...}}`` frame; ``callback_query`` carries a flat dict. Both
are handed to :class:`Callbacks` for resolution.
"""

import threading
from json import loads, JSONDecodeError
from time import sleep

import requests

from .events import Callbacks

# Server sends a heartbeat every 25s; if nothing arrives within this window the
# connection is presumed dead and we reconnect.
READ_TIMEOUT = 60
CONNECT_TIMEOUT = 10


class SSEHandler(Callbacks):
    """
    Background SSE reader. Mixed into the client (which passes itself as
    ``client``), exactly as ``SocketHandler`` was in AminoLightPy. Reconnects
    with exponential backoff until :meth:`stop_sse` is called.
    """

    def __init__(self, client, debug: bool = False):
        super().__init__()
        self.client = client
        self.debug = debug

        self._thread = None
        self._response = None
        self._running = False

        self.reconnect_delay = 3
        self.max_reconnect_delay = 60

        # Discard the server-side backlog on the first successful connect.
        self.drop_pending = False

    def _log(self, msg):
        if self.debug:
            print(msg)

    @property
    def sse_url(self) -> str:
        return f"{self.client.session.base_url}/g/s/bot/updates"

    # -- lifecycle ---------------------------------------------------------

    def run_sse(self):
        """Start the reader thread (idempotent)."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._stream_loop, name="AstranetSSE", daemon=True
        )
        self._thread.start()

    def stop_sse(self):
        """Stop the reader and drop the current connection."""
        self._running = False
        if self._response is not None:
            try:
                self._response.close()
            except Exception:
                pass

    # -- internals ---------------------------------------------------------

    def _stream_loop(self):
        delay = self.reconnect_delay
        while self._running:
            try:
                self._connect_and_read()
                delay = self.reconnect_delay  # clean disconnect -> reset backoff
            except Exception as e:  # noqa: BLE001 — transport errors are expected
                self._log(f"[sse] connection error: {e}")
            if not self._running:
                break
            sleep(delay)
            delay = min(delay * 2, self.max_reconnect_delay)

    def _connect_and_read(self):
        headers = {
            "Authorization": f"Bot {self.client.token}",
            "Accept": "text/event-stream",
        }
        params = {"dropPending": "1"} if self.drop_pending else None
        with requests.get(
            self.sse_url,
            headers=headers,
            params=params,
            stream=True,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        ) as resp:
            self._response = resp
            resp.raise_for_status()
            # Only once per process: on a reconnect the backlog is what
            # arrived during the gap, and the bot must get it.
            self.drop_pending = False

            resp.encoding = "utf-8"
            self._log("[sse] connected")

            event_type = None
            data_lines = []
            for raw in resp.iter_lines(decode_unicode=True):
                if not self._running:
                    break
                if raw is None:
                    continue

                # Blank line terminates an event block.
                if raw == "":
                    if data_lines:
                        self._emit(event_type or "message", "\n".join(data_lines))
                    event_type = None
                    data_lines = []
                    continue

                # Comment / heartbeat (": connected", ": ping").
                if raw.startswith(":"):
                    continue

                field, _, value = raw.partition(":")
                value = value[1:] if value.startswith(" ") else value
                if field == "event":
                    event_type = value
                elif field == "data":
                    data_lines.append(value)
                # "id" and any other fields are ignored (server self-acks).

            self._response = None

    def _emit(self, event_type, data_str):
        try:
            payload = loads(data_str)
        except JSONDecodeError:
            self._log(f"[sse] dropping non-JSON data: {data_str!r}")
            return
        try:
            self.dispatch(event_type, payload)
        except Exception as e:  # noqa: BLE001 — a bad handler must not kill the stream
            self._log(f"[sse] handler error for {event_type}: {e}")
