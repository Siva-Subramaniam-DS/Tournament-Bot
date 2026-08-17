import json
import os
import uuid
import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from supabase import create_client, Client
from web_server.config import SUPABASE_URL, SUPABASE_KEY, BASE_DIR

# Initialize Supabase Client
supabase: Optional[Client] = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[Web Server] Supabase client initialized successfully.")
    except Exception as e:
        print(f"[Web Server] Supabase initialization failed: {e}")
else:
    print("[Web Server] Supabase credentials not provided. Using local JSON store.")

# Local Fallback File Helpers
LOCAL_GUILD_CONFIGS_FILE = BASE_DIR / "guild_configs.json"
LOCAL_TOURNAMENTS_FILE = BASE_DIR / "tournaments.json"
LOCAL_EVENTS_FILE = BASE_DIR / "scheduled_events.json"
LOCAL_SPONSORS_FILE = BASE_DIR / "sponsors.json"
LOCAL_AFFILIATES_FILE = BASE_DIR / "affiliates.json"
LOCAL_WEB_USERS_FILE = BASE_DIR / "web_users.json"

def _load_json_file(file_path: Path, default_data: Any) -> Any:
    if file_path.exists():
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Database] Error reading {file_path}: {e}")
    return default_data

def _save_json_file(file_path: Path, data: Any):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[Database] Error writing {file_path}: {e}")

# =========================================================================
# GUILD CONFIGURATION QUERIES
# =========================================================================
def get_guild_config(guild_id: str) -> Dict[str, Any]:
    """Fetch guild config from Supabase with local fallback."""
    if supabase:
        try:
            res = supabase.table("GuildConfig").select("*").eq("Guild_ID", str(guild_id)).execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
                return {
                    "guild_id": str(guild_id),
                    "admin_role_id": row.get("Admin_Role_ID"),
                    "organizer_role_id": row.get("Organizer_Role_ID"),
                    "helper_role_id": row.get("Helper_Role_ID"),
                    "judge_role_id": row.get("Judge_Role_ID"),
                    "recorder_role_id": row.get("Recorder_Role_ID"),
                    "staff_role_id": row.get("Staff_Role_ID"),
                    "players_role_id": row.get("Players_Role_ID"),
                    "organization_name": row.get("organization_name") or "Tournament Organization",
                    "tournament_system_name": row.get("tournament_system_name") or "Tournament Bot",
                    "player_info_link": row.get("player_info_link") or "",
                    "player_info_format": row.get("player_info_format") or "5 vs 5",
                    "server_logo_path": row.get("server_logo_path") or ""
                }
        except Exception as e:
            print(f"[Database] Supabase get_guild_config error: {e}")

    # Fallback to local guild_configs.json
    local_data = _load_json_file(LOCAL_GUILD_CONFIGS_FILE, {})
    g_data = local_data.get(str(guild_id), {})
    role_ids = g_data.get("role_ids", {})
    return {
        "guild_id": str(guild_id),
        "admin_role_id": str(role_ids.get("head_organizer")) if role_ids.get("head_organizer") else None,
        "organizer_role_id": str(role_ids.get("organizer")) if role_ids.get("organizer") else None,
        "helper_role_id": str(role_ids.get("helper_team")) if role_ids.get("helper_team") else None,
        "judge_role_id": str(role_ids.get("judge")) if role_ids.get("judge") else None,
        "recorder_role_id": str(role_ids.get("recorder")) if role_ids.get("recorder") else None,
        "staff_role_id": str(role_ids.get("staff")) if role_ids.get("staff") else None,
        "players_role_id": str(role_ids.get("players")) if role_ids.get("players") else None,
        "organization_name": g_data.get("organization_name", "Tournament Organization"),
        "tournament_system_name": g_data.get("tournament_system_name", "Tournament Bot"),
        "player_info_link": g_data.get("player_info_link", ""),
        "player_info_format": g_data.get("player_info_format", "5 vs 5"),
        "server_logo_path": g_data.get("server_logo_path", "")
    }

