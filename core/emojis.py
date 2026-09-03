import discord
from typing import Optional

# ===========================================================================================
# CUSTOM DISCORD EMOJIS REGISTRY
# ===========================================================================================

EMOJI_IDS = {
    "cameraman_in": 1544981358450053252,
    "cameraman_out": 1544981504680140890,
    "recorder": 1544981791566331924,
    "judge": 1544980903871127645,
    "not_verified": 1544978198104899616,
    "verified": 1544978254669021216,
    "skull": 1544982280425185302,
    "not_in_server": 1544976783991119872,
    "attendance_done": 1544979996395970560,
    "captain": 1544978620458475532,
    "trophy": 1544979065042378772,
}

# Fallback string mappings (in case guild cache is not ready yet)
EMOJIS = {
    "cameraman_in": "<:CameramanAdd:1544981358450053252>",
    "cameraman_out": "<:CameramanRemove:1544981504680140890>",
    "recorder": "<:camera:1544981791566331924>",
    "judge": "<:judge:1544980903871127645>",
    "not_verified": "<:nonverified_IDS:1544978198104899616>",
    "verified": "<:verified_IDS:1544978254669021216>",
    "skull": "<:skull:1544982280425185302>",
    "not_in_server": "<:not_in_server:1544976783991119872>",
    "attendance_done": "<a:White_Verification:1544979996395970560>",
    "captain": "<:captain:1544978620458475532>",
    "trophy": "<a:trophy:1544979065042378772>",
}

# Dynamic cache for real resolved Discord emoji strings
EMOJI_CACHE = {}

def init_emojis_from_bot(bot):
    """Scan all server emojis accessible to the bot and cache their exact Discord string by ID."""
    global EMOJI_CACHE
    id_to_key = {v: k for k, v in EMOJI_IDS.items()}
    found_count = 0
    for emoji in bot.emojis:
        if emoji.id in id_to_key:
            key = id_to_key[emoji.id]
            formatted = str(emoji)
            EMOJI_CACHE[key] = formatted
            EMOJIS[key] = formatted
            found_count += 1
            print(f"  [Emoji Found] '{key}' -> name='{emoji.name}', id={emoji.id}, animated={emoji.animated} -> {formatted}")
    print(f"✅ Resolved {found_count}/{len(EMOJI_IDS)} custom emojis directly from Discord servers.")

def get_emoji(name: str, guild: Optional[discord.Guild] = None, default: str = "") -> str:
    """
    Retrieve the custom emoji.
    Prefers the cached resolved emoji, or searches the guild directly by ID so the exact
    name and animated (<a:) status is always 100% accurate.
    """
    if name in EMOJI_CACHE:
        return EMOJI_CACHE[name]

    target_id = EMOJI_IDS.get(name)
    if guild and target_id:
        for em in guild.emojis:
            if em.id == target_id:
                formatted = str(em)
                EMOJI_CACHE[name] = formatted
                EMOJIS[name] = formatted
                return formatted

    return EMOJIS.get(name, default)

def get_staff_emoji(guild: Optional[discord.Guild], role: str) -> str:
    """Get custom emoji for staff roles (judge / recorder)."""
    key = "judge" if role.lower() == "judge" else "recorder"
    return get_emoji(key, guild=guild, default=EMOJIS.get(key, ""))
