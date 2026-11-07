__title__ = 'AstranetPy'
__author__ = 'AugustLight'
__license__ = 'MIT'
__version__ = '0.2.0'

# Bot SDK for Astranet (GoMino backend), structured after AminoLightPy so that
# bots written for it (Client / SubClient + objects.*) port with minimal changes.
from . import aliases
from . import live
from .client import Client
from .sub_client import SubClient
from .abstract_client import AbstractClient
from .session import AstranetSession, upload_media, DEFAULT_BASE_URL
from .managers import Typing, Recording
from .events import Callbacks
from .sse import SSEHandler
from .lib.util import objects
from .lib.util.objects import ChatEvent, Event, Message, LiveRoom
from .live import LiveJoin
from .lib import *
