import os
from pathlib import Path
from flask import Flask, render_template, request, redirect, jsonify
from web_server.config import PORT, HOST, BASE_DIR
from web_server.auth import get_current_user_from_request
from web_server.database import (
    get_tournaments, get_tournament_by_id, get_sponsors,
    get_affiliate_products, get_events, get_guild_config, get_all_guilds
)
from web_server.routes.auth_routes import auth_bp
from web_server.routes.public_routes import public_bp
from web_server.routes.organizer_routes import organizer_bp
from web_server.routes.admin_routes import admin_bp

TEMPLATES_DIR = BASE_DIR / "web_server" / "templates"
STATIC_DIR = BASE_DIR / "web_server" / "static"

app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR)
)
app.config["SECRET_KEY"] = os.getenv("JWT_SECRET", "super-secret-tournament-bot-jwt-key")

# Register API Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(public_bp)
app.register_blueprint(organizer_bp)
app.register_blueprint(admin_bp)

# Context Processor for Global Template Variables
@app.context_processor
def inject_global_data():
    user = get_current_user_from_request()
    is_admin = user.get("role") in ["admin", "super_admin"] or user.get("is_admin", False) if user else False
    is_org = user.get("role") in ["admin", "organizer", "super_admin"] or user.get("is_admin", False) if user else False
    return {
        "current_user": user,
        "is_logged_in": user is not None,
        "is_admin": is_admin,
        "is_organizer": is_org,
        "is_super_admin": is_admin  # Backward compatibility
    }

# =========================================================================
# WEB PAGE ROUTES
# =========================================================================
@app.route("/")
def home():
    """Public Landing Page & Tournament Explorer."""
    tournaments = get_tournaments()
    guilds = get_all_guilds()
    sponsors = get_sponsors()
    affiliates = get_affiliate_products()
    return render_template(
        "index.html",
        tournaments=tournaments,
        guilds=guilds,
        sponsors=sponsors,
        affiliates=affiliates
    )

@app.route("/tournament/<tournament_id>")
def tournament_page(tournament_id):
    """Public Interactive Bracket & Match Details Page."""
    tourney = get_tournament_by_id(tournament_id)
    if not tourney:
        return render_template("404.html", message="Tournament Not Found"), 404

    guild_id = tourney.get("Guild_ID") or tourney.get("guild_id")
    guild_config = get_guild_config(guild_id) if guild_id else {}
    sponsors = get_sponsors(guild_id=guild_id, tournament_id=tournament_id)
    events = get_events(tournament_name=tourney.get("Tournament_Name"), guild_id=guild_id)
    
    # Infer game category from tournament name or default to Valorant/General
    game_category = "General"
    for game in ["Valorant", "BGMI", "Free Fire", "Call of Duty", "Brawl Stars", "Clash Royale", "Dota 2", "Fortnite", "Rocket League", "CS2"]:
        if game.lower() in str(tourney.get("Tournament_Name", "")).lower():
            game_category = game
            break

    affiliates = get_affiliate_products(game_category=game_category)

    user = get_current_user_from_request()
    auth_guilds = user.get("authorized_guild_ids", []) if user else []
    is_organizer = False
    if user:
        is_organizer = (
            user.get("is_admin") or
            user.get("is_super_admin") or
            user.get("role") in ["admin", "organizer", "super_admin"] or
            "*" in auth_guilds or
            str(guild_id) in [str(g) for g in auth_guilds]
        )

    return render_template(
        "tournament.html",
        tournament=tourney,
        guild=guild_config,
        sponsors=sponsors,
        events=events,
        affiliates=affiliates,
        game_category=game_category,
        user=user,
        is_organizer=is_organizer
    )

@app.route("/commands")
def commands_page():
    """Discord Command Reference & Operational Guide."""
    return render_template("commands.html")

@app.route("/login")
def login_page():
    """Dual Login Portal (Discord OAuth2 + Master Admin Credentials)."""
    user = get_current_user_from_request()
    if user:
        return redirect("/dashboard" if user.get("role") in ["admin", "organizer", "super_admin"] else "/")
    return render_template("login.html")

@app.route("/dashboard")
def dashboard_page():
    """Tournament Organizer & Admin Management Dashboard."""
    user = get_current_user_from_request()
    if not user:
        return redirect("/login")
    if user.get("role") not in ["admin", "organizer", "super_admin"] and not user.get("is_admin") and not user.get("is_super_admin"):
        return redirect("/?error=insufficient_permissions")

    auth_guilds = user.get("authorized_guild_ids", [])
    is_admin = user.get("is_admin") or user.get("is_super_admin") or user.get("role") == "admin" or "*" in auth_guilds
    
    all_tourneys = get_tournaments()
    if is_admin:
        tournaments = all_tourneys
    else:
        tournaments = [
            t for t in all_tourneys
            if str(t.get("Guild_ID") or t.get("guild_id")) in [str(g) for g in auth_guilds]
        ]

    sponsors = get_sponsors()
    affiliates = get_affiliate_products()
    guilds = get_all_guilds()

    return render_template(
        "dashboard.html",
        user=user,
        tournaments=tournaments,
        sponsors=sponsors,
        affiliates=affiliates,
        guilds=guilds
    )

if __name__ == "__main__":
    print(f"🚀 Starting Tournament Web Portal on http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=True)
