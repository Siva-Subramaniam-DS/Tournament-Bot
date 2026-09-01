import os
import io
import re
import json
import asyncio
import datetime
from typing import Optional, List, Union

import discord
from discord import app_commands
from discord.ext import commands
import pytz
from PIL import Image

from core.config import (
    BASE_DIR, BRAND_COLOR, BOT_OWNER_ID, ORGANIZATION_NAME,
    DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS
)
from core.state import (
    current_guild_id, with_guild_context, is_authorized_to_configure,
    is_staff, has_organizer_permission, has_event_create_permission,
    get_user_permission_level, get_org_name, get_tournament_name,
    get_system_name, get_bracket_link, get_bracket_api_key,
    get_link_bracket, get_link_deadline, get_link_rules,
    ROLE_IDS, CHANNEL_IDS, scheduled_events, save_scheduled_events,
    scheduled_deadlines, reminder_tasks, deadline_tasks,
    auto_room_loops, auto_room_locks, get_default_tournament_data
)
from core.database import (
    supabase_client, load_guild_tournaments, save_guild_tournaments,
    get_guild_config, get_active_tournament_config,
    save_event_to_supabase, log_bot_activity, sheetdb_post,
    update_challonge_match, get_challonge_matches, get_challonge_participants,
    get_guild_staff_stats, save_guild_staff_stats, update_staff_stats,
    update_results_embed_with_links, save_scheduled_deadline, delete_scheduled_deadline,
    fetch_challonge_open_matches, fetch_google_sheet_captains
)




from core.image_generator import get_random_template, get_thumbnail_url_from_channel
from core.transcript import generate_html_transcript, generate_text_transcript


# ===========================================================================================
# AUTOCOMPLETE HELPERS
# ===========================================================================================

async def tournament_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    try:
        tournaments = load_guild_tournaments(interaction.guild_id)
        choices = []
        for t_id, t_cfg in tournaments.items():
            name = t_cfg.get("name", t_id)
            state = t_cfg.get("state", "pending")
            display = f"{name} ({t_id}) [{state}]"
            if not current or current.lower() in display.lower():
                choices.append(app_commands.Choice(name=display[:100], value=t_id))
        return choices[:25]
    except Exception as e:
        print(f"Error in tournament_autocomplete: {e}")
        return []

async def game_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    games = ["Modern Warship", "BGMI", "Free Fire", "Valorant", "PUBG Mobile", "Call of Duty Mobile", "Pokemon UNITE", "Clash Royale"]
    choices = []
    for g in games:
        if not current or current.lower() in g.lower():
            choices.append(app_commands.Choice(name=g, value=g))
    return choices[:25]

async def match_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    try:
        guild_id = interaction.guild_id
        selected_tournament = getattr(interaction.namespace, "tournament", None)
        choices = []
        current_lower = current.lower()
        
        for ev_id, ev_data in scheduled_events.items():
            if str(ev_data.get('guild_id')) != str(guild_id):
                continue
            
            if selected_tournament:
                ev_t = ev_data.get('tournament')
                t_cfg = load_guild_tournaments(guild_id).get(selected_tournament)
                t_name = t_cfg.get('name') if t_cfg else None
                if ev_t and selected_tournament.lower() not in ev_t.lower() and (not t_name or t_name.lower() not in ev_t.lower()):
                    continue
            
            t1_val = ev_data.get('team1_name')
            if not t1_val:
                t1_cap = ev_data.get('team1_captain')
                t1_val = getattr(t1_cap, 'name', str(t1_cap))
            t2_val = ev_data.get('team2_name')
            if not t2_val:
                t2_cap = ev_data.get('team2_captain')
                t2_val = getattr(t2_cap, 'name', str(t2_cap))
                
            rnd = ev_data.get('round', '')
            choice_name = f"[{ev_id}] {t1_val} vs {t2_val} ({rnd})"
            if len(choice_name) > 100:
                choice_name = choice_name[:97] + "..."
                
            if not current or current_lower in choice_name.lower():
                choices.append(app_commands.Choice(name=choice_name, value=ev_id))
                
        return choices[:25]
    except Exception as e:
        print(f"Error in match_autocomplete: {e}")
        return []

def find_event_by_name_or_id(guild_id: int, match_query: str) -> tuple[Optional[str], Optional[dict]]:
    query = match_query.strip().lower()
    if query in scheduled_events and str(scheduled_events[query].get('guild_id')) == str(guild_id):
        return query, scheduled_events[query]

    for ev_id, ev_data in scheduled_events.items():
        if str(ev_data.get('guild_id')) != str(guild_id):
            continue
        m_name = (ev_data.get('match_name') or "").lower()
        t1 = (ev_data.get('team1_name') or "").lower()
        t2 = (ev_data.get('team2_name') or "").lower()
        if query == m_name or query in m_name or (query in t1 or query in t2):
            return ev_id, ev_data

    return None, None

def mask_api_key(key: str) -> str:
    if not key:
        return "Not Set"
    if len(key) <= 4:
        return "****"
    return "*" * (len(key) - 4) + key[-4:]


# ===========================================================================================
# EMBED BUILDERS
# ===========================================================================================

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

    def chan_mention(key):
        val = t_data.get(key) or t_data.get(f"{key}_channel") or t_data.get(f"{key}_channel_id")
        cid = safe_int(val)
        if not cid:
            return "Not Set"
        ch = guild.get_channel(cid) if guild else None
        return ch.mention if ch else f"`ID: {cid}`"
        
    def cat_mention(key):
        val = t_data.get(key) or t_data.get(f"{key}_category") or t_data.get(f"{key}_category_id")
        cid = safe_int(val)
        if not cid:
            return "Not Set"
        ch = guild.get_channel(cid) if guild else None
        return f"# {ch.name}" if ch else f"`ID: {cid}`"

    sheet_link = t_data.get('google_sheet_link') or t_data.get('captains_sheet_link', '')
    sheet_str = f"[Click Here]({sheet_link})" if sheet_link else "Not Set"

    bracket_val = t_data.get('challonge_bracket_link', '')
    bracket_str = f"[Click Here]({bracket_val})" if bracket_val.startswith("http") else (f"`{bracket_val}`" if bracket_val else "Not Set")

    key_val = t_data.get('key', '')
    game_val = t_data.get('game') or 'Not Set'
    embed.add_field(name="🏆 Tournament ID", value=f"`{t_data['id']}`", inline=True)
    embed.add_field(name="📊 Tournament State", value=f"`{t_data['state']}`", inline=True)
    embed.add_field(name="🎮 Game", value=f"`{game_val}`", inline=True)
    key_str = f"`{mask_api_key(key_val)}`"

    thumb_chan_id = safe_int(t_data.get('thumbnail'))
    thumb_url = await get_thumbnail_url_from_channel(thumb_chan_id)
    
    file = None
    if thumb_url and thumb_url.startswith("http") and "discord.com/channels/" not in thumb_url:
        embed.set_thumbnail(url=thumb_url)
        thumb_str = f"[Image Link]({thumb_url}) (from {chan_mention('thumbnail')})"
    else:
        game_hint = t_data.get('game') or t_data.get('name') or t_data.get('mode') or t_data.get('id')
        template_path = get_random_template(game_or_mode=game_hint)
        if template_path and os.path.exists(template_path):
            try:
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
                print(f"Error processing template {template_path}: {e}")
                thumb_str = f"Default (Channel: {chan_mention('thumbnail')})"
        else:
            thumb_str = f"Default (Channel: {chan_mention('thumbnail')})"

    embed.add_field(name="🔑 Challonge API Key", value=key_str, inline=True)
    embed.add_field(name="🗒️ Transcript Channel", value=chan_mention('transcript'), inline=True)
    embed.add_field(name="📁 Closed Category 1", value=cat_mention('closed_ticket_1'), inline=True)

    embed.add_field(name="📁 Closed Category 2", value=cat_mention('closed_ticket_2'), inline=True)
    embed.add_field(name="📌 Rules Channel", value=chan_mention('rules'), inline=True)
    embed.add_field(name="📅 Deadline Channel", value=chan_mention('deadline'), inline=True)

    embed.add_field(name="🏅 Result Channel", value=chan_mention('result'), inline=True)
    embed.add_field(name="🎮 Challonge Bracket", value=bracket_str, inline=True)
    embed.add_field(name="📊 Attendance Channel", value=chan_mention('attendance'), inline=True)

    embed.add_field(name="📝 Challonge Logs", value=chan_mention('challonge_logs'), inline=True)
    embed.add_field(name="📋 Schedule Channel", value=chan_mention('schedule'), inline=True)
    embed.add_field(name="🤖 Bot Logs Channel", value=chan_mention('bot_logs'), inline=True)

    embed.add_field(name="📄 Google Sheet", value=sheet_str, inline=True)
    embed.add_field(name="🖼️ Thumbnail", value=thumb_str, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    open_cats = []
    for i in range(1, 4):
        cat_id = t_data.get(f'ticket_open_category_{i}')
        cat = guild.get_channel(safe_int(cat_id)) if (guild and cat_id) else None
        if cat:
            open_cats.append(f"▪️ Category {i}: # 🏆 {cat.name} 🏆")
    if open_cats:
        embed.add_field(name="📂 Open Ticket Categories", value="\n".join(open_cats), inline=False)

    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    return embed, file


# ===========================================================================================
# TOURNAMENT COMMAND GROUP
# ===========================================================================================

tournament_group = app_commands.Group(name="tournament", description="Manage multi-tournament settings and configurations")

@tournament_group.command(name="add", description="Register a new tournament configuration")
@app_commands.describe(
    tournament_id="Unique identifier for the tournament (e.g. t1, apex2024)",
    name="Full name of the tournament",
    game="Game for this tournament (e.g. Modern Warship, BGMI, Valorant)",
    challonge_key="Challonge API Key or Bracket Identifier",
    bracket_link="Challonge or tournament bracket URL",
    sheet_link="Google Sheet link for player roster / team info",
    attendance_channel="Channel for staff check-ins",
    transcript_channel="Channel for ticket transcripts",
    schedule_channel="Channel for posting match schedules",
    rules_channel="Channel for tournament rules",
    result_channel="Channel for official match results",
    deadline_channel="Channel for round deadlines",
    bot_logs="Channel for bot activity logs",
    challonge_logs="Channel for Challonge bracket logs",
    closed_category="Category where closed tickets are stored",
    open_category_1="1st category for ticket opening (open tickets)",
    open_category_2="2nd category for ticket opening (open tickets)",
    open_category_3="3rd category for ticket opening (open tickets)",
    auto_room="Toggle automatic room creation for this tournament"
)
@app_commands.autocomplete(game=game_autocomplete)
@with_guild_context
async def tournament_add(
    interaction: discord.Interaction,
    tournament_id: str,
    name: str,
    game: Optional[str] = None,
    challonge_key: Optional[str] = None,
    bracket_link: Optional[str] = None,
    sheet_link: Optional[str] = None,
    attendance_channel: Optional[discord.TextChannel] = None,
    transcript_channel: Optional[discord.TextChannel] = None,
    schedule_channel: Optional[discord.TextChannel] = None,
    rules_channel: Optional[discord.TextChannel] = None,
    result_channel: Optional[discord.TextChannel] = None,
    deadline_channel: Optional[discord.TextChannel] = None,
    bot_logs: Optional[discord.TextChannel] = None,
    challonge_logs: Optional[discord.TextChannel] = None,
    closed_category: Optional[discord.CategoryChannel] = None,
    open_category_1: Optional[discord.CategoryChannel] = None,
    open_category_2: Optional[discord.CategoryChannel] = None,
    open_category_3: Optional[discord.CategoryChannel] = None,
    auto_room: Optional[bool] = False
):
    if not interaction.guild_id:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    tournaments = load_guild_tournaments(interaction.guild_id)
    t_id_clean = tournament_id.strip().lower()

    if t_id_clean in tournaments:
        await interaction.response.send_message(f"⚠️ A tournament with ID `{t_id_clean}` already exists. Use `/tournament edit` to modify it.", ephemeral=True)
        return

    t_data = get_default_tournament_data()
    t_data["id"] = t_id_clean
    t_data["name"] = name.strip()
    t_data["state"] = "pending"
    if game:                t_data["game"] = game.strip()
    if challonge_key:       t_data["key"] = challonge_key.strip()
    if bracket_link:        t_data["challonge_bracket_link"] = bracket_link.strip()
    if sheet_link:          t_data["google_sheet_link"] = sheet_link.strip()
    if attendance_channel:  t_data["attendance"] = attendance_channel.id
    if transcript_channel:  t_data["transcript"] = transcript_channel.id
    if schedule_channel:    t_data["schedule"] = schedule_channel.id
    if rules_channel:       t_data["rules"] = rules_channel.id
    if result_channel:      t_data["result"] = result_channel.id
    if deadline_channel:    t_data["deadline"] = deadline_channel.id
    if bot_logs:            t_data["bot_logs"] = bot_logs.id
    if challonge_logs:      t_data["challonge_logs"] = challonge_logs.id
    if closed_category:     t_data["closed_ticket_1"] = closed_category.id
    if open_category_1:     t_data["ticket_open_category_1"] = open_category_1.id
    if open_category_2:     t_data["ticket_open_category_2"] = open_category_2.id
    if open_category_3:     t_data["ticket_open_category_3"] = open_category_3.id
    if auto_room is not None: t_data["auto_room_creation"] = auto_room

    tournaments[t_id_clean] = t_data
    save_guild_tournaments(interaction.guild_id, tournaments)

    embed, file = await build_tournament_embed(interaction, t_data, "Tournament Registered")
    if file:
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=False)


