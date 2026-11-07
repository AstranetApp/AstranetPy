"""
Bot capability aliases — a mirror of the GoMino catalog
(``internal/models/bot/alias.go``). Keep the two in sync by hand; the wire
truth is always the ``aliasCatalog`` returned by ``POST /g/s/auth/bot-login``
(exposed as ``Client.alias_catalog`` after ``get_me()``).

Three tiers:

  * **Basic** — granted automatically on bot creation (the reply essentials).
  * **Opt-in** — off by default; the developer enables them in BotFather.
    Active on request alone in any community the bot was invited to.
  * **Privileged** — admin-type powers; inert in a community until that
    community's admins explicitly approve them.

Effective permission in a community =
``requested(developer) − disabled(admin)``, and approval-gated aliases also
require ``approved(admin)``.

The *actual* per-community state is queryable: ``Client.get_aliases()`` is the
full map (every community + effective sets, one call), and
``SubClient.get_my_aliases()`` / ``SubClient.has_alias()`` answer for one
community. The ``aliases_changed`` / ``community_joined`` /
``community_removed`` SSE events keep those answers current at runtime.

The HOME community (Astranet Members, :data:`HOME_NDC_ID`) is special: every
bot is auto-joined there unvetted, so only the reply core
(:data:`HOME_CORE`) works without approval — everything else behaves like a
privileged alias there.
"""

# ── Basic (default-on) ──────────────────────────────────────────────────────
MESSAGES_SEND    = "messages.send"     # send messages in threads it belongs to
MESSAGES_RECEIVE = "messages.receive"  # receive chat updates over SSE
MESSAGES_REPLY   = "messages.reply"    # reply to a specific message
INLINE_KEYBOARDS = "inline.keyboards"  # attach interactive buttons
PROFILE_READ     = "profile.read"      # read public profiles / community info
MEDIA_SEND       = "media.send"        # send images / stickers / media

# ── Opt-in (developer enables in BotFather) ────────────────────────────────
USERS_DM       = "users.dm"       # open a DM with a user who hasn't messaged first
MESSAGES_BULK  = "messages.bulk"  # raised send limits / fan-out across threads
CHATS_CREATE   = "chats.create"   # create group / public chat threads
POSTS_CREATE   = "posts.create"   # publish blogs / polls / wiki entries
COMMENTS_WRITE = "comments.write" # comment on posts and wiki entries
LIVE_ROOMS     = "live.rooms"     # start/join voice & video rooms, get LiveKit tokens

# ── Privileged (community approval required) ───────────────────────────────
MODERATION_DELETE   = "moderation.delete"   # delete other members' messages
MODERATION_KICK     = "moderation.kick"     # kick / ban members
MODERATION_READONLY = "moderation.readonly" # put a member into read-mode

# Tier names as used in the wire catalog.
TIER_BASIC = "basic"
TIER_OPTIN = "optin"
TIER_PRIVILEGED = "privileged"

# The community every new bot is auto-joined to (Astranet Members).
HOME_NDC_ID = 4752731799

# Canonical catalog, in server display order (basic → opt-in → privileged).
# ``default`` mirrors "granted on creation"; ``privileged`` mirrors
# "needs community approval". Titles/descriptions are the English fallbacks
# the server ships; user-facing localization lives in the client apps.
CATALOG = [
    {"key": MESSAGES_SEND,    "tier": TIER_BASIC, "default": True,  "privileged": False,
     "title": "Send messages"},
    {"key": MESSAGES_RECEIVE, "tier": TIER_BASIC, "default": True,  "privileged": False,
     "title": "Receive messages"},
    {"key": MESSAGES_REPLY,   "tier": TIER_BASIC, "default": True,  "privileged": False,
     "title": "Reply to messages"},
    {"key": INLINE_KEYBOARDS, "tier": TIER_BASIC, "default": True,  "privileged": False,
     "title": "Interactive buttons"},
    {"key": PROFILE_READ,     "tier": TIER_BASIC, "default": True,  "privileged": False,
     "title": "Read profiles"},
    {"key": MEDIA_SEND,       "tier": TIER_BASIC, "default": True,  "privileged": False,
     "title": "Send media"},

    {"key": USERS_DM,       "tier": TIER_OPTIN, "default": False, "privileged": False,
     "title": "Direct messages"},
    {"key": MESSAGES_BULK,  "tier": TIER_OPTIN, "default": False, "privileged": False,
     "title": "Bulk sending"},
    {"key": CHATS_CREATE,   "tier": TIER_OPTIN, "default": False, "privileged": False,
     "title": "Create chats"},
    {"key": POSTS_CREATE,   "tier": TIER_OPTIN, "default": False, "privileged": False,
     "title": "Create posts"},
    {"key": COMMENTS_WRITE, "tier": TIER_OPTIN, "default": False, "privileged": False,
     "title": "Write comments"},
    {"key": LIVE_ROOMS,     "tier": TIER_OPTIN, "default": False, "privileged": False,
     "title": "Live rooms"},

    {"key": MODERATION_DELETE,   "tier": TIER_PRIVILEGED, "default": False, "privileged": True,
     "title": "Delete messages"},
    {"key": MODERATION_KICK,     "tier": TIER_PRIVILEGED, "default": False, "privileged": True,
     "title": "Kick and ban"},
    {"key": MODERATION_READONLY, "tier": TIER_PRIVILEGED, "default": False, "privileged": True,
     "title": "Read-only mode"},
]

ALL_ALIASES = tuple(d["key"] for d in CATALOG)
BASIC_ALIASES = tuple(d["key"] for d in CATALOG if d["tier"] == TIER_BASIC)
OPTIN_ALIASES = tuple(d["key"] for d in CATALOG if d["tier"] == TIER_OPTIN)
PRIVILEGED_ALIASES = tuple(d["key"] for d in CATALOG if d["tier"] == TIER_PRIVILEGED)

# The exact set active in the home community without admin approval — just
# enough to answer messages addressed to the bot. NOTE: deliberately narrower
# than the basic tier (no media.send).
HOME_CORE = frozenset({
    MESSAGES_SEND, MESSAGES_RECEIVE, MESSAGES_REPLY,
    INLINE_KEYBOARDS, PROFILE_READ,
})


def is_known(key: str) -> bool:
    "Whether ``key`` is a real catalog alias."
    return key in ALL_ALIASES


def is_privileged(key: str) -> bool:
    """
    Whether ``key`` needs community-admin approval everywhere. Unknown keys
    are treated as privileged (fail-closed), matching the server.
    """
    return key not in ALL_ALIASES or key in PRIVILEGED_ALIASES


def requires_approval(key: str, comId: int) -> bool:
    """
    Whether ``key`` needs an explicit admin grant to be active in ``comId``:
    privileged aliases everywhere; in the home community, anything outside
    the reply core.
    """
    if is_privileged(key):
        return True
    return comId == HOME_NDC_ID and key not in HOME_CORE
