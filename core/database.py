import os
import io
import re
import csv
import json
import time
import asyncio
import datetime
from typing import Optional, Union, Any
import pytz
import discord
import requests
from supabase import create_client, Client

from core.config import (
    BASE_DIR, SUPABASE_URL, SUPABASE_KEY, DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS
)
from core.state import (
    current_guild_id, get_default_config, get_default_tournament_data,
    GUILD_CONFIG_CACHE, RULES_CACHE, STAFF_STATS_CACHE, TOURNAMENTS_CACHE,
    scheduled_events, scheduled_deadlines
)

# Supabase Client Initialization
supabase_client: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase client initialized successfully.")
    except Exception as e:
        print(f"Supabase client initialization failed: {e}")
else:
    print("Supabase URL or Key not found in environment. Supabase logging is disabled.")

def supabase_safe_upsert(table_name: str, payload: dict, on_conflict: Optional[str] = None) -> bool:
    """
    Safely upserts a row into Supabase. If any columns do not exist in the remote table,
    it dynamically detects the missing column from the error message, prunes it, and retries.
    """
    if not supabase_client:
        return False
        
    row = payload.copy()
    for attempt in range(5):
        try:
            query = supabase_client.table(table_name)
            if on_conflict:
                query.upsert(row, on_conflict=on_conflict).execute()
            else:
                query.upsert(row).execute()
            return True
        except Exception as e:
            err_msg = str(e)
            col_match = re.search(r'column ["\']?([a-zA-Z0-9_]+)["\']? of relation', err_msg, re.IGNORECASE)
            if not col_match:
                col_match = re.search(r'Could not find the [\'"]([a-zA-Z0-9_]+)[\'"] column of [\'"]([a-zA-Z0-9_]+)[\'"]', err_msg, re.IGNORECASE)
            if not col_match:
                col_match = re.search(r'column ["\']?([a-zA-Z0-9_]+)["\']? does not exist', err_msg, re.IGNORECASE)

            if col_match:
                bad_col = col_match.group(1)
                if bad_col in row:
                    del row[bad_col]
                    continue
                matched_key = next((k for k in row.keys() if k.lower() == bad_col.lower()), None)
                if matched_key:
                    del row[matched_key]
                    continue

            # Foreign key constraint violation (e.g. Key (Team1_ID)=(...) is not present in table "Teams")
            fk_key_match = re.search(r'Key \((\w+)\)=\([^)]+\) is not present in table', err_msg, re.IGNORECASE)
            if not fk_key_match:
                fk_key_match = re.search(r'violates foreign key constraint ["\']?[a-zA-Z0-9_]*_?(\w+)_fkey["\']?', err_msg, re.IGNORECASE)
            if fk_key_match:
                fk_col = fk_key_match.group(1)
                matched_key = next((k for k in row.keys() if k.lower() == fk_col.lower()), None)
                if matched_key and row.get(matched_key) is not None:
                    print(f"[Supabase] Foreign key {matched_key} not present in parent table for '{table_name}'. Setting to None and retrying...")
                    row[matched_key] = None
                    continue

            # Unique / exclusion constraint mismatch (42P10)
            if "no unique or exclusion constraint matching the ON CONFLICT" in err_msg or "42P10" in err_msg:
                if on_conflict and "," in on_conflict:
                    fallback_conflict = on_conflict.split(",")[-1].strip()
                    print(f"[Supabase] Composite unique constraint '{on_conflict}' not found on '{table_name}'. Falling back to on_conflict='{fallback_conflict}'...")
                    on_conflict = fallback_conflict
                    continue
                elif on_conflict:
                    print(f"[Supabase] No unique constraint on '{table_name}' for '{on_conflict}'. Retrying without on_conflict...")
                    on_conflict = None
                    continue

            # Duplicate key violation (23505) - record already exists
            if "duplicate key value violates unique constraint" in err_msg or "23505" in err_msg:
                print(f"[Supabase] Note on '{table_name}': Record already exists or unique constraint satisfied. Continuing.")
                return True

            # Relation error (e.g. table not found)
            if "does not exist" in err_msg and "relation" in err_msg:
                print(f"[Supabase] Table '{table_name}' does not exist or access denied: {e}")
                return False

            print(f"[Supabase] Upsert error on '{table_name}': {e}")
            if attempt < 2:
                time.sleep(0.3)
            else:
                return False
    return False

# ===========================================================================================
# GUILD CONFIGURATION
# ===========================================================================================

