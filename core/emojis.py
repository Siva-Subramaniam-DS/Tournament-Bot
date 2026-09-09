import discord
from typing import Optional

# ===========================================================================================
# CUSTOM DISCORD EMOJIS REGISTRY (APPLICATION EMOJIS & SERVER EMOJIS)
# ===========================================================================================

EMOJI_IDS = {
    # Core Tournament & Roles
    "vs": 1547124088449929247,
    "verified": 1547124086084472912,
    "trophy": 1547124059656167465,
    "winner": 1547124059656167465,
    "recorder": 1547124365684908092,
    "not_verified": 1547124074805854239,
    "not_in_server": 1547128818500902923,
    "attendance_done": 1547124086084472912,
    "match_done": 1547124086084472912,
    "skull": 1547124357006888970,
    "loser": 1547124357006888970,
    "judge": 1547124067163963452,
    "details": 1547124077385228338,
    "player": 1547124077385228338,
    "player_details": 1547124077385228338,
    "captain": 1547124055025520761,
    "captain_details": 1547124055025520761,
    "helpers": 1547124062168551464,
    "organizer": 1547124062168551464,
    "rules": 1547124083626614854,
    "clock": 1547124057504358480,
    "announcement": 1547124072150999070,

    # Staff Actions & Management
    "staff_in": 1547128838998462465,
    "staff_out": 1547128842618015806,
    "cameraman_in": 1547128838998462465,
    "cameraman_out": 1547128842618015806,
    "cameraman_add": 1547128838998462465,
    "cameraman_remove": 1547128842618015806,
    "exchange_staff": 1547142285161009192,

    # UI / Status / System emojis
    "gear": 1547124946407522384,
    "caution": 1547128818500902923,
    "folder": 1547128846288035930,
    "trashcan": 1547128832040112188,
    "loading": 1547124896285466684,
    "wrong": 1547124074805854239,
    "dice": 1547124064492199997,

    # Navigation & Interactive Button emojis
    "left_side_button": 1547142290005561364,
    "right_side_button": 1547142287497101342,
    "take_schedule": 1547142298079334460,
    "record_match": 1547142295541907536,
    "confirm_presence": 1547142292589252608,
}

# Direct Discord emoji format strings (Application Emojis uploaded in Discord Dev Portal)
EMOJIS = {
    # Core Tournament & Roles
    "vs": "<:VS:1547124088449929247>",
    "verified": "<:VerifiedCheckmark:1547124086084472912>",
    "trophy": "<:GoldenTournamentTrophy:1547124059656167465>",
    "winner": "<:GoldenTournamentTrophy:1547124059656167465>",
    "recorder": "<:Recorder:1547124365684908092>",
    "not_verified": "<:NotVerified:1547124074805854239>",
    "not_in_server": "<:NotinServer:1547128818500902923>",
    "attendance_done": "<:VerifiedCheckmark:1547124086084472912>",
    "match_done": "<:VerifiedCheckmark:1547124086084472912>",
    "skull": "<:Loser:1547124357006888970>",
    "loser": "<:Loser:1547124357006888970>",
    "judge": "<:JudgeGavel:1547124067163963452>",
    "details": "<:Player:1547124077385228338>",
    "player": "<:Player:1547124077385228338>",
    "player_details": "<:Player:1547124077385228338>",
    "captain": "<:CaptainBadge:1547124055025520761>",
    "captain_details": "<:CaptainBadge:1547124055025520761>",
    "helpers": "<:HelperOrganizer:1547124062168551464>",
    "organizer": "<:HelperOrganizer:1547124062168551464>",
    "rules": "<:TournamentRules:1547124083626614854>",
    "clock": "<:Clock:1547124057504358480>",
    "announcement": "<:MegaAnnouncement:1547124072150999070>",

    # Staff Actions & Management
    "staff_in": "<:StaffMemberIn:1547128838998462465>",
    "staff_out": "<:StaffMemberOut:1547128842618015806>",
    "cameraman_in": "<:StaffMemberIn:1547128838998462465>",
    "cameraman_out": "<:StaffMemberOut:1547128842618015806>",
    "cameraman_add": "<:StaffMemberIn:1547128838998462465>",
    "cameraman_remove": "<:StaffMemberOut:1547128842618015806>",
    "exchange_staff": "<:ExchangeStaff:1547142285161009192>",

    # UI / Status emojis
    "gear": "<:SettingsGear:1547124946407522384>",
    "caution": "<:NotinServer:1547128818500902923>",
    "folder": "<:TicketArchiveFolder:1547128846288035930>",
    "trashcan": "<:RedCyberTrashcan:1547128832040112188>",
    "loading": "<a:Loading:1547124896285466684>",
    "wrong": "<:NotVerified:1547124074805854239>",
    "dice": "<:HolographicDice:1547124064492199997>",

    # Navigation & Interactive Button emojis
    "left_side_button": "<:PreviousPageArrow:1547142290005561364>",
    "right_side_button": "<:NextPageArrow:1547142287497101342>",
    "take_schedule": "<:TakeSchedule:1547142298079334460>",
    "record_match": "<:RecordMatch:1547142295541907536>",
    "confirm_presence": "<:ConfirmPresence:1547142292589252608>",
}

