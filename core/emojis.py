import discord
from typing import Optional

# ===========================================================================================
# CUSTOM DISCORD EMOJIS REGISTRY
# ===========================================================================================

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

def get_emoji(name: str, default: str = "") -> str:
    """Retrieve the formatted custom emoji string, or a fallback default."""
    return EMOJIS.get(name, default)

def get_staff_emoji(guild: Optional[discord.Guild], role: str) -> str:
    """
    Get custom emoji for staff roles (judge / recorder).
    Prefers the guild-resolved emoji object if available, falling back to the configured custom emoji string.
    """
    if role.lower() == "judge":
        target_id = 1544980903871127645
        fallback = EMOJIS["judge"]
    else:
        target_id = 1544981791566331924
        fallback = EMOJIS["recorder"]

    if guild:
        for emoji in guild.emojis:
            if emoji.id == target_id:
                return str(emoji)
            if role.lower() == "judge" and "judge" in emoji.name.lower():
                return str(emoji)
            if role.lower() != "judge" and any(k in emoji.name.lower() for k in ["recorder", "camera"]):
                return str(emoji)

    return fallback
