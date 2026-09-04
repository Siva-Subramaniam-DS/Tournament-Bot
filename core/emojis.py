import discord
from typing import Optional

# ===========================================================================================
# CUSTOM DISCORD EMOJIS REGISTRY (APPLICATION EMOJIS & SERVER EMOJIS)
# ===========================================================================================

EMOJI_IDS = {
    "vs": 1545045392515797042,
    "verified": 1545045390452334602,
    "trophy": 1545045388145205298,
    "recorder": 1545045386199044106,
    "not_verified": 1545045384274116669,
    "not_in_server": 1545045381329457202,
    "attendance_done": 1545045378657951744,
    "match_done": 1545045378657951744,
    "skull": 1545045375205773402,
    "loser": 1545045375205773402,
    "judge": 1545045372953559110,
    "details": 1545045370961133668,
    "player": 1545045370961133668,
    "player_details": 1545045370961133668,
    "captain": 1545045368218329208,
    "captain_details": 1545045368218329208,

    # Newly added emojis
    "winner": 1545271946223292426,
    "helpers": 1545271188593320006,

    # Staff replacement action fallbacks
    "cameraman_in": 1545045386199044106,
    "cameraman_out": 1545045386199044106,
}

# Direct Discord emoji format strings (Application Emojis uploaded in Discord Dev Portal)
EMOJIS = {
    "vs": "<:Vs:1545045392515797042>",
    "verified": "<:Verified:1545045390452334602>",
    "trophy": "<:trophy:1545045388145205298>",
    "recorder": "<:Recorder:1545045386199044106>",
    "not_verified": "<:NotVerifed:1545045384274116669>",
    "not_in_server": "<:NotInServer:1545045381329457202>",
    "attendance_done": "<:MatchDone:1545045378657951744>",
    "match_done": "<:MatchDone:1545045378657951744>",
    "skull": "<:Loser:1545045375205773402>",
    "loser": "<:Loser:1545045375205773402>",
    "judge": "<:Judge:1545045372953559110>",
    "details": "<:Details:1545045370961133668>",
    "player": "<:Details:1545045370961133668>",
    "player_details": "<:Details:1545045370961133668>",
    "captain": "<:CaptainDetails:1545045368218329208>",
    "captain_details": "<:CaptainDetails:1545045368218329208>",

    # Newly added emojis
    "winner": "<:winner:1545271946223292426>",
    "helpers": "<:Helpers:1545271188593320006>",

    # Fallbacks for cameraman replacement
    "cameraman_in": "<:Recorder:1545045386199044106>",
    "cameraman_out": "<:Recorder:1545045386199044106>",
}

# Dynamic cache for real resolved Discord emoji strings
EMOJI_CACHE = {}

import re

def _norm_name(n: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', str(n)).lower()

NAME_TO_KEY = {
    "vs": "vs",
    "verified": "verified",
    "trophy": "trophy",
    "recorder": "recorder",
    "notverifed": "not_verified",
    "notverified": "not_verified",
    "notinserver": "not_in_server",
    "matchdone": "attendance_done",
    "attendancedone": "attendance_done",
    "loser": "loser",
    "skull": "skull",
    "judge": "judge",
    "details": "details",
    "player": "player",
    "playerdetails": "player_details",
    "captain": "captain",
    "captaindetails": "captain_details",
    "winner": "winner",
    "helpers": "helpers",
    "helper": "helpers",
}

async def init_emojis_from_bot(bot):
    """
    Scan application emojis (uploaded to Discord Developer Portal)
    and any server emojis accessible to the bot, caching their exact Discord string by ID and name.
    """
    global EMOJI_CACHE
    found_count = 0

    all_emojis = []

    # 1. Fetch Application Emojis from Discord Developer Portal
    try:
        if hasattr(bot, 'fetch_application_emojis'):
            app_emojis = await bot.fetch_application_emojis()
            all_emojis.extend(app_emojis)
    except Exception as e:
        print(f"  [App Emojis Info] Could not fetch application emojis: {e}")

    # 2. Add guild emojis accessible to the bot
    if hasattr(bot, 'emojis'):
        all_emojis.extend(bot.emojis)

    for emoji in all_emojis:
        prefix = "a" if getattr(emoji, 'animated', False) else ""
        formatted = f"<{prefix}:{emoji.name}:{emoji.id}>"
        
        # Match by ID
        for k, v in EMOJI_IDS.items():
            if v == emoji.id:
                EMOJI_CACHE[k] = formatted
                EMOJIS[k] = formatted
                found_count += 1
                
        # Match by normalized name
        norm = _norm_name(emoji.name)
        if norm in NAME_TO_KEY:
            target_k = NAME_TO_KEY[norm]
            EMOJI_CACHE[target_k] = formatted
            EMOJIS[target_k] = formatted
            if target_k == "attendance_done":
                EMOJI_CACHE["match_done"] = formatted
                EMOJIS["match_done"] = formatted
            found_count += 1

    print(f"✅ Loaded {len(EMOJI_CACHE) or len(EMOJIS)} custom emojis for bot.")

def get_emoji(name: str, guild: Optional[discord.Guild] = None, default: str = "") -> str:
    """
    Retrieve the custom emoji.
    Prefers the cached resolved emoji, or searches the guild directly by ID or name so the exact
    name and animated (<a:) status is always 100% accurate, falling back to preconfigured strings.
    """
    if name in EMOJI_CACHE:
        return EMOJI_CACHE[name]

    target_id = EMOJI_IDS.get(name)
    norm_target = _norm_name(name)

    if guild:
        for em in guild.emojis:
            if target_id and em.id == target_id:
                prefix = "a" if getattr(em, 'animated', False) else ""
                formatted = f"<{prefix}:{em.name}:{em.id}>"
                EMOJI_CACHE[name] = formatted
                EMOJIS[name] = formatted
                return formatted
            if _norm_name(em.name) == norm_target:
                prefix = "a" if getattr(em, 'animated', False) else ""
                formatted = f"<{prefix}:{em.name}:{em.id}>"
                EMOJI_CACHE[name] = formatted
                EMOJIS[name] = formatted
                return formatted

    return EMOJIS.get(name, default)

def get_staff_emoji(guild: Optional[discord.Guild], role: str) -> str:
    """Get custom emoji for staff roles (judge / recorder)."""
    key = "judge" if role.lower() == "judge" else "recorder"
    return get_emoji(key, guild=guild, default=EMOJIS.get(key, ""))