# PartialEmoji instances for direct use in discord.ui.Button
LEFT_BUTTON_EMOJI = discord.PartialEmoji(name="PreviousPageArrow", id=1547142290005561364)
RIGHT_BUTTON_EMOJI = discord.PartialEmoji(name="NextPageArrow", id=1547142287497101342)
TAKE_SCHEDULE_BUTTON_EMOJI = discord.PartialEmoji(name="TakeSchedule", id=1547142298079334460)
RECORD_BUTTON_EMOJI = discord.PartialEmoji(name="RecordMatch", id=1547142295541907536)
CONFIRM_PRESENCE_BUTTON_EMOJI = discord.PartialEmoji(name="ConfirmPresence", id=1547142292589252608)
EXCHANGE_STAFF_BUTTON_EMOJI = discord.PartialEmoji(name="ExchangeStaff", id=1547142285161009192)
VERIFIED_BUTTON_EMOJI = discord.PartialEmoji(name="VerifiedCheckmark", id=1547124086084472912)

# Dynamic cache for real resolved Discord emoji strings
EMOJI_CACHE = {}

import re

def _norm_name(n: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', str(n)).lower()

NAME_TO_KEY = {
    # Core Tournament & Roles
    "vs": "vs",
    "verifiedcheckmark": "verified",
    "verified": "verified",
    "goldentournamenttrophy": "trophy",
    "trophy": "trophy",
    "winner": "winner",
    "recorder": "recorder",
    "notverified": "not_verified",
    "notinserver": "not_in_server",
    "loser": "loser",
    "skull": "skull",
    "judgegavel": "judge",
    "judge": "judge",
    "player": "player",
    "playerdetails": "player_details",
    "captainbadge": "captain",
    "captain": "captain",
    "captaindetails": "captain_details",
    "helperorganizer": "helpers",
    "helpers": "helpers",
    "helper": "helpers",
    "organizer": "organizer",
    "tournamentrules": "rules",
    "rules": "rules",
    "clock": "clock",
    "megaannouncement": "announcement",
    "announcement": "announcement",

    # Staff Actions
    "staffmemberin": "staff_in",
    "staffmemberout": "staff_out",
    "cameramanadd": "cameraman_in",
    "cameramanremove": "cameraman_out",
    "exchangestaff": "exchange_staff",

    # UI / Status
    "settingsgear": "gear",
    "gear": "gear",
    "ticketarchivefolder": "folder",
    "folder": "folder",
    "redcybertrashcan": "trashcan",
    "trashcan": "trashcan",
    "loading": "loading",
    "holographicdice": "dice",
    "dice": "dice",

    # Buttons
    "previouspagearrow": "left_side_button",
    "nextpagearrow": "right_side_button",
    "takeschedule": "take_schedule",
    "recordmatch": "record_match",
    "confirmpresence": "confirm_presence",
}

async def init_emojis_from_bot(bot):
    """
    Scan application emojis from Discord Developer Portal first (high priority),
    caching their exact strings by ID and name. Server emojis only fill in missing keys.
    """
    global EMOJI_CACHE
    found_count = 0

    # 1. Fetch Application Emojis from Discord Developer Portal (PRIORITY)
    try:
        if hasattr(bot, 'fetch_application_emojis'):
            app_emojis = await bot.fetch_application_emojis()
            for emoji in app_emojis:
                prefix = "a" if getattr(emoji, 'animated', False) else ""
                formatted = f"<{prefix}:{emoji.name}:{emoji.id}>"
                norm = _norm_name(emoji.name)

                # Match by ID
                for k, v in EMOJI_IDS.items():
                    if v == emoji.id:
                        EMOJI_CACHE[k] = formatted
                        EMOJIS[k] = formatted
                        found_count += 1

                # Match by normalized name
                if norm in NAME_TO_KEY:
                    target_k = NAME_TO_KEY[norm]
                    EMOJI_CACHE[target_k] = formatted
                    EMOJIS[target_k] = formatted
                    if target_k == "attendance_done":
                        EMOJI_CACHE["match_done"] = formatted
                        EMOJIS["match_done"] = formatted
                    if target_k == "cameraman_in":
                        EMOJI_CACHE["cameraman_add"] = formatted
                        EMOJIS["cameraman_add"] = formatted
                    if target_k == "cameraman_out":
                        EMOJI_CACHE["cameraman_remove"] = formatted
                        EMOJIS["cameraman_remove"] = formatted
                    found_count += 1
            print(f"✅ Loaded {len(app_emojis)} Application Emojis from Developer Portal.")
    except Exception as e:
        print(f"  [App Emojis Info] Could not fetch application emojis: {e}")

    # 2. Guild emojis (fill in only what is not already in EMOJI_CACHE)
    if hasattr(bot, 'emojis'):
        for emoji in bot.emojis:
            prefix = "a" if getattr(emoji, 'animated', False) else ""
            formatted = f"<{prefix}:{emoji.name}:{emoji.id}>"
            norm = _norm_name(emoji.name)

            for k, v in EMOJI_IDS.items():
                if v == emoji.id and k not in EMOJI_CACHE:
                    EMOJI_CACHE[k] = formatted
                    EMOJIS[k] = formatted
                    found_count += 1

            if norm in NAME_TO_KEY:
                target_k = NAME_TO_KEY[norm]
                if target_k not in EMOJI_CACHE:
                    EMOJI_CACHE[target_k] = formatted
                    EMOJIS[target_k] = formatted
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

