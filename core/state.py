import os
import json
import contextvars
import functools
from typing import Optional, Union, Any
import discord
from core.config import BASE_DIR, DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS, BOT_OWNER_ID

# ContextVar to hold current guild ID for async execution contexts
current_guild_id = contextvars.ContextVar("current_guild_id", default=None)

def with_guild_context(func):
    """Decorator to automatically extract guild ID and set current_guild_id ContextVar."""
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

# In-Memory Global Caches
GUILD_CONFIG_CACHE = {}
RULES_CACHE = {}
STAFF_STATS_CACHE = {}
CHALLONGE_MATCHES_CACHE = {}
TOURNAMENTS_CACHE = {}
sheetdb_tabs_cache = {}

# Active Tracking Dictionaries
scheduled_events = {}
scheduled_deadlines = {}
reminder_tasks = {}
cleanup_tasks = {}
judge_assignments = {}
deadline_tasks = {}
auto_room_loops = {}
auto_room_locks = {}
category_monitors = {}

def load_category_monitors():
    global category_monitors
    path = os.path.join(BASE_DIR, "category_monitors.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                category_monitors.clear()
                category_monitors.update(json.load(f))
        except Exception:
            pass
    return category_monitors

def save_category_monitors():
    path = os.path.join(BASE_DIR, "category_monitors.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(category_monitors, f, indent=2)
    except Exception as e:
        print(f"Error saving category monitors: {e}")

load_category_monitors()



def get_default_config() -> dict:
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

def get_default_tournament_data() -> dict:
    return {
        'name': "",
        'state': "pending",
        'game': "",
        'key': "",
        'challonge_bracket_link': "",
        'captains_sheet_link': "",
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
        'closed_ticket_1': None,
        'closed_ticket_2': None,
        'ticket_open_category_1': None,
        'ticket_open_category_2': None,
        'ticket_open_category_3': None,
        'auto_room_creation': False
    }

# Dynamic String Wrapper for backward compatibility
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

# Guild Dictionary Proxy for dynamic per-guild fallback resolution
class GuildDictProxy(dict):
    def __init__(self, default_dict, config_key):
        super().__init__(default_dict)
        self.default_dict = default_dict
        self.config_key = config_key

    def _get_current_dict(self):
        from core.database import get_guild_config, get_active_tournament_config
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

class GuildStatsProxy(dict):
    def _get_current_dict(self):
        from core.database import get_guild_staff_stats
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
        from core.database import get_guild_staff_stats, save_guild_staff_stats
        g_id = current_guild_id.get()
        if g_id:
            stats = get_guild_staff_stats(g_id)
            stats[key] = value
            save_guild_staff_stats(g_id, stats)

    def __delitem__(self, key):
        from core.database import get_guild_staff_stats, save_guild_staff_stats
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
        from core.database import get_guild_rules
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
        from core.database import get_guild_rules, save_guild_rules
        g_id = current_guild_id.get()
        if g_id:
            rules = get_guild_rules(g_id)
            rules[key] = value
            save_guild_rules(g_id, rules)

    def __delitem__(self, key):
        from core.database import get_guild_rules, save_guild_rules
        g_id = current_guild_id.get()
        if g_id:
            rules = get_guild_rules(g_id)
            if key in rules:
                del rules[key]
                save_guild_rules(g_id, rules)

    def __bool__(self):
        return bool(self._get_current_dict())

staff_stats = GuildStatsProxy()
tournament_rules = GuildRulesProxy()

# Helper getters
def get_org_name(context=None) -> str:
    from core.database import get_guild_config
    return get_guild_config(context).get("organization_name", "Tournament Organizer")

def get_system_name(context=None) -> str:
    from core.database import get_guild_config
    return get_guild_config(context).get("tournament_system_name", "Tournament System")

def get_bracket_link(context=None) -> str:
    from core.database import get_active_tournament_config
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
    from core.database import get_active_tournament_config
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
    from core.database import get_guild_config
    return get_guild_config(context).get("google_sheet_link", "")

def get_tournament_name(context=None) -> str:
    from core.database import get_guild_config, get_active_tournament_config
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
    from core.database import get_guild_config
    return get_guild_config(context).get("player_info_link", "")

def get_player_info_format(context=None) -> str:
    from core.database import get_guild_config
    return get_guild_config(context).get("player_info_format", "5 vs 5")

def get_sheetdb_api_url(context=None) -> str:
    from core.database import get_guild_config
    url = get_guild_config(context).get("sheetdb_api_url", "")
    return url if url else os.getenv("SHEETDB_API_URL", "")

def get_link_bracket(context=None) -> str:
    from core.database import get_guild_config, get_active_tournament_config
    g_id = None
    if context:
        if isinstance(context, int):
            g_id = context
        elif hasattr(context, "guild") and context.guild:
            g_id = context.guild.id
        elif isinstance(context, discord.Guild):
            g_id = context.id
    if not g_id:
        g_id = current_guild_id.get()

    if g_id:
        t_cfg = get_active_tournament_config(g_id)
        if t_cfg and t_cfg.get('challonge_bracket_link'):
            b_link = str(t_cfg['challonge_bracket_link']).strip()
            return b_link if b_link.startswith("http") else f"https://challonge.com/{b_link}"
        if t_cfg and t_cfg.get('bracket'):
            return f"https://discord.com/channels/{g_id}/{t_cfg['bracket']}"
            
        cfg = get_guild_config(g_id)
        b_chan = cfg.get('channel_ids', {}).get('bracket')
        if b_chan:
            return f"https://discord.com/channels/{g_id}/{b_chan}"
    return "https://challonge.com"

def get_link_deadline(context=None) -> str:
    from core.database import get_guild_config, get_active_tournament_config
    g_id = None
    if context:
        if isinstance(context, int):
            g_id = context
        elif hasattr(context, "guild") and context.guild:
            g_id = context.guild.id
        elif isinstance(context, discord.Guild):
            g_id = context.id
    if not g_id:
        g_id = current_guild_id.get()

    if g_id:
        t_cfg = get_active_tournament_config(g_id)
        if t_cfg and t_cfg.get('deadline'):
            return f"https://discord.com/channels/{g_id}/{t_cfg['deadline']}"
            
        cfg = get_guild_config(g_id)
        d_chan = cfg.get('channel_ids', {}).get('deadlines') or cfg.get('channel_ids', {}).get('deadline')
        if d_chan:
            return f"https://discord.com/channels/{g_id}/{d_chan}"
    return "https://discord.com"

def get_link_rules(context=None) -> str:
    from core.database import get_guild_config, get_active_tournament_config
    g_id = None
    if context:
        if isinstance(context, int):
            g_id = context
        elif hasattr(context, "guild") and context.guild:
            g_id = context.guild.id
        elif isinstance(context, discord.Guild):
            g_id = context.id
    if not g_id:
        g_id = current_guild_id.get()

    if g_id:
        t_cfg = get_active_tournament_config(g_id)
        if t_cfg and t_cfg.get('rules'):
            return f"https://discord.com/channels/{g_id}/{t_cfg['rules']}"
            
        cfg = get_guild_config(g_id)
        r_chan = cfg.get('channel_ids', {}).get('rules')
        if r_chan:
            return f"https://discord.com/channels/{g_id}/{r_chan}"
    return "https://discord.com"


ORGANIZATION_NAME = DynamicString(lambda: get_org_name())
TOURNAMENT_SYSTEM_NAME = DynamicString(lambda: get_system_name())
BRACKET_LINK = DynamicString(lambda: get_bracket_link())
BRACKET_API_KEY = DynamicString(lambda: get_bracket_api_key())
GOOGLE_SHEET_LINK = DynamicString(lambda: get_google_sheet_link())
CURRENT_TOURNAMENT_NAME = DynamicString(lambda: get_tournament_name())
PLAYER_INFO_LINK = DynamicString(lambda: get_player_info_link())
PLAYER_INFO_FORMAT = DynamicString(lambda: get_player_info_format())
SHEETDB_API_URL = DynamicString(lambda: get_sheetdb_api_url())

# Permission and Role Utilities
def get_user_permission_level(user_roles, user_id: int = None, guild_id: int = None) -> str:
    """Determine user's permission level based on their Discord roles and guild configuration"""
    from core.database import get_guild_config
    try:
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
        elif has_role("helper_team"):
            return "helper"
        elif has_role("judge"):
            return "judge"
        elif has_role("recorder"):
            return "recorder"
        else:
            return "user"
    except Exception as e:
        print(f"Error determining user permission level: {e}")
        return "user"

def has_organizer_permission(interaction: discord.Interaction) -> bool:
    """Check if user has organizer permissions for rule management"""
    from core.database import get_guild_config
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

def is_authorized_to_configure(interaction: discord.Interaction) -> bool:
    """Check if the user is authorized to configure tournament / bot settings."""
    from core.database import get_guild_config
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
        try:
            if int(head_org_id) in member_role_ids or str(head_org_id) in [str(r) for r in member_role_ids]:
                return True
        except (ValueError, TypeError):
            if str(head_org_id) in [str(r) for r in member_role_ids]:
                return True
            
    return False

def is_staff(member: Union[discord.Member, discord.User], guild: Optional[discord.Guild] = None) -> bool:
    """Check if a member has any staff role or administrative privileges."""
    from core.database import get_guild_config
    if not member:
        return False
    if member.id == BOT_OWNER_ID:
        return True
    if isinstance(member, discord.Member):
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        if not guild:
            guild = member.guild
    if not guild:
        return False
        
    cfg = get_guild_config(guild.id)
    role_ids = cfg.get("role_ids", DEFAULT_ROLE_IDS)
    
    staff_keys = ["head_organizer", "organizer", "helper_team", "judge", "recorder", "staff"]
    member_role_ids = [r.id for r in member.roles] if isinstance(member, discord.Member) else []
    
    for key in staff_keys:
        val = role_ids.get(key)
        if val is not None:
            try:
                if int(val) in member_role_ids:
                    return True
            except (ValueError, TypeError):
                if str(val) in [str(r) for r in member_role_ids]:
                    return True
    return False

def has_event_create_permission(interaction: discord.Interaction) -> bool:
    """Check if user has permission to create events (Head Organizer, Head Helper or Helper Team)"""
    from core.database import get_guild_config
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
    helper_team_id = safe_get("helper_team")
    
    user_role_ids = [r.id for r in interaction.user.roles] if hasattr(interaction.user, "roles") else []
    
    return (
        (head_organizer_id and head_organizer_id in user_role_ids) or
        (helper_team_id and helper_team_id in user_role_ids)
    )

def has_event_result_permission(interaction: discord.Interaction) -> bool:
    from core.database import get_guild_config
    if interaction.user.id == BOT_OWNER_ID:
        return True
    if interaction.guild and (
        interaction.user.guild_permissions.administrator or
        interaction.user.guild_permissions.manage_guild or
        interaction.user.guild_permissions.manage_events
    ):
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
    helper_team_id = safe_get("helper_team")
    judge_id = safe_get("judge")
    recorder_id = safe_get("recorder")
    staff_id = safe_get("staff")
    
    user_role_ids = [r.id for r in interaction.user.roles] if hasattr(interaction.user, "roles") else []
    role_names = [r.name.lower() for r in interaction.user.roles] if hasattr(interaction.user, "roles") else []
    name_match = any(
        target in r_name
        for r_name in role_names
        for target in ["head organizer", "organizer", "judge", "recorder", "helper", "staff"]
    )
    
    return (
        (head_organizer_id and head_organizer_id in user_role_ids) or
        (helper_team_id and helper_team_id in user_role_ids) or
        (judge_id and judge_id in user_role_ids) or
        (recorder_id and recorder_id in user_role_ids) or
        (staff_id and staff_id in user_role_ids) or
        name_match
    )

# Embed Helpers

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
    """Safely remove a field by name using Discord.py methods."""
    try:
        field_index = find_field_index(embed, field_name)
        if field_index != -1:
            embed.remove_field(field_index)
            return True
        return False
    except Exception as e:
        print(f"Error removing field by name '{field_name}': {e}")
        return False

def update_judge_field(embed: discord.Embed, judge_member: discord.Member, existing_recorder: Optional[discord.Member] = None) -> bool:
    """Update or add judge field safely."""
    try:
        has_recorder_field = any(field.name == "🎥 Recorder" for field in embed.fields)
        recorder_value = None
        
        if has_recorder_field:
            for field in embed.fields:
                if field.name == "🎥 Recorder":
                    recorder_value = field.value
                    break
        
        remove_field_by_name(embed, "👨‍⚖️ Judge")
        embed.add_field(
            name="👨‍⚖️ Judge", 
            value=f"{judge_member.mention}", 
            inline=True
        )
        
        if not has_recorder_field:
            if existing_recorder:
                embed.add_field(name="🎥 Recorder", value=f"{existing_recorder.mention}", inline=True)
            else:
                embed.add_field(name="🎥 Recorder", value="⏳ Waiting...", inline=True)
        elif recorder_value and "Waiting" not in recorder_value:
            remove_field_by_name(embed, "🎥 Recorder")
            embed.add_field(name="🎥 Recorder", value=recorder_value, inline=True)
        
        return True
    except Exception as e:
        print(f"Error updating judge field: {e}")
        return False

def remove_judge_field(embed: discord.Embed) -> bool:
    """Remove judge field safely."""
    try:
        return remove_field_by_name(embed, "👨‍⚖️ Judge")
    except Exception as e:
        print(f"Error removing judge field: {e}")
        return False

def add_green_circle_to_title(title: str) -> str:
    green_circle = "🟢"
    if title and title.startswith(green_circle):
        return title
    return green_circle + (title or "")

def update_embed_title_with_green_circle(embed: discord.Embed) -> bool:
    try:
        if embed.title:
            embed.title = add_green_circle_to_title(embed.title)
            return True
        return False
    except Exception as e:
        print(f"Error updating embed title with green circle: {e}")
        return False

def replace_green_circle_with_checkmark(title: str) -> str:
    green_circle = "🟢"
    checkmark = "✅"
    if title and title.startswith(green_circle):
        return checkmark + title[len(green_circle):]
    return checkmark + (title or "")

def update_embed_title_with_checkmark(embed: discord.Embed) -> bool:
    try:
        if embed.title:
            embed.title = replace_green_circle_with_checkmark(embed.title)
            return True
        return False
    except Exception as e:
        print(f"Error updating embed title with checkmark: {e}")
        return False

def load_scheduled_events() -> dict:
    """Load scheduled events from local JSON storage into the shared dictionary, pruning finished events to save memory."""
    global scheduled_events
    path = os.path.join(BASE_DIR, 'scheduled_events.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                import datetime
                active_events = {}
                for event_id, event_data in data.items():
                    if not isinstance(event_data, dict):
                        continue
                    if str(event_data.get('status', '')).lower() == 'completed':
                        continue
                    if 'datetime' in event_data and isinstance(event_data['datetime'], str):
                        try:
                            event_data['datetime'] = datetime.datetime.fromisoformat(event_data['datetime'])
                        except Exception:
                            pass
                    active_events[event_id] = event_data
                scheduled_events.clear()
                scheduled_events.update(active_events)
                print(f"Loaded {len(scheduled_events)} active scheduled events from local fallback")
        except Exception as e:
            print(f"Error loading scheduled_events.json: {e}")
    return scheduled_events

def save_scheduled_events():
    """Save scheduled events to local JSON and trigger background Supabase synchronization."""
    import json
    import os
    import datetime
    import asyncio
    from core.config import BASE_DIR
    try:
        data_to_save = {}
        for event_id, event_data in scheduled_events.items():
            event_copy = event_data.copy()
            if 'datetime' in event_copy and isinstance(event_copy['datetime'], datetime.datetime):
                event_copy['datetime'] = event_copy['datetime'].isoformat()
            if 'team1_captain' in event_copy and hasattr(event_copy['team1_captain'], 'id'):
                event_copy['team1_captain'] = event_copy['team1_captain'].id
            if 'team2_captain' in event_copy and hasattr(event_copy['team2_captain'], 'id'):
                event_copy['team2_captain'] = event_copy['team2_captain'].id
            if 'judge' in event_copy and hasattr(event_copy['judge'], 'id'):
                event_copy['judge'] = event_copy['judge'].id
            if 'recorder' in event_copy and hasattr(event_copy['recorder'], 'id'):
                event_copy['recorder'] = event_copy['recorder'].id
            data_to_save[event_id] = event_copy
        path = os.path.join(BASE_DIR, 'scheduled_events.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)

        # Trigger Supabase background save if loop is running
        try:
            from core.database import save_event_to_supabase, supabase_client
            if supabase_client:
                loop = asyncio.get_running_loop()
                async def _bg_save_all():
                    for ev_id, ev_data in list(scheduled_events.items()):
                        try:
                            await save_event_to_supabase(ev_id, ev_data)
                        except Exception:
                            pass
                loop.create_task(_bg_save_all())
        except Exception:
            pass
    except Exception as e:
        print(f"Error saving scheduled events: {e}")

def save_staff_stats():
    from core.database import save_guild_staff_stats, get_guild_staff_stats
    g_id = current_guild_id.get()
    if g_id:
        stats = get_guild_staff_stats(g_id)
        save_guild_staff_stats(g_id, stats)

def reset_staff_stats(guild_id: int):
    from core.database import save_guild_staff_stats
    save_guild_staff_stats(guild_id, {})

def get_current_rules(guild_id: int = None) -> str:
    from core.database import get_guild_rules
    g_id = guild_id or current_guild_id.get()
    if g_id:
        return get_guild_rules(g_id).get('content', '')
    return ""

def set_rules_content(guild_id: int, content: str):
    from core.database import get_guild_rules, save_guild_rules
    g_id = guild_id or current_guild_id.get()
    if g_id:
        rules = get_guild_rules(g_id)
        rules['content'] = content
        save_guild_rules(g_id, rules)


