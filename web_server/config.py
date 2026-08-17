import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Server Configuration
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")
SECRET_KEY = os.getenv("JWT_SECRET", "super-secret-tournament-bot-jwt-key-2026-xyz987")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 Days session

# Discord OAuth2 Credentials
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/api/auth/discord/callback")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Discord API Endpoints
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_OAUTH_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"

# Supabase Credentials
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Master Admin / Owner Settings
# Comma-separated Discord User IDs who automatically have Super Admin rights
MASTER_DISCORD_IDS = [
    x.strip() for x in os.getenv("MASTER_DISCORD_IDS", "1303887060754497569").split(",") if x.strip()
]

# Default Master Username and Password (Can be initialized or changed)
DEFAULT_MASTER_USERNAME = os.getenv("MASTER_ADMIN_USER", "Hokageadmin")
DEFAULT_MASTER_PASSWORD = os.getenv("MASTER_ADMIN_PASS", "MyHokageadmin2004")