@tournament_group.command(name="edit", description="Modify an existing tournament configuration")
@app_commands.describe(
    tournament="Select the tournament to edit",
    name="Updated name for the tournament",
    state="Tournament state (pending, active, completed)",
    game="Updated game for template posters (e.g. Modern Warship, BGMI, Valorant)",
    challonge_key="Challonge API Key or Identifier",
    bracket_link="Challonge bracket URL",
    sheet_link="Google Sheet link for player roster",
    attendance_channel="Attendance channel",
    transcript_channel="Transcript channel",
    schedule_channel="Schedule channel",
    rules_channel="Rules channel",
    result_channel="Result channel",
    deadline_channel="Deadline channel",
    bot_logs="Bot activity logs channel",
    challonge_logs="Challonge logs channel",
    closed_category="Closed ticket category",
    open_category_1="1st category for ticket opening (open tickets)",
    open_category_2="2nd category for ticket opening (open tickets)",
    open_category_3="3rd category for ticket opening (open tickets)",
    auto_room="Toggle automatic room creation"
)
@app_commands.autocomplete(tournament=tournament_autocomplete, game=game_autocomplete)
@app_commands.choices(
    state=[
        app_commands.Choice(name="pending",   value="pending"),
        app_commands.Choice(name="active",    value="active"),
        app_commands.Choice(name="completed", value="completed")
    ]
)
@with_guild_context
async def tournament_edit(
    interaction: discord.Interaction,
    tournament: str,
    name: Optional[str] = None,
    state: Optional[str] = None,
    game: Optional[str] = None,
    challonge_key: Optional[str] = None,
    bracket_link: Optional[str] = None,
    sheet_link: Optional[str] = None,
    attendance_channel: Optional[discord.TextChannel] = None,
    transcript_channel: Optional[discord.TextChannel] = None,
    schedule_channel: Optional[discord.TextChannel] = None,
    rules_channel: Optional[discord.TextChannel] = None,
    result_channel: Optional[discord.TextChannel] = None,
    deadline_channel: Optional[discord.TextChannel] = None,
    bot_logs: Optional[discord.TextChannel] = None,
    challonge_logs: Optional[discord.TextChannel] = None,
    closed_category: Optional[discord.CategoryChannel] = None,
    open_category_1: Optional[discord.CategoryChannel] = None,
    open_category_2: Optional[discord.CategoryChannel] = None,
    open_category_3: Optional[discord.CategoryChannel] = None,
    auto_room: Optional[bool] = None
):
    if not interaction.guild_id:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    tournaments = load_guild_tournaments(interaction.guild_id)
    t_id_clean = tournament.strip().lower()

    if t_id_clean not in tournaments:
        await interaction.response.send_message(f"❌ Tournament `{t_id_clean}` not found.", ephemeral=True)
        return

    t_data = tournaments[t_id_clean]
    if name:               t_data["name"] = name.strip()
    if state:              t_data["state"] = state
    if game:               t_data["game"] = game.strip()
    if challonge_key:      t_data["key"] = challonge_key.strip()
    if bracket_link:       t_data["challonge_bracket_link"] = bracket_link.strip()
    if sheet_link:         t_data["google_sheet_link"] = sheet_link.strip()
    if attendance_channel: t_data["attendance"] = attendance_channel.id
    if transcript_channel: t_data["transcript"] = transcript_channel.id
    if schedule_channel:   t_data["schedule"] = schedule_channel.id
    if rules_channel:      t_data["rules"] = rules_channel.id
    if result_channel:     t_data["result"] = result_channel.id
    if deadline_channel:   t_data["deadline"] = deadline_channel.id
    if bot_logs:           t_data["bot_logs"] = bot_logs.id
    if challonge_logs:     t_data["challonge_logs"] = challonge_logs.id
    if closed_category:    t_data["closed_ticket_1"] = closed_category.id
    if open_category_1:    t_data["ticket_open_category_1"] = open_category_1.id
    if open_category_2:    t_data["ticket_open_category_2"] = open_category_2.id
    if open_category_3:    t_data["ticket_open_category_3"] = open_category_3.id
    if auto_room is not None: t_data["auto_room_creation"] = auto_room

    save_guild_tournaments(interaction.guild_id, tournaments)

    embed, file = await build_tournament_embed(interaction, t_data, "Tournament Updated")
    if file:
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=False)


@tournament_group.command(name="delete", description="Delete a tournament configuration and all associated matches and schedules")
@app_commands.describe(tournament="Select tournament to delete")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def tournament_delete(interaction: discord.Interaction, tournament: str):
    if not interaction.guild_id:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    tournaments = load_guild_tournaments(interaction.guild_id)
    t_id_clean = tournament.strip().lower()

    if t_id_clean not in tournaments:
        await interaction.followup.send(f"❌ Tournament `{t_id_clean}` not found.", ephemeral=True)
        return

    t_name = str(tournaments[t_id_clean].get('name', '')).lower()
    del tournaments[t_id_clean]
    save_guild_tournaments(interaction.guild_id, tournaments)

    removed_events = 0
    removed_event_ids = []
    for ev_id, ev_data in list(scheduled_events.items()):
        ev_t_id = str(ev_data.get('tournament_id', '') or '').lower()
        ev_t_name = str(ev_data.get('tournament', '') or '').lower()
        if ev_t_id == t_id_clean or ev_t_name == t_id_clean or (t_name and ev_t_name == t_name):
            if ev_id in reminder_tasks:
                try:
                    reminder_tasks[ev_id].cancel()
                    del reminder_tasks[ev_id]
                except Exception:
                    pass
            removed_event_ids.append(ev_id)
            del scheduled_events[ev_id]
            removed_events += 1
    if removed_events > 0:
        save_scheduled_events()

    for dl_id, dl_data in list(scheduled_deadlines.items()):
        dl_t = str(dl_data.get('tournament_id', '') or dl_data.get('tournament', '') or '').lower()
        if dl_t == t_id_clean or (t_name and dl_t == t_name):
            del scheduled_deadlines[dl_id]

    if supabase_client:
        try:
            supabase_client.table("Matches").delete().eq("Tournament_ID", t_id_clean).execute()
            supabase_client.table("Tournaments").delete().eq("Tournament_ID", t_id_clean).execute()
        except Exception as e:
            print(f"[Supabase] Error deleting tournament '{t_id_clean}': {e}")

    await interaction.followup.send(
        f"🗑️ Successfully deleted tournament `{t_id_clean}` and all associated matches and schedules.",
        ephemeral=False
    )


@tournament_group.command(name="info", description="Display configuration details of a tournament")
@app_commands.describe(tournament="Select tournament to view")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def tournament_info(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild_id:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    tournaments = load_guild_tournaments(interaction.guild_id)
    if not tournaments:
        await interaction.response.send_message("ℹ️ No registered tournaments found. Use `/tournament add` to create one.", ephemeral=True)
        return

    target_t_data = None
    if tournament:
        t_id_clean = tournament.strip().lower()
        target_t_data = tournaments.get(t_id_clean)
    else:
        for t_id, t_cfg in tournaments.items():
            if t_cfg.get("state") == "active":
                target_t_data = t_cfg
                break
        if not target_t_data:
            target_t_data = list(tournaments.values())[0]

    if not target_t_data:
        await interaction.response.send_message("❌ Tournament not found.", ephemeral=True)
        return

    embed, file = await build_tournament_embed(interaction, target_t_data, f"Tournament Details — {target_t_data.get('id', 'N/A')}")
    if file:
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=False)


@tournament_group.command(name="list", description="List all tournaments registered for this server")
@with_guild_context
async def tournament_list(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    tournaments = load_guild_tournaments(interaction.guild_id)
    if not tournaments:
        await interaction.response.send_message("ℹ️ No tournaments registered yet. Use `/tournament add` to create one.", ephemeral=False)
        return

    embed = discord.Embed(
        title=f"🏆 Server Tournaments [{len(tournaments)}]",
        description="List of registered tournaments for this server:",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )

    for t_id, t_cfg in tournaments.items():
        state_icon = "🟢" if t_cfg.get("state") == "active" else "🟡" if t_cfg.get("state") == "pending" else "🔴"
        name = t_cfg.get("name", "Unnamed")
        auto_room = "Enabled" if t_cfg.get("auto_room_creation") else "Disabled"
        embed.add_field(
            name=f"{state_icon} {name} (`{t_id}`)",
            value=f"**State:** {t_cfg.get('state', 'pending').title()}\n**Auto Room:** {auto_room}\n**Bracket:** [Link]({t_cfg.get('challonge_bracket_link')})" if t_cfg.get('challonge_bracket_link') else f"**State:** {t_cfg.get('state', 'pending').title()}\n**Auto Room:** {auto_room}",
            inline=False
        )

    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed, ephemeral=False)


