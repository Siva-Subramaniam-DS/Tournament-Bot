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
    scheduled_deadlines, reminder_tasks, get_default_tournament_data
)
from core.database import (
    supabase_client, load_guild_tournaments, save_guild_tournaments,
    get_guild_config, get_active_tournament_config,
    save_event_to_supabase, log_bot_activity, sheetdb_post,
    update_challonge_match, get_challonge_matches, get_challonge_participants,
    get_guild_staff_stats, save_guild_staff_stats, update_staff_stats,
    update_results_embed_with_links
)


from core.image_generator import get_random_template, get_thumbnail_url_from_channel

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
# TOURNAMENTS COG
# ===========================================================================================

class Tournaments(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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


async def setup(bot: commands.Bot):
    bot.tree.add_command(tournament_group)
    bot.tree.add_command(link_group)
    await bot.add_cog(Tournaments(bot))
