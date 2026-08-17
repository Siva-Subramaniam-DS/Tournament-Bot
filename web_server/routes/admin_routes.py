from flask import Blueprint, request, jsonify
from web_server.auth import super_admin_required, organizer_required, hash_password
from web_server.database import (
    get_all_guilds, get_tournaments, save_web_user, supabase,
    LOCAL_WEB_USERS_FILE, _load_json_file,
    get_activity_logs, log_activity,
    get_command_configs, save_command_configs
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
        
        log_activity(
            action_type="USER_CREATE",
            actor=user.get("username", "admin"),
            description=f"Created web admin user '{username}' with role '{role}'",
            target=username,
            category="admin"
        )
        
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

@admin_bp.route("/logs", methods=["GET"])
@organizer_required
def get_audit_logs_api(user):
    """Retrieve audit activity logs across organizer actions and admin operations."""
    category = request.args.get("category", "all")
    guild_id = request.args.get("guild_id")
    limit = int(request.args.get("limit", 150))
    
    logs = get_activity_logs(category=category, guild_id=guild_id, limit=limit)
    return jsonify({
        "status": "success",
        "total": len(logs),
        "logs": logs
    })

@admin_bp.route("/commands", methods=["GET", "POST"])
@organizer_required
def manage_command_configs_api(user):
    """Fetch or customize Discord bot slash commands, permissions, and response templates."""
    guild_id = request.args.get("guild_id") or request.json.get("guild_id") if request.is_json else None
    
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        g_id = str(data.get("guild_id", ""))
        commands_dict = data.get("commands", {})
        
        if not commands_dict and data.get("command_key") and data.get("config"):
            current = get_command_configs(g_id)
            current[data["command_key"]] = data["config"]
            commands_dict = current
            
        if not commands_dict:
            return jsonify({"error": "commands payload required"}), 400
            
        saved = save_command_configs(g_id, commands_dict)
        return jsonify({
            "status": "success",
            "message": "Discord bot command settings & templates saved successfully!",
            "commands": saved
        })

    # GET
    cmd_configs = get_command_configs(guild_id)
    return jsonify({
        "status": "success",
        "guild_id": guild_id or "default",
        "commands": cmd_configs
    })
