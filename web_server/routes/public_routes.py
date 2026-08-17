from flask import Blueprint, request, jsonify, redirect
from web_server.database import (
    get_all_guilds, get_guild_config, get_tournaments, get_tournament_by_id,
    get_events, get_sponsors, log_sponsor_click, get_affiliate_products
)

public_bp = Blueprint("public", __name__, url_prefix="/api/public")

@public_bp.route("/guilds", methods=["GET"])
def list_guilds():
    """List all participating Discord tournament guilds."""
    guilds = get_all_guilds()
    return jsonify({"status": "success", "guilds": guilds})

@public_bp.route("/tournaments", methods=["GET"])
def list_tournaments():
    """List active tournaments, optionally filtered by guild_id."""
    guild_id = request.args.get("guild_id")
    tournaments = get_tournaments(guild_id=guild_id)
    return jsonify({"status": "success", "tournaments": tournaments})

@public_bp.route("/tournaments/<tournament_id>", methods=["GET"])
def get_tournament_details(tournament_id):
    """Get single tournament details."""
    tourney = get_tournament_by_id(tournament_id)
    if not tourney:
        return jsonify({"error": "Tournament not found"}), 404
    
    guild_id = tourney.get("Guild_ID") or tourney.get("guild_id")
    guild_config = get_guild_config(guild_id) if guild_id else {}
    sponsors = get_sponsors(guild_id=guild_id, tournament_id=tournament_id)
    events = get_events(tournament_name=tourney.get("Tournament_Name"), guild_id=guild_id)

    return jsonify({
        "status": "success",
        "tournament": tourney,
        "guild": guild_config,
        "sponsors": sponsors,
        "events": events
    })

@public_bp.route("/sponsors", methods=["GET"])
def list_sponsors():
    """Fetch active sponsor banners."""
    guild_id = request.args.get("guild_id")
    tournament_id = request.args.get("tournament_id")
    sponsors = get_sponsors(guild_id=guild_id, tournament_id=tournament_id)
    return jsonify({"status": "success", "sponsors": sponsors})

@public_bp.route("/click/<sponsor_id>", methods=["GET"])
def handle_sponsor_click(sponsor_id):
    """Track sponsor banner click and redirect to partner page."""
    user_ip = request.remote_addr or ""
    user_agent = request.headers.get("User-Agent", "")
    target_url = log_sponsor_click(sponsor_id, user_ip, user_agent)
    return redirect(target_url)

@public_bp.route("/affiliates", methods=["GET"])
def list_affiliates():
    """Fetch affiliate gaming store cards & in-game currency top-ups."""
    game = request.args.get("game", "all")
    products = get_affiliate_products(game_category=game)
    return jsonify({"status": "success", "products": products})

@public_bp.route("/events", methods=["GET"])
def list_events():
    """Fetch recent matches and schedule."""
    guild_id = request.args.get("guild_id")
    tournament_name = request.args.get("tournament")
    events = get_events(tournament_name=tournament_name, guild_id=guild_id)
    return jsonify({"status": "success", "events": events})