# ===========================================================================================
# LINK COMMAND GROUP
# ===========================================================================================

class LinkMissingView(discord.ui.View):
    def __init__(self, pages: list, author_id: int):
        super().__init__(timeout=180)
        self.pages = pages
        self.current_page = 0
        self.author_id = author_id
        self.update_buttons()

    def update_buttons(self):
        self.first_page.disabled = (self.current_page == 0)
        self.prev_page.disabled = (self.current_page == 0)
        self.next_page.disabled = (self.current_page >= len(self.pages) - 1)
        self.last_page.disabled = (self.current_page >= len(self.pages) - 1)

    async def update_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ You cannot control this pagination view.", ephemeral=False)
            return
        self.update_buttons()
        embed = self.pages[self.current_page]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏮️", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = 0
        await self.update_page(interaction)

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.primary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_page(interaction)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.primary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
        await self.update_page(interaction)

    @discord.ui.button(label="⏭️", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page = len(self.pages) - 1
        await self.update_page(interaction)


link_group = app_commands.Group(name="link", description="Manage match links and VODs")

@link_group.command(name="add", description="Add a recording/VOD link for a match event")
@app_commands.describe(
    tournament="Select the tournament",
    match="Select the match event by Name or ID",
    link_type="Select what type of link you are adding",
    link="The URL of the recording/VOD link to add"
)
@app_commands.choices(link_type=[
    app_commands.Choice(name="General Recording", value="general"),
    app_commands.Choice(name="Recorder VOD", value="recorder"),
    app_commands.Choice(name="Judge VOD", value="judge"),
])
@app_commands.autocomplete(tournament=tournament_autocomplete, match=match_autocomplete)
@with_guild_context
async def link_add(
    interaction: discord.Interaction,
    tournament: str,
    match: str,
    link_type: app_commands.Choice[str],
    link: str
):
    await interaction.response.defer(ephemeral=False)

    link_stripped = link.strip()
    if not (link_stripped.startswith("http://") or link_stripped.startswith("https://")):
        await interaction.followup.send("❌ Please provide a valid URL starting with `http://` or `https://`.", ephemeral=False)
        return

    ev_id, ev_data = find_event_by_name_or_id(interaction.guild.id, match)
    if not ev_id or not ev_data:
        await interaction.followup.send("❌ No matching scheduled event was found.", ephemeral=False)
        return

    key = "recording_link"
    if link_type.value == "recorder":
        key = "recorder_link"
    elif link_type.value == "judge":
        key = "judge_link"
        
    ev_data[key] = link_stripped

    rec_obj = ev_data.get('recorder')
    rec_credited_name = None
    if rec_obj and not ev_data.get('recorder_credited'):
        rec_mem = None
        if isinstance(rec_obj, (discord.Member, discord.User)):
            rec_mem = rec_obj
        elif isinstance(rec_obj, (int, str)) and str(rec_obj).isdigit():
            rec_mem = interaction.guild.get_member(int(rec_obj))
            
        if not rec_mem and isinstance(rec_obj, str) and rec_obj.isdigit():
            try: rec_mem = await interaction.guild.fetch_member(int(rec_obj))
            except: pass

        if rec_mem:
            update_staff_stats(rec_mem, "recorder")
            ev_data['recorder_credited'] = True
            rec_credited_name = rec_mem.mention
        elif interaction.user:
            update_staff_stats(interaction.user, "recorder")
            ev_data['recorder_credited'] = True
            rec_credited_name = interaction.user.mention

    save_scheduled_events()
    asyncio.create_task(save_event_to_supabase(ev_id, ev_data))
    await update_results_embed_with_links(interaction.guild, ev_data)

    event_saved_note = f"✅ Link saved to event record **`{ev_id}`** ({ev_data.get('match_name', 'Match')})."
    if rec_credited_name:
        event_saved_note += f"\n🎉 **Recorder credit registered in staff stats for {rec_credited_name}!**"

    link_label = link_type.name
    embed = discord.Embed(
        title=f"🎥 {link_label} Added",
        description=(
            f"**Tournament:** {tournament}\n"
            f"**Event / Match:** {ev_data.get('match_name') or match}\n"
            f"**Match ID:** `{ev_id}`\n"
            f"**Link:** {link_stripped}"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="📋 Details", value=event_saved_note, inline=False)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Link System")

    await interaction.followup.send(embed=embed, ephemeral=False)


@link_group.command(name="edit", description="Edit an existing recording/VOD link for a match event")
@app_commands.describe(
    tournament="Select the tournament",
    match="Select the match event by Name or ID",
    link_type="Select what type of link you are updating",
    new_link="The updated URL of the recording/VOD link"
)
@app_commands.choices(link_type=[
    app_commands.Choice(name="General Recording", value="general"),
    app_commands.Choice(name="Recorder VOD", value="recorder"),
    app_commands.Choice(name="Judge VOD", value="judge"),
])
@app_commands.autocomplete(tournament=tournament_autocomplete, match=match_autocomplete)
@with_guild_context
async def link_edit(
    interaction: discord.Interaction,
    tournament: str,
    match: str,
    link_type: app_commands.Choice[str],
    new_link: str
):
    await interaction.response.defer(ephemeral=False)

    link_stripped = new_link.strip()
    if not (link_stripped.startswith("http://") or link_stripped.startswith("https://")):
        await interaction.followup.send("❌ Please provide a valid URL starting with `http://` or `https://`.", ephemeral=False)
        return

    ev_id, ev_data = find_event_by_name_or_id(interaction.guild.id, match)
    if not ev_id or not ev_data:
        await interaction.followup.send("❌ No matching scheduled event was found.", ephemeral=False)
        return

    key = "recording_link"
    if link_type.value == "recorder":
        key = "recorder_link"
    elif link_type.value == "judge":
        key = "judge_link"

    old_link = ev_data.get(key, "None")
    ev_data[key] = link_stripped
    save_scheduled_events()
    asyncio.create_task(save_event_to_supabase(ev_id, ev_data))
    await update_results_embed_with_links(interaction.guild, ev_data)

    event_saved_note = f"✅ Link updated for event record **`{ev_id}`** ({ev_data.get('match_name', 'Match')})."

    embed = discord.Embed(
        title=f"🎥 {link_type.name} Updated",
        description=(
            f"**Tournament:** {tournament}\n"
            f"**Event / Match:** {ev_data.get('match_name') or match}\n"
            f"**Match ID:** `{ev_id}`\n"
            f"**Old Link:** {old_link}\n"
            f"**New Link:** {link_stripped}"
        ),
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="📋 Status", value=event_saved_note, inline=False)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Link System")

    await interaction.followup.send(embed=embed, ephemeral=False)


@link_group.command(name="delete", description="Delete a recording/VOD link from a match event")
@app_commands.describe(
    tournament="Select the tournament",
    match="Select the match event by Name or ID",
    link_type="Select which link type to remove"
)
@app_commands.choices(link_type=[
    app_commands.Choice(name="General Recording", value="general"),
    app_commands.Choice(name="Recorder VOD", value="recorder"),
    app_commands.Choice(name="Judge VOD", value="judge"),
    app_commands.Choice(name="All Links", value="all"),
])
@app_commands.autocomplete(tournament=tournament_autocomplete, match=match_autocomplete)
@with_guild_context
async def link_delete(
    interaction: discord.Interaction,
    tournament: str,
    match: str,
    link_type: app_commands.Choice[str]
):
    await interaction.response.defer(ephemeral=False)

    ev_id, ev_data = find_event_by_name_or_id(interaction.guild.id, match)
    if not ev_id or not ev_data:
        await interaction.followup.send("❌ No matching scheduled event was found.", ephemeral=False)
        return

    removed_types = []
    if link_type.value in ("general", "all"):
        ev_data["recording_link"] = ""
        removed_types.append("General Recording")
    if link_type.value in ("recorder", "all"):
        ev_data["recorder_link"] = ""
        removed_types.append("Recorder VOD")
    if link_type.value in ("judge", "all"):
        ev_data["judge_link"] = ""
        removed_types.append("Judge VOD")

    save_scheduled_events()
    asyncio.create_task(save_event_to_supabase(ev_id, ev_data))
    await update_results_embed_with_links(interaction.guild, ev_data)


    embed = discord.Embed(
        title="🎥 Recording Link Deleted",
        description=(
            f"**Tournament:** {tournament}\n"
            f"**Event / Match:** {ev_data.get('match_name') or match}\n"
            f"**Match ID:** `{ev_id}`\n"
            f"**Link Type:** {', '.join(removed_types)}\n"
            f"**Action By:** {interaction.user.mention}"
        ),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Link System")
    await interaction.followup.send(embed=embed, ephemeral=False)


@link_group.command(name="missing", description="List matches missing VOD links with paginated view")
@app_commands.describe(tournament="Filter by tournament (optional)")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def link_missing(interaction: discord.Interaction, tournament: str = None):
    await interaction.response.defer(ephemeral=False)

    missing_list = []
    for ev_id, ev_data in scheduled_events.items():
        if str(ev_data.get('guild_id')) != str(interaction.guild.id):
            continue
        if tournament:
            t_name = ev_data.get('tournament') or ''
            if tournament.lower() not in t_name.lower():
                continue

        rec_link = ev_data.get('recorder_link')
        jdg_link = ev_data.get('judge_link')
        general_link = ev_data.get('recording_link')

        missing_types = []
        if not general_link: missing_types.append("General Link")
        if not rec_link: missing_types.append("Recorder VOD")
        if not jdg_link: missing_types.append("Judge VOD")

        if missing_types:
            missing_list.append((ev_id, ev_data, missing_types))

    if not missing_list:
        embed = discord.Embed(
            title="🎥 Missing VOD Links",
            description="🎉 All matches have their recording and VOD links fully updated!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"{ORGANIZATION_NAME} • Link System")
        await interaction.followup.send(embed=embed, ephemeral=False)
        return

    items_per_page = 5
    pages = []
    total_pages = (len(missing_list) + items_per_page - 1) // items_per_page

    for page_idx in range(total_pages):
        start = page_idx * items_per_page
        chunk = missing_list[start:start + items_per_page]
        
        embed = discord.Embed(
            title=f"🎥 Missing VOD Links (Page {page_idx + 1}/{total_pages})",
            description=f"Total matches missing links: **{len(missing_list)}**",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        
        for ev_id, ev_data, missing_types in chunk:
            m_name = ev_data.get('match_name') or f"{ev_data.get('team1_name', 'T1')} vs {ev_data.get('team2_name', 'T2')}"
            rnd = ev_data.get('round', 'N/A')
            tourn = ev_data.get('tournament', 'N/A')
            status = ev_data.get('status', 'Scheduled')
            missing_str = ", ".join(missing_types)
            
            embed.add_field(
                name=f"📌 [{ev_id}] {m_name}",
                value=f"• **Tournament:** {tourn} ({rnd})\n• **Status:** {status}\n• **Missing:** `{missing_str}`",
                inline=False
            )
            
        embed.set_footer(text=f"Page {page_idx + 1}/{total_pages} • {ORGANIZATION_NAME} Link System")
        pages.append(embed)

    view = LinkMissingView(pages, interaction.user.id)
    await interaction.followup.send(embed=pages[0], view=view, ephemeral=False)


# ===========================================================================================
# DEADLINE HELPERS & REMINDER SCHEDULING
# ===========================================================================================

def parse_deadline_datetime(date_str: str, time_str: str = "23:59") -> Optional[datetime.datetime]:
    date_str = date_str.strip()
    time_str = time_str.strip() if time_str else "23:59"
    
    date_formats = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y"]
    parsed_date = None
    for fmt in date_formats:
        try:
            parsed_date = datetime.datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            continue
            
    if not parsed_date:
        return None
        
    time_formats = ["%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M%p", "%H%M"]
    parsed_time = None
    for t_fmt in time_formats:
        try:
            parsed_time = datetime.datetime.strptime(time_str, t_fmt).time()
            break
        except ValueError:
            continue
            
    if not parsed_time:
        parsed_time = datetime.time(23, 59)
        
    dt = datetime.datetime.combine(parsed_date, parsed_time).replace(tzinfo=pytz.UTC)
    return dt

async def deadline_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    g_id = interaction.guild_id
    choices = []
    for dl_id, dl_data in scheduled_deadlines.items():
        if dl_data.get('guild_id') == g_id:
            rnd = dl_data.get('round', 'Unknown')
            t_name = dl_data.get('tournament', '')
            dt = dl_data.get('deadline_dt')
            dt_str = ""
            if isinstance(dt, datetime.datetime):
                dt_str = dt.strftime("%d/%m/%Y %H:%M UTC")
            elif isinstance(dt, str):
                try:
                    parsed = datetime.datetime.fromisoformat(dt)
                    dt_str = parsed.strftime("%d/%m/%Y %H:%M UTC")
                except Exception:
                    dt_str = dt
            label = f"{t_name + ' - ' if t_name else ''}{rnd} ({dt_str})".strip()
            if current.lower() in label.lower() or current.lower() in dl_id.lower():
                choices.append(app_commands.Choice(name=label[:100], value=dl_id))
    return choices[:25]

def cancel_deadline_tasks(dl_id: str):
    if dl_id in deadline_tasks:
        for t in deadline_tasks[dl_id]:
            if not t.done():
                t.cancel()
        del deadline_tasks[dl_id]

def schedule_deadline_tasks(bot: commands.Bot, dl_id: str):
    cancel_deadline_tasks(dl_id)
    
    dl_data = scheduled_deadlines.get(dl_id)
    if not dl_data:
        return
        
    guild_id = dl_data.get('guild_id')
    deadline_dt = dl_data.get('deadline_dt')
    if isinstance(deadline_dt, str):
        try:
            deadline_dt = datetime.datetime.fromisoformat(deadline_dt)
        except Exception:
            return
    if not isinstance(deadline_dt, datetime.datetime):
        return
    if deadline_dt.tzinfo is None:
        deadline_dt = deadline_dt.replace(tzinfo=pytz.UTC)
        
    now = datetime.datetime.now(pytz.UTC)
    deadline_date = deadline_dt.date()
    reminder_1_dt = datetime.datetime.combine(deadline_date - datetime.timedelta(days=1), datetime.time(6, 0)).replace(tzinfo=pytz.UTC)
    reminder_2_dt = datetime.datetime.combine(deadline_date, datetime.time(6, 0)).replace(tzinfo=pytz.UTC)
    
    tasks = []
    if reminder_1_dt > now:
        t1 = asyncio.create_task(run_deadline_reminder_task(bot, dl_id, reminder_1_dt, "one_day_before"))
        tasks.append(t1)
    if reminder_2_dt > now:
        t2 = asyncio.create_task(run_deadline_reminder_task(bot, dl_id, reminder_2_dt, "deadline_day"))
        tasks.append(t2)
        
    if tasks:
        deadline_tasks[dl_id] = tasks

async def run_deadline_reminder_task(bot: commands.Bot, dl_id: str, target_dt: datetime.datetime, reminder_type: str):
    try:
        now = datetime.datetime.now(pytz.UTC)
        delay = (target_dt - now).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)
            
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
                return
                
        # Resolve deadline channel
        t_name = dl_data.get('tournament')
        channel_id = dl_data.get('channel_id')
        if not channel_id:
            t_cfg = get_active_tournament_config(guild_id)
            if t_cfg:
                channel_id = t_cfg.get('deadline') or t_cfg.get('Deadline_Channel_ID')
            if not channel_id:
                cfg = get_guild_config(guild_id)
                channel_id = cfg.get('channel_ids', {}).get('deadlines')
                
        if not channel_id:
            return
            
        channel = guild.get_channel(int(channel_id))
        if not channel:
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except Exception:
                return
                
        # Ping the Players_Role_ID
        cfg = get_guild_config(guild_id)
        players_role_ping = "@Player"
        players_r_id = dl_data.get('players_role_id')
        if not players_r_id:
            t_cfg_dl = get_active_tournament_config(guild_id)
            if t_cfg_dl:
                raw = t_cfg_dl.get('players_role_id')
                if raw:
                    try: players_r_id = int(raw)
                    except: pass
        if not players_r_id:
            raw = cfg.get('role_ids', {}).get('players')
            if raw:
                try: players_r_id = int(raw)
                except: pass
        if players_r_id:
            role_obj = guild.get_role(players_r_id)
            if role_obj:
                players_role_ping = role_obj.mention

        deadline_date_str = deadline_dt.strftime("%d/%m/%Y")
        deadline_time_str = deadline_dt.strftime("%H:%M UTC")

        if reminder_type == "one_day_before":
            message = (
                f"Hello {players_role_ping}!\n"
                f"Tomorrow ({deadline_date_str}) is the deadline for Round **{round_name}**. If you have not opened your ticket and scheduled your match time, please do so.\n"
                f"**Deadline: {deadline_time_str}** (<t:{int(deadline_dt.timestamp())}:R>)\n\n"
                f"Good luck!"
            )
        else:
            message = (
                f"Hello {players_role_ping}!\n"
                f"Today ({deadline_date_str}) is the deadline for Round **{round_name}**. If you have not opened your ticket and scheduled your match time, please do so immediately!\n"
                f"**Deadline: {deadline_time_str}** (<t:{int(deadline_dt.timestamp())}:R>)\n\n"
                f"Good luck!"
            )

        await channel.send(message)
    except Exception as e:
        print(f"Error running deadline reminder task for {dl_id}: {e}")


# ===========================================================================================
# DEADLINE COMMAND GROUP
# ===========================================================================================

deadline_group = app_commands.Group(name="deadline", description="Manage round match deadlines and automated player reminders")

@deadline_group.command(name="add", description="Add and announce a round match deadline with automated player reminders")
@app_commands.describe(
    round="Round name (e.g. Round 1, Round 2, Quarter-Finals, Semi-Finals, Finals)",
    date="Deadline date (e.g. DD/MM/YYYY or YYYY-MM-DD)",
    time="Deadline time in UTC (e.g. 23:59 or 18:00 - default: 23:59)",
    tournament="Tournament to associate with (optional)",
    note="Optional additional notes or instructions"
)
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def deadline_add_cmd(
    interaction: discord.Interaction,
    round: str,
    date: str,
    time: Optional[str] = "23:59",
    tournament: Optional[str] = None,
    note: Optional[str] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to manage deadlines.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    dt = parse_deadline_datetime(date, time or "23:59")
    if not dt:
        await interaction.followup.send(
            "❌ Invalid date/time format. Please use `DD/MM/YYYY` (or `YYYY-MM-DD`) and `HH:MM` in UTC (e.g. `05/09/2026 23:59`).",
            ephemeral=True
        )
        return

    # Resolve tournament
    guild_id = interaction.guild.id
    t_cfg = None
    t_name = tournament
    if t_name:
        all_t = load_guild_tournaments(guild_id)
        for t_k, t_v in all_t.items():
            if t_v.get('name', '').lower() == t_name.lower() or t_k.lower() == t_name.lower():
                t_cfg = t_v
                t_name = t_v.get('name', t_name)
                break
    if not t_cfg:
        t_cfg = get_active_tournament_config(guild_id)
        if t_cfg:
            t_name = t_cfg.get('name', 'Tournament')

    # Resolve deadline channel
    channel_id = None
    if t_cfg:
        channel_id = t_cfg.get('deadline') or t_cfg.get('Deadline_Channel_ID')
    if not channel_id:
        cfg = get_guild_config(guild_id)
        channel_id = cfg.get('channel_ids', {}).get('deadlines')

    deadline_channel = None
    if channel_id:
        try:
            deadline_channel = interaction.guild.get_channel(int(channel_id))
            if not deadline_channel:
                deadline_channel = await interaction.guild.fetch_channel(int(channel_id))
        except Exception:
            deadline_channel = None

    if not deadline_channel:
        await interaction.followup.send(
            "❌ No deadline channel is configured for this tournament or server. Please set `deadline_channel` in `/tournament edit` or `/settings add` first.",
            ephemeral=True
        )
        return

    # Resolve Players_Role_ID
    cfg = get_guild_config(guild_id)
    players_role = None
    players_r_id = None
    if t_cfg:
        raw = t_cfg.get('players_role_id')
        if raw:
            try: players_r_id = int(raw)
            except: pass
    if not players_r_id:
        raw = cfg.get('role_ids', {}).get('players')
        if raw:
            try: players_r_id = int(raw)
            except: pass
    if players_r_id:
        players_role = interaction.guild.get_role(players_r_id)

    unix_ts = int(dt.timestamp())
    embed = discord.Embed(
        title=f"⏰ MATCH DEADLINE — {round.upper()}",
        description=(
            f"🏆 **Tournament:** `{t_name or 'Tournament'}`\n"
            f"⚔️ **Round:** `{round}`\n"
            f"📅 **Deadline:** <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
            + (f"📌 **Note:** {note}\n" if note else "")
            + f"\n⚠️ Please ensure all matches for **{round}** are scheduled and completed in tickets before this deadline!"
        ),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.set_footer(text=f"{interaction.guild.name} • Match Deadlines • Set by {interaction.user.display_name}")

    msg_content = players_role.mention if players_role else ""
    try:
        announcement_msg = await deadline_channel.send(content=msg_content, embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to post deadline to {deadline_channel.mention}: {e}")
        return

    clean_round = re.sub(r'[^a-zA-Z0-9_]', '_', round.lower())
    clean_tname = re.sub(r'[^a-zA-Z0-9_]', '_', (t_name or 'tourney').lower())
    dl_id = f"dl_{clean_tname}_{clean_round}_{guild_id}"

    dl_data = {
        'guild_id': guild_id,
        'tournament': t_name or '',
        'round': round,
        'deadline_dt': dt,
        'channel_id': deadline_channel.id,
        'message_id': announcement_msg.id,
        'note': note or '',
        'players_role_id': players_role.id if players_role else None
    }

    save_scheduled_deadline(dl_id, dl_data)
    schedule_deadline_tasks(interaction.client, dl_id)

    log_embed = discord.Embed(
        title="⏰ Match Deadline Scheduled",
        description=f"**{interaction.user.mention}** scheduled deadline for **{round}** in {deadline_channel.mention}.",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.add_field(name="Tournament", value=t_name or "—", inline=True)
    log_embed.add_field(name="Deadline", value=f"<t:{unix_ts}:F>", inline=True)
    if note:
        log_embed.add_field(name="Note", value=note, inline=False)
    await log_bot_activity(interaction.guild, log_embed)

    confirm_embed = discord.Embed(
        title="✅ Deadline Scheduled",
        description=(
            f"Successfully posted and scheduled deadline for **{round}** in {deadline_channel.mention}!\n\n"
            f"📅 **Deadline:** <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
            f"🔔 **Pings:** {players_role.mention if players_role else 'None'}\n"
            f"⏰ **Automated Reminders:** 24 hours before & day of deadline at 06:00 UTC"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    await interaction.followup.send(embed=confirm_embed)

@deadline_group.command(name="edit", description="Edit an existing round match deadline")
@app_commands.describe(
    deadline="Select the deadline to edit",
    new_date="New deadline date (e.g. DD/MM/YYYY or YYYY-MM-DD)",
    new_time="New deadline time in UTC (e.g. 23:59)",
    new_round="New round name (optional)",
    note="New or updated note (optional)"
)
@app_commands.autocomplete(deadline=deadline_autocomplete)
@with_guild_context
async def deadline_edit_cmd(
    interaction: discord.Interaction,
    deadline: str,
    new_date: Optional[str] = None,
    new_time: Optional[str] = None,
    new_round: Optional[str] = None,
    note: Optional[str] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to manage deadlines.", ephemeral=True)
        return

    dl_data = scheduled_deadlines.get(deadline)
    if not dl_data:
        await interaction.response.send_message("❌ Deadline not found. Please select from the autocomplete list.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    old_dt = dl_data.get('deadline_dt')
    if isinstance(old_dt, str):
        try:
            old_dt = datetime.datetime.fromisoformat(old_dt)
        except Exception:
            old_dt = datetime.datetime.now(pytz.UTC)

    if new_date or new_time:
        date_str = new_date if new_date else old_dt.strftime("%d/%m/%Y")
        time_str = new_time if new_time else old_dt.strftime("%H:%M")
        dt = parse_deadline_datetime(date_str, time_str)
        if not dt:
            await interaction.followup.send("❌ Invalid date/time format. Please use `DD/MM/YYYY` and `HH:MM` UTC.", ephemeral=True)
            return
        dl_data['deadline_dt'] = dt
    else:
        dt = old_dt

    if new_round:
        dl_data['round'] = new_round
    if note is not None:
        dl_data['note'] = note

    save_scheduled_deadline(deadline, dl_data)
    schedule_deadline_tasks(interaction.client, deadline)

    unix_ts = int(dt.timestamp())
    channel_id = dl_data.get('channel_id')
    round_name = dl_data.get('round')
    t_name = dl_data.get('tournament', 'Tournament')

    # Resolve players role
    guild_id = interaction.guild.id
    cfg = get_guild_config(guild_id)
    players_role = None
    players_r_id = dl_data.get('players_role_id')
    if not players_r_id:
        raw = cfg.get('role_ids', {}).get('players')
        if raw:
            try: players_r_id = int(raw)
            except: pass
    if players_r_id:
        players_role = interaction.guild.get_role(players_r_id)

    if channel_id:
        try:
            chan = interaction.guild.get_channel(int(channel_id))
            if chan:
                update_embed = discord.Embed(
                    title=f"📢 DEADLINE UPDATED — {round_name.upper()}",
                    description=(
                        f"🏆 **Tournament:** `{t_name}`\n"
                        f"⚔️ **Round:** `{round_name}`\n"
                        f"📅 **New Deadline:** <t:{unix_ts}:F> (<t:{unix_ts}:R>)\n"
                        + (f"📌 **Note:** {dl_data.get('note')}\n" if dl_data.get('note') else "")
                        + f"\n⚠️ The deadline has been updated by staff. Please adjust match schedules accordingly!"
                    ),
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                update_embed.set_footer(text=f"{interaction.guild.name} • Match Deadlines")
                await chan.send(content=players_role.mention if players_role else "", embed=update_embed)
        except Exception as e:
            print(f"Failed to post deadline update notice: {e}")

    log_embed = discord.Embed(
        title="⏰ Match Deadline Edited",
        description=f"**{interaction.user.mention}** edited the deadline for **{round_name}**.",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.add_field(name="New Deadline", value=f"<t:{unix_ts}:F>", inline=True)
    await log_bot_activity(interaction.guild, log_embed)

    confirm_embed = discord.Embed(
        title="✅ Deadline Updated",
        description=(
            f"Successfully updated deadline for **{round_name}**!\n\n"
            f"📅 **New Deadline:** <t:{unix_ts}:F> (<t:{unix_ts}:R>)"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    await interaction.followup.send(embed=confirm_embed)

@deadline_group.command(name="delete", description="Delete an active match deadline and cancel reminders")
@app_commands.describe(deadline="Select the deadline to delete")
@app_commands.autocomplete(deadline=deadline_autocomplete)
@with_guild_context
async def deadline_delete_cmd(interaction: discord.Interaction, deadline: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to manage deadlines.", ephemeral=True)
        return

    dl_data = scheduled_deadlines.get(deadline)
    if not dl_data:
        await interaction.response.send_message("❌ Deadline not found. Please select from the autocomplete list.", ephemeral=True)
        return

    round_name = dl_data.get('round', 'Unknown')
    cancel_deadline_tasks(deadline)
    delete_scheduled_deadline(deadline)

    log_embed = discord.Embed(
        title="🗑️ Match Deadline Deleted",
        description=f"**{interaction.user.mention}** deleted the deadline for **{round_name}**.",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    await log_bot_activity(interaction.guild, log_embed)

    await interaction.response.send_message(f"🗑️ Successfully deleted deadline for **{round_name}** and cancelled automated reminders.")

@deadline_group.command(name="list", description="List all scheduled match deadlines for the server")
@app_commands.describe(tournament="Filter by tournament name (optional)")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def deadline_list_cmd(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    guild_deadlines = []
    for dl_id, dl_data in scheduled_deadlines.items():
        if dl_data.get('guild_id') == guild_id:
            if tournament:
                t_name = dl_data.get('tournament', '')
                if tournament.lower() not in t_name.lower():
                    continue
            guild_deadlines.append(dl_data)

    if not guild_deadlines:
        await interaction.response.send_message(f"ℹ️ No active deadlines found{' for `' + tournament + '`' if tournament else ''}.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⏰ Scheduled Match Deadlines",
        description=f"Active round deadlines for **{interaction.guild.name}**:",
        color=discord.Color.gold(),
        timestamp=discord.utils.utcnow()
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    for dl in guild_deadlines:
        rnd = dl.get('round', 'Unknown')
        t_name = dl.get('tournament', 'Tournament')
        dt = dl.get('deadline_dt')
        if isinstance(dt, str):
            try: dt = datetime.datetime.fromisoformat(dt)
            except: pass
        
        ts_str = "—"
        if isinstance(dt, datetime.datetime):
            unix_ts = int(dt.timestamp())
            ts_str = f"<t:{unix_ts}:F> (<t:{unix_ts}:R>)"
        note = dl.get('note')
        val = f"📅 **Deadline:** {ts_str}"
        if note:
            val += f"\n📌 **Note:** {note}"
        embed.add_field(name=f"🏆 {t_name} — {rnd}", value=val, inline=False)

    embed.set_footer(text=f"{interaction.guild.name} • Match Deadlines")
    await interaction.response.send_message(embed=embed)


# ===========================================================================================
# AUTO ROOM CREATION LOGIC & BACKGROUND SWEEPER
# ===========================================================================================

async def auto_create_open_tickets_for_tournament(guild: discord.Guild, t_cfg: dict, on_progress=None) -> tuple[int, str]:
    guild_id = guild.id
    if guild_id not in auto_room_locks:
        auto_room_locks[guild_id] = asyncio.Lock()
        
    async with auto_room_locks[guild_id]:
        import time as pytime
        last_edit = 0
        
        async def report(percent: int, text: str, force: bool = False):
            nonlocal last_edit
            if not on_progress:
                return
            now = pytime.time()
            if force or (now - last_edit >= 1.5):
                try:
                    await on_progress(percent, text)
                except Exception:
                    pass
                last_edit = now

        await report(0, "Fetching matches from Challonge...", force=True)
        
        cfg = get_guild_config(guild.id)
        bracket_link = t_cfg.get('challonge_bracket_link') or t_cfg.get('id')
        api_key = t_cfg.get('key') or get_bracket_api_key(guild.id)
        sheet_link = t_cfg.get('captains_sheet_link') or t_cfg.get('sheet_link') or cfg.get('player_info_link') or cfg.get('google_sheet_link')
        
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
            
        await report(15, f"Fetched {len(matches)} open match(es). Fetching captains from Google Sheet...", force=True)
        
        captains_dict, is_1v1, err2 = await fetch_google_sheet_captains(sheet_link)
        if err2:
            return 0, f"Google Sheet Error: {err2}"
            
        await report(30, "Parsing categories and role permissions...", force=True)
        
        categories = []
        for i in range(1, 5):
            cat_id = t_cfg.get(f'ticket_open_category_{i}') or t_cfg.get(f'Open_Category_{i}_ID')
            if cat_id:
                try:
                    cat_id = int(cat_id)
                except (ValueError, TypeError):
                    pass
                cat = discord.utils.get(guild.categories, id=cat_id)
                if cat:
                    categories.append(cat)
                    
        if not categories:
            return 0, "No open ticket categories configured for this tournament (set in `/tournament edit`)."
            
        helper_team_role = None
        if helper_role_id := t_cfg.get('helper_role_id'):
            try: helper_role_id = int(helper_role_id)
            except (ValueError, TypeError): pass
            helper_team_role = discord.utils.get(guild.roles, id=helper_role_id)
        if not helper_team_role:
            if global_helper_id := cfg.get('role_ids', {}).get('helper_team'):
                try: global_helper_id = int(global_helper_id)
                except (ValueError, TypeError): pass
                helper_team_role = discord.utils.get(guild.roles, id=global_helper_id)
                
        rules_link = f"https://discord.com/channels/{guild.id}/{t_cfg.get('rules')}" if t_cfg.get('rules') else "Not Set"
        deadline_link = f"https://discord.com/channels/{guild.id}/{t_cfg.get('deadline')}" if t_cfg.get('deadline') else "Not Set"
        bracket_display_link = bracket_link if bracket_link.startswith("http") else f"https://challonge.com/{bracket_link}"
        
        created_count = 0
        total_matches = len(matches)

        for idx, match in enumerate(matches):
            team1, team2 = match['team1'], match['team2']
            p1_id, p2_id = match['player1_id'], match['player2_id']
            match_id, mod_round = match['id'], match['round']
            round_name = match.get('round_name', f"Round {mod_round}")
            
            loop_percent = 35 + int(((idx + 1) / total_matches) * 60)
            await report(loop_percent, f"Processing match {idx+1}/{total_matches}: {team1} vs {team2}...")
            
            def get_captain_raw(t_name: str) -> str:
                if not t_name:
                    return ""
                if t_name in captains_dict:
                    return captains_dict[t_name]
                if t_name.strip() in captains_dict:
                    return captains_dict[t_name.strip()]
                clean = t_name.strip().lower()
                for k, v in captains_dict.items():
                    if k.strip().lower() == clean:
                        return v
                alpha_clean = re.sub(r'[^a-zA-Z0-9]', '', clean)
                if alpha_clean:
                    for k, v in captains_dict.items():
                        if re.sub(r'[^a-zA-Z0-9]', '', k).lower() == alpha_clean:
                            return v
                for k, v in captains_dict.items():
                    k_alpha = re.sub(r'[^a-zA-Z0-9]', '', k).lower()
                    if len(k_alpha) >= 3 and (k_alpha in alpha_clean or alpha_clean in k_alpha):
                        return v
                return ""

            c1_raw = get_captain_raw(team1)
            c2_raw = get_captain_raw(team2)
            
            async def resolve_member_and_mention(raw: str, fallback_name: str) -> tuple[Optional[Union[discord.Member, discord.Object]], str]:
                if not raw or not raw.strip():
                    raw = fallback_name
                clean_raw = raw.strip() if raw else ""
                if clean_raw.startswith('@'):
                    clean_raw = clean_raw[1:].strip()

                m = re.search(r'\b(\d{17,20})\b', clean_raw)
                uid = int(m.group(1)) if m else None

                if uid:
                    member = guild.get_member(uid)
                    if not member:
                        try:
                            member = await guild.fetch_member(uid)
                        except Exception:
                            pass
                    if member:
                        return member, member.mention
                    return discord.Object(id=uid), f"<@{uid}>"

                for member in guild.members:
                    m_names = [member.name.lower(), member.display_name.lower()]
                    if hasattr(member, 'global_name') and member.global_name:
                        m_names.append(member.global_name.lower())
                    if clean_raw.lower() in m_names:
                        return member, member.mention

                try:
                    found_members = await guild.query_members(query=clean_raw, limit=10)
                    for member in found_members:
                        m_names = [member.name.lower(), member.display_name.lower()]
                        if hasattr(member, 'global_name') and member.global_name:
                            m_names.append(member.global_name.lower())
                        if clean_raw.lower() in m_names:
                            return member, member.mention
                    if found_members:
                        return found_members[0], found_members[0].mention
                except Exception:
                    pass

                if clean_raw.startswith("<@") and clean_raw.endswith(">"):
                    return None, clean_raw

                return None, clean_raw
                
            cap1_obj, cap1_mention = await resolve_member_and_mention(c1_raw, team1)
            cap2_obj, cap2_mention = await resolve_member_and_mention(c2_raw, team2)

            captain1 = cap1_obj if isinstance(cap1_obj, discord.Member) else None
            captain2 = cap2_obj if isinstance(cap2_obj, discord.Member) else None
            
            round_lbl = str(mod_round)
            r_name_lower = round_name.lower()
            if "semi" in r_name_lower:
                round_lbl = "lsf" if "loser" in r_name_lower else "sf"
            elif "quarter" in r_name_lower:
                round_lbl = "lq" if "loser" in r_name_lower else "q"
            elif "final" in r_name_lower:
                round_lbl = "lfinal" if "loser" in r_name_lower else "final"
            elif "losers round" in r_name_lower:
                m_num = re.search(r'\d+', r_name_lower)
                round_lbl = f"lr{m_num.group(0)}" if m_num else f"lr{abs(mod_round)}"
            elif "round" in r_name_lower:
                m_num = re.search(r'\d+', r_name_lower)
                round_lbl = f"r{m_num.group(0)}" if m_num else f"r{mod_round}"
            else:
                round_lbl = re.sub(r'[^a-zA-Z0-9]', '', r_name_lower)

            if is_1v1:
                n1 = (captain1.name if captain1 else re.sub(r'[^a-zA-Z0-9]', '', team1))[:12].lower()
                n2 = (captain2.name if captain2 else re.sub(r'[^a-zA-Z0-9]', '', team2))[:12].lower()
                chan_name = f"{round_lbl}-{n1}-vs-{n2}"
            else:
                safe_t1 = re.sub(r'[^a-zA-Z0-9]', '', team1).lower()[:8]
                safe_t2 = re.sub(r'[^a-zA-Z0-9]', '', team2).lower()[:8]
                chan_name = f"{round_lbl}-{safe_t1}-vs-{safe_t2}"
                
            chan_name = re.sub(r'[^a-zA-Z0-9\-]', '-', chan_name)
            chan_name = re.sub(r'-+', '-', chan_name).strip('-')[:100].lower()
            topic = f"MatchID:{match_id}"
            
            # Duplicate check
            already_exists = False
            STATUS_PREFIXES = ("sh-", "dq-", "dd-", "ho-", "closed-", "done-")
            all_channels = list(guild._channels.values()) if hasattr(guild, '_channels') else list(guild.text_channels)
            for channel in all_channels:
                if not isinstance(channel, discord.TextChannel):
                    continue
                if channel.topic and f"MatchID:{match_id}" in channel.topic:
                    already_exists = True
                    break
                base_name = channel.name
                for pfx in STATUS_PREFIXES:
                    if base_name.startswith(pfx):
                        base_name = base_name[len(pfx):]
                        break
                if base_name == chan_name:
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
                overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_permissions=True)

                for role_key in ["admin_role_id", "helper_role_id"]:
                    if r_id := t_cfg.get(role_key):
                        try: r_id = int(r_id)
                        except (ValueError, TypeError): pass
                        if staff_r := discord.utils.get(guild.roles, id=r_id):
                            overwrites[staff_r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

                for role_key in ["head_organizer", "organizer", "helper_team"]:
                    if r_id := cfg.get('role_ids', {}).get(role_key):
                        try: r_id = int(r_id)
                        except (ValueError, TypeError): pass
                        if staff_r := discord.utils.get(guild.roles, id=r_id):
                            overwrites[staff_r] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

                if cap1_obj:
                    overwrites[cap1_obj] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                if cap2_obj:
                    overwrites[cap2_obj] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    
                new_ch = await guild.create_text_channel(
                    name=chan_name,
                    category=target_category,
                    topic=topic,
                    overwrites=overwrites
                )
                
                event_id = f"challonge_{match_id}"
                scheduled_events[event_id] = {
                    'guild_id': guild.id,
                    'title': f"{round_name} Match",
                    'datetime': datetime.datetime.utcnow(),
                    'time_str': "Live",
                    'date_str': "Live",
                    'round': round_name,
                    'group': None,
                    'minutes_left': 0,
                    'tournament': t_cfg.get('name', 'Tournament'),
                    'mode': None,
                    'judge': None,
                    'recorder': None,
                    'channel_id': new_ch.id,
                    'team1_captain': getattr(cap1_obj, 'id', None),
                    'team2_captain': getattr(cap2_obj, 'id', None),
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
                    description="Welcome to your match channel. Use this channel for all tournament discussions and match scheduling.",
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
                
                round_display = round_name
                if is_1v1:
                    pval = f"**Round:** {round_display}\n**Captain 1:** {cap1_mention}\n**Captain 2:** {cap2_mention}"
                else:
                    pval = f"**Round:** {round_display}\n**Team 1:** {team1} — Captain: {cap1_mention}\n**Team 2:** {team2} — Captain: {cap2_mention}"
                    
                rules_embed.add_field(name="👥 Match Participants", value=pval, inline=False)
                rules_embed.add_field(
                    name="🆘 Need Help?",
                    value=f"Ping {helper_team_role.mention if helper_team_role else '@Helper Team'} for assistance. ⚓",
                    inline=False
                )
                rules_embed.set_footer(text=f"{org_name} • Auto-Ticket")
                
                ping_parts = []
                if cap1_mention:
                    ping_parts.append(cap1_mention)
                if cap2_mention:
                    ping_parts.append(cap2_mention)
                ping_content = " ".join(ping_parts) if ping_parts else f"⚔️ {team1} vs {team2}"
                
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

async def auto_room_background_loop(bot: commands.Bot, guild_id: int):
    try:
        await asyncio.sleep(5)
    except asyncio.CancelledError:
        return

    while True:
        try:
            guild = bot.get_guild(guild_id)
            if guild:
                all_tournaments = load_guild_tournaments(guild_id)
                for t_k, t_cfg in all_tournaments.items():
                    if t_cfg.get('auto_room_creation'):
                        await auto_create_open_tickets_for_tournament(guild, t_cfg)
        except Exception as e:
            print(f"Error in auto_room background loop for guild {guild_id}: {e}")
            
        try:
            await asyncio.sleep(300)
        except asyncio.CancelledError:
            break

def start_auto_room_loop(bot: commands.Bot, guild_id: int):
    if guild_id in auto_room_loops and not auto_room_loops[guild_id].done():
        return
    task = asyncio.create_task(auto_room_background_loop(bot, guild_id))
    auto_room_loops[guild_id] = task
    print(f"🚀 Started auto-room background loop for guild {guild_id}")

def stop_auto_room_loop(guild_id: int):
    if task := auto_room_loops.pop(guild_id, None):
        task.cancel()
        print(f"⏹️ Stopped auto-room background loop for guild {guild_id}")


# ===========================================================================================
# AUTO ROOM COMMAND GROUP
# ===========================================================================================

auto_room_group = app_commands.Group(name="auto_room", description="Manage automatic match room ticket creation")

@auto_room_group.command(name="toggle", description="Toggle automatic room creation for a tournament")
@app_commands.describe(
    tournament="Tournament to configure (optional, defaults to active tournament)",
    enabled="Explicitly enable or disable auto room creation (optional)"
)
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_toggle_cmd(
    interaction: discord.Interaction,
    tournament: Optional[str] = None,
    enabled: Optional[bool] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to manage tournament settings.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    all_tournaments = load_guild_tournaments(guild_id)
    target_key = None
    target_cfg = None

    if tournament:
        for k, v in all_tournaments.items():
            if v.get('name', '').lower() == tournament.lower() or k.lower() == tournament.lower():
                target_key = k
                target_cfg = v
                break
        if not target_cfg:
            await interaction.response.send_message(f"❌ Tournament `{tournament}` not found.", ephemeral=True)
            return
    else:
        for k, v in all_tournaments.items():
            if v.get('state') == 'active':
                target_key = k
                target_cfg = v
                break
        if not target_cfg and all_tournaments:
            target_key, target_cfg = next(iter(all_tournaments.items()))

    if not target_cfg:
        await interaction.response.send_message("❌ No tournaments configured for this server. Use `/tournament add` first.", ephemeral=True)
        return

    curr_val = bool(target_cfg.get('auto_room_creation', False))
    new_val = (not curr_val) if enabled is None else enabled
    target_cfg['auto_room_creation'] = new_val
    all_tournaments[target_key] = target_cfg
    save_guild_tournaments(guild_id, all_tournaments)

    if new_val:
        start_auto_room_loop(interaction.client, guild_id)
    else:
        has_other_enabled = any(v.get('auto_room_creation') for v in all_tournaments.values())
        if not has_other_enabled:
            stop_auto_room_loop(guild_id)

    status_str = "ENABLED ✅" if new_val else "DISABLED ❌"
    embed = discord.Embed(
        title="⚙️ Automatic Room Creation",
        description=f"Auto room creation for **{target_cfg.get('name')}** is now **{status_str}**.",
        color=discord.Color.green() if new_val else discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    if new_val:
        embed.add_field(name="🔄 Background Sweep", value="Bot will automatically poll Challonge for open matches every 5 minutes and create ticket channels.", inline=False)
    else:
        embed.add_field(name="⏹️ Background Sweep", value="Background ticket creation suspended. You can still trigger manual sweeps with `/auto_room run`.", inline=False)
    
    embed.set_footer(text=f"{interaction.guild.name} • Auto Room System")
    await interaction.response.send_message(embed=embed)

@auto_room_group.command(name="run", description="Manually trigger the automatic match room ticket creation sweep")
@app_commands.describe(tournament="Tournament to run room creation for (optional)")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_run_cmd(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to run auto room creation.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    guild_id = interaction.guild.id
    all_tournaments = load_guild_tournaments(guild_id)
    target_cfg = None

    if tournament:
        for k, v in all_tournaments.items():
            if v.get('name', '').lower() == tournament.lower() or k.lower() == tournament.lower():
                target_cfg = v
                break
        if not target_cfg:
            await interaction.followup.send(f"❌ Tournament `{tournament}` not found.", ephemeral=True)
            return
    else:
        target_cfg = get_active_tournament_config(guild_id)
        if not target_cfg and all_tournaments:
            target_cfg = next(iter(all_tournaments.values()))

    if not target_cfg:
        await interaction.followup.send("❌ No tournament found for this server. Use `/tournament add` first.", ephemeral=True)
        return

    msg = await interaction.followup.send("⏳ Running automatic match room creation sweep... Please wait.")

    async def progress_hook(pct: int, text: str):
        try:
            await msg.edit(content=f"⏳ **[{pct}%]** {text}")
        except Exception:
            pass

    created_count, err = await auto_create_open_tickets_for_tournament(interaction.guild, target_cfg, on_progress=progress_hook)
    if err:
        await msg.edit(content=f"❌ Auto room creation encountered an issue:\n```{err}```")
        return

    embed = discord.Embed(
        title="🎫 Auto Room Sweep Complete",
        description=f"Created **{created_count}** new match room ticket(s) for **{target_cfg.get('name')}**.",
        color=discord.Color.green() if created_count > 0 else discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    if created_count == 0:
        embed.description = f"🎉 All open matches for **{target_cfg.get('name')}** already have tickets created!"
    embed.set_footer(text=f"{interaction.guild.name} • Auto Room System")
    await msg.edit(content=None, embed=embed)

@auto_room_group.command(name="stop", description="Suspend automatic room creation and stop the background loop")
@app_commands.describe(tournament="Tournament to stop auto rooms for (optional)")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_stop_cmd(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to manage tournament settings.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    all_tournaments = load_guild_tournaments(guild_id)
    target_key = None
    target_cfg = None

    if tournament:
        for k, v in all_tournaments.items():
            if v.get('name', '').lower() == tournament.lower() or k.lower() == tournament.lower():
                target_key = k
                target_cfg = v
                break
    else:
        for k, v in all_tournaments.items():
            if v.get('state') == 'active':
                target_key = k
                target_cfg = v
                break
        if not target_cfg and all_tournaments:
            target_key, target_cfg = next(iter(all_tournaments.items()))

    if target_cfg:
        target_cfg['auto_room_creation'] = False
        all_tournaments[target_key] = target_cfg
        save_guild_tournaments(guild_id, all_tournaments)

    stop_auto_room_loop(guild_id)
    await interaction.response.send_message(f"⏹️ Auto room creation background loop has been stopped for **{target_cfg.get('name') if target_cfg else interaction.guild.name}**.")

@auto_room_group.command(name="status", description="Check auto room creation configuration and loop status")
@app_commands.describe(tournament="Filter by tournament name (optional)")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_status_cmd(interaction: discord.Interaction, tournament: Optional[str] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    guild_id = interaction.guild.id
    all_tournaments = load_guild_tournaments(guild_id)
    is_loop_running = guild_id in auto_room_loops and not auto_room_loops[guild_id].done()

    embed = discord.Embed(
        title="⚙️ Auto Room Creation Status",
        description=f"Server: **{interaction.guild.name}**\nBackground Loop Running: **{'Yes ✅' if is_loop_running else 'No ❌'}**",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    for k, t in all_tournaments.items():
        if tournament and tournament.lower() not in t.get('name', '').lower() and tournament.lower() not in k.lower():
            continue
        t_name = t.get('name', k)
        auto_enabled = "Enabled ✅" if t.get('auto_room_creation') else "Disabled ❌"
        bracket = t.get('challonge_bracket_link') or "Not Set"
        sheet = t.get('captains_sheet_link') or t.get('sheet_link') or "Not Set"
        
        cats = []
        for i in range(1, 5):
            c_id = t.get(f'ticket_open_category_{i}') or t.get(f'Open_Category_{i}_ID')
            if c_id:
                cats.append(f"<#{c_id}>")
        cats_str = ", ".join(cats) if cats else "None"

        val = (
            f"• **Auto Room:** `{auto_enabled}`\n"
            f"• **Bracket:** `{bracket}`\n"
            f"• **Sheet:** `{'Configured' if sheet != 'Not Set' else 'Not Set'}`\n"
            f"• **Open Categories:** {cats_str}"
        )
        embed.add_field(name=f"🏆 {t_name}", value=val, inline=False)

    embed.set_footer(text=f"{interaction.guild.name} • Auto Room Status")
    await interaction.response.send_message(embed=embed)


# ===========================================================================================
# CLEAR / PURGE CATEGORY COMMAND GROUP
# ===========================================================================================

class ConfirmClearCategoryView(discord.ui.View):
    def __init__(self, author_id: int, category: discord.CategoryChannel):
        super().__init__(timeout=60.0)
        self.author_id = author_id
        self.category = category
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Only the command author can confirm this action.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm & Delete All Channels", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ Clear category operation cancelled.", embed=None, view=self)


clear_group = app_commands.Group(name="clear", description="Clear and bulk-delete ticket channels or categories")

@clear_group.command(name="category", description="Bulk delete all open or closed ticket channels in a specified category")
@app_commands.describe(
    category="The category containing the ticket channels to delete",
    keep_category="Keep the category container itself and only delete channels inside it (default: True)"
)
@with_guild_context
async def clear_category_cmd(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
    keep_category: Optional[bool] = True
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to clear categories (Organizer only).", ephemeral=True)
        return

    channels_to_delete = list(category.channels)
    if not channels_to_delete:
        await interaction.response.send_message(f"ℹ️ Category **{category.name}** is already empty (0 channels).", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚠️ Bulk Delete Category Channels Confirmation",
        description=(
            f"Are you sure you want to delete **all {len(channels_to_delete)} channel(s)** in category **{category.name}**?\n\n"
            f"⚠️ **Warning:** This action is permanent and cannot be undone! Any chat logs or open match tickets in these channels will be removed."
        ),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="📁 Target Category", value=f"{category.name} (`{category.id}`)", inline=True)
    embed.add_field(name="📊 Channels to Delete", value=f"**{len(channels_to_delete)}** channel(s)", inline=True)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")

    view = ConfirmClearCategoryView(interaction.user.id, category)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    await view.wait()
    if not view.confirmed:
        return

    status_msg = await interaction.followup.send(f"⏳ Bulk deleting {len(channels_to_delete)} channel(s) in **{category.name}**... Please wait.")

    deleted_count = 0
    failed_count = 0

    for idx, channel in enumerate(channels_to_delete):
        try:
            for ev_id, ev_data in list(scheduled_events.items()):
                if ev_data.get('channel_id') == channel.id:
                    ev_data['status'] = 'deleted'
            await channel.delete(reason=f"Bulk category clear by {interaction.user.name}")
            deleted_count += 1
            if (idx + 1) % 5 == 0 or (idx + 1) == len(channels_to_delete):
                try:
                    await status_msg.edit(content=f"⏳ Deleted **{deleted_count}/{len(channels_to_delete)}** channel(s)...")
                except Exception:
                    pass
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"Error deleting channel {channel.name}: {e}")
            failed_count += 1

    save_scheduled_events()

    if not keep_category:
        try:
            await category.delete(reason=f"Category deleted by {interaction.user.name}")
        except Exception as e:
            print(f"Error deleting category itself: {e}")

    log_embed = discord.Embed(
        title="🗑️ Category Channels Bulk Deleted",
        description=f"**{interaction.user.mention}** bulk deleted **{deleted_count}** channel(s) from category **{category.name}**.",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    if failed_count > 0:
        log_embed.add_field(name="Failed", value=f"{failed_count} channel(s)", inline=True)
    await log_bot_activity(interaction.guild, log_embed)

    result_embed = discord.Embed(
        title="✅ Category Cleared",
        description=f"Successfully deleted **{deleted_count}** channel(s) in category **{category.name}**.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    if failed_count > 0:
        result_embed.add_field(name="⚠️ Failed", value=f"Could not delete {failed_count} channel(s) due to permissions or rate limits.", inline=False)
    result_embed.set_footer(text=f"{ORGANIZATION_NAME} • Category Cleaner")

    await status_msg.edit(content=None, embed=result_embed)

@clear_group.command(name="cache", description="Clear Challonge bracket, sheet, and local memory caches")
@with_guild_context
async def clear_cache_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to clear cache.", ephemeral=True)
        return

    from core.state import GUILD_CONFIG_CACHE, RULES_CACHE, STAFF_STATS_CACHE, TOURNAMENTS_CACHE
    GUILD_CONFIG_CACHE.clear()
    RULES_CACHE.clear()
    STAFF_STATS_CACHE.clear()
    TOURNAMENTS_CACHE.clear()

    await interaction.response.send_message("✅ Successfully cleared all server configuration, tournament, bracket, and sheet caches!", ephemeral=False)


# ===========================================================================================
# TOURNAMENTS COG
# ===========================================================================================

class Tournaments(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        asyncio.create_task(self._init_deadline_tasks())
        asyncio.create_task(self._init_auto_room_loops())

    async def _init_deadline_tasks(self):
        try:
            await self.bot.wait_until_ready()
            for dl_id, dl_data in list(scheduled_deadlines.items()):
                try:
                    schedule_deadline_tasks(self.bot, dl_id)
                except Exception as e:
                    print(f"Error initializing deadline task {dl_id}: {e}")
        except Exception:
            pass

    async def _init_auto_room_loops(self):
        try:
            await self.bot.wait_until_ready()
            for guild in self.bot.guilds:
                try:
                    tourns = load_guild_tournaments(guild.id)
                    if any(t.get('auto_room_creation') for t in tourns.values()):
                        start_auto_room_loop(self.bot, guild.id)
                except Exception as e:
                    print(f"Error initializing auto_room loop for guild {guild.id}: {e}")
        except Exception:
            pass



    @app_commands.command(name="add_captain", description="Add two captains to a tournament match and rename the channel")
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
    async def add_captain_cmd(
        self,
        interaction: discord.Interaction, 
        round: str, 
        captain1: discord.Member, 
        captain2: discord.Member, 
        bracket: str = None,
        team_1: str = None,
        team_2: str = None
    ):
        try:
            if not has_event_create_permission(interaction):
                await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=False)
                return
            
            valid_rounds = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10", "Q", "SF", "3rd Place", "Final"]
            if round not in valid_rounds:
                await interaction.response.send_message("❌ Invalid round. Please select R1-R10, Q, SF, 3rd Place, or Final.", ephemeral=False)
                return
            
            channel = interaction.channel
            t1_name = team_1 if team_1 else captain1.name
            t2_name = team_2 if team_2 else captain2.name
            
            if bracket:
                new_name = f"{bracket}-{round.lower()}-{t1_name.lower()}-vs-{t2_name.lower()}"
            else:
                new_name = f"{round.lower()}-{t1_name.lower()}-vs-{t2_name.lower()}"
            
            new_name = re.sub(r'[^a-zA-Z0-9\-]', '-', new_name)
            new_name = re.sub(r'-+', '-', new_name).strip('-')
            if len(new_name) > 100:
                new_name = new_name[:100]
            
            try:
                await channel.edit(name=new_name)
                await interaction.response.send_message(f"✅ Channel renamed to `{new_name}`", ephemeral=False)
            except discord.Forbidden:
                await interaction.response.send_message("❌ I don't have permission to rename this channel.", ephemeral=False)
                return
            
            try:
                await channel.set_permissions(captain1, view_channel=True, send_messages=True)
                await channel.set_permissions(captain2, view_channel=True, send_messages=True)
            except Exception as e:
                print(f"Error setting captain permissions: {e}")
            
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
            await channel.send(embed=rules_embed)

        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=False)

    @app_commands.command(name="upload-score", description="Upload match score to Challonge bracket (Judge/Organizer only)")
    @app_commands.describe(
        winner="Select the match and the winning team from the list",
        winner_score="Score of the winning team (e.g. 2)",
        loser_score="Score of the losing team (e.g. 1)"
    )
    @with_guild_context
    async def upload_score_cmd(
        self,
        interaction: discord.Interaction,
        winner: str,
        winner_score: int,
        loser_score: int
    ):
        await interaction.response.defer(ephemeral=False)

        permission_level = get_user_permission_level(interaction.user.roles, interaction.user.id)
        if permission_level not in ["organizer", "owner"]:
            await interaction.followup.send("❌ You need **Head Organizer** role to upload scores.", ephemeral=False)
            return

        try:
            parts = winner.split(":")
            if len(parts) < 3:
                await interaction.followup.send("❌ Invalid selection. Please select a match from the autocomplete dropdown list.", ephemeral=False)
                return
            match_id = parts[0]
            winner_participant_id = parts[1]
            winner_name = parts[2]
            player1_id = str(parts[3]) if len(parts) >= 4 else None
        except Exception:
            await interaction.followup.send("❌ Error parsing the selection. Please use the autocomplete list.", ephemeral=False)
            return

        t_cfg = get_active_tournament_config(interaction.guild.id) if interaction.guild else None
        bracket_link = t_cfg.get('challonge_bracket_link') or t_cfg.get('id') if t_cfg else get_bracket_link(interaction)
        api_key = t_cfg.get('key') if t_cfg else get_bracket_api_key(interaction)

        if not bracket_link or not str(bracket_link).startswith("http"):
            await interaction.followup.send("❌ No bracket link configured. Set one in tournament configuration.", ephemeral=False)
            return
        if not api_key:
            await interaction.followup.send("❌ No Challonge API key configured. Set one in tournament configuration.", ephemeral=False)
            return

        if player1_id and str(winner_participant_id) == str(player1_id):
            scores_csv = f"{winner_score}-{loser_score}"
        elif player1_id:
            scores_csv = f"{loser_score}-{winner_score}"
        else:
            scores_csv = f"{winner_score}-{loser_score}"

        try:
            success, error = await update_challonge_match(
                bracket_link, api_key, match_id, winner_participant_id, scores_csv
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Error uploading score: `{e}`", ephemeral=False)
            return

        tournament_name = t_cfg.get('name') if t_cfg else get_tournament_name(interaction) or ""

        if success:
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
            await interaction.followup.send(embed=embed, ephemeral=False)

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
            await interaction.followup.send(f"❌ Challonge rejected the score upload:\n```{error[:500] if error else 'Unknown error'}```", ephemeral=False)

    @app_commands.command(name="close", description="Close the current match ticket room, generate transcripts, and move to closed category")
    @with_guild_context
    async def close_room_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ This command can only be used in server text channels.", ephemeral=True)
            return

        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to close tickets.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        message_channel = interaction.channel

        try:
            messages_list = []
            async for m in message_channel.history(limit=2000, oldest_first=True):
                messages_list.append(m)

            guild = interaction.guild
            clean_chan_name = re.sub(r'[^a-zA-Z0-9_\-]', '', message_channel.name).lower() or "ticket"
            html_content = generate_html_transcript(message_channel, messages_list, guild, closed_by=interaction.user)
            text_content = generate_text_transcript(message_channel, messages_list, guild, closed_by=interaction.user)

            html_filename = f"transcript_{clean_chan_name}.html"
            text_filename = f"transcript_{clean_chan_name}.txt"

            html_file_local = discord.File(io.BytesIO(html_content.encode('utf-8')), filename=html_filename)
            text_file_local = discord.File(io.BytesIO(text_content.encode('utf-8')), filename=text_filename)

            attachment_count = sum(len(m.attachments) for m in messages_list)

            await interaction.followup.send(
                f"📄 **Transcript of `{message_channel.name}`** ({len(messages_list)} messages, {attachment_count} attachments):\n"
                f"• Open the `.html` file in any browser for full Discord chat with images & embeds!\n"
                f"• Open the `.txt` file for a text log with image URLs.",
                files=[html_file_local, text_file_local]
            )

            # Resolve transcript log channel
            transcript_channel = None
            t_cfg = get_active_tournament_config(guild.id)
            if t_cfg:
                for k in ['transcript', 'transcript_logs', 'transcript_channel_id', 'Transcript_Channel_ID']:
                    if t_cfg.get(k):
                        try:
                            transcript_channel = guild.get_channel(int(t_cfg[k])) or await guild.fetch_channel(int(t_cfg[k]))
                            if transcript_channel: break
                        except Exception: pass

            if not transcript_channel:
                tournaments = load_guild_tournaments(guild.id)
                for _, tdata in tournaments.items():
                    for k in ['transcript', 'transcript_logs', 'transcript_channel_id', 'Transcript_Channel_ID']:
                        if tdata.get(k):
                            try:
                                transcript_channel = guild.get_channel(int(tdata[k])) or await guild.fetch_channel(int(tdata[k]))
                                if transcript_channel: break
                            except Exception: pass
                    if transcript_channel: break

            if not transcript_channel:
                cfg = get_guild_config(guild.id)
                for k in ['transcript_logs', 'transcript', 'transcript_channel_id', 'Transcript_Channel_ID']:
                    t_id = cfg.get('channel_ids', {}).get(k) or cfg.get(k)
                    if t_id:
                        try:
                            transcript_channel = guild.get_channel(int(t_id)) or await guild.fetch_channel(int(t_id))
                            if transcript_channel: break
                        except Exception: pass

            if transcript_channel:
                html_file_rec = discord.File(io.BytesIO(html_content.encode('utf-8')), filename=html_filename)
                text_file_rec = discord.File(io.BytesIO(text_content.encode('utf-8')), filename=text_filename)

                summary_embed = discord.Embed(
                    title=f"📋 Ticket Closed: #{message_channel.name}",
                    description=(
                        f"**Closed by:** {interaction.user.mention}\n"
                        f"**Total Messages:** `{len(messages_list)}`\n"
                        f"**Attachments / Images:** `{attachment_count}`\n"
                        f"**Participants:** `{len(set(m.author.id for m in messages_list))}`\n"
                        f"**Closed At:** <t:{int(datetime.datetime.utcnow().timestamp())}:F>\n\n"
                        f"📁 *HTML & Text transcripts attached below.*"
                    ),
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                summary_embed.set_footer(text=f"{ORGANIZATION_NAME} • Ticket Transcripts")
                await transcript_channel.send(embed=summary_embed, files=[html_file_rec, text_file_rec])

            # Resolve closed tickets category
            closed_category = None
            if t_cfg:
                for k in ['closed_ticket_1', 'closed_ticket_2', 'closed_tickets_category', 'closed_category']:
                    if t_cfg.get(k):
                        try:
                            closed_category = guild.get_channel(int(t_cfg[k]))
                            if closed_category: break
                        except Exception: pass
            if not closed_category:
                tournaments = load_guild_tournaments(guild.id)
                for _, tdata in tournaments.items():
                    for k in ['closed_ticket_1', 'closed_ticket_2', 'closed_tickets_category', 'closed_category']:
                        if tdata.get(k):
                            try:
                                closed_category = guild.get_channel(int(tdata[k]))
                                if closed_category: break
                            except Exception: pass
                    if closed_category: break
            if not closed_category:
                cfg = get_guild_config(guild.id)
                for k in ['closed_tickets_category', 'closed_category']:
                    c_id = cfg.get('channel_ids', {}).get(k) or cfg.get(k)
                    if c_id:
                        try:
                            closed_category = guild.get_channel(int(c_id))
                            if closed_category: break
                        except Exception: pass

            if closed_category:
                await message_channel.edit(
                    category=closed_category,
                    sync_permissions=True,
                    reason=f"Ticket closed by {interaction.user.name}"
                )
                await message_channel.send("🔒 Ticket closed and moved to closed category. Use `$delete` (or `/delete_room`) to permanently delete it.")
            else:
                await message_channel.send("🔒 Ticket closed.")
        except Exception as e:
            print(f"Error closing ticket via slash command: {e}")
            await interaction.followup.send(f"❌ Failed to close ticket: {e}")

    @app_commands.command(name="delete_room", description="Permanently delete the current ticket channel")
    @with_guild_context
    async def delete_room_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ This command can only be used in server text channels.", ephemeral=True)
            return

        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to delete ticket rooms.", ephemeral=True)
            return

        await interaction.response.send_message("🗑️ Deleting this ticket channel in 3 seconds...")
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user.name}")
        except Exception as e:
            print(f"Error deleting channel: {e}")



async def setup(bot: commands.Bot):
    bot.tree.add_command(tournament_group)
    bot.tree.add_command(link_group)
    bot.tree.add_command(deadline_group)
    bot.tree.add_command(auto_room_group)
    bot.tree.add_command(clear_group)
    await bot.add_cog(Tournaments(bot))