def load_guild_config(guild_id: int) -> dict:
    guild_id_str = str(guild_id)
    if guild_id_str in GUILD_CONFIG_CACHE:
        return GUILD_CONFIG_CACHE[guild_id_str]
        
    config = get_default_config()
    
    # 1. Load from local json first
    if os.path.exists('guild_configs.json'):
        try:
            with open('guild_configs.json', 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
                if guild_id_str in all_configs:
                    db_data = all_configs[guild_id_str]
                    for k, v in db_data.items():
                        if isinstance(v, dict) and k in config:
                            config[k].update(v)
                        else:
                            config[k] = v
        except Exception as e:
            print(f"Error loading guild_configs.json: {e}")
            
    # 2. Overlay with Supabase
    if supabase_client:
        try:
            resp = supabase_client.table("GuildConfig").select("*").eq("Guild_ID", guild_id_str).execute()
            if resp.data and len(resp.data) > 0:
                db_data = resp.data[0]
                
                role_mappings = [
                    ('head_organizer', 'Admin_Role_ID'),
                    ('organizer', 'Organizer_Role_ID'),
                    ('helper_team', 'Helper_Role_ID'),
                    ('judge', 'Judge_Role_ID'),
                    ('recorder', 'Recorder_Role_ID'),
                    ('staff', 'Staff_Role_ID'),
                    ('players', 'Players_Role_ID'),
                    ('verification', 'Verification_Role_ID'),
                    ('challonge_role', 'Challonge_Role_ID'),
                ]
                for dict_key, col_name in role_mappings:
                    db_val = db_data.get(col_name)
                    if db_val not in (None, "", "None"):
                        try:
                            config['role_ids'][dict_key] = int(db_val)
                        except:
                            pass
                            
                channel_mappings = [
                    ('challonge_logs', 'Challonge_Logs_Channel_ID'),
                    ('transcript_logs', 'Transcript_Logs_Channel_ID'),
                    ('closed_tickets_category', 'Closed_Category_ID'),
                    ('take_schedule', 'Schedule_Channel_ID'),
                    ('results', 'Results_Channel_ID'),
                    ('bracket', 'channel_bracket'),
                    ('bot_logs', 'Bot_Logs_Channel_ID'),
                    ('thumbnail', 'Thumbnail_Channel_ID'),
                    ('staff_chat', 'Staff_Chat_Channel_ID'),
                ]
                for dict_key, col_name in channel_mappings:
                    db_val = db_data.get(col_name)
                    if db_val not in (None, "", "None"):
                        try:
                            config['channel_ids'][dict_key] = int(db_val)
                        except:
                            pass
                            
                for key in ['organization_name', 'tournament_system_name', 'google_sheet_link', 'player_info_link', 'player_info_format', 'server_logo_path', 'server_logo_url']:
                    db_val = db_data.get(key)
                    if db_val in (None, "", "None"):
                        title_key = "_".join(w.capitalize() for w in key.split("_"))
                        pascal_key = "".join(w.capitalize() for w in key.split("_"))
                        db_val = db_data.get(title_key) or db_data.get(pascal_key)
                    if db_val not in (None, "", "None"):
                        config[key] = db_val
                        
        except Exception as e:
            print(f"Error merging config from Supabase: {e}")
            
    GUILD_CONFIG_CACHE[guild_id_str] = config
    return config

def save_guild_config(guild_id: int, config: dict):
    guild_id_str = str(guild_id)
    GUILD_CONFIG_CACHE[guild_id_str] = config
    
    all_configs = {}
    if os.path.exists('guild_configs.json'):
        try:
            with open('guild_configs.json', 'r', encoding='utf-8') as f:
                all_configs = json.load(f)
        except Exception as e:
            print(f"Error loading guild_configs.json for save: {e}")
            
    all_configs[guild_id_str] = config
    try:
        with open('guild_configs.json', 'w', encoding='utf-8') as f:
            json.dump(all_configs, f, indent=4)
    except Exception as e:
        print(f"Error saving config to guild_configs.json: {e}")
            
    try:
        if supabase_client:
            loop = asyncio.get_running_loop()
            loop.create_task(save_guild_config_to_supabase(guild_id, config))
    except RuntimeError:
        pass

def get_guild_config(context=None) -> dict:
    if context is None:
        g_id = current_guild_id.get()
        if g_id:
            return load_guild_config(g_id)
        return get_default_config()
        
    guild_id = None
    if isinstance(context, (int, str)):
        try:
            guild_id = int(context)
        except:
            pass
    elif isinstance(context, discord.Guild):
        guild_id = context.id
    elif hasattr(context, "guild") and context.guild:
        guild_id = context.guild.id
    elif isinstance(context, (discord.TextChannel, discord.CategoryChannel, discord.VoiceChannel)):
        guild_id = context.guild.id
    elif isinstance(context, (discord.Member, discord.User)):
        if hasattr(context, "guild") and context.guild:
            guild_id = context.guild.id
    elif isinstance(context, discord.Message) and context.guild:
        guild_id = context.guild.id
        
    if not guild_id:
        g_id = current_guild_id.get()
        if g_id:
            guild_id = g_id
            
    if not guild_id:
        return get_default_config()
        
    return load_guild_config(guild_id)

def _sync_save_guild_config_to_supabase(guild_id: int, cfg: dict):
    if not supabase_client:
        return False
    roles = cfg.get('role_ids', {})
    channels = cfg.get('channel_ids', {})
    org_name = str(cfg.get('organization_name', '') or '')
    sys_name = str(cfg.get('tournament_system_name', '') or '')
    logo_path = str(cfg.get('server_logo_path', '') or '')
    logo_url = str(cfg.get('server_logo_url', '') or '')
    updated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    row = {
        "Guild_ID": str(guild_id),
        "Admin_Role_ID": str(roles.get('head_organizer') or ""),
        "Organizer_Role_ID": str(roles.get('organizer') or ""),
        "Helper_Role_ID": str(roles.get('helper_team') or ""),
        "Judge_Role_ID": str(roles.get('judge') or ""),
        "Recorder_Role_ID": str(roles.get('recorder') or ""),
        "Staff_Role_ID": str(roles.get('staff') or ""),
        "Players_Role_ID": str(roles.get('players') or ""),
        "Verification_Role_ID": str(roles.get('verification') or ""),
        "Challonge_Role_ID": str(roles.get('challonge_role') or ""),
        "Organization_Name": org_name,
        "Tournament_System_Name": sys_name,
        "organization_name": org_name,
        "tournament_system_name": sys_name,
        "server_logo_path": logo_path,
        "server_logo_url": logo_url,
        "player_info_link": str(cfg.get('player_info_link', '') or ''),
        "player_info_format": str(cfg.get('player_info_format', '') or ''),
        "google_sheet_link": str(cfg.get('google_sheet_link', '') or ''),
        "Challonge_Logs_Channel_ID": str(channels.get('challonge_logs') or ""),
        "Transcript_Logs_Channel_ID": str(channels.get('transcript_logs') or ""),
        "Closed_Category_ID": str(channels.get('closed_tickets_category') or ""),
        "Schedule_Channel_ID": str(channels.get('take_schedule') or ""),
        "Results_Channel_ID": str(channels.get('results') or ""),
        "channel_bracket": str(channels.get('bracket') or ""),
        "Bot_Logs_Channel_ID": str(channels.get('bot_logs') or ""),
        "Thumbnail_Channel_ID": str(channels.get('thumbnail') or ""),
        "Staff_Chat_Channel_ID": str(channels.get('staff_chat') or ""),
        "Updated_At": updated_at
    }
    return supabase_safe_upsert("GuildConfig", row, on_conflict="Guild_ID")

async def save_guild_config_to_supabase(guild_id: int, cfg: dict):
    if supabase_client:
        await asyncio.to_thread(_sync_save_guild_config_to_supabase, guild_id, cfg)


# ===========================================================================================
# TOURNAMENTS MANAGEMENT
# ===========================================================================================

def load_guild_tournaments(guild_id: int) -> dict:
    guild_id_str = str(guild_id)
    if guild_id_str in TOURNAMENTS_CACHE:
        return TOURNAMENTS_CACHE[guild_id_str]
        
    tournaments = {}
    
    # 1. Load from tournaments.json first
    if os.path.exists('tournaments.json'):
        try:
            with open('tournaments.json', 'r', encoding='utf-8') as f:
                all_tournaments = json.load(f)
                if guild_id_str in all_tournaments:
                    tournaments = all_tournaments[guild_id_str]
        except Exception as e:
            print(f"Error loading tournaments.json: {e}")
            
    # 2. Overlay with Supabase
    if supabase_client:
        try:
            resp = supabase_client.table("Tournaments").select("*").eq("Guild_ID", guild_id_str).execute()
            if resp.data:
                for row in resp.data:
                    t_id = row.get("Tournament_ID")
                    if t_id:
                        # Clean/skip corrupted tournament IDs like "Name (id) [state]"
                        if "(" in t_id and "[" in t_id:
                            match = re.search(r'\(([^)]+)\)', t_id)
                            if match:
                                clean_extracted = match.group(1).strip()
                                if clean_extracted in tournaments:
                                    continue
                                t_id = clean_extracted
                            else:
                                continue

                        existing = tournaments.get(t_id, get_default_tournament_data())
                        existing.update({
                            "name": row.get("Tournament_Name") or existing.get("name") or "",
                            "state": row.get("State") or existing.get("state") or "pending",
                            "game": row.get("Game") or row.get("game") or existing.get("game") or "",
                            "key": row.get("Key") or existing.get("key") or "",
                            "challonge_bracket_link": row.get("challonge_bracket_link") or existing.get("challonge_bracket_link") or "",
                            "captains_sheet_link": row.get("Captains_Sheet_Link") or row.get("Sheet_Link") or existing.get("captains_sheet_link") or "",
                            "sheet_link": row.get("Captains_Sheet_Link") or row.get("Sheet_Link") or existing.get("sheet_link") or "",
                        })
                        
                        channel_keys = [
                            ("thumbnail", "Thumbnail_Channel_ID"),
                            ("attendance", "Attendance_Channel_ID"),
                            ("transcript", "Transcript_Channel_ID"),
                            ("schedule", "Schedule_Channel_ID"),
                            ("rules", "Rules_Channel_ID"),
                            ("deadline", "Deadline_Channel_ID"),
                            ("result", "Result_Channel_ID"),
                            ("challonge_logs", "Challonge_Logs_Channel_ID"),
                            ("transcript_logs", "Transcript_Logs_Channel_ID"),
                            ("bot_logs", "Bot_Logs_Channel_ID"),
                            ("participant", "Participant_Channel_ID"),
                        ]
                        for dict_key, col_name in channel_keys:
                            db_val = row.get(col_name)
                            if db_val not in (None, "", "None"):
                                try:
                                    val_int = int(db_val)
                                    existing[dict_key] = val_int
                                    existing[f"{dict_key}_channel"] = val_int
                                except:
                                    pass
                                    
                        category_keys = [
                            ("closed_ticket_1", "Closed_Ticket_Category_ID"),
                            ("closed_ticket_2", "Closed_Ticket_Category_2_ID"),
                            ("ticket_open_category_1", "Open_Category_1_ID"),
                            ("ticket_open_category_2", "Open_Category_2_ID"),
                            ("ticket_open_category_3", "Open_Category_3_ID"),
                        ]
                        for dict_key, col_name in category_keys:
                            db_val = row.get(col_name)
                            if db_val not in (None, "", "None"):
                                try:
                                    existing[dict_key] = int(db_val)
                                except:
                                    pass
                                    
                        db_val = row.get("Auto_Room_Creation")
                        if db_val not in (None, "", "None"):
                            existing["auto_room_creation"] = (str(db_val).lower() == 'true')

                        db_val = row.get("Players_Role_ID")
                        if db_val not in (None, "", "None"):
                            try:
                                existing["players_role_id"] = int(db_val)
                            except:
                                pass
                                    
                        tournaments[t_id] = existing
        except Exception as e:
            print(f"Error loading/merging tournaments from Supabase: {e}")
            
    TOURNAMENTS_CACHE[guild_id_str] = tournaments
    return tournaments

def save_guild_tournaments(guild_id: int, tournaments: dict):
    guild_id_str = str(guild_id)
    TOURNAMENTS_CACHE[guild_id_str] = tournaments
    
    all_tournaments = {}
    if os.path.exists('tournaments.json'):
        try:
            with open('tournaments.json', 'r', encoding='utf-8') as f:
                all_tournaments = json.load(f)
        except Exception as e:
            print(f"Error loading tournaments.json for save: {e}")
            
    all_tournaments[guild_id_str] = tournaments
    try:
        with open('tournaments.json', 'w', encoding='utf-8') as f:
            json.dump(all_tournaments, f, indent=4)
    except Exception as e:
        print(f"Error saving tournaments to tournaments.json: {e}")
            
    try:
        if supabase_client:
            loop = asyncio.get_running_loop()
            for t_id, t_data in tournaments.items():
                loop.create_task(save_tournament_to_supabase(guild_id, t_id, t_data))
    except RuntimeError:
        pass

def _sync_save_tournament_to_supabase(guild_id: int, tournament_id: str, t_data: dict):
    if not supabase_client:
        return False

    auto_room_val = t_data.get('auto_room_creation', False)
    if isinstance(auto_room_val, str):
        auto_room_val = auto_room_val.lower() in ('true', '1', 'yes')

    def _get_val(*keys):
        for k in keys:
            v = t_data.get(k)
            if v not in (None, "", "None"):
                return str(v).strip()
        return ""

    bracket_link = _get_val('challonge_bracket_link', 'Challonge_Bracket_Link', 'bracket')
    sheet_link = _get_val('google_sheet_link', 'Google_Sheet_Link', 'captains_sheet_link', 'Captains_Sheet_Link', 'sheet_link')
    updated_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    row = {
        "Tournament_ID": str(tournament_id),
        "Guild_ID": str(guild_id),
        "Tournament_Name": _get_val('name', 'Tournament_Name') or str(tournament_id),
        "State": _get_val('state', 'State') or "pending",
        "Game": _get_val('game', 'Game'),
        "Key": _get_val('key', 'Key'),
        "Challonge_Bracket_Link": bracket_link,
        "challonge_bracket_link": bracket_link,
        "Google_Sheet_Link": sheet_link,
        "Captains_Sheet_Link": sheet_link,
        "Sheet_Link": sheet_link,
        "Attendance_Channel_ID": _get_val('attendance', 'attendance_channel', 'Attendance_Channel_ID'),
        "Transcript_Channel_ID": _get_val('transcript', 'transcript_channel', 'Transcript_Channel_ID'),
        "Schedule_Channel_ID": _get_val('schedule', 'schedule_channel', 'schedule_channel_id', 'Schedule_Channel_ID'),
        "Rules_Channel_ID": _get_val('rules', 'rules_channel', 'Rules_Channel_ID'),
        "Result_Channel_ID": _get_val('result', 'result_channel', 'Result_Channel_ID'),
        "Deadline_Channel_ID": _get_val('deadline', 'deadline_channel', 'Deadline_Channel_ID'),
        "Bot_Logs_Channel_ID": _get_val('bot_logs', 'Bot_Logs_Channel_ID'),
        "Challonge_Logs_Channel_ID": _get_val('challonge_logs', 'Challonge_Logs_Channel_ID'),
        "Transcript_Logs_Channel_ID": _get_val('transcript_logs', 'Transcript_Logs_Channel_ID'),
        "Thumbnail_Channel_ID": _get_val('thumbnail', 'Thumbnail_Channel_ID'),
        "Participant_Channel_ID": _get_val('participant', 'Participant_Channel_ID'),
        "Closed_Ticket_Category_ID": _get_val('closed_ticket_1', 'Closed_Ticket_Category_ID'),
        "Closed_Ticket_Category_2_ID": _get_val('closed_ticket_2', 'Closed_Ticket_Category_2_ID'),
        "Open_Category_1_ID": _get_val('ticket_open_category_1', 'Open_Category_1_ID'),
        "Open_Category_2_ID": _get_val('ticket_open_category_2', 'Open_Category_2_ID'),
        "Open_Category_3_ID": _get_val('ticket_open_category_3', 'Open_Category_3_ID'),
        "Open_Category_4_ID": _get_val('ticket_open_category_4', 'Open_Category_4_ID'),
        "Auto_Room_Creation": bool(auto_room_val),
        "Players_Role_ID": _get_val('players_role_id', 'Players_Role_ID'),
        "Map_Pool": _get_val('map_pool', 'Map_Pool'),
        "Updated_At": updated_at
    }

    return supabase_safe_upsert("Tournaments", row, on_conflict="Guild_ID,Tournament_ID")

async def save_tournament_to_supabase(guild_id: int, tournament_id: str, t_data: dict):
    if supabase_client:
        await asyncio.to_thread(_sync_save_tournament_to_supabase, guild_id, tournament_id, t_data)

def _sync_delete_tournament_from_supabase(guild_id: int, tournament_id: str):
    if not supabase_client:
        return False
    try:
        supabase_client.table("Tournaments").delete().eq("Guild_ID", str(guild_id)).eq("Tournament_ID", tournament_id).execute()
        return True
    except Exception as e:
        print(f"[Supabase] Error deleting tournament {tournament_id}: {e}")
        return False

async def delete_tournament_from_supabase(guild_id: int, tournament_id: str):
    if supabase_client:
        await asyncio.to_thread(_sync_delete_tournament_from_supabase, guild_id, tournament_id)

def find_tournament_config(guild_id: int, tournament_query: Optional[str] = None) -> Optional[dict]:
    if not guild_id:
        return None
    tournaments = load_guild_tournaments(guild_id)
    if not tournaments:
        return None

    if tournament_query:
        query_raw = str(tournament_query).strip()
        query_lower = query_raw.lower()
        query_slug = re.sub(r'[^a-z0-9]', '', query_lower)

        if query_raw in tournaments:
            return tournaments[query_raw]
        if query_lower in tournaments:
            return tournaments[query_lower]

        for tid, cfg in tournaments.items():
            t_name = str(cfg.get('name') or cfg.get('Tournament_Name') or '').strip().lower()
            if str(tid).lower() == query_lower or t_name == query_lower:
                return cfg

        if query_slug:
            for tid, cfg in tournaments.items():
                tid_slug = re.sub(r'[^a-z0-9]', '', str(tid).lower())
                t_name_slug = re.sub(r'[^a-z0-9]', '', str(cfg.get('name') or cfg.get('Tournament_Name') or '').lower())
                if query_slug == tid_slug or query_slug == t_name_slug:
                    return cfg

        for tid, cfg in tournaments.items():
            t_name = str(cfg.get('name') or cfg.get('Tournament_Name') or '').strip().lower()
            if (query_lower and query_lower in str(tid).lower()) or (query_lower and query_lower in t_name) or (t_name and t_name in query_lower):
                return cfg

    active_cfg = get_active_tournament_config(guild_id)
    if active_cfg:
        return active_cfg

    if len(tournaments) == 1:
        return next(iter(tournaments.values()))

    return None

def get_active_tournament_config(guild_id: int) -> Optional[dict]:
    tournaments = load_guild_tournaments(guild_id)
    for t_id, t_cfg in tournaments.items():
        if str(t_cfg.get('state', '')).lower() in ('active', 'underway'):
            return t_cfg
    return None

def get_active_tournament_id(guild_id: int) -> Optional[str]:
    tournaments = load_guild_tournaments(guild_id)
    for t_id, t_cfg in tournaments.items():
        if str(t_cfg.get('state', '')).lower() in ('active', 'underway'):
            return t_id
    return None


# ===========================================================================================
# DISCORD CHANNEL RESOLUTION HELPERS
# ===========================================================================================

def resolve_discord_channel(guild: discord.Guild, channel_id_val: Optional[Any], bot_client: Optional[discord.Client] = None) -> Optional[discord.TextChannel]:
    if not guild or not channel_id_val:
        return None
    try:
        cid = int(channel_id_val)
        ch = guild.get_channel(cid)
        if not ch and bot_client:
            ch = bot_client.get_channel(cid)
        if ch and hasattr(ch, "send"):
            return ch
    except Exception:
        pass
    return None

async def fetch_discord_channel_safe(guild: discord.Guild, channel_id_val: Optional[Any], bot_client: Optional[discord.Client] = None) -> Optional[discord.TextChannel]:
    if not guild or not channel_id_val:
        return None
    ch = resolve_discord_channel(guild, channel_id_val, bot_client)
    if ch:
        return ch
    try:
        cid = int(channel_id_val)
        ch = await guild.fetch_channel(cid)
        if ch and hasattr(ch, "send"):
            return ch
    except Exception:
        if bot_client:
            try:
                ch = await bot_client.fetch_channel(cid)
                if ch and hasattr(ch, "send"):
                    return ch
            except Exception:
                pass
    return None

def get_tournament_schedule_channel(guild: discord.Guild, tournament_name_or_id: str = None) -> Optional[discord.TextChannel]:
    if not guild:
        return None
    t_cfg = find_tournament_config(guild.id, tournament_name_or_id)
    if t_cfg:
        ch_id = t_cfg.get('schedule') or t_cfg.get('schedule_channel') or t_cfg.get('schedule_channel_id') or t_cfg.get('Schedule_Channel_ID')
        ch = resolve_discord_channel(guild, ch_id)
        if ch:
            return ch
    cfg = get_guild_config(guild.id)
    g_sched_id = cfg.get('channel_ids', {}).get('take_schedule')
    return resolve_discord_channel(guild, g_sched_id)

def get_tournament_results_channel(guild: discord.Guild, tournament_name_or_id: str = None) -> Optional[discord.TextChannel]:
    if not guild:
        return None
    t_cfg = find_tournament_config(guild.id, tournament_name_or_id)
    if t_cfg:
        ch_id = t_cfg.get('result') or t_cfg.get('result_channel') or t_cfg.get('results_channel') or t_cfg.get('Result_Channel_ID')
        ch = resolve_discord_channel(guild, ch_id)
        if ch:
            return ch
    cfg = get_guild_config(guild.id)
    g_res_id = cfg.get('channel_ids', {}).get('results')
    return resolve_discord_channel(guild, g_res_id)

def get_tournament_attendance_channel(guild: discord.Guild, tournament_name_or_id: str = None) -> Optional[discord.TextChannel]:
    if not guild:
        return None
    t_cfg = find_tournament_config(guild.id, tournament_name_or_id)
    if t_cfg:
        ch_id = t_cfg.get('attendance') or t_cfg.get('attendance_channel') or t_cfg.get('Attendance_Channel_ID')
        ch = resolve_discord_channel(guild, ch_id)
        if ch:
            return ch
    cfg = get_guild_config(guild.id)
    g_att_id = cfg.get('channel_ids', {}).get('staff_attendance')
    return resolve_discord_channel(guild, g_att_id)

async def log_bot_activity(guild: discord.Guild, embed: discord.Embed):
    if not guild:
        return

    channel = None

    # 1. Try guild config bot_logs (Primary server-wide setting)
    cfg = get_guild_config(guild.id)
    default_logs_id = cfg.get('channel_ids', {}).get('bot_logs') or cfg.get('bot_logs')
    if default_logs_id:
        try:
            channel = guild.get_channel(int(default_logs_id)) or await guild.fetch_channel(int(default_logs_id))
        except Exception:
            pass

    # 2. Try active tournament config
    if not channel:
        t_cfg = get_active_tournament_config(guild.id)
        if t_cfg:
            for k in ['bot_logs', 'bot_logs_channel_id', 'Bot_Logs_Channel_ID']:
                if t_cfg.get(k):
                    try:
                        c_id = int(t_cfg[k])
                        channel = guild.get_channel(c_id) or await guild.fetch_channel(c_id)
                        if channel: break
                    except Exception:
                        pass

    # 3. Try any tournament configured in the guild
    if not channel:
        tournaments = load_guild_tournaments(guild.id)
        for _, tdata in tournaments.items():
            for k in ['bot_logs', 'bot_logs_channel_id', 'Bot_Logs_Channel_ID']:
                if tdata.get(k):
                    try:
                        c_id = int(tdata[k])
                        channel = guild.get_channel(c_id) or await guild.fetch_channel(c_id)
                        if channel: break
                    except Exception:
                        pass
            if channel:
                break

    # 4. Fallback search by channel name
    if not channel:
        for ch in guild.text_channels:
            if ch.name.lower() in ('bot-logs', 'bot_logs', 'bot-log', 'audit-logs', 'audit_logs', 'logs'):
                channel = ch
                break

    if channel:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to log bot activity: {e}")


# ===========================================================================================
# RULES & STAFF STATS STORAGE
# ===========================================================================================

def get_guild_rules(guild_id: int) -> dict:
    guild_id_str = str(guild_id)
    if guild_id_str in RULES_CACHE:
        return RULES_CACHE[guild_id_str]
        
    rules = {}
    if os.path.exists('tournament_rules.json'):
        try:
            with open('tournament_rules.json', 'r', encoding='utf-8') as f:
                all_rules = json.load(f)
                if guild_id_str in all_rules:
                    rules = all_rules[guild_id_str]
                elif 'rules' in all_rules and not all_rules.get(guild_id_str):
                    rules = all_rules
        except Exception as e:
            print(f"Error loading tournament_rules.json: {e}")
            
    RULES_CACHE[guild_id_str] = rules
    return rules

def save_guild_rules(guild_id: int, rules: dict):
    guild_id_str = str(guild_id)
    RULES_CACHE[guild_id_str] = rules
    
    all_rules = {}
    if os.path.exists('tournament_rules.json'):
        try:
            with open('tournament_rules.json', 'r', encoding='utf-8') as f:
                all_rules = json.load(f)
        except Exception:
            pass
    
    if 'rules' in all_rules and not any(isinstance(v, dict) and 'rules' in v for v in all_rules.values() if v):
        all_rules = {}
        
    all_rules[guild_id_str] = rules
    try:
        with open('tournament_rules.json', 'w', encoding='utf-8') as f:
            json.dump(all_rules, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving rules to tournament_rules.json: {e}")

def get_guild_staff_stats(guild_id: int) -> dict:
    guild_id_str = str(guild_id)
    if guild_id_str in STAFF_STATS_CACHE:
        stats = STAFF_STATS_CACHE[guild_id_str]
    else:
        stats = {}
        if os.path.exists('staff_stats.json'):
            try:
                with open('staff_stats.json', 'r', encoding='utf-8') as f:
                    all_stats = json.load(f)
                    if guild_id_str in all_stats:
                        stats = all_stats[guild_id_str]
                    elif all_stats and not any(isinstance(v, dict) and any(isinstance(inner, dict) for inner in v.values()) for v in all_stats.values() if v):
                        stats = all_stats
            except Exception as e:
                print(f"Error loading staff_stats.json: {e}")
                
        STAFF_STATS_CACHE[guild_id_str] = stats

    # Ensure all numerical fields are clean integers
    if isinstance(stats, dict):
        for uid, udata in list(stats.items()):
            if isinstance(udata, dict):
                udata["judge_count"] = int(udata.get("judge_count") or 0)
                udata["recorder_count"] = int(udata.get("recorder_count") or 0)
                udata["judge_and_recorder_count"] = int(udata.get("judge_and_recorder_count") or 0)
                udata["total_count"] = int(udata.get("total_count") or (udata["judge_count"] + udata["recorder_count"] + udata["judge_and_recorder_count"]))
    return stats

def save_guild_staff_stats(guild_id: int, stats: dict):
    guild_id_str = str(guild_id)
    STAFF_STATS_CACHE[guild_id_str] = stats
    
    all_stats = {}
    if os.path.exists('staff_stats.json'):
        try:
            with open('staff_stats.json', 'r', encoding='utf-8') as f:
                all_stats = json.load(f)
        except Exception:
            pass
            
    if all_stats and not any(isinstance(v, dict) and any(isinstance(inner, dict) for inner in v.values()) for v in all_stats.values() if v):
        all_stats = {}
        
    all_stats[guild_id_str] = stats
    try:
        with open('staff_stats.json', 'w', encoding='utf-8') as f:
            json.dump(all_stats, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving staff stats to staff_stats.json: {e}")

    if supabase_client:
        try:
            loop = asyncio.get_running_loop()
            for u_id, u_stats in stats.items():
                if not isinstance(u_stats, dict):
                    continue
                jr_cnt = int(u_stats.get("judge_and_recorder_count", 0))
                row = {
                    "Guild_ID": guild_id_str,
                    "User_ID": str(u_id),
                    "Name": str(u_stats.get("name") or "Staff"),
                    "Judge_Count": int(u_stats.get("judge_count", 0)),
                    "Recorder_Count": int(u_stats.get("recorder_count", 0)),
                    "Judge_and_Record": jr_cnt,
                    "Total_Count": int(u_stats.get("total_count", 0)),
                    "Timestamp": u_stats.get("last_active") or datetime.datetime.utcnow().isoformat()
                }
                loop.create_task(asyncio.to_thread(supabase_safe_upsert, "StaffStats", row, "Guild_ID,User_ID"))
        except RuntimeError:
            pass

def load_rules():
    global RULES_CACHE
    try:
        if os.path.exists('tournament_rules.json'):
            with open('tournament_rules.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data and any(isinstance(v, dict) and 'rules' in v for v in data.values() if v):
                    RULES_CACHE.update(data)
                else:
                    RULES_CACHE["legacy"] = data
    except Exception as e:
        print(f"Error loading tournament rules: {e}")

def load_staff_stats():
    global STAFF_STATS_CACHE
    try:
        if os.path.exists('staff_stats.json'):
            with open('staff_stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data and any(isinstance(v, dict) and any(isinstance(inner, dict) for inner in v.values()) for v in data.values() if v):
                    STAFF_STATS_CACHE.update(data)
                else:
                    STAFF_STATS_CACHE["legacy"] = data
        elif os.path.exists('judge_stats.json'):
            with open('judge_stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                STAFF_STATS_CACHE["legacy"] = data
    except Exception as e:
        print(f"Error loading staff stats: {e}")

def save_staff_stats():
    g_id = current_guild_id.get()
    if g_id:
        save_guild_staff_stats(g_id, get_guild_staff_stats(g_id))
        return True
    return False

def reset_staff_stats():
    g_id = current_guild_id.get()
    if g_id:
        save_guild_staff_stats(g_id, {})
        return True
    return False

def update_staff_stats(user: Any, role_type: str, guild_id: Optional[int] = None):
    g_id = guild_id or (getattr(user, 'guild', None).id if hasattr(user, 'guild') and user.guild else current_guild_id.get())
        
    if not g_id:
        return
        
    stats = get_guild_staff_stats(g_id)
    user_id = str(getattr(user, 'id', user))
    display_name = str(getattr(user, 'display_name', getattr(user, 'name', f"Staff_{user_id}")))
    
    if user_id not in stats:
        stats[user_id] = {
            "name": display_name,
            "judge_count": 0,
            "recorder_count": 0,
            "judge_and_recorder_count": 0,
            "total_count": 0
        }
    
    if role_type == "judge":
        stats[user_id]["judge_count"] = int(stats[user_id].get("judge_count", 0)) + 1
    elif role_type == "recorder":
        stats[user_id]["recorder_count"] = int(stats[user_id].get("recorder_count", 0)) + 1
    elif role_type in ("judge_and_recorder", "judge_and_recorder_count", "both"):
        stats[user_id]["judge_and_recorder_count"] = int(stats[user_id].get("judge_and_recorder_count", 0)) + 1
    elif role_type == "upgrade_to_both":
        stats[user_id]["judge_count"] = max(0, int(stats[user_id].get("judge_count", 1)) - 1)
        stats[user_id]["judge_and_recorder_count"] = int(stats[user_id].get("judge_and_recorder_count", 0)) + 1
        
    stats[user_id]["total_count"] = (
        int(stats[user_id].get("judge_count", 0)) + 
        int(stats[user_id].get("recorder_count", 0)) + 
        int(stats[user_id].get("judge_and_recorder_count", 0))
    )
    stats[user_id]["name"] = display_name
    stats[user_id]["last_active"] = datetime.datetime.utcnow().isoformat()
    
    save_guild_staff_stats(g_id, stats)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sheetdb_post("StaffStats", {
            "Guild_ID": str(g_id) if g_id else "",
            "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "User_ID": user_id,
            "Name": display_name,
            "Role_Updated": role_type,
            "Judge_Count": stats[user_id].get("judge_count", 0),
            "Recorder_Count": stats[user_id].get("recorder_count", 0),
            "Judge_and_Record": stats[user_id].get("judge_and_recorder_count", 0),
            "Total_Count": stats[user_id].get("total_count", 0)
        }))
    except RuntimeError:
        pass

def decrement_staff_stats(user: Any, role_type: str, guild_id: Optional[int] = None):
    g_id = guild_id or (getattr(user, 'guild', None).id if hasattr(user, 'guild') and user.guild else current_guild_id.get())
    if not g_id:
        return
    stats = get_guild_staff_stats(g_id)
    user_id = str(getattr(user, 'id', user))
    if user_id not in stats:
        return
    if role_type == "judge":
        stats[user_id]["judge_count"] = max(0, int(stats[user_id].get("judge_count", 0)) - 1)
    elif role_type == "recorder":
        stats[user_id]["recorder_count"] = max(0, int(stats[user_id].get("recorder_count", 0)) - 1)
    elif role_type in ("judge_and_recorder", "both"):
        stats[user_id]["judge_and_recorder_count"] = max(0, int(stats[user_id].get("judge_and_recorder_count", 0)) - 1)
    stats[user_id]["total_count"] = (
        int(stats[user_id].get("judge_count", 0)) +
        int(stats[user_id].get("recorder_count", 0)) +
        int(stats[user_id].get("judge_and_recorder_count", 0))
    )
    save_guild_staff_stats(g_id, stats)

def recalculate_guild_staff_stats(guild_id: int) -> dict:
    """
    Recalculates staff stats for a guild based on all completed matches in scheduled_events.
    """
    g_id_str = str(guild_id)
    new_stats = {}
    for ev_id, ev in scheduled_events.items():
        if ev.get('guild_id') and str(ev.get('guild_id')) != g_id_str:
            continue
        is_completed = (
            ev.get('status') == 'completed' or
            bool(ev.get('results_message_id')) or
            bool(ev.get('completed_at')) or
            'winner_score' in ev
        )
        if not is_completed:
            continue

        j_val = ev.get('result_judge') or ev.get('judge')
        r_val = ev.get('recorder')
        
        j_id = str(getattr(j_val, 'id', j_val)) if j_val else None
        r_id = str(getattr(r_val, 'id', r_val)) if r_val else None

        if j_id and r_id and j_id == r_id:
            if j_id not in new_stats:
                j_name = getattr(j_val, 'display_name', getattr(j_val, 'name', f"Staff_{j_id}"))
                new_stats[j_id] = {"name": str(j_name), "judge_count": 0, "recorder_count": 0, "judge_and_recorder_count": 0, "total_count": 0}
            new_stats[j_id]["judge_and_recorder_count"] += 1
        else:
            if j_id:
                if j_id not in new_stats:
                    j_name = getattr(j_val, 'display_name', getattr(j_val, 'name', f"Staff_{j_id}"))
                    new_stats[j_id] = {"name": str(j_name), "judge_count": 0, "recorder_count": 0, "judge_and_recorder_count": 0, "total_count": 0}
                new_stats[j_id]["judge_count"] += 1
            if r_id:
                if r_id not in new_stats:
                    r_name = getattr(r_val, 'display_name', getattr(r_val, 'name', f"Staff_{r_id}"))
                    new_stats[r_id] = {"name": str(r_name), "judge_count": 0, "recorder_count": 0, "judge_and_recorder_count": 0, "total_count": 0}
                new_stats[r_id]["recorder_count"] += 1

    for u_id, u_data in new_stats.items():
        u_data["total_count"] = u_data["judge_count"] + u_data["recorder_count"] + u_data["judge_and_recorder_count"]

    save_guild_staff_stats(guild_id, new_stats)
    return new_stats


# ===========================================================================================
# SCHEDULED EVENTS & DEADLINES PERSISTENCE
# ===========================================================================================

def load_scheduled_events():
    global scheduled_events
    path = os.path.join(BASE_DIR, 'scheduled_events.json')
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                active_events = {}
                for event_id, event_data in data.items():
                    if not isinstance(event_data, dict):
                        continue
                    # Retain recent completed events (last 7 days or has results message) for /link add and editing
                    is_completed = str(event_data.get('status', '')).lower() in ('completed', 'closed', 'finished', 'done')
                    if is_completed and not event_data.get('results_message_id'):
                        completed_at = event_data.get('completed_at')
                        if completed_at:
                            try:
                                cat = datetime.datetime.fromisoformat(completed_at)
                                if cat.tzinfo is None: cat = cat.replace(tzinfo=pytz.UTC)
                                if cat < datetime.datetime.now(pytz.UTC) - datetime.timedelta(days=7):
                                    continue
                            except Exception:
                                pass
                    if 'datetime' in event_data and isinstance(event_data['datetime'], str):
                        try:
                            parsed_dt = datetime.datetime.fromisoformat(event_data['datetime'])
                            if parsed_dt.tzinfo is None:
                                parsed_dt = parsed_dt.replace(tzinfo=pytz.UTC)
                            event_data['datetime'] = parsed_dt
                        except Exception:
                            pass
                    elif 'datetime' in event_data and isinstance(event_data['datetime'], datetime.datetime):
                        if event_data['datetime'].tzinfo is None:
                            event_data['datetime'] = event_data['datetime'].replace(tzinfo=pytz.UTC)
                    active_events[event_id] = event_data
                scheduled_events.clear()
                scheduled_events.update(active_events)
                print(f"Loaded {len(scheduled_events)} active/recent scheduled events from local file")
    except Exception as e:
        print(f"Error loading scheduled events from local file: {e}")
    return scheduled_events

async def load_scheduled_events_from_supabase():
    if not supabase_client:
        return
        
    print("⏳ Loading scheduled events from Supabase...")
    try:
        try:
            res = await asyncio.to_thread(
                lambda: supabase_client.table("Matches").select("*").execute()
            )
        except Exception:
            res = await asyncio.to_thread(
                lambda: supabase_client.table("Events").select("*").execute()
            )
        if res and res.data:
            loaded_count = 0
            for row in res.data:
                row_status = str(row.get("State") or row.get("Status") or "").lower()
                is_completed = row_status in ("completed", "closed", "finished", "done")

                event_id = row.get("Match_ID") or row.get("Event_ID")
                if not event_id:
                    continue
                    
                date_str = row.get("Date") or ""
                utc_time_str = row.get("UTC_Time") or ""
                event_datetime = None
                has_remote_time = False
                
                if row.get("Scheduled_Time"):
                    try:
                        clean_time = str(row["Scheduled_Time"]).replace('Z', '+00:00')
                        event_datetime = datetime.datetime.fromisoformat(clean_time)
                        if event_datetime.tzinfo is None:
                            event_datetime = event_datetime.replace(tzinfo=pytz.UTC)
                        utc_time_str = event_datetime.strftime("%H:%M UTC")
                        date_str = event_datetime.strftime("%d/%m")
                        has_remote_time = True
                    except Exception:
                        pass
                        
                if not event_datetime and date_str and utc_time_str:
                    try:
                        day, month = map(int, date_str.split('/'))
                        time_part = utc_time_str.split(' ')[0]
                        hour, minute = map(int, time_part.split(':'))
                        current_year = datetime.datetime.now().year
                        event_datetime = datetime.datetime(current_year, month, day, hour, minute, tzinfo=pytz.UTC)
                        has_remote_time = True
                    except Exception:
                        pass
                
                if not event_datetime:
                    event_datetime = datetime.datetime.now(pytz.UTC)
                
                # For completed matches, only skip if older than 7 days and has no results message
                if is_completed and not row.get("results_message_id"):
                    updated_at_str = row.get("Updated_At") or row.get("Created_At")
                    if updated_at_str:
                        try:
                            clean_uat = updated_at_str.replace('Z', '+00:00')
                            uat = datetime.datetime.fromisoformat(clean_uat)
                            now_utc = datetime.datetime.now(uat.tzinfo) if uat.tzinfo else datetime.datetime.now(pytz.UTC)
                            if uat < now_utc - datetime.timedelta(days=7):
                                continue
                        except Exception:
                            continue

                def parse_int_safe(val):
                    if not val:
                        return None
                    try:
                        return int(val)
                    except ValueError:
                        return None
                        
                g_id = parse_int_safe(row.get("Guild_ID"))
                t1_id = parse_int_safe(row.get("Team1_Captain_ID") or row.get("Team1_ID"))
                t2_id = parse_int_safe(row.get("Team2_Captain_ID") or row.get("Team2_ID"))
                j_id = parse_int_safe(row.get("Judge_ID"))
                r_id = parse_int_safe(row.get("Recorder_ID"))

                t1_n = row.get('Team1_Captain_Name') or row.get('Team1_Name')
                t2_n = row.get('Team2_Captain_Name') or row.get('Team2_Name')
                m_name = row.get('Match_Name') or ''
                if (not t1_n or not t2_n) and ' vs ' in m_name:
                    parts = m_name.split(' vs ', 1)
                    if not t1_n and len(parts) == 2: t1_n = parts[0].strip()
                    if not t2_n and len(parts) == 2: t2_n = parts[1].strip()
                
                if event_id not in scheduled_events:
                    scheduled_events[event_id] = {
                        'guild_id': g_id,
                        'title': f"Round {row.get('Round')} Match",
                        'datetime': event_datetime,
                        'time_str': utc_time_str,
                        'date_str': date_str,
                        'round': row.get('Round'),
                        'group': row.get('Group'),
                        'minutes_left': 0,
                        'tournament': row.get('Tournament_ID') or row.get('Tournament'),
                        'mode': None,
                        'judge': j_id,
                        'recorder': r_id,
                        'channel_id': parse_int_safe(row.get("Channel_ID")),
                        'team1_captain': t1_id,
                        'team2_captain': t2_id,
                        'team1_name': t1_n,
                        'team2_name': t2_n,
                        'match_name': m_name or f"{t1_n or 'Team 1'} vs {t2_n or 'Team 2'}",
                        'status': row_status or 'scheduled',
                        'recording_link': row.get('recording_link') or '',
                        'recorder_link': row.get('recorder_link') or '',
                        'judge_link': row.get('judge_link') or '',
                        'results_message_id': parse_int_safe(row.get('results_message_id')),
                        'results_channel_id': parse_int_safe(row.get('results_channel_id')),
                        'match_results_message_id': parse_int_safe(row.get('match_results_message_id')),
                        'match_results_channel_id': parse_int_safe(row.get('match_results_channel_id')),
                        'winner_score': row.get('Team1_Score'),
                        'loser_score': row.get('Team2_Score'),
                        'winner_id': row.get('Winner_ID'),
                        'remarks': row.get('Remarks') or '',
                        'disqualified': row.get('Disqualified') or False,
                    }
                    loaded_count += 1
                else:
                    existing = scheduled_events[event_id]
                    if has_remote_time and event_datetime and existing.get('datetime') != event_datetime:
                        existing['datetime'] = event_datetime
                        existing['time_str'] = utc_time_str
                        existing['date_str'] = date_str
                    
                    supabase_ch = parse_int_safe(row.get("Channel_ID"))
                    if supabase_ch and existing.get('channel_id') != supabase_ch:
                        existing['channel_id'] = supabase_ch
                        
                    if t1_id and existing.get('team1_captain') != t1_id:
                        existing['team1_captain'] = t1_id
                    if t2_id and existing.get('team2_captain') != t2_id:
                        existing['team2_captain'] = t2_id
                    if row.get('Team1_Captain_Name'):
                        existing['team1_name'] = row.get('Team1_Captain_Name')
                    if row.get('Team2_Captain_Name'):
                        existing['team2_name'] = row.get('Team2_Captain_Name')
                        
                    if j_id and existing.get('judge') != j_id:
                        existing['judge'] = j_id
                    if r_id and existing.get('recorder') != r_id:
                        existing['recorder'] = r_id
                        
                    if row.get('recording_link'):
                        existing['recording_link'] = row.get('recording_link')
                    if row.get('recorder_link'):
                        existing['recorder_link'] = row.get('recorder_link')
                    if row.get('judge_link'):
                        existing['judge_link'] = row.get('judge_link')
                    if row.get('results_message_id'):
                        existing['results_message_id'] = parse_int_safe(row.get('results_message_id'))
                    if row.get('results_channel_id'):
                        existing['results_channel_id'] = parse_int_safe(row.get('results_channel_id'))
                    if row_status:
                        existing['status'] = row_status
                    if row.get('Team1_Score') is not None:
                        existing['winner_score'] = row.get('Team1_Score')
                    if row.get('Team2_Score') is not None:
                        existing['loser_score'] = row.get('Team2_Score')
                    
            print(f"✅ Loaded {loaded_count} scheduled event(s) from Supabase.")
    except Exception as e:
        print(f"❌ Error loading scheduled events from Supabase: {e}")

def find_event_by_name_or_id(guild_id: int, query: str):
    if not query:
        return None, None
    query_clean = str(query).strip()
    query_lower = query_clean.lower()
    
    if query_clean in scheduled_events and str(scheduled_events[query_clean].get('guild_id')) == str(guild_id):
        return query_clean, scheduled_events[query_clean]
        
    if query_clean.startswith("[") and "]" in query_clean:
        extracted_id = query_clean[1:query_clean.index("]")].strip()
        if extracted_id in scheduled_events and str(scheduled_events[extracted_id].get('guild_id')) == str(guild_id):
            return extracted_id, scheduled_events[extracted_id]

    for ev_id, ev_data in scheduled_events.items():
        if str(ev_data.get('guild_id')) != str(guild_id):
            continue
        m_name = (ev_data.get('match_name') or f"{ev_data.get('team1_name', '')} vs {ev_data.get('team2_name', '')}").lower()
        t1 = str(ev_data.get('team1_name', '')).lower()
        t2 = str(ev_data.get('team2_name', '')).lower()
        
        if query_lower == ev_id.lower() or query_lower == m_name or (t1 and t1 in query_lower and t2 and t2 in query_lower):
            return ev_id, ev_data

    for ev_id, ev_data in scheduled_events.items():
        if str(ev_data.get('guild_id')) != str(guild_id):
            continue
        m_name = (ev_data.get('match_name') or f"{ev_data.get('team1_name', '')} vs {ev_data.get('team2_name', '')}").lower()
        t1 = str(ev_data.get('team1_name', '')).lower()
        t2 = str(ev_data.get('team2_name', '')).lower()
        
        if query_lower in m_name or query_lower in ev_id.lower() or (t1 and query_lower in t1) or (t2 and query_lower in t2):
            return ev_id, ev_data
            
    return None, None

def _json_serialize_clean(obj):
    if hasattr(obj, 'id'):
        return obj.id
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_serialize_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_serialize_clean(x) for x in obj]
    return str(obj) if not isinstance(obj, (int, float, bool, type(None))) else obj

def save_scheduled_events(event_id: Optional[str] = None):
    try:
        data_to_save = {}
        for ev_id, ev_data in scheduled_events.items():
            data_to_save[ev_id] = _json_serialize_clean(ev_data)
        
        with open('scheduled_events.json', 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)

        if supabase_client:
            try:
                loop = asyncio.get_running_loop()
                if event_id and event_id in scheduled_events:
                    loop.create_task(save_event_to_supabase(event_id, scheduled_events[event_id]))
                elif not event_id and scheduled_events:
                    # Sync only the most recent event to avoid socket exhaustion and duplicate mass queries
                    latest_id = list(scheduled_events.keys())[-1]
                    loop.create_task(save_event_to_supabase(latest_id, scheduled_events[latest_id]))
            except RuntimeError:
                pass
    except Exception as e:
        print(f"Error saving scheduled events: {e}")

async def save_event_to_supabase(event_id: str, event_data: dict):
    if not supabase_client:
        return
        
    try:
        guild_id = event_data.get('guild_id')
        t1_cap = event_data.get('team1_captain')
        t2_cap = event_data.get('team2_captain')
        judge_val = event_data.get('judge')
        recorder_val = event_data.get('recorder')
        
        t1_id = getattr(t1_cap, 'id', t1_cap)
        t2_id = getattr(t2_cap, 'id', t2_cap)
        j_id = getattr(judge_val, 'id', judge_val) if judge_val else None
        r_id = getattr(recorder_val, 'id', recorder_val) if recorder_val else None
        
        t1_name = event_data.get('team1_name') or (t1_cap.name if hasattr(t1_cap, 'name') else '')
        t2_name = event_data.get('team2_name') or (t2_cap.name if hasattr(t2_cap, 'name') else '')
        match_name = event_data.get('match_name') or f"{t1_name} vs {t2_name}"

        raw_tourney = event_data.get('tournament_id') or event_data.get('tournament') or ''
        resolved_t_id = None
        
        if raw_tourney and "(" in str(raw_tourney) and "[" in str(raw_tourney):
            m = re.search(r'\(([^)]+)\)', str(raw_tourney))
            if m:
                raw_tourney = m.group(1).strip()

        if guild_id and str(raw_tourney).strip():
            try:
                tournaments = load_guild_tournaments(int(guild_id))
                t_clean = str(raw_tourney).strip().lower()
                if t_clean in tournaments:
                    resolved_t_id = t_clean
                else:
                    for tid, tcfg in tournaments.items():
                        if tcfg.get('name', '').strip().lower() == t_clean:
                            resolved_t_id = tid
                            break
                if resolved_t_id and resolved_t_id in tournaments:
                    _sync_save_tournament_to_supabase(int(guild_id), resolved_t_id, tournaments[resolved_t_id])
            except Exception as tourney_sync_err:
                print(f"[Supabase] Note on tournament pre-sync: {tourney_sync_err}")

        # Check if resolved_t_id is valid non-empty string; if not, set to None (NULL in SQL)
        if resolved_t_id and str(resolved_t_id).strip():
            resolved_t_id = str(resolved_t_id).strip()
        elif str(raw_tourney).strip():
            t_candidate = str(raw_tourney).strip()
            # Do not create corrupted placeholder if it has brackets or parentheses
            if "(" in t_candidate or "[" in t_candidate:
                resolved_t_id = None
            else:
                try:
                    t_check_query = supabase_client.table("Tournaments").select("Tournament_ID").eq("Tournament_ID", t_candidate)
                    if guild_id:
                        t_check_query = t_check_query.eq("Guild_ID", str(guild_id))
                    t_check_res = t_check_query.execute()
                    if t_check_res and t_check_res.data and len(t_check_res.data) > 0:
                        resolved_t_id = t_candidate
                    elif guild_id:
                        # Upsert placeholder tournament so FK constraint is satisfied
                        t_payload = {
                            "Tournament_ID": t_candidate,
                            "Guild_ID": str(guild_id),
                            "Tournament_Name": t_candidate,
                            "State": "active"
                        }
                        supabase_safe_upsert("Tournaments", t_payload, on_conflict="Guild_ID,Tournament_ID")
                        resolved_t_id = t_candidate
                    else:
                        resolved_t_id = None
                except Exception:
                    resolved_t_id = None
        else:
            resolved_t_id = None

        target_table = "Matches"
        try:
            res = await asyncio.to_thread(
                lambda: supabase_client.table("Matches").select("Match_ID").eq("Match_ID", event_id).execute()
            )
        except Exception:
            target_table = "Events"
            res = await asyncio.to_thread(
                lambda: supabase_client.table("Events").select("id").eq("Event_ID", event_id).execute()
            )

        if target_table == "Matches":
            round_val = event_data.get('round', '')
            round_int = int(round_val) if str(round_val).isdigit() else 1
            w_score = event_data.get('winner_score') if event_data.get('winner_score') is not None else event_data.get('team1_score')
            l_score = event_data.get('loser_score') if event_data.get('loser_score') is not None else event_data.get('team2_score')

            dt_val = event_data.get('datetime')
            sched_time_str = None
            if isinstance(dt_val, datetime.datetime):
                sched_time_str = dt_val.isoformat()
            elif isinstance(dt_val, str) and dt_val:
                sched_time_str = dt_val

            j_name_str = getattr(judge_val, 'name', getattr(judge_val, 'display_name', '')) if judge_val else ''
            r_name_str = getattr(recorder_val, 'name', getattr(recorder_val, 'display_name', '')) if recorder_val else ''

            match_row = {
                "Match_ID": event_id,
                "Guild_ID": str(guild_id) if guild_id else None,
                "Match_Name": match_name,
                "Tournament_ID": resolved_t_id,
                "Round": round_int,
                "Group": str(event_data.get('group', '') or ''),
                "Scheduled_Time": sched_time_str,
                "Date": str(event_data.get('date_str') or ''),
                "UTC_Time": str(event_data.get('time_str') or ''),
                "Team1_ID": str(t1_id) if t1_id else None,
                "Team2_ID": str(t2_id) if t2_id else None,
                "Team1_Captain_ID": str(t1_id) if t1_id else None,
                "Team1_Captain_Name": str(t1_name or ''),
                "Team2_Captain_ID": str(t2_id) if t2_id else None,
                "Team2_Captain_Name": str(t2_name or ''),
                "Judge_ID": str(j_id) if j_id else None,
                "Judge_Name": str(j_name_str or ''),
                "Recorder_ID": str(r_id) if r_id else None,
                "Recorder_Name": str(r_name_str or ''),
                "Team1_Score": int(w_score) if w_score is not None and str(w_score).isdigit() else None,
                "Team2_Score": int(l_score) if l_score is not None and str(l_score).isdigit() else None,
                "Status": str(event_data.get('status', 'scheduled')).lower(),
                "Channel_ID": str(event_data.get('channel_id', '')),
                "recording_link": str(event_data.get('recording_link', '')),
                "recorder_link": str(event_data.get('recorder_link', '')),
                "judge_link": str(event_data.get('judge_link', '')),
                "results_message_id": str(event_data.get('results_message_id', '')),
                "results_channel_id": str(event_data.get('results_channel_id', '')),
                "match_results_message_id": str(event_data.get('match_results_message_id', '')),
                "match_results_channel_id": str(event_data.get('match_results_channel_id', '')),
                "Winner_ID": str(event_data.get('winner_id')) if event_data.get('winner_id') else None,
                "Remarks": str(event_data.get('remarks') or ''),
                "Disqualified": bool(event_data.get('disqualified') or False),
                "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }

            # Ensure Team1 and Team2 exist in Teams table so foreign key constraint (Matches_Team1_ID_fkey) is satisfied
            if t1_id and resolved_t_id:
                try:
                    q = supabase_client.table("Teams").select("Team_ID").eq("Tournament_ID", str(resolved_t_id))
                    if t1_name:
                        q = q.eq("Team_Name", str(t1_name))
                    else:
                        q = q.eq("Captain_ID", str(t1_id))
                    existing_t1 = await asyncio.to_thread(lambda: q.execute())
                    if existing_t1 and existing_t1.data and len(existing_t1.data) > 0:
                        t1_id = existing_t1.data[0]["Team_ID"]
                    else:
                        t1_row = {
                            "Team_ID": str(t1_id),
                            "Tournament_ID": resolved_t_id,
                            "Team_Name": str(t1_name or f"Team {t1_id}"),
                            "Captain_ID": str(t1_id)
                        }
                        await asyncio.to_thread(supabase_safe_upsert, "Teams", t1_row, "Team_ID")
                except Exception as e:
                    print(f"[Supabase] Note on Team1 sync: {e}")

            if t2_id and resolved_t_id:
                try:
                    q = supabase_client.table("Teams").select("Team_ID").eq("Tournament_ID", str(resolved_t_id))
                    if t2_name:
                        q = q.eq("Team_Name", str(t2_name))
                    else:
                        q = q.eq("Captain_ID", str(t2_id))
                    existing_t2 = await asyncio.to_thread(lambda: q.execute())
                    if existing_t2 and existing_t2.data and len(existing_t2.data) > 0:
                        t2_id = existing_t2.data[0]["Team_ID"]
                    else:
                        t2_row = {
                            "Team_ID": str(t2_id),
                            "Tournament_ID": resolved_t_id,
                            "Team_Name": str(t2_name or f"Team {t2_id}"),
                            "Captain_ID": str(t2_id)
                        }
                        await asyncio.to_thread(supabase_safe_upsert, "Teams", t2_row, "Team_ID")
                except Exception as e:
                    print(f"[Supabase] Note on Team2 sync: {e}")

            match_row["Team1_ID"] = str(t1_id) if t1_id else None
            match_row["Team2_ID"] = str(t2_id) if t2_id else None

            try:
                await asyncio.to_thread(supabase_safe_upsert, "Matches", match_row, "Match_ID")
            except Exception as upsert_err:
                if "Tournament_ID" in str(upsert_err):
                    match_row["Tournament_ID"] = None
                    await asyncio.to_thread(supabase_safe_upsert, "Matches", match_row, "Match_ID")
                else:
                    print(f"[Supabase] Error upserting match {event_id}: {upsert_err}")

            # Sync staff assignments to MatchStaff
            if j_id:
                j_name = judge_val.display_name if hasattr(judge_val, 'display_name') else (judge_val.name if hasattr(judge_val, 'name') else "Judge")
                j_payload = {
                    "Match_ID": event_id,
                    "User_ID": str(j_id),
                    "Name": str(j_name),
                    "Role": "Judge",
                    "Confirmed": True
                }
                await asyncio.to_thread(supabase_safe_upsert, "MatchStaff", j_payload, "Match_ID,User_ID,Role")
            if r_id:
                r_name = recorder_val.display_name if hasattr(recorder_val, 'display_name') else (recorder_val.name if hasattr(recorder_val, 'name') else "Recorder")
                r_payload = {
                    "Match_ID": event_id,
                    "User_ID": str(r_id),
                    "Name": str(r_name),
                    "Role": "Recorder",
                    "Confirmed": True
                }
                await asyncio.to_thread(supabase_safe_upsert, "MatchStaff", r_payload, "Match_ID,User_ID,Role")

        else:
            legacy_row = {
                "Guild_ID": str(guild_id) if guild_id else "",
                "Event_ID": event_id,
                "Match_Name": match_name,
                "Tournament": event_data.get('tournament', ''),
                "Round": event_data.get('round', ''),
                "Group": event_data.get('group', '') or '',
                "Date": event_data.get('date_str', ''),
                "UTC_Time": event_data.get('time_str', ''),
                "Team1_Captain_ID": str(t1_id) if t1_id else '',
                "Team1_Captain_Name": t1_name,
                "Team2_Captain_ID": str(t2_id) if t2_id else '',
                "Team2_Captain_Name": t2_name,
                "Judge_ID": str(j_id) if j_id else '',
                "Judge_Name": judge_val.name if hasattr(judge_val, 'name') else '',
                "Recorder_ID": str(r_id) if r_id else '',
                "Recorder_Name": recorder_val.name if hasattr(recorder_val, 'name') else '',
                "Channel_ID": str(event_data.get('channel_id', '')),
                "Status": event_data.get('status', 'Scheduled'),
                "recording_link": event_data.get('recording_link', ''),
                "recorder_link": event_data.get('recorder_link', ''),
                "judge_link": event_data.get('judge_link', ''),
                "results_message_id": str(event_data.get('results_message_id', '')),
                "results_channel_id": str(event_data.get('results_channel_id', '')),
                "match_results_message_id": str(event_data.get('match_results_message_id', '')),
                "match_results_channel_id": str(event_data.get('match_results_channel_id', '')),
                "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }
            if res and res.data and len(res.data) > 0:
                row_id = res.data[0]["id"]
                await asyncio.to_thread(
                    lambda: supabase_client.table("Events").update(legacy_row).eq("id", row_id).execute()
                )
            else:
                await asyncio.to_thread(
                    lambda: supabase_client.table("Events").insert(legacy_row).execute()
                )

            # If match has results, sync to Results table
            w_score = event_data.get('winner_score')
            l_score = event_data.get('loser_score')
            if w_score is not None or event_data.get('winner_id'):
                results_row = {
                    "Event_ID": event_id,
                    "Guild_ID": str(guild_id) if guild_id else "",
                    "Match_Name": match_name,
                    "Tournament": event_data.get('tournament', ''),
                    "Round": str(event_data.get('round', '')),
                    "Group": str(event_data.get('group', '') or ''),
                    "Winner_ID": str(event_data.get('winner_id', '')),
                    "Winner_Name": str(event_data.get('winner_name', '')),
                    "Winner_Score": str(w_score) if w_score is not None else "",
                    "Loser_ID": str(event_data.get('loser_id', '')),
                    "Loser_Name": str(event_data.get('loser_name', '')),
                    "Loser_Score": str(l_score) if l_score is not None else "",
                    "Judge_ID": str(j_id) if j_id else '',
                    "Judge_Name": judge_val.name if hasattr(judge_val, 'name') else '',
                    "Recorder_ID": str(r_id) if r_id else '',
                    "Recorder_Name": recorder_val.name if hasattr(recorder_val, 'name') else '',
                    "Remarks": str(event_data.get('remarks', '') or ''),
                    "Disqualified": bool(event_data.get('disqualified') or False),
                    "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                }
                await asyncio.to_thread(supabase_safe_upsert, "Results", results_row)

        # Sync to Judge_and_Record table if available in Supabase
        try:
            j_display = ""
            if j_id:
                j_display = judge_val.display_name if hasattr(judge_val, 'display_name') else (judge_val.name if hasattr(judge_val, 'name') else str(judge_val))
            r_display = ""
            if r_id:
                r_display = recorder_val.display_name if hasattr(recorder_val, 'display_name') else (recorder_val.name if hasattr(recorder_val, 'name') else str(recorder_val))

            jr_payload = {
                "Guild_ID": str(guild_id) if guild_id else "",
                "Event_ID": str(event_id),
                "Match_Name": str(match_name or ''),
                "Tournament": str(event_data.get('tournament', '') or ''),
                "Round": str(event_data.get('round', '') or ''),
                "Date": str(event_data.get('date_str', '') or ''),
                "UTC_Time": str(event_data.get('time_str', '') or ''),
                "Judge_ID": str(j_id) if j_id else "",
                "Judge_Name": j_display if j_id else "",
                "judge_link": str(event_data.get('judge_link', '') or ''),
                "Recorder_ID": str(r_id) if r_id else "",
                "Recorder_Name": r_display if r_id else "",
                "recorder_link": str(event_data.get('recorder_link', '') or event_data.get('recording_link', '') or ''),
                "Status": str(event_data.get('status', 'Scheduled')),
                "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }
            upserted = await asyncio.to_thread(supabase_safe_upsert, "Judge_and_Record", jr_payload, "Event_ID")
            if not upserted:
                await asyncio.to_thread(supabase_safe_upsert, "Judge and Record", jr_payload, "Event_ID")
        except Exception as jr_err:
            print(f"[Supabase] Note on Judge_and_Record sync: {jr_err}")

    except Exception as e:
        print(f"[Supabase] Error saving event {event_id} to database: {e}")

async def resolve_scheduled_event_members(bot_client: discord.Client):
    print("⏳ Resolving member IDs in scheduled events...")
    resolved_count = 0
    for ev_id, ev_data in scheduled_events.items():
        g_id = ev_data.get('guild_id')
        if not g_id:
            continue
        try:
            g_id_int = int(g_id)
        except (ValueError, TypeError):
            continue
        guild = bot_client.get_guild(g_id_int)
        if not guild:
            try:
                guild = await bot_client.fetch_guild(g_id_int)
            except Exception:
                continue
            
        for key in ['team1_captain', 'team2_captain', 'judge', 'recorder']:
            val = ev_data.get(key)
            if val is not None and not isinstance(val, (discord.Member, discord.User)):
                try:
                    user_id = int(val)
                    member = guild.get_member(user_id)
                    if not member:
                        try:
                            member = await guild.fetch_member(user_id)
                        except Exception:
                            member = None
                    if member:
                        ev_data[key] = member
                        resolved_count += 1
                except (ValueError, TypeError):
                    pass
    print(f"✅ Resolved {resolved_count} member ID(s) to Member objects.")

def parse_round_to_int(round_val) -> int:
    if not round_val:
        return 1
    s = str(round_val).strip().lower()
    m = re.search(r'\d+', s)
    if m:
        return int(m.group())
    if 'final' in s:
        if 'semi' in s:
            return 98
        if 'quarter' in s:
            return 97
        return 99
    if 'qualifier' in s or 'qual' in s:
        return 95
    return 1

DEADLINES_FILE_PATH = os.path.join(BASE_DIR, 'scheduled_deadlines.json')

def load_scheduled_deadlines():
    global scheduled_deadlines
    try:
        if os.path.exists(DEADLINES_FILE_PATH):
            with open(DEADLINES_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for dl_id, dl_data in data.items():
                    if isinstance(dl_data, dict) and 'deadline_dt' in dl_data:
                        try:
                            dl_data['deadline_dt'] = datetime.datetime.fromisoformat(dl_data['deadline_dt'])
                        except Exception:
                            pass
                scheduled_deadlines.clear()
                scheduled_deadlines.update(data)
                print(f"Loaded {len(scheduled_deadlines)} scheduled deadlines from local fallback")
    except Exception as e:
        print(f"Error loading scheduled_deadlines.json fallback: {e}")
        scheduled_deadlines.clear()

async def load_all_deadlines_from_supabase():
    global scheduled_deadlines
    if not supabase_client:
        return
    try:
        resp = await asyncio.to_thread(lambda: supabase_client.table("Deadlines").select("*").execute())
        if resp and resp.data:
            for row in resp.data:
                try:
                    t_id = str(row.get("Tournament_ID") or row.get("Guild_ID") or "")
                    rnd_int = row.get("Round", 1)
                    if isinstance(rnd_int, str) and rnd_int.isdigit():
                        rnd_int = int(rnd_int)
                    elif not isinstance(rnd_int, int):
                        rnd_int = parse_round_to_int(rnd_int)
                    rnd_name = f"Round {rnd_int}" if rnd_int < 90 else ("Final" if rnd_int == 99 else "Semi-Final")
                    g_id = row.get("Guild_ID")
                    if not g_id:
                        for g_k, t_dict in TOURNAMENTS_CACHE.items():
                            if isinstance(t_dict, dict):
                                for t_k, t_cfg in t_dict.items():
                                    if isinstance(t_cfg, dict) and (t_cfg.get('id') == t_id or t_cfg.get('Tournament_ID') == t_id or t_k == t_id):
                                        g_id = int(g_k) if str(g_k).isdigit() else g_k
                                        break
                            if g_id:
                                break
                    dl_id = f"dl_{g_id}_{t_id}_{rnd_int}"
                    if dl_id not in scheduled_deadlines:
                        dt_raw = row.get("Deadline_Time")
                        dt_obj = datetime.datetime.fromisoformat(str(dt_raw)) if dt_raw else datetime.datetime.utcnow()
                        scheduled_deadlines[dl_id] = {
                            'guild_id': int(g_id) if g_id and str(g_id).isdigit() else g_id,
                            'tournament': t_id,
                            'tournament_id': t_id,
                            'round': rnd_name,
                            'deadline_dt': dt_obj
                        }
                except Exception as parse_err:
                    print(f"Error parsing Supabase deadline row {row}: {parse_err}")
            
            # Keep local JSON in sync with Supabase deadlines
            try:
                data_to_save = {}
                for d_id, d_data in scheduled_deadlines.items():
                    if isinstance(d_data, dict):
                        copy_data = d_data.copy()
                        if 'deadline_dt' in copy_data and isinstance(copy_data['deadline_dt'], datetime.datetime):
                            copy_data['deadline_dt'] = copy_data['deadline_dt'].isoformat()
                        data_to_save[d_id] = copy_data
                with open(DEADLINES_FILE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(data_to_save, f, indent=4)
            except Exception as save_err:
                print(f"Error caching deadlines to JSON: {save_err}")
            print(f"Merged config with {len(resp.data)} deadlines from Supabase.")
    except Exception as e:
        print(f"Error loading deadlines from Supabase: {e}")

def save_scheduled_deadline(dl_id: str, dl_data: dict):
    scheduled_deadlines[dl_id] = dl_data
    try:
        data_to_save = {}
        for d_id, d_data in scheduled_deadlines.items():
            if isinstance(d_data, dict):
                copy_data = d_data.copy()
                if 'deadline_dt' in copy_data and isinstance(copy_data['deadline_dt'], datetime.datetime):
                    copy_data['deadline_dt'] = copy_data['deadline_dt'].isoformat()
                data_to_save[d_id] = copy_data
        with open(DEADLINES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e:
        print(f"Error saving scheduled_deadlines.json: {e}")

    if supabase_client:
        try:
            g_id = str(dl_data.get('guild_id') or "")
            t_name = dl_data.get('tournament', '')
            t_id = dl_data.get('tournament_id')
            if not t_id and g_id:
                tourns = load_guild_tournaments(int(g_id) if g_id.isdigit() else g_id)
                for tk, tv in tourns.items():
                    if tv.get('name', '').lower() == t_name.lower() or tk.lower() == t_name.lower():
                        t_id = tv.get('id') or tv.get('Tournament_ID') or tk
                        break
            if not t_id:
                tourns = load_guild_tournaments(int(g_id)) if g_id and g_id.isdigit() else {}
                if tourns:
                    first_t = next(iter(tourns.values()))
                    t_id = first_t.get('id') or first_t.get('Tournament_ID') or next(iter(tourns.keys()))
                else:
                    t_id = t_name

            rnd_int = parse_round_to_int(dl_data.get('round', 1))
            dt_val = dl_data['deadline_dt']
            dt_iso = dt_val.isoformat() if isinstance(dt_val, datetime.datetime) else str(dt_val)

            dl_payload = {
                "Tournament_ID": str(t_id),
                "Guild_ID": g_id,
                "Round": rnd_int,
                "Deadline_Time": dt_iso,
                "Created_At": datetime.datetime.utcnow().isoformat()
            }
            supabase_safe_upsert("Deadlines", dl_payload)
        except Exception as e:
            print(f"[Supabase] Failed to upsert deadline to Supabase: {e}")

def delete_scheduled_deadline(dl_id: str) -> bool:
    dl_data = scheduled_deadlines.pop(dl_id, None)
    if not dl_data:
        return False
    
    try:
        data_to_save = {}
        for d_id, d_data in scheduled_deadlines.items():
            if isinstance(d_data, dict):
                copy_data = d_data.copy()
                if 'deadline_dt' in copy_data and isinstance(copy_data['deadline_dt'], datetime.datetime):
                    copy_data['deadline_dt'] = copy_data['deadline_dt'].isoformat()
                data_to_save[d_id] = copy_data
        with open(DEADLINES_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e:
        print(f"Error saving scheduled_deadlines.json on delete: {e}")

    if supabase_client and isinstance(dl_data, dict):
        try:
            g_id = str(dl_data.get('guild_id') or "")
            t_name = dl_data.get('tournament', '')
            t_id = dl_data.get('tournament_id')
            if not t_id and g_id:
                tourns = load_guild_tournaments(int(g_id) if g_id.isdigit() else g_id)
                for tk, tv in tourns.items():
                    if tv.get('name', '').lower() == t_name.lower() or tk.lower() == t_name.lower():
                        t_id = tv.get('id') or tv.get('Tournament_ID') or tk
                        break
            if not t_id:
                t_id = t_name
            rnd_int = parse_round_to_int(dl_data.get('round', 1))
            try:
                delete_query = supabase_client.table("Deadlines").delete().eq("Tournament_ID", str(t_id)).eq("Round", rnd_int)
                if g_id:
                    delete_query = delete_query.eq("Guild_ID", g_id)
                delete_query.execute()
            except Exception:
                if g_id:
                    supabase_client.table("Deadlines").delete().eq("Guild_ID", g_id).eq("Round", rnd_int).execute()
        except Exception as e:
            print(f"[Supabase] Failed to delete deadline from Supabase: {e}")
            
    return True

def save_player_data(discord_id: Union[int, str], ign: Optional[str] = None, game_id: Optional[str] = None, title: Optional[str] = None) -> dict:
    """
    Saves player profile info to players.json and synchronizes to Supabase Players table.
    """
    d_id = str(discord_id)
    players = {}
    path = os.path.join(BASE_DIR, 'players.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                players = json.load(f)
        except Exception:
            pass
    
    player_entry = players.get(d_id, {
        "Player_ID": f"p_{d_id}",
        "Discord_ID": d_id,
        "IGN": "",
        "Game_ID": "",
        "Title": "",
        "Updated_At": datetime.datetime.utcnow().isoformat()
    })
    
    if ign is not None: player_entry["IGN"] = ign.strip()
    if game_id is not None: player_entry["Game_ID"] = game_id.strip()
    if title is not None: player_entry["Title"] = title.strip()
    player_entry["Updated_At"] = datetime.datetime.utcnow().isoformat()
    
    players[d_id] = player_entry
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(players, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving players.json: {e}")
        
    if supabase_client:
        supabase_safe_upsert("Players", player_entry, on_conflict="Discord_ID")
        
    return player_entry

def save_team_data(captain_id: Union[int, str], team_name: str, tournament_id: Optional[str] = None) -> dict:
    """
    Saves team info to teams.json and synchronizes to Supabase Teams table.
    """
    c_id = str(captain_id)
    teams = {}
    path = os.path.join(BASE_DIR, 'teams.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                teams = json.load(f)
        except Exception:
            pass
            
    team_entry = teams.get(c_id, {
        "Team_ID": c_id,
        "Tournament_ID": str(tournament_id or ""),
        "Team_Name": team_name.strip(),
        "Captain_ID": c_id,
        "Updated_At": datetime.datetime.utcnow().isoformat()
    })
    team_entry["Team_Name"] = team_name.strip()
    if tournament_id:
        team_entry["Tournament_ID"] = str(tournament_id)
    team_entry["Updated_At"] = datetime.datetime.utcnow().isoformat()
    
    teams[c_id] = team_entry
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(teams, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving teams.json: {e}")
        
    if supabase_client:
        supabase_safe_upsert("Teams", team_entry, on_conflict="Captain_ID")
        
    return team_entry




# ===========================================================================================
# SHEETDB POST FALLBACK / SYNC
# ===========================================================================================

def _sync_sheetdb_post(sheet_name: str, row_data: dict):
    if not supabase_client:
        return False

    cleaned_row = row_data.copy()
    if "sheetdb_api_url" in cleaned_row:
        del cleaned_row["sheetdb_api_url"]

    target_table = sheet_name
    if target_table in ("Events", "Results"):
        target_table = "Matches"
        match_id = cleaned_row.get("Match_ID") or cleaned_row.get("Event_ID")
        if not match_id:
            return False
        match_payload = {
            "Match_ID": str(match_id),
            "Match_Name": str(cleaned_row.get("Match_Name") or ""),
            "Round": int(cleaned_row.get("Round", 1)) if str(cleaned_row.get("Round", "")).isdigit() else 1,
            "Group": str(cleaned_row.get("Group") or ""),
            "Status": str(cleaned_row.get("Status", "scheduled")).lower(),
            "Channel_ID": str(cleaned_row.get("Channel_ID") or "")
        }
        try:
            supabase_client.table("Matches").upsert(match_payload, on_conflict="Match_ID").execute()
            return True
        except Exception as e:
            print(f"[Supabase] Exception posting to Matches: {e}")
            return False

    if target_table == "JudgeAssignments":
        target_table = "MatchStaff"
        match_id = cleaned_row.get("Match_ID") or cleaned_row.get("Event_ID")
        user_id = cleaned_row.get("User_ID") or cleaned_row.get("Judge_ID")
        user_name = cleaned_row.get("Name") or cleaned_row.get("Judge_Name") or "Staff"
        if not match_id or not user_id:
            return False
        staff_payload = {
            "Match_ID": str(match_id),
            "User_ID": str(user_id),
            "Name": str(user_name),
            "Role": "Judge",
            "Confirmed": True
        }
        try:
            supabase_client.table("MatchStaff").upsert(staff_payload, on_conflict="Match_ID,User_ID,Role").execute()
            return True
        except Exception as e:
            print(f"[Supabase] Exception posting to MatchStaff: {e}")
            return False

    if target_table == "StaffStats":
        if "Role_Updated" in cleaned_row:
            del cleaned_row["Role_Updated"]
        try:
            supabase_client.table("StaffStats").upsert(cleaned_row).execute()
            return True
        except Exception as e:
            print(f"[Supabase] StaffStats upsert warning: {e}")
            return False

    try:
        supabase_client.table(target_table).insert(cleaned_row).execute()
        return True
    except Exception as e:
        print(f"[Supabase] Exception posting to '{target_table}': {e}")
        return False

async def sheetdb_post(sheet_name: str, row_data: dict):
    await asyncio.to_thread(_sync_sheetdb_post, sheet_name, row_data)


# ===========================================================================================
# CHALLONGE & GOOGLE SHEETS PARSING
# ===========================================================================================

def extract_challonge_id(link: str) -> str:
    match = re.search(r'https?://(?:([a-zA-Z0-9-]+)\.)?challonge\.com/([a-zA-Z0-9-_]+)', link)
    if match:
        subdomain, path = match.groups()
        if subdomain and subdomain != 'www':
            return f"{subdomain}-{path}"
        return path
    return link.split('/')[-1]

def _sync_fetch_challonge_open_matches(bracket_link: str, api_key: str):
    t_id = extract_challonge_id(bracket_link)
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    
    t_url = f"https://api.challonge.com/v1/tournaments/{t_id}.json"
    t_type = "single elimination"
    try:
        t_req = requests.get(t_url, params={"api_key": api_key}, headers=headers, timeout=15)
        if t_req.status_code == 200:
            t_type = t_req.json().get('tournament', {}).get('tournament_type', 'single elimination')
    except Exception as e:
        print(f"Error fetching tournament type from Challonge: {e}")
        
    p_url = f"https://api.challonge.com/v1/tournaments/{t_id}/participants.json"
    p_req = requests.get(p_url, params={"api_key": api_key}, headers=headers, timeout=15)
    if p_req.status_code != 200:
        return None, f"Failed to fetch participants (HTTP {p_req.status_code}): {p_req.text[:300]}"
    pts = {p['participant']['id']: p['participant']['name'] for p in p_req.json()}
    
    m_url = f"https://api.challonge.com/v1/tournaments/{t_id}/matches.json"
    m_req = requests.get(m_url, params={"api_key": api_key}, headers=headers, timeout=15)
    if m_req.status_code != 200:
        return None, f"Failed to fetch matches (HTTP {m_req.status_code}): {m_req.text[:300]}"
    
    matches_json = m_req.json()
    all_matches = [m['match'] for m in matches_json]
    
    winners_rounds = sorted(list(set(m.get('round') for m in all_matches if m.get('round', 0) > 0)))
    losers_rounds = sorted(list(set(m.get('round') for m in all_matches if m.get('round', 0) < 0)), reverse=True)
    
    max_w = winners_rounds[-1] if winners_rounds else 0
    round_mapping = {}
    
    if "swiss" in t_type or "robin" in t_type:
        for r in winners_rounds:
            round_mapping[r] = f"Round {r}"
    elif "double" in t_type:
        for r in winners_rounds:
            if r == max_w:
                round_mapping[r] = "Finals"
            elif r == max_w - 1 and max_w >= 2:
                round_mapping[r] = "Semifinals"
            else:
                round_mapping[r] = f"Round {r}"
        if losers_rounds:
            min_l = losers_rounds[-1]
            for r in losers_rounds:
                if r == min_l:
                    round_mapping[r] = "Losers Finals"
                elif r == min_l + 1:
                    round_mapping[r] = "Losers Semifinals"
                else:
                    round_mapping[r] = f"Losers Round {abs(r)}"
    else:
        for r in winners_rounds:
            if r == max_w:
                round_mapping[r] = "Finals"
            elif r == max_w - 1 and max_w >= 2:
                round_mapping[r] = "Semifinals"
            elif r == max_w - 2 and max_w >= 3:
                round_mapping[r] = "Quarterfinals"
            else:
                round_mapping[r] = f"Round {r}"
                
    matches_info = []
    for m in all_matches:
        if m.get('state') != 'open':
            continue
        if not m.get('player1_id') or not m.get('player2_id'):
            continue
        p1 = pts.get(m['player1_id'], "TBD")
        p2 = pts.get(m['player2_id'], "TBD")
        r_val = m.get('round')
        r_name = round_mapping.get(r_val, f"Round {r_val}")
        
        matches_info.append({
            'id': m['id'],
            'round': r_val,
            'round_name': r_name,
            'team1': p1,
            'team2': p2,
            'player1_id': m['player1_id'],
            'player2_id': m['player2_id']
        })
    return matches_info, None

async def fetch_challonge_open_matches(bracket_link: str, api_key: str):
    return await asyncio.to_thread(_sync_fetch_challonge_open_matches, bracket_link, api_key)

def _sync_update_challonge_match(bracket_link: str, api_key: str, match_id: str, winner_id: str, scores_csv: str):
    t_id = extract_challonge_id(bracket_link)
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    m_url = f"https://api.challonge.com/v1/tournaments/{t_id}/matches/{match_id}.json"
    data = {
        "api_key": api_key,
        "match[winner_id]": winner_id,
        "match[scores_csv]": scores_csv
    }
    resp = requests.put(m_url, data=data, headers=headers, timeout=15)
    if resp.status_code != 200:
        return False, resp.text
    return True, None

async def update_challonge_match(bracket_link: str, api_key: str, match_id: str, winner_id: str, scores_csv: str):
    return await asyncio.to_thread(_sync_update_challonge_match, bracket_link, api_key, match_id, winner_id, scores_csv)

def extract_discord_id_from_text(text: Union[str, int, float, None]) -> Optional[int]:
    """
    Extracts a 17-20 digit Discord User ID from any format:
    - Pure integer or numeric string
    - Discord mention (<@123456789012345678> or <@!123456789012345678>)
    - Discord URL (https://discord.com/users/123456789012345678)
    - Formatted numbers (1,084,589,736,917,737,522)
    - Scientific notation / float string (1.08458973691774E+18 or 1084589736917737522.0)
    """
    if text is None:
        return None
    if isinstance(text, int):
        if 10**16 <= text <= 10**20:
            return text
        return None

    s = str(text).strip()
    if not s:
        return None

    # 1. Mention format <@!123456789012345678>
    m = re.search(r'<@!?(\d{17,20})>', s)
    if m:
        try: return int(m.group(1))
        except Exception: pass

    # 2. Discord user URL
    m = re.search(r'discord\.com/users/(\d{17,20})', s)
    if m:
        try: return int(m.group(1))
        except Exception: pass

    # 3. 17-20 digit number inside string
    m = re.search(r'\b(\d{17,20})\b', s)
    if m:
        try: return int(m.group(1))
        except Exception: pass

    # 4. Clean out commas / spaces and check if 17-20 digits
    clean_digits = re.sub(r'[^\d]', '', s)
    if 17 <= len(clean_digits) <= 20:
        try: return int(clean_digits)
        except Exception: pass

    # 5. Scientific notation / float string like 1.08458973691774E+18 or 1084589736917737522.0
    try:
        f_val = float(s)
        i_val = int(f_val)
        if 10**16 <= i_val <= 10**20:
            return i_val
    except Exception:
        pass

    return None

def _sync_fetch_google_sheet_captains(sheet_link: str):
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if not match:
        return None, "Invalid Google Sheet link — could not extract sheet ID"
    sheet_id = match.group(1)
    
    # Extract tab GID if specified in sheet URL
    gid_match = re.search(r'[#&?]gid=([0-9]+)', sheet_link)
    gid_param = f"&gid={gid_match.group(1)}" if gid_match else ""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv{gid_param}"
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        reader = csv.reader(io.StringIO(resp.text))
        
        h_row = next(reader, [])
        h_lower = [h.lower().strip() for h in h_row]
        
        key_col = -1
        is_1v1 = False
        for i, h in enumerate(h_lower):
            if any(x in h for x in ['team name', 'team_name', 'team']):
                key_col = i
                is_1v1 = False
                break
            elif any(x in h for x in ['discord name', 'participant', 'player name', 'player', 'name']):
                key_col = i
                is_1v1 = True
                break

        val_col = -1
        for i, h in enumerate(h_lower):
            if i != key_col:
                if any(x in h for x in ['developer id', 'developers id', 'developers i\'d', 'discord id', 'discord_id', 'mention', 'discord tag', 'discord uid', 'uid', 'user id', 'discord']) and not any(x in h for x in ['game id', 'ign', 'in-game']):
                    val_col = i
                    break
        if val_col == -1:
            for i, h in enumerate(h_lower):
                if i != key_col and 'discord' in h:
                    val_col = i
                    break

        ign_col = -1
        game_name_col = -1
        game_id_col = -1
        for i, h in enumerate(h_lower):
            if i != key_col and i != val_col:
                if any(x in h for x in ['in-game name', 'in game name', 'game name', 'ign', 'player name', 'ingame name']):
                    game_name_col = i
                elif any(x in h for x in ['in-game id', 'in game id', 'game id', 'player id', 'account id']):
                    game_id_col = i
                elif any(x in h for x in ['captain id']):
                    ign_col = i

        if ign_col == -1 and game_id_col != -1:
            ign_col = game_id_col
        elif ign_col == -1 and game_name_col != -1:
            ign_col = game_name_col

        if key_col == -1: key_col = 0
        if val_col == -1: val_col = 1
        
        captains = {}
        for row in reader:
            if not row or not any(str(c).strip() for c in row):
                continue
            if len(row) > key_col:
                k = row[key_col].strip()
                if not k:
                    continue
                v = row[val_col].strip() if len(row) > val_col else ""
                ign = row[ign_col].strip() if (ign_col != -1 and len(row) > ign_col) else ""
                g_name = row[game_name_col].strip() if (game_name_col != -1 and len(row) > game_name_col) else ""
                g_id = row[game_id_col].strip() if (game_id_col != -1 and len(row) > game_id_col) else ""
                
                # Check for Discord UID in target column first, then check all cells in row
                discord_uid = extract_discord_id_from_text(v)
                if not discord_uid:
                    for c_idx, cell in enumerate(row):
                        if c_idx != key_col:
                            found_id = extract_discord_id_from_text(cell)
                            if found_id:
                                discord_uid = found_id
                                break

                # Construct discord mention string if UID found
                discord_str = f"<@{discord_uid}>" if discord_uid else v
                
                entry = {
                    "team": k,
                    "discord": discord_str,
                    "discord_id": discord_uid,
                    "ign": g_name or ign or v or k,
                    "game_name": g_name or (ign if g_id and ign != g_id else ""),
                    "game_id": g_id or ign or "",
                    "raw": v
                }

                # Thorough multi-key indexing so Challonge matches can easily find their team
                captains[k] = entry
                captains[k.strip()] = entry
                captains[k.strip().lower()] = entry
                clean_k = re.sub(r'[^a-zA-Z0-9]', '', k).lower()
                if clean_k:
                    captains[clean_k] = entry

                if g_name and g_name.strip():
                    captains[g_name.strip().lower()] = entry
                    clean_gn = re.sub(r'[^a-zA-Z0-9]', '', g_name).lower()
                    if clean_gn:
                        captains[clean_gn] = entry

                if ign and ign.strip():
                    captains[ign.strip().lower()] = entry
                    clean_ign = re.sub(r'[^a-zA-Z0-9]', '', ign).lower()
                    if clean_ign:
                        captains[clean_ign] = entry

        return captains, is_1v1, None
    except Exception as e:
        return None, False, str(e)

async def fetch_google_sheet_captains(sheet_link: str):
    return await asyncio.to_thread(_sync_fetch_google_sheet_captains, sheet_link)


# ===========================================================================================
# EMBED THUMBNAIL RESOLVER
# ===========================================================================================

async def get_thumbnail_url_from_channel(channel_id: Optional[int], bot_client: Optional[discord.Client] = None) -> Optional[str]:
    if not channel_id or not bot_client:
        return None
    try:
        channel = bot_client.get_channel(channel_id)
        if not channel:
            channel = await bot_client.fetch_channel(channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            async for message in channel.history(limit=20):
                if message.attachments:
                    for att in message.attachments:
                        if att.content_type and att.content_type.startswith("image/"):
                            return att.url
    except Exception as e:
        print(f"Error fetching thumbnail from channel {channel_id}: {e}")
    return None

async def resolve_embed_thumbnail(
    guild_id: int, 
    embed: discord.Embed, 
    fallback_to_captain_avatar: Optional[discord.Member] = None,
    bot_client: Optional[discord.Client] = None
) -> tuple[Optional[discord.File], bool]:
    cfg = get_guild_config(guild_id)
    logo_filename = cfg.get('server_logo_path')
    if logo_filename and os.path.exists(logo_filename):
        try:
            with open(logo_filename, "rb") as f:
                logo_data = f.read()
            embed.set_thumbnail(url="attachment://server_logo.png")
            file_obj = discord.File(fp=io.BytesIO(logo_data), filename="server_logo.png")
            return file_obj, True
        except Exception as e:
            print(f"Error loading server logo path {logo_filename}: {e}")

    if bot_client:
        guild = bot_client.get_guild(guild_id)
        if guild and guild.icon:
            try:
                embed.set_thumbnail(url=guild.icon.url)
                return None, False
            except Exception as e:
                print(f"Error setting guild icon thumbnail: {e}")

    t_cfg = get_active_tournament_config(guild_id)
    if t_cfg and bot_client:
        thumb_chan_id = t_cfg.get('thumbnail')
        if thumb_chan_id:
            try:
                thumb_url = await get_thumbnail_url_from_channel(int(thumb_chan_id), bot_client)
                if thumb_url:
                    embed.set_thumbnail(url=thumb_url)
                    return None, False
            except Exception as e:
                print(f"Error resolving thumbnail from channel {thumb_chan_id}: {e}")

    default_logo = os.path.join(BASE_DIR, "tournament_bot_logo.png")
    if os.path.exists(default_logo):
        try:
            with open(default_logo, "rb") as f:
                logo_data = f.read()
            embed.set_thumbnail(url="attachment://tournament_bot_logo.png")
            file_obj = discord.File(fp=io.BytesIO(logo_data), filename="tournament_bot_logo.png")
            return file_obj, True
        except Exception:
            pass

    if fallback_to_captain_avatar and fallback_to_captain_avatar.avatar:
        embed.set_thumbnail(url=fallback_to_captain_avatar.avatar.url)
        return None, False

    return None, False

def extract_challonge_tournament_id(bracket_link: str) -> str:
    return extract_challonge_id(str(bracket_link))

async def update_challonge_match(bracket_link: str, api_key: str, match_id: str, winner_id: str, scores_csv: str) -> tuple[bool, Optional[str]]:
    import aiohttp
    tournament_id = extract_challonge_tournament_id(bracket_link)
    url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/matches/{match_id}.json"
    params = {
        "api_key": api_key,
        "match[winner_id]": winner_id,
        "match[scores_csv]": scores_csv
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.put(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    return True, None
                text = await resp.text()
                return False, f"Status {resp.status}: {text}"
    except Exception as e:
        return False, str(e)

async def get_challonge_matches(bracket_link: str, api_key: str) -> tuple[list, Optional[str]]:
    import aiohttp
    tournament_id = extract_challonge_tournament_id(bracket_link)
    url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/matches.json"
    params = {"api_key": api_key}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    matches = [m.get("match", {}) for m in data]
                    return matches, None
                text = await resp.text()
                return [], f"Status {resp.status}: {text}"
    except Exception as e:
        return [], str(e)

async def get_challonge_participants(bracket_link: str, api_key: str) -> tuple[dict, Optional[str]]:
    import aiohttp
    tournament_id = extract_challonge_tournament_id(bracket_link)
    url = f"https://api.challonge.com/v1/tournaments/{tournament_id}/participants.json"
    params = {"api_key": api_key}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    participants = {}
                    for p in data:
                        part = p.get("participant", {})
                        participants[str(part.get("id"))] = part.get("name") or part.get("display_name")
                    return participants, None
                text = await resp.text()
                return {}, f"Status {resp.status}: {text}"
    except Exception as e:
        return {}, str(e)

async def load_guild_configs_from_supabase():
    if not supabase_client:
        return
    try:
        resp = await asyncio.to_thread(lambda: supabase_client.table("GuildConfig").select("*").execute())
        if resp and resp.data:
            for row in resp.data:
                g_id = row.get("Guild_ID")
                if g_id:
                    load_guild_config(int(g_id) if str(g_id).isdigit() else g_id)
    except Exception as e:
        print(f"Error loading all guild configs from Supabase: {e}")

async def load_all_tournaments_from_supabase():
    if not supabase_client:
        return
    try:
        resp = await asyncio.to_thread(lambda: supabase_client.table("Tournaments").select("*").execute())
        if resp and resp.data:
            for row in resp.data:
                g_id = row.get("Guild_ID")
                if g_id:
                    load_guild_tournaments(int(g_id) if str(g_id).isdigit() else g_id)
    except Exception as e:
        print(f"Error loading all tournaments from Supabase: {e}")

async def load_all_staff_stats_from_supabase():
    if not supabase_client:
        return
    try:
        resp = await asyncio.to_thread(lambda: supabase_client.table("StaffStats").select("*").execute())
        if resp and resp.data:
            all_stats = {}
            if os.path.exists('staff_stats.json'):
                try:
                    with open('staff_stats.json', 'r', encoding='utf-8') as f:
                        all_stats = json.load(f)
                except Exception:
                    pass
            for row in resp.data:
                g_id = str(row.get("Guild_ID") or "")
                u_id = str(row.get("User_ID") or "")
                if not g_id or not u_id:
                    continue
                if g_id not in STAFF_STATS_CACHE:
                    STAFF_STATS_CACHE[g_id] = {}
                if g_id not in all_stats:
                    all_stats[g_id] = {}
                
                user_stat = {
                    "name": row.get("Name") or "Staff",
                    "judge_count": int(row.get("Judge_Count") or 0),
                    "recorder_count": int(row.get("Recorder_Count") or 0),
                    "judge_and_recorder_count": int(row.get("Judge_and_Record") or row.get("Judge_and_Recorder_Count") or 0),
                    "total_count": int(row.get("Total_Count") or 0),
                    "last_active": row.get("Timestamp") or datetime.datetime.utcnow().isoformat()
                }
                STAFF_STATS_CACHE[g_id][u_id] = user_stat
                all_stats[g_id][u_id] = user_stat

            try:
                with open('staff_stats.json', 'w', encoding='utf-8') as f:
                    json.dump(all_stats, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error saving staff_stats.json during Supabase load: {e}")
            print(f"✅ Loaded {len(resp.data)} staff stat entries from Supabase.")
    except Exception as e:
        print(f"Error loading all staff stats from Supabase: {e}")

async def tournament_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[discord.app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    try:
        tournaments = load_guild_tournaments(interaction.guild_id)
        choices = []
        for t_id, t_cfg in tournaments.items():
            if "(" in t_id and "[" in t_id:
                continue
            name = t_cfg.get("name") or t_id
            display = name.strip()
            if not current or current.lower() in display.lower() or current.lower() in t_id.lower():
                choices.append(discord.app_commands.Choice(name=display[:100], value=t_id[:100]))
        return choices[:25]
    except Exception as e:
        print(f"Error in tournament_autocomplete: {e}")
        return []

async def match_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[discord.app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    try:
        choices = []
        curr_clean = (current or "").strip().lower()
        for ev_id, ev_data in scheduled_events.items():
            if ev_data.get('guild_id') and str(ev_data.get('guild_id')) != str(interaction.guild_id):
                continue
            m_name = ev_data.get('match_name') or f"{ev_data.get('team1_name', 'Team 1')} vs {ev_data.get('team2_name', 'Team 2')}"
            t_name = ev_data.get('tournament', '')
            display = m_name
            if not curr_clean or curr_clean in display.lower() or curr_clean in ev_id.lower():
                choices.append(discord.app_commands.Choice(name=display[:100], value=ev_id[:100]))
        return choices[:25]
    except Exception as e:
        print(f"Error in match_autocomplete: {e}")
        return []

def format_links_markdown(raw_val: str, label_prefix: str = "Link") -> str:
    if not raw_val:
        return ""
    links = [l.strip() for l in str(raw_val).split(',') if l.strip()]
    if not links:
        return ""
    if len(links) == 1:
        return f"[Watch Here]({links[0]})"
    return ", ".join(f"[{label_prefix}{idx}]({url})" for idx, url in enumerate(links, start=1))

async def update_results_embed_with_links(guild: discord.Guild, ev_data: dict):
    if not guild or not ev_data:
        return
        
    res_msg_id = ev_data.get('results_message_id')
    res_chan_id = ev_data.get('results_channel_id')
    
    # 1. Auto-resolve results channel: tournament-specific channel takes priority
    channel = None
    t_id = ev_data.get('tournament') or ev_data.get('tournament_id')
    if t_id:
        try:
            channel = get_tournament_results_channel(guild, t_id)
        except Exception:
            channel = None

    if not channel and res_chan_id:
        try:
            channel = guild.get_channel(int(res_chan_id)) or await guild.fetch_channel(int(res_chan_id))
        except Exception:
            channel = None
            
    if not channel:
        cfg = get_guild_config(guild.id)
        candidate_chan_id = cfg.get('channel_ids', {}).get('results') or cfg.get('channel_ids', {}).get('result')
        if candidate_chan_id:
            try:
                channel = guild.get_channel(int(candidate_chan_id)) or await guild.fetch_channel(int(candidate_chan_id))
                if channel:
                    ev_data['results_channel_id'] = channel.id
            except Exception:
                channel = None

    if not channel:
        return

    msg = None
    if res_msg_id:
        try:
            msg = await channel.fetch_message(int(res_msg_id))
        except Exception:
            msg = None

    # If message not found by ID, search recent results messages for match
    if not msg:
        t1 = str(ev_data.get('team1_name') or '').lower()
        t2 = str(ev_data.get('team2_name') or '').lower()
        m_name = str(ev_data.get('match_name') or '').lower()
        try:
            async for history_msg in channel.history(limit=40):
                if history_msg.author == guild.me and history_msg.embeds:
                    em = history_msg.embeds[0]
                    content_to_check = f"{em.title or ''} {em.description or ''} " + " ".join(f.name + " " + f.value for f in em.fields)
                    c_lower = content_to_check.lower()
                    if (t1 and t2 and t1 in c_lower and t2 in c_lower) or (m_name and m_name in c_lower):
                        msg = history_msg
                        ev_data['results_message_id'] = msg.id
                        ev_data['results_channel_id'] = channel.id
                        break
        except Exception as search_err:
            print(f"Error searching results channel for match: {search_err}")

    if not msg or not msg.embeds:
        return

    try:
        from core.emojis import EMOJIS
    except Exception:
        EMOJIS = {}

    rec_emoji = EMOJIS.get('recorder', '📹')
    jdg_emoji = EMOJIS.get('judge', '⚖️')

    async def _apply_links_to_message(target_msg: discord.Message):
        if not target_msg or not target_msg.embeds:
            return
        embed = target_msg.embeds[0]
        general_link = ev_data.get('recording_link')
        rec_link = ev_data.get('recorder_link')
        jdg_link = ev_data.get('judge_link')
        
        link_lines = []
        if general_link:
            link_lines.append(f"{rec_emoji} **Recording:** {format_links_markdown(general_link, 'Link')}")
        if rec_link:
            link_lines.append(f"{rec_emoji} **Recorder VOD:** {format_links_markdown(rec_link, 'Link')}")
        if jdg_link:
            link_lines.append(f"{jdg_emoji} **Judge VOD:** {format_links_markdown(jdg_link, 'Link')}")
        
        # Filter out existing recording/VOD fields
        clean_fields = []
        remarks_field = None
        ss_field = None
        for f in embed.fields:
            if "Recording" in (f.name or "") or "VOD" in (f.name or "") or "Recordings / VODs" in (f.name or ""):
                continue
            if "Remarks" in (f.name or ""):
                remarks_field = f
                continue
            if "Screenshots" in (f.name or "") or "Screenshots of Result" in (f.value or ""):
                ss_field = f
                continue
            clean_fields.append(f)

        embed.clear_fields()
        for f in clean_fields:
            embed.add_field(name=f.name, value=f.value, inline=f.inline)

        # Place VOD links directly before Remarks, or before Screenshots
        if link_lines:
            vod_title = f"{rec_emoji} Recordings / VODs"
            embed.add_field(name=vod_title, value="\n".join(link_lines), inline=False)

        if remarks_field:
            embed.add_field(name=remarks_field.name, value=remarks_field.value, inline=remarks_field.inline)
        if ss_field:
            embed.add_field(name=ss_field.name, value=ss_field.value, inline=ss_field.inline)
            
        await target_msg.edit(embed=embed)

    try:
        await _apply_links_to_message(msg)
    except Exception as e:
        print(f"Error updating result embed with links: {e}")

    # Also update ticket channel message if saved
    ticket_msg_id = ev_data.get('ticket_results_message_id')
    ticket_chan_id = ev_data.get('channel_id')
    if ticket_msg_id and ticket_chan_id:
        try:
            t_chan = guild.get_channel(int(ticket_chan_id)) or await guild.fetch_channel(int(ticket_chan_id))
            if t_chan:
                t_msg = await t_chan.fetch_message(int(ticket_msg_id))
                if t_msg:
                    await _apply_links_to_message(t_msg)
        except Exception:
            pass


# ===========================================================================================
# BANNED PLAYERS DATABASE (SUPABASE + LOCAL JSON CACHE)
# ===========================================================================================

BANNED_PLAYERS_FILE = os.path.join(BASE_DIR, "banned_players.json")
BANNED_PLAYERS_CACHE: dict = {}

def load_banned_players() -> dict:
    global BANNED_PLAYERS_CACHE
    if os.path.exists(BANNED_PLAYERS_FILE):
        try:
            with open(BANNED_PLAYERS_FILE, "r", encoding="utf-8") as f:
                BANNED_PLAYERS_CACHE = json.load(f)
        except Exception as e:
            print(f"Error loading banned_players.json: {e}")
            BANNED_PLAYERS_CACHE = {}
    return BANNED_PLAYERS_CACHE

def save_banned_players(data: Optional[dict] = None):
    global BANNED_PLAYERS_CACHE
    if data is not None:
        BANNED_PLAYERS_CACHE = data
    try:
        with open(BANNED_PLAYERS_FILE, "w", encoding="utf-8") as f:
            json.dump(BANNED_PLAYERS_CACHE, f, indent=4)
    except Exception as e:
        print(f"Error saving banned_players.json: {e}")

async def load_banned_players_from_supabase():
    global BANNED_PLAYERS_CACHE
    load_banned_players()
    if not supabase_client:
        return BANNED_PLAYERS_CACHE
    try:
        resp = await asyncio.to_thread(lambda: supabase_client.table('banned_players').select('*').execute())
        if resp and resp.data:
            for row in resp.data:
                gid = str(row.get('game_id', '')).strip().lower()
                if gid:
                    BANNED_PLAYERS_CACHE[gid] = {
                        'game_id': str(row.get('game_id')),
                        'discord_user_id': row.get('discord_user_id'),
                        'discord_username': row.get('discord_username'),
                        'reason': row.get('reason', 'Tournament Ban'),
                        'banned_by': row.get('banned_by'),
                        'banned_at': row.get('banned_at'),
                        'guild_id': row.get('guild_id')
                    }
            save_banned_players()
            print(f"✅ Loaded {len(resp.data)} banned player(s) from Supabase.")
    except Exception as e:
        print(f"⚠️ Could not load banned players from Supabase: {e}")
    return BANNED_PLAYERS_CACHE

def get_banned_player(game_id: str) -> Optional[dict]:
    load_banned_players()
    gid = str(game_id).strip().lower()
    return BANNED_PLAYERS_CACHE.get(gid)

def is_game_id_banned(game_id: str) -> bool:
    return get_banned_player(game_id) is not None

async def add_banned_player(
    game_id: str,
    discord_user_id: Optional[int] = None,
    discord_username: Optional[str] = None,
    reason: Optional[str] = "Tournament Ban",
    banned_by: Optional[int] = None,
    guild_id: Optional[int] = None
) -> dict:
    load_banned_players()
    gid_clean = str(game_id).strip()
    gid_key = gid_clean.lower()
    now_iso = datetime.datetime.utcnow().isoformat()

    record = {
        'game_id': gid_clean,
        'discord_user_id': str(discord_user_id) if discord_user_id else None,
        'discord_username': str(discord_username) if discord_username else None,
        'reason': reason or "Tournament Ban",
        'banned_by': str(banned_by) if banned_by else None,
        'banned_at': now_iso,
        'guild_id': str(guild_id) if guild_id else None
    }
    BANNED_PLAYERS_CACHE[gid_key] = record
    save_banned_players()

    if supabase_client:
        def _sync_db():
            supabase_safe_upsert('banned_players', record, on_conflict='game_id')
        asyncio.create_task(asyncio.to_thread(_sync_db))

    return record

async def remove_banned_player(game_id: Optional[str] = None, discord_user_id: Optional[int] = None) -> Optional[dict]:
    load_banned_players()
    removed_record = None

    if game_id:
        gid_key = str(game_id).strip().lower()
        if gid_key in BANNED_PLAYERS_CACHE:
            removed_record = BANNED_PLAYERS_CACHE.pop(gid_key)

    if not removed_record and discord_user_id:
        d_id_str = str(discord_user_id)
        for k, v in list(BANNED_PLAYERS_CACHE.items()):
            if str(v.get('discord_user_id')) == d_id_str:
                removed_record = BANNED_PLAYERS_CACHE.pop(k)
                break

    if removed_record:
        save_banned_players()
        if supabase_client:
            def _sync_del():
                try:
                    if removed_record.get('game_id'):
                        supabase_client.table('banned_players').delete().eq('game_id', removed_record['game_id']).execute()
                    elif removed_record.get('discord_user_id'):
                        supabase_client.table('banned_players').delete().eq('discord_user_id', removed_record['discord_user_id']).execute()
                except Exception as del_err:
                    print(f"Error removing ban from Supabase: {del_err}")
            asyncio.create_task(asyncio.to_thread(_sync_del))

    return removed_record



