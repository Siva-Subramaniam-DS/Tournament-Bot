from flask import Blueprint, request, jsonify
from web_server.auth import super_admin_required, hash_password
from web_server.database import (
    get_all_guilds, get_tournaments, save_web_user, supabase,
    LOCAL_WEB_USERS_FILE, _load_json_file
)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

@admin_bp.route("/system", methods=["GET"])
@super_admin_required
def get_system_status(user):
    """Platform health check and summary stats."""
    guilds = get_all_guilds()
    tournaments = get_tournaments()
    
    return jsonify({
        "status": "healthy",
        "supabase_connected": supabase is not None,
        "total_guilds": len(guilds),
        "total_tournaments": len(tournaments),
        "admin_user": user.get("username")
    })

@admin_bp.route("/users", methods=["GET", "POST"])
@super_admin_required
def manage_web_users(user):
    """List or create master admin accounts."""
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        role = data.get("role", "super_admin")
        discord_id = data.get("discord_id")

        if not username or not password:
            return jsonify({"error": "Username and password required"}), 400

        pw_hash = hash_password(password)
        save_web_user(username, pw_hash, role=role, discord_id=discord_id)
        return jsonify({"status": "success", "message": f"User {username} created successfully"})

    # GET
    users = []
    if supabase:
        try:
            res = supabase.table("WebUsers").select("id, username, role, discord_id, created_at, last_login").execute()
            if res.data:
                users = res.data
        except Exception as e:
            print(f"[Admin] Error fetching users from Supabase: {e}")

    if not users:
        local_users = _load_json_file(LOCAL_WEB_USERS_FILE, {})
        for u, data in local_users.items():
            users.append({
                "username": u,
                "role": data.get("role", "super_admin"),
                "discord_id": data.get("discord_id"),
                "created_at": data.get("created_at")
            })

    return jsonify({"status": "success", "users": users})
