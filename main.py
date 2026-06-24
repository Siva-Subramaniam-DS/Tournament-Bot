import discord
from discord import app_commands
from discord.ext import commands
import os
import random
from dotenv import load_dotenv
from itertools import combinations
from typing import Optional
import re
import datetime
import asyncio
import glob
from discord.ui import Button, View
import pytz
from PIL import Image, ImageDraw, ImageFont
# Removed pilmoji import due to dependency issues
import io
import json
from pathlib import Path
import requests
import tempfile
import supabase
from supabase import create_client, Client

# Load environment variables
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Supabase Setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client: Optional[Client] = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Supabase client initialized successfully.")
    except Exception as e:
        print(f"Supabase client initialization failed: {e}")
else:
    print("Supabase URL or Key not found in environment. Supabase logging is disabled.")

# Default Configs — Multi-Server Configuration Defaults
DEFAULT_CHANNEL_IDS = {
    "rules":        None,    # Rules
    "bracket":      None,    # Bracket
    "deadlines":    None,    # Deadlines
    "staff_attendance": None, # Attendance
    "take_schedule": None,   # Schedule Channel
    "results":      None,    # Result
    "category_1":   None,    # Category 1
    "category_2":   None,    # Category 2
    "closed_tickets_category": None,  # Closed Tickets
    "challonge_logs": None,  # Challonge Logs Channel
    "transcript_logs": None, # Transcript Logs Channel
    "bot_logs":     None,    # Bot Logs Channel
    "thumbnail":    None     # Thumbnail Channel
}

DEFAULT_ROLE_IDS = {
    "head_organizer": None,  # Admin Role
    "organizer":      None,  # Organizer Role
    "helper_team":    None,  # Helper Role
    "judge":          None,  # Judge Role
    "recorder":       None,  # Recorder Role
    "staff":          None,  # Staff Role
    "players":        None,  # Players Role
    "challonge_role": None   # Challonge Role (legacy)
}

# ContextVar to hold current guild ID
import contextvars
current_guild_id = contextvars.ContextVar("current_guild_id", default=None)

import functools
def with_guild_context(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        interaction = None
        for arg in args:
            if isinstance(arg, discord.Interaction):
                interaction = arg
                break
            elif isinstance(arg, discord.Message):
                if arg.guild:
                    current_guild_id.set(arg.guild.id)
                break
        if interaction and interaction.guild:
            current_guild_id.set(interaction.guild.id)
        return await func(*args, **kwargs)
    return wrapper

# Cache for configurations, rules, and staff stats
GUILD_CONFIG_CACHE = {}
RULES_CACHE = {}
STAFF_STATS_CACHE = {}
CHALLONGE_MATCHES_CACHE = {}

def get_default_config():
    return {
        'channel_ids': DEFAULT_CHANNEL_IDS.copy(),
        'role_ids': DEFAULT_ROLE_IDS.copy(),
        'organization_name': "",
        'tournament_system_name': "",
        'google_sheet_link': "",
        'current_tournament_name': "",
        'player_info_link': "",
        'player_info_format': "5 vs 5"
    }

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
                    print(f"Loaded config for guild {guild_id} from guild_configs.json")
        except Exception as e:
            print(f"Error loading guild_configs.json: {e}")
            
    # 2. Overlay with Supabase
    if supabase_client:
        try:
            resp = supabase_client.table("GuildConfig").select("*").eq("Guild_ID", guild_id_str).execute()
            if resp.data and len(resp.data) > 0:
                db_data = resp.data[0]
                
                # Load roles (only overlay if present in DB)
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
                            
                # Load channels (only overlay if present in DB)
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
                            
                # Branding and settings (only overlay if not empty in DB)
                for key in ['organization_name', 'tournament_system_name', 'google_sheet_link', 'player_info_link', 'player_info_format']:
                    db_val = db_data.get(key)
                    if db_val not in (None, "", "None"):
                        config[key] = db_val
                        
                print(f"Merged config for guild {guild_id} with Supabase data.")
        except Exception as e:
            print(f"Error merging config from Supabase: {e}")
            
    GUILD_CONFIG_CACHE[guild_id_str] = config
    return config

def save_guild_config(guild_id: int, config: dict):
    guild_id_str = str(guild_id)
    GUILD_CONFIG_CACHE[guild_id_str] = config
    
    # Save locally to JSON fallback
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
        print(f"Saved config for guild {guild_id} to guild_configs.json")
    except Exception as e:
        print(f"Error saving config to guild_configs.json: {e}")
            
    # Sync config to Supabase in the background (SheetDB is removed)
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
        guild_id = int(context)
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

class GuildDictProxy(dict):
    def __init__(self, default_dict, config_key):
        super().__init__(default_dict)
        self.default_dict = default_dict
        self.config_key = config_key

    def _get_current_dict(self):
        g_id = current_guild_id.get()
        if g_id:
            if self.config_key == "channel_ids":
                t_cfg = get_active_tournament_config(g_id)
                cfg = get_guild_config(g_id)
                global_chans = cfg.get("channel_ids", {})
                combined = self.default_dict.copy()
                combined.update({k: v for k, v in global_chans.items() if v})
                
                if t_cfg:
                    tourney_chans = {
                        'thumbnail': t_cfg.get('thumbnail'),
                        'rules': t_cfg.get('rules'),
                        'bracket': t_cfg.get('bracket') or t_cfg.get('challonge_bracket_link'),
                        'deadlines': t_cfg.get('deadline'),
                        'staff_attendance': t_cfg.get('attendance'),
                        'take_schedule': t_cfg.get('schedule'),
                        'results': t_cfg.get('result'),
                        'challonge_logs': t_cfg.get('challonge_logs'),
                        'transcript_logs': t_cfg.get('transcript_logs'),
                        'bot_logs': t_cfg.get('bot_logs'),
                        'closed_tickets_category': t_cfg.get('closed_ticket_1'),
                        'close_ticket_category_2_id': t_cfg.get('closed_ticket_2'),
                        'category_1': t_cfg.get('ticket_open_category_1'),
                        'category_2': t_cfg.get('ticket_open_category_2'),
                        'category_3': t_cfg.get('ticket_open_category_3'),
                        'participant': t_cfg.get('participant'),
                        'transcript': t_cfg.get('transcript')
                    }
                    combined.update({k: v for k, v in tourney_chans.items() if v is not None})
                return combined
            
            cfg = get_guild_config(g_id)
            return cfg.get(self.config_key, self.default_dict)
        return self.default_dict

    def _coerce(self, val):
        if val is not None and self.config_key in ("role_ids", "channel_ids"):
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return val

    def __getitem__(self, key):
        return self._coerce(self._get_current_dict().get(key, self.default_dict.get(key)))

    def get(self, key, default=None):
        return self._coerce(self._get_current_dict().get(key, self.default_dict.get(key, default)))

    def __contains__(self, key):
        return key in self._get_current_dict() or key in self.default_dict

    def items(self):
        return [(k, self._coerce(v)) for k, v in self._get_current_dict().items()]

    def keys(self):
        return self._get_current_dict().keys()

    def values(self):
        return [self._coerce(v) for v in self._get_current_dict().values()]

    def update(self, other):
        self.default_dict.update(other)

CHANNEL_IDS = GuildDictProxy(DEFAULT_CHANNEL_IDS, "channel_ids")
ROLE_IDS = GuildDictProxy(DEFAULT_ROLE_IDS, "role_ids")

# Bot Owner ID for special permissions
BOT_OWNER_ID = 1251442077561131059

# Legacy loads for global scope variables
class DynamicString:
    def __init__(self, func):
        self.func = func
    def __str__(self):
        return self.func()
    def __repr__(self):
        return self.func()
    def __add__(self, other):
        return str(self) + str(other)
    def __radd__(self, other):
        return str(other) + str(self)
    def __eq__(self, other):
        return str(self) == str(other)
    def __bool__(self):
        return bool(str(self))
    def __len__(self):
        return len(str(self))
    def __hash__(self):
        return hash(str(self))
    def __getattr__(self, name):
        return getattr(str(self), name)

# SheetDB API endpoint
def get_sheetdb_api_url(context=None) -> str:
    url = get_guild_config(context).get("sheetdb_api_url", "")
    return url if url else "https://sheetdb.io/api/v1/vlbn6vbc8vdbb"

SHEETDB_API_URL = DynamicString(lambda: get_sheetdb_api_url())

# Default brand colour (deep navy blue)
BRAND_COLOR = 0x1E3A5F

ORGANIZATION_NAME = DynamicString(lambda: get_org_name())
TOURNAMENT_SYSTEM_NAME = DynamicString(lambda: get_system_name())
BRACKET_LINK = DynamicString(lambda: get_bracket_link())
BRACKET_API_KEY = DynamicString(lambda: get_bracket_api_key())
GOOGLE_SHEET_LINK = DynamicString(lambda: get_google_sheet_link())
CURRENT_TOURNAMENT_NAME = DynamicString(lambda: get_tournament_name())
PLAYER_INFO_LINK = DynamicString(lambda: get_player_info_link())
PLAYER_INFO_FORMAT = DynamicString(lambda: get_player_info_format())

def get_org_name(context=None) -> str:
    return get_guild_config(context).get("organization_name", "Tournament Organizer")

def get_system_name(context=None) -> str:
    return get_guild_config(context).get("tournament_system_name", "Tournament System")

def get_bracket_link(context=None) -> str:
    g_id = None
    if context and hasattr(context, "guild") and context.guild:
        g_id = context.guild.id
    elif isinstance(context, discord.Guild):
        g_id = context.id
    elif isinstance(context, int):
        g_id = context
    else:
        g_id = current_guild_id.get()
        
    if g_id:
        t_cfg = get_active_tournament_config(g_id)
        if t_cfg:
            return t_cfg.get("challonge_bracket_link") or t_cfg.get("id") or ""
    return ""

def get_bracket_api_key(context=None) -> str:
    g_id = None
    if context and hasattr(context, "guild") and context.guild:
        g_id = context.guild.id
    elif isinstance(context, discord.Guild):
        g_id = context.id
    elif isinstance(context, int):
        g_id = context
    else:
        g_id = current_guild_id.get()
        
    if g_id:
        t_cfg = get_active_tournament_config(g_id)
        if t_cfg and t_cfg.get("key"):
            return t_cfg.get("key")
    return ""

def get_google_sheet_link(context=None) -> str:
    return get_guild_config(context).get("google_sheet_link", "")

def get_tournament_name(context=None) -> str:
    guild_id = None
    if context:
        if isinstance(context, int):
            guild_id = context
        elif hasattr(context, "guild") and context.guild:
            guild_id = context.guild.id
        elif isinstance(context, discord.Guild):
            guild_id = context.id
    if not guild_id:
        guild_id = current_guild_id.get()
    
    if guild_id:
        t_cfg = get_active_tournament_config(guild_id)
        if t_cfg and t_cfg.get('name'):
            return t_cfg.get('name')
            
    return get_guild_config(context).get("current_tournament_name", "")

def get_player_info_link(context=None) -> str:
    return get_guild_config(context).get("player_info_link", "")

def get_player_info_format(context=None) -> str:
    return get_guild_config(context).get("player_info_format", "5 vs 5")

def get_link_bracket(context=None) -> str:
    cfg = get_guild_config(context)
    g_id = 1500186736633053184
    if context and hasattr(context, "guild") and context.guild:
        g_id = context.guild.id
    elif isinstance(context, discord.Guild):
        g_id = context.id
    return f"https://discord.com/channels/{g_id}/{cfg['channel_ids'].get('bracket', DEFAULT_CHANNEL_IDS['bracket'])}"

def get_link_deadline(context=None) -> str:
    cfg = get_guild_config(context)
    g_id = 1500186736633053184
    if context and hasattr(context, "guild") and context.guild:
        g_id = context.guild.id
    elif isinstance(context, discord.Guild):
        g_id = context.id
    return f"https://discord.com/channels/{g_id}/{cfg['channel_ids'].get('deadlines', DEFAULT_CHANNEL_IDS['deadlines'])}"

def get_link_rules(context=None) -> str:
    cfg = get_guild_config(context)
    g_id = 1500186736633053184
    if context and hasattr(context, "guild") and context.guild:
        g_id = context.guild.id
    elif isinstance(context, discord.Guild):
        g_id = context.id
    return f"https://discord.com/channels/{g_id}/{cfg['channel_ids'].get('rules', DEFAULT_CHANNEL_IDS['rules'])}"

# Dummy/Legacy wrappers for backwards-compatibility
def load_config():
    pass

def save_config():
    pass

# Set Windows event loop policy for asyncio
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.guild_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

@tree.interaction_check
async def global_interaction_check(interaction: discord.Interaction) -> bool:
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)
    return True

class GuildStatsProxy(dict):
    def _get_current_dict(self):
        g_id = current_guild_id.get()
        if g_id:
            return get_guild_staff_stats(g_id)
        return {}

    def __getitem__(self, key):
        return self._get_current_dict().__getitem__(key)

    def get(self, key, default=None):
        return self._get_current_dict().get(key, default)

    def __contains__(self, key):
        return key in self._get_current_dict()

    def items(self):
        return self._get_current_dict().items()

    def keys(self):
        return self._get_current_dict().keys()

    def values(self):
        return self._get_current_dict().values()
        
    def __setitem__(self, key, value):
        g_id = current_guild_id.get()
        if g_id:
            stats = get_guild_staff_stats(g_id)
            stats[key] = value
            save_guild_staff_stats(g_id, stats)

    def __delitem__(self, key):
        g_id = current_guild_id.get()
        if g_id:
            stats = get_guild_staff_stats(g_id)
            if key in stats:
                del stats[key]
                save_guild_staff_stats(g_id, stats)

    def __bool__(self):
        return bool(self._get_current_dict())

class GuildRulesProxy(dict):
    def _get_current_dict(self):
        g_id = current_guild_id.get()
        if g_id:
            return get_guild_rules(g_id)
        return {}

    def __getitem__(self, key):
        return self._get_current_dict().__getitem__(key)

    def get(self, key, default=None):
        return self._get_current_dict().get(key, default)

    def __contains__(self, key):
        return key in self._get_current_dict()

    def items(self):
        return self._get_current_dict().items()

    def keys(self):
        return self._get_current_dict().keys()

    def values(self):
        return self._get_current_dict().values()
        
    def __setitem__(self, key, value):
        g_id = current_guild_id.get()
        if g_id:
            rules = get_guild_rules(g_id)
            rules[key] = value
            save_guild_rules(g_id, rules)

    def __delitem__(self, key):
        g_id = current_guild_id.get()
        if g_id:
            rules = get_guild_rules(g_id)
            if key in rules:
                del rules[key]
                save_guild_rules(g_id, rules)

    def __bool__(self):
        return bool(self._get_current_dict())

# Store scheduled events for reminders
scheduled_events = {}

# Store staff statistics for leaderboard
staff_stats = GuildStatsProxy()


# Load scheduled events from file on startup
def load_scheduled_events():
    global scheduled_events
    try:
        if os.path.exists('scheduled_events.json'):
            with open('scheduled_events.json', 'r') as f:
                data = json.load(f)
                # Convert datetime strings back to datetime objects
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
            lambda: supabase_client.table("Events").select("*").execute()
        )
        if res.data:
            loaded_count = 0
            for row in res.data:
                event_id = row.get("Event_ID")
                if not event_id:
                    continue
                    
                # Reconstruct datetime
                date_str = row.get("Date") or ""
                utc_time_str = row.get("UTC_Time") or ""
                event_datetime = None
                if date_str and utc_time_str:
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
                
                # Extract integer IDs
                def parse_int_safe(val):
                    if not val:
                        return None
                    try:
                        return int(val)
                    except ValueError:
                        return None
                        
                g_id = parse_int_safe(row.get("Guild_ID"))
                t1_id = parse_int_safe(row.get("Team1_Captain_ID"))
                t2_id = parse_int_safe(row.get("Team2_Captain_ID"))
                j_id = parse_int_safe(row.get("Judge_ID"))
                
                # If this event already exists in scheduled_events
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
                        'tournament': row.get('Tournament'),
                        'mode': None,
                        'judge': j_id,
                        'recorder': None,
                        'channel_id': parse_int_safe(row.get("Channel_ID")),
                        'team1_captain': t1_id,
                        'team2_captain': t2_id,
                        'team1_name': row.get('Team1_Captain_Name'),
                        'team2_name': row.get('Team2_Captain_Name')
                    }
                    loaded_count += 1
                else:
                    # Sync fields from database if they are newer/assigned
                    existing = scheduled_events[event_id]
                    if j_id and not existing.get('judge'):
                        existing['judge'] = j_id
                    
            print(f"✅ Loaded {loaded_count} scheduled event(s) from Supabase.")
    except Exception as e:
        print(f"❌ Error loading scheduled events from Supabase: {e}")

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
        
        row = {
            "Guild_ID": str(guild_id) if guild_id else "",
            "Event_ID": event_id,
            "Tournament": event_data.get('tournament', ''),
            "Round": event_data.get('round', ''),
            "Group": event_data.get('group', '') or '',
            "Date": event_data.get('date_str', ''),
            "UTC_Time": event_data.get('time_str', ''),
            "Team1_Captain_ID": str(t1_id) if t1_id else '',
            "Team1_Captain_Name": event_data.get('team1_name') or (t1_cap.name if hasattr(t1_cap, 'name') else ''),
            "Team2_Captain_ID": str(t2_id) if t2_id else '',
            "Team2_Captain_Name": event_data.get('team2_name') or (t2_cap.name if hasattr(t2_cap, 'name') else ''),
            "Judge_ID": str(j_id) if j_id else '',
            "Judge_Name": judge_val.name if hasattr(judge_val, 'name') else '',
            "Channel_ID": str(event_data.get('channel_id', '')),
            "Status": "Scheduled"
        }
        
        res = await asyncio.to_thread(
            lambda: supabase_client.table("Events").select("id").eq("Event_ID", event_id).execute()
        )
        if res.data and len(res.data) > 0:
            row_id = res.data[0]["id"]
            await asyncio.to_thread(
                lambda: supabase_client.table("Events").update(row).eq("id", row_id).execute()
            )
        else:
            row["Timestamp"] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            await asyncio.to_thread(
                lambda: supabase_client.table("Events").insert(row).execute()
            )
    except Exception as e:
        print(f"[Supabase] Error saving event {event_id} to database: {e}")

async def resolve_scheduled_event_members():
    """Resolves member IDs in scheduled_events back to discord.Member/discord.User objects on startup."""
    print("⏳ Resolving member IDs in scheduled events...")
    resolved_count = 0
    for ev_id, ev_data in scheduled_events.items():
        g_id = ev_data.get('guild_id')
        if not g_id:
            continue
        guild = bot.get_guild(g_id)
        if not guild:
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

# Save scheduled events to file
def save_scheduled_events():
    try:
        # Convert datetime objects to strings for JSON serialization
        data_to_save = {}
        for event_id, event_data in scheduled_events.items():
            event_copy = event_data.copy()
            if 'datetime' in event_copy:
                event_copy['datetime'] = event_copy['datetime'].isoformat()
            
            # Convert Discord Member objects to IDs for JSON serialization
            if 'team1_captain' in event_copy and hasattr(event_copy['team1_captain'], 'id'):
                event_copy['team1_captain'] = event_copy['team1_captain'].id
            if 'team2_captain' in event_copy and hasattr(event_copy['team2_captain'], 'id'):
                event_copy['team2_captain'] = event_copy['team2_captain'].id
            if 'judge' in event_copy and hasattr(event_copy['judge'], 'id'):
                event_copy['judge'] = event_copy['judge'].id
            elif 'judge' in event_copy and event_copy['judge'] is None:
                event_copy['judge'] = None

            if 'recorder' in event_copy and hasattr(event_copy['recorder'], 'id'):
                event_copy['recorder'] = event_copy['recorder'].id
            elif 'recorder' in event_copy and event_copy['recorder'] is None:
                event_copy['recorder'] = None
                
            data_to_save[event_id] = event_copy
        
        with open('scheduled_events.json', 'w') as f:
            json.dump(data_to_save, f, indent=2)

        # Sync with Supabase asynchronously in the background
        # Use a single throttled task instead of blasting all events at once,
        # which caused SSL/EOF errors from too many simultaneous connections.
        if supabase_client:
            try:
                loop = asyncio.get_running_loop()
                async def _throttled_save_all_events():
                    for ev_id, ev_data in list(scheduled_events.items()):
                        try:
                            await save_event_to_supabase(ev_id, ev_data)
                        except Exception as _e:
                            print(f"[Supabase] Error saving event {ev_id}: {_e}")
                        await asyncio.sleep(0.3)  # 300ms gap between each save
                loop.create_task(_throttled_save_all_events())
            except RuntimeError:
                pass
    except Exception as e:
        print(f"Error saving scheduled events: {e}")

# Track per-event reminder tasks (for cancellation/update)
reminder_tasks = {}

# Track per-event cleanup tasks (to remove finished events after result)
cleanup_tasks = {}

# Store judge assignments to prevent overloading
judge_assignments = {}  # {judge_id: [event_ids]}

# Store scheduled deadlines for reminders
scheduled_deadlines = {}
deadline_tasks = {} # {dl_id: [tasks]}

# Load scheduled deadlines from Supabase (with JSON fallback)
def load_scheduled_deadlines():
    global scheduled_deadlines
    # 1. Load from local fallback JSON first
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

    # 2. Merge/Overlay with Supabase
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

# Save scheduled deadline to file and Supabase
def save_scheduled_deadline(dl_id: str, dl_data: dict):
    # Save to local in-memory
    scheduled_deadlines[dl_id] = dl_data

    # Save to local JSON backup
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

    # Save to Supabase table
    if supabase_client:
        try:
            row = {
                "Guild_ID": str(dl_data['guild_id']),
                "Round": dl_data['round'],
                "Deadline_Time": dl_data['deadline_dt'].isoformat()
            }
            # Upsert into Deadlines table based on Guild_ID + Round uniqueness
            supabase_client.table("Deadlines").upsert(row).execute()
            print(f"[Supabase] ✅ Deadline for round '{dl_data['round']}' in guild {dl_data['guild_id']} saved.")
        except Exception as e:
            print(f"[Supabase] ❌ Failed to upsert deadline to Supabase: {e}")

# Helper to cancel scheduled deadline tasks
def cancel_deadline_tasks(dl_id: str):
    if dl_id in deadline_tasks:
        for t in deadline_tasks[dl_id]:
            if not t.done():
                t.cancel()
        del deadline_tasks[dl_id]

# Schedule the deadline reminder tasks
def schedule_deadline_tasks(dl_id: str):
    cancel_deadline_tasks(dl_id)
    
    dl_data = scheduled_deadlines.get(dl_id)
    if not dl_data:
        return
        
    guild_id = dl_data.get('guild_id')
    round_name = dl_data.get('round')
    deadline_dt = dl_data.get('deadline_dt')
    if isinstance(deadline_dt, str):
        deadline_dt = datetime.datetime.fromisoformat(deadline_dt)
    if deadline_dt.tzinfo is None:
        deadline_dt = deadline_dt.replace(tzinfo=pytz.UTC)
        
    now = datetime.datetime.now(pytz.UTC)
    
    # Calculate target reminder times (06:00 UTC)
    deadline_date = deadline_dt.date()
    reminder_1_dt = datetime.datetime.combine(deadline_date - datetime.timedelta(days=1), datetime.time(6, 0)).replace(tzinfo=pytz.UTC)
    reminder_2_dt = datetime.datetime.combine(deadline_date, datetime.time(6, 0)).replace(tzinfo=pytz.UTC)
    
    tasks = []
    
    # 1. One day before at 06:00 UTC
    if reminder_1_dt > now:
        t1 = asyncio.create_task(run_deadline_reminder_task(dl_id, reminder_1_dt, "one_day_before"))
        tasks.append(t1)
        
    # 2. On the deadline day at 06:00 UTC
    if reminder_2_dt > now:
        t2 = asyncio.create_task(run_deadline_reminder_task(dl_id, reminder_2_dt, "deadline_day"))
        tasks.append(t2)
        
    if tasks:
        deadline_tasks[dl_id] = tasks

# Background task wrapper
async def run_deadline_reminder_task(dl_id: str, target_dt: datetime.datetime, reminder_type: str):
    try:
        now = datetime.datetime.now(pytz.UTC)
        delay = (target_dt - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
            
        # Verify deadline still exists
        dl_data = scheduled_deadlines.get(dl_id)
        if not dl_data:
            return
            
        guild_id = dl_data.get('guild_id')
        round_name = dl_data.get('round')
        deadline_dt = dl_data.get('deadline_dt')
        if isinstance(deadline_dt, str):
            deadline_dt = datetime.datetime.fromisoformat(deadline_dt)
        if deadline_dt.tzinfo is None:
            deadline_dt = deadline_dt.replace(tzinfo=pytz.UTC)
            
        current_guild_id.set(guild_id)
        
        guild = bot.get_guild(guild_id)
        if not guild:
            try:
                guild = await bot.fetch_guild(guild_id)
            except Exception:
                print(f"Failed to fetch guild {guild_id} for deadline reminder")
                return
                
        # Get deadline channel ID
        t_cfg = get_active_tournament_config(guild_id)
        channel_id = None
        if t_cfg:
            channel_id = t_cfg.get('deadline') or t_cfg.get('Deadline_Channel_ID')
        if not channel_id:
            cfg = get_guild_config(guild_id)
            channel_id = cfg.get('channel_ids', {}).get('deadlines')
            
        if not channel_id:
            print(f"No deadline channel configured for guild {guild_id}")
            return
            
        channel = guild.get_channel(int(channel_id))
        if not channel:
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except Exception:
                print(f"Failed to fetch deadline channel {channel_id} in guild {guild_id}")
                return
                
        # Ping the players role instead of individual player IDs
        # Priority: tournament config players_role_id -> guild config Players_Role_ID
        cfg = get_guild_config(guild_id)
        t_cfg_dl = get_active_tournament_config(guild_id)
        players_role_ping = "@Player"
        players_r_id = None
        # 1. Check tournament config first
        if t_cfg_dl:
            raw = t_cfg_dl.get('players_role_id')
            if raw:
                try:
                    players_r_id = int(raw)
                except (ValueError, TypeError):
                    players_r_id = None
        # 2. Fall back to guild config Players_Role_ID
        if not players_r_id:
            raw = cfg.get('role_ids', {}).get('players')
            if raw:
                try:
                    players_r_id = int(raw)
                except (ValueError, TypeError):
                    players_r_id = None
        if players_r_id:
            players_role_obj = guild.get_role(players_r_id)
            if players_role_obj:
                players_role_ping = players_role_obj.mention

        deadline_date_str = deadline_dt.strftime("%d/%m/%Y")
        deadline_time_str = deadline_dt.strftime("%H:%M UTC")

        if reminder_type == "one_day_before":
            message = (
                f"Hello {players_role_ping}!\n"
                f"Tomorrow ({deadline_date_str}) is the deadline for Round {round_name}. If you have not opened your ticket and scheduled your match time, please do so. Otherwise, the bot will randomly assign a time based on the UTC time you provided.\n"
                f"**Deadline: {deadline_time_str}**\n\n"
                f"Good luck!"
            )
        else: # "deadline_day"
            message = (
                f"Hello {players_role_ping}!\n"
                f"Today ({deadline_date_str}) is the deadline for Round {round_name}. If you have not opened your ticket and scheduled your match time, please do so immediately. Otherwise, the bot will randomly assign a time based on the UTC time you provided.\n"
                f"**Deadline: {deadline_time_str}**\n\n"
                f"Good luck!"
            )

        await channel.send(message)
        
    except Exception as e:
        print(f"Error running deadline reminder task for {dl_id}: {e}")

def format_round_heading(round_val) -> str:
    if not round_val:
        return "Round Not Set"
    
    round_str = str(round_val).strip()
    
    # Strip leading 'R' or 'r' if followed by numbers or negatives
    match = re.match(r'^[Rr](-?\d+)$', round_str)
    if match:
        round_str = match.group(1)
        
    try:
        r_int = int(round_str)
        if r_int < 0:
            return f"Losers Round {abs(r_int)}"
        else:
            return f"Winners Round {r_int}"
    except (ValueError, TypeError):
        return round_str

# Helper to map round name selection to Challonge round numbers
def map_round_name_to_challonge_rounds(round_name: str, matches: list) -> list[int]:
    if round_name.startswith("D"):
        try:
            num = int(round_name[1:])
            return [num, -num]
        except ValueError:
            pass
            
    # Find unique rounds from matches
    rounds = sorted(list(set(m.get('round') for m in matches if m.get('round') is not None)))
    winners_rounds = [r for r in rounds if r > 0]
    
    if round_name == "Final":
        res = []
        if winners_rounds:
            res.append(winners_rounds[-1])
        return res
    elif round_name == "Semi-Final":
        res = []
        if len(winners_rounds) >= 2:
            res.append(winners_rounds[-2])
        return res
    elif round_name == "Bronze Match":
        res = []
        if winners_rounds:
            res.append(winners_rounds[-1])
        return res
    return []

# Helper to map round name selection to channel prefix patterns
def get_round_channel_prefixes(round_name: str) -> list[str]:
    if round_name.startswith("D"):
        try:
            num = int(round_name[1:])
            return [f"rd{num}-", f"r{num}-", f"r-{num}-"]
        except ValueError:
            pass
    if round_name == "Semi-Final":
        return ["rsemi-", "rsemifinal-", "rsemi-final-"]
    if round_name == "Final":
        return ["rfinal-"]
    if round_name == "Bronze Match":
        return ["rbronze-", "r3rd-", "rthird-"]
    return [f"r{round_name.lower()}-"]

# Helper to resolve member names to discord members
async def resolve_member_helper(guild: discord.Guild, raw: str) -> Optional[discord.Member]:
    if not raw or not raw.strip():
        return None
    clean_raw = raw.strip()
    if clean_raw.startswith('@'):
        clean_raw = clean_raw[1:].strip()
        
    m = re.search(r'<@!?(\d+)>', clean_raw)
    uid = None
    if m:
        uid = int(m.group(1))
    elif clean_raw.isdigit():
        uid = int(clean_raw)
        
    if uid:
        member = guild.get_member(uid)
        if not member:
            try:
                member = await guild.fetch_member(uid)
            except Exception:
                pass
        return member
    
    for member in guild.members:
        if member.name.lower() == clean_raw.lower() or member.display_name.lower() == clean_raw.lower():
            return member
            
    try:
        found_members = await guild.query_members(query=clean_raw, limit=5)
        for member in found_members:
            if member.name.lower() == clean_raw.lower() or member.display_name.lower() == clean_raw.lower():
                return member
    except Exception:
        pass
    return None

# Find relevant players to ping
async def get_unscheduled_players_for_round(guild: discord.Guild, round_name: str) -> list[str]:
    unscheduled = []
    
    t_cfg = get_active_tournament_config(guild.id)
    if not t_cfg:
        return []
        
    bracket_link = t_cfg.get('challonge_bracket_link') or t_cfg.get('id')
    api_key = t_cfg.get('key')
    sheet_link = t_cfg.get('google_sheet_link') or t_cfg.get('Captains_Sheet_Link')
    
    # 1. Fetch matches from Challonge
    matches = []
    if bracket_link and api_key:
        try:
            matches_info, err = await fetch_challonge_open_matches(bracket_link, api_key)
            if matches_info:
                matches = matches_info
        except Exception as e:
            print(f"Error fetching Challonge matches for deadline reminder: {e}")
            
    # 2. Fetch captains from Google Sheet
    captains_dict = {}
    if sheet_link:
        try:
            c_dict, is_1v1, err2 = await fetch_google_sheet_captains(sheet_link)
            if c_dict:
                captains_dict = c_dict
        except Exception as e:
            print(f"Error fetching Google Sheet captains for deadline reminder: {e}")
            
    target_rounds = map_round_name_to_challonge_rounds(round_name, matches)
    target_matches = [m for m in matches if m.get('round') in target_rounds]
    
    for match in target_matches:
        match_id = match.get('id')
        team1 = match.get('team1')
        team2 = match.get('team2')
        
        c1_raw = captains_dict.get(team1) or captains_dict.get(team1.strip()) if team1 else None
        c2_raw = captains_dict.get(team2) or captains_dict.get(team2.strip()) if team2 else None
        
        captain1_mention = None
        captain2_mention = None
        
        if c1_raw:
            if c1_raw.startswith("<@") and c1_raw.endswith(">"):
                captain1_mention = c1_raw
            elif c1_raw.isdigit():
                captain1_mention = f"<@{c1_raw}>"
            else:
                member = await resolve_member_helper(guild, c1_raw)
                if member:
                    captain1_mention = member.mention
                    
        if c2_raw:
            if c2_raw.startswith("<@") and c2_raw.endswith(">"):
                captain2_mention = c2_raw
            elif c2_raw.isdigit():
                captain2_mention = f"<@{c2_raw}>"
            else:
                member = await resolve_member_helper(guild, c2_raw)
                if member:
                    captain2_mention = member.mention
                    
        channel_exists = False
        channel_id = None
        for channel in guild.text_channels:
            if channel.topic and f"MatchID:{match_id}" in channel.topic:
                channel_exists = True
                channel_id = channel.id
                break
                
        is_scheduled = False
        if channel_exists and channel_id:
            for ev_id, ev_data in scheduled_events.items():
                if ev_data.get('channel_id') == channel_id:
                    is_scheduled = True
                    break
                    
        if not channel_exists or not is_scheduled:
            if captain1_mention and captain1_mention not in unscheduled:
                unscheduled.append(captain1_mention)
            if captain2_mention and captain2_mention not in unscheduled:
                unscheduled.append(captain2_mention)
                
    # Fallback to scanning ticket channels if no matches found via Challonge (or API fails)
    if not unscheduled:
        prefix_options = get_round_channel_prefixes(round_name)
        for channel in guild.text_channels:
            matches_prefix = any(channel.name.startswith(p) for p in prefix_options)
            if matches_prefix:
                is_scheduled = False
                for ev_id, ev_data in scheduled_events.items():
                    if ev_data.get('channel_id') == channel.id:
                        is_scheduled = True
                        break
                if not is_scheduled:
                    cfg = get_guild_config(guild.id)
                    staff_role_ids = []
                    for r_key in ["head_organizer", "organizer", "helper_team", "judge", "recorder", "staff"]:
                        if r_id := cfg.get('role_ids', {}).get(r_key):
                            try:
                                staff_role_ids.append(int(r_id))
                            except:
                                pass
                                
                    for member, overwrite in channel.overwrites.items():
                        if isinstance(member, discord.Member) and not member.bot:
                            is_staff = any(role.id in staff_role_ids for role in member.roles)
                            if not is_staff and overwrite.view_channel:
                                if member.mention not in unscheduled:
                                    unscheduled.append(member.mention)
                                    
    return unscheduled

# Store judge assignments to prevent overloading
judge_assignments = {}  # {judge_id: [event_ids]}

import csv
import io

# Cache for SheetDB tab names to prevent querying on every request
sheetdb_tabs_cache = {}  # {api_url: [tab_names]}

def _sync_sheetdb_post(sheet_name: str, row_data: dict):
    """Synchronous write to Supabase and SheetDB (Google Sheets). Call via asyncio.to_thread."""
    # 1. Supabase insert
    supabase_success = False
    cleaned_row = row_data.copy()
    if "sheetdb_api_url" in cleaned_row:
        del cleaned_row["sheetdb_api_url"]

    if supabase_client:
        try:
            supabase_client.table(sheet_name).insert(cleaned_row).execute()
            print(f"[Supabase] ✅ Row added to '{sheet_name}'")
            supabase_success = True
        except Exception as e:
            print(f"[Supabase] ❌ Exception posting to '{sheet_name}': {e}")

    # 2. SheetDB insert
    guild_id = row_data.get("Guild_ID")
    if not guild_id:
        guild_id = current_guild_id.get()

    try:
        api_url = get_sheetdb_api_url(guild_id)
    except Exception as e:
        print(f"[SheetDB] ❌ Failed to fetch SheetDB URL for guild {guild_id}: {e}")
        api_url = "https://sheetdb.io/api/v1/vlbn6vbc8vdbb"

    if not api_url:
        print(f"[SheetDB] ❌ No API URL found for guild {guild_id}")
        return supabase_success

    import urllib.parse
    import time
    
    # Dynamically match sheet name to resolve spaces/casing differences
    global sheetdb_tabs_cache
    resolved_sheet_name = sheet_name
    try:
        parsed_api = urllib.parse.urlparse(api_url)
        sheets_url = f"{parsed_api.scheme}://{parsed_api.netloc}{parsed_api.path.rstrip('/')}/sheets"
        
        if api_url not in sheetdb_tabs_cache:
            sheets_resp = requests.get(sheets_url, timeout=5)
            if sheets_resp.status_code == 200:
                data = sheets_resp.json()
                if isinstance(data, dict) and "sheets" in data:
                    sheetdb_tabs_cache[api_url] = data["sheets"]
                elif isinstance(data, list):
                    sheetdb_tabs_cache[api_url] = data
                print(f"[SheetDB] Cached sheet tabs for {api_url}: {sheetdb_tabs_cache[api_url]}")
        
        if api_url in sheetdb_tabs_cache:
            tabs = sheetdb_tabs_cache[api_url]
            if sheet_name in tabs:
                resolved_sheet_name = sheet_name
            else:
                stripped_target = sheet_name.strip().lower()
                for existing_tab in tabs:
                    if existing_tab.strip().lower() == stripped_target:
                        resolved_sheet_name = existing_tab
                        print(f"[SheetDB] ℹ️ Mapped '{sheet_name}' to existing tab '{resolved_sheet_name}'")
                        break
    except Exception as e:
        print(f"[SheetDB] ⚠️ Failed to resolve/map sheet name '{sheet_name}': {e}")

    parsed = urllib.parse.urlparse(api_url)
    quoted_sheet = urllib.parse.quote(resolved_sheet_name)
    if parsed.query:
        post_url = f"{api_url}&sheet={quoted_sheet}"
    else:
        post_url = f"{api_url}?sheet={quoted_sheet}"

    payload = {"data": [cleaned_row]}
    
    sheetdb_success = False
    retry_delay = 1.0
    for attempt in range(1, 4):
        try:
            response = requests.post(post_url, json=payload, timeout=10)
            if response.status_code in (200, 201):
                print(f"[SheetDB] ✅ Row added to '{sheet_name}' (as '{resolved_sheet_name}') (Attempt {attempt})")
                sheetdb_success = True
                break
            else:
                print(f"[SheetDB] ⚠️ Non-200 response on attempt {attempt}: Status {response.status_code}, Body: {response.text}")
        except Exception as e:
            print(f"[SheetDB] ⚠️ Request exception on attempt {attempt}: {e}")
        
        if attempt < 3:
            time.sleep(retry_delay)
            retry_delay *= 2.0

    if not sheetdb_success:
        print(f"[SheetDB] ❌ Failed to post to '{sheet_name}' after 3 attempts")

    return supabase_success or sheetdb_success

async def sheetdb_post(sheet_name: str, row_data: dict):
    """Async wrapper — runs Supabase and SheetDB inserts in a thread so the event loop stays free."""
    await asyncio.to_thread(_sync_sheetdb_post, sheet_name, row_data)


# ===========================================================================================
# SUPABASE INTEGRATION HELPER FUNCTIONS
# ===========================================================================================

def _sync_save_guild_config_to_supabase(guild_id: int, cfg: dict):
    if not supabase_client:
        return False
    
    # Modern full schema
    row = {
        "Guild_ID": str(guild_id),
        "Admin_Role_ID": str(cfg.get('role_ids', {}).get('head_organizer') or ""),
        "Organizer_Role_ID": str(cfg.get('role_ids', {}).get('organizer') or ""),
        "Helper_Role_ID": str(cfg.get('role_ids', {}).get('helper_team') or ""),
        "Judge_Role_ID": str(cfg.get('role_ids', {}).get('judge') or ""),
        "Recorder_Role_ID": str(cfg.get('role_ids', {}).get('recorder') or ""),
        "Staff_Role_ID": str(cfg.get('role_ids', {}).get('staff') or ""),
        "Players_Role_ID": str(cfg.get('role_ids', {}).get('players') or ""),
        
        "organization_name": str(cfg.get('organization_name', '')),
        "tournament_system_name": str(cfg.get('tournament_system_name', '')),
        "player_info_link": str(cfg.get('player_info_link', '')),
        "player_info_format": str(cfg.get('player_info_format', '5 vs 5')),
        "player_info_participant_channel_id": str(cfg.get('player_info_participant_channel_id', '')),
        "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Legacy schema fallback
    legacy_row = {
        "Guild_ID": str(guild_id),
        "Admin_Role_ID": str(cfg.get('role_ids', {}).get('head_organizer') or ""),
        "Staff_Role_ID": str(cfg.get('role_ids', {}).get('helper_team') or ""),
        "Challonge_Role_ID": str(cfg.get('role_ids', {}).get('players') or ""),
        "Judge_Role_ID": str(cfg.get('role_ids', {}).get('judge') or ""),
        "Recorder_Role_ID": str(cfg.get('role_ids', {}).get('recorder') or ""),
        "organization_name": str(cfg.get('organization_name', '')),
        "tournament_system_name": str(cfg.get('tournament_system_name', '')),
        "player_info_link": str(cfg.get('player_info_link', '')),
        "player_info_format": str(cfg.get('player_info_format', '5 vs 5')),
        "player_info_participant_channel_id": str(cfg.get('player_info_participant_channel_id', '')),
        "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        supabase_client.table("GuildConfig").upsert(row).execute()
        print(f"[Supabase] ✅ GuildConfig updated/created for guild {guild_id}")
        return True
    except Exception as e:
        print(f"[Supabase] ⚠️ Failed saving with full GuildConfig schema, trying legacy fallback: {e}")
        try:
            supabase_client.table("GuildConfig").upsert(legacy_row).execute()
            print("[Supabase] ✅ GuildConfig saved using legacy fallback columns.")
            return True
        except Exception as fallback_err:
            print(f"[Supabase] ❌ Error saving config using legacy fallback: {fallback_err}")
            return False

async def save_guild_config_to_supabase(guild_id: int, cfg: dict):
    if supabase_client:
        await asyncio.to_thread(_sync_save_guild_config_to_supabase, guild_id, cfg)

def _sync_save_tournament_to_supabase(guild_id: int, tournament_id: str, t_data: dict):
    if not supabase_client:
        return False

    # Modern full schema
    row = {
        "Guild_ID": str(guild_id),
        "Tournament_ID": str(tournament_id),
        "Tournament_Name": str(t_data.get('name') or ""),
        "State": str(t_data.get('state') or "pending"),
        "Key": str(t_data.get('key') or ""),
        "challonge_bracket_link": str(t_data.get('challonge_bracket_link') or ""),
        
        # Channels
        "Attendance_Channel_ID": str(t_data.get('attendance') or ""),
        "Transcript_Channel_ID": str(t_data.get('transcript') or ""),
        "Schedule_Channel_ID": str(t_data.get('schedule') or ""),
        "Rules_Channel_ID": str(t_data.get('rules') or ""),
        "Deadline_Channel_ID": str(t_data.get('deadline') or ""),
        "Result_Channel_ID": str(t_data.get('result') or ""),
        "Challonge_Logs_Channel_ID": str(t_data.get('challonge_logs') or ""),
        "Transcript_Logs_Channel_ID": str(t_data.get('transcript_logs') or ""),
        "Bot_Logs_Channel_ID": str(t_data.get('bot_logs') or ""),
        
        # Categories
        "Closed_Ticket_Category_ID": str(t_data.get('closed_ticket_1') or ""),
        "Closed_Ticket_Category_2_ID": str(t_data.get('closed_ticket_2') or ""),
        "Open_Category_1_ID": str(t_data.get('ticket_open_category_1') or ""),
        "Open_Category_2_ID": str(t_data.get('ticket_open_category_2') or ""),
        "Open_Category_3_ID": str(t_data.get('ticket_open_category_3') or ""),
        
        "Auto_Room_Creation": str(t_data.get('auto_room_creation', True)),
        "Players_Role_ID": str(t_data.get('players_role_id') or ""),
        "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Legacy schema fallback
    legacy_row = {
        "Guild_ID": str(guild_id),
        "Tournament_ID": str(tournament_id),
        "Tournament_Name": str(t_data.get('name') or ""),
        "State": str(t_data.get('state') or "pending"),
        "Key": str(t_data.get('key') or ""),
        "challonge_bracket_link": str(t_data.get('challonge_bracket_link') or ""),
        "Transcript_Channel_ID": str(t_data.get('transcript') or ""),
        "Closed_Ticket_Category_ID": str(t_data.get('closed_ticket_1') or ""),
        "Closed_Ticket_Category_2_ID": str(t_data.get('closed_ticket_2') or ""),
        "Attendance_Channel_ID": str(t_data.get('attendance') or ""),
        "Rules_Channel_ID": str(t_data.get('rules') or ""),
        "Deadline_Channel_ID": str(t_data.get('deadline') or ""),
        "Result_Channel_ID": str(t_data.get('result') or ""),
        "Open_Category_1_ID": str(t_data.get('ticket_open_category_1') or ""),
        "Open_Category_2_ID": str(t_data.get('ticket_open_category_2') or ""),
        "Open_Category_3_ID": str(t_data.get('ticket_open_category_3') or ""),
        "Auto_Room_Creation": str(t_data.get('auto_room_creation', True)),
        "Players_Role_ID": str(t_data.get('players_role_id') or ""),
        "Updated_At": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    }

    try:
        supabase_client.table("Tournaments").upsert(row).execute()
        print(f"[Supabase] ✅ Tournaments updated/created for tournament {tournament_id}")
        return True
    except Exception as e:
        print(f"[Supabase] ⚠️ Failed saving with full Tournaments schema, trying legacy fallback: {e}")
        try:
            supabase_client.table("Tournaments").upsert(legacy_row).execute()
            print("[Supabase] ✅ Tournaments saved using legacy fallback columns.")
            return True
        except Exception as fallback_err:
            print(f"[Supabase] ❌ Error saving tournament using legacy fallback: {fallback_err}")
            return False

async def save_tournament_to_supabase(guild_id: int, tournament_id: str, t_data: dict):
    if supabase_client:
        await asyncio.to_thread(_sync_save_tournament_to_supabase, guild_id, tournament_id, t_data)

def _sync_delete_tournament_from_supabase(guild_id: int, tournament_id: str):
    if not supabase_client:
        return False
    try:
        supabase_client.table("Tournaments").delete().eq("Tournament_ID", tournament_id).execute()
        print(f"[Supabase] ✅ Tournaments row deleted for tournament {tournament_id}")
        return True
    except Exception as e:
        print(f"[Supabase] ❌ Error deleting tournament from Supabase: {e}")
        return False

async def delete_tournament_from_supabase(guild_id: int, tournament_id: str):
    if supabase_client:
        await asyncio.to_thread(_sync_delete_tournament_from_supabase, guild_id, tournament_id)


def _sync_save_guild_config_to_sheetdb(guild_id: int, cfg: dict):
    return True

async def save_guild_config_to_sheetdb(guild_id: int, cfg: dict):
    return True

def _sync_save_tournament_to_sheetdb(guild_id: int, tournament_id: str, t_data: dict):
    return True

async def save_tournament_to_sheetdb(guild_id: int, tournament_id: str, t_data: dict):
    return True

def _sync_delete_tournament_from_sheetdb(guild_id: int, tournament_id: str):
    return True

async def delete_tournament_from_sheetdb(guild_id: int, tournament_id: str):
    return True


def extract_challonge_id(link: str) -> str:
    match = re.search(r'https?://(?:([a-zA-Z0-9-]+)\.)?challonge\.com/([a-zA-Z0-9-_]+)', link)
    if match:
        subdomain, path = match.groups()
        if subdomain and subdomain != 'www':
            return f"{subdomain}-{path}"
        return path
    return link.split('/')[-1]

def _sync_fetch_challonge_open_matches(bracket_link: str, api_key: str):
    """Synchronous version — call via asyncio.to_thread"""
    t_id = extract_challonge_id(bracket_link)
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    p_url = f"https://api.challonge.com/v1/tournaments/{t_id}/participants.json"
    p_req = requests.get(p_url, params={"api_key": api_key}, headers=headers, timeout=15)
    if p_req.status_code != 200:
        return None, f"Failed to fetch participants (HTTP {p_req.status_code}): {p_req.text[:300]}"
    pts = {p['participant']['id']: p['participant']['name'] for p in p_req.json()}
    m_url = f"https://api.challonge.com/v1/tournaments/{t_id}/matches.json"
    m_req = requests.get(m_url, params={"api_key": api_key, "state": "open"}, headers=headers, timeout=15)
    if m_req.status_code != 200:
        return None, f"Failed to fetch matches (HTTP {m_req.status_code}): {m_req.text[:300]}"
    matches_info = []
    for m in m_req.json():
        match = m['match']
        if not match.get('player1_id') or not match.get('player2_id'):
            continue
        p1 = pts.get(match['player1_id'], "TBD")
        p2 = pts.get(match['player2_id'], "TBD")
        matches_info.append({
            'id': match['id'],
            'round': match['round'],
            'team1': p1,
            'team2': p2,
            'player1_id': match['player1_id'],
            'player2_id': match['player2_id']
        })
    return matches_info, None

async def fetch_challonge_open_matches(bracket_link: str, api_key: str):
    """Async wrapper — runs the HTTP call in a thread so the event loop stays free."""
    return await asyncio.to_thread(_sync_fetch_challonge_open_matches, bracket_link, api_key)

def _sync_update_challonge_match(bracket_link: str, api_key: str, match_id: str, winner_id: str, scores_csv: str):
    """Synchronous version — call via asyncio.to_thread"""
    t_id = extract_challonge_id(bracket_link)
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
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
    """Async wrapper — runs the HTTP call in a thread so the event loop stays free."""
    return await asyncio.to_thread(_sync_update_challonge_match, bracket_link, api_key, match_id, winner_id, scores_csv)

def _sync_fetch_google_sheet_captains(sheet_link: str):
    """Synchronous version — call via asyncio.to_thread"""
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if not match:
        return None, "Invalid Google Sheet link — could not extract sheet ID"
    sheet_id = match.group(1)
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        reader = csv.reader(io.StringIO(resp.text))
        
        # Read header row
        h_row = next(reader, [])
        h_lower = [h.lower() for h in h_row]
        
        # Find which column contains the team name or discord name (Identifier)
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
                
        # Find which column contains the discord developer ID or mention (Value)
        val_col = -1
        for i, h in enumerate(h_lower):
            if any(x in h for x in ['developer id', 'discord id', 'discord_id', 'mention', 'discord', 'uid', 'id']):
                if i != key_col:
                    val_col = i
                    break
                
        # Default to columns 0 and 1 if nothing found
        if key_col == -1: key_col = 0
        if val_col == -1: val_col = 1
        
        captains = {}
        for row in reader:
            if len(row) > max(key_col, val_col):
                k = row[key_col].strip()
                v = row[val_col].strip()
                if k:
                    # If it's a raw discord number, format as ping <@>
                    if v.isdigit():
                        v = f"<@{v}>"
                    captains[k] = v
        return captains, is_1v1, None
    except Exception as e:
        return None, False, str(e)


async def fetch_google_sheet_captains(sheet_link: str):
    """Async wrapper — runs the HTTP call in a thread so the event loop stays free."""
    return await asyncio.to_thread(_sync_fetch_google_sheet_captains, sheet_link)

# ===========================================================================================
# RULE MANAGEMENT SYSTEM
# ===========================================================================================

# Store tournament rules in memory
tournament_rules = GuildRulesProxy()

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
    """Load rules from persistent storage on startup"""
    global RULES_CACHE
    try:
        if os.path.exists('tournament_rules.json'):
            with open('tournament_rules.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data and any(isinstance(v, dict) and 'rules' in v for v in data.values() if v):
                    RULES_CACHE.update(data)
                else:
                    RULES_CACHE["legacy"] = data
                print(f"Loaded tournament rules from file")
    except Exception as e:
        print(f"Error loading tournament rules: {e}")

def load_staff_stats():
    """Load staff statistics from persistence storage on startup"""
    global STAFF_STATS_CACHE
    try:
        if os.path.exists('staff_stats.json'):
            with open('staff_stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data and any(isinstance(v, dict) and any(isinstance(inner, dict) for inner in v.values()) for v in data.values() if v):
                    STAFF_STATS_CACHE.update(data)
                else:
                    STAFF_STATS_CACHE["legacy"] = data
                print(f"Loaded staff statistics from staff_stats.json")
        elif os.path.exists('judge_stats.json'):
            with open('judge_stats.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                STAFF_STATS_CACHE["legacy"] = data
                print(f"Migrated statistics from judge_stats.json")
    except Exception as e:
        print(f"Error loading staff stats: {e}")

def save_staff_stats():
    """Save staff statistics for the current guild"""
    g_id = current_guild_id.get()
    if g_id:
        save_guild_staff_stats(g_id, get_guild_staff_stats(g_id))
        return True
    return False

def reset_staff_stats():
    """Reset all staff statistics for the current guild"""
    g_id = current_guild_id.get()
    if g_id:
        save_guild_staff_stats(g_id, {})
        return True
    return False

def update_staff_stats(user: discord.Member, role_type: str):
    """Update stats for a staff member (judge or recorder)"""
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
    
    # Update count based on role
    if role_type == "judge":
        stats[user_id]["judge_count"] = stats[user_id].get("judge_count", 0) + 1
    elif role_type == "recorder":
        stats[user_id]["recorder_count"] = stats[user_id].get("recorder_count", 0) + 1
        
    # Update total and metadata
    stats[user_id]["total_count"] = stats[user_id].get("judge_count", 0) + stats[user_id].get("recorder_count", 0)
    stats[user_id]["name"] = user.display_name
    stats[user_id]["last_active"] = datetime.datetime.utcnow().isoformat()
    
    save_guild_staff_stats(g_id, stats)

    # Log to SheetDB
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

def save_rules():
    # Legacy wrapper - no-op since GuildRulesProxy saves automatically on setitem
    return True

def get_current_rules():
    """Get current rules content"""
    return tournament_rules.get('rules', {}).get('content', '')

def set_rules_content(content, user_id, username):
    """Set new rules content with metadata"""
    # Sanitize content (basic cleanup)
    if content:
        content = content.strip()
    
    # Update rules with metadata (invokes GuildRulesProxy.__setitem__)
    tournament_rules['rules'] = {
        'content': content,
        'last_updated': datetime.datetime.utcnow().isoformat(),
        'updated_by': {
            'user_id': user_id,
            'username': username
        },
        'version': tournament_rules.get('rules', {}).get('version', 0) + 1
    }
    return True

def get_user_permission_level(user_roles, user_id: int = None, guild_id: int = None) -> str:
    """Determine user's permission level based on their Discord roles and guild configuration"""
    try:
        # Bot owner ALWAYS gets owner level regardless of roles
        if user_id and user_id == BOT_OWNER_ID:
            return "owner"
        
        if not user_roles:
            return "user"
            
        if not guild_id:
            guild_id = user_roles[0].guild.id
            
        cfg = get_guild_config(guild_id)
        role_ids = cfg.get("role_ids", DEFAULT_ROLE_IDS)
        
        member_role_ids = [role.id for role in user_roles]
        
        def has_role(role_key):
            val = role_ids.get(role_key)
            if not val:
                return False
            try:
                return int(val) in member_role_ids
            except (ValueError, TypeError):
                return str(val) in [str(r) for r in member_role_ids]
        
        if has_role("head_organizer"):
            return "organizer"
        elif has_role("head_helper") or has_role("helper_team"):
            return "helper"
        elif has_role("judge"):
            return "judge"
        elif has_role("recorder"):
            return "recorder"
        else:
            return "user"
    except Exception as e:
        print(f"Error determining user permission level: {e}")
        return "user"  # Default to basic user permissions

def has_organizer_permission(interaction):
    """Check if user has organizer permissions for rule management"""
    if interaction.user.id == BOT_OWNER_ID:
        return True
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    if not interaction.guild:
        return False
    
    cfg = get_guild_config(interaction.guild.id)
    role_ids = cfg.get("role_ids", DEFAULT_ROLE_IDS)
    
    raw_id = role_ids.get("head_organizer")
    try:
        role_id = int(raw_id) if raw_id is not None else None
    except (ValueError, TypeError):
        role_id = None
        
    if not role_id:
        return False
        
    head_organizer_role = discord.utils.get(interaction.user.roles, id=role_id)
    return head_organizer_role is not None

# Embed field utility functions for safe Discord.py embed manipulation
def find_field_index(embed: discord.Embed, field_name: str) -> int:
    """Find the index of a field by name. Returns -1 if not found."""
    try:
        for i, field in enumerate(embed.fields):
            if field.name == field_name:
                return i
        return -1
    except Exception as e:
        print(f"Error finding field index: {e}")
        return -1

def remove_field_by_name(embed: discord.Embed, field_name: str) -> bool:
    """Safely remove a field by name using Discord.py methods. Returns True if removed, False if not found."""
    try:
        field_index = find_field_index(embed, field_name)
        if field_index != -1:
            embed.remove_field(field_index)
            return True
        return False
    except Exception as e:
        print(f"Error removing field by name '{field_name}': {e}")
        return False

def update_judge_field(embed: discord.Embed, judge_member: discord.Member) -> bool:
    """Update or add judge field safely. Returns True if successful."""
    try:
        # Remove existing judge field if it exists
        remove_field_by_name(embed, "👨‍⚖️ Judge")
        
        # Add new judge field
        embed.add_field(
            name="👨‍⚖️ Judge", 
            value=f"{judge_member.mention}", 
            inline=True
        )
        return True
    except Exception as e:
        print(f"Error updating judge field: {e}")
        return False

def remove_judge_field(embed: discord.Embed) -> bool:
    """Remove judge field safely. Returns True if removed, False if not found."""
    try:
        return remove_field_by_name(embed, "👨‍⚖️ Judge")
    except Exception as e:
        print(f"Error removing judge field: {e}")
        return False

def add_green_circle_to_title(title: str) -> str:
    """Add green circle emoji to the beginning of title if not already present"""
    green_circle = "🟢"
    
    # Check if already has green circle
    if title and title.startswith(green_circle):
        return title
    
    # Add green circle to beginning
    return green_circle + (title or "")

def update_embed_title_with_green_circle(embed: discord.Embed) -> bool:
    """Update embed title with green circle, returns success status"""
    try:
        if embed.title:
            new_title = add_green_circle_to_title(embed.title)
            embed.title = new_title
            return True
        return False
    except Exception as e:
        print(f"Error updating embed title with green circle: {e}")
        return False

def replace_green_circle_with_checkmark(title: str) -> str:
    """Replace green circle emoji with checkmark emoji in title"""
    green_circle = "🟢"
    checkmark = "✅"
    
    if title and title.startswith(green_circle):
        return checkmark + title[len(green_circle):]
    
    # If no green circle, just add checkmark at the beginning
    return checkmark + (title or "")

def update_embed_title_with_checkmark(embed: discord.Embed) -> bool:
    """Update embed title with checkmark, returns success status"""
    try:
        if embed.title:
            new_title = replace_green_circle_with_checkmark(embed.title)
            embed.title = new_title
            return True
        return False
    except Exception as e:
        print(f"Error updating embed title with checkmark: {e}")
        return False

def can_judge_take_schedule(judge_id: int, max_assignments: int = 999) -> tuple[bool, str]:
    """Judge limit removed — judges can take unlimited schedules."""
    return True, ""

def add_judge_assignment(judge_id: int, event_id: str):
    """Add a schedule assignment to a judge"""
    if judge_id not in judge_assignments:
        judge_assignments[judge_id] = []
    judge_assignments[judge_id].append(event_id)

def remove_judge_assignment(judge_id: int, event_id: str):
    """Remove a schedule assignment from a judge"""
    if judge_id in judge_assignments and event_id in judge_assignments[judge_id]:
        judge_assignments[judge_id].remove(event_id)
        if not judge_assignments[judge_id]:  # Remove empty list
            del judge_assignments[judge_id]

# ===========================================================================================
# STAFF CONFIRMATION AND REPLACEMENT SYSTEM
# ===========================================================================================

def get_staff_emoji(guild: discord.Guild, role: str) -> str:
    if guild:
        for emoji in guild.emojis:
            if "peek" in emoji.name.lower():
                return str(emoji)
    return "👩‍⚖️" if role == "judge" else "🎥"

class StaffConfirmationView(discord.ui.View):
    def __init__(self, event_id: str, judge_member: Optional[discord.Member], recorder_member: Optional[discord.Member]):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.judge_member = judge_member
        self.recorder_member = recorder_member
        self.update_buttons()

    def update_buttons(self):
        ev = scheduled_events.get(self.event_id, {})
        self.clear_items()
        
        # Dynamically update from latest event data
        self.judge_member = ev.get('judge')
        self.recorder_member = ev.get('recorder')
        
        # Check if within 20 mins
        dt = ev.get('datetime')
        is_too_late = False
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            now = datetime.datetime.now(pytz.UTC)
            is_too_late = (dt - now).total_seconds() < 1200
        
        # Add Judge button if a judge is assigned
        if self.judge_member:
            is_confirmed = ev.get('judge_confirmed', False)
            btn_label = "👨‍⚖️ Confirmed" if is_confirmed else "👨‍⚖️ Confirm Presence"
            btn_style = discord.ButtonStyle.green if is_confirmed else discord.ButtonStyle.gray
            
            btn = discord.ui.Button(label=btn_label, style=btn_style, custom_id=f"confirm_judge_{self.event_id}")
            btn.callback = self.confirm_judge_callback
            if is_too_late and not is_confirmed:
                btn.disabled = True
                btn.label = "❌ Too Late to Confirm"
            self.add_item(btn)
            
        # Add Recorder button if a recorder is assigned
        if self.recorder_member:
            is_confirmed = ev.get('recorder_confirmed', False)
            btn_label = "🎥 Present" if is_confirmed else "🎥 Confirm Presence"
            btn_style = discord.ButtonStyle.blurple if is_confirmed else discord.ButtonStyle.gray
            
            btn = discord.ui.Button(label=btn_label, style=btn_style, custom_id=f"confirm_recorder_{self.event_id}")
            btn.callback = self.confirm_recorder_callback
            if is_too_late and not is_confirmed:
                btn.disabled = True
                btn.label = "❌ Too Late to Confirm"
            self.add_item(btn)

    @with_guild_context
    async def confirm_judge_callback(self, interaction: discord.Interaction):
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
            
        self.judge_member = ev.get('judge')
        assigned_judge_id = getattr(self.judge_member, 'id', self.judge_member)
        if interaction.user.id != assigned_judge_id:
            await interaction.response.send_message("❌ You are not the assigned judge for this event.", ephemeral=True)
            return
            
        dt = ev.get('datetime')
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            now = datetime.datetime.now(pytz.UTC)
            if (dt - now).total_seconds() < 1200:
                await interaction.response.send_message("❌ Too late to confirm presence. Staff replacement is now required.", ephemeral=True)
                return
                
        ev['judge_confirmed'] = True
        save_scheduled_events()
        self.update_buttons()
        
        # Calculate overall status for the footer
        j_conf = ev.get('judge_confirmed', False)
        r_conf = ev.get('recorder_confirmed', False)
        status_parts = []
        if j_conf: status_parts.append("Judge Confirmed")
        if r_conf: status_parts.append("Recorder Present")
        status_str = " | ".join(status_parts) if status_parts else "Pending Confirmation"
        
        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Status: {status_str}")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)
        await interaction.followup.send("✅ You have confirmed your presence as Judge!", ephemeral=True)
        # Log Bot Activity
        log_embed = discord.Embed(
            title="⚖️ Judge Presence Confirmed",
            description=f"Judge **{interaction.user.display_name}** confirmed presence for match (Event ID: `{self.event_id}`).",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Confirmed by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)

    @with_guild_context
    async def confirm_recorder_callback(self, interaction: discord.Interaction):
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
            
        self.recorder_member = ev.get('recorder')
        assigned_recorder_id = getattr(self.recorder_member, 'id', self.recorder_member)
        if interaction.user.id != assigned_recorder_id:
            await interaction.response.send_message("❌ You are not the assigned recorder for this event.", ephemeral=True)
            return
            
        dt = ev.get('datetime')
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            now = datetime.datetime.now(pytz.UTC)
            if (dt - now).total_seconds() < 1200:
                await interaction.response.send_message("❌ Too late to confirm presence. Staff replacement is now required.", ephemeral=True)
                return
                
        ev['recorder_confirmed'] = True
        save_scheduled_events()
        self.update_buttons()
        
        # Calculate overall status for the footer
        j_conf = ev.get('judge_confirmed', False)
        r_conf = ev.get('recorder_confirmed', False)
        status_parts = []
        if j_conf: status_parts.append("Judge Confirmed")
        if r_conf: status_parts.append("Recorder Present")
        status_str = " | ".join(status_parts) if status_parts else "Pending Confirmation"
        
        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Status: {status_str}")
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)
        await interaction.followup.send("✅ You have confirmed your presence as Recorder!", ephemeral=True)
        # Log Bot Activity
        log_embed = discord.Embed(
            title="🎥 Recorder Presence Confirmed",
            description=f"Recorder **{interaction.user.display_name}** confirmed presence for match (Event ID: `{self.event_id}`).",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Confirmed by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)


class StaffReplacementView(discord.ui.View):
    def __init__(self, event_id: str, replace_judge: bool, replace_recorder: bool):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.replace_judge = replace_judge
        self.replace_recorder = replace_recorder
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        ev = scheduled_events.get(self.event_id, {})
        
        if self.replace_judge:
            is_replaced = ev.get('judge_replaced', False)
            btn_label = "👨‍⚖️ Replaced" if is_replaced else "👨‍⚖️ Replace Judge"
            btn_style = discord.ButtonStyle.green if is_replaced else discord.ButtonStyle.primary
            
            btn = discord.ui.Button(label=btn_label, style=btn_style, disabled=is_replaced, custom_id=f"replace_judge_{self.event_id}")
            btn.callback = self.replace_judge_callback
            self.add_item(btn)
            
        if self.replace_recorder:
            is_replaced = ev.get('recorder_replaced', False)
            btn_label = "🎥 Replaced" if is_replaced else "🎥 Replace Recorder"
            btn_style = discord.ButtonStyle.green if is_replaced else discord.ButtonStyle.primary
            
            btn = discord.ui.Button(label=btn_label, style=btn_style, disabled=is_replaced, custom_id=f"replace_recorder_{self.event_id}")
            btn.callback = self.replace_recorder_callback
            self.add_item(btn)

    @with_guild_context
    async def replace_judge_callback(self, interaction: discord.Interaction):
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        head_helper_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_helper"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, head_helper_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_admin or is_owner):
            await interaction.response.send_message("❌ You do not have the required role to replace the judge.", ephemeral=True)
            return
            
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
            
        ev['judge'] = interaction.user
        ev['judge_confirmed'] = True
        ev['judge_replaced'] = True
        save_scheduled_events()
        
        ch_id = ev.get('channel_id')
        event_ch = interaction.guild.get_channel(ch_id) if ch_id else None
        if event_ch:
            try:
                await event_ch.set_permissions(
                    interaction.user,
                    read_messages=True, send_messages=True, view_channel=True,
                    embed_links=True, attach_files=True, read_message_history=True
                )
            except Exception as e:
                print(f"Error updating channel permissions for replacement judge: {e}")
            
        self.update_buttons()
        
        # Update schedule message in take schedule channel if it exists
        try:
            sched_chan_id = ev.get('schedule_channel_id')
            sched_msg_id = ev.get('schedule_message_id')
            if sched_chan_id and sched_msg_id:
                sched_chan = interaction.guild.get_channel(sched_chan_id)
                if sched_chan:
                    sched_msg = await sched_chan.fetch_message(sched_msg_id)
                    if sched_msg:
                        sched_embed = sched_msg.embeds[0]
                        update_judge_field(sched_embed, interaction.user)
                        sched_view = TakeScheduleButton(self.event_id, ev.get('team1_captain'), ev.get('team2_captain'), event_ch)
                        await sched_msg.edit(embed=sched_embed, view=sched_view)
        except Exception as e:
            print(f"Error updating schedule message after replacement: {e}")
        
        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(name="✅ New Judge Assigned", value=f"{interaction.user.mention} has taken over judging this match.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"✅ You have successfully replaced the judge for this match!", ephemeral=True)
        # Log Bot Activity
        log_embed = discord.Embed(
            title="👨‍⚖️ Judge Replaced",
            description=f"New Judge **{interaction.user.display_name}** took over judging for match (Event ID: `{self.event_id}`).",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Replaced by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)
        if event_ch:
            emoji = get_staff_emoji(event_ch.guild, "judge")
            await event_ch.send(f"{interaction.user.mention} assigned as **judge** {emoji}")

    @with_guild_context
    async def replace_recorder_callback(self, interaction: discord.Interaction):
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        head_helper_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_helper"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, head_helper_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_admin or is_owner):
            await interaction.response.send_message("❌ You do not have the required role to replace the recorder.", ephemeral=True)
            return
            
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
            
        ev['recorder'] = interaction.user
        ev['recorder_confirmed'] = True
        ev['recorder_replaced'] = True
        save_scheduled_events()
        
        ch_id = ev.get('channel_id')
        event_ch = interaction.guild.get_channel(ch_id) if ch_id else None
        if event_ch:
            try:
                await event_ch.set_permissions(
                    interaction.user,
                    read_messages=True, send_messages=True, view_channel=True,
                    embed_links=True, attach_files=True, read_message_history=True
                )
            except Exception as e:
                print(f"Error updating channel permissions for replacement recorder: {e}")
            
        self.update_buttons()
        
        # Update schedule message in take schedule channel if it exists
        try:
            sched_chan_id = ev.get('schedule_channel_id')
            sched_msg_id = ev.get('schedule_message_id')
            if sched_chan_id and sched_msg_id:
                sched_chan = interaction.guild.get_channel(sched_chan_id)
                if sched_chan:
                    sched_msg = await sched_chan.fetch_message(sched_msg_id)
                    if sched_msg:
                        sched_embed = sched_msg.embeds[0]
                        remove_field_by_name(sched_embed, "🎥 Recorder")
                        sched_embed.add_field(name="🎥 Recorder", value=interaction.user.mention, inline=True)
                        sched_view = TakeScheduleButton(self.event_id, ev.get('team1_captain'), ev.get('team2_captain'), event_ch)
                        await sched_msg.edit(embed=sched_embed, view=sched_view)
        except Exception as e:
            print(f"Error updating schedule message after recorder replacement: {e}")
        
        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(name="✅ New Recorder Assigned", value=f"{interaction.user.mention} has taken over recording this match.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"✅ You have successfully replaced the recorder for this match!", ephemeral=True)
        # Log Bot Activity
        log_embed = discord.Embed(
            title="🎥 Recorder Replaced",
            description=f"New Recorder **{interaction.user.display_name}** took over recording for match (Event ID: `{self.event_id}`).",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Replaced by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)
        if event_ch:
            emoji = get_staff_emoji(event_ch.guild, "recorder")
            await event_ch.send(f"{interaction.user.mention} assigned as **recorder** {emoji}")


async def run_staff_presence_check(event_id: str, event_channel: discord.TextChannel, match_time: datetime.datetime, minutes_before: int = 10):
    if event_id not in scheduled_events:
        return
        
    ev = scheduled_events[event_id]
    guild = event_channel.guild
    j_id = ev.get('judge')
    r_id = ev.get('recorder')
    
    judge = guild.get_member(j_id) if isinstance(j_id, int) else j_id
    recorder = guild.get_member(r_id) if isinstance(r_id, int) else r_id
    
    judge_confirmed = ev.get('judge_confirmed', False)
    recorder_confirmed = ev.get('recorder_confirmed', False)
    
    judge_needs_replacement = judge and not judge_confirmed
    if not judge and not judge_confirmed:
        judge_needs_replacement = True
        
    recorder_needs_replacement = recorder and not recorder_confirmed
    if not recorder and not recorder_confirmed:
        recorder_needs_replacement = True
        
    if not judge_needs_replacement and not recorder_needs_replacement:
        # Both are confirmed! Send regular 10-minute reminder if within 10 minutes
        if minutes_before <= 10:
            t1 = ev.get('team1_captain')
            t2 = ev.get('team2_captain')
            t1_m = guild.get_member(t1) if isinstance(t1, int) else t1
            t2_m = guild.get_member(t2) if isinstance(t2, int) else t2
            await send_ten_minute_reminder(event_id, t1_m, t2_m, judge, event_channel, match_time)
        return
        
    pings = []
    missing_staff_details = []
    
    if judge_needs_replacement:
        if judge:
            pings.append(f"<@{judge.id}>")
            missing_staff_details.append(f"⚖️ **Judge** {judge.mention} failed to confirm presence or resigned")
        else:
            missing_staff_details.append(f"⚖️ **Judge** (No Judge was assigned to this match)")
            
        j_role_id = ROLE_IDS.get("judge")
        if j_role_id:
            pings.append(f"<@&{j_role_id}>")
        
    if recorder_needs_replacement:
        if recorder:
            pings.append(f"<@{recorder.id}>")
            missing_staff_details.append(f"🎥 **Recorder** {recorder.mention} failed to confirm presence or resigned")
        else:
            missing_staff_details.append(f"🎥 **Recorder** (No Recorder was assigned to this match)")
            
        r_role_id = ROLE_IDS.get("recorder")
        if r_role_id:
            pings.append(f"<@&{r_role_id}>")
        
    pings_str = " ".join(set(pings))
    
    embed = discord.Embed(
        title="🚨 URGENT STAFF REPLACEMENT NEEDED!",
        description=f"Match starts in {minutes_before} minutes!\n\n" + "\n".join(missing_staff_details),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"IMMEDIATE ACTION REQUIRED - Match starts in {minutes_before} minutes")
    
    # Load poster image for unified size
    poster_image = ev.get('poster_path')
    file = None
    if poster_image and os.path.exists(poster_image):
        try:
            file = discord.File(poster_image, filename="event_poster.png")
            embed.set_image(url="attachment://event_poster.png")
        except Exception as e:
            print(f"Error loading poster image for replacement embed: {e}")
            
    view = StaffReplacementView(event_id, judge_needs_replacement, recorder_needs_replacement)
    
    # Send replacement request to schedule channel (active tournament first, then global fallback)
    _sched_ch_staff = None
    try:
        _guild_id_staff = ev.get('guild_id')
        if _guild_id_staff:
            _t_cfg_staff = get_active_tournament_config(_guild_id_staff)
            if _t_cfg_staff and _t_cfg_staff.get('schedule_channel_id'):
                _sched_ch_staff = guild.get_channel(int(_t_cfg_staff['schedule_channel_id']))
    except Exception as _e_staff:
        print(f"Error resolving tournament schedule channel for staff check: {_e_staff}")
    if not _sched_ch_staff:
        _sched_ch_staff = guild.get_channel(CHANNEL_IDS.get("take_schedule"))
    schedule_channel = _sched_ch_staff
    if schedule_channel:
        try:
            if file:
                await schedule_channel.send(content=f"{pings_str} 🚨 **URGENT STAFF REPLACEMENT NEEDED!**", embed=embed, file=file, view=view)
            else:
                await schedule_channel.send(content=f"{pings_str} 🚨 **URGENT STAFF REPLACEMENT NEEDED!**", embed=embed, view=view)
        except Exception as e:
            print(f"Failed to send replacement alert to schedule channel: {e}")
            
    # Notify event channel
    try:
        await event_channel.send("🚨 **URGENT:** Staff presence was not confirmed. Staff replacement request has been posted to the schedule channel.")
    except Exception as e:
        print(f"Failed to send warning to ticket channel: {e}")


async def run_two_minute_staff_check(event_id: str, event_channel: discord.TextChannel, match_time: datetime.datetime):
    # Compatibility wrapper for legacy 2-minute staff check
    await run_staff_presence_check(event_id, event_channel, match_time, minutes_before=2)


class TakeScheduleButton(discord.ui.View):
    def __init__(self, event_id: str, team1_captain: discord.Member, team2_captain: discord.Member, event_channel: discord.TextChannel = None):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.team1_captain = team1_captain
        self.team2_captain = team2_captain
        self.event_channel = event_channel
        self._taking_schedule = False  # Flag to prevent race conditions

        # Load dynamic state
        ev = scheduled_events.get(event_id, {})
        self.judge = ev.get('judge')
        self.recorder = ev.get('recorder')

        for child in self.children:
            if child.custom_id == "take_schedule_btn" or (child.custom_id and child.custom_id.startswith("take_schedule_")):
                child.custom_id = f"take_schedule_{event_id}"
                if self.judge:
                    j_name = getattr(self.judge, 'display_name', str(self.judge))
                    child.label = f"Taken by {j_name}"
                    child.style = discord.ButtonStyle.gray
                    child.disabled = True
                    child.emoji = "✅"
            elif child.custom_id == "record_btn" or (child.custom_id and child.custom_id.startswith("record_")):
                child.custom_id = f"record_{event_id}"
                if self.recorder:
                    r_name = getattr(self.recorder, 'display_name', str(self.recorder))
                    child.label = f"Recording: {r_name}"
                    child.style = discord.ButtonStyle.gray
                    child.disabled = True
                    child.emoji = "✅"

    def _is_event_started(self) -> bool:
        """Returns True if the event datetime has passed (event started)."""
        event_data = scheduled_events.get(self.event_id)
        if not event_data:
            return False
        dt = event_data.get('datetime')
        if not dt:
            return False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)
        return datetime.datetime.now(pytz.UTC) >= dt

    @discord.ui.button(label="Take Schedule", style=discord.ButtonStyle.green, emoji="📋", custom_id="take_schedule_btn")
    @with_guild_context
    async def take_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Disable both buttons once event has started
        if self._is_event_started():
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await interaction.response.send_message("❌ This event has already started. Buttons are now disabled.", ephemeral=True)
            return

        if self._taking_schedule:
            await interaction.response.send_message("⏳ Another judge is currently taking this schedule. Please wait.", ephemeral=True)
            return

        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        head_helper_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_helper"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, head_helper_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_owner or is_admin):
            await interaction.response.send_message("❌ You do not have the required role to take this schedule.", ephemeral=True)
            return

        if self.judge:
            await interaction.response.send_message(f"❌ This schedule has already been taken by {self.judge.display_name}.", ephemeral=True)
            return

        # Check overlapping schedules
        ev = scheduled_events.get(self.event_id, {})
        current_dt = ev.get('datetime')
        if current_dt:
            user_id = interaction.user.id
            for other_id, other_ev in scheduled_events.items():
                if other_id == self.event_id:
                    continue
                other_dt = other_ev.get('datetime')
                if other_dt:
                    cdt = current_dt.replace(tzinfo=None)
                    odt = other_dt.replace(tzinfo=None)
                    if cdt == odt:
                        other_j = other_ev.get('judge')
                        other_r = other_ev.get('recorder')
                        def safe_int_id(val):
                            if not val:
                                return None
                            try:
                                return int(getattr(val, 'id', val))
                            except (ValueError, TypeError):
                                return None

                        other_j_id = safe_int_id(other_j)
                        other_r_id = safe_int_id(other_r)
                        if user_id in (other_j_id, other_r_id):
                            await interaction.response.send_message("❌ You are already scheduled as staff (Judge/Recorder) for another match at this exact same time.", ephemeral=True)
                            return

        # Capture original button states for rollback if needed
        original_label = button.label
        original_style = button.style
        original_disabled = button.disabled
        original_emoji = button.emoji

        # Instant-disable button to prevent double clicks
        button.label = "Claiming..."
        button.style = discord.ButtonStyle.secondary
        button.disabled = True
        button.emoji = None

        self._taking_schedule = True
        try:
            await interaction.response.edit_message(view=self)
        except Exception as e:
            self._taking_schedule = False
            button.label = original_label
            button.style = original_style
            button.disabled = original_disabled
            button.emoji = original_emoji
            print(f"Failed to edit message in take_schedule initial response: {e}")
            return

        try:
            # Recheck after the edit_message to prevent race conditions
            ev = scheduled_events.get(self.event_id, {})
            if ev.get('judge'):
                button.label = original_label
                button.style = original_style
                button.disabled = original_disabled
                button.emoji = original_emoji
                await interaction.message.edit(view=self)
                j_val = ev.get('judge')
                j_name = getattr(j_val, 'display_name', str(j_val))
                await interaction.followup.send(f"❌ This schedule has already been taken by {j_name}.", ephemeral=True)
                return

            self.judge = interaction.user
            add_judge_assignment(interaction.user.id, self.event_id)

            button.label = f"Taken by {interaction.user.display_name}"
            button.style = discord.ButtonStyle.secondary
            button.disabled = True
            button.emoji = "✅"

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            update_embed_title_with_checkmark(embed)
            if not update_judge_field(embed, interaction.user):
                # Restore button state on embed update failure
                button.label = original_label
                button.style = original_style
                button.disabled = original_disabled
                button.emoji = original_emoji
                await interaction.message.edit(view=self)
                await interaction.followup.send("❌ Failed to update embed with judge information.", ephemeral=True)
                return

            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send("✅ You have successfully taken this schedule!", ephemeral=True)
            
            # Log Bot Activity
            log_embed = discord.Embed(
                title="⚖️ Schedule Claimed",
                description=f"Judge **{interaction.user.display_name}** claimed match schedule (Event ID: `{self.event_id}`).",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            log_embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            await log_bot_activity(interaction.guild, log_embed)

            await self.send_judge_assignment_notification(interaction.user)

            if self.event_id in scheduled_events:
                scheduled_events[self.event_id]['judge'] = self.judge
                save_scheduled_events()

            # Log judge assignment to SheetDB
            asyncio.create_task(sheetdb_post("JudgeAssignments", {
                "Guild_ID":       str(interaction.guild.id) if interaction.guild else "",
                "Timestamp":      datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "Event_ID":       self.event_id,
                "Judge_ID":       str(interaction.user.id),
                "Judge_Name":     interaction.user.name,
                "Tournament":     ev.get('tournament', ''),
                "Round":          ev.get('round', ''),
                "Date":           ev.get('date_str', ''),
                "UTC_Time":       ev.get('time_str', ''),
                "Action":         "Assigned",
            }))

        except Exception as e:
            print(f"Error in take_schedule: {e}")
            button.label = original_label
            button.style = original_style
            button.disabled = original_disabled
            button.emoji = original_emoji
            try:
                await interaction.message.edit(view=self)
            except Exception as edit_err:
                print(f"Error editing message back: {edit_err}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)
        finally:
            self._taking_schedule = False

    @discord.ui.button(label="Record", style=discord.ButtonStyle.blurple, emoji="🎥", custom_id="record_btn")
    @with_guild_context
    async def record(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Allow a recorder to claim the recording slot."""
        if self._is_event_started():
            for child in self.children:
                child.disabled = True
            try:
                await interaction.message.edit(view=self)
            except Exception:
                pass
            await interaction.response.send_message("❌ This event has already started. Buttons are now disabled.", ephemeral=True)
            return

        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        head_helper_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_helper"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, head_helper_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_owner or is_admin):
            await interaction.response.send_message("❌ You do not have the required role to record.", ephemeral=True)
            return

        if self.recorder:
            await interaction.response.send_message(f"❌ This recording slot has already been claimed by {self.recorder.display_name}.", ephemeral=True)
            return

        # Check overlapping schedules
        ev = scheduled_events.get(self.event_id, {})
        current_dt = ev.get('datetime')
        if current_dt:
            user_id = interaction.user.id
            for other_id, other_ev in scheduled_events.items():
                if other_id == self.event_id:
                    continue
                other_dt = other_ev.get('datetime')
                if other_dt:
                    cdt = current_dt.replace(tzinfo=None)
                    odt = other_dt.replace(tzinfo=None)
                    if cdt == odt:
                        other_j = other_ev.get('judge')
                        other_r = other_ev.get('recorder')
                        other_j_id = getattr(other_j, 'id', other_j) if other_j else None
                        other_r_id = getattr(other_r, 'id', other_r) if other_r else None
                        if user_id in (other_j_id, other_r_id):
                            await interaction.response.send_message("❌ You are already scheduled as staff (Judge/Recorder) for another match at this exact same time.", ephemeral=True)
                            return

        # Capture original button states for rollback if needed
        original_label = button.label
        original_style = button.style
        original_disabled = button.disabled
        original_emoji = button.emoji

        # Instant-disable button to prevent double clicks
        button.label = "Processing..."
        button.style = discord.ButtonStyle.secondary
        button.disabled = True
        button.emoji = None

        try:
            await interaction.response.edit_message(view=self)
        except Exception as e:
            button.label = original_label
            button.style = original_style
            button.disabled = original_disabled
            button.emoji = original_emoji
            print(f"Failed to edit message in record initial response: {e}")
            return

        try:
            # Recheck after the edit_message to prevent race conditions
            ev = scheduled_events.get(self.event_id, {})
            if ev.get('recorder'):
                button.label = original_label
                button.style = original_style
                button.disabled = original_disabled
                button.emoji = original_emoji
                await interaction.message.edit(view=self)
                r_val = ev.get('recorder')
                r_name = getattr(r_val, 'display_name', str(r_val))
                await interaction.followup.send(f"❌ This recording slot has already been claimed by {r_name}.", ephemeral=True)
                return

            self.recorder = interaction.user
            button.label = f"Recording: {interaction.user.display_name}"
            button.style = discord.ButtonStyle.secondary
            button.disabled = True
            button.emoji = "✅"

            if self.event_id in scheduled_events:
                scheduled_events[self.event_id]['recorder'] = interaction.user
                save_scheduled_events()
                
            # Log Bot Activity
            log_embed = discord.Embed(
                title="🎥 Recording claimed",
                description=f"Recorder **{interaction.user.display_name}** claimed match recording (Event ID: `{self.event_id}`).",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            log_embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            await log_bot_activity(interaction.guild, log_embed)

            embed = interaction.message.embeds[0]
            remove_field_by_name(embed, "🎥 Recorder")
            embed.add_field(name="🎥 Recorder", value=interaction.user.mention, inline=True)
            await interaction.message.edit(embed=embed, view=self)

            if self.event_channel:
                try:
                    await self.event_channel.set_permissions(
                        interaction.user,
                        read_messages=True, send_messages=True, view_channel=True,
                        embed_links=True, attach_files=True, read_message_history=True
                    )
                    # Retrieve latest judge
                    ev = scheduled_events.get(self.event_id, {})
                    j_val = ev.get('judge')
                    judge_mem = self.event_channel.guild.get_member(j_val) if isinstance(j_val, int) else j_val
                    
                    emoji = get_staff_emoji(self.event_channel.guild, "recorder")
                    await self.event_channel.send(content=f"{interaction.user.mention} assigned as **recorder** {emoji}")
                except Exception as e:
                    print(f"Error notifying recorder: {e}")

            # Log recorder to SheetDB
            asyncio.create_task(sheetdb_post("JudgeAssignments", {
                "Guild_ID":    str(interaction.guild.id) if interaction.guild else "",
                "Timestamp":   datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "Event_ID":    self.event_id,
                "Judge_ID":    str(interaction.user.id),
                "Judge_Name":  interaction.user.name,
                "Tournament":  ev.get('tournament', ''),
                "Round":       ev.get('round', ''),
                "Date":        ev.get('date_str', ''),
                "UTC_Time":    ev.get('time_str', ''),
                "Action":      "Recorder",
            }))
            await interaction.followup.send("✅ You have been assigned as the Recorder!", ephemeral=True)

        except Exception as e:
            print(f"Error in record callback: {e}")
            button.label = original_label
            button.style = original_style
            button.disabled = original_disabled
            button.emoji = original_emoji
            try:
                await interaction.message.edit(view=self)
            except Exception as edit_err:
                print(f"Error editing message back: {edit_err}")
            await interaction.followup.send(f"❌ An error occurred: {str(e)}", ephemeral=True)

    async def send_judge_assignment_notification(self, judge: discord.Member):
        """Send notification to the event channel when a judge is assigned and add judge to channel"""
        if not self.event_channel:
            return
        try:
            await self.event_channel.set_permissions(
                judge,
                read_messages=True, send_messages=True, view_channel=True,
                embed_links=True, attach_files=True, read_message_history=True
            )
            ev = scheduled_events.get(self.event_id, {})
            r_val = ev.get('recorder')
            recorder_mem = self.event_channel.guild.get_member(r_val) if isinstance(r_val, int) else r_val
            
            emoji = get_staff_emoji(self.event_channel.guild, "judge")
            await self.event_channel.send(content=f"{judge.mention} assigned as **judge** {emoji}")
        except discord.Forbidden:
            print(f"Error: Bot doesn't have permission to add {judge.display_name} to channel {self.event_channel.name}")
        except Exception as e:
            print(f"Error sending judge assignment notification: {e}")


# ===========================================================================================
# RULE MANAGEMENT UI COMPONENTS
# ===========================================================================================

class RuleInputModal(discord.ui.Modal):
    """Modal for entering/editing rule content"""
    
    def __init__(self, title: str, current_content: str = ""):
        super().__init__(title=title)
        
        # Text input field for rule content
        self.rule_input = discord.ui.TextInput(
            label="Tournament Rules",
            placeholder="Enter the tournament rules here...",
            default=current_content,
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=False
        )
        self.add_item(self.rule_input)
    
    @with_guild_context
    async def on_submit(self, interaction: discord.Interaction):
        try:
            # Get the content from the input
            content = self.rule_input.value.strip()
            
            # Save the rules
            success = set_rules_content(content, interaction.user.id, interaction.user.name)
            
            if success:
                # Create confirmation embed
                embed = discord.Embed(
                    title="✅ Rules Updated Successfully",
                    description="Tournament rules have been saved.",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                
                if content:
                    # Show preview of rules (truncated if too long)
                    preview = content[:500] + "..." if len(content) > 500 else content
                    embed.add_field(name="Rules Preview", value=f"```\n{preview}\n```", inline=False)
                else:
                    embed.add_field(name="Status", value="Rules have been cleared (empty)", inline=False)
                
                embed.set_footer(text=f"Updated by {interaction.user.name}")
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message("❌ Failed to save rules. Please try again.", ephemeral=True)
                
        except Exception as e:
            print(f"Error in rule modal submission: {e}")
            await interaction.response.send_message("❌ An error occurred while saving rules.", ephemeral=True)

class RulesManagementView(discord.ui.View):
    """Interactive view for organizers with rule management buttons"""
    
    def __init__(self):
        super().__init__(timeout=300)  # 5 minute timeout
    
    @discord.ui.button(label="Enter Rules", style=discord.ButtonStyle.green, emoji="📝")
    @with_guild_context
    async def enter_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Button to enter new rules"""
        modal = RuleInputModal("Enter Tournament Rules")
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Reedit Rules", style=discord.ButtonStyle.primary, emoji="✏️")
    @with_guild_context
    async def reedit_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Button to edit existing rules"""
        current_rules = get_current_rules()
        
        if not current_rules:
            await interaction.response.send_message("❌ No rules are currently set. Use 'Enter Rules' to create new rules.", ephemeral=True)
            return
        
        modal = RuleInputModal("Edit Tournament Rules", current_rules)
        await interaction.response.send_modal(modal)
    
    @discord.ui.button(label="Show Rules", style=discord.ButtonStyle.secondary, emoji="👁️")
    @with_guild_context
    async def show_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Button to display current rules"""
        await display_rules(interaction)

async def display_rules(interaction: discord.Interaction):
    """Display current tournament rules in an embed"""
    try:
        if interaction.guild:
            current_guild_id.set(interaction.guild.id)
            
        global tournament_rules
        current_rules = get_current_rules()
        org_name = get_org_name(interaction.guild)
        
        if not current_rules:
            embed = discord.Embed(
                title="📋 Tournament Rules",
                description="No tournament rules have been set yet.",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"{org_name} • Tournament System")
        else:
            embed = discord.Embed(
                title="📋 Tournament Rules",
                description=current_rules,
                color=discord.Color(BRAND_COLOR),
                timestamp=discord.utils.utcnow()
            )
            
            # Add metadata if available
            if 'rules' in tournament_rules and 'last_updated' in tournament_rules['rules']:
                updated_by = tournament_rules['rules'].get('updated_by', {}).get('username', 'Unknown')
                embed.set_footer(text=f"{org_name} • Last updated by {updated_by}")
        
        await interaction.response.send_message(embed=embed, ephemeral=False)
        
    except Exception as e:
        print(f"Error displaying rules: {e}")
        await interaction.response.send_message("❌ An error occurred while displaying rules.", ephemeral=False)

class JudgeLeaderboardView(View):
    """View for staff leaderboard with reset functionality"""
    
    def __init__(self, show_reset: bool = False):
        super().__init__(timeout=300)
        self.show_reset = show_reset
        
        if not show_reset:
            self.clear_items()
    
    @discord.ui.button(label="🔄 Reset Leaderboard", style=discord.ButtonStyle.danger, emoji="🔄")
    @with_guild_context
    async def reset_leaderboard(self, interaction: discord.Interaction, button: Button):
        # Double-check permissions
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        if not head_organizer_role:
            await interaction.response.send_message("❌ You need **Head Organizer** role to reset the leaderboard.", ephemeral=True)
            return
        
        confirm_view = ConfirmResetView()
        await interaction.response.send_message(
            "⚠️ **WARNING**: This will permanently delete all staff statistics!\n\n"
            "Are you sure you want to reset the staff leaderboard?",
            view=confirm_view,
            ephemeral=True
        )

class ConfirmResetView(View):
    """Confirmation view for resetting staff leaderboard"""
    
    def __init__(self):
        super().__init__(timeout=60)
    
    @discord.ui.button(label="✅ Yes, Reset", style=discord.ButtonStyle.danger, emoji="✅")
    @with_guild_context
    async def confirm_reset(self, interaction: discord.Interaction, button: Button):
        try:
            reset_staff_stats()
            await interaction.response.edit_message(
                content="✅ **Staff leaderboard has been reset successfully!**",
                view=None
            )
            print(f"Staff leaderboard reset by {interaction.user.display_name}")
        except Exception as e:
            print(f"Error resetting staff leaderboard: {e}")
            await interaction.response.edit_message(
                content="❌ **Error resetting leaderboard.**",
                view=None
            )
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    @with_guild_context
    async def cancel_reset(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content="✅ **Reset cancelled.**",
            view=None
        )

# ===========================================================================================
# NOTIFICATION AND REMINDER SYSTEM (Ten-minute reminder for captains and judge)
# ===========================================================================================

async def send_ten_minute_reminder(event_id: str, team1_captain: discord.Member, team2_captain: discord.Member, judge: Optional[discord.Member], event_channel: discord.TextChannel, match_time: datetime.datetime):
    """Send 10-minute reminder notification to judge, recorder and captains"""
    try:
        if not event_channel:
            print(f"No event channel provided for event {event_id}")
            return

        # Get the latest data from scheduled_events if available
        resolved_judge = judge
        resolved_team1_captain = team1_captain
        resolved_team2_captain = team2_captain
        resolved_recorder = None
        
        if event_id in scheduled_events:
            event_data = scheduled_events[event_id]
            stored_judge = event_data.get('judge')
            if stored_judge:
                resolved_judge = stored_judge
            
            stored_recorder = event_data.get('recorder')
            if stored_recorder:
                resolved_recorder = stored_recorder
            
            # Get updated captain information
            stored_team1 = event_data.get('team1_captain')
            stored_team2 = event_data.get('team2_captain')
            if stored_team1:
                resolved_team1_captain = stored_team1
            if stored_team2:
                resolved_team2_captain = stored_team2

        # Get correct IDs formatting defensively (handles both Member objects and raw IDs)
        t1_id = getattr(resolved_team1_captain, 'id', resolved_team1_captain)
        t2_id = getattr(resolved_team2_captain, 'id', resolved_team2_captain)
        j_id = getattr(resolved_judge, 'id', resolved_judge) if resolved_judge else None
        r_id = getattr(resolved_recorder, 'id', resolved_recorder) if resolved_recorder else None

        # Create reminder embed
        embed = discord.Embed(
            title="⏰ 10-MINUTE MATCH REMINDER",
            description=f"**Your tournament match is starting in 10 minutes!**",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        _mt_utc = match_time if match_time.tzinfo else match_time.replace(tzinfo=datetime.timezone.utc)
        embed.add_field(name="🕒 Match Time", value=f"<t:{int(_mt_utc.timestamp())}:F>", inline=False)
        embed.add_field(name="👥 Team Captains", value=f"<@{t1_id}> vs <@{t2_id}>", inline=False)
        if j_id:
            embed.add_field(name="👨‍⚖️ Judge", value=f"<@{j_id}>", inline=True)
        if r_id:
            embed.add_field(name="🎥 Recorder", value=f"<@{r_id}>", inline=True)
        embed.add_field(name="📝 Action Required", value="Please prepare for the match and join the designated channel.", inline=False)
        embed.set_footer(text="Tournament Management System")

        # Load poster image for unified size
        file = None
        if event_id in scheduled_events:
            ev_data = scheduled_events[event_id]
            poster_image = ev_data.get('poster_path')
            if poster_image and os.path.exists(poster_image):
                try:
                    file = discord.File(poster_image, filename="event_poster.png")
                    embed.set_image(url="attachment://event_poster.png")
                except Exception as e:
                    print(f"Error loading poster image for 10-min reminder: {e}")

        # Send notification with pings
        pings = f"<@{t1_id}> <@{t2_id}>"
        if j_id:
            pings = f"<@{j_id}> " + pings
        if r_id:
            pings = f"<@{r_id}> " + pings
        notification_text = f"🔔 **MATCH REMINDER**\n\n{pings}\n\nYour match starts in **10 minutes**!"

        if file:
            await event_channel.send(content=notification_text, embed=embed, file=file)
        else:
            await event_channel.send(content=notification_text, embed=embed)
        print(f"10-minute reminder sent for event {event_id}")
    except Exception as e:
        print(f"Error sending 10-minute reminder for event {event_id}: {e}")


async def schedule_ten_minute_reminder(event_id: str, team1_captain: discord.Member, team2_captain: discord.Member, judge: Optional[discord.Member], event_channel: discord.TextChannel, match_time: datetime.datetime):
    """Schedule reminders for the match (20-min judge reminder and 10-min match reminder)"""
    try:
        now = datetime.datetime.now(pytz.UTC)
        if match_time.tzinfo is None:
            match_time = match_time.replace(tzinfo=pytz.UTC)
            
        reminder_time_30 = match_time - datetime.timedelta(minutes=30)
        reminder_time_20 = match_time - datetime.timedelta(minutes=20)
        reminder_time_10 = match_time - datetime.timedelta(minutes=10)
        
        async def combined_reminder_task():
            g_id = None
            if event_id in scheduled_events:
                g_id = scheduled_events[event_id].get('guild_id')
                if g_id:
                    current_guild_id.set(g_id)
                    
            # Wait for 30-min reminder
            delay_30 = (reminder_time_30 - datetime.datetime.now(pytz.UTC)).total_seconds()
            if delay_30 > 0:
                await asyncio.sleep(delay_30)
            
            if g_id:
                current_guild_id.set(g_id)
                
            # Fire 30-min reminder / staff confirmation request
            if event_id in scheduled_events:
                now_check = datetime.datetime.now(pytz.UTC)
                if now_check < match_time:
                    ev_data = scheduled_events[event_id]
                    j = ev_data.get('judge')
                    r = ev_data.get('recorder')
                    
                    # Check assignments and alert roles if missing
                    if not j:
                        try:
                            j_role = ROLE_IDS.get('judge', '')
                            await event_channel.send(f"⚠️ <@&{j_role}> **URGENT:** A match is starting in 30 minutes and NO JUDGE is assigned! Please Take Schedule!")
                        except Exception as e:
                            print(f"Failed to send 30 min judge warning: {e}")
                    
                    if not r:
                        try:
                            r_role = ROLE_IDS.get('recorder', '')
                            await event_channel.send(f"⚠️ <@&{r_role}> **URGENT:** A match is starting in 30 minutes and NO RECORDER is assigned! Please Record!")
                        except Exception as e:
                            print(f"Failed to send 30 min recorder warning: {e}")
                    
                    # If Judge or Recorder are assigned, send presence confirmation view
                    if j or r:
                        try:
                            pings = []
                            if j:
                                j_member = event_channel.guild.get_member(j) if isinstance(j, int) else j
                                if j_member:
                                    pings.append(j_member.mention)
                            if r:
                                r_member = event_channel.guild.get_member(r) if isinstance(r, int) else r
                                if r_member:
                                    pings.append(r_member.mention)
                            
                            ping_str = " ".join(pings)
                            
                            embed = discord.Embed(
                                title="Staff Confirmation Required",
                                description="Please confirm your presence for the upcoming match.",
                                color=discord.Color.orange(),
                                timestamp=discord.utils.utcnow()
                            )
                            embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Confirmation Required | Confirm before the 20-minute staff check")
                            
                            j_m = event_channel.guild.get_member(j) if isinstance(j, int) else j
                            r_m = event_channel.guild.get_member(r) if isinstance(r, int) else r
                            view = StaffConfirmationView(event_id, j_m, r_m)
                            
                            await event_channel.send(content=f"{ping_str} 🔔 **Staff Confirmation Required**", embed=embed, view=view)
                        except Exception as e:
                            print(f"Failed to send staff confirmation request at 30m: {e}")
            
            # Wait for 20-min staff presence check
            delay_20 = (reminder_time_20 - datetime.datetime.now(pytz.UTC)).total_seconds()
            if delay_20 > 0:
                await asyncio.sleep(delay_20)
                
            if g_id:
                current_guild_id.set(g_id)
                
            # Fire staff presence check (replacement trigger at 20-min mark)
            if event_id in scheduled_events:
                now_check = datetime.datetime.now(pytz.UTC)
                if now_check < match_time:
                    try:
                        await run_staff_presence_check(event_id, event_channel, match_time, minutes_before=20)
                    except Exception as e:
                        print(f"Failed to run 20-min staff check: {e}")
            
            # Wait for 10-min player reminder
            delay_10 = (reminder_time_10 - datetime.datetime.now(pytz.UTC)).total_seconds()
            if delay_10 > 0:
                await asyncio.sleep(delay_10)
                
            if g_id:
                current_guild_id.set(g_id)
                
            # Send 10-min player reminder
            if event_id in scheduled_events:
                now_check = datetime.datetime.now(pytz.UTC)
                if now_check < match_time:
                    try:
                        ev_data = scheduled_events[event_id]
                        t1 = ev_data.get('team1_captain')
                        t2 = ev_data.get('team2_captain')
                        t1_m = event_channel.guild.get_member(t1) if isinstance(t1, int) else t1
                        t2_m = event_channel.guild.get_member(t2) if isinstance(t2, int) else t2
                        j_val = ev_data.get('judge')
                        j_m = event_channel.guild.get_member(j_val) if isinstance(j_val, int) else j_val
                        await send_ten_minute_reminder(event_id, t1_m, t2_m, j_m, event_channel, match_time)
                    except Exception as e:
                        print(f"Failed to send 10-min player reminder: {e}")

        # Cancel existing reminder if any
        if event_id in reminder_tasks:
            reminder_tasks[event_id].cancel()

        # Schedule new reminder wrapper
        reminder_tasks[event_id] = asyncio.create_task(combined_reminder_task())
        print(f"Reminders scheduled for event {event_id}")
    except Exception as e:
        print(f"Error scheduling reminders for event {event_id}: {e}")


async def schedule_event_reminder_v2(event_id: str, team1_captain: discord.Member, team2_captain: discord.Member, judge: Optional[discord.Member], event_channel: discord.TextChannel):
    """Schedule event reminder with 10-minute notification using stored event datetime"""
    try:
        if event_id not in scheduled_events:
            print(f"Event {event_id} not found in scheduled_events")
            return
        event_data = scheduled_events[event_id]
        match_time = event_data.get('datetime')
        if not match_time:
            print(f"No datetime found for event {event_id}")
            return
        # Ensure timezone-aware UTC
        if match_time.tzinfo is None:
            match_time = match_time.replace(tzinfo=pytz.UTC)
        await schedule_ten_minute_reminder(event_id, team1_captain, team2_captain, judge, event_channel, match_time)
    except Exception as e:
        print(f"Error in schedule_event_reminder_v2 for event {event_id}: {e}")

async def schedule_event_cleanup(event_id: str, delay_hours: int = 36, delay_minutes: int = None):
    """Schedule cleanup to remove an event and its channel after delay (default 36h, or delay_minutes)."""
    try:
        if event_id not in scheduled_events:
            return
        
        if delay_minutes is not None:
            delay_seconds = delay_minutes * 60
        else:
            delay_seconds = delay_hours * 3600

        async def cleanup_task():
            try:
                if event_id in scheduled_events:
                    g_id = scheduled_events[event_id].get('guild_id')
                    if g_id:
                        current_guild_id.set(g_id)
                await asyncio.sleep(delay_seconds)
                data = scheduled_events.get(event_id)
                if not data:
                    return
                # Delete original schedule message if known
                try:
                    guilds = bot.guilds
                    for guild in guilds:
                        ch_id = data.get('schedule_channel_id')
                        msg_id = data.get('schedule_message_id')
                        if ch_id and msg_id:
                            channel = guild.get_channel(ch_id)
                            if channel:
                                try:
                                    msg = await channel.fetch_message(msg_id)
                                    await msg.delete()
                                except discord.NotFound:
                                    pass
                                except Exception as e:
                                    print(f"Error deleting schedule message for {event_id}: {e}")
                except Exception as e:
                    print(f"Guild/channel fetch error during cleanup for {event_id}: {e}")

                # Clean up poster file if any
                try:
                    poster_path = data.get('poster_path')
                    if poster_path and os.path.exists(poster_path):
                        os.remove(poster_path)
                except Exception as e:
                    print(f"Poster cleanup error for {event_id}: {e}")

                # Delete or complete Discord Server Scheduled Event if exists
                try:
                    scheduled_event_id_val = data.get('scheduled_event_id')
                    if scheduled_event_id_val:
                        for guild in bot.guilds:
                            try:
                                scheduled_event = guild.get_scheduled_event(int(scheduled_event_id_val))
                                if not scheduled_event:
                                    scheduled_event = await guild.fetch_scheduled_event(int(scheduled_event_id_val))
                                if scheduled_event:
                                    try:
                                        if scheduled_event.status == discord.EventStatus.scheduled:
                                            try:
                                                await scheduled_event.edit(status=discord.EventStatus.active)
                                            except Exception:
                                                pass
                                        await scheduled_event.edit(status=discord.EventStatus.completed)
                                    except Exception:
                                        try:
                                            await scheduled_event.delete()
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                except Exception as e:
                    print(f"Error cleaning up scheduled event: {e}")

                # Delete the match/ticket channel if known
                try:
                    ticket_channel_id = data.get('channel_id')
                    if ticket_channel_id:
                        for guild in bot.guilds:
                            channel = guild.get_channel(ticket_channel_id)
                            if channel:
                                try:
                                    await channel.delete(reason="Event result cleanup (30-min auto-delete)")
                                    print(f"🗑️ Deleted ticket/match channel {ticket_channel_id} for event {event_id}")
                                    break
                                except discord.Forbidden:
                                    print(f"Missing permissions to delete channel {ticket_channel_id}")
                                except discord.NotFound:
                                    pass
                                except Exception as err:
                                    print(f"Error deleting channel {ticket_channel_id}: {err}")
                except Exception as e:
                    print(f"Error in channel deletion for event {event_id}: {e}")

                # Remove any reminder task
                try:
                    if event_id in reminder_tasks:
                        reminder_tasks[event_id].cancel()
                        del reminder_tasks[event_id]
                except Exception:
                    pass

                # Finally remove from scheduled events and persist
                try:
                    if event_id in scheduled_events:
                        del scheduled_events[event_id]
                        save_scheduled_events()
                except Exception as e:
                    print(f"Error removing event {event_id} in cleanup: {e}")
            except asyncio.CancelledError:
                print(f"Cleanup task for event {event_id} was cancelled")
            except Exception as e:
                print(f"Error in cleanup task for event {event_id}: {e}")

        # Cancel existing cleanup if any and schedule new
        if event_id in cleanup_tasks:
            try:
                cleanup_tasks[event_id].cancel()
            except Exception:
                pass

        cleanup_tasks[event_id] = asyncio.create_task(cleanup_task())
        if delay_minutes is not None:
            print(f"Cleanup scheduled for event {event_id} in {delay_minutes} minutes")
        else:
            print(f"Cleanup scheduled for event {event_id} in {delay_hours} hours")
    except Exception as e:
        print(f"Error scheduling cleanup for event {event_id}: {e}")

# Google Fonts API Integration
def download_google_font(font_family: str, font_style: str = "regular", font_weight: str = "400") -> str:
    """Download a font from Google Fonts API and return the local file path"""
    try:
        # Google Fonts API URL
        api_url = f"https://fonts.googleapis.com/css2?family={font_family.replace(' ', '+')}:wght@{font_weight}"
        
        # Add style parameter if not regular
        if font_style != "regular":
            api_url += f"&style={font_style}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # Parse CSS to get font URL
        css_content = response.text
        font_urls = re.findall(r'url\((https://[^)]+\.woff2?)\)', css_content)
        
        if not font_urls:
            print(f"No font URLs found in CSS for {font_family}")
            return None
        
        # Download the first font file (usually woff2)
        font_url = font_urls[0]
        font_response = requests.get(font_url, timeout=15)
        font_response.raise_for_status()
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.woff2')
        temp_file.write(font_response.content)
        temp_file.close()
        
        print(f"Downloaded Google Font: {font_family} -> {temp_file.name}")
        return temp_file.name
        
    except Exception as e:
        print(f"Error downloading Google Font {font_family}: {e}")
        return None

def get_font_with_fallbacks(font_name: str, size: int, font_style: str = "regular") -> ImageFont.FreeTypeFont:
    """Get a font using your local fonts first, then Google Fonts as fallback"""
    fonts_dir = "/home/container/Fonts"
    if not os.path.exists(fonts_dir):
        if os.path.exists("/home/container/fonts"):
            fonts_dir = "/home/container/fonts"
        else:
            fonts_dir = os.path.join(BASE_DIR, "Fonts")
    font_candidates = []
    
    # 1. Try your local fonts FIRST (from Fonts/ folder)
    if font_name == "DS-Digital":
        # Prioritize DS-Digital fonts when specifically requested
        local_fonts = [
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGIB.TTF"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGII.TTF"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGI.TTF"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGIT.TTF"),
        ]
    else:
        # Default local fonts for other font requests
        local_fonts = []
        # Prioritize requested font first if recognized
        if font_name == "Capture it":
            local_fonts.append(str(Path(fonts_dir) / "capture_it" / "Capture it.ttf"))
        elif font_name == "Square One":
            local_fonts.extend([
                str(Path(fonts_dir) / "square_one_2" / "Square One Bold.ttf"),
                str(Path(fonts_dir) / "square_one_2" / "Square One.ttf"),
            ])
            
        # Add secondary local font fallbacks
        all_other_fonts = [
            str(Path(fonts_dir) / "capture_it" / "Capture it.ttf"),
            str(Path(fonts_dir) / "square_one_2" / "Square One.ttf"),
            str(Path(fonts_dir) / "square_one_2" / "Square One Bold.ttf"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGIB.TTF"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGII.TTF"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGI.TTF"),
            str(Path(fonts_dir) / "ds_digital" / "DS-DIGIT.TTF"),
        ]
        for f_path in all_other_fonts:
            if f_path not in local_fonts:
                local_fonts.append(f_path)
    font_candidates.extend(local_fonts)
    
    # 2. Try Google Fonts as fallback (only if local fonts fail)
    try:
        google_font_path = download_google_font(font_name, font_style)
        if google_font_path:
            font_candidates.append(google_font_path)
    except Exception as e:
        print(f"Google Fonts failed for {font_name}: {e}")
    
    # 3. Try system fonts
    system_fonts = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf", 
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/trebucbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    font_candidates.extend(system_fonts)
    
    # Try each font candidate
    for font_path in font_candidates:
        try:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, size)
                print(f"Successfully loaded font: {font_path}")
                return font
        except Exception as e:
            print(f"Failed to load font {font_path}: {e}")
            continue
    
    # Final fallback to default font
    print(f"All fonts failed, using default font")
    try:
        # Pillow 10.1.0+ supports size in load_default
        return ImageFont.load_default(size=size)
    except:
        return ImageFont.load_default()

def sanitize_username_for_poster(username: str) -> str:
    """Convert Discord display names to poster-friendly ASCII by stripping emojis and fancy Unicode.

    - Normalizes to NFKD and drops non-ASCII codepoints
    - Collapses repeated whitespace and trims ends
    - Falls back to 'Player' if empty after sanitization
    """
    try:
        import unicodedata
        # Normalize and strip accents/fancy letters
        normalized = unicodedata.normalize('NFKD', str(username))
        ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
        # Remove remaining characters that might be control or non-printable
        ascii_only = re.sub(r"[^\x20-\x7E]", "", ascii_only)
        # Collapse whitespace
        ascii_only = re.sub(r"\s+", " ", ascii_only).strip()
        return ascii_only if ascii_only else "Player"
    except Exception:
        return str(username) if username else "Player"

def get_random_template():
    """Get a random template image from the Templates folder"""
    template_path = "/home/container/templates"
    if not os.path.exists(template_path):
        if os.path.exists("/home/container/Templates"):
            template_path = "/home/container/Templates"
        else:
            template_path = os.path.join(BASE_DIR, "Templates")
    image_files = []
    if os.path.exists(template_path):
        # Get all image files
        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif']
        for ext in image_extensions:
            image_files.extend(glob.glob(os.path.join(template_path, ext)))
            image_files.extend(glob.glob(os.path.join(template_path, ext.upper())))
            
    # Fallback to root templates/banners if Templates folder is empty or missing
    if not image_files:
        fallback_banners = ["tournament_bot_banner.png", "banner.png"]
        for fb in fallback_banners:
            fb_path = os.path.join(BASE_DIR, fb)
            if os.path.exists(fb_path):
                image_files.append(fb_path)
        
    if image_files:
        return random.choice(image_files)
    return None

def create_event_poster(template_path: str, round_label: str, team1_captain: str, team2_captain: str, utc_time: str, date_str: str = None, server_name: str = "Tournament Organizer") -> str:
    """Create event poster with text overlays using Google Fonts and improved error handling"""
    print(f"Creating poster with template: {template_path}")
    
    try:
        # Validate template path
        if not os.path.exists(template_path):
            print(f"Template file not found: {template_path}")
            return None
            
        # Open the template image
        with Image.open(template_path) as img:
            print(f"Opened template image: {img.size}, mode: {img.mode}")
            
            # Convert to RGBA if needed
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Resize image to be smaller (max 800x600 to avoid Discord size limits)
            max_width, max_height = 800, 600
            width, height = img.size
            
            # Calculate new dimensions while maintaining aspect ratio
            if width > max_width or height > max_height:
                ratio = min(max_width / width, max_height / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                print(f"Resized image to: {new_width}x{new_height}")
            
            # Create a copy to work with
            poster = img.copy()
            draw = ImageDraw.Draw(poster)
            
            # Get final image dimensions
            width, height = poster.size
            
            # Load fonts using the new system with Google Fonts integration
            print("Loading fonts...")
            
            # Define font sizes based on image height (reduced for better fit)
            title_size = int(height * 0.10)
            round_size = int(height * 0.14)
            vs_size = int(height * 0.09)
            time_size = int(height * 0.07)
            tiny_size = int(height * 0.05)
            
            # Load fonts with Google Fonts fallback
            try:
                # Use Capture it font for server name, DS-Digital for round, date, and time
                font_title = get_font_with_fallbacks("Capture it", title_size, "bold")  # Server name
                font_round = get_font_with_fallbacks("DS-Digital", round_size, "bold")  # Round text
                # Use a unique bundled font for player names so styling is consistent regardless of Discord nickname styling
                font_vs = get_font_with_fallbacks("Capture it", vs_size, "bold")       # Unique display font from Fonts/capture_it
                font_time = get_font_with_fallbacks("DS-Digital", time_size, "bold")  # Date and time
                font_tiny = get_font_with_fallbacks("Roboto", tiny_size)              # Small text
                
                print("Fonts loaded successfully")
                
            except Exception as font_error:
                print(f"Font loading error: {font_error}")
                # Ultimate fallback to default fonts
                font_title = ImageFont.load_default()
                font_round = ImageFont.load_default()
                font_vs = ImageFont.load_default()
                font_time = ImageFont.load_default()
                font_tiny = ImageFont.load_default()
            
            # Define colors for clean visibility
            text_color = (255, 255, 255)  # Bright white
            outline_color = (0, 0, 0)     # Pure black
            yellow_color = (255, 255, 0)  # Bright yellow for important text
            
            # Helper function to draw text with outline
            def draw_text_with_outline(text, x, y, font, text_color=text_color, use_yellow=False):
                x, y = int(x), int(y)
                final_text_color = yellow_color if use_yellow else text_color
                
                # Draw thick black outline for visibility
                outline_width = 4
                for dx in range(-outline_width, outline_width + 1):
                    for dy in range(-outline_width, outline_width + 1):
                        if dx != 0 or dy != 0:
                            try:
                                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
                            except Exception as e:
                                print(f"Error drawing outline: {e}")
                
                # Draw main text on top
                try:
                    draw.text((x, y), text, font=font, fill=final_text_color)
                except Exception as e:
                    print(f"Error drawing main text: {e}")
            
            # Add server name text (top center)
            try:
                server_text = server_name
                server_bbox = draw.textbbox((0, 0), server_text, font=font_title)
                server_width = server_bbox[2] - server_bbox[0]
                
                # Auto-scale title font if too wide
                temp_font = font_title
                temp_size = title_size
                while server_width > width * 0.9 and temp_size > 10:
                    temp_size -= 2
                    try:
                        temp_font = get_font_with_fallbacks("Capture it", temp_size, "bold")
                    except Exception as fe:
                        print(f"Error loading fallback font for title scaling: {fe}")
                        temp_font = ImageFont.load_default()
                    server_bbox = draw.textbbox((0, 0), server_text, font=temp_font)
                    server_width = server_bbox[2] - server_bbox[0]
                
                font_title = temp_font
                server_x = (width - server_width) // 2
                server_y = int(height * 0.08)
                draw_text_with_outline(server_text, server_x, server_y, font_title)
                print(f"Added server name: {server_text}")
            except Exception as e:
                print(f"Error adding server name: {e}")
            
            # Add Round text (center) - use yellow for emphasis
            try:
                round_text = f"ROUND {round_label}"
                round_bbox = draw.textbbox((0, 0), round_text, font=font_round)
                round_width = round_bbox[2] - round_bbox[0]
                round_x = (width - round_width) // 2
                round_y = int(height * 0.35)
                draw_text_with_outline(round_text, round_x, round_y, font_round, use_yellow=True)
                print(f"Added round text: {round_text}")
            except Exception as e:
                print(f"Error adding round text: {e}")
            
            # Add Captain vs Captain text (center)
            try:
                left_name_text = sanitize_username_for_poster(team1_captain)
                vs_core = " VS "
                right_name_text = sanitize_username_for_poster(team2_captain)

                # Measure text components to center the whole line
                left_box = draw.textbbox((0, 0), left_name_text, font=font_vs)
                vs_box = draw.textbbox((0, 0), vs_core, font=font_vs)
                right_box = draw.textbbox((0, 0), right_name_text, font=font_vs)
                
                total_width = (left_box[2] - left_box[0]) + (vs_box[2] - vs_box[0]) + (right_box[2] - right_box[0])
                
                # Auto-scale font_vs if total width is too wide
                temp_font_vs = font_vs
                temp_vs_size = vs_size
                while total_width > width * 0.95 and temp_vs_size > 10:
                    temp_vs_size -= 2
                    try:
                        temp_font_vs = get_font_with_fallbacks("Capture it", temp_vs_size, "bold")
                    except Exception:
                        temp_font_vs = ImageFont.load_default()
                    left_box = draw.textbbox((0, 0), left_name_text, font=temp_font_vs)
                    vs_box = draw.textbbox((0, 0), vs_core, font=temp_font_vs)
                    right_box = draw.textbbox((0, 0), right_name_text, font=temp_font_vs)
                    total_width = (left_box[2] - left_box[0]) + (vs_box[2] - vs_box[0]) + (right_box[2] - right_box[0])
                
                font_vs = temp_font_vs
                current_x = (width - total_width) // 2
                vs_y = int(height * 0.55)

                # Draw left name
                draw_text_with_outline(left_name_text, current_x, vs_y, font_vs)
                current_x += (left_box[2] - left_box[0])
                
                # Draw VS
                draw_text_with_outline(vs_core, current_x, vs_y, font_vs, use_yellow=False)
                current_x += (vs_box[2] - vs_box[0])
                
                # Draw right name
                draw_text_with_outline(right_name_text, current_x, vs_y, font_vs)
                
                print(f"Added VS text: {left_name_text} VS {right_name_text}")
            except Exception as e:
                print(f"Error adding VS text: {e}")
            
            # Add date (if provided)
            if date_str:
                try:
                    date_text = f"DATE:  {date_str}"
                    date_bbox = draw.textbbox((0, 0), date_text, font=font_time)
                    date_width = date_bbox[2] - date_bbox[0]
                    date_x = (width - date_width) // 2
                    date_y = int(height * 0.72)
                    draw_text_with_outline(date_text, date_x, date_y, font_time)
                    print(f"Added date: {date_text}")
                except Exception as e:
                    print(f"Error adding date: {e}")
            
            # Add UTC time
            try:
                time_text = f"TIME:  {utc_time}"
                time_bbox = draw.textbbox((0, 0), time_text, font=font_time)
                time_width = time_bbox[2] - time_bbox[0]
                time_x = (width - time_width) // 2
                time_y = int(height * 0.82) if date_str else int(height * 0.75)
                draw_text_with_outline(time_text, time_x, time_y, font_time)
                print(f"Added time: {time_text}")
            except Exception as e:
                print(f"Error adding time: {e}")
            
            # Save the modified image
            output_path = os.path.join(BASE_DIR, f"temp_poster_{int(datetime.datetime.now().timestamp())}.png")
            poster.save(output_path, "PNG")
            print(f"Poster saved successfully: {output_path}")
            return output_path
            
    except Exception as e:
        print(f"Critical error creating poster: {e}")
        import traceback
        traceback.print_exc()
        return None

def calculate_time_difference(event_datetime: datetime.datetime, user_timezone: str = None) -> dict:
    """Calculate time difference and format for different timezones"""
    current_time = datetime.datetime.utcnow()
    time_diff = event_datetime - current_time
    minutes_remaining = int(time_diff.total_seconds() / 60)
    
    # Format UTC time exactly as requested
    utc_time_str = event_datetime.strftime("%H:%M utc, %d/%m")
    
    # Try to detect user's local timezone
    local_timezone = None
    if user_timezone:
        try:
            local_timezone = pytz.timezone(user_timezone)
        except:
            pass
    
    # If no user timezone provided, try to detect from system
    if not local_timezone:
        try:
            # Try to get system timezone
            import time
            local_timezone = pytz.timezone(time.tzname[time.daylight])
        except:
            # Fallback to IST if detection fails
            local_timezone = pytz.timezone('Asia/Kolkata')
    
    # Calculate user's local time
    local_time = event_datetime.replace(tzinfo=pytz.UTC).astimezone(local_timezone)
    local_time_formatted = local_time.strftime("%A, %d %B, %Y %H:%M")
    
    # Calculate other common timezones
    ist_tz = pytz.timezone('Asia/Kolkata')
    ist_time = event_datetime.replace(tzinfo=pytz.UTC).astimezone(ist_tz)
    ist_formatted = ist_time.strftime("%A, %d %B, %Y %H:%M")
    
    est_tz = pytz.timezone('America/New_York')
    est_time = event_datetime.replace(tzinfo=pytz.UTC).astimezone(est_tz)
    est_formatted = est_time.strftime("%A, %d %B, %Y %H:%M")
    
    gmt_tz = pytz.timezone('Europe/London')
    gmt_time = event_datetime.replace(tzinfo=pytz.UTC).astimezone(gmt_tz)
    gmt_formatted = gmt_time.strftime("%A, %d %B, %Y %H:%M")
    
    return {
        'minutes_remaining': minutes_remaining,
        'utc_time': utc_time_str,
        'utc_time_simple': event_datetime.strftime("%H:%M UTC"),
        'local_time': local_time_formatted,
        'ist_time': ist_formatted,
        'est_time': est_formatted,
        'gmt_time': gmt_formatted
    }

def has_event_create_permission(interaction):
    """Check if user has permission to create events (Head Organizer, Head Helper or Helper Team)"""
    if interaction.user.id == BOT_OWNER_ID:
        return True
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    if not interaction.guild:
        return False
        
    cfg = get_guild_config(interaction.guild.id)
    role_ids = cfg.get("role_ids", DEFAULT_ROLE_IDS)
    
    def safe_get(key):
        val = role_ids.get(key)
        try:
            return int(val) if val is not None else None
        except:
            return None
            
    head_organizer_id = safe_get("head_organizer")
    head_helper_id = safe_get("head_helper")
    helper_team_id = safe_get("helper_team")
    
    user_role_ids = [r.id for r in interaction.user.roles] if hasattr(interaction.user, "roles") else []
    
    return (
        (head_organizer_id and head_organizer_id in user_role_ids) or
        (head_helper_id and head_helper_id in user_role_ids) or
        (helper_team_id and helper_team_id in user_role_ids)
    )

def has_event_result_permission(interaction):
    if interaction.user.id == BOT_OWNER_ID:
        return True
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    if not interaction.guild:
        return False
        
    cfg = get_guild_config(interaction.guild.id)
    role_ids = cfg.get("role_ids", DEFAULT_ROLE_IDS)
    
    def safe_get(key):
        val = role_ids.get(key)
        try:
            return int(val) if val is not None else None
        except:
            return None
            
    head_organizer_id = safe_get("head_organizer")
    head_helper_id = safe_get("head_helper")
    helper_team_id = safe_get("helper_team")
    judge_id = safe_get("judge")
    recorder_id = safe_get("recorder")
    staff_id = safe_get("staff")
    
    user_role_ids = [r.id for r in interaction.user.roles] if hasattr(interaction.user, "roles") else []
    
    return (
        (head_organizer_id and head_organizer_id in user_role_ids) or
        (head_helper_id and head_helper_id in user_role_ids) or
        (helper_team_id and helper_team_id in user_role_ids) or
        (judge_id and judge_id in user_role_ids) or
        (recorder_id and recorder_id in user_role_ids) or
        (staff_id and staff_id in user_role_ids)
    )

@bot.event
async def on_message(message):
    """Handle auto-response commands for ticket management"""
    if message.guild:
        current_guild_id.set(message.guild.id)
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return
    
    # Only process messages that start with ? or $ and are in specific channels
    if not (message.content.startswith('?') or message.content.startswith('$')):
        return
    
    # Check if the command should be restricted to specific channels
    # For now, allow in all channels, but you can add restrictions here
    # Example: if message.channel.id not in [CHANNEL_IDS["take_schedule"], ...]:
    #     return
    
    # Extract command from message
    command = message.content.lower().strip()
    
    # Handle ticket status commands (?sh, ?dq, ?dd, ?ho, $close, $delete) - modify channel name prefix
    if command in ['?sh', '?dq', '?dd', '?ho', '$close', '$delete']:
        # Check permissions for ticket management commands
        is_owner = message.author.id == BOT_OWNER_ID
        is_admin = message.author.guild_permissions.administrator if hasattr(message.author, 'guild_permissions') else False
        has_role = False
        
        if hasattr(message.author, 'roles'):
            head_org_id = ROLE_IDS.get("head_organizer")
            head_helper_id = ROLE_IDS.get("head_helper")
            helper_team_id = ROLE_IDS.get("helper_team")
            judge_id_val = ROLE_IDS.get("judge")
            recorder_id_val = ROLE_IDS.get("recorder")
            staff_id_val = ROLE_IDS.get("staff")
            head_org = discord.utils.get(message.author.roles, id=head_org_id) if head_org_id else None
            head_helper = discord.utils.get(message.author.roles, id=head_helper_id) if head_helper_id else None
            helper_team = discord.utils.get(message.author.roles, id=helper_team_id) if helper_team_id else None
            judge = discord.utils.get(message.author.roles, id=judge_id_val) if judge_id_val else None
            recorder = discord.utils.get(message.author.roles, id=recorder_id_val) if recorder_id_val else None
            staff = discord.utils.get(message.author.roles, id=staff_id_val) if staff_id_val else None
            has_role = bool(head_org or head_helper or helper_team or judge or recorder or staff)
            
        if not (is_owner or is_admin or has_role):
            # No permission, quietly delete message and return
            try:
                await message.delete()
            except:
                pass
            return
            
        if command == '$close':
            try:
                # Check category constraint
                if message.channel.category_id not in [CHANNEL_IDS.get("category_1"), CHANNEL_IDS.get("category_2")]:
                    try:
                        await message.delete()
                    except:
                        pass
                    return
                
                closed_category_id = CHANNEL_IDS.get("closed_tickets_category", 1492915418556268605)
                closed_category = message.guild.get_channel(closed_category_id)
                
                # Create Transcript
                await message.channel.send("⏳ Generating transcript, please wait...")
                transcript_lines = []
                async for m in message.channel.history(limit=1000, oldest_first=True):
                    time_str = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    content = m.clean_content or "[Attachment/Embed]"
                    transcript_lines.append(f"[{time_str}] {m.author.display_name}: {content}")
                
                transcript_content = "\n".join(transcript_lines)
                
                # Send to current channel
                transcript_file_local = discord.File(io.BytesIO(transcript_content.encode('utf-8')), filename=f"transcript_{message.channel.name}.txt")
                await message.channel.send(f"📄 Transcript of this ticket:", file=transcript_file_local)
                
                # Also send to transcript record channel (active tournament's transcript first, then fallback)
                transcript_channel = None
                try:
                    t_cfg_close = get_active_tournament_config(message.guild.id)
                    if t_cfg_close:
                        trans_ch_id = t_cfg_close.get('transcript') or t_cfg_close.get('transcript_logs')
                        if trans_ch_id:
                            transcript_channel = message.guild.get_channel(int(trans_ch_id))
                except Exception as _tc_err:
                    print(f"Error resolving tournament transcript channel: {_tc_err}")
                
                if not transcript_channel:
                    try:
                        fallback_trans_id = CHANNEL_IDS.get("transcript_logs") or CHANNEL_IDS.get("transcript")
                        if fallback_trans_id:
                            transcript_channel = message.guild.get_channel(int(fallback_trans_id))
                    except Exception as _tc_fallback_err:
                        print(f"Error resolving fallback transcript channel: {_tc_fallback_err}")
                
                if not transcript_channel:
                    transcript_channel = message.guild.get_channel(CHANNEL_IDS.get("results", 1500279846704513074))
                if transcript_channel:
                    transcript_file_record = discord.File(io.BytesIO(transcript_content.encode('utf-8')), filename=f"transcript_{message.channel.name}.txt")
                    await transcript_channel.send(f"📋 Transcript for closed ticket `{message.channel.name}` (closed by {message.author.display_name}):", file=transcript_file_record)
                
                if closed_category:
                    await message.channel.edit(
                        category=closed_category,
                        sync_permissions=True,
                        reason=f"Ticket closed by {message.author.name}"
                    )
                    await message.channel.send("🔒 Ticket closed and moved to the closed category. Use `$delete` to permanently delete it.")
                else:
                    await message.channel.send("❌ Closed ticket category not found.")
                
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"Error closing ticket: {e}")
            return
            
        elif command == '$delete':
            try:
                allowed_cats = [
                    CHANNEL_IDS.get("category_1"), 
                    CHANNEL_IDS.get("category_2"), 
                    CHANNEL_IDS.get("closed_tickets_category", 1492915418556268605)
                ]
                if message.channel.category_id in allowed_cats:
                    await message.channel.delete(reason=f"Ticket deleted by {message.author.name}")
                else:
                    await message.channel.send("❌ This command can only be used in ticket categories.")
            except discord.Forbidden:
                await message.channel.send("❌ I don't have permission to delete this channel.")
            except Exception as e:
                print(f"Error deleting ticket: {e}")
            return

        try:
            # Get the current channel
            channel = message.channel
            
            # Determine the new prefix based on command
            if command == '?sh':
                new_prefix = "🟢"
            elif command == '?dq':
                new_prefix = "🔴"
            elif command == '?dd':
                new_prefix = "✅"
            elif command == '?ho':
                new_prefix = "🟡"
            
            # Get current channel name
            current_name = channel.name
            
            # Remove existing status prefixes if they exist
            clean_name = current_name
            status_prefixes = ["🟢", "🔴", "✅", "🟡"]
            for prefix in status_prefixes:
                if clean_name.startswith(prefix):
                    clean_name = clean_name[len(prefix):].lstrip("-").lstrip()
                    break
            
            # Create new channel name with the status prefix
            new_name = f"{new_prefix}-{clean_name}"
            
            # Update channel name
            await channel.edit(name=new_name)
            
            # Delete the original command message after successful execution
            try:
                await message.delete()
            except discord.Forbidden:
                pass  # Ignore if we can't delete the message
            except Exception:
                pass  # Ignore any other deletion errors
            
        except discord.Forbidden:
            response = await message.channel.send("❌ I don't have permission to edit this channel's name.")
            try:
                await message.delete()
            except:
                pass
        except discord.HTTPException as e:
            response = await message.channel.send(f"❌ Error updating channel name: {e}")
            try:
                await message.delete()
            except:
                pass
        except Exception as e:
            response = await message.channel.send(f"❌ Unexpected error: {e}")
            try:
                await message.delete()
            except:
                pass
        
    elif command == '?b':
        # Challonge URL response
        response = await message.channel.send("https://challonge.com/Pandora_12")
        # Delete the original command message
        try:
            await message.delete()
        except discord.Forbidden:
            pass  # Ignore if we can't delete the message
        except Exception:
            pass  # Ignore any other deletion errors
    
    # Process other bot commands (important for command processing)
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user}")
    print(f"🆔 Bot ID: {bot.user.id}")
    print(f"📊 Connected to {len(bot.guilds)} guild(s)")
    
    # Load scheduled events from file
    load_scheduled_events()
    
    # Load/merge scheduled events from Supabase
    try:
        await load_scheduled_events_from_supabase()
    except Exception as e:
        print(f"Error loading events from Supabase on startup: {e}")
        
    # Resolve member IDs to Member objects
    try:
        await resolve_scheduled_event_members()
    except Exception as e:
        print(f"Error resolving event members on startup: {e}")
    
    # Load scheduled deadlines from Supabase/JSON fallback
    load_scheduled_deadlines()
    
    # Load tournament rules from file
    load_rules()
    
    # Load staff stats from file
    load_staff_stats()
    
    # Reschedule reminders and register persistent views for loaded events
    import pytz
    now_utc = datetime.datetime.now(pytz.UTC)
    for ev_id, ev_data in scheduled_events.items():
        dt = ev_data.get('datetime')
        ch_id = ev_data.get('channel_id')
        
        # Register persistent views for active/recent events on bot startup
        try:
            t1 = ev_data.get('team1_captain')
            t2 = ev_data.get('team2_captain')
            j = ev_data.get('judge')
            r = ev_data.get('recorder')
            
            # Reconstruct and register TakeScheduleButton
            bot.add_view(TakeScheduleButton(ev_id, t1, t2))
            
            # Reconstruct and register StaffConfirmationView
            bot.add_view(StaffConfirmationView(ev_id, j, r))
            
            # Reconstruct and register StaffReplacementView
            bot.add_view(StaffReplacementView(ev_id, True, True))
        except Exception as view_err:
            print(f"Error registering persistent views for event {ev_id} on startup: {view_err}")
            
        if dt and ch_id:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            if dt > now_utc:
                channel = bot.get_channel(ch_id)
                if channel:
                    asyncio.create_task(schedule_ten_minute_reminder(
                        ev_id, 
                        ev_data.get('team1_captain'), 
                        ev_data.get('team2_captain'), 
                        ev_data.get('judge'), 
                        channel, 
                        dt
                    ))
    
    # Reschedule cleanups for any events already marked finished_on if needed (optional)
    try:
        for ev_id, data in list(scheduled_events.items()):
            # If previously scheduled cleanup exists, skip (it won't persist); we don't know result time here
            # Optionally: clean up events older than 7 days to avoid clutter
            try:
                dt = data.get('datetime')
                if isinstance(dt, datetime.datetime):
                    age_days = (datetime.datetime.now() - dt).days
                    if age_days >= 7:
                        # Hard cleanup very old events
                        if ev_id in reminder_tasks:
                            try:
                                reminder_tasks[ev_id].cancel()
                                del reminder_tasks[ev_id]
                            except Exception:
                                pass
                        del scheduled_events[ev_id]
            except Exception:
                pass
        save_scheduled_events()
    except Exception as e:
        print(f"Startup cleanup sweep error: {e}")
        
    # Reschedule deadline reminders on startup
    for dl_id, dl_data in list(scheduled_deadlines.items()):
        dt = dl_data.get('deadline_dt')
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            
            # Check if both reminders have already passed
            deadline_date = dt.date()
            reminder_1_dt = datetime.datetime.combine(deadline_date - datetime.timedelta(days=1), datetime.time(6, 0)).replace(tzinfo=pytz.UTC)
            reminder_2_dt = datetime.datetime.combine(deadline_date, datetime.time(6, 0)).replace(tzinfo=pytz.UTC)
            
            if reminder_1_dt <= now_utc and reminder_2_dt <= now_utc:
                # Both reminders have passed. Clean up obsolete ones older than 7 days
                age_days = (datetime.datetime.now() - dt.replace(tzinfo=None)).days
                if age_days >= 7:
                    if dl_id in scheduled_deadlines:
                        del scheduled_deadlines[dl_id]
            else:
                schedule_deadline_tasks(dl_id)
    # Save any cleanup updates
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
        print(f"Error saving scheduled_deadlines.json on startup: {e}")

    # Start auto-room background loops for all guilds the bot is in
    for guild in bot.guilds:
        try:
            start_auto_room_loop(guild.id)
        except Exception as e:
            print(f"Error starting auto-room loop for guild {guild.id} on startup: {e}")

    # Sync commands with timeout handling
    try:
        print("🔄 Syncing slash commands...")
        import asyncio
        synced = await asyncio.wait_for(tree.sync(), timeout=30.0)
        print(f"✅ Synced {len(synced)} command(s)")
    except asyncio.TimeoutError:
        print("⚠️ Command sync timed out, but bot will continue running")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
        print("⚠️ Bot will continue running without command sync")
    
    print("🎯 Bot is ready to receive commands!")



@tree.command(name="upload-score", description="Upload match score to Challonge bracket (Judge/Organizer only)")
@app_commands.describe(
    winner="Select the match and the winning team from the list",
    winner_score="Score of the winning team (e.g. 2)",
    loser_score="Score of the losing team (e.g. 1)"
)
@with_guild_context
async def upload_score(
    interaction: discord.Interaction,
    winner: str,
    winner_score: int,
    loser_score: int
):
    """Upload a match score to Challonge from Discord using autocomplete."""
    await interaction.response.defer(ephemeral=True)

    if interaction.guild:
        current_guild_id.set(interaction.guild.id)

    # Permission check — Organizer / Bot Owner
    permission_level = get_user_permission_level(interaction.user.roles, interaction.user.id)
    if permission_level not in ["organizer", "owner"]:
        await interaction.followup.send("❌ You need **Head Organizer** role to upload scores.", ephemeral=True)
        return

    # Parse selected winner option
    # Value format (new): match_id:winner_participant_id:team_name:player1_id
    # Value format (legacy): match_id:winner_participant_id:team_name
    try:
        parts = winner.split(":")
        if len(parts) < 3:
            await interaction.followup.send("❌ Invalid selection. Please select a match from the autocomplete dropdown list.", ephemeral=True)
            return
        match_id = parts[0]
        winner_participant_id = parts[1]
        winner_name = parts[2]
        # 4th segment carries player1_id so we can order scores correctly
        player1_id = str(parts[3]) if len(parts) >= 4 else None
    except Exception:
        await interaction.followup.send("❌ Error parsing the selection. Please use the autocomplete list.", ephemeral=True)
        return

    # Resolve bracket link and API key
    bracket_link = None
    api_key = None

    t_cfg = get_active_tournament_config(interaction.guild.id) if interaction.guild else None
    if t_cfg:
        bracket_link = t_cfg.get('challonge_bracket_link') or t_cfg.get('id') or get_bracket_link(interaction)
        api_key = t_cfg.get('key') or get_bracket_api_key(interaction)
    
    if not bracket_link:
        bracket_link = get_bracket_link(interaction)
    if not api_key:
        api_key = get_bracket_api_key(interaction)

    if not bracket_link or not bracket_link.startswith("http"):
        await interaction.followup.send("❌ No bracket link configured. Set one in the tournament configuration.", ephemeral=True)
        return
    if not api_key:
        await interaction.followup.send("❌ No Challonge API key configured. Set one in the tournament configuration.", ephemeral=True)
        return

    # Challonge scores_csv must ALWAYS be "player1_score-player2_score"
    # regardless of who won. Build it based on whether the winner is player1 or player2.
    if player1_id and str(winner_participant_id) == str(player1_id):
        # Winner is player1 → player1 has the higher score
        scores_csv = f"{winner_score}-{loser_score}"
    elif player1_id:
        # Winner is player2 → player1 has the lower score
        scores_csv = f"{loser_score}-{winner_score}"
    else:
        # Legacy fallback (no player1_id info): assume winner_score first
        scores_csv = f"{winner_score}-{loser_score}"

    try:
        success, error = await update_challonge_match(
            bracket_link, api_key, match_id, winner_participant_id, scores_csv
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Error uploading score: `{e}`", ephemeral=True)
        return

    tournament_name = t_cfg.get('name') if t_cfg else get_tournament_name(interaction) or ""

    # Fetch Challonge Logs Channel
    challonge_logs_channel = None
    if t_cfg and t_cfg.get('challonge_logs') and interaction.guild:
        try:
            challonge_logs_channel = interaction.guild.get_channel(int(t_cfg['challonge_logs']))
            if not challonge_logs_channel:
                challonge_logs_channel = await interaction.guild.fetch_channel(int(t_cfg['challonge_logs']))
        except Exception:
            pass

    if success:
        # Log to SheetDB
        asyncio.create_task(sheetdb_post("Challonge_Uploads", {
            "Guild_ID": str(interaction.guild.id) if interaction.guild else "",
            "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "Match_ID": match_id,
            "Winner_Participant_ID": winner_participant_id,
            "Winner_Score": winner_score,
            "Loser_Score": loser_score,
            "Tournament_ID": tournament_name,
            "Uploaded_By_ID": str(interaction.user.id),
            "Uploaded_By_Name": interaction.user.name,
            "Status": "Success"
        }))
        embed = discord.Embed(
            title="✅ Score Uploaded to Challonge",
            description=f"Match updated successfully: **{winner_name}** won!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🏆 Score", value=f"**{winner_score}** – {loser_score}", inline=True)
        embed.add_field(name="🆔 Match ID", value=f"`{match_id}`", inline=True)
        embed.add_field(name="👤 Winner Team", value=f"**{winner_name}** (`{winner_participant_id}`)", inline=True)
        embed.set_footer(text=f"{ORGANIZATION_NAME} • Uploaded by {interaction.user.display_name}")
        await interaction.followup.send(embed=embed, ephemeral=True)

        # Log to challonge_logs channel if configured
        if challonge_logs_channel:
            try:
                await challonge_logs_channel.send(embed=embed)
            except Exception as e:
                print(f"Error sending log to challonge_logs channel: {e}")

        # Log to bot logs channel
        bot_log_embed = discord.Embed(
            title="🏆 Score Uploaded to Challonge",
            description=f"Judge **{interaction.user.display_name}** successfully uploaded match score (Event ID: `{match_id}`): **{winner_name}** won!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        bot_log_embed.add_field(name="Score", value=f"**{winner_score}** – {loser_score}", inline=True)
        bot_log_embed.set_footer(text=f"Uploaded by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, bot_log_embed)
    else:
        # Log to SheetDB
        asyncio.create_task(sheetdb_post("Challonge_Uploads", {
            "Guild_ID": str(interaction.guild.id) if interaction.guild else "",
            "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "Match_ID": match_id,
            "Winner_Participant_ID": winner_participant_id,
            "Winner_Score": winner_score,
            "Loser_Score": loser_score,
            "Tournament_ID": tournament_name,
            "Uploaded_By_ID": str(interaction.user.id),
            "Uploaded_By_Name": interaction.user.name,
            "Status": f"Failed: {error[:100] if error else 'Unknown'}"
        }))
        await interaction.followup.send(f"❌ Challonge rejected the score upload:\n```{error[:500] if error else 'Unknown error'}```", ephemeral=True)

        # Log to challonge_logs channel if configured
        if challonge_logs_channel:
            try:
                fail_embed = discord.Embed(
                    title="❌ Challonge Score Upload Failed",
                    description=f"Failed to update match score on Challonge: **{winner_name}**.",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                fail_embed.add_field(name="🏆 Intended Score", value=f"**{winner_score}** – {loser_score}", inline=True)
                fail_embed.add_field(name="🆔 Match ID", value=f"`{match_id}`", inline=True)
                fail_embed.add_field(name="❌ Error Details", value=f"```{error[:500] if error else 'Unknown error'}```", inline=False)
                fail_embed.set_footer(text=f"Attempted by {interaction.user.display_name}")
                await challonge_logs_channel.send(embed=fail_embed)
            except Exception as e:
                print(f"Error sending fail log to challonge_logs channel: {e}")

        # Log to bot logs channel
        bot_log_embed = discord.Embed(
            title="❌ Score Upload to Challonge Failed",
            description=f"Judge **{interaction.user.display_name}** attempted score upload for (Event ID: `{match_id}`) but it failed.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        bot_log_embed.add_field(name="Error Details", value=f"```{error[:200]}```", inline=False)
        bot_log_embed.set_footer(text=f"Attempted by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, bot_log_embed)


@upload_score.autocomplete('winner')
async def upload_score_winner_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
        
    current_guild_id.set(interaction.guild.id)
    
    t_cfg = get_active_tournament_config(interaction.guild.id)
    if not t_cfg:
        return []
        
    bracket_link = t_cfg.get('challonge_bracket_link') or t_cfg.get('id')
    api_key = t_cfg.get('key')
    
    if not bracket_link or not api_key:
        return []
        
    now = datetime.datetime.now()
    guild_id = interaction.guild.id
    
    matches = []
    cached = CHALLONGE_MATCHES_CACHE.get(guild_id)
    if cached and (now - cached[0]).total_seconds() < 20:
        matches = cached[1]
    else:
        try:
            matches_info, err = await fetch_challonge_open_matches(bracket_link, api_key)
            if matches_info:
                matches = matches_info
                CHALLONGE_MATCHES_CACHE[guild_id] = (now, matches)
            else:
                print(f"[Challonge Autocomplete] Error: {err}")
        except Exception as e:
            print(f"[Challonge Autocomplete] Exception: {e}")
            
    if not matches:
        return []
        
    choices = []
    current_lower = current.lower()
    
    # Check if we are inside a ticket channel and can extract the match ID
    channel_match_id = None
    if interaction.channel and hasattr(interaction.channel, 'topic') and interaction.channel.topic:
        topic = interaction.channel.topic
        m_match = re.search(r'MatchID:([a-zA-Z0-9-_]+)', topic)
        if m_match:
            channel_match_id = m_match.group(1)

    if channel_match_id:
        target_match = None
        for m in matches:
            if str(m.get('id')) == str(channel_match_id):
                target_match = m
                break
        if target_match:
            team1 = target_match.get('team1') or "TBD"
            team2 = target_match.get('team2') or "TBD"
            match_id = target_match.get('id')
            p1_id = target_match.get('player1_id')
            p2_id = target_match.get('player2_id')
            
            # Show simple team/player names
            # Value format: match_id:winner_participant_id:team_name:player1_id
            # The 4th segment (player1_id) lets upload_score build scores_csv in the correct order
            opt1_name = team1
            opt1_val = f"{match_id}:{p1_id}:{team1}:{p1_id}"
            if not current or current_lower in opt1_name.lower():
                choices.append(app_commands.Choice(name=opt1_name[:100], value=opt1_val[:100]))
                
            opt2_name = team2
            opt2_val = f"{match_id}:{p2_id}:{team2}:{p1_id}"
            if not current or current_lower in opt2_name.lower():
                choices.append(app_commands.Choice(name=opt2_name[:100], value=opt2_val[:100]))
            
            if choices:
                return choices

    # Fallback/General search: show teams with opponents in parenthesis
    for m in matches:
        team1 = m.get('team1') or "TBD"
        team2 = m.get('team2') or "TBD"
        match_id = m.get('id')
        p1_id = m.get('player1_id')
        p2_id = m.get('player2_id')
        
        opt1_name = f"{team1} (vs {team2})"
        # Value format: match_id:winner_participant_id:team_name:player1_id
        opt1_val = f"{match_id}:{p1_id}:{team1}:{p1_id}"
        if not current or current_lower in opt1_name.lower():
            choices.append(app_commands.Choice(name=opt1_name[:100], value=opt1_val[:100]))
            
        opt2_name = f"{team2} (vs {team1})"
        opt2_val = f"{match_id}:{p2_id}:{team2}:{p1_id}"
        if not current or current_lower in opt2_name.lower():
            choices.append(app_commands.Choice(name=opt2_name[:100], value=opt2_val[:100]))
            
    return choices[:25]


NOTION_HELP_URL = "https://elated-chartreuse-9a7.notion.site/Tournament-Bot-Help-Guide-37c8a2e4cbdf80af8e87d6a03b7db8e5"

@tree.command(name="help", description="Show all available bot commands and guide")
@with_guild_context
async def help_command(interaction: discord.Interaction):
    """Help command — links to the Notion command guide"""
    try:
        if interaction.guild:
            current_guild_id.set(interaction.guild.id)

        permission_level = get_user_permission_level(
            interaction.user.roles,
            interaction.user.id,
            interaction.guild.id if interaction.guild else None
        )

        badge_map = {
            "owner":     "👑 Bot Owner",
            "organizer": "🏛️ Organiser",
            "helper":    "🛡️ Helper",
            "judge":     "⚖️ Judge",
            "recorder":  "🎥 Recorder",
            "user":      "👤 Member",
        }
        badge = badge_map.get(permission_level, "👤 Member")
        raw_org_name = get_org_name(interaction.guild)
        org_name = raw_org_name if raw_org_name else (interaction.guild.name if interaction.guild else "Tournament Organizer")
        bot_icon = interaction.client.user.display_avatar.url if interaction.client.user.display_avatar else None
        user_icon = interaction.user.display_avatar.url if interaction.user.display_avatar else None

        embed = discord.Embed(
            title="📖 Tournament Bot — Command Guide",
            description=(
                f"⚓ **{org_name}**\n"
                f"══════════════════════════════════════\n"
                f"🔰 **Your Access Level:** {badge}\n\n"
                f"📚 All commands, usage examples and permissions are documented in our **Notion Help Guide**.\n\n"
                f"🔗 **[Click here to open the Help Guide]({NOTION_HELP_URL})**"
            ),
            color=discord.Color(BRAND_COLOR),
            timestamp=discord.utils.utcnow()
        )

        if bot_icon:
            embed.set_thumbnail(url=bot_icon)

        footer_text = f"{org_name} • Help Guide • Requested by {interaction.user.display_name}"
        if user_icon:
            embed.set_footer(text=footer_text, icon_url=user_icon)
        else:
            embed.set_footer(text=footer_text)

        await interaction.response.send_message(embed=embed, ephemeral=False)

        # Log to bot logs channel
        try:
            log_embed = discord.Embed(
                title="📖 Help Command Used",
                description=f"{interaction.user.mention} used `/help` and viewed the command guide.",
                color=discord.Color(BRAND_COLOR),
                timestamp=discord.utils.utcnow()
            )
            log_embed.add_field(name="👤 User", value=f"{interaction.user.display_name} (`{interaction.user.id}`)", inline=True)
            log_embed.add_field(name="🔰 Access Level", value=badge, inline=True)
            log_embed.set_footer(text=f"Help requested by {interaction.user.display_name}")
            await log_bot_activity(interaction.guild, log_embed)
        except Exception as log_err:
            print(f"Error logging help command to bot_logs: {log_err}")

    except Exception as e:
        print(f"Error in help command: {e}")
        await interaction.response.send_message("❌ An error occurred while generating help.", ephemeral=True)

@tree.command(name="staff-leaderboard", description="Display the staff activity leaderboard")
@with_guild_context
async def staff_leaderboard(interaction: discord.Interaction):
    """Rich visual staff leaderboard"""
    try:
        if not staff_stats:
            embed = discord.Embed(
                title=f"📊 Staff Leaderboard — {ORGANIZATION_NAME}",
                description="No staff activity recorded yet. Stats will appear once matches are judged/recorded.",
                color=discord.Color(BRAND_COLOR),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Tracking")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        # Sort by total (desc)
        sorted_staff = sorted(
            staff_stats.items(),
            key=lambda item: item[1].get('total_count', 0),
            reverse=True
        )
        top_staff = sorted_staff[:15]

        # Medal emojis for top 3
        rank_emojis = {1: "🥇", 2: "🥈", 3: "🥉"}

        embed = discord.Embed(
            title="🏆 Staff Activity Leaderboard",
            description=(
                f"**{ORGANIZATION_NAME}**\n"
                "═══════════════════════════\n"
                f"Tracking the top **{len(top_staff)}** most active staff this tournament season."
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )

        # Build a clean visual list (two compact columns)
        left_col  = ""
        right_col = ""

        for i, (user_id, stats) in enumerate(top_staff, 1):
            medal   = rank_emojis.get(i, f"`#{i:>2}`")
            name    = (stats.get('name') or 'Unknown')[:16]
            j_cnt   = stats.get('judge_count', 0)
            r_cnt   = stats.get('recorder_count', 0)
            total   = stats.get('total_count', 0)
            line = f"{medal} **{name}**\n⚖️ {j_cnt}  🎥 {r_cnt}  ✅ {total}\n"
            if i % 2 == 1:
                left_col += line
            else:
                right_col += line

        if left_col:
            embed.add_field(name="👥 Staff (odd)",  value=left_col,  inline=True)
        if right_col:
            embed.add_field(name="👥 Staff (even)", value=right_col, inline=True)

        # Summary stats
        total_matches = sum(s.get('total_count', 0) for _, s in top_staff)
        total_judged  = sum(s.get('judge_count', 0) for _, s in top_staff)
        total_rec     = sum(s.get('recorder_count', 0) for _, s in top_staff)
        embed.add_field(
            name="📈 Tournament Totals",
            value=(
                f"⚖️ **Total Judged:** {total_judged}\n"
                f"🎥 **Total Recorded:** {total_rec}\n"
                f"📊 **Combined Actions:** {total_matches}"
            ),
            inline=False
        )

        embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Leaderboard • ⚖️ Judge  🎥 Recorder  ✅ Total")

        # Show reset button only to organiser / bot owner
        is_owner = interaction.user.id == BOT_OWNER_ID
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        view = JudgeLeaderboardView(show_reset=bool(head_organizer_role or is_owner or is_admin))

        await interaction.response.send_message(embed=embed, view=view)

    except Exception as e:
        print(f"Error in staff-leaderboard command: {e}")
        await interaction.response.send_message("❌ An error occurred while generating the leaderboard.", ephemeral=True)

@tree.command(name="info", description="Display bot information and statistics")
@with_guild_context
async def info_command(interaction: discord.Interaction):
    """Display bot information and server statistics"""
    try:
        # Calculate statistics
        total_members = sum(g.member_count for g in bot.guilds)
        total_channels = sum(len(g.channels) for g in bot.guilds)
        
        # Create embed
        embed = discord.Embed(
            title=f"ℹ️ {ORGANIZATION_NAME} Bot Information",
            description="Tournament management bot for Modern Warships",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        # Bot Information
        embed.add_field(
            name="🤖 Bot Details",
            value=f"**Name:** {bot.user.name}\n"
                  f"**ID:** {bot.user.id}\n"
                  f"**Latency:** {round(bot.latency * 1000)}ms",
            inline=True
        )
        
        # Bot Statistics
        embed.add_field(
            name="📊 Bot Statistics",
            value=f"**Servers:** {len(bot.guilds)}\n"
                  f"**Users:** {total_members:,}\n"
                  f"**Channels:** {total_channels:,}",
            inline=True
        )
        
        # Server Information (if in a guild)
        if interaction.guild:
            embed.add_field(
                name="🏠 Current Server",
                value=f"**Name:** {interaction.guild.name}\n"
                      f"**Members:** {interaction.guild.member_count:,}\n"
                      f"**Created:** {interaction.guild.created_at.strftime('%d/%m/%Y')}",
                inline=True
            )
        
        # Commands Information
        total_commands = len(bot.tree.get_commands())
        embed.add_field(
            name="⚙️ Commands",
            value=f"**Total Commands:** {total_commands}\n"
                  f"**Categories:** Tournament, Event Management, Utility, System",
            inline=False
        )
        
        # Organization Info
        embed.add_field(
            name="🏆 Organization",
            value=f"{ORGANIZATION_NAME}\n"
                  f"Modern Warships Tournament System",
            inline=False
        )
        
        # Set thumbnail to bot avatar
        if bot.user.avatar:
            embed.set_thumbnail(url=bot.user.avatar.url)
        
        embed.set_footer(text=f"Requested by {interaction.user.name}")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)
        print(f"Error in info command: {e}")


    

@tree.command(name="event", description="Event management commands")
@app_commands.describe(
    action="Select the event action to perform"
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="result", value="result")
    ]
)
@with_guild_context
async def event(interaction: discord.Interaction, action: app_commands.Choice[str]):
    """Base event command - this will be handled by subcommands"""
    await interaction.response.send_message(f"Please use `/event {action.value}` with the appropriate parameters.", ephemeral=True)

@tree.command(name="event-create", description="Creates an event (Head Organizer/Head Helper/Helper Team only)")
@app_commands.describe(
    team_1_captain="Captain of team 1",
    team_2_captain="Captain of team 2", 
    hour="Hour of the event (0-23)",
    minute="Minute of the event (0-59)",
    date="Date of the event",
    month="Month of the event",
    round="Round label",
    tournament="Tournament name (e.g. King of the Seas, Summer Cup, etc.)",
    group="Group assignment (A-J) or Winner/Loser",
    team_1_name="Optional name of team 1",
    team_2_name="Optional name of team 2"
)
@app_commands.choices(
    round=[
        app_commands.Choice(name="R1", value="R1"),
        app_commands.Choice(name="R2", value="R2"),
        app_commands.Choice(name="R3", value="R3"),
        app_commands.Choice(name="R4", value="R4"),
        app_commands.Choice(name="R5", value="R5"),
        app_commands.Choice(name="R6", value="R6"),
        app_commands.Choice(name="R7", value="R7"),
        app_commands.Choice(name="R8", value="R8"),
        app_commands.Choice(name="R9", value="R9"),
        app_commands.Choice(name="R10", value="R10"),
        app_commands.Choice(name="Qualifier", value="Qualifier"),
        app_commands.Choice(name="Semi Final", value="Semi Final"),
        app_commands.Choice(name="3rd Place", value="3rd Place"),
        app_commands.Choice(name="Final", value="Final"),
    ],
    group=[
        app_commands.Choice(name="Group A", value="Group A"),
        app_commands.Choice(name="Group B", value="Group B"),
        app_commands.Choice(name="Group C", value="Group C"),
        app_commands.Choice(name="Group D", value="Group D"),
        app_commands.Choice(name="Group E", value="Group E"),
        app_commands.Choice(name="Group F", value="Group F"),
        app_commands.Choice(name="Group G", value="Group G"),
        app_commands.Choice(name="Group H", value="Group H"),
        app_commands.Choice(name="Group I", value="Group I"),
        app_commands.Choice(name="Group J", value="Group J"),
        app_commands.Choice(name="Winner", value="Winner"),
        app_commands.Choice(name="Loser", value="Loser"),
    ]
)
@with_guild_context
async def event_create(
    interaction: discord.Interaction,
    team_1_captain: discord.Member,
    team_2_captain: discord.Member,
    hour: int,
    minute: int,
    date: int,
    month: int,
    round: app_commands.Choice[str],
    tournament: str,
    group: app_commands.Choice[str] = None,
    team_1_name: str = None,
    team_2_name: str = None,
    mode: str = None
):
    """Creates an event with the specified parameters"""
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)
    
    # Defer the response to give us more time for image processing
    await interaction.response.defer(ephemeral=True)
    
    # Check permissions
    if not has_event_create_permission(interaction):
        await interaction.followup.send("❌ You need **Head Organizer**, **Head Helper** or **Helper Team** role to create events.", ephemeral=True)
        return
    
    # Validate input parameters
    if not (0 <= hour <= 23):
        await interaction.followup.send("❌ Hour must be between 0 and 23", ephemeral=True)
        return
    
    if not (1 <= date <= 31):
        await interaction.followup.send("❌ Date must be between 1 and 31", ephemeral=True)
        return

    if not (1 <= month <= 12):
        await interaction.followup.send("❌ Month must be between 1 and 12", ephemeral=True)
        return
            
    if not (0 <= minute <= 59):
        await interaction.followup.send("❌ Minute must be between 0 and 59", ephemeral=True)
        return

    # Generate unique event ID
    event_id = f"event_{int(datetime.datetime.now().timestamp())}"
    
    # Create event datetime
    current_year = datetime.datetime.now().year
    event_datetime = datetime.datetime(current_year, month, date, hour, minute)
    
    # Calculate time differences and format times
    time_info = calculate_time_difference(event_datetime)
    
    # Resolve round label from choice
    round_label = round.value if isinstance(round, app_commands.Choice) else str(round)
    
    # Resolve group label from choice
    group_label = group.value if group and isinstance(group, app_commands.Choice) else None
    
    # Store event data for reminders
    scheduled_events[event_id] = {
        'guild_id': interaction.guild.id if interaction.guild else None,
        'title': f"Round {round_label} Match",
        'datetime': event_datetime,
        'time_str': time_info['utc_time'],
        'date_str': f"{date:02d}/{month:02d}",
        'round': round_label,
        'group': group_label,
        'minutes_left': time_info['minutes_remaining'],
        'tournament': tournament,
        'mode': mode,
        'judge': None,
        'channel_id': interaction.channel.id,
        'team1_captain': team_1_captain,
        'team2_captain': team_2_captain,
        'team1_name': team_1_name,
        'team2_name': team_2_name
    }
    
    print(f"📝 Event {event_id} created internally for {team_1_captain.name} vs {team_2_captain.name}")
    
    # Save events to file
    save_scheduled_events()
    print(f"💾 Event {event_id} saved to file")

    # Log to SheetDB — Events sheet
    asyncio.create_task(sheetdb_post("Events", {
        "Guild_ID":          str(interaction.guild.id) if interaction.guild else "",
        "Timestamp":         datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "Event_ID":          event_id,
        "Tournament":        tournament,
        "Round":             round_label,
        "Group":             group_label or "",
        "Date":              f"{date:02d}/{month:02d}",
        "UTC_Time":          time_info['utc_time'],
        "Team1_Captain_ID":  str(team_1_captain.id),
        "Team1_Captain_Name": team_1_name if team_1_name else team_1_captain.name,
        "Team2_Captain_ID":  str(team_2_captain.id),
        "Team2_Captain_Name": team_2_name if team_2_name else team_2_captain.name,
        "Judge_ID":          "",
        "Judge_Name":        "",
        "Channel_ID":        str(interaction.channel.id),
        "Status":            "Scheduled",
        "Created_By_ID":     str(interaction.user.id),
        "Created_By_Name":   interaction.user.name
    }))
    
    # Get random template image and create poster (exact same as Sample Bot)
    template_image = get_random_template()
    poster_image = None
    
    if template_image:
        try:
            # Create poster with text overlays (exact same as Sample Bot)
            t1_poster = team_1_name if team_1_name else team_1_captain.name
            t2_poster = team_2_name if team_2_name else team_2_captain.name
            cfg = get_guild_config(interaction)
            org_name = cfg.get('organization_name') or (interaction.guild.name if interaction.guild else "Tournament Organizer")
            poster_image = create_event_poster(
                template_image, 
                round_label, 
                t1_poster, 
                t2_poster, 
                time_info['utc_time_simple'],
                f"{date:02d}/{month:02d}/{current_year}",
                server_name=org_name
            )
            if poster_image:
                # Keep poster path for later cleanup/deletion
                scheduled_events[event_id]['poster_path'] = poster_image
                save_scheduled_events()
        except Exception as e:
            print(f"Error creating poster: {e}")
            poster_image = None
    else:
        print("No template images found in Templates folder")
    
    # Try to create a Discord Server Scheduled Event
    scheduled_event = None
    try:
        # We need timezone-aware datetime. event_datetime is naive, representing UTC
        event_datetime_aware = event_datetime.replace(tzinfo=datetime.timezone.utc)
        
        # Just in case the user set a date in the past, make sure start_time is at least 15 seconds in the future
        now_aware = datetime.datetime.now(datetime.timezone.utc)
        if event_datetime_aware <= now_aware:
            event_datetime_aware = now_aware + datetime.timedelta(seconds=15)
            
        end_time_aware = event_datetime_aware + datetime.timedelta(minutes=45) # 45 minutes duration
        
        # Emoji mapping for group letter
        group_emoji = "👥"
        if group_label:
            group_upper = group_label.upper()
            if "GROUP A" in group_upper or "GROUP: A" in group_upper or group_upper == "A":
                group_emoji = "🅰️"
            elif "GROUP B" in group_upper or "GROUP: B" in group_upper or group_upper == "B":
                group_emoji = "🅱️"
            elif "GROUP C" in group_upper:
                group_emoji = "🇨"
            elif "GROUP D" in group_upper:
                group_emoji = "🇩"
            elif "GROUP E" in group_upper:
                group_emoji = "🇪"
            elif "GROUP F" in group_upper:
                group_emoji = "🇫"
            elif "GROUP G" in group_upper:
                group_emoji = "🇬"
            elif "GROUP H" in group_upper:
                group_emoji = "🇭"
            elif "GROUP I" in group_upper:
                group_emoji = "🇮"
            elif "GROUP J" in group_upper:
                group_emoji = "🇯"
                
        description_str = f"🏆 Tournament: {tournament}\n"
        if group_label:
            description_str += f"{group_emoji} Group: {group_label}\n"
        description_str += f"🔄 Round: {format_round_heading(round_label)}"
        
        t1_disp = team_1_name if team_1_name else team_1_captain.name
        t2_disp = team_2_name if team_2_name else team_2_captain.name
        
        image_bytes = None
        if poster_image:
            try:
                with open(poster_image, 'rb') as img_f:
                    image_bytes = img_f.read()
            except Exception as e:
                print(f"Error reading poster image for Discord Scheduled Event: {e}")
                
        try:
            scheduled_event = await interaction.guild.create_scheduled_event(
                name=f"{t1_disp} vs {t2_disp}",
                description=description_str,
                start_time=event_datetime_aware,
                end_time=end_time_aware,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location=interaction.guild.name,
                image=image_bytes
            )
        except Exception as e:
            print(f"Failed to create scheduled event with image, trying without image: {e}")
            scheduled_event = await interaction.guild.create_scheduled_event(
                name=f"{t1_disp} vs {t2_disp}",
                description=description_str,
                start_time=event_datetime_aware,
                end_time=end_time_aware,
                entity_type=discord.EntityType.external,
                privacy_level=discord.PrivacyLevel.guild_only,
                location=interaction.guild.name
            )
        if scheduled_event:
            scheduled_events[event_id]['scheduled_event_id'] = scheduled_event.id
            save_scheduled_events()
            print(f"✅ Discord Scheduled Event created: '{scheduled_event.name}' with ID {scheduled_event.id}")
    except Exception as e:
        print(f"❌ Failed to create Discord Scheduled Event: {e}")
    
    # Create event embed with new format
    t1_disp = team_1_name if team_1_name else team_1_captain.name
    t2_disp = team_2_name if team_2_name else team_2_captain.name
    embed = discord.Embed(
        title="Schedule",
        description=f"🗓️ {t1_disp} VS {t2_disp}",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    thumb_file, is_local_thumb = await resolve_embed_thumbnail(interaction.guild_id, embed, fallback_to_captain_avatar=team_1_captain)

    
    # Tournament and Time Information
    # Create Discord timestamp for automatic timezone conversion (UTC-aware)
    timestamp = int(event_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())
    # Build event details text
    event_details = f"**Tournament:** {tournament}\n"
    if mode:
        event_details += f"**Mode:** {mode}\n"
    event_details += f"**UTC Time:** {time_info['utc_time']}\n"
    event_details += f"**Local Time:** <t:{timestamp}:F> (<t:{timestamp}:R>)\n"
    event_details += f"**Round:** {format_round_heading(round_label)}\n"
    
    # Add group if specified
    if group_label:
        event_details += f"**Group:** {group_label}\n"
    
    event_details += f"**Channel:** {interaction.channel.mention}"
    
    embed.add_field(
        name="📋 Event Details", 
        value=event_details,
        inline=False
    )
    # Add spacing
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    # Captains Section
    captains_text = f"**Captains**\n"
    if team_1_name:
        captains_text += f"- Team1 Captain: {team_1_captain.mention} @{team_1_captain.name} (Team: **{team_1_name}**)\n"
    else:
        captains_text += f"- Team1 Captain: {team_1_captain.mention} @{team_1_captain.name}\n"
        
    if team_2_name:
        captains_text += f"- Team2 Captain: {team_2_captain.mention} @{team_2_captain.name} (Team: **{team_2_name}**)"
    else:
        captains_text += f"- Team2 Captain: {team_2_captain.mention} @{team_2_captain.name}"
    embed.add_field(name="👑 Team Captains", value=captains_text, inline=False)
    
    # Add spacing
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    embed.add_field(name="👤 Created By", value=interaction.user.mention, inline=False)
    
    # Add poster image if available
    files_to_send = []
    if poster_image and os.path.exists(poster_image):
        try:
            with open(poster_image, 'rb') as f:
                poster_data = f.read()
            file_obj = discord.File(
                fp=io.BytesIO(poster_data),
                filename="event_poster.png"
            )
            embed.set_image(url="attachment://event_poster.png")
            files_to_send.append(file_obj)
        except Exception as e:
            print(f"Error loading poster image: {e}")
            
    if is_local_thumb and thumb_file:
        files_to_send.append(thumb_file)
    
    embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
    
    # Create Take Schedule button
    take_schedule_view = TakeScheduleButton(event_id, team_1_captain, team_2_captain, interaction.channel)
    
    # Send confirmation to user
    await interaction.followup.send("✅ Event created and posted to both channels! Reminder will ping captains 10 minutes before start.", ephemeral=True)
    
    # Post in Take-Schedule channel (with button)
    try:
        schedule_channel = interaction.guild.get_channel(CHANNEL_IDS["take_schedule"])
        if schedule_channel:
            staff_role_id = ROLE_IDS.get('staff')
            staff_ping = f"<@&{staff_role_id}>" if staff_role_id else ("<@&" + str(ROLE_IDS['judge']) + ">" if ROLE_IDS.get('judge') else "@Staff")
            if files_to_send:
                # Create copies of files for schedule channel
                schedule_files = []
                for file_obj in files_to_send:
                    file_obj.fp.seek(0)
                    file_data = file_obj.fp.read()
                    schedule_files.append(discord.File(
                        fp=io.BytesIO(file_data),
                        filename=file_obj.filename
                    ))
                schedule_message = await schedule_channel.send(content=staff_ping, embed=embed, files=schedule_files, view=take_schedule_view)
            else:
                schedule_message = await schedule_channel.send(content=staff_ping, embed=embed, view=take_schedule_view)
            
            # Store the message ID for later deletion
            scheduled_events[event_id]['schedule_message_id'] = schedule_message.id
            scheduled_events[event_id]['schedule_channel_id'] = schedule_channel.id
            save_scheduled_events()
        else:
            await interaction.followup.send("⚠️ Could not find Take-Schedule channel.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Could not post in Take-Schedule channel: {e}", ephemeral=True)
    
    # Post in the channel where command was used (without button)
    try:
        if files_to_send:
            # Create copies of files for current channel
            current_files = []
            for file_obj in files_to_send:
                file_obj.fp.seek(0)
                file_data = file_obj.fp.read()
                current_files.append(discord.File(
                    fp=io.BytesIO(file_data),
                    filename=file_obj.filename
                ))
            await interaction.channel.send(embed=embed, files=current_files)
        else:
            await interaction.channel.send(embed=embed)

        # Log event scheduling activity
        try:
            log_embed = discord.Embed(
                title="📅 Event Scheduled",
                description=(
                    f"**Match:** {t1_disp} VS {t2_disp}\n"
                    f"**Tournament:** {tournament}\n"
                    f"**Round:** {round_label}"
                    + (f" ({group_label})" if group_label else "") + "\n"
                    f"**Time:** {time_info['utc_time']} UTC"
                ),
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            log_embed.set_footer(text=f"Scheduled by {interaction.user.display_name}")
            await log_bot_activity(interaction.guild, log_embed)
        except Exception as log_err:
            print(f"Error logging event scheduling to bot_logs: {log_err}")

        # Schedule the 10-minute reminder
        await schedule_ten_minute_reminder(event_id, team_1_captain, team_2_captain, None, interaction.channel, event_datetime)
        
    except Exception as e:
        await interaction.followup.send(f"⚠️ Could not post in current channel: {e}", ephemeral=True)
@tree.command(name="event-result", description="Add event results (Head Organizer/Judge only)")
@app_commands.describe(
    winner="Winner of the event (optional if team name is provided)",
    winner_score="Winner's score",
    loser="Loser of the event (optional if team name is provided)", 
    loser_score="Loser's score",
    tournament="Tournament name (e.g., The Zumwalt S2)",
    round="Round name (e.g., Semi-Final, Final, Quarter-Final)",
    group="Group assignment (A-J) - optional",
    remarks="Remarks about the match (e.g., ggwp, close match)",
    recorder="Staff member who recorded the match (optional)",
    winner_team_name="Optional name of the winning team",
    loser_team_name="Optional name of the losing team",
    disqualified="Optional: Mark winner, loser, or both as disqualified",
    ss_1="Screenshot 1 (upload)",
    ss_2="Screenshot 2 (upload)",
    ss_3="Screenshot 3 (upload)",
    ss_4="Screenshot 4 (upload)",
    ss_5="Screenshot 5 (upload)",
    ss_6="Screenshot 6 (upload)",
    ss_7="Screenshot 7 (upload)",
    ss_8="Screenshot 8 (upload)",
    ss_9="Screenshot 9 (upload)",
    ss_10="Screenshot 10 (upload)",
    ss_11="Screenshot 11 (upload)"
)
@app_commands.choices(
    group=[
        app_commands.Choice(name="Group A", value="Group A"),
        app_commands.Choice(name="Group B", value="Group B"),
        app_commands.Choice(name="Group C", value="Group C"),
        app_commands.Choice(name="Group D", value="Group D"),
        app_commands.Choice(name="Group E", value="Group E"),
        app_commands.Choice(name="Group F", value="Group F"),
        app_commands.Choice(name="Group G", value="Group G"),
        app_commands.Choice(name="Group H", value="Group H"),
        app_commands.Choice(name="Group I", value="Group I"),
        app_commands.Choice(name="Group J", value="Group J"),
        app_commands.Choice(name="Winner", value="Winner"),
        app_commands.Choice(name="Loser", value="Loser"),
    ],
    disqualified=[
        app_commands.Choice(name="Winner Disqualified", value="Winner"),
        app_commands.Choice(name="Loser Disqualified", value="Loser"),
        app_commands.Choice(name="Both Disqualified (0:0)", value="Both"),
    ]
)
@with_guild_context
async def event_result(
    interaction: discord.Interaction,
    winner_score: int,
    loser_score: int,
    tournament: str,
    round: str,
    winner: discord.Member = None,
    loser: discord.Member = None,
    group: app_commands.Choice[str] = None,
    remarks: str = "ggwp",
    recorder: discord.Member = None,
    winner_team_name: str = None,
    loser_team_name: str = None,
    disqualified: app_commands.Choice[str] = None,
    ss_1: discord.Attachment = None,
    ss_2: discord.Attachment = None,
    ss_3: discord.Attachment = None,
    ss_4: discord.Attachment = None,
    ss_5: discord.Attachment = None,
    ss_6: discord.Attachment = None,
    ss_7: discord.Attachment = None,
    ss_8: discord.Attachment = None,
    ss_9: discord.Attachment = None,
    ss_10: discord.Attachment = None,
    ss_11: discord.Attachment = None
):
    """Adds results for an event"""
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)
    
    # Defer the response immediately to avoid timeout issues
    await interaction.response.defer(ephemeral=True)
    
    # Check permissions
    if not has_event_result_permission(interaction):
        await interaction.followup.send("❌ You need **Head Organizer** or **Judge** role to post event results.", ephemeral=True)
        return

    # Check if either winner member or winner team name is provided
    if not winner and not winner_team_name:
        await interaction.followup.send("❌ Please provide either a **Winner Member** or a **Winner Team Name**.", ephemeral=True)
        return
        
    if not loser and not loser_team_name:
        await interaction.followup.send("❌ Please provide either a **Loser Member** or a **Loser Team Name**.", ephemeral=True)
        return

    # Validate scores
    if winner_score < 0 or loser_score < 0:
        await interaction.followup.send("❌ Scores cannot be negative", ephemeral=True)
        return
            
    # Resolve group label from choice
    group_label = group.value if group and isinstance(group, app_commands.Choice) else None
            
    # Determine display names
    w_name = winner_team_name if winner_team_name else (winner.name if winner else "Unknown")
    l_name = loser_team_name if loser_team_name else (loser.name if loser else "Unknown")
    
    w_mention = winner.mention if winner else f"**{winner_team_name}**"
    l_mention = loser.mention if loser else f"**{loser_team_name}**"

    # Resolve disqualified choice
    dq_status = disqualified.value if disqualified and isinstance(disqualified, app_commands.Choice) else disqualified

    w_display_name = w_name
    l_display_name = l_name
    w_display_mention = w_mention
    l_display_mention = l_mention

    if dq_status == "Winner":
        w_display_name = f"{w_name} (Disqualified)"
        w_display_mention = f"{w_mention} (Disqualified)"
    elif dq_status == "Loser":
        l_display_name = f"{l_name} (Disqualified)"
        l_display_mention = f"{l_mention} (Disqualified)"
    elif dq_status == "Both":
        w_display_name = f"{w_name} (Disqualified)"
        w_display_mention = f"{w_mention} (Disqualified)"
        l_display_name = f"{l_name} (Disqualified)"
        l_display_mention = f"{l_mention} (Disqualified)"

    # Try to find corresponding scheduled event to check if it had a mode
    mode = None
    for ev_id, ev_data in scheduled_events.items():
        if ev_data.get('channel_id') == interaction.channel.id:
            mode = ev_data.get('mode')
            break

    # Create results embed matching the exact template format
    embed_description = f"🗓️ {w_display_name} Vs {l_display_name}\n"
    embed_description += f"**Tournament:** {tournament}\n"
    if mode:
        embed_description += f"**Mode:** {mode}\n"
    embed_description += f"**Round:** {format_round_heading(round)}"
    
    # Add group if specified
    if group_label:
        embed_description += f"\n**Group:** {group_label}"
    
    embed = discord.Embed(
        title="Results",
        description=embed_description,
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )

    thumb_file, is_local_thumb = await resolve_embed_thumbnail(interaction.guild.id, embed)

    # Captains Section
    captains_text = f"**Captains**\n"
    captains_text += f"- Team1 Captain: {w_display_mention}" + (f" @{winner.name}" if winner else "") + "\n"
    captains_text += f"- Team2 Captain: {l_display_mention}" + (f" @{loser.name}" if loser else "")
    embed.add_field(name="", value=captains_text, inline=False)
    
    # Results Section
    results_text = f"**Results**\n"
    if dq_status == "Both":
        results_text += f"❌ {w_name} (Disqualified) ({winner_score}) Vs ({loser_score}) {l_name} (Disqualified) ❌"
    elif dq_status == "Winner":
        results_text += f"💀 {w_name} (Disqualified) ({winner_score}) Vs ({loser_score}) {l_name} 🏆"
    elif dq_status == "Loser":
        results_text += f"🏆 {w_name} ({winner_score}) Vs ({loser_score}) {l_name} (Disqualified) 💀"
    else:
        results_text += f"🏆 {w_name} ({winner_score}) Vs ({loser_score}) {l_name} 💀"
    embed.add_field(name="", value=results_text, inline=False)
    
    # Staff Section
    staff_text = f"👨‍⚖️ **Staffs**\n"
    staff_text += f"▪ Judge: {interaction.user.mention}"
    if recorder:
        staff_text += f"\n▪ Recorder: {recorder.mention}"
    embed.add_field(name="", value=staff_text, inline=False)
    
    # Update staff statistics
    update_staff_stats(interaction.user, "judge")
    if recorder:
        update_staff_stats(recorder, "recorder")
    
    # Remarks Section
    embed.add_field(name="📝 Remarks", value=remarks, inline=False)
    
    # Handle screenshots - collect them and send as files (no image embeds)
    screenshots = [ss_1, ss_2, ss_3, ss_4, ss_5, ss_6, ss_7, ss_8, ss_9, ss_10, ss_11]
    files_to_send = []
    screenshot_names = []
    
    # Add local logo file if needed for embed thumbnail
    if is_local_thumb and thumb_file:
        files_to_send.append(thumb_file)
            
    # Find matching scheduled event to fetch its poster
    matching_event = None
    poster_image = None
    
    # Normalizing comparison values
    norm_tournament = tournament.strip().lower()
    norm_round = round.strip().lower()
    norm_group = group_label.strip().lower() if group_label else None
    
    w_cap_id = winner.id if winner else None
    l_cap_id = loser.id if loser else None
    
    w_team = winner_team_name.strip().lower() if winner_team_name else ""
    l_team = loser_team_name.strip().lower() if loser_team_name else ""
    
    def get_member_id(m):
        if m is None:
            return None
        if hasattr(m, 'id'):
            return m.id
        try:
            return int(m)
        except:
            return None

    # Loop to find the matching event
    for ev_id, ev_data in scheduled_events.items():
        if (ev_data.get('tournament') or "").strip().lower() != norm_tournament:
            continue
        if (ev_data.get('round') or "").strip().lower() != norm_round:
            continue
        ev_group = ev_data.get('group')
        norm_ev_group = ev_group.strip().lower() if ev_group else None
        if norm_group != norm_ev_group:
            continue
            
        # Compare captains or team names
        ev_t1_cap_id = get_member_id(ev_data.get('team1_captain'))
        ev_t2_cap_id = get_member_id(ev_data.get('team2_captain'))
        ev_t1_name = (ev_data.get('team1_name') or "").strip().lower()
        ev_t2_name = (ev_data.get('team2_name') or "").strip().lower()
        
        match_captains = False
        if w_cap_id and l_cap_id:
            if (w_cap_id == ev_t1_cap_id and l_cap_id == ev_t2_cap_id) or \
               (w_cap_id == ev_t2_cap_id and l_cap_id == ev_t1_cap_id):
                match_captains = True
        elif w_cap_id:
            if w_cap_id in (ev_t1_cap_id, ev_t2_cap_id):
                match_captains = True
        elif l_cap_id:
            if l_cap_id in (ev_t1_cap_id, ev_t2_cap_id):
                match_captains = True
                
        match_names = False
        if w_team and l_team:
            if (w_team == ev_t1_name and l_team == ev_t2_name) or \
               (w_team == ev_t2_name and l_team == ev_t1_name):
                match_names = True
        elif w_team:
            if w_team in (ev_t1_name, ev_t2_name):
                match_names = True
        elif l_team:
            if l_team in (ev_t1_name, ev_t2_name):
                match_names = True
                
        if match_captains or match_names:
            matching_event = ev_data
            break
            
    # Fallback to single candidate if no direct match by captains/names
    if not matching_event:
        candidates = []
        for ev_id, ev_data in scheduled_events.items():
            ev_t = ev_data.get('tournament') or ""
            ev_r = ev_data.get('round') or ""
            ev_g = ev_data.get('group')
            norm_ev_g = ev_g.strip().lower() if ev_g else None
            if ev_t.strip().lower() == norm_tournament and ev_r.strip().lower() == norm_round and norm_group == norm_ev_g:
                candidates.append(ev_data)
        if len(candidates) == 1:
            matching_event = candidates[0]
            
    if matching_event:
        poster_image = matching_event.get('poster_path')
        
        # Check for recorder_link/judge_link
        rec_link = matching_event.get('recorder_link')
        jdg_link = matching_event.get('judge_link')
        if rec_link or jdg_link:
            links_text = []
            if rec_link:
                links_text.append(f"🎥 **Recorder VOD:** [Link]({rec_link})")
            if jdg_link:
                links_text.append(f"⚖️ **Judge VOD:** [Link]({jdg_link})")
            
            remarks_idx = -1
            for idx, field in enumerate(embed.fields):
                if field.name == "📝 Remarks":
                    remarks_idx = idx
                    break
            if remarks_idx != -1:
                embed.insert_field_at(remarks_idx, name="🎥 Recordings / VODs", value="\n".join(links_text), inline=False)
            else:
                embed.add_field(name="🎥 Recordings / VODs", value="\n".join(links_text), inline=False)
        
    if poster_image and os.path.exists(poster_image):
        try:
            with open(poster_image, 'rb') as f:
                poster_data = f.read()
                poster_file = discord.File(
                    fp=io.BytesIO(poster_data),
                    filename="event_poster.png"
                )
                embed.set_image(url="attachment://event_poster.png")
                files_to_send.append(poster_file)
        except Exception as e:
            print(f"Error loading poster image for result embed: {e}")
    
    for i, screenshot in enumerate(screenshots, 1):
        if screenshot:
            # Create a file object for each screenshot
            try:
                file_data = await screenshot.read()
                file_obj = discord.File(
                    fp=io.BytesIO(file_data),
                    filename=f"SS-{i}_{screenshot.filename}"
                )
                files_to_send.append(file_obj)
                screenshot_names.append(f"SS-{i}")
            except Exception as e:
                print(f"Error processing screenshot {i}: {e}")
    
    # Add screenshot section if any screenshots were provided
    if screenshot_names:
        screenshot_text = f"**Screenshots of Result ({len(screenshot_names)} images)**\n"
        screenshot_text += f"📷 {' • '.join(screenshot_names)}"
        embed.add_field(name="", value=screenshot_text, inline=False)
    
    embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
    
    # Log to SheetDB — Results sheet
    asyncio.create_task(sheetdb_post("Results", {
        "Guild_ID":       str(interaction.guild.id) if interaction.guild else "",
        "Timestamp":      datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "Tournament":     tournament,
        "Round":          round,
        "Group":          group_label or "",
        "Winner_ID":      str(winner.id) if winner else "",
        "Winner_Name":    w_name + (" (Disqualified)" if dq_status in ("Winner", "Both") else ""),
        "Winner_Score":   str(winner_score),
        "Loser_ID":       str(loser.id) if loser else "",
        "Loser_Name":     l_name + (" (Disqualified)" if dq_status in ("Loser", "Both") else ""),
        "Loser_Score":    str(loser_score),
        "Judge_ID":       str(interaction.user.id),
        "Judge_Name":     interaction.user.name,
        "Recorder_ID":    str(recorder.id) if recorder else "",
        "Recorder_Name":  recorder.name if recorder else "",
        "Remarks":        remarks,
        "Screenshots_Count": str(sum(1 for s in [ss_1,ss_2,ss_3,ss_4,ss_5,ss_6,ss_7,ss_8,ss_9,ss_10,ss_11] if s)),
        "Disqualified":   dq_status or "None"
    }))

    # Send confirmation to user
    await interaction.followup.send("✅ Event results posted to Results channel, current channel, and Staff Attendance logged!", ephemeral=True)
    
    # Post in Results channel with screenshots as attachments
    results_posted = False
    results_msg = None
    current_msg = None
    try:
        t_cfg_res = get_active_tournament_config(interaction.guild.id)
        results_channel = None
        if t_cfg_res:
            res_ch_id = t_cfg_res.get('result')
            if res_ch_id:
                results_channel = interaction.guild.get_channel(int(res_ch_id))
        if not results_channel:
            results_channel = interaction.guild.get_channel(CHANNEL_IDS["results"])

        if results_channel:
            if files_to_send:
                # Create copies of files for results channel (files can only be used once)
                results_files = []
                for file_obj in files_to_send:
                    file_obj.fp.seek(0)  # Reset file pointer
                    file_data = file_obj.fp.read()
                    results_files.append(discord.File(
                        fp=io.BytesIO(file_data),
                        filename=file_obj.filename
                    ))
                results_msg = await results_channel.send(embed=embed, files=results_files)
            else:
                results_msg = await results_channel.send(embed=embed)
            results_posted = True
        else:
            await interaction.followup.send("⚠️ Could not find Results channel.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Could not post in Results channel: {e}", ephemeral=True)
    
    # Post in current channel (where command was executed)
    try:
        current_channel = interaction.channel
        res_ch_id_val = results_channel.id if results_channel else CHANNEL_IDS["results"]
        if current_channel and current_channel.id != res_ch_id_val and current_channel.id != CHANNEL_IDS.get("take_schedule"):  # Don't duplicate or post in schedule channel
            if files_to_send:
                # Reset file pointers and create new file objects for current channel
                current_files = []
                for file_obj in files_to_send:
                    file_obj.fp.seek(0)  # Reset file pointer
                    file_data = file_obj.fp.read()
                    current_files.append(discord.File(
                        fp=io.BytesIO(file_data),
                        filename=file_obj.filename
                    ))
                current_msg = await current_channel.send(embed=embed, files=current_files)
            else:
                current_msg = await current_channel.send(embed=embed)
        elif current_channel and current_channel.id == res_ch_id_val and not results_posted:
            # If we're in results channel but posting failed above, try again
            if files_to_send:
                results_msg = await current_channel.send(embed=embed, files=files_to_send)
            else:
                results_msg = await current_channel.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Could not post in current channel: {e}", ephemeral=True)

    # Post staff attendance in Staff Attendance channel
    try:
        t_cfg_att = get_active_tournament_config(interaction.guild.id)
        staff_attendance_channel = None
        if t_cfg_att:
            att_ch_id = t_cfg_att.get('attendance')
            if att_ch_id:
                staff_attendance_channel = interaction.guild.get_channel(int(att_ch_id))
        if not staff_attendance_channel:
            staff_attendance_channel = interaction.guild.get_channel(CHANNEL_IDS["staff_attendance"])

        if staff_attendance_channel:
            att_embed = discord.Embed(
                title="📋 Staff Attendance Log",
                description=(
                    f"🏅 **{w_name}** vs **{l_name}**\n"
                    f"**Tournament:** {tournament}\n"
                    f"**Round:** {round}"
                    + (f"\n**Group:** {group_label}" if group_label else "")
                ),
                color=discord.Color(BRAND_COLOR),
                timestamp=discord.utils.utcnow()
            )
            
            # Winner & Loser display in Attendance
            w_att_text = winner.mention if winner else f"**{w_name}**"
            l_att_text = loser.mention if loser else f"**{l_name}**"
            if dq_status == "Winner":
                w_att_text += " (Disqualified)"
            elif dq_status == "Loser":
                l_att_text += " (Disqualified)"
            elif dq_status == "Both":
                w_att_text += " (Disqualified)"
                l_att_text += " (Disqualified)"

            att_embed.add_field(
                name="🏆 Result",
                value=f"**Winner/Team 1:** {w_att_text} `({winner_score})`\n**Loser/Team 2:** {l_att_text} `({loser_score})`",
                inline=False
            )
            staff_val = f"⚖️ **Judge:** {interaction.user.mention}"
            if recorder:
                staff_val += f"\n🎥 **Recorder:** {recorder.mention}"
            att_embed.add_field(name="👥 Staff on Duty", value=staff_val, inline=False)
            att_embed.add_field(name="📝 Remarks", value=remarks, inline=False)
            att_embed.set_footer(text=f"{ORGANIZATION_NAME} • Attendance")
            await staff_attendance_channel.send(embed=att_embed)
        else:
            print("⚠️ Could not find Staff Attendance channel.")
    except Exception as e:
        print(f"⚠️ Could not post in Staff Attendance channel: {e}")

    # Log event result activity
    try:
        log_embed = discord.Embed(
            title="🏆 Match Result Posted",
            description=(
                f"**Match:** {w_name} vs {l_name}\n"
                f"**Score:** {winner_score} - {loser_score}\n"
                f"**Tournament:** {tournament}\n"
                f"**Round:** {round}"
                + (f" ({group_label})" if group_label else "") + "\n"
                f"**Remarks:** {remarks}"
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Result posted by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception as log_err:
        print(f"Error logging event result: {log_err}")

    # Schedule auto-cleanup of matching events in this channel after 30 minutes
    try:
        current_channel_id = interaction.channel.id if interaction.channel else None
        matching_event_ids = []
        for ev_id, data in scheduled_events.items():
            if data.get('channel_id') == current_channel_id:
                # Optional: further match by captains to be safer
                try:
                    t1_raw = data.get('team1_captain')
                    t2_raw = data.get('team2_captain')
                    
                    t1 = getattr(t1_raw, 'id', t1_raw)
                    if isinstance(t1, str) and t1.isdigit():
                        t1 = int(t1)
                    t2 = getattr(t2_raw, 'id', t2_raw)
                    if isinstance(t2, str) and t2.isdigit():
                        t2 = int(t2)
                    
                    w_id = getattr(winner, 'id', None)
                    l_id = getattr(loser, 'id', None)
                    
                    matches_captains = False
                    if w_id and l_id and t1 and t2:
                        if w_id in (t1, t2) and l_id in (t1, t2):
                            matches_captains = True
                    elif w_name and l_name:
                        t1_cap_name = ""
                        if t1_raw:
                            if hasattr(t1_raw, 'name'):
                                t1_cap_name = t1_raw.name
                            elif isinstance(t1_raw, int) or (isinstance(t1_raw, str) and t1_raw.isdigit()):
                                try:
                                    t1_mem = interaction.guild.get_member(int(t1_raw))
                                    if t1_mem:
                                        t1_cap_name = t1_mem.name
                                except:
                                    pass
                        t1_name = data.get('team1_name') or t1_cap_name
                        
                        t2_cap_name = ""
                        if t2_raw:
                            if hasattr(t2_raw, 'name'):
                                t2_cap_name = t2_raw.name
                            elif isinstance(t2_raw, int) or (isinstance(t2_raw, str) and t2_raw.isdigit()):
                                try:
                                    t2_mem = interaction.guild.get_member(int(t2_raw))
                                    if t2_mem:
                                        t2_cap_name = t2_mem.name
                                except:
                                    pass
                        t2_name = data.get('team2_name') or t2_cap_name
                        
                        if (w_name.lower() in (t1_name.lower(), t2_name.lower())) or (l_name.lower() in (t1_name.lower(), t2_name.lower())):
                            matches_captains = True
                            
                    if matches_captains:
                        matching_event_ids.append(ev_id)
                        
                        # Update the event with result data
                        scheduled_events[ev_id]['result_added'] = True
                        scheduled_events[ev_id]['result_winner'] = winner
                        scheduled_events[ev_id]['result_loser'] = loser
                        scheduled_events[ev_id]['result_winner_score'] = winner_score
                        scheduled_events[ev_id]['result_loser_score'] = loser_score
                        scheduled_events[ev_id]['result_judge'] = interaction.user
                        scheduled_events[ev_id]['result_group'] = group_label
                        scheduled_events[ev_id]['result_remarks'] = remarks
                        
                        if results_msg:
                            scheduled_events[ev_id]['results_message_id'] = results_msg.id
                            scheduled_events[ev_id]['results_channel_id'] = results_msg.channel.id
                        if current_msg:
                            scheduled_events[ev_id]['match_results_message_id'] = current_msg.id
                            scheduled_events[ev_id]['match_results_channel_id'] = current_msg.channel.id
                        
                        print(f"Updated event {ev_id} with result data")
                except Exception as e:
                    print(f"Error updating event {ev_id}: {e}")
                    matching_event_ids.append(ev_id)

        # Save updated events
        if matching_event_ids:
            save_scheduled_events()

        scheduled_any = False
        for ev_id in matching_event_ids:
            # Update the original schedule message title with checkmark
            try:
                event_data = scheduled_events.get(ev_id)
                if event_data:
                    # Cancel/complete Discord Server Scheduled Event
                    scheduled_event_id = event_data.get('scheduled_event_id')
                    if scheduled_event_id:
                        try:
                            scheduled_event = interaction.guild.get_scheduled_event(int(scheduled_event_id))
                            if not scheduled_event:
                                scheduled_event = await interaction.guild.fetch_scheduled_event(int(scheduled_event_id))
                            if scheduled_event:
                                # Try completing, fallback to deleting
                                try:
                                    if scheduled_event.status == discord.EventStatus.scheduled:
                                        try:
                                            await scheduled_event.edit(status=discord.EventStatus.active)
                                        except Exception:
                                            pass
                                    await scheduled_event.edit(status=discord.EventStatus.completed)
                                    print(f"✅ Completed Scheduled Event {scheduled_event_id}")
                                except Exception as status_err:
                                    print(f"Failed to complete event status: {status_err}, trying deletion")
                                    await scheduled_event.delete()
                                    print(f"✅ Deleted Scheduled Event {scheduled_event_id}")
                        except Exception as e:
                            print(f"Error handling scheduled event completion/deletion: {e}")

                    schedule_channel_id = event_data.get('schedule_channel_id')
                    schedule_message_id = event_data.get('schedule_message_id')
                    
                    if schedule_channel_id and schedule_message_id:
                        schedule_channel = interaction.guild.get_channel(schedule_channel_id)
                        if schedule_channel:
                            try:
                                schedule_message = await schedule_channel.fetch_message(schedule_message_id)
                                if schedule_message.embeds:
                                    embed = schedule_message.embeds[0]
                                    # Update title with checkmark
                                    if update_embed_title_with_checkmark(embed):
                                        try:
                                            await schedule_message.edit(embed=embed)
                                            print(f"Updated schedule title with checkmark for event {ev_id}")
                                        except discord.Forbidden:
                                            print(f"Bot doesn't have permission to edit message in channel {schedule_channel.name}")
                                        except Exception as edit_error:
                                            print(f"Error editing schedule message for event {ev_id}: {edit_error}")
                            except discord.NotFound:
                                print(f"Schedule message not found for event {ev_id}")
                            except Exception as e:
                                print(f"Error updating schedule title for event {ev_id}: {e}")
            except Exception as e:
                print(f"Error processing title update for event {ev_id}: {e}")
            
            await schedule_event_cleanup(ev_id, delay_minutes=30)
            scheduled_any = True
        
        # Also update any schedule messages in the current channel
        try:
            current_channel = interaction.channel
            if current_channel:
                # Look for recent messages in current channel that might be schedule messages
                async for message in current_channel.history(limit=50):
                    if message.embeds and message.author == bot.user:
                        embed = message.embeds[0]
                        # Check if this looks like a schedule message with green circle
                        if embed.title and embed.title.startswith("🟢"):
                            # Check if this matches our winner/loser
                            description = embed.description or ""
                            w_search = winner.name if winner else w_name
                            l_search = loser.name if loser else l_name
                            w_mention_search = winner.mention if winner else w_name
                            l_mention_search = loser.mention if loser else l_name
                            
                            if (w_search in description and l_search in description) or \
                               (w_mention_search in description and l_mention_search in description):
                                if update_embed_title_with_checkmark(embed):
                                    try:
                                        await message.edit(embed=embed)
                                        print(f"Updated current channel schedule title with checkmark")
                                    except discord.Forbidden:
                                        print(f"Bot doesn't have permission to edit message in current channel")
                                    except Exception as edit_error:
                                        print(f"Error editing current channel message: {edit_error}")
                                break
        except Exception as e:
            print(f"Error updating current channel schedule title: {e}")

        if scheduled_any:
            await interaction.followup.send("🧹 Auto-cleanup scheduled: Related event(s) and match channel will be removed after 30 minutes.", ephemeral=True)
    except Exception as e:
        print(f"Error scheduling auto-cleanup after results: {e}")

@tree.command(name="time", description="Get a random match time from fixed 30-min slots (10:00-19:00 UTC)")
@with_guild_context
async def time(interaction: discord.Interaction):
    """Pick a random time from 30-minute slots between 10:00 and 19:00 UTC and show all slots."""
    
    import random
    
    # Fixed 30-minute slots from 10:00 to 19:00 UTC (19:00 inclusive, no 19:30)
    slots = [
        "10:00 UTC", "10:30 UTC",
        "11:00 UTC", "11:30 UTC",
        "12:00 UTC", "12:30 UTC",
        "13:00 UTC", "13:30 UTC",
        "14:00 UTC", "14:30 UTC",
        "15:00 UTC", "15:30 UTC",
        "16:00 UTC", "16:30 UTC",
        "17:00 UTC", "17:30 UTC",
        "18:00 UTC", "18:30 UTC",
        "19:00 UTC",
    ]
    
    chosen_time = random.choice(slots)
    
    slots_display = "  ".join(slots)
    
    embed = discord.Embed(
        title="⏰ Match Time (30‑min slots)",
        description=f"**Your random match time:** `{chosen_time}`",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(
        name="🕒 Available Slots",
        value=slots_display,
        inline=False
    )
    embed.add_field(
        name="📅 Range",
        value="From **10:00** to **19:00 UTC** (every 30 minutes)",
        inline=False
    )

    embed.set_footer(text=f"Match Time Generator • {ORGANIZATION_NAME}")
    
    await interaction.response.send_message(embed=embed)

## Removed test-poster command per request


@tree.command(name="available_events", description="List events without a judge assigned (Judges/Organizers)")
@with_guild_context
async def available_events(interaction: discord.Interaction):
    """Show all scheduled events that do not currently have a judge assigned."""
    try:
        is_owner = interaction.user.id == BOT_OWNER_ID if interaction.user else False
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator if (interaction.user and interaction.guild) else False
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"]) if interaction.user else None
        head_helper_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_helper"]) if interaction.user else None
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"]) if interaction.user else None
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"]) if interaction.user else None
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"]) if interaction.user else None
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"]) if interaction.user else None

        if not (head_organizer_role or head_helper_role or helper_team_role or judge_role or recorder_role or staff_role or is_owner or is_admin):
            await interaction.response.send_message("❌ You need Organizer, Helper, Judge, or Staff role to view unassigned events.", ephemeral=True)
            return

        # Build list of unassigned events
        unassigned = []
        for event_id, data in scheduled_events.items():
            if not data.get('judge'):
                unassigned.append((event_id, data))

        # If none, inform
        if not unassigned:
            await interaction.response.send_message("✅ All events currently have a judge assigned.", ephemeral=True)
            return

        # Sort by datetime if present
        try:
            unassigned.sort(key=lambda x: x[1].get('datetime') or datetime.datetime.max)
        except Exception:
            pass

        # Create embed summary
        embed = discord.Embed(
            title="📝 Available Events",
            description="Events without a judge. Use the message link to take the schedule.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )

        # Add up to 25 entries (Discord practical limit for a single embed field block)
        lines = []
        for idx, (ev_id, data) in enumerate(unassigned[:25], start=1):
            round_label = data.get('round', 'Round')
            date_str = data.get('date_str', 'N/A')
            time_str = data.get('time_str', 'N/A')
            ch_id = data.get('schedule_channel_id') or data.get('channel_id')
            msg_id = data.get('schedule_message_id')
            team1 = data.get('team1_captain')
            team2 = data.get('team2_captain')
            team1_name = getattr(team1, 'name', 'Unknown') if team1 else 'Unknown'
            team2_name = getattr(team2, 'name', 'Unknown') if team2 else 'Unknown'

            link = None
            try:
                if interaction.guild and ch_id and msg_id:
                    link = f"https://discord.com/channels/{interaction.guild.id}/{ch_id}/{msg_id}"
            except Exception:
                link = None

            if link:
                line = f"{idx}. {team1_name} vs {team2_name} • {round_label} • {time_str} • {date_str}\n↪ {link}"
            else:
                line = f"{idx}. {team1_name} vs {team2_name} • {round_label} • {time_str} • {date_str}"
            lines.append(line)

        embed.add_field(
            name=f"Available ({len(unassigned)})",
            value="\n\n".join(lines),
            inline=False
        )

        embed.set_footer(text="Use the link to open the original schedule and press Take Schedule.")

        await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as e:
        print(f"Error in available_events: {e}")
        try:
            await interaction.response.send_message("❌ An error occurred while fetching available events.", ephemeral=True)
        except Exception:
            pass

@tree.command(name="reassign", description="Resign from an event and notify other judges to take it")
@with_guild_context
async def reassign_command(interaction: discord.Interaction):
    """Unassign judge from match"""
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)
    permission_level = get_user_permission_level(interaction.user.roles, interaction.user.id)
    if permission_level not in ["judge", "organizer", "owner", "helper"]:
        await interaction.response.send_message("❌ You do not have permission to use /reassign.", ephemeral=True)
        return

    # Find events the user is judging
    user_events = []
    for event_id, event_data in scheduled_events.items():
        judge_val = event_data.get('judge')
        if judge_val:
            try:
                j_id = int(getattr(judge_val, 'id', judge_val))
                if j_id == interaction.user.id:
                    user_events.append((event_id, event_data))
            except (ValueError, TypeError):
                if str(getattr(judge_val, 'id', judge_val)) == str(interaction.user.id):
                    user_events.append((event_id, event_data))

    if not user_events:
        await interaction.response.send_message("❌ You are not assigned to any events.", ephemeral=True)
        return

    class EventReassignView(View):
        def __init__(self):
            super().__init__(timeout=120)

        @discord.ui.select(
            placeholder="Select an event to resign from...",
            options=[
                discord.SelectOption(
                    label=f"Match {idx+1}: {event_data.get('round', 'Round')} — {event_data.get('date_str', '')}",
                    description=f"{event_data.get('time_str', 'Time')} | {event_data.get('tournament', '')}",
                    value=event_id
                )
                for idx, (event_id, event_data) in enumerate(user_events[:25])
            ]
        )
        async def select_event(self, select_interaction: discord.Interaction, select: discord.ui.Select):
            if select_interaction.guild:
                current_guild_id.set(select_interaction.guild.id)
            selected_event_id = select.values[0]
            event_data = scheduled_events.get(selected_event_id)
            if not event_data:
                await select_interaction.response.send_message("❌ Event not found.", ephemeral=True)
                return

            # Block reassign within 20 minutes of event start
            dt = event_data.get('datetime')
            if dt:
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.UTC)
                time_until = dt - datetime.datetime.now(pytz.UTC)
                if 0 < time_until.total_seconds() < 20 * 60:
                    await select_interaction.response.send_message(
                        "❌ Cannot resign — this event starts in less than 20 minutes. Contact an organizer.", ephemeral=True
                    )
                    return

            # Remove judge from event
            old_judge = interaction.user
            event_data['judge'] = None
            remove_judge_assignment(interaction.user.id, selected_event_id)
            save_scheduled_events()

            # Log to SheetDB
            asyncio.create_task(sheetdb_post("JudgeAssignments", {
                "Guild_ID":    str(interaction.guild.id) if interaction.guild else "",
                "Timestamp":   datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "Event_ID":    selected_event_id,
                "Judge_ID":    str(old_judge.id),
                "Judge_Name":  old_judge.name,
                "Tournament":  event_data.get('tournament', ''),
                "Round":       event_data.get('round', ''),
                "Date":        event_data.get('date_str', ''),
                "UTC_Time":    event_data.get('time_str', ''),
                "Action":      "Reassigned (resigned)",
            }))

            # Get schedule channel to update the original message
            sched_ch_id = event_data.get('schedule_channel_id') or event_data.get('channel_id')
            msg_id = event_data.get('schedule_message_id')
            sched_channel = bot.get_channel(sched_ch_id) if sched_ch_id else None

            t1 = event_data.get('team1_captain')
            t2 = event_data.get('team2_captain')
            
            def get_member_safe(val):
                if not val:
                    return None
                if isinstance(val, discord.Member):
                    return val
                try:
                    val_id = int(getattr(val, 'id', val))
                    return select_interaction.guild.get_member(val_id)
                except (ValueError, TypeError):
                    return None
                    
            mem_1 = get_member_safe(t1)
            mem_2 = get_member_safe(t2)
            t1_id = getattr(mem_1, 'id', None) or (int(t1) if isinstance(t1, (int, str)) and str(t1).isdigit() else None)
            t2_id = getattr(mem_2, 'id', None) or (int(t2) if isinstance(t2, (int, str)) and str(t2).isdigit() else None)

            if sched_channel and msg_id:
                try:
                    msg = await sched_channel.fetch_message(msg_id)
                    if msg and msg.embeds:
                        embed = msg.embeds[0]
                        # Remove judge field so it shows as open again
                        remove_field_by_name(embed, "👨‍⚖️ Judge")
                        embed.color = discord.Color.blue()
                        if embed.title and embed.title.startswith("✅"):
                            embed.title = embed.title[1:]
                        # Restore Take Schedule + Record buttons
                        new_view = TakeScheduleButton(selected_event_id, mem_1 or t1, mem_2 or t2, sched_channel)
                        await msg.edit(embed=embed, view=new_view)
                except Exception as e:
                    print(f"Failed to restore schedule message: {e}")

                # Ping judge role in the schedule channel with a rich notification
                t1_ping = f"<@{t1_id}>" if t1_id else "Team 1"
                t2_ping = f"<@{t2_id}>" if t2_id else "Team 2"
                notify_embed = discord.Embed(
                    title="🔄 Judge Needed — Schedule Open",
                    description=(
                        f"**{old_judge.display_name}** has resigned from judging this match.\n\n"
                        f"A replacement judge is required! Please click **Take Schedule** on the event post."
                    ),
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                notify_embed.add_field(
                    name="📋 Match Details",
                    value=(
                        f"**Tournament:** {event_data.get('tournament', 'N/A')}\n"
                        f"**Round:** {event_data.get('round', 'N/A')}\n"
                        f"**Date/Time:** {event_data.get('date_str', '')} at {event_data.get('time_str', '')}\n"
                        f"**Captains:** {t1_ping} vs {t2_ping}"
                    ),
                    inline=False
                )
                notify_embed.set_footer(text=f"{ORGANIZATION_NAME} • Reassign System")
                try:
                    await sched_channel.send(
                        content=f"⚠️ <@&{ROLE_IDS['judge']}> — A judge is needed for this match!",
                        embed=notify_embed
                    )
                except Exception as e:
                    print(f"Error sending reassign notification: {e}")

            await select_interaction.response.send_message(
                f"✅ You have been removed from the schedule. Judges have been notified.", ephemeral=True
            )
            self.stop()

    await interaction.response.send_message(
        "Select the event you want to resign from:", view=EventReassignView(), ephemeral=True
    )


@tree.command(name="event-delete", description="Delete a scheduled event (Head Organizer/Head Helper/Helper Team only)")
@with_guild_context
async def event_delete(interaction: discord.Interaction):
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)
    # Check permissions - only Head Organizer, Head Helper or Helper Team can delete events
    if not has_event_create_permission(interaction):
        await interaction.response.send_message("❌ You need **Head Organizer**, **Head Helper** or **Helper Team** role to delete events.", ephemeral=True)
        return
    
    try:
        # Check if there are any scheduled events
        if not scheduled_events:
            await interaction.response.send_message(f"❌ No scheduled events found to delete.\n\n**Debug Info:**\n• Scheduled events count: {len(scheduled_events)}\n• Events in memory: {list(scheduled_events.keys()) if scheduled_events else 'None'}", ephemeral=True)
            return
        
        def _safe_captain_label(cap, team_name=None):
            """Safely get a display name from a captain value (may be Member, int, or None)."""
            if team_name:
                return team_name
            if cap is None:
                return "Unknown"
            if isinstance(cap, discord.Member):
                return cap.display_name or cap.name
            if isinstance(cap, int) or (isinstance(cap, str) and str(cap).isdigit()):
                member = interaction.guild.get_member(int(cap)) if interaction.guild else None
                return member.display_name if member else f"User#{cap}"
            return str(cap)
        
        # Create dropdown with event names
        class EventDeleteView(View):
            def __init__(self):
                super().__init__(timeout=60)
                
            @discord.ui.select(
                placeholder="Select an event to delete...",
                options=[
                    discord.SelectOption(
                        label=f"{_safe_captain_label(event_data.get('team1_captain'), event_data.get('team1_name'))} VS {_safe_captain_label(event_data.get('team2_captain'), event_data.get('team2_name'))}",
                        description=f"{event_data.get('round', 'Unknown Round')} - {event_data.get('date_str', 'No date')} at {event_data.get('time_str', 'No time')}",
                        value=event_id
                    )
                    for event_id, event_data in list(scheduled_events.items())[:25]  # Discord limit of 25 options
                ]
            )
            async def select_event(self, select_interaction: discord.Interaction, select: discord.ui.Select):
                if select_interaction.guild:
                    current_guild_id.set(select_interaction.guild.id)
                selected_event_id = select.values[0]
                
                # Get event details for confirmation
                event_data = scheduled_events[selected_event_id]
                
                # Delete Discord Server Scheduled Event if exists
                scheduled_event_id_val = event_data.get('scheduled_event_id')
                if scheduled_event_id_val:
                    try:
                        scheduled_event = select_interaction.guild.get_scheduled_event(int(scheduled_event_id_val))
                        if not scheduled_event:
                            scheduled_event = await select_interaction.guild.fetch_scheduled_event(int(scheduled_event_id_val))
                        if scheduled_event:
                            await scheduled_event.delete()
                            print(f"🗑️ Deleted Scheduled Event {scheduled_event_id_val} from event-delete")
                    except Exception as e:
                        print(f"Error deleting scheduled event: {e}")
                
                # Cancel any scheduled reminders
                if selected_event_id in reminder_tasks:
                    reminder_tasks[selected_event_id].cancel()
                    del reminder_tasks[selected_event_id]
                
                # Remove judge assignment if exists
                if 'judge' in event_data and event_data['judge']:
                    judge_raw = event_data['judge']
                    judge_id = getattr(judge_raw, 'id', int(judge_raw) if isinstance(judge_raw, (int, str)) else None)
                    if judge_id:
                        remove_judge_assignment(judge_id, selected_event_id)
                
                # Delete the original schedule message if it exists
                deleted_message = False
                if 'schedule_message_id' in event_data and 'schedule_channel_id' in event_data:
                    try:
                        schedule_channel = select_interaction.guild.get_channel(event_data['schedule_channel_id'])
                        if schedule_channel:
                            schedule_message = await schedule_channel.fetch_message(event_data['schedule_message_id'])
                            await schedule_message.delete()
                            deleted_message = True
                    except discord.NotFound:
                        pass  # Message already deleted
                    except Exception as e:
                        print(f"Error deleting schedule message: {e}")
                
                # Clean up any temporary poster files
                if 'poster_path' in event_data:
                    try:
                        import os
                        if os.path.exists(event_data['poster_path']):
                            os.remove(event_data['poster_path'])
                    except Exception as e:
                        print(f"Error deleting poster file: {e}")
                
                # Remove from scheduled events
                del scheduled_events[selected_event_id]
                
                # Save events to file
                save_scheduled_events()
                
                # Create confirmation embed
                embed = discord.Embed(
                    title="🗑️ Event Deleted",
                    description=f"Event has been successfully deleted.",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                
                embed.add_field(
                    name="📋 Deleted Event Details",
                    value=f"**Title:** {event_data.get('title', 'N/A')}\n**Round:** {event_data.get('round', 'N/A')}\n**Time:** {event_data.get('time_str', 'N/A')}\n**Date:** {event_data.get('date_str', 'N/A')}",
                    inline=False
                )
                
                # Build actions completed list
                actions_completed = [
                    "• Event removed from schedule",
                    "• Reminder cancelled",
                    "• Judge assignment cleared"
                ]
                
                if deleted_message:
                    actions_completed.append("• Original schedule message deleted")
                
                if 'poster_path' in event_data:
                    actions_completed.append("• Temporary poster file cleaned up")
                
                embed.add_field(
                    name="✅ Actions Completed",
                    value="\n".join(actions_completed),
                    inline=False
                )
                
                embed.set_footer(text=f"Event Management • {ORGANIZATION_NAME}")
                
                await select_interaction.response.edit_message(embed=embed, view=None)
        
        # Create initial embed
        embed = discord.Embed(
            title="🗑️ Delete Event",
            description="Select an event from the dropdown below to delete it.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.add_field(
            name="📋 Available Events",
            value=f"Found {len(scheduled_events)} scheduled event(s)",
            inline=False
        )
        
        embed.set_footer(text=f"Event Management • {ORGANIZATION_NAME}")
        
        view = EventDeleteView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)


@tree.command(name='staff-update', description="Update a staff member's match count in the leaderboard")
@app_commands.describe(staff_member='The staff member to update', role='Role to update (judge or recorder)', action='Add, Subtract, or Set the count', amount='The number of matches to add, subtract, or set to')
@app_commands.choices(role=[
    app_commands.Choice(name='Judge', value='judge'),
    app_commands.Choice(name='Recorder', value='recorder')
], action=[
    app_commands.Choice(name='Add (+)', value='add'),
    app_commands.Choice(name='Subtract (-)', value='subtract'),
    app_commands.Choice(name='Set (=)', value='set')
])
@with_guild_context
async def staff_update(interaction: discord.Interaction, staff_member: discord.Member, role: app_commands.Choice[str], action: app_commands.Choice[str], amount: int):
    """Update staff statistics for a specific user"""
    if not has_organizer_permission(interaction):
        await interaction.response.send_message('❌ You need **Head Organizer** role to update staff statistics.', ephemeral=True)
        return

    if amount < 0 and action.value != 'subtract':
        await interaction.response.send_message('❌ Amount cannot be negative.', ephemeral=True)
        return

    global staff_stats
    uid = str(staff_member.id)
    if uid not in staff_stats:
        staff_stats[uid] = {'name': staff_member.display_name, 'judge_count': 0, 'recorder_count': 0, 'last_activity': None}
    else:
        staff_stats[uid]['name'] = staff_member.display_name

    role_key = f'{role.value}_count'
    current_count = staff_stats[uid].get(role_key, 0)
    
    if action.value == 'add':
        new_count = current_count + amount
    elif action.value == 'subtract':
        new_count = max(0, current_count - amount)
    else:
        new_count = max(0, amount)

    staff_stats[uid][role_key] = new_count
    staff_stats[uid]['last_activity'] = datetime.datetime.utcnow().isoformat()
    save_staff_stats()

    # Log manual update to SheetDB
    asyncio.create_task(sheetdb_post("StaffStats", {
        "Guild_ID": str(interaction.guild.id) if interaction.guild else "",
        "Timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "User_ID": uid,
        "Name": staff_member.display_name,
        "Role_Updated": f"{role.value} ({action.value} {amount})",
        "Judge_Count": staff_stats[uid].get("judge_count", 0),
        "Recorder_Count": staff_stats[uid].get("recorder_count", 0),
        "Total_Count": staff_stats[uid].get("judge_count", 0) + staff_stats[uid].get("recorder_count", 0)
    }))

    await interaction.response.send_message(f"✅ Successfully updated **{staff_member.display_name}**'s {role.name} count from {current_count} to **{new_count}**.", ephemeral=False)




@tree.command(name="exchange", description="Exchange a Judge or Recorder for an event")
@app_commands.describe(
    role="Role to exchange",
    old_user="The old staff member removing access from",
    new_user="The new staff member granting access to"
)
@app_commands.choices(role=[
    app_commands.Choice(name="Judge", value="judge"),
    app_commands.Choice(name="Recorder", value="recorder")
])
@with_guild_context
async def exchange(interaction: discord.Interaction, role: app_commands.Choice[str], old_user: discord.Member, new_user: discord.Member):
    permission_level = get_user_permission_level(interaction.user.roles, interaction.user.id, interaction.guild_id)
    if permission_level not in ["helper", "organizer", "owner"]:
        await interaction.response.send_message("❌ You need **Head Organizer**, **Head Helper** or **Helper Team** role to exchange staff.", ephemeral=True)
        return

    current_channel_id = interaction.channel.id
    target_event_ids = []
    
    for ev_id, data in scheduled_events.items():
        if data.get('channel_id') == current_channel_id:
            assigned_val = data.get('judge') if role.value == 'judge' else data.get('recorder')
            assigned_id = getattr(assigned_val, 'id', assigned_val)
            if isinstance(assigned_id, str) and assigned_id.isdigit():
                assigned_id = int(assigned_id)
            if assigned_id == old_user.id:
                target_event_ids.append(ev_id)

    if not target_event_ids:
        await interaction.response.send_message(f"⚠️ No events in this channel are assigned to {old_user.mention} as a {role.name}.", ephemeral=True)
        return

    updated_count = 0
    for ev_id in target_event_ids:
        data = scheduled_events.get(ev_id)
        if not data:
            continue
            
        try:
            await interaction.channel.set_permissions(old_user, overwrite=None)
            await interaction.channel.set_permissions(new_user, view_channel=True, send_messages=True, read_messages=True, embed_links=True, attach_files=True, read_message_history=True)
        except Exception as e:
            print(f"Error setting permissions in exchange: {e}")

        if role.value == 'judge':
            data['judge'] = new_user
            try:
                remove_judge_assignment(old_user.id, ev_id)
            except Exception:
                pass
            add_judge_assignment(new_user.id, ev_id)
        else:
            data['recorder'] = new_user

        save_scheduled_events()
        
        team1 = data.get('team1_captain')
        team2 = data.get('team2_captain')
        current_judge = data.get('judge')
        
        def get_mention_str(val):
            if not val:
                return ""
            val_id = getattr(val, 'id', val)
            if isinstance(val_id, (int, str)) and str(val_id).isdigit():
                return f"<@{val_id}> "
            if hasattr(val, 'mention'):
                return f"{val.mention} "
            return ""
            
        t1_ping = get_mention_str(team1)
        t2_ping = get_mention_str(team2)
        j_ping = get_mention_str(current_judge)
        pings = f"{t1_ping}{t2_ping}{j_ping}".strip()
            
        notify_embed = discord.Embed(
            title="🔄 Staff Exchange Notification",
            description=f"Staff assignment for this match has been updated.\n\n**Role:** {role.name}\n**Old Staff:** {old_user.mention} `@{old_user.name}`\n**New Staff:** {new_user.mention} `@{new_user.name}`\n**Updated by:** {interaction.user.mention}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        channel_mention = interaction.channel.mention
        notify_embed.add_field(
            name="📋 Event",
            value=f"{channel_mention} • Time: {data.get('time_str', '')} • {data.get('round', '')}",
            inline=False
        )
        notify_embed.set_footer(text=f"{ORGANIZATION_NAME} • Match Update")
        
        if pings:
            await interaction.channel.send(content=f"🔔 {pings}", embed=notify_embed)
        else:
            await interaction.channel.send(embed=notify_embed)
            
        updated_count += 1
        
    await interaction.response.send_message(f"✅ {new_user.mention} is now the **{role.name}** for {updated_count} event(s), replacing {old_user.mention}.", ephemeral=True)


async def update_results_embed_with_links(guild: discord.Guild, event_data: dict):
    rec_link = event_data.get('recorder_link')
    jdg_link = event_data.get('judge_link')
    if not rec_link and not jdg_link:
        return
        
    links_text = []
    if rec_link:
        links_text.append(f"🎥 **Recorder VOD:** [Link]({rec_link})")
    if jdg_link:
        links_text.append(f"⚖️ **Judge VOD:** [Link]({jdg_link})")
        
    value_text = "\n".join(links_text)
    
    # 1. Update results channel message
    res_ch_id = event_data.get('results_channel_id')
    res_msg_id = event_data.get('results_message_id')
    if res_ch_id and res_msg_id:
        try:
            channel = guild.get_channel(int(res_ch_id))
            if not channel:
                channel = await guild.fetch_channel(int(res_ch_id))
            if channel:
                msg = await channel.fetch_message(int(res_msg_id))
                if msg and msg.embeds:
                    embed = msg.embeds[0]
                    # Update embed fields
                    recording_field_index = -1
                    for idx, field in enumerate(embed.fields):
                        if field.name == "🎥 Recordings / VODs":
                            recording_field_index = idx
                            break
                    if recording_field_index != -1:
                        embed.set_field_at(recording_field_index, name="🎥 Recordings / VODs", value=value_text, inline=False)
                    else:
                        remarks_field_index = -1
                        for idx, field in enumerate(embed.fields):
                            if field.name == "📝 Remarks":
                                remarks_field_index = idx
                                break
                        if remarks_field_index != -1:
                            embed.insert_field_at(remarks_field_index, name="🎥 Recordings / VODs", value=value_text, inline=False)
                        else:
                            embed.add_field(name="🎥 Recordings / VODs", value=value_text, inline=False)
                    await msg.edit(embed=embed)
        except Exception as e:
            print(f"Error updating results channel message with links: {e}")
            
    # 2. Update match channel results message
    match_ch_id = event_data.get('match_results_channel_id')
    match_msg_id = event_data.get('match_results_message_id')
    if match_ch_id and match_msg_id:
        try:
            channel = guild.get_channel(int(match_ch_id))
            if not channel:
                channel = await guild.fetch_channel(int(match_ch_id))
            if channel:
                msg = await channel.fetch_message(int(match_msg_id))
                if msg and msg.embeds:
                    embed = msg.embeds[0]
                    # Update embed fields
                    recording_field_index = -1
                    for idx, field in enumerate(embed.fields):
                        if field.name == "🎥 Recordings / VODs":
                            recording_field_index = idx
                            break
                    if recording_field_index != -1:
                        embed.set_field_at(recording_field_index, name="🎥 Recordings / VODs", value=value_text, inline=False)
                    else:
                        remarks_field_index = -1
                        for idx, field in enumerate(embed.fields):
                            if field.name == "📝 Remarks":
                                remarks_field_index = idx
                                break
                        if remarks_field_index != -1:
                            embed.insert_field_at(remarks_field_index, name="🎥 Recordings / VODs", value=value_text, inline=False)
                        else:
                            embed.add_field(name="🎥 Recordings / VODs", value=value_text, inline=False)
                    await msg.edit(embed=embed)
        except Exception as e:
            print(f"Error updating match channel results message with links: {e}")


# ===========================================================================================
# ADD RECORD LINK COMMAND
# ===========================================================================================

@tree.command(name="add-record-link", description="Add a recording/VOD link for a match event (Recorder, Judge, or Helper)")
@app_commands.describe(
    link_type="Choose what type of link you are adding",
    event_name="The event or match name this recording belongs to (e.g. TeamA vs TeamB R1)",
    link="The recording link to paste (e.g. YouTube, Google Drive, etc.)"
)
@app_commands.choices(link_type=[
    app_commands.Choice(name="Add Recorder Link", value="recorder"),
    app_commands.Choice(name="Add Judge Link", value="judge"),
])
@with_guild_context
async def add_record_link(
    interaction: discord.Interaction,
    link_type: app_commands.Choice[str],
    event_name: str,
    link: str
):
    """Allow Recorder, Judge, or Helper to submit a recording or VOD link for a match."""
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)

    # Permission check — Recorder, Judge, Helper, Organizer, or Bot Owner
    is_owner = interaction.user.id == BOT_OWNER_ID
    is_admin = interaction.guild and interaction.user.guild_permissions.administrator
    cfg = get_guild_config(interaction.guild.id if interaction.guild else None)
    role_ids = cfg.get("role_ids", DEFAULT_ROLE_IDS)

    def safe_role_id(key):
        val = role_ids.get(key)
        try:
            return int(val) if val is not None else None
        except (ValueError, TypeError):
            return None

    user_role_ids = [r.id for r in interaction.user.roles] if hasattr(interaction.user, "roles") else []
    allowed_roles = [
        safe_role_id("recorder"),
        safe_role_id("judge"),
        safe_role_id("helper_team"),
        safe_role_id("head_organizer"),
        safe_role_id("organizer"),
        safe_role_id("staff"),
    ]
    has_role = any(rid and rid in user_role_ids for rid in allowed_roles)

    if not (is_owner or is_admin or has_role):
        await interaction.response.send_message(
            "❌ You need **Recorder**, **Judge**, **Helper**, or **Organizer** role to add a record link.",
            ephemeral=True
        )
        return

    # Basic URL validation
    link_stripped = link.strip()
    if not (link_stripped.startswith("http://") or link_stripped.startswith("https://")):
        await interaction.response.send_message(
            "❌ Please provide a valid URL starting with `http://` or `https://`.",
            ephemeral=True
        )
        return

    # Determine label and emoji based on link_type
    if link_type.value == "recorder":
        link_label = "🎥 Recorder Link"
        link_emoji = "🎥"
        role_label = "Recorder"
    else:
        link_label = "⚖️ Judge Link"
        link_emoji = "⚖️"
        role_label = "Judge"

    # Try to find a matching event in scheduled_events to attach the link to
    matched_event_id = None
    for ev_id, ev_data in scheduled_events.items():
        ev_name_stored = ev_data.get("tournament", "") + " " + ev_data.get("round", "")
        t1 = ev_data.get("team1_captain")
        t2 = ev_data.get("team2_captain")
        t1_name = getattr(t1, "display_name", str(t1)) if t1 else ""
        t2_name = getattr(t2, "display_name", str(t2)) if t2 else ""
        # Match on any part of the event name provided
        search_str = event_name.lower()
        if (
            search_str in ev_name_stored.lower()
            or search_str in t1_name.lower()
            or search_str in t2_name.lower()
            or t1_name.lower() in search_str
            or t2_name.lower() in search_str
        ):
            matched_event_id = ev_id
            break

    # Also try matching against current channel's event
    if not matched_event_id and interaction.channel:
        for ev_id, ev_data in scheduled_events.items():
            if ev_data.get("channel_id") == interaction.channel.id:
                matched_event_id = ev_id
                break

    # Store the link on the event if found
    if matched_event_id and matched_event_id in scheduled_events:
        key = "recorder_link" if link_type.value == "recorder" else "judge_link"
        scheduled_events[matched_event_id][key] = link_stripped
        save_scheduled_events()
        event_saved_note = f"\n✅ Link saved to event record **`{matched_event_id}`**."
        
        # Edit already posted result messages if results were already added
        if scheduled_events[matched_event_id].get('result_added'):
            try:
                await update_results_embed_with_links(interaction.guild, scheduled_events[matched_event_id])
                event_saved_note += "\n✅ Posted result embeds have been updated with the new link."
            except Exception as e:
                print(f"Error updating result embeds with links in add_record_link: {e}")
    else:
        event_saved_note = "\n⚠️ No matching event was found in schedule — link logged here only."

    # Build embed response
    embed = discord.Embed(
        title=f"{link_emoji} {link_label} Added",
        description=(
            f"**Event / Match:** {event_name}\n"
            f"**Submitted by:** {interaction.user.mention} ({role_label})\n"
            f"**Link:** {link_stripped}"
        ),
        color=discord.Color.blurple() if link_type.value == "recorder" else discord.Color.orange(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="📋 Details", value=f"**Role:** {role_label}\n**Event Name:** {event_name}{event_saved_note}", inline=False)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Record Link System • {interaction.user.display_name}")

    # Post publicly in the current channel so all staff can see
    await interaction.response.send_message(embed=embed)

    # Also log to bot activity log
    try:
        log_embed = discord.Embed(
            title=f"{link_emoji} Record Link Added",
            description=(
                f"**{role_label}** {interaction.user.display_name} submitted a {role_label.lower()} link.\n"
                f"**Event:** {event_name}\n"
                f"**Link:** {link_stripped}"
            ),
            color=discord.Color.blurple() if link_type.value == "recorder" else discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Submitted by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception as log_err:
        print(f"Error logging record link: {log_err}")


@tree.command(name="event-edit", description="Edit the event in this ticket channel (Head Organizer/Head Helper/Helper Team only)")
@app_commands.describe(
    team_1_captain="Captain of team 1 (optional)",
    team_2_captain="Captain of team 2 (optional)", 
    hour="Hour of the event (0-23) (optional)",
    minute="Minute of the event (0-59) (optional)",
    date="Date of the event (optional)",
    month="Month of the event (optional)",
    round="Round label (optional)",
    tournament="Tournament name (optional)",
    group="Group assignment (A-J) or Winner/Loser (optional)",
    team_1_name="Optional name of team 1 (optional)",
    team_2_name="Optional name of team 2 (optional)"
)
@app_commands.choices(
    round=[
        app_commands.Choice(name="R1", value="R1"),
        app_commands.Choice(name="R2", value="R2"),
        app_commands.Choice(name="R3", value="R3"),
        app_commands.Choice(name="R4", value="R4"),
        app_commands.Choice(name="R5", value="R5"),
        app_commands.Choice(name="R6", value="R6"),
        app_commands.Choice(name="R7", value="R7"),
        app_commands.Choice(name="R8", value="R8"),
        app_commands.Choice(name="R9", value="R9"),
        app_commands.Choice(name="R10", value="R10"),
        app_commands.Choice(name="Qualifier", value="Qualifier"),
        app_commands.Choice(name="Semi Final", value="Semi Final"),
        app_commands.Choice(name="3rd Place", value="3rd Place"),
        app_commands.Choice(name="Final", value="Final"),
    ],
    group=[
        app_commands.Choice(name="Group A", value="Group A"),
        app_commands.Choice(name="Group B", value="Group B"),
        app_commands.Choice(name="Group C", value="Group C"),
        app_commands.Choice(name="Group D", value="Group D"),
        app_commands.Choice(name="Group E", value="Group E"),
        app_commands.Choice(name="Group F", value="Group F"),
        app_commands.Choice(name="Group G", value="Group G"),
        app_commands.Choice(name="Group H", value="Group H"),
        app_commands.Choice(name="Group I", value="Group I"),
        app_commands.Choice(name="Group J", value="Group J"),
        app_commands.Choice(name="Winner", value="Winner"),
        app_commands.Choice(name="Loser", value="Loser"),
    ]
)
@with_guild_context
async def event_edit(
    interaction: discord.Interaction,
    team_1_captain: discord.Member = None,
    team_2_captain: discord.Member = None,
    hour: int = None,
    minute: int = None,
    date: int = None,
    month: int = None,
    round: app_commands.Choice[str] = None,
    tournament: str = None,
    group: app_commands.Choice[str] = None,
    team_1_name: str = None,
    team_2_name: str = None,
    mode: str = None
):
    """Edit the event in this ticket channel"""
    if interaction.guild:
        current_guild_id.set(interaction.guild.id)
    
    # Defer the response to give us more time for processing
    await interaction.response.defer(ephemeral=True)
    
    # Check permissions - Bot Owner, Head Organizer, Head Helper or Helper Team can edit events
    if interaction.user.id != BOT_OWNER_ID:
        if not has_event_create_permission(interaction):
            await interaction.followup.send("❌ You need **Bot Owner**, **Head Organizer**, **Head Helper** or **Helper Team** role to edit events.", ephemeral=True)
            return
    
    # Find event in current channel
    current_channel_id = interaction.channel.id
    event_to_edit = None
    event_id = None
    
    for ev_id, event_data in scheduled_events.items():
        if event_data.get('channel_id') == current_channel_id:
            event_to_edit = event_data
            event_id = ev_id
            break
    
    if not event_to_edit:
        await interaction.followup.send("❌ No event found in this ticket channel. Use `/event-create` to create an event first.", ephemeral=True)
        return
    
    # Check if at least one field is provided
    if not any([team_1_captain, team_2_captain, hour is not None, minute is not None, date is not None, month is not None, round, tournament, group, team_1_name is not None, team_2_name is not None, mode is not None]):
        await interaction.followup.send("❌ Please provide at least one field to update.", ephemeral=True)
        return
    
    # Validate input parameters only if provided
    if hour is not None and not (0 <= hour <= 23):
        await interaction.followup.send("❌ Hour must be between 0 and 23", ephemeral=True)
        return
    
    if date is not None and not (1 <= date <= 31):
        await interaction.followup.send("❌ Date must be between 1 and 31", ephemeral=True)
        return

    if month is not None and not (1 <= month <= 12):
        await interaction.followup.send("❌ Month must be between 1 and 12", ephemeral=True)
        return
            
    if minute is not None and not (0 <= minute <= 59):
        await interaction.followup.send("❌ Minute must be between 0 and 59", ephemeral=True)
        return

    try:
        # Get current event data
        current_datetime = event_to_edit.get('datetime', datetime.datetime.now())
        current_hour = hour if hour is not None else current_datetime.hour
        current_minute = minute if minute is not None else current_datetime.minute
        current_date = date if date is not None else current_datetime.day
        current_month = month if month is not None else current_datetime.month
        
        # Create new datetime
        current_year = datetime.datetime.now().year
        new_datetime = datetime.datetime(current_year, current_month, current_date, current_hour, current_minute)
        
        # Calculate time differences
        time_info = calculate_time_difference(new_datetime)
        
        # Update only provided fields
        if team_1_captain:
            event_to_edit['team1_captain'] = team_1_captain
        if team_2_captain:
            event_to_edit['team2_captain'] = team_2_captain
        if team_1_name is not None:
            event_to_edit['team1_name'] = team_1_name
        if team_2_name is not None:
            event_to_edit['team2_name'] = team_2_name
            
        if hour is not None or minute is not None or date is not None or month is not None:
            event_to_edit['datetime'] = new_datetime
            event_to_edit['time_str'] = time_info['utc_time']
            event_to_edit['date_str'] = f"{current_date:02d}/{current_month:02d}"
            event_to_edit['minutes_left'] = time_info['minutes_remaining']
            
        if round:
            round_label = round.value if isinstance(round, app_commands.Choice) else str(round)
            event_to_edit['round'] = round_label
        if tournament:
            event_to_edit['tournament'] = tournament
        if group:
            event_to_edit['group'] = group.value
        if mode is not None:
            event_to_edit['mode'] = mode
        
        # Save updated events
        save_scheduled_events()
        
        # Get updated event details for public posting and reminders
        t1_cap = event_to_edit.get('team1_captain')
        t2_cap = event_to_edit.get('team2_captain')
        
        # Resolve names safely for display (handles both Member objects and IDs)
        async def resolve_member_name_and_ping(cap):
            if not cap:
                return "Unknown", "Unknown"
            if isinstance(cap, discord.Member):
                return cap.name, cap.mention
            if isinstance(cap, int) or (isinstance(cap, str) and cap.isdigit()):
                try:
                    u = interaction.guild.get_member(int(cap)) or await bot.fetch_user(int(cap))
                    if u:
                        return u.name, u.mention
                except Exception:
                    pass
            return "Unknown", f"<@{cap}>"
            
        t1_name, t1_mention = await resolve_member_name_and_ping(t1_cap)
        t2_name, t2_mention = await resolve_member_name_and_ping(t2_cap)
        
        # Schedule/Reschedule the 10-minute reminder with updated event data
        try:
            # Resolve to final Member objects defensively for scheduling
            t1_cap_member = t1_cap if isinstance(t1_cap, discord.Member) else interaction.guild.get_member(int(t1_cap)) if isinstance(t1_cap, int) or (isinstance(t1_cap, str) and t1_cap.isdigit()) else None
            t2_cap_member = t2_cap if isinstance(t2_cap, discord.Member) else interaction.guild.get_member(int(t2_cap)) if isinstance(t2_cap, int) or (isinstance(t2_cap, str) and t2_cap.isdigit()) else None
            judge_cap_member = event_to_edit.get('judge')
            if judge_cap_member and not isinstance(judge_cap_member, discord.Member):
                judge_cap_member = interaction.guild.get_member(int(judge_cap_member)) if isinstance(judge_cap_member, int) or (isinstance(judge_cap_member, str) and judge_cap_member.isdigit()) else None
                
            await schedule_ten_minute_reminder(event_id, t1_cap_member, t2_cap_member, judge_cap_member, interaction.channel, new_datetime)
        except Exception as e:
            print(f"Error scheduling reminder for updated event {event_id}: {e}")
        
        round_info = event_to_edit.get('round', 'Unknown')
        tournament_info = event_to_edit.get('tournament', 'Unknown')
        time_info_display = event_to_edit.get('time_str', 'Unknown')
        date_info_display = event_to_edit.get('date_str', 'Unknown')
        group_info = event_to_edit.get('group', '')
        
        # Recreate poster
        poster_image = None
        template_image = get_random_template()
        if template_image:
            try:
                # Clean up old poster first
                old_poster = event_to_edit.get('poster_path')
                if old_poster and os.path.exists(old_poster):
                    try:
                        os.remove(old_poster)
                    except Exception as e:
                        print(f"Error removing old poster: {e}")
                
                t1_poster = event_to_edit.get('team1_name') or t1_name
                t2_poster = event_to_edit.get('team2_name') or t2_name
                cfg = get_guild_config(interaction)
                org_name = cfg.get('organization_name') or (interaction.guild.name if interaction.guild else "Tournament Organizer")
                poster_image = create_event_poster(
                    template_image,
                    round_info,
                    t1_poster,
                    t2_poster,
                    time_info['utc_time_simple'],
                    f"{new_datetime.day:02d}/{new_datetime.month:02d}/{new_datetime.year}",
                    server_name=org_name
                )
                if poster_image:
                    event_to_edit['poster_path'] = poster_image
                    save_scheduled_events()
            except Exception as e:
                print(f"Error creating updated poster: {e}")

        # Update Discord Scheduled Event if it exists
        scheduled_event_id = event_to_edit.get('scheduled_event_id')
        if scheduled_event_id:
            try:
                scheduled_event = interaction.guild.get_scheduled_event(int(scheduled_event_id))
                if not scheduled_event:
                    scheduled_event = await interaction.guild.fetch_scheduled_event(int(scheduled_event_id))
                
                if scheduled_event:
                    t1_disp = event_to_edit.get('team1_name') or t1_name
                    t2_disp = event_to_edit.get('team2_name') or t2_name
                    
                    group_emoji = "👥"
                    if group_info:
                        group_upper = group_info.upper()
                        if "GROUP A" in group_upper or "GROUP: A" in group_upper or group_upper == "A":
                            group_emoji = "🅰️"
                        elif "GROUP B" in group_upper or "GROUP: B" in group_upper or group_upper == "B":
                            group_emoji = "🅱️"
                        elif "GROUP C" in group_upper:
                            group_emoji = "🇨"
                        elif "GROUP D" in group_upper:
                            group_emoji = "🇩"
                        elif "GROUP E" in group_upper:
                            group_emoji = "🇪"
                        elif "GROUP F" in group_upper:
                            group_emoji = "🇫"
                        elif "GROUP G" in group_upper:
                            group_emoji = "🇬"
                        elif "GROUP H" in group_upper:
                            group_emoji = "🇭"
                        elif "GROUP I" in group_upper:
                            group_emoji = "🇮"
                        elif "GROUP J" in group_upper:
                            group_emoji = "🇯"
                    
                    description_str = f"🏆 Tournament: {tournament_info}\n"
                    if group_info:
                        description_str += f"{group_emoji} Group: {group_info}\n"
                    description_str += f"🔄 Round: {format_round_heading(round_info)}"
                    
                    event_datetime_aware = new_datetime.replace(tzinfo=datetime.timezone.utc)
                    now_aware = datetime.datetime.now(datetime.timezone.utc)
                    if event_datetime_aware <= now_aware:
                        event_datetime_aware = now_aware + datetime.timedelta(seconds=15)
                    end_time_aware = event_datetime_aware + datetime.timedelta(minutes=45)
                    
                    image_bytes = None
                    if poster_image:
                        try:
                            with open(poster_image, 'rb') as img_f:
                                image_bytes = img_f.read()
                        except Exception as e:
                            print(f"Error reading updated poster image: {e}")
                    
                    try:
                        kwargs = {
                            "name": f"{t1_disp} vs {t2_disp}",
                            "description": description_str,
                            "start_time": event_datetime_aware,
                            "end_time": end_time_aware,
                            "location": interaction.guild.name
                        }
                        if image_bytes:
                            kwargs["image"] = image_bytes
                            
                        await scheduled_event.edit(**kwargs)
                    except Exception as e:
                        print(f"Failed to edit scheduled event with image, trying without: {e}")
                        await scheduled_event.edit(
                            name=f"{t1_disp} vs {t2_disp}",
                            description=description_str,
                            start_time=event_datetime_aware,
                            end_time=end_time_aware,
                            location=interaction.guild.name
                        )
                    print(f"✅ Discord Scheduled Event updated: ID {scheduled_event.id}")
            except Exception as e:
                print(f"❌ Failed to update Discord Scheduled Event: {e}")

        # Update the `#take-schedule` message
        take_schedule_view = TakeScheduleButton(
            event_id, 
            t1_cap_member if t1_cap_member else t1_cap, 
            t2_cap_member if t2_cap_member else t2_cap, 
            interaction.channel
        )
        
        t1_disp = event_to_edit.get('team1_name') or t1_name
        t2_disp = event_to_edit.get('team2_name') or t2_name
        
        schedule_embed = discord.Embed(
            title="Schedule",
            description=f"🗓️ {t1_disp} VS {t2_disp}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        thumb_file, is_local_thumb = await resolve_embed_thumbnail(interaction.guild.id, schedule_embed, fallback_to_captain_avatar=t1_cap_member)

        timestamp_val = int(new_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())
        event_details_text = f"**Tournament:** {tournament_info}\n"
        if event_to_edit.get('mode'):
            event_details_text += f"**Mode:** {event_to_edit.get('mode')}\n"
        event_details_text += f"**UTC Time:** {time_info['utc_time']}\n"
        event_details_text += f"**Local Time:** <t:{timestamp_val}:F> (<t:{timestamp_val}:R>)\n"
        event_details_text += f"**Round:** {format_round_heading(round_info)}\n"
        
        if group_info:
            event_details_text += f"**Group:** {group_info}\n"
        
        event_details_text += f"**Channel:** {interaction.channel.mention}"
        
        schedule_embed.add_field(
            name="📋 Event Details", 
            value=event_details_text,
            inline=False
        )
        schedule_embed.add_field(name="\u200b", value="\u200b", inline=False)
        
        captains_text = f"**Captains**\n"
        if event_to_edit.get('team1_name'):
            captains_text += f"- Team1 Captain: {t1_mention} @{t1_name} (Team: **{event_to_edit.get('team1_name')}**)\n"
        else:
            captains_text += f"- Team1 Captain: {t1_mention} @{t1_name}\n"
            
        if event_to_edit.get('team2_name'):
            captains_text += f"- Team2 Captain: {t2_mention} @{t2_name} (Team: **{event_to_edit.get('team2_name')}**)"
        else:
            captains_text += f"- Team2 Captain: {t2_mention} @{t2_name}"
            
        schedule_embed.add_field(name="👑 Team Captains", value=captains_text, inline=False)
        schedule_embed.add_field(name="\u200b", value="\u200b", inline=False)
        schedule_embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
        
        # Prepare files to send
        files_to_send = []
        if poster_image and os.path.exists(poster_image):
            try:
                with open(poster_image, 'rb') as f:
                    poster_data = f.read()
                file_obj = discord.File(
                    fp=io.BytesIO(poster_data),
                    filename="event_poster.png"
                )
                schedule_embed.set_image(url="attachment://event_poster.png")
                files_to_send.append(file_obj)
            except Exception as e:
                print(f"Error loading poster image for schedule edit: {e}")
                
        if is_local_thumb and thumb_file:
            files_to_send.append(thumb_file)
        
        # Delete old message
        old_msg_id = event_to_edit.get('schedule_message_id')
        old_ch_id = event_to_edit.get('schedule_channel_id')
        if old_msg_id and old_ch_id:
            try:
                ch = interaction.guild.get_channel(old_ch_id)
                if ch:
                    old_msg = await ch.fetch_message(old_msg_id)
                    await old_msg.delete()
            except Exception as e:
                print(f"Could not delete old schedule message: {e}")
                
        # Send new message (use active tournament schedule channel first, then global fallback)
        try:
            _sched_ch_edit = None
            _t_cfg_sched_edit = get_active_tournament_config(interaction.guild.id)
            if _t_cfg_sched_edit and _t_cfg_sched_edit.get('schedule_channel_id'):
                _sched_ch_edit = interaction.guild.get_channel(int(_t_cfg_sched_edit['schedule_channel_id']))
            if not _sched_ch_edit:
                _sched_ch_edit = interaction.guild.get_channel(CHANNEL_IDS.get("take_schedule"))
            schedule_channel = _sched_ch_edit
            if schedule_channel:
                judge_ping = f"<@&{ROLE_IDS['judge']}>"
                if files_to_send:
                    # Create copies of files for schedule channel
                    schedule_files = []
                    for file_obj in files_to_send:
                        file_obj.fp.seek(0)
                        file_data = file_obj.fp.read()
                        schedule_files.append(discord.File(
                            fp=io.BytesIO(file_data),
                            filename=file_obj.filename
                        ))
                    schedule_message = await schedule_channel.send(content=judge_ping, embed=schedule_embed, files=schedule_files, view=take_schedule_view)
                else:
                    schedule_message = await schedule_channel.send(content=judge_ping, embed=schedule_embed, view=take_schedule_view)
                
                event_to_edit['schedule_message_id'] = schedule_message.id
                event_to_edit['schedule_channel_id'] = schedule_channel.id
                save_scheduled_events()
        except Exception as e:
            print(f"Could not post updated schedule message: {e}")

        # Automatically rename ticket channel to match new names
        try:
            new_channel_name = f"{round_info.lower()}-{t1_disp.lower()}-vs-{t2_disp.lower()}"
            if group_info:
                new_channel_name = f"{group_info.lower().replace(' ', '-')}-{new_channel_name}"
            new_channel_name = re.sub(r'[^a-zA-Z0-9\-]', '-', new_channel_name)
            new_channel_name = re.sub(r'-+', '-', new_channel_name)
            new_channel_name = new_channel_name.strip('-')
            if len(new_channel_name) > 100:
                new_channel_name = new_channel_name[:100]
            await interaction.channel.edit(name=new_channel_name)
        except Exception as e:
            print(f"Error renaming ticket channel: {e}")

        # Create public embed matching event_create format
        timestamp_val = int(new_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())
        embed = discord.Embed(
            title="Schedule",
            description=f"🗓️ {t1_disp} VS {t2_disp}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        await resolve_embed_thumbnail(interaction.guild.id, embed, fallback_to_captain_avatar=t1_cap_member)
        if poster_image:
            embed.set_image(url="attachment://event_poster.png")

        # Event Details
        event_details = f"**Tournament:** {tournament_info}\n"
        event_details += f"**UTC Time:** {time_info_display}\n"
        event_details += f"**Local Time:** <t:{timestamp_val}:F> (<t:{timestamp_val}:R>)\n"
        event_details += f"**Round:** {round_info}\n"
        if group_info:
            event_details += f"**Group:** {group_info}\n"
        event_details += f"**Channel:** {interaction.channel.mention}"

        embed.add_field(name="📋 Event Details", value=event_details, inline=False)
        embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Captains
        embed.add_field(name="👑 Team Captains", value=captains_text, inline=False)
        embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.add_field(name="✏️ Updated By", value=interaction.user.mention, inline=False)
        embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")

        # Post in ticket channel (where command was run)
        if files_to_send:
            # Create copies of files for current channel
            current_files = []
            for file_obj in files_to_send:
                file_obj.fp.seek(0)
                file_data = file_obj.fp.read()
                current_files.append(discord.File(
                    fp=io.BytesIO(file_data),
                    filename=file_obj.filename
                ))
            await interaction.channel.send(embed=embed, files=current_files)
        else:
            await interaction.channel.send(embed=embed)

        # Send private confirmation to the user who edited
        await interaction.followup.send("✅ Event updated successfully, ticket channel renamed, and posted in the channel!", ephemeral=True)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error updating event: {str(e)}", ephemeral=True)


@tree.command(name="general_tie_breaker", description="To break a tie between two teams using the highest total score")
@app_commands.describe(
    tm1_name="Name of the first team. By default, it is Alpha",
    tm1_pl1_score="Score of the first player of the first team",
    tm1_pl2_score="Score of the second player of the first team", 
    tm1_pl3_score="Score of the third player of the first team",
    tm1_pl4_score="Score of the fourth player of the first team",
    tm1_pl5_score="Score of the fifth player of the first team",
    tm2_name="Name of the second team. By default, it is Bravo",
    tm2_pl1_score="Score of the first player of the second team",
    tm2_pl2_score="Score of the second player of the second team",
    tm2_pl3_score="Score of the third player of the second team",
    tm2_pl4_score="Score of the fourth player of the second team",
    tm2_pl5_score="Score of the fifth player of the second team"
)
@with_guild_context
async def general_tie_breaker(
    interaction: discord.Interaction,
    tm1_pl1_score: int,
    tm1_pl2_score: int,
    tm1_pl3_score: int,
    tm1_pl4_score: int,
    tm1_pl5_score: int,
    tm2_pl1_score: int,
    tm2_pl2_score: int,
    tm2_pl3_score: int,
    tm2_pl4_score: int,
    tm2_pl5_score: int,
    tm1_name: str = "Alpha",
    tm2_name: str = "Bravo"
):
    """Break a tie between two teams using the highest total score"""
    
    # Check permissions - only organizers and helpers can use this command
    if not has_event_create_permission(interaction):
        await interaction.response.send_message("❌ You need **Organizers** or **Helpers Tournament** role to use tie breaker.", ephemeral=True)
        return
    
    # Calculate team totals
    tm1_total = tm1_pl1_score + tm1_pl2_score + tm1_pl3_score + tm1_pl4_score + tm1_pl5_score
    tm2_total = tm2_pl1_score + tm2_pl2_score + tm2_pl3_score + tm2_pl4_score + tm2_pl5_score
    
    # Determine winner
    if tm1_total > tm2_total:
        winner = tm1_name
        winner_total = tm1_total
        loser = tm2_name
        loser_total = tm2_total
        color = discord.Color.green()
    elif tm2_total > tm1_total:
        winner = tm2_name
        winner_total = tm2_total
        loser = tm1_name
        loser_total = tm1_total
        color = discord.Color.green()
    else:
        # Still tied
        winner = "TIE"
        winner_total = tm1_total
        loser = ""
        loser_total = tm2_total
        color = discord.Color.orange()
    
    # Create result embed
    embed = discord.Embed(
        title="🏆 Tie Breaker Results",
        description="Results based on highest total team score",
        color=color,
        timestamp=discord.utils.utcnow()
    )
    
    # Team 1 scores
    embed.add_field(
        name=f"🔵 {tm1_name} Team",
        value=f"Player 1: `{tm1_pl1_score}`\n"
              f"Player 2: `{tm1_pl2_score}`\n"
              f"Player 3: `{tm1_pl3_score}`\n"
              f"Player 4: `{tm1_pl4_score}`\n"
              f"Player 5: `{tm1_pl5_score}`\n"
              f"**Total: {tm1_total}**",
        inline=True
    )
    
    # Team 2 scores
    embed.add_field(
        name=f"🔴 {tm2_name} Team",
        value=f"Player 1: `{tm2_pl1_score}`\n"
              f"Player 2: `{tm2_pl2_score}`\n"
              f"Player 3: `{tm2_pl3_score}`\n"
              f"Player 4: `{tm2_pl4_score}`\n"
              f"Player 5: `{tm2_pl5_score}`\n"
              f"**Total: {tm2_total}**",
        inline=True
    )
    
    # Add spacing
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    # Result
    if winner == "TIE":
        embed.add_field(
            name="🤝 Final Result",
            value=f"**STILL TIED!**\n"
                  f"Both teams scored {tm1_total} points\n"
                  f"Additional tie-breaking method needed",
            inline=False
        )
    else:
        embed.add_field(
            name="🏆 Winner",
            value=f"**{winner}** wins the tie breaker!\n"
                  f"**{winner}**: {winner_total} points\n"
                  f"**{loser}**: {loser_total} points\n"
                  f"Difference: {abs(winner_total - loser_total)} points",
            inline=False
        )
    
    embed.set_footer(text=f"Tie Breaker • Calculated by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed)


@tree.command(name="add_captain", description="Add two captains to a tournament match and rename the channel")
@app_commands.describe(
    round="Round of the tournament (R1-R10, Q, SF, Final)",
    captain1="First captain/team for the match",
    captain2="Second captain/team for the match",
    bracket="Optional bracket identifier (e.g., A, B, Winner, Loser)",
    team_1="Optional name of team 1",
    team_2="Optional name of team 2"
)
@app_commands.choices(
    round=[
        app_commands.Choice(name="R1", value="R1"),
        app_commands.Choice(name="R2", value="R2"),
        app_commands.Choice(name="R3", value="R3"),
        app_commands.Choice(name="R4", value="R4"),
        app_commands.Choice(name="R5", value="R5"),
        app_commands.Choice(name="R6", value="R6"),
        app_commands.Choice(name="R7", value="R7"),
        app_commands.Choice(name="R8", value="R8"),
        app_commands.Choice(name="R9", value="R9"),
        app_commands.Choice(name="R10", value="R10"),
        app_commands.Choice(name="Qualifier", value="Q"),
        app_commands.Choice(name="Semi Final", value="SF"),
        app_commands.Choice(name="3rd Place", value="3rd Place"),
        app_commands.Choice(name="Final", value="Final")
    ]
)
@with_guild_context
async def add_captain(
    interaction: discord.Interaction, 
    round: str, 
    captain1: discord.Member, 
    captain2: discord.Member, 
    bracket: str = None,
    team_1: str = None,
    team_2: str = None
):
    """Add two captains to a tournament match and rename the channel with tournament rules."""
    try:
        if not has_event_create_permission(interaction):
            await interaction.response.send_message("❌ You don't have permission to use this command. Only Head Helper, Helper Team, Head Organizer, or Bot Owner/Admin can add captains.", ephemeral=True)
            return
        
        # Validate round parameter
        valid_rounds = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "Q", "SF", "Final"]
        if round not in valid_rounds:
            await interaction.response.send_message("❌ Invalid round. Please select R1-R10, Q, SF, or Final.", ephemeral=True)
            return
        
        # Get current channel
        channel = interaction.channel
        
        # Determine team or captain names for channel renaming
        t1_name = team_1 if team_1 else captain1.name
        t2_name = team_2 if team_2 else captain2.name
        
        # Create new channel name
        if bracket:
            new_name = f"{bracket}-{round.lower()}-{t1_name.lower()}-vs-{t2_name.lower()}"
        else:
            new_name = f"{round.lower()}-{t1_name.lower()}-vs-{t2_name.lower()}"
        
        # Remove special characters and spaces, replace with hyphens
        new_name = re.sub(r'[^a-zA-Z0-9\-]', '-', new_name)
        new_name = re.sub(r'-+', '-', new_name)  # Replace multiple hyphens with single hyphen
        new_name = new_name.strip('-')  # Remove leading/trailing hyphens
        
        # Ensure channel name is within Discord's limits (100 characters max)
        if len(new_name) > 100:
            new_name = new_name[:100]
        
        # Rename the channel
        try:
            await channel.edit(name=new_name)
            await interaction.response.send_message(f"✅ Channel renamed to `{new_name}`", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to rename this channel.", ephemeral=True)
            return
        except discord.HTTPException as e:
            await interaction.response.send_message(f"❌ Failed to rename channel: {e}", ephemeral=True)
            return
        
        # Add both captains to the channel
        try:
            # Add captain 1 to the channel
            await channel.set_permissions(captain1, 
                                         view_channel=True,
                                         send_messages=True)
            
            # Add captain 2 to the channel
            await channel.set_permissions(captain2, 
                                         view_channel=True,
                                         send_messages=True)
        except discord.Forbidden:
            await interaction.followup.send("⚠️ Channel renamed but couldn't add captains - missing permissions.", ephemeral=True)
        except discord.HTTPException as e:
            await interaction.followup.send(f"⚠️ Channel renamed but error adding captains: {e}", ephemeral=True)
        
        # Send tournament rules message — dynamic branded
        rules_embed = discord.Embed(
            title=f"⚓ {get_system_name(interaction)} | {get_tournament_name(interaction)} — Match Setup",
            description="Welcome to your match channel. Use this channel for all tournament discussions.",
            color=discord.Color(BRAND_COLOR)
        )
        if interaction.guild and interaction.guild.icon:
            rules_embed.set_thumbnail(url=interaction.guild.icon.url)
        rules_embed.add_field(
            name="📋 Tournament Information",
            value=(
                f"• 🏆 [Live Bracket]({get_link_bracket(interaction)}) — View current standings\n"
                f"• ⏰ [Match Deadlines]({get_link_deadline(interaction)}) — Schedule & timings\n"
                f"• 📜 [Tournament Rules]({get_link_rules(interaction)}) — Read before playing"
            ),
            inline=False
        )
        
        # Determine participant descriptions for embed
        t1_display = f"**{team_1}** ({captain1.mention})" if team_1 else captain1.mention
        t2_display = f"**{team_2}** ({captain2.mention})" if team_2 else captain2.mention
        
        rules_embed.add_field(
            name="👥 Match Participants",
            value=f"**Round:** {round}\n**Captain 1:** {t1_display}\n**Captain 2:** {t2_display}",
            inline=False
        )
        rules_embed.add_field(
            name="🆘 Need Help?",
            value=f"Ping <@&{ROLE_IDS['helper_team']}> and a staff member will assist you.",
            inline=False
        )
        rules_embed.add_field(
            name="🤝 Fair Play",
            value="We appreciate your cooperation. Good luck and have fun! ⚓",
            inline=False
        )
        rules_embed.set_footer(text=f"{ORGANIZATION_NAME} | Setup by {interaction.user.name} • {datetime.datetime.now().strftime('%d-%m-%Y %H:%M')}")
        try:
            if interaction.guild and interaction.guild.icon:
                rules_embed.set_thumbnail(url=interaction.guild.icon.url)
                await channel.send(embed=rules_embed)
            else:
                logo_candidates = ["tournament_bot_logo.png", "logo.png"]
                logo_sent = False
                for logo_path in logo_candidates:
                    try:
                        with open(logo_path, "rb") as logo_file:
                            logo_data = io.BytesIO(logo_file.read())
                            lf = discord.File(logo_data, filename="logo.png")
                            rules_embed.set_thumbnail(url="attachment://logo.png")
                            await channel.send(embed=rules_embed, file=lf)
                            logo_sent = True
                            break
                    except FileNotFoundError:
                        continue
                if not logo_sent:
                    await channel.send(embed=rules_embed)
        except Exception as e:
            print(f"Warning: Could not send logo: {e}")
            await channel.send(embed=rules_embed)

    except Exception as e:
        await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=True)
        print(f"Error in add_captain command: {e}")
@tree.command(name="maps", description="Randomly select 3, 5, or 7 maps for gameplay")
@app_commands.describe(
    count="Number of maps to select (3, 5, or 7)"
)
@with_guild_context
async def maps(interaction: discord.Interaction, count: int):
    """Randomly selects 3, 5, or 7 maps from the available map pool"""
    
    import random
    
    # Predefined map list
    maps_list = [
        "New Storm (2024)",
        "Arid Frontier", 
        "Islands of Iceland",
        "Unexplored Rocks",
        "Arctic",
        "Lost City",
        "Polar Frontier",
        "Hidden Dragon",
        "Monstrous Maelstrom",
        "Two Samurai",
        "Stone Peaks",
        "Viking Bay",
        "Rising Fortress",
        "Greenlands",
        "Old Storm"
    ]
    
    # Validate count
    if count not in [3, 5, 7]:
        await interaction.response.send_message("❌ Please select 3, 5, or 7 maps only.", ephemeral=True)
        return
    
    # Randomly select the specified number of maps
    selected_maps = random.sample(maps_list, count)
    
    embed = discord.Embed(
        title=f"🗺️ Random Map Selection {ORGANIZATION_NAME}",
        description=f"**Randomly selected {count} map(s):**",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    
    # Add selected maps as a field
    selected_maps_text = "\n".join([f"• {map_name}" for map_name in selected_maps])
    embed.add_field(
        name=f"🎯 Selected Maps ({count})",
        value=selected_maps_text,
        inline=False
    )
    
    embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
    await interaction.response.send_message(embed=embed)


@tree.command(name="test_channels", description="Test if bot can access configured channels (Organizer only)")
@with_guild_context
async def test_channels(interaction: discord.Interaction):
    """Test channel access for debugging"""
    
    if not has_organizer_permission(interaction):
        await interaction.response.send_message(
            "❌ You need to be **Bot Owner** or **Head Organizer** to use this command.",
            ephemeral=True
        )
        return
    
    embed = discord.Embed(
        title="🔍 Channel Access Test",
        description="Testing bot access to configured channels...",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    
    # Test each channel
    for channel_name, channel_id in CHANNEL_IDS.items():
        channel = interaction.guild.get_channel(channel_id)
        
        if channel:
            # Check if bot can send messages
            perms = channel.permissions_for(interaction.guild.me)
            can_send = perms.send_messages
            can_embed = perms.embed_links
            can_attach = perms.attach_files
            can_mention = perms.mention_everyone
            
            status = "✅" if (can_send and can_embed) else "⚠️"
            details = f"Channel: {channel.mention}\n"
            details += f"• Send Messages: {'✅' if can_send else '❌'}\n"
            details += f"• Embed Links: {'✅' if can_embed else '❌'}\n"
            details += f"• Attach Files: {'✅' if can_attach else '❌'}\n"
            details += f"• Mention Everyone: {'✅' if can_mention else '❌'}"
            
            embed.add_field(
                name=f"{status} {channel_name.replace('_', ' ').title()}",
                value=details,
                inline=False
            )
        else:
            embed.add_field(
                name=f"❌ {channel_name.replace('_', ' ').title()}",
                value=f"Channel ID `{channel_id}` not found!\nThe channel may have been deleted or the ID is wrong.",
                inline=False
            )
    
    embed.set_footer(text=f"{ORGANIZATION_NAME}")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@tree.command(name="choose", description="Randomly choose from a list of options")
@app_commands.describe(
    options="List of options separated by commas"
)
@with_guild_context
async def choose(interaction: discord.Interaction, options: str):
    """Randomly selects one option from a comma-separated list"""
    
    import random
    
    # Handle comma-separated options (original functionality)
    option_list = [option.strip() for option in options.split(',') if option.strip()]
    
    # Validate input
    if len(option_list) < 2:
        await interaction.response.send_message("❌ Please provide at least 2 options separated by commas.", ephemeral=True)
        return
    
    if len(option_list) > 20:
        await interaction.response.send_message("❌ Too many options! Please provide 20 or fewer options.", ephemeral=True)
        return
    
    # Randomly select one option
    chosen_option = random.choice(option_list)
    
    # Create embed
    embed = discord.Embed(
        title="🎲 Random Choice",
        description=f"**Selected:** {chosen_option}",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    
    # Add all options as a field
    options_text = "\n".join([f"• {option}" for option in option_list])
    embed.add_field(
        name=f"📋 Available Options ({len(option_list)})",
        value=options_text,
        inline=False
    )
    
    embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
    
    await interaction.response.send_message(embed=embed)




# Automatic background ticket creation for open matches based on active tournament configuration
auto_room_loops = {}
auto_room_locks = {}

async def auto_create_open_tickets_for_tournament(guild: discord.Guild, t_cfg: dict, on_progress=None) -> tuple[int, str]:
    guild_id = guild.id
    if guild_id not in auto_room_locks:
        auto_room_locks[guild_id] = asyncio.Lock()
        
    async with auto_room_locks[guild_id]:
        import time
        last_edit = 0
        
        async def report(percent: int, text: str, force: bool = False):
            nonlocal last_edit
            if not on_progress:
                return
            now = time.time()
            if force or (now - last_edit >= 1.5):
                await on_progress(percent, text)
                last_edit = now

        await report(0, "Fetching matches from Challonge...", force=True)
        
        cfg = get_guild_config(guild.id)
        bracket_link = t_cfg.get('challonge_bracket_link') or t_cfg.get('id')
        api_key = t_cfg.get('key') or get_bracket_api_key(guild.id)
        sheet_link = t_cfg.get('sheet_link') or t_cfg.get('captains_sheet_link') or cfg.get('player_info_link') or cfg.get('google_sheet_link')
        
        missing_fields = []
        if not bracket_link or not bracket_link.strip():
            missing_fields.append("❌ Challonge Bracket Link is missing.")
        if not api_key or not api_key.strip():
            missing_fields.append("❌ Challonge API Key is missing.")
        if not sheet_link or not sheet_link.strip():
            missing_fields.append("❌ Google Sheet Link is missing.")
            
        if missing_fields:
            return 0, "\n".join(missing_fields)
            
        matches, err = await fetch_challonge_open_matches(bracket_link, api_key)
        if err:
            return 0, f"Challonge API Error: {err}"
        if not matches:
            return 0, ""
            
        await report(15, f"Fetched {len(matches)} matches. Fetching captain info from Google Sheet...", force=True)
        
        captains_dict, is_1v1, err2 = await fetch_google_sheet_captains(sheet_link)
        if err2:
            return 0, f"Google Sheet Error: {err2}"
            
        await report(30, "Parsing categories and roles...", force=True)
        
        categories = []
        for i in range(1, 5):
            cat_id = t_cfg.get(f'ticket_open_category_{i}')
            if cat_id:
                try:
                    cat_id = int(cat_id)
                except (ValueError, TypeError):
                    pass
                cat = discord.utils.get(guild.categories, id=cat_id)
                if cat:
                    categories.append(cat)
                    
        if not categories:
            return 0, "No open ticket categories configured for this tournament."
            
        helper_team_role = None
        if helper_role_id := t_cfg.get('helper_role_id'):
            try:
                helper_role_id = int(helper_role_id)
            except (ValueError, TypeError):
                pass
            helper_team_role = discord.utils.get(guild.roles, id=helper_role_id)
        if not helper_team_role:
            cfg = get_guild_config(guild.id)
            if global_helper_id := cfg.get('role_ids', {}).get('helper_team'):
                try:
                    global_helper_id = int(global_helper_id)
                except (ValueError, TypeError):
                    pass
                helper_team_role = discord.utils.get(guild.roles, id=global_helper_id)
                
        rules_link = f"https://discord.com/channels/{guild.id}/{t_cfg.get('rules')}" if t_cfg.get('rules') else "Not Set"
        deadline_link = f"https://discord.com/channels/{guild.id}/{t_cfg.get('deadline')}" if t_cfg.get('deadline') else "Not Set"
        bracket_display_link = bracket_link if bracket_link.startswith("http") else f"https://challonge.com/{bracket_link}"
        
        created_count = 0
        total_matches = len(matches)

        # ── Retroactive MatchID stamping ─────────────────────────────────────
        # Channels created by older bot versions have no MatchID in their topic.
        # Scan all guild channels and tag any untagged ones that belong to a
        # current open match, so duplicate detection works on the next loop run.
        STATUS_PREFIXES_STAMP = ("sh-", "dq-", "dd-", "ho-", "closed-", "done-")
        all_guild_channels = list(guild._channels.values()) if hasattr(guild, '_channels') else list(guild.text_channels)
        for match in matches:
            m_id   = match['id']
            m_t1   = match['team1']
            m_t2   = match['team2']
            m_rnd  = match['round']
            tag    = f"MatchID:{m_id}"

            # Build every plausible name variant for this match
            name_variants = set()
            for trunc in [8, 10, 12, 14, 16, 20, 25]:
                s1 = re.sub(r'[^a-zA-Z0-9]', '', m_t1).lower()[:trunc]
                s2 = re.sub(r'[^a-zA-Z0-9]', '', m_t2).lower()[:trunc]
                name_variants.add(f"r{m_rnd}-{s1}-vs-{s2}")
                # also swapped order
                name_variants.add(f"r{m_rnd}-{s2}-vs-{s1}")

            for ch in all_guild_channels:
                if not isinstance(ch, discord.TextChannel):
                    continue
                # Skip if already tagged
                if ch.topic and tag in ch.topic:
                    break

                # Strip status prefix to get base name
                base = ch.name
                for pfx in STATUS_PREFIXES_STAMP:
                    if base.startswith(pfx):
                        base = base[len(pfx):]
                        break

                if base in name_variants:
                    # Stamp the MatchID into the topic silently
                    try:
                        new_topic = f"{tag}"
                        if ch.topic and ch.topic.strip():
                            new_topic = f"{ch.topic.strip()} | {tag}"
                        await ch.edit(topic=new_topic, reason="Auto-stamping MatchID for duplicate detection")
                    except Exception:
                        pass
                    break
        # ─────────────────────────────────────────────────────────────────────

        for idx, match in enumerate(matches):
            team1, team2 = match['team1'], match['team2']
            p1_id, p2_id = match['player1_id'], match['player2_id']
            match_id, mod_round = match['id'], match['round']
            
            loop_percent = 40 + int((idx / total_matches) * 55)
            await report(loop_percent, f"Processing match {idx+1}/{total_matches}: {team1} vs {team2}...")
            
            c1_raw = captains_dict.get(team1, "") or captains_dict.get(team1.strip(), "")
            c2_raw = captains_dict.get(team2, "") or captains_dict.get(team2.strip(), "")
            
            async def resolve_member(raw: str) -> Optional[discord.Member]:
                if not raw or not raw.strip():
                    return None
                clean_raw = raw.strip()
                if clean_raw.startswith('@'):
                    clean_raw = clean_raw[1:].strip()
                    
                m = re.search(r'<@!?(\d+)>', clean_raw)
                uid = None
                if m:
                    uid = int(m.group(1))
                elif clean_raw.isdigit():
                    uid = int(clean_raw)
                    
                if uid:
                    member = guild.get_member(uid)
                    if not member:
                        try:
                            member = await guild.fetch_member(uid)
                        except Exception:
                            pass
                    return member
                
                # Fallback to search by username / display name in cache
                for member in guild.members:
                    if member.name.lower() == clean_raw.lower() or member.display_name.lower() == clean_raw.lower():
                        return member
                
                # Fallback to query_members via Gateway search
                try:
                    found_members = await guild.query_members(query=clean_raw, limit=5)
                    for member in found_members:
                        if member.name.lower() == clean_raw.lower() or member.display_name.lower() == clean_raw.lower():
                            return member
                except Exception:
                    pass
                return None
                
            captain1 = await resolve_member(c1_raw)
            captain2 = await resolve_member(c2_raw)
            
            if is_1v1:
                n1 = (captain1.name if captain1 else re.sub(r'[^a-zA-Z0-9]', '', team1))[:12].lower()
                n2 = (captain2.name if captain2 else re.sub(r'[^a-zA-Z0-9]', '', team2))[:12].lower()
                chan_name = f"r{mod_round}-{n1}-vs-{n2}"
            else:
                safe_t1 = re.sub(r'[^a-zA-Z0-9]', '', team1).lower()[:8]
                safe_t2 = re.sub(r'[^a-zA-Z0-9]', '', team2).lower()[:8]
                chan_name = f"r{mod_round}-{safe_t1}-vs-{safe_t2}"
                
            chan_name = re.sub(r'[^a-zA-Z0-9\-]', '-', chan_name)
            chan_name = re.sub(r'-+', '-', chan_name).strip('-')[:100].lower()
            topic = f"MatchID:{match_id}"
            
            already_exists = False
            # Use guild._channels to check ALL channels including ones in restricted/closed
            # categories that may not be visible to the bot via guild.text_channels cache.
            STATUS_PREFIXES = ("sh-", "dq-", "dd-", "ho-", "closed-", "done-")
            all_channels = list(guild._channels.values()) if hasattr(guild, '_channels') else list(guild.text_channels)
            for channel in all_channels:
                if not isinstance(channel, discord.TextChannel):
                    continue
                # Check by MatchID in topic (most reliable)
                if channel.topic and f"MatchID:{match_id}" in channel.topic:
                    already_exists = True
                    break
                # Check by channel name (exact match)
                if channel.name == chan_name:
                    already_exists = True
                    break
                # Check by channel name after stripping status prefixes (e.g. "sh-r2-team-vs-team")
                stripped_name = channel.name
                for pfx in STATUS_PREFIXES:
                    if stripped_name.startswith(pfx):
                        stripped_name = stripped_name[len(pfx):]
                        break
                if stripped_name == chan_name:
                    already_exists = True
                    break
            if already_exists:
                continue
                
            target_category = None
            for c in categories:
                if len(c.channels) < 49:
                    target_category = c
                    break
            if not target_category:
                break
                
            try:
                overwrites = {}
                # @everyone is always denied — only explicitly allowed roles/members can see this channel
                overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)

                # Bot itself
                overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_permissions=True)

                # Track which role IDs are explicitly allowed
                allowed_role_ids = set()

                # From tournament config: admin_role_id, helper_role_id
                for role_key in ["admin_role_id", "helper_role_id"]:
                    if r_id := t_cfg.get(role_key):
                        try:
                            r_id = int(r_id)
                        except (ValueError, TypeError):
                            pass
                        if staff_r := discord.utils.get(guild.roles, id=r_id):
                            overwrites[staff_r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                            allowed_role_ids.add(staff_r.id)

                # From global guild config: head_organizer, organizer, head_helper, helper_team
                cfg = get_guild_config(guild.id)
                for role_key in ["head_organizer", "organizer", "head_helper", "helper_team"]:
                    if r_id := cfg.get('role_ids', {}).get(role_key):
                        try:
                            r_id = int(r_id)
                        except (ValueError, TypeError):
                            pass
                        if staff_r := discord.utils.get(guild.roles, id=r_id):
                            overwrites[staff_r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                            allowed_role_ids.add(staff_r.id)


                # Individual captain overrides (specific member access)
                if captain1:
                    overwrites[captain1] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                if captain2:
                    overwrites[captain2] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    
                new_ch = await guild.create_text_channel(
                    name=chan_name,
                    category=target_category,
                    topic=topic,
                    overwrites=overwrites
                )
                
                # Register the auto-created match in scheduled_events and Supabase
                event_id = f"challonge_{match_id}"
                scheduled_events[event_id] = {
                    'guild_id': guild.id,
                    'title': f"{format_round_heading(mod_round)} Match",
                    'datetime': datetime.datetime.utcnow(),
                    'time_str': "Live",
                    'date_str': "Live",
                    'round': str(mod_round),
                    'group': None,
                    'minutes_left': 0,
                    'tournament': t_cfg.get('name', 'Tournament'),
                    'mode': None,
                    'judge': None,
                    'recorder': None,
                    'channel_id': new_ch.id,
                    'team1_captain': captain1.id if captain1 else None,
                    'team2_captain': captain2.id if captain2 else None,
                    'team1_name': team1,
                    'team2_name': team2
                }
                save_scheduled_events()
                try:
                    await save_event_to_supabase(event_id, scheduled_events[event_id])
                except Exception as db_err:
                    print(f"Error syncing auto-room event to Supabase: {db_err}")
                
                org_name = cfg.get('organization_name', 'Tournament Organizer')
                rules_embed = discord.Embed(
                    title=f"⚓ {get_system_name(guild)} | {t_cfg.get('name')} — Match Setup",
                    description="Welcome to your match channel. Use this channel for all tournament discussions.",
                    color=discord.Color(BRAND_COLOR)
                )
                if guild.icon:
                    rules_embed.set_thumbnail(url=guild.icon.url)
                rules_embed.add_field(
                    name="📋 Tournament Information",
                    value=(
                        f"• 🏆 [Live Bracket]({bracket_display_link})\n"
                        f"• ⏰ [Deadlines]({deadline_link})\n"
                        f"• 📜 [Rules]({rules_link})"
                    ),
                    inline=False
                )
                
                round_display = format_round_heading(mod_round)
                if is_1v1:
                    pval = f"**Round:** {round_display}\n**Captain 1:** {captain1.mention if captain1 else c1_raw or team1}\n**Captain 2:** {captain2.mention if captain2 else c2_raw or team2}"
                else:
                    pval = f"**Round:** {round_display}\n**Team 1:** {team1} — Captain: {captain1.mention if captain1 else c1_raw or 'Not Found'}\n**Team 2:** {team2} — Captain: {captain2.mention if captain2 else c2_raw or 'Not Found'}"
                    
                rules_embed.add_field(name="👥 Match Participants", value=pval, inline=False)
                rules_embed.add_field(
                    name="🆘 Need Help?",
                    value=f"Ping {helper_team_role.mention if helper_team_role else '@Helper Team'} for assistance. ⚓",
                    inline=False
                )
                rules_embed.set_footer(text=f"{org_name} • Auto-Ticket")
                
                ping_content = " ".join(filter(None, [
                    captain1.mention if captain1 else (c1_raw or None),
                    captain2.mention if captain2 else (c2_raw or None),
                ])) or f"{team1} vs {team2}"
                
                if guild.icon:
                    await new_ch.send(content=ping_content, embed=rules_embed)
                else:
                    logo_candidates_at = ["tournament_bot_logo.png", "logo.png"]
                    sent_at = False
                    for logo_file in logo_candidates_at:
                        if os.path.exists(logo_file):
                            try:
                                with open(logo_file, "rb") as lf:
                                    rules_embed.set_thumbnail(url="attachment://logo.png")
                                    await new_ch.send(content=ping_content, embed=rules_embed, file=discord.File(io.BytesIO(lf.read()), "logo.png"))
                                    sent_at = True
                                    break
                            except Exception:
                                pass
                    if not sent_at:
                        await new_ch.send(content=ping_content, embed=rules_embed)
                    
                created_count += 1
            except Exception as e:
                print(f"Error creating auto-room channel {chan_name}: {e}")
                
        if created_count > 0:
            try:
                log_embed = discord.Embed(
                    title="🎫 Auto Rooms Created",
                    description=f"Automatically created **{created_count}** match room channel(s) for tournament **{t_cfg.get('name')}**.",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                if guild.icon:
                    log_embed.set_thumbnail(url=guild.icon.url)
                await log_bot_activity(guild, log_embed)
            except Exception as log_err:
                print(f"Failed to log auto room creation: {log_err}")
                
        return created_count, ""

async def auto_create_open_tickets(guild: discord.Guild, user: discord.Member):
    t_cfg = get_active_tournament_config(guild.id)
    if t_cfg and t_cfg.get('auto_room_creation', True):
        await auto_create_open_tickets_for_tournament(guild, t_cfg)

async def auto_room_background_loop(guild_id: int):
    # Short initial sleep to let bot start up and cache guild members/channels
    try:
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        return

    while True:
        try:
            t_cfg = get_active_tournament_config(guild_id)
            if t_cfg and t_cfg.get('auto_room_creation', True):
                guild = bot.get_guild(guild_id)
                if guild:
                    await auto_create_open_tickets_for_tournament(guild, t_cfg)
        except Exception as e:
            print(f"Error in auto_room run: {e}")
            
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            break

def start_auto_room_loop(guild_id: int):
    if guild_id in auto_room_loops:
        return
    task = asyncio.create_task(auto_room_background_loop(guild_id))
    auto_room_loops[guild_id] = task
    print(f"🚀 Started auto-room background loop for guild {guild_id}")

def stop_auto_room_loop(guild_id: int):
    if task := auto_room_loops.pop(guild_id, None):
        task.cancel()
        print(f"⏹️ Stopped auto-room background loop for guild {guild_id}")

@bot.event
async def on_guild_join(guild: discord.Guild):
    """Fires when the bot is added to a new server. Starts the auto-room loop for that guild."""
    print(f"✅ Bot joined new guild: {guild.name} ({guild.id}) — starting auto-room loop...")
    start_auto_room_loop(guild.id)

@bot.event
async def on_guild_remove(guild: discord.Guild):
    """Fires when the bot is removed from a server. Stops the auto-room loop for that guild."""
    print(f"❌ Bot removed from guild: {guild.name} ({guild.id}) — stopping auto-room loop...")
    stop_auto_room_loop(guild.id)


# ── Column name sets for player-info lookup ──────────────────────────────────
_1V1_FIELDS = [
    "Player Discord ID",
    "Player Game Name",
    "Player Game ID",
    "Player Title",
]

_TEAM_CAPTAIN_FIELDS = [
    "Team Name",
    "Captain Discord ID",
    "Captain Game Name",
    "Captain Game ID",
    "Captain Title",
]

_TEAM_PLAYER_FIELDS_TEMPLATE = [
    "Player {n} Discord ID",
    "Player {n} Game Name",
    "Player {n} Game ID",
    "Player {n} Title",
]

def _build_team_fields(format_str: str) -> list:
    """Return the ordered field list for a given team format string (e.g. '3 vs 3')."""
    try:
        size = int(format_str.split()[0])
    except (ValueError, IndexError):
        size = 5
    fields = list(_TEAM_CAPTAIN_FIELDS)
    for n in range(2, size + 1):
        for tmpl in _TEAM_PLAYER_FIELDS_TEMPLATE:
            fields.append(tmpl.format(n=n))
    return fields

def _col_index(header: list, name: str) -> int:
    """Return the column index for name (case-insensitive, normalized spaces), or -1 if not found."""
    if not name:
        return -1
    
    # 1. Normalize spaces of the target name
    name_clean = " ".join(name.lower().split())
    
    # Try exact match after space normalization
    for i, h in enumerate(header):
        h_clean = " ".join(h.lower().split())
        if h_clean == name_clean:
            return i
            
    # 2. Try substring match (e.g. if the header has extra text or trailing whitespace)
    for i, h in enumerate(header):
        h_clean = " ".join(h.lower().split())
        if name_clean in h_clean:
            return i
            
    # 3. Try removing all spaces as a fallback (e.g. "player2discordid" vs "player 2 discord id")
    name_nospace = "".join(name_clean.split())
    for i, h in enumerate(header):
        h_nospace = "".join(h.lower().split())
        if name_nospace in h_nospace:
            return i
            
    return -1

def convert_google_drive_url(url: str) -> str:
    """Convert Google Drive sharing URL to direct image URL"""
    if not url:
        return None
    url = url.strip()
    if url.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        return url
    file_id = None
    file_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if file_id_match:
        file_id = file_id_match.group(1)
    if not file_id:
        id_match = re.search(r'[?&]id=([a-zA-Z0-9-_]+)', url)
        if id_match:
            file_id = id_match.group(1)
    if not file_id:
        folder_match = re.search(r'/folders/([a-zA-Z0-9-_]+)', url)
        if folder_match:
            file_id = folder_match.group(1)
    if file_id:
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    return url

def create_id_card_image(user_data: dict, discord_user: discord.Member) -> io.BytesIO:
    """Create an ID card image with user information"""
    try:
        card_width = 800
        card_height = 500
        img = Image.new('RGB', (card_width, card_height), color='#1a1a2e')
        draw = ImageDraw.Draw(img)
        for i in range(card_height):
            r = int(26 + (i / card_height) * 10)
            g = int(26 + (i / card_height) * 20)
            b = int(46 + (i / card_height) * 30)
            draw.rectangle([(0, i), (card_width, i + 1)], fill=(r, g, b))
        
        border_width = 4
        draw.rectangle(
            [(border_width, border_width), (card_width - border_width, card_height - border_width)],
            outline='#FFD700',
            width=border_width
        )
        
        title_font = get_font_with_fallbacks("Arial", 40, "bold")
        heading_font = get_font_with_fallbacks("Arial", 24, "bold")
        text_font = get_font_with_fallbacks("Arial", 20)
        small_font = get_font_with_fallbacks("Arial", 16)
        
        header_y = 20
        draw.text((card_width // 2, header_y), f"{ORGANIZATION_NAME} ID CARD", fill='#FFD700', font=title_font, anchor='mt')
        
        logo_size = 150
        logo_x = 50
        logo_y = 100
        logo_path = "tournament_bot_logo.png"
        try:
            if os.path.exists(logo_path):
                logo_img = Image.open(logo_path)
                if logo_img.mode != 'RGBA':
                    logo_img = logo_img.convert('RGBA')
                logo_img.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
                logo_width, logo_height = logo_img.size
                logo_paste_x = logo_x + (logo_size - logo_width) // 2
                logo_paste_y = logo_y + (logo_size - logo_height) // 2
                if logo_img.mode == 'RGBA':
                    img.paste(logo_img, (logo_paste_x, logo_paste_y), logo_img)
                else:
                    img.paste(logo_img, (logo_paste_x, logo_paste_y))
                draw.rectangle(
                    [(logo_x - 2, logo_y - 2), (logo_x + logo_size + 2, logo_y + logo_size + 2)],
                    outline='#FFD700',
                    width=2
                )
            else:
                draw.rectangle([(logo_x, logo_y), (logo_x + logo_size, logo_y + logo_size)], outline='#FFD700', width=3)
                org_initials = "".join([w[0] for w in str(ORGANIZATION_NAME).split() if w])[:4].upper() or "LOGO"
                draw.text((logo_x + logo_size // 2, logo_y + logo_size // 2), org_initials, fill='#FFD700', font=heading_font, anchor='mm')
        except Exception:
            draw.rectangle([(logo_x, logo_y), (logo_x + logo_size, logo_y + logo_size)], outline='#FFD700', width=3)
            org_initials = "".join([w[0] for w in str(ORGANIZATION_NAME).split() if w])[:4].upper() or "LOGO"
            draw.text((logo_x + logo_size // 2, logo_y + logo_size // 2), org_initials, fill='#FFD700', font=heading_font, anchor='mm')
        
        screenshot_size = 120
        screenshot_x = logo_x
        screenshot_y = logo_y + logo_size + 20
        if user_data.get('screenshot_url'):
            try:
                screenshot_url = convert_google_drive_url(user_data['screenshot_url'])
                screenshot_response = requests.get(screenshot_url, timeout=10)
                if screenshot_response.status_code == 200:
                    screenshot_img = Image.open(io.BytesIO(screenshot_response.content)).convert('RGB')
                    screenshot_img = screenshot_img.resize((screenshot_size, screenshot_size), Image.Resampling.LANCZOS)
                    img.paste(screenshot_img, (screenshot_x, screenshot_y))
                    draw.rectangle(
                        [(screenshot_x - 2, screenshot_y - 2), (screenshot_x + screenshot_size + 2, screenshot_y + screenshot_size + 2)],
                        outline='#FFD700', width=2
                    )
            except Exception as e:
                print(f"Error loading screenshot: {e}")
        
        info_x = 250
        info_y = 120
        line_height = 40
        current_y = info_y
        
        draw.text((info_x, current_y), "Discord Tag:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), user_data.get('discord_tag', 'N/A') or 'N/A', fill='#FFFFFF', font=text_font)
        current_y += line_height
        
        draw.text((info_x, current_y), "Game Name:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), user_data.get('game_name', 'N/A') or 'N/A', fill='#FFFFFF', font=text_font)
        current_y += line_height
        
        draw.text((info_x, current_y), "Game ID:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), str(user_data.get('game_id', 'N/A') or 'N/A'), fill='#FFFFFF', font=text_font)
        current_y += line_height
        
        if user_data.get('real_name'):
            draw.text((info_x, current_y), "Real Name:", fill='#FFD700', font=heading_font)
            draw.text((info_x + 180, current_y), user_data.get('real_name', 'N/A'), fill='#FFFFFF', font=text_font)
            current_y += line_height
        
        if user_data.get('country'):
            draw.text((info_x, current_y), "Country:", fill='#FFD700', font=heading_font)
            draw.text((info_x + 180, current_y), user_data.get('country', 'N/A'), fill='#FFFFFF', font=text_font)
            current_y += line_height
        
        if user_data.get('title'):
            draw.text((info_x, current_y), "Title:", fill='#FFD700', font=heading_font)
            draw.text((info_x + 180, current_y), user_data.get('title', 'N/A'), fill='#FFFFFF', font=text_font)
            current_y += line_height
        
        draw.text((info_x, current_y), "Level:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), str(user_data.get('level', 'N/A') or 'N/A'), fill='#FFFFFF', font=text_font)
        
        footer_y = card_height - 30
        draw.text((card_width // 2, footer_y), f"{ORGANIZATION_NAME} Tournament Bot", fill='#888888', font=small_font, anchor='mt')
        
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        return img_bytes
    except Exception as e:
        print(f"Error creating ID card image: {e}")
        return None
async def sync_player_info_to_channel(guild: discord.Guild, sheet_link: str, format_str: str, channel: discord.TextChannel):
    sheet_match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if not sheet_match:
        return False, "Invalid Google Sheet link."
    
    sheet_id = sheet_match.group(1)
    gid_match = re.search(r'[#&?]gid=([0-9]+)', sheet_link)
    gid = gid_match.group(1) if gid_match else None
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        url += f"&gid={gid}"
    
    try:
        # Purge/clear channel messages
        try:
            await channel.purge(limit=100)
        except Exception as purge_err:
            print(f"Failed to purge participant channel: {purge_err}")

        # Fetch sheet rows
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        rows = list(csv.reader(io.StringIO(resp.text)))
        
        if not rows:
            return False, "Google Sheet is empty."
            
        header = rows[0]
        is_1v1 = (format_str == "1 vs 1")
        
        # Determine team size if not 1v1
        team_size = 5
        if not is_1v1:
            try:
                match = re.search(r'\d+', format_str)
                team_size = int(match.group()) if match else 5
            except:
                pass

        posted_count = 0
        for row in rows[1:]:
            # Check if row is empty or doesn't have sufficient fields
            if not row or all(not cell.strip() for cell in row):
                continue
                
            # Build formatted info
            text_lines = []
            
            # Resolve the captain or player member if possible to mention them
            user_mention = "—"
            
            search_col = -1
            if is_1v1:
                search_col = _col_index(header, "Player Discord ID")
                if search_col == -1:
                    for alias in ["player discord developer id", "discord developer id", "developer id", "player discord id", "discord id", "player discord", "discord tag", "discord name", "discord"]:
                        search_col = _col_index(header, alias)
                        if search_col != -1:
                            break
            else:
                search_col = _col_index(header, "Captain Discord ID")
                if search_col == -1:
                    for alias in ["captain discord developer id", "captain developer id", "discord developer id", "developer id", "captain discord id", "captain discord", "captain id", "discord id", "captain", "captain's discord", "discord tag", "captain discord name", "discord name"]:
                        search_col = _col_index(header, alias)
                        if search_col != -1:
                            break
                            
            if search_col != -1 and search_col < len(row):
                cell_val = row[search_col].strip()
                digits_match = re.search(r'\d+', cell_val)
                if digits_match:
                    member_id = int(digits_match.group())
                    member = guild.get_member(member_id)
                    if not member:
                        try:
                            member = await guild.fetch_member(member_id)
                        except:
                            pass
                    if member:
                        user_mention = member.mention
            
            if is_1v1:
                text_lines.append("🎮 **PLAYER INFORMATION**")
                text_lines.append(f"Player: {user_mention}")
                text_lines.append(f"**Format:** {format_str}")
                text_lines.append("───────────────────────────")
                
                aliases_map_1v1 = {
                    "Player Discord ID": ["player discord developer id", "discord developer id", "developer id", "player discord id", "discord id", "player discord", "discord tag", "discord name", "discord"],
                    "Player Game Name": ["game name", "player name", "ign", "in-game name", "player ign", "player in-game name", "in-game name (for example"],
                    "Player Game ID": ["game id", "player game id", "player id", "uid", "riot id", "player in-game id", "in-game id (for example"],
                    "Player Title": ["title", "player title", "rank", "role", "player in-game title", "in-game title"]
                }
                
                found_any = False
                for field_name in _1V1_FIELDS:
                    aliases = aliases_map_1v1.get(field_name, [])
                    col = _col_index(header, field_name)
                    if col == -1:
                        for alias in aliases:
                            col = _col_index(header, alias)
                            if col != -1:
                                break
                    if col == -1:
                        continue
                    val = row[col].strip() if col < len(row) else ""
                    if not val:
                        val = "—"
                    
                    if ("discord id" in field_name.lower() or "discord_id" in field_name.lower()) and val != "—":
                        digits_match = re.search(r'\d+', val)
                        if digits_match:
                            val = f"<@{digits_match.group()}>"
                        elif val.isdigit():
                            val = f"<@{val}>"
                        else:
                            val = f"`{val}`"
                    elif val != "—":
                        val = f"`{val}`"
                        
                    label = field_name.replace("Player ", "")
                    emoji = ""
                    if "discord id" in field_name.lower():
                        emoji = "👤 "
                        label = "Discord ID"
                    elif "game name" in field_name.lower():
                        emoji = "🎮 "
                        label = "Game Name"
                    elif "game id" in field_name.lower():
                        emoji = "🆔 "
                        label = "Game ID"
                    elif "title" in field_name.lower():
                        emoji = "🎖️ "
                        label = "Title"
                        
                    text_lines.append(f"{emoji}**{label}:** {val}")
                    found_any = True
                if not found_any:
                    text_lines.append(f"⚠️ **Column Mismatch:** Expected columns like `{'` | `'.join(_1V1_FIELDS)}`")
                    
                text_lines.append("───────────────────────────")
                text_lines.append(f"*{guild.name} • Player Info*")
                
            else:
                text_lines.append("🏆 **TEAM INFORMATION**")
                text_lines.append(f"Captain: {user_mention}")
                text_lines.append(f"**Format:** {format_str}")
                text_lines.append("───────────────────────────")
                
                # Team Name
                tn_col = _col_index(header, "Team Name")
                if tn_col == -1:
                    for alias in ["teamname", "team", "clan name", "clan"]:
                        tn_col = _col_index(header, alias)
                        if tn_col != -1:
                            break
                if tn_col != -1:
                    tn_val = row[tn_col].strip() if tn_col < len(row) else "—"
                    text_lines.append(f"🏷️ **Team Name:** {tn_val or '—'}")
                    text_lines.append("")
                    
                # Captain block
                cap_block = []
                aliases_map_captain = {
                    "Captain Discord ID": ["captain discord developer id", "captain developer id", "discord developer id", "developer id", "captain discord id", "captain discord", "captain id", "discord id", "captain", "captain's discord", "discord tag"],
                    "Captain Game Name": ["captain in-game name", "captain ign", "captain game name", "captain name", "captain's ign", "captain's name", "game name", "ign"],
                    "Captain Game ID": ["captain in-game id", "captain game id", "captain uid", "captain's game id", "game id", "uid"],
                    "Captain Title": ["captain in-game title", "captain title", "captain rank", "captain's title", "title", "rank"]
                }
                
                for fname in ["Captain Discord ID", "Captain Game Name", "Captain Game ID", "Captain Title"]:
                    aliases = aliases_map_captain.get(fname, [])
                    col = _col_index(header, fname)
                    if col == -1:
                        for alias in aliases:
                            col = _col_index(header, alias)
                            if col != -1:
                                break
                    if col == -1:
                        continue
                    val = row[col].strip() if col < len(row) else "—"
                    if not val:
                        val = "—"
                    
                    if ("discord id" in fname.lower() or "discord_id" in fname.lower()) and val != "—":
                        digits_match = re.search(r'\d+', val)
                        if digits_match:
                            val = f"<@{digits_match.group()}>"
                        elif val.isdigit():
                            val = f"<@{val}>"
                        else:
                            val = f"`{val}`"
                    elif val != "—":
                        val = f"`{val}`"
                        
                    label = fname.replace("Captain ", "")
                    emoji = ""
                    if "discord id" in fname.lower():
                        emoji = "👤 "
                        label = "Discord ID"
                    elif "game name" in fname.lower():
                        emoji = "🎮 "
                        label = "Game Name"
                    elif "game id" in fname.lower():
                        emoji = "🆔 "
                        label = "Game ID"
                    elif "title" in fname.lower():
                        emoji = "🎖️ "
                        label = "Title"
                    cap_block.append(f"{emoji}**{label}:** {val}")
                    
                if cap_block:
                    text_lines.append("👑 **Captain**")
                    text_lines.extend(cap_block)
                    text_lines.append("")
                    
                # Players
                for n in range(2, team_size + 1):
                    player_block = []
                    for tmpl in _TEAM_PLAYER_FIELDS_TEMPLATE:
                        fname = tmpl.format(n=n)
                        aliases = []
                        if "Discord ID" in fname:
                            aliases = [f"player{n} discord developer id", f"player {n} discord developer id", f"player {n} developer id", f"player{n} developer id", f"p{n} discord developer id", f"p{n} developer id", f"player{n} discord id", f"player {n} discord", f"player {n} id", f"player{n} id", f"p{n} discord id", f"p{n} discord", f"player {n}"]
                        elif "Game Name" in fname:
                            aliases = [f"player{n} in-game name", f"player {n} in-game name", f"p{n} in-game name", f"player{n} game name", f"player {n} ign", f"player {n} name", f"player{n} ign", f"p{n} game name", f"p{n} ign", f"p{n} name"]
                        elif "Game ID" in fname:
                            aliases = [f"player{n} in-game id", f"player {n} in-game id", f"p{n} in-game id", f"player{n} game id", f"player {n} game id", f"player {n} uid", f"player{n} uid", f"p{n} game id", f"p{n} uid"]
                        elif "Title" in fname:
                            aliases = [f"player{n} in-game title", f"player {n} in-game title", f"p{n} in-game title", f"player{n} title", f"player {n} rank", f"player{n} rank", f"p{n} title", f"p{n} rank"]
                            
                        col = _col_index(header, fname)
                        if col == -1:
                            for alias in aliases:
                                col = _col_index(header, alias)
                                if col != -1:
                                    break
                        if col == -1:
                            continue
                        val = row[col].strip() if col < len(row) else "—"
                        if not val:
                            val = "—"
                        
                        if ("discord id" in fname.lower() or "discord_id" in fname.lower()) and val != "—":
                            digits_match = re.search(r'\d+', val)
                            if digits_match:
                                val = f"<@{digits_match.group()}>"
                            elif val.isdigit():
                                val = f"<@{val}>"
                            else:
                                val = f"`{val}`"
                        elif val != "—":
                            val = f"`{val}`"
                            
                        label = fname.replace(f"Player {n} ", "")
                        emoji = ""
                        if "discord id" in fname.lower():
                            emoji = "👤 "
                            label = "Discord ID"
                        elif "game name" in fname.lower():
                            emoji = "🎮 "
                            label = "Game Name"
                        elif "game id" in fname.lower():
                            emoji = "🆔 "
                            label = "Game ID"
                        elif "title" in fname.lower():
                            emoji = "🎖️ "
                            label = "Title"
                        player_block.append(f"{emoji}**{label}:** {val}")
                        
                    if player_block:
                        text_lines.append(f"👥 **Player {n}**")
                        text_lines.extend(player_block)
                        text_lines.append("")
                        
                while text_lines and text_lines[-1] == "":
                    text_lines.pop()
                    
                text_lines.append("───────────────────────────")
                text_lines.append(f"*{guild.name} • Team Info*")
                
            await channel.send("\n".join(text_lines))
            posted_count += 1
            await asyncio.sleep(0.5)
            
        return True, f"Successfully parsed Google Sheet and posted **{posted_count}** player/team details to {channel.mention}."
    except Exception as e:
        print(f"Error syncing player information sheet: {e}")
        return False, f"Failed to sync sheet: {str(e)}"


@tree.command(name="config_player_information", description="Configure player information Google Sheet link, format, and participant channel")
@app_commands.describe(
    sheet_link="Google Sheet link containing player or team details",
    format="The tournament format (e.g. 1 vs 1, 5 vs 5)",
    participant_channel="The channel where player/team information will be automatically posted and updated"
)
@app_commands.choices(
    format=[
        app_commands.Choice(name="1 vs 1", value="1 vs 1"),
        app_commands.Choice(name="2 vs 2", value="2 vs 2"),
        app_commands.Choice(name="3 vs 3", value="3 vs 3"),
        app_commands.Choice(name="4 vs 4", value="4 vs 4"),
        app_commands.Choice(name="5 vs 5", value="5 vs 5")
    ]
)
@with_guild_context
async def config_player_information(
    interaction: discord.Interaction,
    sheet_link: str,
    format: app_commands.Choice[str],
    participant_channel: discord.TextChannel
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to configure player information.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    cfg = get_guild_config(interaction.guild.id)
    cfg['player_info_link'] = sheet_link.strip()
    cfg['player_info_format'] = format.value
    cfg['player_info_participant_channel_id'] = participant_channel.id
    
    # Save the updated guild settings
    save_guild_config(interaction.guild.id, cfg)
    
    # Log bot activity
    log_embed = discord.Embed(
        title="⚙️ Player Info Configured",
        description=(
            f"**Sheet Link:** [Link]({sheet_link.strip()})\n"
            f"**Format:** {format.value}\n"
            f"**Participant Channel:** {participant_channel.mention}"
        ),
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.set_footer(text=f"Configured by {interaction.user.display_name}")
    await log_bot_activity(interaction.guild, log_embed)
    
    # Sync details to participant channel
    success, msg = await sync_player_info_to_channel(interaction.guild, sheet_link.strip(), format.value, participant_channel)
    if success:
        await interaction.followup.send(f"✅ Configuration saved!\n{msg}", ephemeral=True)
    else:
        await interaction.followup.send(f"⚠️ Configuration saved, but sync failed: {msg}", ephemeral=True)


@tree.command(name="player_information", description="Look up player or team info from the configured Google Sheet")
@app_commands.describe(user="The player or team captain to look up")
@with_guild_context
async def player_information(interaction: discord.Interaction, user: discord.Member):
    """Fetches structured player/team info from the configured Google Sheet.
    1 vs 1  -> Player Discord ID, Game Name, Game ID, Title
    2-5 vs  -> Team Name, Captain fields, Player 2-N fields (grouped per player)
    """
    await interaction.response.defer()

    # Convert DynamicString to actual string
    link_str = str(PLAYER_INFO_LINK)
    if not link_str:
        await interaction.followup.send(
            "❌ Player info sheet is not configured yet. Ask an organizer to configure it in `/settings`."
        )
        return

    sheet_match = re.search(r'/d/([a-zA-Z0-9-_]+)', link_str)
    if not sheet_match:
        await interaction.followup.send("❌ Invalid Google Sheet link in config.")
        return

    sheet_id = sheet_match.group(1)
    gid_match = re.search(r'[#&?]gid=([0-9]+)', link_str)
    gid = gid_match.group(1) if gid_match else None
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        url += f"&gid={gid}"

    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        resp.encoding = 'utf-8'  # Force UTF-8 so special characters from the sheet are decoded correctly
        rows = list(csv.reader(io.StringIO(resp.text)))

        if not rows:
            await interaction.followup.send("❌ The player info sheet is empty.")
            return

        header = rows[0]
        user_id_str = str(user.id)
        user_mention = f"<@{user.id}>"

        # Find the row matching this user's Discord ID
        found_row = None
        for row in rows[1:]:
            for cell in row:
                cell_clean = cell.strip()
                if user_id_str in cell_clean or user_mention in cell_clean:
                    found_row = row
                    break
            if found_row:
                break

        if found_row is None:
            await interaction.followup.send(
                f"❌ {user.mention} was not found in the player information sheet.\n"
                f"Make sure their Discord ID is recorded in the sheet."
            )
            return

        # Convert DynamicString to actual string
        info_format = str(PLAYER_INFO_FORMAT)
        is_1v1 = (info_format == "1 vs 1")

        # ── 1 vs 1 Layout ──────────────────────────────────────────────────────
        if is_1v1:
            text_lines = [
                "🎮 **PLAYER INFORMATION**",
                f"Player: {user.mention}",
                f"**Format:** {info_format}",
                "───────────────────────────"
            ]

            found_any = False
            aliases_map_1v1 = {
                "Player Discord ID": ["player discord developer id", "discord developer id", "developer id", "player discord id", "discord id", "player discord", "discord tag", "discord name", "discord"],
                "Player Game Name": ["game name", "player name", "ign", "in-game name", "player ign", "player in-game name", "in-game name (for example"],
                "Player Game ID": ["game id", "player game id", "player id", "uid", "riot id", "player in-game id", "in-game id (for example"],
                "Player Title": ["title", "player title", "rank", "role", "player in-game title", "in-game title"]
            }

            for field_name in _1V1_FIELDS:
                aliases = aliases_map_1v1.get(field_name, [])
                col = _col_index(header, field_name)
                if col == -1:
                    for alias in aliases:
                        col = _col_index(header, alias)
                        if col != -1:
                            break
                if col == -1:
                    continue
                val = found_row[col].strip() if col < len(found_row) else ""
                if not val:
                    val = "—"
                
                # Format value properly (do not backtick-wrap if it's already a mention)
                if ("discord id" in field_name.lower() or "discord_id" in field_name.lower()) and val != "—":
                    digits_match = re.search(r'\d+', val)
                    if digits_match:
                        val = f"<@{digits_match.group()}>"
                    elif val.isdigit():
                        val = f"<@{val}>"
                    else:
                        val = f"`{val}`"
                elif val != "—":
                    val = f"`{val}`"

                # Emoji and Label mapping for premium UI
                label = field_name.replace("Player ", "")
                emoji = ""
                if "discord id" in field_name.lower():
                    emoji = "👤 "
                    label = "Discord ID"
                elif "game name" in field_name.lower():
                    emoji = "🎮 "
                    label = "Game Name"
                elif "game id" in field_name.lower():
                    emoji = "🆔 "
                    label = "Game ID"
                elif "title" in field_name.lower():
                    emoji = "🎖️ "
                    label = "Title"

                text_lines.append(f"{emoji}**{label}:** {val}")
                found_any = True

            if not found_any:
                text_lines.append(f"⚠️ **Column Mismatch:** Expected columns like `{'` | `'.join(_1V1_FIELDS)}`")

            text_lines.append("───────────────────────────")
            text_lines.append(f"*{ORGANIZATION_NAME} • Player Info • Requested by {interaction.user.display_name}*")
            await interaction.followup.send("\n".join(text_lines))

        # ── Team Layout (2v2 – 5v5) ───────────────────────────────────────────
        else:
            try:
                # Find the first number in the format string (e.g. "3 vs 3" -> 3, "4vs4" -> 4)
                match = re.search(r'\d+', info_format)
                team_size = int(match.group()) if match else 5
            except Exception:
                team_size = 5

            text_lines = [
                "🏆 **TEAM INFORMATION**",
                f"Captain: {user.mention}",
                f"**Format:** {info_format}",
                "───────────────────────────"
            ]

            found_any = False

            # Team Name
            tn_col = _col_index(header, "Team Name")
            if tn_col == -1:
                for alias in ["teamname", "team", "clan name", "clan"]:
                    tn_col = _col_index(header, alias)
                    if tn_col != -1:
                        break
            if tn_col != -1:
                tn_val = found_row[tn_col].strip() if tn_col < len(found_row) else "—"
                text_lines.append(f"🏷️ **Team Name:** {tn_val or '—'}")
                text_lines.append("")
                found_any = True

            # Captain block
            cap_block = []
            aliases_map_captain = {
                "Captain Discord ID": ["captain discord developer id", "captain developer id", "discord developer id", "developer id", "captain discord id", "captain discord", "captain id", "discord id", "captain", "captain's discord", "discord tag"],
                "Captain Game Name": ["captain in-game name", "captain ign", "captain game name", "captain name", "captain's ign", "captain's name", "game name", "ign"],
                "Captain Game ID": ["captain in-game id", "captain game id", "captain uid", "captain's game id", "game id", "uid"],
                "Captain Title": ["captain in-game title", "captain title", "captain rank", "captain's title", "title", "rank"]
            }

            for fname in ["Captain Discord ID", "Captain Game Name", "Captain Game ID", "Captain Title"]:
                aliases = aliases_map_captain.get(fname, [])
                col = _col_index(header, fname)
                if col == -1:
                    for alias in aliases:
                        col = _col_index(header, alias)
                        if col != -1:
                            break
                if col == -1:
                    continue
                val = found_row[col].strip() if col < len(found_row) else "—"
                if not val:
                    val = "—"
                
                # Format value properly (do not backtick-wrap if it's already a mention)
                if ("discord id" in fname.lower() or "discord_id" in fname.lower()) and val != "—":
                    digits_match = re.search(r'\d+', val)
                    if digits_match:
                        val = f"<@{digits_match.group()}>"
                    elif val.isdigit():
                        val = f"<@{val}>"
                    else:
                        val = f"`{val}`"
                elif val != "—":
                    val = f"`{val}`"

                # Emoji and Label mapping for premium UI
                label = fname.replace("Captain ", "")
                emoji = ""
                if "discord id" in fname.lower():
                    emoji = "👤 "
                    label = "Discord ID"
                elif "game name" in fname.lower():
                    emoji = "🎮 "
                    label = "Game Name"
                elif "game id" in fname.lower():
                    emoji = "🆔 "
                    label = "Game ID"
                elif "title" in fname.lower():
                    emoji = "🎖️ "
                    label = "Title"

                cap_block.append(f"{emoji}**{label}:** {val}")
                found_any = True
            
            if cap_block:
                text_lines.append("👑 **Captain**")
                text_lines.extend(cap_block)
                text_lines.append("")

            # Each additional player
            for n in range(2, team_size + 1):
                player_block = []
                for tmpl in _TEAM_PLAYER_FIELDS_TEMPLATE:
                    fname = tmpl.format(n=n)
                    aliases = []
                    if "Discord ID" in fname:
                        aliases = [f"player{n} discord developer id", f"player {n} discord developer id", f"player {n} developer id", f"player{n} developer id", f"p{n} discord developer id", f"p{n} developer id", f"player{n} discord id", f"player {n} discord", f"player {n} id", f"player{n} id", f"p{n} discord id", f"p{n} discord", f"player {n}"]
                    elif "Game Name" in fname:
                        aliases = [f"player{n} in-game name", f"player {n} in-game name", f"p{n} in-game name", f"player{n} game name", f"player {n} ign", f"player {n} name", f"player{n} ign", f"p{n} game name", f"p{n} ign", f"p{n} name"]
                    elif "Game ID" in fname:
                        aliases = [f"player{n} in-game id", f"player {n} in-game id", f"p{n} in-game id", f"player{n} game id", f"player {n} game id", f"player {n} uid", f"player{n} uid", f"p{n} game id", f"p{n} uid"]
                    elif "Title" in fname:
                        aliases = [f"player{n} in-game title", f"player {n} in-game title", f"p{n} in-game title", f"player{n} title", f"player {n} rank", f"player{n} rank", f"p{n} title", f"p{n} rank"]

                    col = _col_index(header, fname)
                    if col == -1:
                        for alias in aliases:
                            col = _col_index(header, alias)
                            if col != -1:
                                break
                    if col == -1:
                        continue
                    val = found_row[col].strip() if col < len(found_row) else "—"
                    if not val:
                        val = "—"
                    
                    # Format value properly (do not backtick-wrap if it's already a mention)
                    if ("discord id" in fname.lower() or "discord_id" in fname.lower()) and val != "—":
                        digits_match = re.search(r'\d+', val)
                        if digits_match:
                            val = f"<@{digits_match.group()}>"
                        elif val.isdigit():
                            val = f"<@{val}>"
                        else:
                            val = f"`{val}`"
                    elif val != "—":
                        val = f"`{val}`"

                    # Emoji and Label mapping for premium UI
                    label = fname.replace(f"Player {n} ", "")
                    emoji = ""
                    if "discord id" in fname.lower():
                        emoji = "👤 "
                        label = "Discord ID"
                    elif "game name" in fname.lower():
                        emoji = "🎮 "
                        label = "Game Name"
                    elif "game id" in fname.lower():
                        emoji = "🆔 "
                        label = "Game ID"
                    elif "title" in fname.lower():
                        emoji = "🎖️ "
                        label = "Title"

                    player_block.append(f"{emoji}**{label}:** {val}")
                    found_any = True
                
                if player_block:
                    text_lines.append(f"👥 **Player {n}**")
                    text_lines.extend(player_block)
                    text_lines.append("")

            if not found_any:
                text_lines.append("⚠️ **Column Mismatch:** Sheet headers don't match expected format.")

            # Trim trailing empty lines
            while text_lines and text_lines[-1] == "":
                text_lines.pop()

            text_lines.append("───────────────────────────")
            text_lines.append(f"*{ORGANIZATION_NAME} • Player Info • Requested by {interaction.user.display_name}*")
            await interaction.followup.send("\n".join(text_lines))

    except Exception as e:
        await interaction.followup.send(f"❌ Error fetching player info: {str(e)}")
        print(f"[player_information] Error: {e}")





# ===========================================================================================
# CONFIGURATION AND BRANDING COMMANDS
# ===========================================================================================

def mask_api_key(key: str) -> str:
    if not key:
        return "Not Set"
    if len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]

def is_authorized_to_configure(interaction: discord.Interaction) -> bool:
    if interaction.user.id == BOT_OWNER_ID:
        return True
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    
    cfg = get_guild_config(interaction.guild.id)
    role_ids = cfg.get("role_ids", {})
    head_org_id = role_ids.get("head_organizer")
    if head_org_id:
        member_role_ids = [role.id for role in interaction.user.roles]
        if head_org_id in member_role_ids:
            return True
            
    return False

class OwnerConfirmationView(discord.ui.View):
    def __init__(self, callback_coro, action_description: str, requester: discord.Member):
        super().__init__(timeout=120)
        self.callback_coro = callback_coro
        self.action_description = action_description
        self.requester = requester

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Only the Bot Owner can confirm this action.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Deletion", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await self.callback_coro(interaction)
            # Disable buttons
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(content=f"✅ **Action Confirmed**: {self.action_description} (approved by Bot Owner)", view=None)
        except Exception as e:
            print(f"Error executing owner confirmed action: {e}")
            await interaction.followup.send(f"❌ Error executing action: {e}", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"❌ **Action Cancelled**: {self.action_description} was cancelled.", view=None)

# Group for Settings commands
settings_group = app_commands.Group(name="settings", description="Manage guild settings (Roles, Branding, and Links)")

async def update_settings_logic(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    organizer_role: Optional[discord.Role] = None,
    helper_role: Optional[discord.Role] = None,
    judge_role: Optional[discord.Role] = None,
    recorder_role: Optional[discord.Role] = None,
    staff_role: Optional[discord.Role] = None,
    players_role: Optional[discord.Role] = None,
    server_name: Optional[str] = None,
    tournament_bot_name: Optional[str] = None,
    server_logo: Optional[discord.Attachment] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to manage settings. Only the **Bot Owner**, **Administrators**, or members with the **Head Organizer** role can use this.", ephemeral=True)
        return
        
    cfg = get_guild_config(interaction.guild.id)
    
    updates = []
    
    # Process Roles
    role_mapping = {
        'head_organizer': admin_role,
        'organizer': organizer_role,
        'helper_team': helper_role,
        'judge': judge_role,
        'recorder': recorder_role,
        'staff': staff_role,
        'players': players_role
    }
    
    for key, role_obj in role_mapping.items():
        if role_obj is not None:
            cfg['role_ids'][key] = role_obj.id
            updates.append(f"• **{key.replace('_', ' ').title()} Role:** {role_obj.mention}")
            
    # Process Text/Links
    if server_name is not None:
        cfg['organization_name'] = server_name.strip()
        updates.append(f"• **Server Name:** {server_name.strip()}")
    if tournament_bot_name is not None:
        cfg['tournament_system_name'] = tournament_bot_name.strip()
        updates.append(f"• **Tournament Bot Name:** {tournament_bot_name.strip()}")
        
    # Process Logo
    if server_logo is not None:
        try:
            if server_logo.content_type and server_logo.content_type.startswith("image/"):
                logo_data = await server_logo.read()
                filename = f"server_logo_{interaction.guild.id}.png"
                with open(filename, "wb") as f:
                    f.write(logo_data)
                cfg['server_logo_path'] = filename
                updates.append("• **Server Logo:** Updated successfully")
            else:
                updates.append("⚠️ **Server Logo:** Uploaded file is not a valid image")
        except Exception as logo_err:
            print(f"Error saving server logo: {logo_err}")
            updates.append(f"❌ **Server Logo:** Failed to save logo: {logo_err}")
        
    if not updates:
        await interaction.response.send_message("⚠️ No parameters were provided. Settings remain unchanged.", ephemeral=True)
        return
        
    save_guild_config(interaction.guild.id, cfg)
    
    # Log activity
    log_embed = discord.Embed(
        title="⚙️ Server Settings Updated",
        description=f"Server settings have been updated:\n\n" + "\n".join(updates),
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.set_footer(text=f"Updated by {interaction.user.display_name}")
    await log_bot_activity(interaction.guild, log_embed)
    
    embed = discord.Embed(
        title="✅ Settings Updated",
        description=f"Successfully updated settings for **{cfg.get('organization_name', 'Tournament Organizer')}**:\n\n" + "\n".join(updates),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"Configured by {interaction.user.display_name}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@settings_group.command(name="add", description="Add server-wide settings: configure server roles and branding details")
@app_commands.describe(
    admin_role="Admin / Head Organizer role",
    organizer_role="Organizer role",
    helper_role="Helper Team / Staff role",
    judge_role="Judge role",
    recorder_role="Recorder role",
    staff_role="General staff role (fallback)",
    players_role="Players role",
    server_name="Name of your esports organization/server",
    tournament_bot_name="Branding name for the tournament system",
    server_logo="Upload your server logo image"
)
@with_guild_context
async def settings_add(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    organizer_role: Optional[discord.Role] = None,
    helper_role: Optional[discord.Role] = None,
    judge_role: Optional[discord.Role] = None,
    recorder_role: Optional[discord.Role] = None,
    staff_role: Optional[discord.Role] = None,
    players_role: Optional[discord.Role] = None,
    server_name: Optional[str] = None,
    tournament_bot_name: Optional[str] = None,
    server_logo: Optional[discord.Attachment] = None
):
    await update_settings_logic(
        interaction=interaction,
        admin_role=admin_role,
        organizer_role=organizer_role,
        helper_role=helper_role,
        judge_role=judge_role,
        recorder_role=recorder_role,
        staff_role=staff_role,
        players_role=players_role,
        server_name=server_name,
        tournament_bot_name=tournament_bot_name,
        server_logo=server_logo
    )

@settings_group.command(name="edit", description="Edit server-wide settings: update server roles and branding details")
@app_commands.describe(
    admin_role="Admin / Head Organizer role",
    organizer_role="Organizer role",
    helper_role="Helper Team / Staff role",
    judge_role="Judge role",
    recorder_role="Recorder role",
    staff_role="General staff role (fallback)",
    players_role="Players role",
    server_name="Name of your esports organization/server",
    tournament_bot_name="Branding name for the tournament system",
    server_logo="Upload your server logo image"
)
@with_guild_context
async def settings_edit(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    organizer_role: Optional[discord.Role] = None,
    helper_role: Optional[discord.Role] = None,
    judge_role: Optional[discord.Role] = None,
    recorder_role: Optional[discord.Role] = None,
    staff_role: Optional[discord.Role] = None,
    players_role: Optional[discord.Role] = None,
    server_name: Optional[str] = None,
    tournament_bot_name: Optional[str] = None,
    server_logo: Optional[discord.Attachment] = None
):
    await update_settings_logic(
        interaction=interaction,
        admin_role=admin_role,
        organizer_role=organizer_role,
        helper_role=helper_role,
        judge_role=judge_role,
        recorder_role=recorder_role,
        staff_role=staff_role,
        players_role=players_role,
        server_name=server_name,
        tournament_bot_name=tournament_bot_name,
        server_logo=server_logo
    )

@settings_group.command(name="show", description="Display the current bot settings for this server")
@with_guild_context
async def settings_show(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    cfg = get_guild_config(interaction.guild.id)
    role_ids = cfg.get("role_ids", {})
    guild = interaction.guild

    def get_role_str(key):
        rid = role_ids.get(key)
        if not rid:
            return "`Not Set`"
        role = guild.get_role(int(rid))
        return role.mention if role else f"`ID: {rid}`"

    def get_setting_str(key, default="Not Set"):
        val = cfg.get(key)
        if not val:
            return f"`{default}`"
        if key == "player_info_link":
            return f"[Link]({val})" if val.startswith("http") else f"`{val}`"
        return f"`{val}`"

    embed = discord.Embed(
        title="⚙️ Current Bot Settings",
        description="Here are the configured roles, branding details, and links for this server.",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )

    # Roles section
    roles_value = (
        f"👑 **Admin:** {get_role_str('head_organizer')}\n"
        f"🛡️ **Organizer:** {get_role_str('organizer')}\n"
        f"👥 **Helper:** {get_role_str('helper_team')}\n"
        f"⚖️ **Judge:** {get_role_str('judge')}\n"
        f"🎥 **Recorder:** {get_role_str('recorder')}\n"
        f"📝 **Staff:** {get_role_str('staff')}\n"
        f"🎮 **Players:** {get_role_str('players')}"
    )
    embed.add_field(name="👥 Roles", value=roles_value, inline=False)

    # Branding/Links section
    branding_value = (
        f"🏢 **Server Name:** {get_setting_str('organization_name', 'TASK FORCE TRIDENT')}\n"
        f"⚙️ **Tournament Bot Name:** {get_setting_str('tournament_system_name', 'Tournament Organizer')}"
    )
    embed.add_field(name="🏆 Branding & Links", value=branding_value, inline=False)

    logo_filename = cfg.get('server_logo_path')
    if not logo_filename or not os.path.exists(logo_filename):
        logo_filename = "tournament_bot_logo.png" if os.path.exists("tournament_bot_logo.png") else None

    if logo_filename:
        embed.set_thumbnail(url="attachment://server_logo.png")
    
    embed.set_footer(
        text=f"Requested by {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
    )

    file = None
    if logo_filename:
        file = discord.File(logo_filename, filename="server_logo.png")

    if file:
        await interaction.response.send_message(embed=embed, file=file, ephemeral=True)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=True)

@settings_group.command(name="clean", description="Reset all bot configurations and data to defaults for this server")
@with_guild_context
async def settings_clean(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to clean settings. Only the **Bot Owner**, **Administrators**, or members with the **Head Organizer** role can use this.", ephemeral=True)
        return
        
    async def do_clean(confirm_interaction: discord.Interaction):
        guild_id = interaction.guild.id
        guild_id_str = str(guild_id)
        
        # 1. Reset caches for this guild
        GUILD_CONFIG_CACHE[guild_id_str] = get_default_config()
        TOURNAMENTS_CACHE[guild_id_str] = {}
        if guild_id_str in RULES_CACHE:
            del RULES_CACHE[guild_id_str]
        if guild_id_str in STAFF_STATS_CACHE:
            del STAFF_STATS_CACHE[guild_id_str]
        if guild_id in CHALLONGE_MATCHES_CACHE:
            del CHALLONGE_MATCHES_CACHE[guild_id]
            
        # 2. Delete from Supabase tables
        if supabase_client:
            tables = ["GuildConfig", "Tournaments", "Events", "JudgeAssignments", "StaffStats", "Results", "Challonge_Uploads"]
            for table in tables:
                try:
                    supabase_client.table(table).delete().eq("Guild_ID", guild_id_str).execute()
                    print(f"[Supabase] Cleaned table '{table}' for guild {guild_id}")
                except Exception as e:
                    print(f"[Supabase] Error cleaning table '{table}': {e}")
                    
        # 3. Wiping local JSON configurations / databases
        if os.path.exists('guild_configs.json'):
            try:
                with open('guild_configs.json', 'r', encoding='utf-8') as f:
                    all_configs = json.load(f)
                if guild_id_str in all_configs:
                    del all_configs[guild_id_str]
                    with open('guild_configs.json', 'w', encoding='utf-8') as f:
                        json.dump(all_configs, f, indent=4)
            except Exception as e:
                print(f"Error cleaning guild_configs.json: {e}")
                
        if os.path.exists('tournaments.json'):
            try:
                with open('tournaments.json', 'r', encoding='utf-8') as f:
                    all_tournaments = json.load(f)
                if guild_id_str in all_tournaments:
                    del all_tournaments[guild_id_str]
                    with open('tournaments.json', 'w', encoding='utf-8') as f:
                        json.dump(all_tournaments, f, indent=4)
            except Exception as e:
                print(f"Error cleaning tournaments.json: {e}")

        if os.path.exists('tournament_rules.json'):
            try:
                with open('tournament_rules.json', 'r', encoding='utf-8') as f:
                    all_rules = json.load(f)
                if guild_id_str in all_rules:
                    del all_rules[guild_id_str]
                    with open('tournament_rules.json', 'w', encoding='utf-8') as f:
                        json.dump(all_rules, f, indent=4)
            except Exception as e:
                print(f"Error cleaning tournament_rules.json: {e}")

        if os.path.exists('staff_stats.json'):
            try:
                with open('staff_stats.json', 'r', encoding='utf-8') as f:
                    all_stats = json.load(f)
                if guild_id_str in all_stats:
                    del all_stats[guild_id_str]
                    with open('staff_stats.json', 'w', encoding='utf-8') as f:
                        json.dump(all_stats, f, indent=4)
            except Exception as e:
                print(f"Error cleaning staff_stats.json: {e}")

        global scheduled_events
        to_delete_events = [ev_id for ev_id, ev_data in scheduled_events.items() if ev_data.get('guild_id') == guild_id]
        if to_delete_events:
            for ev_id in to_delete_events:
                del scheduled_events[ev_id]
            save_scheduled_events()

        # Log bot activity
        log_embed = discord.Embed(
            title="🧹 Server Settings Cleaned",
            description=f"All bot settings, tournament configurations, events, logs, stats, and rules have been completely reset.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)

        embed = discord.Embed(
            title="🧹 Settings Cleaned",
            description="All bot settings, tournament configurations, events, logs, stats, and rules have been completely reset and cleaned for this server.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Cleaned by {interaction.user.display_name}")
        await confirm_interaction.followup.send(embed=embed, ephemeral=True)

    if interaction.user.id == BOT_OWNER_ID:
        class SelfConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
            @discord.ui.button(label="✅ Yes, Clean Everything", style=discord.ButtonStyle.danger)
            async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.defer()
                await do_clean(button_interaction)
                await button_interaction.message.edit(content="✅ Cleaned server settings.", view=None)
            @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.edit_message(content="Cancelled.", view=None)
        await interaction.response.send_message("⚠️ **WARNING**: This will permanently delete all data and configurations for this server! Are you sure you want to proceed?", view=SelfConfirmView(), ephemeral=True)
    else:
        view = OwnerConfirmationView(do_clean, f"Clean all settings for server **{interaction.guild.name}**", interaction.user)
        await interaction.response.send_message(
            content=f"⚠️ <@{BOT_OWNER_ID}> **Owner Deletion Confirmation Required!**\n"
                    f"{interaction.user.mention} requested to reset/clean all bot configurations and data for this server.\n"
                    f"Please confirm or cancel this action below.",
            view=view
        )

# Register settings_group
bot.tree.add_command(settings_group)


# ===========================================================================================
# MULTI-TOURNAMENT MANAGEMENT CONFIGURATION
# ===========================================================================================

TOURNAMENTS_CACHE = {}

def get_default_tournament_data():
    return {
        'name': "",
        'id': "",
        'key': "",
        'challonge_bracket_link': "",
        'captains_sheet_link': "",
        'state': 'pending',  # pending, active, completed
        
        # Channels
        'thumbnail': None,
        'attendance': None,
        'transcript': None,
        'schedule': None,
        'rules': None,
        'deadline': None,
        'result': None,
        'challonge_logs': None,
        'transcript_logs': None,
        'bot_logs': None,
        'participant': None,
        
        # Categories
        'closed_ticket_1': None,
        'closed_ticket_2': None,
        'ticket_open_category_1': None,
        'ticket_open_category_2': None,
        'ticket_open_category_3': None
    }

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
                    print(f"Loaded tournaments for guild {guild_id} from tournaments.json")
        except Exception as e:
            print(f"Error loading tournaments.json: {e}")
            
    # 2. Overlay or merge with Supabase data, preserving local channel configurations if missing in DB
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
                            "key": row.get("Key") or existing.get("key") or "",
                            "challonge_bracket_link": row.get("challonge_bracket_link") or existing.get("challonge_bracket_link") or "",
                            "captains_sheet_link": row.get("Captains_Sheet_Link") or row.get("Sheet_Link") or existing.get("captains_sheet_link") or "",
                            "sheet_link": row.get("Captains_Sheet_Link") or row.get("Sheet_Link") or existing.get("sheet_link") or "",
                        })
                        
                        # Only overwrite channel/category fields from Supabase if they are not None/empty
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
                                    existing[dict_key] = int(db_val)
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

                        # Players role ID (tournament-level override of guild Players_Role_ID)
                        db_val = row.get("Players_Role_ID")
                        if db_val not in (None, "", "None"):
                            try:
                                existing["players_role_id"] = int(db_val)
                            except:
                                pass
                                    
                        tournaments[t_id] = existing
                print(f"Merged tournaments for guild {guild_id} with Supabase.")
        except Exception as e:
            print(f"Error loading/merging tournaments from Supabase: {e}")
            
    TOURNAMENTS_CACHE[guild_id_str] = tournaments
    return tournaments

def save_guild_tournaments(guild_id: int, tournaments: dict):
    guild_id_str = str(guild_id)
    TOURNAMENTS_CACHE[guild_id_str] = tournaments
    
    # Save locally to JSON fallback
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
        print(f"Saved tournaments for guild {guild_id} to tournaments.json")
    except Exception as e:
        print(f"Error saving tournaments to tournaments.json: {e}")
            
    # Sync tournaments to Supabase in the background (SheetDB is removed)
    try:
        if supabase_client:
            loop = asyncio.get_running_loop()
            for t_id, t_data in tournaments.items():
                loop.create_task(save_tournament_to_supabase(guild_id, t_id, t_data))
    except RuntimeError:
        pass

def get_active_tournament_config(guild_id: int) -> Optional[dict]:
    tournaments = load_guild_tournaments(guild_id)
    for t_id, t_cfg in tournaments.items():
        if t_cfg.get('state') == 'active':
            return t_cfg
    return None

async def log_bot_activity(guild: discord.Guild, embed: discord.Embed):
    if not guild:
        return
    t_cfg = get_active_tournament_config(guild.id)
    channel = None
    if t_cfg and t_cfg.get('bot_logs'):
        try:
            channel = guild.get_channel(int(t_cfg['bot_logs']))
            if not channel:
                channel = await guild.fetch_channel(int(t_cfg['bot_logs']))
        except Exception:
            pass
            
    if not channel:
        cfg = get_guild_config(guild.id)
        default_logs_id = cfg.get('channel_ids', {}).get('bot_logs')
        if default_logs_id:
            try:
                channel = guild.get_channel(int(default_logs_id))
                if not channel:
                    channel = await guild.fetch_channel(int(default_logs_id))
            except Exception:
                pass
                
    if channel:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"Failed to log bot activity: {e}")

async def get_thumbnail_url_from_channel(channel_id: Optional[int]) -> Optional[str]:
    if not channel_id:
        return None
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            channel = await bot.fetch_channel(channel_id)
        if channel and isinstance(channel, discord.TextChannel):
            async for message in channel.history(limit=20):
                if message.attachments:
                    for att in message.attachments:
                        if att.content_type and att.content_type.startswith("image/"):
                            return att.url
    except Exception as e:
        print(f"Error fetching thumbnail from channel {channel_id}: {e}")
    return None

async def resolve_embed_thumbnail(guild_id: int, embed: discord.Embed, fallback_to_captain_avatar: Optional[discord.Member] = None) -> tuple[Optional[discord.File], bool]:
    """
    Resolves the thumbnail for a tournament/match embed.
    Order of precedence:
    1. Configured server logo (server_logo_{guild_id}.png)
    2. Guild icon (guild.icon.url)
    3. Active tournament's thumbnail (resolved from the configured thumbnail channel)
    4. Default bundled logo (tournament_bot_logo.png)
    5. Captain's avatar (if fallback_to_captain_avatar is provided)
    
    Returns a tuple: (discord.File if local image is used, bool indicating if a local image attachment was used)
    """
    # 1. Try configured server logo
    cfg = get_guild_config(guild_id)
    logo_filename = cfg.get('server_logo_path')
    if logo_filename and os.path.exists(logo_filename):
        try:
            with open(logo_filename, "rb") as f:
                logo_data = f.read()
            embed.set_thumbnail(url="attachment://server_logo.png")
            file_obj = discord.File(
                fp=io.BytesIO(logo_data),
                filename="server_logo.png"
            )
            return file_obj, True
        except Exception as e:
            print(f"Error loading server logo path {logo_filename}: {e}")

    # 2. Try guild icon
    guild = bot.get_guild(guild_id)
    if guild and guild.icon:
        try:
            embed.set_thumbnail(url=guild.icon.url)
            return None, False
        except Exception as e:
            print(f"Error setting guild icon thumbnail: {e}")

    # 3. Try active tournament's thumbnail channel
    t_cfg = get_active_tournament_config(guild_id)
    if t_cfg:
        thumb_chan_id = t_cfg.get('thumbnail')
        if thumb_chan_id:
            try:
                thumb_url = await get_thumbnail_url_from_channel(int(thumb_chan_id))
                if thumb_url:
                    embed.set_thumbnail(url=thumb_url)
                    return None, False
            except Exception as e:
                print(f"Error resolving thumbnail from channel {thumb_chan_id}: {e}")
                
    # 4. Try default bundled tournament logo
    default_logo_path = os.path.join(BASE_DIR, "tournament_bot_logo.png")
    if os.path.exists(default_logo_path):
        try:
            with open(default_logo_path, "rb") as f:
                logo_data = f.read()
            embed.set_thumbnail(url="attachment://tournament_bot_logo.png")
            file_obj = discord.File(
                fp=io.BytesIO(logo_data),
                filename="tournament_bot_logo.png"
            )
            return file_obj, True
        except Exception as e:
            print(f"Error loading default logo {default_logo_path}: {e}")

    # 5. Fallback to captain avatar
    if fallback_to_captain_avatar and hasattr(fallback_to_captain_avatar, 'display_avatar'):
        embed.set_thumbnail(url=fallback_to_captain_avatar.display_avatar.url)
        return None, False

    return None, False

async def build_tournament_embed(interaction: discord.Interaction, t_data: dict, action_title: str) -> tuple[discord.Embed, Optional[discord.File]]:
    guild = interaction.guild
    embed = discord.Embed(
        title=f"🏆 {action_title}: {t_data['name']}",
        description="A tournament configuration has been updated/registered on this server." if "Edit" in action_title else "A new tournament has been registered on this server.",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )
    
    def safe_int(v):
        try:
            return int(v) if v is not None else None
        except:
            return None

    # Retrieve roles from global settings fallback if not set per-tournament
    cfg = get_guild_config(interaction.guild_id)
    admin_role_id = safe_int(cfg.get('role_ids', {}).get('head_organizer'))
    helper_role_id = safe_int(cfg.get('role_ids', {}).get('helper_team'))
    
    admin_role = guild.get_role(admin_role_id) if admin_role_id else None
    helper_role = guild.get_role(helper_role_id) if helper_role_id else None
    
    admin_str = admin_role.mention if admin_role else "Using default from settings"
    helper_str = helper_role.mention if helper_role else "Using default from settings"
    
    # Resolve channel mentions
    def chan_mention(key):
        cid = safe_int(t_data.get(key))
        if not cid:
            return "Not Set"
        ch = guild.get_channel(cid)
        return ch.mention if ch else f"`ID: {cid}`"
        
    def cat_mention(key):
        cid = safe_int(t_data.get(key))
        if not cid:
            return "Not Set"
        ch = guild.get_channel(cid)
        return f"#{ch.name}" if ch else f"`ID: {cid}`"

    sheet_link = t_data.get('captains_sheet_link', '')
    sheet_str  = f"[Click Here]({sheet_link})" if sheet_link else "Not Set"

    bracket_val = t_data.get('challonge_bracket_link', '')
    bracket_str = f"[Click Here]({bracket_val})" if bracket_val.startswith("http") else (f"`{bracket_val}`" if bracket_val else "Not Set")

    key_val = t_data.get('key', '')
    key_str = f"`{mask_api_key(key_val)}`"

    # Thumbnail channel logic
    thumb_chan_id = safe_int(t_data.get('thumbnail'))
    thumb_url = await get_thumbnail_url_from_channel(thumb_chan_id)
    
    file = None
    if thumb_url and thumb_url.startswith("http") and "discord.com/channels/" not in thumb_url:
        embed.set_thumbnail(url=thumb_url)
        thumb_str = f"[Image Link]({thumb_url}) (from {chan_mention('thumbnail')})"
    else:
        # Try a template image from Templates folder
        template_path = get_random_template()
        if template_path and os.path.exists(template_path):
            try:
                from PIL import Image
                with Image.open(template_path) as img:
                    img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                    thumb_bytes = io.BytesIO()
                    fmt = img.format if img.format else "PNG"
                    img.save(thumb_bytes, format=fmt)
                    thumb_bytes.seek(0)
                ext = os.path.splitext(template_path)[1].lower() or ".png"
                file_name = f"thumbnail{ext}"
                embed.set_thumbnail(url=f"attachment://{file_name}")
                file = discord.File(fp=thumb_bytes, filename=file_name)
                thumb_str = f"Template: {os.path.basename(template_path)} (Channel: {chan_mention('thumbnail')})"
            except Exception as e:
                print(f"Error processing template {template_path} for config thumbnail: {e}")
                # Fall back to local file attachment
                embed.set_thumbnail(url="attachment://tournament_bot_logo.png")
                if os.path.exists("tournament_bot_logo.png"):
                    file = discord.File("tournament_bot_logo.png", filename="tournament_bot_logo.png")
                thumb_str = f"Default Logo (Channel: {chan_mention('thumbnail')})"
        else:
            # Fall back to local file attachment
            embed.set_thumbnail(url="attachment://tournament_bot_logo.png")
            if os.path.exists("tournament_bot_logo.png"):
                file = discord.File("tournament_bot_logo.png", filename="tournament_bot_logo.png")
            thumb_str = f"Default Logo (Channel: {chan_mention('thumbnail')})"

    # Row 1: Tournament ID | State | Key
    embed.add_field(name="🆔 Tournament ID",   value=f"`{t_data['id']}`",    inline=True)
    embed.add_field(name="📊 Tournament State", value=f"`{t_data['state']}`", inline=True)
    embed.add_field(name="🔑 Challonge API Key", value=key_str,               inline=True)

    # Row 2: Transcript | Closed Category 1 | Closed Category 2
    embed.add_field(name="🗒️ Transcript Channel",      value=chan_mention('transcript'),  inline=True)
    embed.add_field(name="📁 Closed Category 1",        value=cat_mention('closed_ticket_1'), inline=True)
    embed.add_field(name="📁 Closed Category 2",        value=cat_mention('closed_ticket_2'), inline=True)

    # Row 3: Rules | Deadline | Result
    embed.add_field(name="📌 Rules Channel",    value=chan_mention('rules'),    inline=True)
    embed.add_field(name="📅 Deadline Channel", value=chan_mention('deadline'), inline=True)
    embed.add_field(name="🏅 Result Channel",   value=chan_mention('result'),      inline=True)

    # Row 4: Challonge Bracket | Attendance | Challonge Logs
    embed.add_field(name="🎮 Challonge Bracket",   value=bracket_str, inline=True)
    embed.add_field(name="📊 Attendance Channel",  value=chan_mention('attendance'),    inline=True)
    embed.add_field(name="📝 Challonge Logs",      value=chan_mention('challonge_logs'),  inline=True)

    # Row 5: Transcript Logs | Bot Logs | Thumbnail
    embed.add_field(name="🗒️ Transcript Logs",    value=chan_mention('transcript_logs'), inline=True)
    embed.add_field(name="🤖 Bot Logs Channel",    value=chan_mention('bot_logs'),        inline=True)
    embed.add_field(name="🖼️ Thumbnail",           value=thumb_str,  inline=True)

    # Row 7: Open Ticket Categories list
    open_cats = []
    for i in range(1, 4):
        cat_id = t_data.get(f'ticket_open_category_{i}')
        cat = guild.get_channel(safe_int(cat_id)) if cat_id else None
        if cat:
            open_cats.append(f"▪️ Category {i}: # 🏆 {cat.name} 🏆")
    if open_cats:
        embed.add_field(name="📂 Open Ticket Categories", value="\n".join(open_cats), inline=False)

    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)
    return embed, file

async def tournament_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    try:
        tournaments = load_guild_tournaments(interaction.guild_id)
        choices = []
        for t_id, t_cfg in tournaments.items():
            name = t_cfg.get('name', t_id)
            if current.lower() in name.lower() or current.lower() in t_id.lower():
                choices.append(app_commands.Choice(name=name, value=t_id))
        return choices[:25]
    except Exception as e:
        print(f"Error in tournament_autocomplete: {e}")
        return []

tournament_group = app_commands.Group(name="tournament", description="Manage tournaments configurations")

@tournament_group.command(name="add", description="Add a tournament configuration")
@app_commands.describe(
    name="The user-friendly display name of the tournament",
    id="Unique ID for the tournament (optional, defaults to lowercase name with underscores)",
    challonge_api_key="Challonge API Key for bracket integration",
    challonge_bracket_link="Challonge Bracket URL or ID",
    attendance="Channel for staff attendance logs",
    transcript="Channel for ticket transcripts",
    schedule="Channel for schedule announcements",
    rules="Channel for rule configurations/posts",
    deadline="Channel for match deadline alerts",
    result="Channel where match results are posted",
    challonge_logs="Channel for Challonge action logs",
    transcript_logs="Channel for match tickets transcript logs",
    bot_logs="Channel for bot logs",
    closed_ticket_1="Category for closed tickets 1",
    closed_ticket_2="Category for closed tickets 2",
    ticket_open_category_1="Open ticket category 1",
    ticket_open_category_2="Open ticket category 2",
    ticket_open_category_3="Open ticket category 3",
    auto_room_creation="Whether to enable auto-ticket creation loops"
)
@with_guild_context
async def tournament_add(
    interaction: discord.Interaction,
    name: str,
    id: Optional[str] = None,
    challonge_api_key: Optional[str] = None,
    challonge_bracket_link: Optional[str] = None,
    attendance: Optional[discord.TextChannel] = None,
    transcript: Optional[discord.TextChannel] = None,
    schedule: Optional[discord.TextChannel] = None,
    rules: Optional[discord.TextChannel] = None,
    deadline: Optional[discord.TextChannel] = None,
    result: Optional[discord.TextChannel] = None,
    challonge_logs: Optional[discord.TextChannel] = None,
    transcript_logs: Optional[discord.TextChannel] = None,
    bot_logs: Optional[discord.TextChannel] = None,
    closed_ticket_1: Optional[discord.CategoryChannel] = None,
    closed_ticket_2: Optional[discord.CategoryChannel] = None,
    ticket_open_category_1: Optional[discord.CategoryChannel] = None,
    ticket_open_category_2: Optional[discord.CategoryChannel] = None,
    ticket_open_category_3: Optional[discord.CategoryChannel] = None,
    auto_room_creation: Optional[bool] = True
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to manage tournaments.", ephemeral=True)
        return
        
    await interaction.response.defer()
    tournaments = load_guild_tournaments(interaction.guild.id)
    
    t_id_clean = id.strip().replace(" ", "_") if id else name.strip().lower().replace(" ", "_")
    t_id_clean = re.sub(r'[^a-zA-Z0-9_]', '', t_id_clean)
    
    if t_id_clean in tournaments:
        await interaction.followup.send(f"❌ A tournament with ID `{t_id_clean}` already exists.")
        return
        
    t_data = get_default_tournament_data()
    t_data.update({
        'name': name.strip(),
        'id': t_id_clean,
        'key': challonge_api_key.strip() if challonge_api_key else "",
        'challonge_bracket_link': challonge_bracket_link.strip() if challonge_bracket_link else "",
        
        # Channels
        'thumbnail': None,
        'attendance': attendance.id if attendance else None,
        'transcript': transcript.id if transcript else None,
        'schedule': schedule.id if schedule else None,
        'rules': rules.id if rules else None,
        'deadline': deadline.id if deadline else None,
        'result': result.id if result else None,
        'challonge_logs': challonge_logs.id if challonge_logs else None,
        'transcript_logs': transcript_logs.id if transcript_logs else None,
        'bot_logs': bot_logs.id if bot_logs else None,
        
        # Categories
        'closed_ticket_1': closed_ticket_1.id if closed_ticket_1 else None,
        'closed_ticket_2': closed_ticket_2.id if closed_ticket_2 else None,
        'ticket_open_category_1': ticket_open_category_1.id if ticket_open_category_1 else None,
        'ticket_open_category_2': ticket_open_category_2.id if ticket_open_category_2 else None,
        'ticket_open_category_3': ticket_open_category_3.id if ticket_open_category_3 else None,

        'auto_room_creation': auto_room_creation if auto_room_creation is not None else True,
        'state': 'pending'
    })
    
    if not tournaments:
        t_data['state'] = 'active'
        if t_data.get('auto_room_creation', True):
            start_auto_room_loop(interaction.guild.id)
        
    tournaments[t_id_clean] = t_data
    save_guild_tournaments(interaction.guild.id, tournaments)
    
    # Log bot activity
    log_embed = discord.Embed(
        title="🏆 Tournament Created",
        description=f"A new tournament has been created: **{name.strip()}** (ID: `{t_id_clean}`)",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.set_footer(text=f"Created by {interaction.user.display_name}")
    await log_bot_activity(interaction.guild, log_embed)
    
    embed, file = await build_tournament_embed(interaction, t_data, "Tournament Created")
    if file:
        await interaction.followup.send(embed=embed, file=file)
    else:
        await interaction.followup.send(embed=embed)

@tournament_group.command(name="edit", description="Edit an existing tournament configuration")
@app_commands.choices(
    state=[
        app_commands.Choice(name="pending", value="pending"),
        app_commands.Choice(name="active", value="active"),
        app_commands.Choice(name="completed", value="completed")
    ]
)
@app_commands.autocomplete(tournament=tournament_autocomplete)
@app_commands.describe(
    tournament="Select the tournament configuration to edit",
    name="The user-friendly display name of the tournament",
    challonge_api_key="Challonge API Key for bracket integration",
    challonge_bracket_link="Challonge Bracket URL or ID",
    attendance="Channel for staff attendance logs",
    transcript="Channel for ticket transcripts",
    schedule="Channel for schedule announcements",
    rules="Channel for rule configurations/posts",
    deadline="Channel for match deadline alerts",
    result="Channel where match results are posted",
    challonge_logs="Channel for Challonge action logs",
    transcript_logs="Channel for match tickets transcript logs",
    bot_logs="Channel for bot logs",
    closed_ticket_1="Category for closed tickets 1",
    closed_ticket_2="Category for closed tickets 2",
    ticket_open_category_1="Open ticket category 1",
    ticket_open_category_2="Open ticket category 2",
    ticket_open_category_3="Open ticket category 3",
    auto_room_creation="Whether to enable auto-ticket creation loops",
    state="The lifecycle state of this tournament"
)
@with_guild_context
async def tournament_edit(
    interaction: discord.Interaction,
    tournament: str,
    name: Optional[str] = None,
    challonge_api_key: Optional[str] = None,
    challonge_bracket_link: Optional[str] = None,
    attendance: Optional[discord.TextChannel] = None,
    transcript: Optional[discord.TextChannel] = None,
    schedule: Optional[discord.TextChannel] = None,
    rules: Optional[discord.TextChannel] = None,
    deadline: Optional[discord.TextChannel] = None,
    result: Optional[discord.TextChannel] = None,
    challonge_logs: Optional[discord.TextChannel] = None,
    transcript_logs: Optional[discord.TextChannel] = None,
    bot_logs: Optional[discord.TextChannel] = None,
    closed_ticket_1: Optional[discord.CategoryChannel] = None,
    closed_ticket_2: Optional[discord.CategoryChannel] = None,
    ticket_open_category_1: Optional[discord.CategoryChannel] = None,
    ticket_open_category_2: Optional[discord.CategoryChannel] = None,
    ticket_open_category_3: Optional[discord.CategoryChannel] = None,
    auto_room_creation: Optional[bool] = None,
    state: Optional[app_commands.Choice[str]] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to manage tournaments.", ephemeral=True)
        return
        
    await interaction.response.defer()
    tournaments = load_guild_tournaments(interaction.guild.id)
    
    t_id_clean = tournament.strip().replace(" ", "_")
    if t_id_clean not in tournaments:
        await interaction.followup.send(f"❌ Tournament with ID `{t_id_clean}` not found.")
        return
        
    t_data = tournaments[t_id_clean]
    
    if name is not None:
        t_data['name'] = name.strip()
    if challonge_api_key is not None:
        t_data['key'] = challonge_api_key.strip()
    if challonge_bracket_link is not None:
        t_data['challonge_bracket_link'] = challonge_bracket_link.strip()
    # Channels
    if attendance is not None:
        t_data['attendance'] = attendance.id
    if transcript is not None:
        t_data['transcript'] = transcript.id
    if schedule is not None:
        t_data['schedule'] = schedule.id
    if rules is not None:
        t_data['rules'] = rules.id
    if deadline is not None:
        t_data['deadline'] = deadline.id
    if result is not None:
        t_data['result'] = result.id
    if challonge_logs is not None:
        t_data['challonge_logs'] = challonge_logs.id
    if transcript_logs is not None:
        t_data['transcript_logs'] = transcript_logs.id
    if bot_logs is not None:
        t_data['bot_logs'] = bot_logs.id
        
    # Categories
    if closed_ticket_1 is not None:
        t_data['closed_ticket_1'] = closed_ticket_1.id
    if closed_ticket_2 is not None:
        t_data['closed_ticket_2'] = closed_ticket_2.id
    if ticket_open_category_1 is not None:
        t_data['ticket_open_category_1'] = ticket_open_category_1.id
    if ticket_open_category_2 is not None:
        t_data['ticket_open_category_2'] = ticket_open_category_2.id
    if ticket_open_category_3 is not None:
        t_data['ticket_open_category_3'] = ticket_open_category_3.id
        
    if auto_room_creation is not None:
        t_data['auto_room_creation'] = auto_room_creation

    if state is not None:
        new_state = state.value
        t_data['state'] = new_state
        if new_state == 'active':
            start_auto_room_loop(interaction.guild.id)
            for other_id, other_cfg in tournaments.items():
                if other_id != t_id_clean and other_cfg.get('state') == 'active':
                    other_cfg['state'] = 'pending'
                    
    tournaments[t_id_clean] = t_data
    save_guild_tournaments(interaction.guild.id, tournaments)
    
    # Log bot activity
    log_embed = discord.Embed(
        title="📝 Tournament Edited",
        description=f"Tournament **{t_data['name']}** (ID: `{t_id_clean}`) configuration has been updated.",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.set_footer(text=f"Edited by {interaction.user.display_name}")
    await log_bot_activity(interaction.guild, log_embed)
    
    embed, file = await build_tournament_embed(interaction, t_data, "Tournament Edited")
    if file:
        await interaction.followup.send(embed=embed, file=file)
    else:
        await interaction.followup.send(embed=embed)

@tournament_group.command(name="delete", description="Delete an existing tournament configuration")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def tournament_delete(interaction: discord.Interaction, tournament: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to manage tournaments.", ephemeral=True)
        return
        
    tournaments = load_guild_tournaments(interaction.guild.id)
    t_id_clean = tournament.strip().replace(" ", "_")
    if t_id_clean not in tournaments:
        await interaction.response.send_message(f"❌ Tournament with ID `{t_id_clean}` not found.", ephemeral=True)
        return
        
    t_data = tournaments[t_id_clean]

    async def do_delete(confirm_interaction: discord.Interaction):
        del tournaments[t_id_clean]
        save_guild_tournaments(interaction.guild.id, tournaments)
        asyncio.create_task(delete_tournament_from_sheetdb(interaction.guild.id, t_id_clean))
        if supabase_client:
            asyncio.create_task(delete_tournament_from_supabase(interaction.guild.id, t_id_clean))
        
        active_exists = False
        for other_id, other_cfg in tournaments.items():
            if other_cfg.get('state') == 'active':
                active_exists = True
                break
        if not active_exists:
            stop_auto_room_loop(interaction.guild.id)
            
        # Log bot activity
        log_embed = discord.Embed(
            title="🗑️ Tournament Deleted",
            description=f"Tournament **{t_data['name']}** (ID: `{t_id_clean}`) was deleted.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Deleted by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)

        embed = discord.Embed(
            title="🗑️ Tournament Deleted",
            description=f"Successfully deleted tournament configuration for **{t_data['name']}** (ID: `{t_id_clean}`).",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        await confirm_interaction.followup.send(embed=embed, ephemeral=True)

    if interaction.user.id == BOT_OWNER_ID:
        class SelfConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
            @discord.ui.button(label="✅ Yes, Delete", style=discord.ButtonStyle.danger)
            async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.defer()
                await do_delete(button_interaction)
                await button_interaction.message.edit(content=f"✅ Deleted tournament `{t_id_clean}`.", view=None)
            @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.edit_message(content="Cancelled.", view=None)
        await interaction.response.send_message(f"⚠️ Are you sure you want to permanently delete tournament **{t_data['name']}** (ID: `{t_id_clean}`)?", view=SelfConfirmView(), ephemeral=True)
    else:
        view = OwnerConfirmationView(do_delete, f"Delete tournament **{t_data['name']}** (ID: `{t_id_clean}`)", interaction.user)
        await interaction.response.send_message(
            content=f"⚠️ <@{BOT_OWNER_ID}> **Owner Deletion Confirmation Required!**\n"
                    f"{interaction.user.mention} requested to permanently delete tournament **{t_data['name']}** (ID: `{t_id_clean}`).\n"
                    f"Please confirm or cancel this action below.",
            view=view
        )

@tournament_group.command(name="info", description="Get information about a specific tournament")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def tournament_info(interaction: discord.Interaction, tournament: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    await interaction.response.defer()
    tournaments = load_guild_tournaments(interaction.guild.id)
    
    t_id_clean = tournament.strip().replace(" ", "_")
    if t_id_clean not in tournaments:
        await interaction.followup.send(f"❌ Tournament with ID `{t_id_clean}` not found.")
        return
        
    t_data = tournaments[t_id_clean]
    embed, file = await build_tournament_embed(interaction, t_data, "Tournament Info")
    if file:
        await interaction.followup.send(embed=embed, file=file)
    else:
        await interaction.followup.send(embed=embed)

@tournament_group.command(name="list", description="Get the tournament list for this server")
@with_guild_context
async def tournament_list(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    await interaction.response.defer()
    tournaments = load_guild_tournaments(interaction.guild.id)
    
    if not tournaments:
        await interaction.followup.send("ℹ️ No tournaments have been configured on this server yet.")
        return
        
    embed = discord.Embed(
        title="🏆 Tournament List",
        description="Here is the list of configured tournaments for this server.",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )
    
    for t_id, t_cfg in tournaments.items():
        state_emoji = "🟢" if t_cfg.get('state') == 'active' else ("🟡" if t_cfg.get('state') == 'pending' else "🔴")
        embed.add_field(
            name=f"{state_emoji} {t_cfg['name']}",
            value=f"**ID:** `{t_id}`\n**State:** `{t_cfg.get('state', 'pending')}`\n**Auto Rooms:** `{'Enabled' if t_cfg.get('auto_room_creation', True) else 'Disabled'}`",
            inline=True
        )
        
    await interaction.followup.send(embed=embed)

auto_room_group = app_commands.Group(name="auto_room", description="Automatic room creation management")

@auto_room_group.command(name="run", description="Manually trigger auto room creation")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_run(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
        return
        
    await interaction.response.defer()
    
    try:
        tournaments = load_guild_tournaments(interaction.guild.id)
        t_cfg = None
        if tournament:
            t_id_clean = tournament.strip().replace(" ", "_")
            t_cfg = tournaments.get(t_id_clean)
            if not t_cfg:
                await interaction.followup.send(f"❌ Tournament with ID `{t_id_clean}` not found.")
                return
        else:
            t_cfg = get_active_tournament_config(interaction.guild.id)
            if not t_cfg:
                await interaction.followup.send("❌ No active tournament found on this server. Please specify a tournament ID.")
                return
                
        status_msg = await interaction.followup.send(f"⏳ [░░░░░░░░░░] 0% — Triggering manual room creation for tournament **{t_cfg['name']}**...")
        
        async def on_progress(percent: int, text: str):
            filled = percent // 10
            bar = "█" * filled + "░" * (10 - filled)
            try:
                await status_msg.edit(content=f"⏳ [{bar}] {percent}% — {text}")
            except Exception as e:
                print(f"Error updating progress message: {e}")
                
        created, error_msg = await auto_create_open_tickets_for_tournament(interaction.guild, t_cfg, on_progress=on_progress)
        
        if error_msg:
            try:
                await status_msg.edit(content=f"❌ Error during room creation: {error_msg}")
            except Exception:
                await interaction.followup.send(f"❌ Error during room creation: {error_msg}")
                
            try:
                log_embed = discord.Embed(
                    title="❌ Auto Room Run Failed",
                    description=f"Manual auto room run failed for tournament **{t_cfg['name']}**.\nReason: {error_msg}",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow()
                )
                log_embed.set_footer(text=f"Triggered by {interaction.user.name}")
                await log_bot_activity(interaction.guild, log_embed)
            except Exception as log_err:
                print(f"Failed to log auto room run failure: {log_err}")
        else:
            try:
                await status_msg.edit(content=f"✅ [██████████] 100% — Auto room creation complete! Created **{created}** new match room(s).")
            except Exception:
                await interaction.followup.send(f"✅ Auto room creation complete! Created **{created}** new match room(s).")
                
            try:
                log_embed = discord.Embed(
                    title="✅ Auto Room Run Complete",
                    description=f"Manual auto room run completed for tournament **{t_cfg['name']}**.\nCreated **{created}** new match room(s).",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()
                )
                log_embed.set_footer(text=f"Triggered by {interaction.user.name}")
                if interaction.guild.icon:
                    log_embed.set_thumbnail(url=interaction.guild.icon.url)
                await log_bot_activity(interaction.guild, log_embed)
            except Exception as log_err:
                print(f"Failed to log auto room run completion: {log_err}")
                
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            await interaction.followup.send(f"❌ An unexpected error occurred: {str(e)}")
        except Exception:
            pass

@auto_room_group.command(name="stop", description="Stop automatic room creation")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_stop(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
        return
        
    await interaction.response.defer()
    tournaments = load_guild_tournaments(interaction.guild.id)
    t_id_clean = None
    if tournament:
        t_id_clean = tournament.strip().replace(" ", "_")
        if t_id_clean not in tournaments:
            await interaction.followup.send(f"❌ Tournament with ID `{t_id_clean}` not found.")
            return
    else:
        t_cfg = get_active_tournament_config(interaction.guild.id)
        if not t_cfg:
            await interaction.followup.send("❌ No active tournament found on this server.")
            return
        t_id_clean = t_cfg['id']
        
    t_cfg = tournaments[t_id_clean]
    t_cfg['auto_room_creation'] = False
    tournaments[t_id_clean] = t_cfg
    save_guild_tournaments(interaction.guild.id, tournaments)
    stop_auto_room_loop(interaction.guild.id)
    
    await interaction.followup.send(f"⏹️ Stopped automatic room creation for tournament **{t_cfg['name']}**.")
    
    try:
        log_embed = discord.Embed(
            title="⏹️ Auto Room Loop Stopped",
            description=f"Automatic room creation loop stopped for tournament **{t_cfg['name']}**.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Action by {interaction.user.name}")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception as log_err:
        print(f"Failed to log auto room stop: {log_err}")

@auto_room_group.command(name="toggle", description="Toggle automatic room creation for a tournament")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_toggle(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
        return
        
    await interaction.response.defer()
    tournaments = load_guild_tournaments(interaction.guild.id)
    t_id_clean = None
    if tournament:
        t_id_clean = tournament.strip().replace(" ", "_")
        if t_id_clean not in tournaments:
            await interaction.followup.send(f"❌ Tournament with ID `{t_id_clean}` not found.")
            return
    else:
        t_cfg = get_active_tournament_config(interaction.guild.id)
        if not t_cfg:
            await interaction.followup.send("❌ No active tournament found on this server.")
            return
        t_id_clean = t_cfg['id']
        
    t_cfg = tournaments[t_id_clean]
    new_state = not t_cfg.get('auto_room_creation', True)
    t_cfg['auto_room_creation'] = new_state
    tournaments[t_id_clean] = t_cfg
    save_guild_tournaments(interaction.guild.id, tournaments)
    
    if new_state:
        start_auto_room_loop(interaction.guild.id)
    else:
        stop_auto_room_loop(interaction.guild.id)
    
    state_str = "Enabled" if new_state else "Disabled"
    await interaction.followup.send(f"🔄 Automatic room creation for tournament **{t_cfg['name']}** has been **{state_str}**.")
    
    try:
        log_embed = discord.Embed(
            title="🔄 Auto Room Config Toggled",
            description=f"Automatic room creation loop for tournament **{t_cfg['name']}** has been **{state_str}**.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Action by {interaction.user.name}")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception as log_err:
        print(f"Failed to log auto room toggle: {log_err}")


clear_group = app_commands.Group(name="clear", description="Clear cache or delete categories")

@clear_group.command(name="category", description="Deletes all channels in a specified category (Organizer only)")
@app_commands.describe(category="The category channel to delete all channels from")
@with_guild_context
async def clear_category(interaction: discord.Interaction, category: discord.CategoryChannel):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    channels_to_delete = list(category.channels)
    if not channels_to_delete:
        await interaction.followup.send(f"ℹ️ Category **{category.name}** has no channels to delete.")
        return
        
    deleted_count = 0
    failed_count = 0
    
    for ch in channels_to_delete:
        try:
            await ch.delete()
            deleted_count += 1
        except Exception as e:
            print(f"Error deleting channel {ch.name} in clear_category: {e}")
            failed_count += 1
            
    await interaction.followup.send(
        f"✅ Purge complete for category **{category.name}**.\n"
        f"🟢 **Deleted:** {deleted_count} channels.\n"
        f"🔴 **Failed:** {failed_count} channels."
    )
    
    try:
        log_embed = discord.Embed(
            title="🗑️ Category Purged",
            description=f"Category **{category.name}** has been purged.\n🟢 **Deleted:** {deleted_count} channels.\n🔴 **Failed:** {failed_count} channels.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Purged by {interaction.user.name}")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception as log_err:
        print(f"Failed to log category purge: {log_err}")

@clear_group.command(name="cache", description="Clear Challonge and sheet caches")
@with_guild_context
async def clear_cache(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to run this command.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    global GUILD_CONFIG_CACHE, RULES_CACHE, STAFF_STATS_CACHE, TOURNAMENTS_CACHE
    GUILD_CONFIG_CACHE.clear()
    RULES_CACHE.clear()
    STAFF_STATS_CACHE.clear()
    TOURNAMENTS_CACHE.clear()
    
    await interaction.followup.send("✅ Config, rules, and staff stats caches cleared successfully!")


ROUND_OPTIONS = [
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10",
    "Semi-Final", "Final", "Bronze Match"
]

def parse_round_input(val: str) -> Optional[str]:
    val_clean = val.strip().lower()
    
    # Check if integer
    if val_clean.isdigit():
        idx = int(val_clean)
        if 1 <= idx <= 10:
            return f"D{idx}"
        elif idx == 11:
            return "Semi-Final"
        elif idx == 12:
            return "Final"
        elif idx == 13:
            return "Bronze Match"
            
    # Check if exact/substring match
    for opt in ROUND_OPTIONS:
        if opt.lower() == val_clean:
            return opt
            
    # Substring match fallback
    for opt in ROUND_OPTIONS:
        if val_clean in opt.lower():
            return opt
            
    return None

@tree.command(name="deadline", description="Sets a deadline and schedules automatic reminders (Head Organizer only)")
@app_commands.describe(
    round="Type a number (1-13) or select/type the round (D1-D10, Semi-Final, Final, Bronze Match)",
    day="Day of the month for the deadline (1-31)",
    month="Month for the deadline (1-12)",
    year="Year for the deadline (e.g. 2026)",
    hour="Hour for the deadline (0-23, UTC) - Default is 12",
    minute="Minute for the deadline (0-59, UTC) - Default is 0"
)
@with_guild_context
async def deadline(
    interaction: discord.Interaction,
    round: str,
    day: int,
    month: int,
    year: int,
    hour: int = 12,
    minute: int = 0
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
        
    if not has_organizer_permission(interaction):
        await interaction.response.send_message("❌ You need **Head Organizer** role to manage deadlines.", ephemeral=True)
        return
        
    await interaction.response.defer(ephemeral=True)
    
    round_name = parse_round_input(round)
    if not round_name:
        await interaction.followup.send(
            "❌ Invalid round name. Please type a number (1-13) or choose/type one of:\n"
            "D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, Semi-Final, Final, Bronze Match.",
            ephemeral=True
        )
        return
        
    try:
        deadline_dt = datetime.datetime(year, month, day, hour, minute)
    except ValueError:
        await interaction.followup.send("❌ Invalid date/time values provided. Please enter a valid date.", ephemeral=True)
        return
        
    deadline_dt = deadline_dt.replace(tzinfo=pytz.UTC)
    now = datetime.datetime.now(pytz.UTC)
    
    if deadline_dt <= now:
        await interaction.followup.send("❌ The deadline date must be in the future.", ephemeral=True)
        return
        
    # Get deadline channel
    t_cfg = get_active_tournament_config(interaction.guild_id)
    channel_id = None
    if t_cfg:
        channel_id = t_cfg.get('deadline') or t_cfg.get('Deadline_Channel_ID')
    if not channel_id:
        cfg = get_guild_config(interaction.guild_id)
        channel_id = cfg.get('channel_ids', {}).get('deadlines')
        
    if not channel_id:
        await interaction.followup.send("❌ No deadline channel configured. Please configure it in your tournament/guild settings.", ephemeral=True)
        return
        
    deadline_channel = interaction.guild.get_channel(int(channel_id))
    if not deadline_channel:
        try:
            deadline_channel = await interaction.guild.fetch_channel(int(channel_id))
        except Exception:
            await interaction.followup.send("❌ Configured deadline channel not found or bot lacks permission to access it.", ephemeral=True)
            return
            
    # Save the scheduled deadline
    dl_id = f"dl_{round_name.lower().replace('-', '_').replace(' ', '_')}_{interaction.guild_id}"
    
    dl_data = {
        'guild_id': interaction.guild_id,
        'round': round_name,
        'deadline_dt': deadline_dt
    }
    
    # Save scheduled deadline (writes to Supabase and JSON backup)
    save_scheduled_deadline(dl_id, dl_data)
    
    # Schedule background tasks
    schedule_deadline_tasks(dl_id)
    
    deadline_date_str = deadline_dt.strftime("%d/%m/%Y")
    deadline_time_str = deadline_dt.strftime("%H:%M UTC")
    
    # Post initial announcement to the Deadline channel
    announce_embed = discord.Embed(
        title="📢 Round Deadline Set",
        description=f"A new deadline has been set for **Round {round_name}**.",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )
    announce_embed.add_field(name="Round", value=round_name, inline=True)
    announce_embed.add_field(name="Deadline Date & Time", value=f"{deadline_date_str} {deadline_time_str}", inline=True)
    announce_embed.add_field(
        name="Action Required", 
        value="Please ensure you open your ticket and schedule your match time before this deadline. Automatic reminders will be sent to unscheduled captains.",
        inline=False
    )
    announce_embed.set_footer(text=f"{interaction.guild.name} • Tournament Deadlines")
    
    try:
        await deadline_channel.send(embed=announce_embed)
    except Exception as e:
        print(f"Failed to send initial deadline announcement to channel: {e}")
        
    await interaction.followup.send(
        f"✅ Successfully scheduled deadline for **Round {round_name}** on **{deadline_date_str} {deadline_time_str}**.\n"
        f"Reminders will be posted in {deadline_channel.mention} at 06:00 UTC one day before and on the deadline day.",
        ephemeral=True
    )

@deadline.autocomplete('round')
async def deadline_round_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    current_clean = current.strip().lower()
    
    choices = []
    
    # If digit
    if current_clean.isdigit():
        try:
            idx = int(current_clean)
            if 1 <= idx <= 10:
                choices.append(app_commands.Choice(name=f"D{idx} (from number)", value=f"D{idx}"))
            elif idx == 11:
                choices.append(app_commands.Choice(name="Semi-Final (from number)", value="Semi-Final"))
            elif idx == 12:
                choices.append(app_commands.Choice(name="Final (from number)", value="Final"))
            elif idx == 13:
                choices.append(app_commands.Choice(name="Bronze Match (from number)", value="Bronze Match"))
        except ValueError:
            pass
            
    # Match strings
    for opt in ROUND_OPTIONS:
        if not current_clean or current_clean in opt.lower():
            choices.append(app_commands.Choice(name=opt, value=opt))
            
    return choices[:25]

bot.tree.add_command(tournament_group)
bot.tree.add_command(auto_room_group)
bot.tree.add_command(clear_group)


if __name__ == "__main__":
    # Get Discord token from environment
    token = os.environ.get("DISCORD_TOKEN")
    
    # Fallback method if direct get doesn't work
    if not token:
        for key, value in os.environ.items():
            if 'DISCORD' in key and 'TOKEN' in key:
                token = value
                break
    
    if not token:
        print("ERROR: Discord token not found in environment variables.")
        print("Please set your Discord bot token in the DISCORD_TOKEN environment variable.")
        print("You can also create a .env file with: DISCORD_TOKEN=your_token_here")
        exit(1)
    
    try:
        print("🚀 Starting Discord bot...")
        print("📡 Connecting to Discord...")
        bot.run(token, log_handler=None)  # Disable default logging to reduce startup time
    except discord.LoginFailure:
        print("ERROR: Invalid Discord token. Please check your bot token.")
        exit(1)
    except discord.HTTPException as e:
        print(f"ERROR: HTTP error connecting to Discord: {e}")
        exit(1)
    except Exception as e:
        print(f"ERROR: Error starting bot: {e}")
        exit(1)

