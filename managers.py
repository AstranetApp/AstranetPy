# pylint: disable=invalid-name
"""
Typing / Recording context managers.

In AminoLightPy these sent websocket presence actions (``t=304``/``306``) while
the ``with`` block was open. GoMino has no bot presence endpoint — bots only
*receive* over SSE — so these are kept as no-ops purely so that code ported from
AminoLightPy (``with sub.typing(chatId): ...``) keeps running unchanged.
"""


class Typing:
    "No-op typing indicator (Amino parity)."

    def __init__(self, context, chatId: str, comId: int = None) -> None:
        self.chatId = chatId
        self.context = context
        self.comId = 0 if not comId else comId

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class Recording:
    "No-op recording indicator (Amino parity)."

    def __init__(self, context, chatId: str, comId: int = None) -> None:
        self.chatId = chatId
        self.context = context
        self.comId = 0 if not comId else comId

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
