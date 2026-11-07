"""
HTTP session for Astranet bots.

Replaces Amino's ``AminoSession`` (constants.py). The differences are the whole
point of the port:

  * Auth is a single bot token sent as ``Authorization: Bot <uid>:<secret>`` on
    every request. There is no SID/session and no per-request signing
    (no NDC-MSG-SIG / NDCDEVICEID / device id).
  * Relative URLs resolve against ``base_url`` (default: the production API).
  * Errors reuse Amino's envelope ``{"api:statuscode", "api:message"}``, so the
    existing ``CheckException`` machinery still applies — but only on non-2xx
    responses, because Astranet success bodies do not carry api:statuscode.
"""

from time import time
from hashlib import sha1
from typing import BinaryIO
from base64 import b64decode
from binascii import Error as BinasciiError
from collections import OrderedDict
from urllib.parse import quote, urlsplit
from mimetypes import guess_type

from requests import Session
from requests.adapters import HTTPAdapter

from .lib import CheckException

DEFAULT_BASE_URL = "https://api.astranetapp.com/api/v1"

_media_cache = OrderedDict()
_MEDIA_CACHE_LEN = 32


def seg(value) -> str:
    """
    One URL path segment, percent-encoded (``/``, ``?``, ``#``, ``%`` … included).

    Every id that goes into a request path passes through here, so a value that
    came from chat text (``!kick <id>``) cannot reroute the request:
    ``"x/../.."`` becomes ``x%2F..%2F..`` instead of climbing to the parent route.
    Empty, ``.`` and ``..`` are rejected outright — ``quote`` leaves dots alone
    and those would still be read as path navigation.
    """
    text = str(value)
    if text in ("", ".", ".."):
        raise ValueError(f"invalid id for a URL path segment: {value!r}")
    return quote(text, safe="")


def comid(value) -> int:
    "A community id as ``int`` (accepts ``5`` or ``\"5\"``); anything else is a ValueError."
    if isinstance(value, bool):
        raise ValueError(f"invalid comId: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    raise ValueError(f"invalid comId: {value!r}")


def _check_relative_path(url: str) -> None:
    """
    Last line of defence for relative URLs built by this SDK: query parameters
    go through ``params=`` and ids through :func:`seg`, so a raw ``?``/``#`` or
    a ``.``/``..`` segment here means an unescaped value slipped into the path.
    """
    if "?" in url or "#" in url:
        raise ValueError(f"unexpected '?' or '#' in request path: {url!r}")
    if any(part in (".", "..") for part in urlsplit(url).path.split("/")):
        raise ValueError(f"dot segment in request path: {url!r}")


class AstranetSession(Session):
    """``requests.Session`` preconfigured for a single Astranet bot identity."""

    def __init__(self, token: str, base_url: str = DEFAULT_BASE_URL) -> None:
        super().__init__()
        self.token = token
        self.base_url = base_url.rstrip("/")

        self.headers.update({
            "Authorization": f"Bot {token}",
            "Accept": "application/json",
            "User-Agent": "AstranetPy",
        })
        self.timeout = 10

        adapter = HTTPAdapter(max_retries=3)
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    def request(self, method, url, *args, **kwargs):
        if not url.startswith(("http://", "https://")):
            _check_relative_path(url)
            url = f"{self.base_url}{url}"

        # Legacy POST-field validation (middleware ValidatePostFields) rejects
        # any non-exempt POST whose JSON body lacks a `timestamp`. Inject it.
        if method.upper() == "POST":
            body = kwargs.get("json")
            if isinstance(body, dict) and "timestamp" not in body:
                kwargs["json"] = {**body, "timestamp": int(time() * 1000)}

        kwargs.setdefault("timeout", self.timeout)

        response = super().request(method, url, *args, **kwargs)

        # Only failures carry the api:statuscode envelope; CheckException maps
        # the code to a typed exception (and falls back to UnknownError for the
        # plain {"error": "..."} bodies some endpoints return).
        if not response.ok:
            CheckException(response.text)

        return response


def upload_media(session: "AstranetSession", file: BinaryIO) -> str:
    """
    Upload a file to Astranet and return its ``mediaValue`` (server URL).

    A ``str`` argument is either an already-uploaded mediaValue (URL — returned
    unchanged) or, for Amino-bot compatibility, base64-encoded file content
    (aminofix bots pass ``b64encode(data).decode()`` as ``file=``), which is
    decoded and uploaded. Raw ``bytes`` upload as-is. The server ignores the
    advertised Content-Type and sniffs the real one from magic bytes.
    Identical files are de-duplicated within the process via a small LRU keyed
    on the SHA-1 of the content.
    """
    if isinstance(file, str):
        if file.startswith(("http://", "https://", "/")):
            return file
        try:
            data = b64decode(file, validate=True)
        except (BinasciiError, ValueError):
            return file  # not base64 — assume an opaque mediaValue
    elif isinstance(file, (bytes, bytearray)):
        data = bytes(file)
    else:
        data = file.read()
    file_hash = sha1(data).hexdigest()
    if file_hash in _media_cache:
        return _media_cache[file_hash]

    name = getattr(file, "name", "") or ""
    content_type = guess_type(name)[0] or "application/octet-stream"

    response = session.post(
        url="/g/s/media/upload",
        data=data,
        headers={"Content-Type": content_type},
    )
    media_value = response.json()["mediaValue"]

    _media_cache[file_hash] = media_value
    if len(_media_cache) > _MEDIA_CACHE_LEN:
        _media_cache.popitem(last=False)

    return media_value
