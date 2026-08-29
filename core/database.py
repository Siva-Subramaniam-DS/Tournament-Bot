import os
import io
import re
import csv
import json
import time
import asyncio
import datetime
from typing import Optional, Union, Any
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
    row = {
        "Guild_ID": str(guild_id),
        "Admin_Role_ID": str(cfg.get('role_ids', {}).get('head_organizer') or ""),
        "Organizer_Role_ID": str(cfg.get('role_ids', {}).get('organizer') or ""),
        "Helper_Role_ID": str(cfg.get('role_ids', {}).get('helper_team') or ""),
        "Judge_Role_ID": str(cfg.get('role_ids', {}).get('judge') or ""),
        "Recorder_Role_ID": str(cfg.get('role_ids', {}).get('recorder') or ""),
        "Staff_Role_ID": str(cfg.get('role_ids', {}).get('staff') or ""),
        "Players_Role_ID": str(cfg.get('role_ids', {}).get('players') or ""),
        "Organization_Name": str(cfg.get('organization_name', '')),
        "Tournament_System_Name": str(cfg.get('tournament_system_name', '')),
        "server_logo_path": str(cfg.get('server_logo_path', '') or ''),
        "server_logo_url": str(cfg.get('server_logo_url', '') or ''),
        "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        supabase_client.table("GuildConfig").upsert(row).execute()
        return True
    except Exception as e:
        safe_row = {
            "Guild_ID": str(guild_id),
            "Admin_Role_ID": str(cfg.get('role_ids', {}).get('head_organizer') or ""),
            "Organizer_Role_ID": str(cfg.get('role_ids', {}).get('organizer') or ""),
            "Helper_Role_ID": str(cfg.get('role_ids', {}).get('helper_team') or ""),
            "Judge_Role_ID": str(cfg.get('role_ids', {}).get('judge') or ""),
            "Recorder_Role_ID": str(cfg.get('role_ids', {}).get('recorder') or ""),
            "Staff_Role_ID": str(cfg.get('role_ids', {}).get('staff') or ""),
            "Players_Role_ID": str(cfg.get('role_ids', {}).get('players') or ""),
            "Organization_Name": str(cfg.get('organization_name', '')),
            "Tournament_System_Name": str(cfg.get('tournament_system_name', '')),
            "server_logo_path": str(cfg.get('server_logo_path', '') or ''),
            "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            supabase_client.table("GuildConfig").upsert(safe_row).execute()
            return True
        except Exception:
            return False

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

    row = {
        "Tournament_ID": str(tournament_id),
        "Guild_ID": str(guild_id),
        "Tournament_Name": _get_val('name', 'Tournament_Name') or str(tournament_id),
        "State": _get_val('state', 'State') or "pending",
        "Game": _get_val('game', 'Game'),
        "Key": _get_val('key', 'Key'),
        "Challonge_Bracket_Link": _get_val('challonge_bracket_link', 'Challonge_Bracket_Link', 'bracket'),
        "Google_Sheet_Link": _get_val('google_sheet_link', 'Google_Sheet_Link', 'captains_sheet_link', 'Captains_Sheet_Link', 'sheet_link'),
        "Attendance_Channel_ID": _get_val('attendance', 'attendance_channel', 'Attendance_Channel_ID'),
        "Transcript_Channel_ID": _get_val('transcript', 'transcript_channel', 'Transcript_Channel_ID'),
        "Schedule_Channel_ID": _get_val('schedule', 'schedule_channel', 'schedule_channel_id', 'Schedule_Channel_ID'),
        "Rules_Channel_ID": _get_val('rules', 'rules_channel', 'Rules_Channel_ID'),
        "Result_Channel_ID": _get_val('result', 'result_channel', 'Result_Channel_ID'),
        "Deadline_Channel_ID": _get_val('deadline', 'deadline_channel', 'Deadline_Channel_ID'),
        "Bot_Logs_Channel_ID": _get_val('bot_logs', 'Bot_Logs_Channel_ID'),
        "Challonge_Logs_Channel_ID": _get_val('challonge_logs', 'Challonge_Logs_Channel_ID'),
        "Closed_Ticket_Category_ID": _get_val('closed_ticket_1', 'Closed_Ticket_Category_ID'),
        "Open_Category_1_ID": _get_val('ticket_open_category_1', 'Open_Category_1_ID'),
        "Open_Category_2_ID": _get_val('ticket_open_category_2', 'Open_Category_2_ID'),
        "Open_Category_3_ID": _get_val('ticket_open_category_3', 'Open_Category_3_ID'),
        "Auto_Room_Creation": bool(auto_room_val),
        "Map_Pool": _get_val('map_pool', 'Map_Pool'),
        "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    for attempt in range(3):
        try:
            supabase_client.table("Tournaments").upsert(row, on_conflict="Tournament_ID").execute()
            return True
        except Exception as e:
            if attempt < 2:
                time.sleep(0.5)
            else:
                return False

async def save_tournament_to_supabase(guild_id: int, tournament_id: str, t_data: dict):
    if supabase_client:
        await asyncio.to_thread(_sync_save_tournament_to_supabase, guild_id, tournament_id, t_data)

def _sync_delete_tournament_from_supabase(guild_id: int, tournament_id: str):
    if not supabase_client:
        return False
    try:
        supabase_client.table("Tournaments").delete().eq("Tournament_ID", tournament_id).execute()
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

async def log_bot_activity(guild: discord.Guild, embed: discord.Embed, tournament: str = None):
    if not guild:
        return
    channel = None
    
    # 1. Check specified tournament bot_logs
    if tournament:
        from core.database import load_guild_tournaments
        tournaments = load_guild_tournaments(guild.id)
        clean_t = str(tournament).strip().lower()
        t_cfg = tournaments.get(clean_t)
        if not t_cfg:
            for tid, tdata in tournaments.items():
                if tdata.get('name', '').strip().lower() == clean_t:
                    t_cfg = tdata
                    break
        if t_cfg:
            for k in ['bot_logs', 'bot_logs_channel_id', 'Bot_Logs_Channel_ID', 'bot_log']:
                if t_cfg.get(k):
                    try:
                        channel = guild.get_channel(int(t_cfg[k]))
                        if not channel:
                            channel = await guild.fetch_channel(int(t_cfg[k]))
                        if channel: break
                    except Exception: pass

    # 2. Check active tournament bot_logs
    if not channel:
        t_cfg = get_active_tournament_config(guild.id)
        if t_cfg:
            for k in ['bot_logs', 'bot_logs_channel_id', 'Bot_Logs_Channel_ID', 'bot_log']:
                if t_cfg.get(k):
                    try:
                        channel = guild.get_channel(int(t_cfg[k]))
                        if not channel:
                            channel = await guild.fetch_channel(int(t_cfg[k]))
                        if channel: break
                    except Exception: pass

    # 3. Check any tournament configured in the guild with bot_logs
    if not channel:
        from core.database import load_guild_tournaments
        tournaments = load_guild_tournaments(guild.id)
        for _, tdata in tournaments.items():
            for k in ['bot_logs', 'bot_logs_channel_id', 'Bot_Logs_Channel_ID', 'bot_log']:
                if tdata.get(k):
                    try:
                        channel = guild.get_channel(int(tdata[k]))
                        if not channel:
                            channel = await guild.fetch_channel(int(tdata[k]))
                        if channel: break
                    except Exception: pass
            if channel: break

    # 4. Check global guild config bot_logs
    if not channel:
        cfg = get_guild_config(guild.id)
        for k in ['bot_logs', 'bot_logs_channel_id', 'Bot_Logs_Channel_ID', 'bot_log']:
            bid = cfg.get('channel_ids', {}).get(k) or cfg.get(k)
            if bid:
                try:
                    channel = guild.get_channel(int(bid))
                    if not channel:
                        channel = await guild.fetch_channel(int(bid))
                    if channel: break
                except Exception: pass

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
        return STAFF_STATS_CACHE[guild_id_str]
        
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

async def save_staff_stats_to_supabase(guild_id: int, user_id: str, user_name: str, judge_count: int, recorder_count: int):
    if not supabase_client:
        return
    try:
        total = int(judge_count) + int(recorder_count)
        row = {
            "Guild_ID": str(guild_id),
            "User_ID": str(user_id),
            "Name": str(user_name),
            "Judge_Count": int(judge_count),
            "Recorder_Count": int(recorder_count),
            "Total_Count": int(total),
            "Timestamp": datetime.datetime.utcnow().isoformat()
        }
        res = await asyncio.to_thread(
            lambda: supabase_client.table("StaffStats").select("id").eq("Guild_ID", str(guild_id)).eq("User_ID", str(user_id)).execute()
        )
        if res and res.data and len(res.data) > 0:
            rec_id = res.data[0]["id"]
            await asyncio.to_thread(
                lambda: supabase_client.table("StaffStats").update(row).eq("id", rec_id).execute()
            )
        else:
            await asyncio.to_thread(
                lambda: supabase_client.table("StaffStats").insert(row).execute()
            )
    except Exception as e:
        print(f"[Supabase] Error saving StaffStats: {e}")

def update_staff_stats(user: discord.Member, role_type: str):
    g_id = None
    if hasattr(user, 'guild') and user.guild:
        g_id = user.guild.id
    else:
        g_id = current_guild_id.get()
        
    if not g_id:
        return
        
    stats = get_guild_staff_stats(g_id)
    user_id = str(user.id)
    
    if user_id not in stats:
        stats[user_id] = {
            "name": user.display_name,
            "judge_count": 0,
            "recorder_count": 0,
            "total_count": 0
        }
    
    if role_type == "judge":
        stats[user_id]["judge_count"] = stats[user_id].get("judge_count", 0) + 1
    elif role_type == "recorder":
        stats[user_id]["recorder_count"] = stats[user_id].get("recorder_count", 0) + 1
        
    stats[user_id]["total_count"] = stats[user_id].get("judge_count", 0) + stats[user_id].get("recorder_count", 0)
    stats[user_id]["name"] = user.display_name
    stats[user_id]["last_active"] = datetime.datetime.utcnow().isoformat()
    
    save_guild_staff_stats(g_id, stats)

    asyncio.create_task(save_staff_stats_to_supabase(
        g_id, user_id, user.display_name,
        stats[user_id].get("judge_count", 0),
        stats[user_id].get("recorder_count", 0)
    ))

    asyncio.create_task(sheetdb_post("StaffStats", {
        "Guild_ID": str(g_id) if g_id else "",
        "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "User_ID": user_id,
        "Name": user.display_name,
        "Role_Updated": role_type,
        "Judge_Count": stats[user_id].get("judge_count", 0),
        "Recorder_Count": stats[user_id].get("recorder_count", 0),
        "Total_Count": stats[user_id].get("total_count", 0)
    }))



# ===========================================================================================
# SCHEDULED EVENTS & DEADLINES PERSISTENCE
# ===========================================================================================

def load_scheduled_events():
    global scheduled_events
    try:
        if os.path.exists('scheduled_events.json'):
            with open('scheduled_events.json', 'r') as f:
                data = json.load(f)
                for event_id, event_data in data.items():
                    if 'datetime' in event_data:
                        event_data['datetime'] = datetime.datetime.fromisoformat(event_data['datetime'])
                scheduled_events = data
                print(f"Loaded {len(scheduled_events)} scheduled events from file")
    except Exception as e:
        print(f"Error loading scheduled events: {e}")
        scheduled_events = {}

async def load_scheduled_events_from_supabase():
    if not supabase_client:
        return
        
    print("⏳ Loading scheduled events from Supabase...")
    try:
        res = await asyncio.to_thread(
            lambda: supabase_client.table("Matches").select("*").execute()
        )
        if res and res.data:

            loaded_count = 0
            for row in res.data:
                event_id = row.get("Match_ID") or row.get("Event_ID")
                if not event_id:
                    continue
                    
                date_str = row.get("Date") or ""
                utc_time_str = row.get("UTC_Time") or ""
                event_datetime = None
                
                if row.get("Scheduled_Time"):
                    try:
                        clean_time = row["Scheduled_Time"].replace('Z', '+00:00')
                        event_datetime = datetime.datetime.fromisoformat(clean_time)
                        utc_time_str = event_datetime.strftime("%H:%M UTC")
                        date_str = event_datetime.strftime("%d/%m")
                    except Exception:
                        pass
                        
                if not event_datetime and date_str and utc_time_str:
                    try:
                        day, month = map(int, date_str.split('/'))
                        time_part = utc_time_str.split(' ')[0]
                        hour, minute = map(int, time_part.split(':'))
                        current_year = datetime.datetime.now().year
                        event_datetime = datetime.datetime(current_year, month, day, hour, minute)
                    except Exception:
                        pass
                
                if not event_datetime:
                    event_datetime = datetime.datetime.now()
                
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
                        'recorder': None,
                        'channel_id': parse_int_safe(row.get("Channel_ID")),
                        'team1_captain': t1_id,
                        'team2_captain': t2_id,
                        'team1_name': row.get('Team1_Captain_Name') or row.get('Team1_Name'),
                        'team2_name': row.get('Team2_Captain_Name') or row.get('Team2_Name'),
                        'match_name': row.get('Match_Name') or f"{row.get('Team1_Captain_Name', '')} vs {row.get('Team2_Captain_Name', '')}",
                    }
                    loaded_count += 1
                else:
                    existing = scheduled_events[event_id]
                    if event_datetime and existing.get('datetime') != event_datetime:
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

def save_scheduled_events():
    try:
        data_to_save = {}
        for event_id, event_data in scheduled_events.items():
            data_to_save[event_id] = _json_serialize_clean(event_data)
        
        with open('scheduled_events.json', 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=2, ensure_ascii=False)

        if supabase_client:
            try:
                loop = asyncio.get_running_loop()
                async def _throttled_save_all_events():
                    for ev_id, ev_data in list(scheduled_events.items()):
                        try:
                            await save_event_to_supabase(ev_id, ev_data)
                        except Exception as _e:
                            print(f"[Supabase] Error saving event {ev_id}: {_e}")
                        await asyncio.sleep(0.3)
                loop.create_task(_throttled_save_all_events())
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
        
        if guild_id:
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
                if resolved_t_id:
                    _sync_save_tournament_to_supabase(int(guild_id), resolved_t_id, tournaments[resolved_t_id])
            except Exception as tourney_sync_err:
                print(f"[Supabase] Note on tournament pre-sync: {tourney_sync_err}")

        if not resolved_t_id:
            resolved_t_id = str(raw_tourney).strip()

        round_raw = event_data.get('round', '')
        round_int = 1
        if isinstance(round_raw, int):
            round_int = round_raw
        elif str(round_raw).isdigit():
            round_int = int(round_raw)
        else:
            r_str = str(round_raw).lower()
            if 'semi' in r_str: round_int = 98
            elif 'final' in r_str: round_int = 99
            elif '3rd' in r_str or 'third' in r_str: round_int = 97
            elif 'qual' in r_str: round_int = 0
            else:
                m = re.search(r'\d+', r_str)
                round_int = int(m.group(0)) if m else 1

        rec_link = str(event_data.get('recording_link', '') or '')
        gen_vod = event_data.get('link1') or (rec_link.split('\n')[0] if rec_link else '')

        match_row = {
            "Match_ID": str(event_id),
            "Match_Name": str(match_name),
            "Tournament_ID": str(resolved_t_id),
            "Round": round_int,
            "Group": str(event_data.get('group', '') or ''),
            "Status": str(event_data.get('status', 'scheduled')).lower(),
            "Channel_ID": str(event_data.get('channel_id', '') or ''),
            "recording_link": rec_link,
            "General_VOD": str(gen_vod or ''),
            "Recorder_VOD": str(event_data.get('recorder_link', '') or ''),
            "Judge_VOD": str(event_data.get('judge_link', '') or ''),
            "recorder_link": str(event_data.get('recorder_link', '') or ''),
            "judge_link": str(event_data.get('judge_link', '') or ''),
            "results_message_id": str(event_data.get('results_message_id', '') or ''),
            "results_channel_id": str(event_data.get('results_channel_id', '') or ''),
            "match_results_message_id": str(event_data.get('match_results_message_id', '') or ''),
            "match_results_channel_id": str(event_data.get('match_results_channel_id', '') or ''),
            "Remarks": str(event_data.get('remarks', '') or ''),
            "Updated_At": datetime.datetime.utcnow().isoformat()
        }
        if t1_id: match_row["Team1_ID"] = str(t1_id)
        if t2_id: match_row["Team2_ID"] = str(t2_id)
        if event_data.get('winner_score') is not None:
            try: match_row["Team1_Score"] = int(event_data['winner_score'])
            except: pass
        if event_data.get('loser_score') is not None:
            try: match_row["Team2_Score"] = int(event_data['loser_score'])
            except: pass

        await asyncio.to_thread(
            lambda: supabase_client.table("Matches").upsert(match_row, on_conflict="Match_ID").execute()
        )
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

def load_scheduled_deadlines():
    global scheduled_deadlines
    try:
        if os.path.exists('scheduled_deadlines.json'):
            with open('scheduled_deadlines.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                for dl_id, dl_data in data.items():
                    if 'deadline_dt' in dl_data:
                        dl_data['deadline_dt'] = datetime.datetime.fromisoformat(dl_data['deadline_dt'])
                scheduled_deadlines = data
                print(f"Loaded {len(scheduled_deadlines)} scheduled deadlines from local fallback")
    except Exception as e:
        print(f"Error loading scheduled_deadlines.json fallback: {e}")
        scheduled_deadlines = {}

    if supabase_client:
        try:
            resp = supabase_client.table("Deadlines").select("*").execute()
            if resp.data:
                for row in resp.data:
                    try:
                        g_id = int(row["Guild_ID"])
                        rnd = row["Round"]
                        dl_id = f"dl_{rnd.lower().replace('-', '_').replace(' ', '_')}_{g_id}"
                        scheduled_deadlines[dl_id] = {
                            'guild_id': g_id,
                            'round': rnd,
                            'deadline_dt': datetime.datetime.fromisoformat(row["Deadline_Time"])
                        }
                    except Exception as parse_err:
                        print(f"Error parsing Supabase deadline row {row}: {parse_err}")
                print(f"Merged config with {len(resp.data)} deadlines from Supabase.")
        except Exception as e:
            print(f"Error loading deadlines from Supabase: {e}")

def save_scheduled_deadline(dl_id: str, dl_data: dict):
    scheduled_deadlines[dl_id] = dl_data
    try:
        data_to_save = {}
        for d_id, d_data in scheduled_deadlines.items():
            copy_data = d_data.copy()
            if 'deadline_dt' in copy_data and isinstance(copy_data['deadline_dt'], datetime.datetime):
                copy_data['deadline_dt'] = copy_data['deadline_dt'].isoformat()
            data_to_save[d_id] = copy_data
        with open('scheduled_deadlines.json', 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e:
        print(f"Error saving scheduled_deadlines.json: {e}")

    if supabase_client:
        try:
            row = {
                "Guild_ID": str(dl_data['guild_id']),
                "Round": dl_data['round'],
                "Deadline_Time": dl_data['deadline_dt'].isoformat()
            }
            supabase_client.table("Deadlines").upsert(row).execute()
        except Exception as e:
            print(f"[Supabase] Failed to upsert deadline to Supabase: {e}")


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

def _sync_fetch_google_sheet_captains(sheet_link: str):
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if not match:
        return None, "Invalid Google Sheet link — could not extract sheet ID"
    sheet_id = match.group(1)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        reader = csv.reader(io.StringIO(resp.text))
        
        h_row = next(reader, [])
        h_lower = [h.lower() for h in h_row]
        
        key_col = -1
        is_1v1 = False
        for i, h in enumerate(h_lower):
            if 'discord name' in h or 'participant' in h:
                key_col = i
                is_1v1 = True
                break
            elif 'team' in h:
                key_col = i
                is_1v1 = False
                break
                
        val_col = -1
        for i, h in enumerate(h_lower):
            if i != key_col:
                if any(x in h for x in ['developer id', 'developers id', 'developers i\'d', 'discord id', 'discord_id', 'mention', 'uid', 'id']) and not any(x in h for x in ['username', 'user name', 'display name']):
                    val_col = i
                    break
        if val_col == -1:
            for i, h in enumerate(h_lower):
                if i != key_col:
                    if 'discord' in h:
                        val_col = i
                        break
                
        if key_col == -1: key_col = 0
        if val_col == -1: val_col = 1
        
        captains = {}
        for row in reader:
            if len(row) > max(key_col, val_col):
                k = row[key_col].strip()
                v = row[val_col].strip()
                if k:
                    if v.isdigit():
                        v = f"<@{v}>"
                    captains[k] = v
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
    link = str(bracket_link).strip()
    if "/" in link:
        parts = [p for p in link.split("/") if p]
        return parts[-1]
    return link

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
            for row in resp.data:
                g_id = row.get("Guild_ID")
                if g_id:
                    get_guild_staff_stats(int(g_id) if str(g_id).isdigit() else g_id)
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
            name = t_cfg.get("name") or t_id
            state = t_cfg.get("state", "pending")
            display = f"{name} ({t_id}) [{state}]"
            if not current or current.lower() in display.lower() or current.lower() in name.lower() or current.lower() in t_id.lower():
                choices.append(discord.app_commands.Choice(name=display[:100], value=name[:100]))
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
            display = f"{m_name} [{ev_id}]"
            if t_name:
                display += f" ({t_name})"
            if not curr_clean or curr_clean in display.lower() or curr_clean in ev_id.lower():
                choices.append(discord.app_commands.Choice(name=display[:100], value=ev_id[:100]))
        return choices[:25]
    except Exception as e:
        print(f"Error in match_autocomplete: {e}")
        return []

async def update_results_embed_with_links(guild: discord.Guild, ev_data: dict):
    res_msg_id = ev_data.get('results_message_id')
    res_chan_id = ev_data.get('results_channel_id')
    if not res_msg_id or not res_chan_id or not guild:
        return
    try:
        channel = guild.get_channel(int(res_chan_id))
        if not channel:
            channel = await guild.fetch_channel(int(res_chan_id))
        msg = await channel.fetch_message(int(res_msg_id))
        if not msg or not msg.embeds:
            return
        
        embed = msg.embeds[0]
        
        links_list = []
        if isinstance(ev_data.get('links'), list):
            links_list = [str(l).strip() for l in ev_data.get('links') if l and str(l).strip()]
        if not links_list:
            for i in range(1, 6):
                lk = ev_data.get(f'link{i}') or ev_data.get(f'link_{i}')
                if lk and str(lk).strip():
                    links_list.append(str(lk).strip())
        if not links_list and ev_data.get('recording_link'):
            links_list = [l.strip() for l in str(ev_data.get('recording_link')).split('\n') if l.strip()]

        rec_link = ev_data.get('recorder_link')
        jdg_link = ev_data.get('judge_link')
        
        link_lines = []
        if len(links_list) == 1:
            link_lines.append(f"🎥 **Recording / VOD:** [Watch Here]({links_list[0]})")
        elif len(links_list) > 1:
            for idx, lk in enumerate(links_list, 1):
                link_lines.append(f"🎥 **Recording {idx}:** [Watch Part {idx}]({lk})")

        if rec_link and rec_link not in links_list:
            link_lines.append(f"📹 **Recorder VOD:** [Watch Here]({rec_link})")
        if jdg_link and jdg_link not in links_list:
            link_lines.append(f"⚖️ **Judge VOD:** [Watch Here]({jdg_link})")
        
        fields = [f for f in embed.fields if f.name not in ("🎥 Recording Link", "🎥 Recordings / VODs", "🎥 Recording / VOD")]
        embed.clear_fields()
        for f in fields:
            embed.add_field(name=f.name, value=f.value, inline=f.inline)
            
        if link_lines:
            embed.add_field(name="🎥 Recordings / VODs", value="\n".join(link_lines), inline=False)
            
        await msg.edit(embed=embed)
    except Exception as e:
        print(f"Error updating result embed with links: {e}")





