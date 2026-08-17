import hashlib
import os
import secrets
import datetime
from functools import wraps
from typing import Optional, Dict, Any, List
import jwt
import requests
from flask import request, jsonify, redirect, make_response
from web_server.config import (
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES,
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_REDIRECT_URI,
    DISCORD_API_BASE, DISCORD_TOKEN_URL, DISCORD_BOT_TOKEN,
    MASTER_DISCORD_IDS
)
from web_server.database import get_guild_config, get_all_guilds, get_web_user_by_username

# =========================================================================
# PASSWORD HASHING (PBKDF2-HMAC-SHA256 - NIST Approved & Zero Extra Deps)
# =========================================================================
def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with random salt."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"{salt}${key.hex()}"

def verify_password(stored_password_hash: str, provided_password: str) -> bool:
    """Verify password against stored hash."""
    try:
        if not stored_password_hash or "$" not in stored_password_hash:
            return False
        salt, stored_hash = stored_password_hash.split("$", 1)
        key = hashlib.pbkdf2_hmac(
            'sha256',
            provided_password.encode('utf-8'),
            salt.encode('utf-8'),
            100000
        )
        return secrets.compare_digest(key.hex(), stored_hash)
    except Exception as e:
        print(f"[Auth] Password verification error: {e}")
        return False

# =========================================================================
# JWT SESSION TOKEN ENGINE
# =========================================================================
def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    """Generate signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + (expires_delta or datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

# =========================================================================
# DISCORD OAUTH2 HELPERS
# =========================================================================
def exchange_discord_code(code: str) -> Optional[Dict[str, Any]]:
    """Exchange authorization code for Discord access token."""
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    try:
        res = requests.post(DISCORD_TOKEN_URL, data=data, headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
        else:
            print(f"[Discord OAuth] Token exchange failed ({res.status_code}): {res.text}")
            return None
    except Exception as e:
        print(f"[Discord OAuth] Token exchange error: {e}")
        return None

def get_discord_user_info(access_token: str) -> Optional[Dict[str, Any]]:
    """Fetch logged in user profile from Discord API."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(f"{DISCORD_API_BASE}/users/@me", headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[Discord OAuth] User info error: {e}")
    return None

def get_discord_user_guilds(access_token: str) -> List[Dict[str, Any]]:
    """Fetch list of guilds user belongs to."""
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers, timeout=10)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[Discord OAuth] User guilds error: {e}")
    return []

def fetch_guild_member_roles(guild_id: str, user_id: str) -> List[str]:
    """Fetch specific user roles in a guild using Bot token."""
    if not DISCORD_BOT_TOKEN:
        return []
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    try:
        res = requests.get(f"{DISCORD_API_BASE}/guilds/{guild_id}/members/{user_id}", headers=headers, timeout=10)
        if res.status_code == 200:
            member_data = res.json()
            return member_data.get("roles", [])
    except Exception as e:
        print(f"[Discord OAuth] Guild roles error: {e}")
    return []

# =========================================================================
# RBAC ROLE RESOLUTION LOGIC
# =========================================================================
def resolve_user_permissions(discord_user: Dict[str, Any], user_guilds: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Determine if user is Super Admin, Tournament Organizer, or Public Viewer.
    Returns dictionary with authorized guild IDs and global role.
    """
    user_id = str(discord_user.get("id"))
    username = discord_user.get("username", "User")
    avatar = discord_user.get("avatar")
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.png" if avatar else "https://cdn.discordapp.com/embed/avatars/0.png"

    # 1. Check if user is hardcoded / configured Admin
    if user_id in MASTER_DISCORD_IDS:
        all_guilds = get_all_guilds()
        return {
            "user_id": user_id,
            "username": username,
            "avatar_url": avatar_url,
            "role": "admin",
            "is_admin": True,
            "is_super_admin": True,  # Keep for backward compatibility
            "authorized_guild_ids": [g["guild_id"] for g in all_guilds],
            "guilds": user_guilds
        }

    # 2. Check Organizer status per guild
    authorized_guild_ids = []
    for g in user_guilds:
        gid = str(g.get("id"))
        is_owner = g.get("owner", False)
        permissions = int(g.get("permissions", 0))
        has_admin_perm = (permissions & 0x8) == 0x8  # Administrator permission flag

        if is_owner or has_admin_perm:
            authorized_guild_ids.append(gid)
            continue

        # Check configured roles in GuildConfig
        config = get_guild_config(gid)
        organizer_role_id = config.get("organizer_role_id")
        admin_role_id = config.get("admin_role_id")

        if organizer_role_id or admin_role_id:
            user_roles = fetch_guild_member_roles(gid, user_id)
            if (organizer_role_id and str(organizer_role_id) in user_roles) or \
               (admin_role_id and str(admin_role_id) in user_roles):
                authorized_guild_ids.append(gid)

    role = "organizer" if len(authorized_guild_ids) > 0 else "viewer"
    return {
        "user_id": user_id,
        "username": username,
        "avatar_url": avatar_url,
        "role": role,
        "is_admin": False,
        "is_super_admin": False,
        "authorized_guild_ids": authorized_guild_ids,
        "guilds": user_guilds
    }

# =========================================================================
# FLASK AUTHENTICATION HELPERS & DECORATORS
# =========================================================================
def get_current_user_from_request() -> Optional[Dict[str, Any]]:
    """Extract user payload from Authorization header or session cookie."""
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    elif "access_token" in request.cookies:
        token = request.cookies.get("access_token")

    if not token:
        return None
    return decode_access_token(token)

def login_required(f):
    """Decorator requiring valid user session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user_from_request()
        if not user:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        return f(*args, user=user, **kwargs)
    return decorated_function

def organizer_required(f):
    """Decorator requiring Tournament Organizer or Admin status."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user_from_request()
        if not user:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        if user.get("is_admin") or user.get("is_super_admin") or user.get("role") in ["admin", "organizer", "super_admin"]:
            return f(*args, user=user, **kwargs)
        return jsonify({"error": "Access denied. Organizer or Admin role required."}), 403
    return decorated_function

def admin_required(f):
    """Decorator requiring Admin status."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user_from_request()
        if not user:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        if not user.get("is_admin") and user.get("role") not in ["admin", "super_admin"] and not user.get("is_super_admin"):
            return jsonify({"error": "Access denied. Admin permissions required."}), 403
        return f(*args, user=user, **kwargs)
    return decorated_function

# Legacy alias
super_admin_required = admin_required

