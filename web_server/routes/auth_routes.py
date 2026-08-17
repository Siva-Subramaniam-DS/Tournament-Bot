import urllib.parse
from flask import Blueprint, request, jsonify, redirect, make_response
from web_server.config import (
    DISCORD_CLIENT_ID, DISCORD_OAUTH_URL, DISCORD_REDIRECT_URI,
    DEFAULT_MASTER_USERNAME, DEFAULT_MASTER_PASSWORD
)
from web_server.auth import (
    exchange_discord_code, get_discord_user_info, get_discord_user_guilds,
    resolve_user_permissions, create_access_token, verify_password, hash_password,
    get_current_user_from_request
)
from web_server.database import get_web_user_by_username, save_web_user

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# =========================================================================
# DISCORD OAUTH2 ENDPOINTS
# =========================================================================
@auth_bp.route("/discord/login", methods=["GET"])
def discord_login():
    """Redirect to Discord OAuth2 Authorization Page."""
    if not DISCORD_CLIENT_ID:
        return jsonify({
            "error": "Discord Client ID not configured. Please set DISCORD_CLIENT_ID in your .env file."
        }), 500

    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify guilds"
    }
    url = f"{DISCORD_OAUTH_URL}?{urllib.parse.urlencode(params)}"
    return redirect(url)

@auth_bp.route("/discord/callback", methods=["GET"])
def discord_callback():
    """Handle Discord OAuth2 Callback and Issue JWT Session."""
    code = request.args.get("code")
    error = request.args.get("error")

    if error or not code:
        return redirect("/login?error=discord_denied")

    token_data = exchange_discord_code(code)
    if not token_data or "access_token" not in token_data:
        return redirect("/login?error=token_exchange_failed")

    access_token = token_data["access_token"]
    user_info = get_discord_user_info(access_token)
    if not user_info:
        return redirect("/login?error=user_info_failed")

    user_guilds = get_discord_user_guilds(access_token)
    permissions = resolve_user_permissions(user_info, user_guilds)

    # Issue JWT session token
    jwt_payload = {
        "sub": permissions["user_id"],
        "username": permissions["username"],
        "avatar_url": permissions["avatar_url"],
        "role": permissions["role"],
        "is_super_admin": permissions["is_super_admin"],
        "authorized_guild_ids": permissions["authorized_guild_ids"]
    }
    jwt_token = create_access_token(jwt_payload)

    redirect_url = "/dashboard" if permissions["role"] in ["super_admin", "organizer"] else "/"
    response = make_response(redirect(redirect_url))
    response.set_cookie(
        "access_token",
        jwt_token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="Lax"
    )
    return response

# =========================================================================
# MASTER ADMIN LOGIN (USERNAME & PASSWORD FALLBACK)
# =========================================================================
@auth_bp.route("/master-login", methods=["POST"])
def master_login():
    """Super Admin login using dedicated credentials."""
    data = request.get_json(silent=True) or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    user_record = get_web_user_by_username(username)
    authenticated = False
    role = "admin"

    if user_record:
        if verify_password(user_record.get("password_hash", ""), password):
            authenticated = True
            role = user_record.get("role", "admin")
    else:
        # Fallback to default bootstrap credentials
        if username == DEFAULT_MASTER_USERNAME and password == DEFAULT_MASTER_PASSWORD:
            authenticated = True
            save_web_user(DEFAULT_MASTER_USERNAME, hash_password(DEFAULT_MASTER_PASSWORD), role="admin")

    if not authenticated:
        return jsonify({"error": "Invalid username or password"}), 401

    is_admin = (role == "admin" or role == "super_admin")

    # Create Master Admin JWT Session
    jwt_payload = {
        "sub": username,
        "username": username,
        "avatar_url": "https://cdn.discordapp.com/embed/avatars/1.png",
        "role": role,
        "is_admin": is_admin,
        "is_super_admin": is_admin,
        "authorized_guild_ids": ["*"] # Global access across all servers
    }
    jwt_token = create_access_token(jwt_payload)

    resp = make_response(jsonify({
        "status": "success",
        "message": f"Authenticated successfully as {role.capitalize()}",
        "token": jwt_token,
        "user": jwt_payload
    }))
    resp.set_cookie(
        "access_token",
        jwt_token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="Lax"
    )
    return resp

# =========================================================================
# SESSION & USER STATUS
# =========================================================================
@auth_bp.route("/me", methods=["GET"])
def get_current_user_profile():
    """Return currently logged-in user profile and permissions."""
    user = get_current_user_from_request()
    if not user:
        return jsonify({"authenticated": False, "user": None})
    return jsonify({
        "authenticated": True,
        "user": {
            "user_id": user.get("sub"),
            "username": user.get("username"),
            "avatar_url": user.get("avatar_url"),
            "role": user.get("role"),
            "is_super_admin": user.get("is_super_admin", False),
            "authorized_guild_ids": user.get("authorized_guild_ids", [])
        }
    })

@auth_bp.route("/logout", methods=["POST", "GET"])
def logout():
    """Clear session cookie and redirect."""
    resp = make_response(redirect("/login"))
    resp.delete_cookie("access_token")
    return resp