def get_full_guild_config(guild_id: str) -> Dict[str, Any]:
    """Fetch complete guild configuration including channels, roles, and settings."""
    gid = str(guild_id)
    local_data = _load_json_file(LOCAL_GUILD_CONFIGS_FILE, {})
    g_data = local_data.get(gid, {})
    
    # Defaults
    channels = g_data.get("channel_ids", {})
    roles = g_data.get("role_ids", {})
    
    config = {
        "guild_id": gid,
        "organization_name": g_data.get("organization_name", "Tournament Server"),
        "tournament_system_name": g_data.get("tournament_system_name", "Tournament Bot"),
        "google_sheet_link": g_data.get("google_sheet_link", ""),
        "current_tournament_name": g_data.get("current_tournament_name", ""),
        "player_info_link": g_data.get("player_info_link", ""),
        "player_info_format": g_data.get("player_info_format", "5 vs 5"),
        "server_logo_path": g_data.get("server_logo_path", "tournament_bot_logo.png"),
        "channel_ids": {
            "rules": channels.get("rules"),
            "bracket": channels.get("bracket"),
            "deadlines": channels.get("deadlines"),
            "staff_attendance": channels.get("staff_attendance"),
            "take_schedule": channels.get("take_schedule"),
            "results": channels.get("results"),
            "category_1": channels.get("category_1"),
            "category_2": channels.get("category_2"),
            "closed_tickets_category": channels.get("closed_tickets_category"),
            "challonge_logs": channels.get("challonge_logs"),
            "transcript_logs": channels.get("transcript_logs"),
            "bot_logs": channels.get("bot_logs"),
            "thumbnail": channels.get("thumbnail")
        },
        "role_ids": {
            "head_organizer": roles.get("head_organizer"),
            "organizer": roles.get("organizer"),
            "helper_team": roles.get("helper_team"),
            "judge": roles.get("judge"),
            "recorder": roles.get("recorder"),
            "staff": roles.get("staff"),
            "players": roles.get("players")
        }
    }
    
    # Overlay with Supabase if present
    if supabase:
        try:
            res = supabase.table("GuildConfig").select("*").eq("Guild_ID", gid).execute()
            if res.data and len(res.data) > 0:
                row = res.data[0]
                if row.get("organization_name"): config["organization_name"] = row.get("organization_name")
                if row.get("tournament_system_name"): config["tournament_system_name"] = row.get("tournament_system_name")
                if row.get("Admin_Role_ID"): config["role_ids"]["head_organizer"] = row.get("Admin_Role_ID")
                if row.get("Organizer_Role_ID"): config["role_ids"]["organizer"] = row.get("Organizer_Role_ID")
                if row.get("Helper_Role_ID"): config["role_ids"]["helper_team"] = row.get("Helper_Role_ID")
                if row.get("Judge_Role_ID"): config["role_ids"]["judge"] = row.get("Judge_Role_ID")
                if row.get("Recorder_Role_ID"): config["role_ids"]["recorder"] = row.get("Recorder_Role_ID")
                if row.get("Staff_Role_ID"): config["role_ids"]["staff"] = row.get("Staff_Role_ID")
                if row.get("Players_Role_ID"): config["role_ids"]["players"] = row.get("Players_Role_ID")
                if row.get("Results_Channel_ID"): config["channel_ids"]["results"] = row.get("Results_Channel_ID")
                if row.get("Schedule_Channel_ID"): config["channel_ids"]["take_schedule"] = row.get("Schedule_Channel_ID")
                if row.get("Closed_Category_ID"): config["channel_ids"]["closed_tickets_category"] = row.get("Closed_Category_ID")
                if row.get("Bot_Logs_Channel_ID"): config["channel_ids"]["bot_logs"] = row.get("Bot_Logs_Channel_ID")
                if row.get("Challonge_Logs_Channel_ID"): config["channel_ids"]["challonge_logs"] = row.get("Challonge_Logs_Channel_ID")
        except Exception as e:
            print(f"[Database] Supabase get_full_guild_config error: {e}")
            
    return config

