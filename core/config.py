import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure output encoding on Windows if needed
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding='utf-8')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Discord Credentials
TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")

# Supabase Credentials
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Bot Owner ID for superuser permissions
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "1251442077561131059"))

# Default Brand Color (deep navy blue)
BRAND_COLOR = 0x1E3A5F

# Default Organization & System Names
ORGANIZATION_NAME = "Tournament Organizer"
TOURNAMENT_SYSTEM_NAME = "Tournament Management System"

# Default Configs — Multi-Server Configuration Defaults
DEFAULT_CHANNEL_IDS = {
    "rules":        None,    # Rules
    "bracket":      None,    # Bracket
    "deadlines":    None,    # Deadlines
    "staff_attendance": None, # Attendance
    "take_schedule": None,   # Schedule Channel
    "results":      None,    # Result
    "category_1":   None,    # Category 1
    "category_2":   None,    # Category 2
    "closed_tickets_category": None,  # Closed Tickets
    "challonge_logs": None,  # Challonge Logs Channel
    "transcript_logs": None, # Transcript Logs Channel
    "bot_logs":     None,    # Bot Logs Channel
    "thumbnail":    None     # Thumbnail Channel
}

DEFAULT_ROLE_IDS = {
    "head_organizer": None,  # Admin Role
    "organizer":      None,  # Organizer Role
    "helper_team":    None,  # Helper / Head Helper Role
    "judge":          None,  # Judge Role
    "recorder":       None,  # Recorder Role
    "staff":          None,  # Staff Role
    "players":        None,  # Players Role
    "verification":   None,  # Verification Role (given to verified members)
    "challonge_role": None   # Challonge Role (legacy)
}

# Known game aliases mapping to template folder names
GAME_ALIASES = {
    "mw": "Modern Warship",
    "modern warships": "Modern Warship",
    "modernwarship": "Modern Warship",
    "modern warship": "Modern Warship",
    "bgmi": "BGMI",
    "pubg": "BGMI",
    "pubgm": "BGMI",
    "pubg mobile": "BGMI",
    "free fire": "Free Fire",
    "ff": "Free Fire",
    "freefire": "Free Fire",
    "val": "Valorant",
    "valo": "Valorant",
    "valorant": "Valorant",
    "cod": "Call of Duty Mobile",
    "codm": "Call of Duty Mobile",
    "call of duty": "Call of Duty Mobile",
    "call of duty mobile": "Call of Duty Mobile",
    "ml": "Mobile Legends",
    "mlbb": "Mobile Legends",
    "mobile legends": "Mobile Legends",
    "cs": "Counter Strike 2",
    "cs2": "Counter Strike 2",
    "csgo": "Counter Strike 2",
    "counter strike": "Counter Strike 2",
    "counter strike 2": "Counter Strike 2",
    "apex": "Apex Legends",
    "apex legends": "Apex Legends",
    "fortnite": "Fortnite",
    "fn": "Fortnite",
    "rl": "Rocket League",
    "rocket league": "Rocket League",
    "dota": "Dota 2",
    "dota 2": "Dota 2",
    "dota2": "Dota 2",
    "brawl stars": "Brawl Stars",
    "bs": "Brawl Stars",
    "brawlstars": "Brawl Stars",
    "clash royale": "Clash Royale",
    "cr": "Clash Royale",
    "clashroyale": "Clash Royale",
    "r6": "Rainbow Six Siege",
    "r6s": "Rainbow Six Siege",
    "rainbow six": "Rainbow Six Siege",
    "rainbow six siege": "Rainbow Six Siege",
    "warzone": "Warzone",
    "wzm": "Warzone",
    "cod warzone": "Warzone"
}