def save_full_guild_config(guild_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Save updated channels, roles, and settings for a guild."""
    gid = str(guild_id)
    local_data = _load_json_file(LOCAL_GUILD_CONFIGS_FILE, {})
    if gid not in local_data:
        local_data[gid] = {}
        
    g_data = local_data[gid]
    
    # Update settings
    if "organization_name" in payload: g_data["organization_name"] = payload["organization_name"]
    if "tournament_system_name" in payload: g_data["tournament_system_name"] = payload["tournament_system_name"]
    if "google_sheet_link" in payload: g_data["google_sheet_link"] = payload["google_sheet_link"]
    if "current_tournament_name" in payload: g_data["current_tournament_name"] = payload["current_tournament_name"]
    if "player_info_link" in payload: g_data["player_info_link"] = payload["player_info_link"]
    if "player_info_format" in payload: g_data["player_info_format"] = payload["player_info_format"]
    
    # Update channels
    if "channel_ids" in payload and isinstance(payload["channel_ids"], dict):
        if "channel_ids" not in g_data: g_data["channel_ids"] = {}
        for k, v in payload["channel_ids"].items():
            g_data["channel_ids"][k] = int(v) if v and str(v).isdigit() else None
            
    # Update roles
    if "role_ids" in payload and isinstance(payload["role_ids"], dict):
        if "role_ids" not in g_data: g_data["role_ids"] = {}
        for k, v in payload["role_ids"].items():
            g_data["role_ids"][k] = int(v) if v and str(v).isdigit() else None
            
    local_data[gid] = g_data
    _save_json_file(LOCAL_GUILD_CONFIGS_FILE, local_data)
    
    # Sync to Supabase if available
    if supabase:
        try:
            roles = g_data.get("role_ids", {})
            channels = g_data.get("channel_ids", {})
            sb_record = {
                "Guild_ID": gid,
                "organization_name": g_data.get("organization_name"),
                "tournament_system_name": g_data.get("tournament_system_name"),
                "Admin_Role_ID": roles.get("head_organizer"),
                "Organizer_Role_ID": roles.get("organizer"),
                "Helper_Role_ID": roles.get("helper_team"),
                "Judge_Role_ID": roles.get("judge"),
                "Recorder_Role_ID": roles.get("recorder"),
                "Staff_Role_ID": roles.get("staff"),
                "Players_Role_ID": roles.get("players"),
                "Results_Channel_ID": channels.get("results"),
                "Schedule_Channel_ID": channels.get("take_schedule"),
                "Closed_Category_ID": channels.get("closed_tickets_category"),
                "Bot_Logs_Channel_ID": channels.get("bot_logs"),
                "Challonge_Logs_Channel_ID": channels.get("challonge_logs"),
                "google_sheet_link": g_data.get("google_sheet_link"),
                "player_info_link": g_data.get("player_info_link"),
                "player_info_format": g_data.get("player_info_format"),
                "Updated_At": datetime.datetime.utcnow().isoformat()
            }
            supabase.table("GuildConfig").upsert(sb_record, on_conflict="Guild_ID").execute()
        except Exception as e:
            print(f"[Database] Supabase save_full_guild_config error: {e}")
            
    return g_data

def create_tournament_record(tournament_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update tournament and bracket structure."""
    t_id = tournament_data.get("Tournament_ID") or tournament_data.get("id") or str(uuid.uuid4())[:8]
    guild_id = str(tournament_data.get("Guild_ID") or tournament_data.get("guild_id") or "1303670721796640799")
    
    t_record = {
        "Tournament_ID": t_id,
        "Tournament_Name": tournament_data.get("Tournament_Name") or tournament_data.get("name", "Tournament"),
        "Guild_ID": guild_id,
        "game_category": tournament_data.get("game_category", "General"),
        "bracket_type": tournament_data.get("bracket_type", "single_elimination"),
        "format": tournament_data.get("format", "5 vs 5"),
        "state": tournament_data.get("state", "underway"),
        "challonge_bracket_link": tournament_data.get("challonge_bracket_link", ""),
        "participants": tournament_data.get("participants", []),
        "bracket_tree": tournament_data.get("bracket_tree", {}),
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    
    # Save local strictly inside guild container
    local_data = _load_json_file(LOCAL_TOURNAMENTS_FILE, {})
    if guild_id not in local_data or not isinstance(local_data[guild_id], dict):
        local_data[guild_id] = {}
    local_data[guild_id][t_id] = t_record

    # Clean up any stray top-level keys
    if t_id in local_data and not isinstance(local_data[t_id], dict):
        del local_data[t_id]

    _save_json_file(LOCAL_TOURNAMENTS_FILE, local_data)
    
    # Save Supabase
    if supabase:
        try:
            sb_data = {
                "Tournament_ID": t_id,
                "Tournament_Name": t_record["Tournament_Name"],
                "Guild_ID": guild_id,
                "State": t_record["state"],
                "challonge_bracket_link": t_record["challonge_bracket_link"]
            }
            supabase.table("Tournaments").upsert(sb_data, on_conflict="Tournament_ID").execute()
        except Exception as e:
            print(f"[Database] Supabase create_tournament error: {e}")
            
    return t_record

import requests
from web_server.config import (
    SUPABASE_URL, SUPABASE_KEY, BASE_DIR,
    DISCORD_BOT_TOKEN, DISCORD_API_BASE
)

# Discord Guild Name Cache
GUILD_NAME_CACHE = {}

def fetch_discord_guild_name(guild_id: str) -> Optional[str]:
    """Fetch real Discord guild name using Bot Token."""
    gid = str(guild_id)
    if gid in GUILD_NAME_CACHE:
        return GUILD_NAME_CACHE[gid]
    if DISCORD_BOT_TOKEN:
        try:
            headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
            res = requests.get(f"{DISCORD_API_BASE}/guilds/{gid}", headers=headers, timeout=4)
            if res.status_code == 200:
                name = res.json().get("name")
                if name:
                    GUILD_NAME_CACHE[gid] = name
                    return name
        except Exception as e:
            print(f"[Discord API] Fetch guild name error: {e}")
    return None

def get_all_guilds() -> List[Dict[str, Any]]:
    """Get list of all configured guilds with resolved server names."""
    guilds_dict = {}
    
    # 1. Load local configs
    local_data = _load_json_file(LOCAL_GUILD_CONFIGS_FILE, {})
    for gid, data in local_data.items():
        gid_str = str(gid)
        discord_name = fetch_discord_guild_name(gid_str)
        org_name = discord_name or data.get("organization_name") or "Tournament Server"
        guilds_dict[gid_str] = {
            "guild_id": gid_str,
            "organization_name": org_name,
            "tournament_system_name": data.get("tournament_system_name", "Tournament Bot")
        }

    # 2. Overlay with Supabase
    if supabase:
        try:
            res = supabase.table("GuildConfig").select("*").execute()
            if res.data:
                for row in res.data:
                    gid_str = str(row.get("Guild_ID"))
                    discord_name = fetch_discord_guild_name(gid_str)
                    org_name = discord_name or row.get("organization_name") or "Tournament Server"
                    guilds_dict[gid_str] = {
                        "guild_id": gid_str,
                        "organization_name": org_name,
                        "tournament_system_name": row.get("tournament_system_name") or "Tournament Bot"
                    }
        except Exception as e:
            print(f"[Database] Supabase get_all_guilds error: {e}")

    return list(guilds_dict.values())

# =========================================================================
# TOURNAMENT & EVENTS QUERIES
# =========================================================================
def get_tournaments(guild_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch active tournaments without duplicates."""
    results = []
    seen_ids = set()

    local_data = _load_json_file(LOCAL_TOURNAMENTS_FILE, {})
    for k, data in local_data.items():
        if isinstance(data, dict):
            # Check if this is a guild dictionary {tournament_id: {...}}
            is_guild_bucket = any(isinstance(v, dict) and ("name" in v or "Tournament_Name" in v or "Tournament_ID" in v or "id" in v) for v in data.values())
            if is_guild_bucket:
                if not guild_id or str(k) == str(guild_id):
                    for sub_id, sub_data in data.items():
                        if isinstance(sub_data, dict):
                            tid = str(sub_data.get("Tournament_ID") or sub_data.get("id") or sub_id)
                            if tid not in seen_ids:
                                seen_ids.add(tid)
                                item = sub_data.copy()
                                item["Tournament_ID"] = tid
                                item["Tournament_Name"] = sub_data.get("Tournament_Name") or sub_data.get("name", tid)
                                item["Guild_ID"] = str(k)
                                results.append(item)
            else:
                # Direct top-level tournament
                tid = str(data.get("Tournament_ID") or data.get("id") or k)
                if tid not in seen_ids:
                    t_gid = str(data.get("Guild_ID") or data.get("guild_id") or "")
                    if not guild_id or t_gid == str(guild_id):
                        seen_ids.add(tid)
                        item = data.copy()
                        item["Tournament_ID"] = tid
                        item["Tournament_Name"] = data.get("Tournament_Name") or data.get("name", tid)
                        results.append(item)
    return results

def get_tournament_by_id(tournament_id: str) -> Optional[Dict[str, Any]]:
    """Fetch single tournament by Tournament_ID."""
    tid_str = str(tournament_id)
    local_data = _load_json_file(LOCAL_TOURNAMENTS_FILE, {})
    
    # 1. Search inside guild buckets
    for gid, sub_data in local_data.items():
        if isinstance(sub_data, dict) and tid_str in sub_data and isinstance(sub_data[tid_str], dict):
            item = sub_data[tid_str].copy()
            item["Tournament_ID"] = tid_str
            item["Tournament_Name"] = item.get("Tournament_Name") or item.get("name", tid_str)
            item["Guild_ID"] = gid
            return item
            
    # 2. Search top level
    if tid_str in local_data and isinstance(local_data[tid_str], dict):
        item = local_data[tid_str].copy()
        item["Tournament_ID"] = tid_str
        item["Tournament_Name"] = item.get("Tournament_Name") or item.get("name", tid_str)
        return item

    return None

def update_tournament_record(tournament_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update tournament information, bracket tree, scores, and status."""
    tid = str(tournament_id)
    local_data = _load_json_file(LOCAL_TOURNAMENTS_FILE, {})
    updated_item = None
    found_guild = None

    # Search in guild buckets
    for gid, sub_data in local_data.items():
        if isinstance(sub_data, dict) and tid in sub_data and isinstance(sub_data[tid], dict):
            sub_data[tid].update(update_data)
            # Sync key aliases
            if "Tournament_Name" in update_data:
                sub_data[tid]["name"] = update_data["Tournament_Name"]
            if "name" in update_data:
                sub_data[tid]["Tournament_Name"] = update_data["name"]
            if "State" in update_data:
                sub_data[tid]["state"] = update_data["State"].lower()
            if "state" in update_data:
                sub_data[tid]["State"] = update_data["state"].upper()
                
            updated_item = sub_data[tid]
            found_guild = gid
            break
        
    if not updated_item:
        default_gid = str(update_data.get("Guild_ID") or "1303670721796640799")
        if default_gid not in local_data or not isinstance(local_data[default_gid], dict):
            local_data[default_gid] = {}
        update_data["Tournament_ID"] = tid
        update_data["Guild_ID"] = default_gid
        local_data[default_gid][tid] = update_data
        updated_item = update_data
        found_guild = default_gid

    _save_json_file(LOCAL_TOURNAMENTS_FILE, local_data)

    if supabase:
        try:
            sb_update = {
                "Tournament_ID": tid,
                "Tournament_Name": updated_item.get("Tournament_Name") or updated_item.get("name"),
                "State": updated_item.get("state") or updated_item.get("State", "underway"),
                "challonge_bracket_link": updated_item.get("challonge_bracket_link", "")
            }
            if found_guild:
                sb_update["Guild_ID"] = str(found_guild)
            supabase.table("Tournaments").upsert(sb_update, on_conflict="Tournament_ID").execute()
        except Exception as e:
            print(f"[Database] Supabase update_tournament error: {e}")

    return updated_item

def delete_tournament_record(tournament_id: str) -> bool:
    """Delete tournament record completely from all locations."""
    tid = str(tournament_id)
    local_data = _load_json_file(LOCAL_TOURNAMENTS_FILE, {})
    deleted = False

    # 1. Delete from top level if exists
    if tid in local_data:
        del local_data[tid]
        deleted = True

    # 2. Delete from guild containers
    for gid, sub_data in list(local_data.items()):
        if isinstance(sub_data, dict) and tid in sub_data:
            del sub_data[tid]
            deleted = True

    _save_json_file(LOCAL_TOURNAMENTS_FILE, local_data)

    if supabase:
        try:
            supabase.table("Tournaments").delete().eq("Tournament_ID", tid).execute()
            deleted = True
        except Exception as e:
            print(f"[Database] Supabase delete_tournament error: {e}")

    return deleted

def get_events(tournament_name: Optional[str] = None, guild_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch match events."""
    if supabase:
        try:
            query = supabase.table("Events").select("*").order("Timestamp", desc=True)
            if guild_id:
                query = query.eq("Guild_ID", str(guild_id))
            if tournament_name:
                query = query.eq("Tournament", str(tournament_name))
            res = query.limit(50).execute()
            if res.data:
                return res.data
        except Exception as e:
            print(f"[Database] Supabase get_events error: {e}")

    local_data = _load_json_file(LOCAL_EVENTS_FILE, {})
    events_list = []
    for eid, edata in local_data.items():
        if (not guild_id or str(edata.get("guild_id")) == str(guild_id)) and \
           (not tournament_name or edata.get("tournament") == tournament_name):
            item = edata.copy()
            item["Event_ID"] = eid
            events_list.append(item)
    return events_list

# =========================================================================
# SPONSORS MANAGEMENT (MONETIZATION)
# =========================================================================
def get_sponsors(guild_id: Optional[str] = None, tournament_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get active sponsors for a guild/tournament with fallback to platform sponsors."""
    if supabase:
        try:
            query = supabase.table("TournamentSponsors").select("*").eq("is_active", True)
            if guild_id:
                query = query.eq("guild_id", str(guild_id))
            res = query.execute()
            if res.data:
                return res.data
        except Exception as e:
            print(f"[Database] Supabase get_sponsors error: {e}")

    # Fallback to local sponsors file
    local_sponsors = _load_json_file(LOCAL_SPONSORS_FILE, [
        {
            "id": "sponsor-hyperx-demo",
            "guild_id": guild_id or "global",
            "tournament_id": tournament_id,
            "sponsor_name": "HyperX Gaming Gear",
            "banner_image_url": "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=1200&auto=format&fit=crop&q=80",
            "target_url": "https://hyperx.com",
            "slot_position": "top_banner",
            "impressions_count": 1420,
            "clicks_count": 89,
            "is_active": True
        },
        {
            "id": "sponsor-redbull-demo",
            "guild_id": guild_id or "global",
            "tournament_id": tournament_id,
            "sponsor_name": "Red Bull Esports",
            "banner_image_url": "https://images.unsplash.com/photo-1511512578047-dfb367046420?w=1200&auto=format&fit=crop&q=80",
            "target_url": "https://redbull.com/esports",
            "slot_position": "stage_sponsor",
            "impressions_count": 980,
            "clicks_count": 64,
            "is_active": True
        }
    ])
    return local_sponsors

def add_or_update_sponsor(sponsor_data: Dict[str, Any]) -> Dict[str, Any]:
    """Add or update a sponsor banner."""
    if "id" not in sponsor_data or not sponsor_data["id"]:
        sponsor_data["id"] = str(uuid.uuid4())
    
    if supabase:
        try:
            res = supabase.table("TournamentSponsors").upsert(sponsor_data).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            print(f"[Database] Supabase add_or_update_sponsor error: {e}")

    # Local fallback
    local_sponsors = _load_json_file(LOCAL_SPONSORS_FILE, [])
    found = False
    for i, sp in enumerate(local_sponsors):
        if sp.get("id") == sponsor_data["id"]:
            local_sponsors[i] = sponsor_data
            found = True
            break
    if not found:
        local_sponsors.append(sponsor_data)
    _save_json_file(LOCAL_SPONSORS_FILE, local_sponsors)
    return sponsor_data

def log_sponsor_click(sponsor_id: str, user_ip: str = "", user_agent: str = "") -> Optional[str]:
    """Log sponsor click and return target URL."""
    target_url = None
    if supabase:
        try:
            res = supabase.table("TournamentSponsors").select("target_url, clicks_count").eq("id", sponsor_id).execute()
            if res.data and len(res.data) > 0:
                target_url = res.data[0].get("target_url")
                current_clicks = res.data[0].get("clicks_count", 0) or 0
                supabase.table("TournamentSponsors").update({"clicks_count": current_clicks + 1}).eq("id", sponsor_id).execute()
                supabase.table("SponsorClickLogs").insert({
                    "sponsor_id": sponsor_id,
                    "user_ip_hash": str(hash(user_ip)),
                    "user_agent": user_agent[:200]
                }).execute()
        except Exception as e:
            print(f"[Database] Supabase log_sponsor_click error: {e}")

    if not target_url:
        local_sponsors = _load_json_file(LOCAL_SPONSORS_FILE, [])
        for sp in local_sponsors:
            if sp.get("id") == sponsor_id:
                sp["clicks_count"] = sp.get("clicks_count", 0) + 1
                target_url = sp.get("target_url")
                _save_json_file(LOCAL_SPONSORS_FILE, local_sponsors)
                break
    return target_url or "https://discord.gg"

# =========================================================================
# AFFILIATE PRODUCTS (GAMING GEAR & CURRENCY)
# =========================================================================
def get_affiliate_products(game_category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch affiliate gaming store products."""
    if supabase:
        try:
            query = supabase.table("AffiliateProducts").select("*").eq("is_active", True)
            if game_category and game_category.lower() != "all":
                query = query.eq("game_category", game_category)
            res = query.order("display_order").execute()
            if res.data:
                return res.data
        except Exception as e:
            print(f"[Database] Supabase get_affiliate_products error: {e}")

    local_affiliates = _load_json_file(LOCAL_AFFILIATES_FILE, [
        {
            "id": "aff-1",
            "game_category": "Valorant",
            "product_name": "Razer Viper V3 Pro Wireless Mouse",
            "product_category": "mouse",
            "image_url": "https://images.unsplash.com/photo-1615663245857-ac93bb7c39e7?w=600&auto=format&fit=crop&q=80",
            "affiliate_url": "https://amazon.com?tag=tournamentpartner-20",
            "badge_text": "Used by 85% Pro Players",
            "price_display": "$159.99",
            "display_order": 1,
            "is_active": True
        },
        {
            "id": "aff-2",
            "game_category": "Valorant",
            "product_name": "Valorant Points (VP) Instant Digital Code",
            "product_category": "currency",
            "image_url": "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=600&auto=format&fit=crop&q=80",
            "affiliate_url": "https://codashop.com?partner=tournamentbot",
            "badge_text": "Instant Code Delivery",
            "price_display": "From $9.99",
            "display_order": 2,
            "is_active": True
        },
        {
            "id": "aff-3",
            "game_category": "BGMI",
            "product_name": "BGMI UC Top-Up Authorized Partner",
            "product_category": "currency",
            "image_url": "https://images.unsplash.com/photo-1542751371-adc38448a05e?w=600&auto=format&fit=crop&q=80",
            "affiliate_url": "https://unipin.com?partner=tournamentbot",
            "badge_text": "Official Partner",
            "price_display": "Instant Top-up",
            "display_order": 3,
            "is_active": True
        },
        {
            "id": "aff-4",
            "game_category": "General",
            "product_name": "SteelSeries Arctis Nova Pro Wireless Headset",
            "product_category": "headset",
            "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&auto=format&fit=crop&q=80",
            "affiliate_url": "https://amazon.com?tag=tournamentpartner-20",
            "badge_text": "Tournament Grade Audio",
            "price_display": "$349.99",
            "display_order": 4,
            "is_active": True
        }
    ])
    if game_category and game_category.lower() != "all":
        return [p for p in local_affiliates if p.get("game_category", "").lower() == game_category.lower() or p.get("game_category") == "General"]
    return local_affiliates

def add_or_update_affiliate(affiliate_data: Dict[str, Any]) -> Dict[str, Any]:
    """Save or update an affiliate product card."""
    if "id" not in affiliate_data or not affiliate_data["id"]:
        affiliate_data["id"] = str(uuid.uuid4())

    if supabase:
        try:
            res = supabase.table("AffiliateProducts").upsert(affiliate_data).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            print(f"[Database] Supabase add_or_update_affiliate error: {e}")

    local_affiliates = _load_json_file(LOCAL_AFFILIATES_FILE, [])
    found = False
    for i, af in enumerate(local_affiliates):
        if af.get("id") == affiliate_data["id"]:
            local_affiliates[i] = affiliate_data
            found = True
            break
    if not found:
        local_affiliates.append(affiliate_data)
    _save_json_file(LOCAL_AFFILIATES_FILE, local_affiliates)
    return affiliate_data

# =========================================================================
# WEB MASTER USERS (SUPER ADMIN & PASSWORDS)
# =========================================================================
def get_web_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    """Find user record by username."""
    if supabase:
        try:
            res = supabase.table("WebUsers").select("*").eq("username", username).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
        except Exception as e:
            print(f"[Database] Supabase get_web_user error: {e}")

    local_users = _load_json_file(LOCAL_WEB_USERS_FILE, {})
    return local_users.get(username)

def save_web_user(username: str, password_hash: str, role: str = "super_admin", discord_id: Optional[str] = None):
    """Save or update web user."""
    user_record = {
        "id": str(uuid.uuid4()),
        "username": username,
        "password_hash": password_hash,
        "role": role,
        "discord_id": discord_id,
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    if supabase:
        try:
            supabase.table("WebUsers").upsert(user_record, on_conflict="username").execute()
        except Exception as e:
            print(f"[Database] Supabase save_web_user error: {e}")

    local_users = _load_json_file(LOCAL_WEB_USERS_FILE, {})
    local_users[username] = user_record
    _save_json_file(LOCAL_WEB_USERS_FILE, local_users)
