import os
import io
import re
import csv
import json
import asyncio
import datetime
from typing import Optional, List, Union
import requests

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
    auto_room_loops, auto_room_locks, get_default_tournament_data,
    category_monitors, CHALLONGE_MATCHES_CACHE
)

from core.database import (
    supabase_client, load_guild_tournaments, save_guild_tournaments,
    get_guild_config, get_active_tournament_config,
    save_event_to_supabase, log_bot_activity, sheetdb_post,
    update_challonge_match, get_challonge_matches, get_challonge_participants,
    get_guild_staff_stats, save_guild_staff_stats, update_staff_stats,
    update_results_embed_with_links, save_scheduled_deadline, delete_scheduled_deadline,
    fetch_challonge_open_matches, fetch_google_sheet_captains, extract_discord_id_from_text
)
from core.emojis import (
    EMOJIS, LEFT_BUTTON_EMOJI, RIGHT_BUTTON_EMOJI,
    CONFIRM_PRESENCE_BUTTON_EMOJI, VERIFIED_BUTTON_EMOJI
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
            if "(" in t_id and "[" in t_id:
                continue
            name = t_cfg.get("name") or t_id
            display = name.strip()
            if not current or current.lower() in display.lower() or current.lower() in t_id.lower():
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

        # Detect if command is adding a link (/link add)
        cmd_name = getattr(interaction.command, 'name', '')
        parent_name = getattr(getattr(interaction.command, 'parent', None), 'name', '')
        data_name = interaction.data.get('name') if isinstance(interaction.data, dict) else ''
        data_options = interaction.data.get('options', []) if isinstance(interaction.data, dict) else []
        subcmd_name = ""
        for opt in data_options:
            if opt.get('type') == 1:
                subcmd_name = opt.get('name', '')
                break

        is_link_add = (
            (parent_name == "link" and cmd_name == "add") or
            (data_name == "link" and subcmd_name == "add") or
            (cmd_name == "add" and hasattr(interaction.namespace, "link_type"))
        )

        selected_link_type = getattr(interaction.namespace, "link_type", None)
        if isinstance(selected_link_type, app_commands.Choice):
            selected_link_type = selected_link_type.value

        guild = interaction.guild or (interaction.client.get_guild(guild_id) if hasattr(interaction, "client") else None)

        def resolve_name(team_val, captain_val, default_name="TBD"):
            val = team_val
            if not val and captain_val:
                val = getattr(captain_val, 'display_name', None) or getattr(captain_val, 'name', None) or str(captain_val)
            val = str(val or default_name).strip()
            if val.isdigit() and guild:
                mem = guild.get_member(int(val))
                if mem:
                    val = mem.display_name or mem.name
            return val

        seen_names = {}

        for ev_id, ev_data in scheduled_events.items():
            if str(ev_data.get('guild_id')) != str(guild_id):
                continue

            # Don't show challonge id and show only whatever event is created
            if ev_id.startswith("challonge_"):
                continue

            if selected_tournament:
                ev_t = str(ev_data.get('tournament') or '').strip().lower()
                ev_t_id = str(ev_data.get('tournament_id') or '').strip().lower()
                sel = str(selected_tournament).strip().lower()

                all_t = load_guild_tournaments(guild_id)
                t_cfg = all_t.get(selected_tournament) or all_t.get(sel)
                if not t_cfg:
                    for tid, cfg in all_t.items():
                        if cfg.get('name', '').strip().lower() == sel or tid.strip().lower() == sel:
                            t_cfg = cfg
                            break

                t_names = [sel]
                if t_cfg:
                    if t_cfg.get('name'): t_names.append(t_cfg['name'].strip().lower())
                    if t_cfg.get('id'): t_names.append(t_cfg['id'].strip().lower())
                    if t_cfg.get('challonge_bracket_link'): t_names.append(t_cfg['challonge_bracket_link'].strip().lower())

                match_found = False
                for candidate in t_names:
                    if candidate and (candidate == ev_t or candidate in ev_t or ev_t in candidate or candidate == ev_t_id or candidate in ev_t_id):
                        match_found = True
                        break
                if not match_found and (ev_t or ev_t_id):
                    continue

            # In /link add: only filter out matches that already have the required link
            if is_link_add:
                if selected_link_type == "recorder":
                    if ev_data.get('recorder_link'):
                        continue
                elif selected_link_type == "judge":
                    if ev_data.get('judge_link'):
                        continue
                elif selected_link_type == "general":
                    if ev_data.get('recording_link'):
                        continue
                else:
                    # By default in link add, skip only if all recording links already exist
                    if ev_data.get('recording_link') and ev_data.get('recorder_link') and ev_data.get('judge_link'):
                        continue

            t1_val = resolve_name(ev_data.get('team1_name'), ev_data.get('team1_captain'), "Team 1")
            t2_val = resolve_name(ev_data.get('team2_name'), ev_data.get('team2_captain'), "Team 2")

            # Clean match name only - no event ID, no match number
            base_name = f"{t1_val} vs {t2_val}"
            if len(base_name) > 100:
                base_name = base_name[:97] + "..."

            if not current or current_lower in base_name.lower() or current_lower in ev_id.lower():
                choice_name = base_name
                if choice_name in seen_names:
                    seen_names[choice_name] += 1
                    choice_name = f"{choice_name} ({seen_names[choice_name]})"[:100]
                else:
                    seen_names[choice_name] = 1

                choices.append(app_commands.Choice(name=choice_name, value=ev_id))

        return choices[:25]
    except Exception as e:
        print(f"Error in match_autocomplete: {e}")
        return []

async def upload_score_winner_autocomplete(
    interaction: discord.Interaction,
    current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    
    try:
        current_guild_id.set(interaction.guild.id)
        guild_id = interaction.guild.id
        
        t_cfg = get_active_tournament_config(guild_id)
        if not t_cfg:
            tournaments = load_guild_tournaments(guild_id)
            if len(tournaments) == 1:
                t_cfg = next(iter(tournaments.values()))
            else:
                for tid, cfg in tournaments.items():
                    if (cfg.get('challonge_bracket_link') or cfg.get('id')) and cfg.get('key'):
                        t_cfg = cfg
                        break

        bracket_link = (t_cfg.get('challonge_bracket_link') or t_cfg.get('id')) if t_cfg else get_bracket_link(interaction)
        api_key = t_cfg.get('key') if t_cfg else get_bracket_api_key(interaction)
        
        if not bracket_link or not api_key:
            return []
            
        now = datetime.datetime.now()
        matches = []
        cached = CHALLONGE_MATCHES_CACHE.get(guild_id)
        if cached and (now - cached[0]).total_seconds() < 20:
            matches = cached[1]
        else:
            matches_info, err = await fetch_challonge_open_matches(bracket_link, api_key)
            if matches_info:
                matches = matches_info
                CHALLONGE_MATCHES_CACHE[guild_id] = (now, matches)
            else:
                print(f"[Challonge Autocomplete] Error: {err}")
                
        if not matches:
            return []
            
        choices = []
        current_lower = current.lower() if current else ""
        
        # Check if we are inside a ticket channel and can extract the match ID
        channel_match_id = None
        if interaction.channel and hasattr(interaction.channel, 'topic') and interaction.channel.topic:
            topic = interaction.channel.topic
            m_match = re.search(r'MatchID:([a-zA-Z0-9-_]+)', topic)
            if m_match:
                channel_match_id = m_match.group(1)

        # Fallback 1: check scheduled_events for this channel
        if not channel_match_id and interaction.channel:
            c_id = interaction.channel.id
            for ev_id, ev_data in scheduled_events.items():
                if ev_data.get('channel_id') == c_id:
                    if ev_data.get('match_id'):
                        channel_match_id = str(ev_data.get('match_id'))
                        break

        # Fallback 2: check channel name for team names
        if not channel_match_id and interaction.channel and hasattr(interaction.channel, 'name'):
            c_name = interaction.channel.name.lower()
            if "-vs-" in c_name or " vs " in c_name:
                for m in matches:
                    t1_str = str(m.get('team1') or "").lower()
                    t2_str = str(m.get('team2') or "").lower()
                    if t1_str and t2_str and (t1_str in c_name and t2_str in c_name):
                        channel_match_id = str(m.get('id'))
                        break

        added_match_ids = set()

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
                round_name = target_match.get('round_name', f"Round {target_match.get('round')}")
                
                # Show simple team/player names
                # Value format: match_id:winner_participant_id:team_name:player1_id
                opt1_name = f"{team1} ({round_name})"
                opt1_val = f"{match_id}:{p1_id}:{team1}:{p1_id}"
                if not current_lower or current_lower in opt1_name.lower() or current_lower in team1.lower():
                    choices.append(app_commands.Choice(name=opt1_name[:100], value=opt1_val[:100]))
                    
                opt2_name = f"{team2} ({round_name})"
                opt2_val = f"{match_id}:{p2_id}:{team2}:{p1_id}"
                if not current_lower or current_lower in opt2_name.lower() or current_lower in team2.lower():
                    choices.append(app_commands.Choice(name=opt2_name[:100], value=opt2_val[:100]))
                
                # In a match room, only show the teams of this specific match to avoid confusion
                return choices

        # Fallback/General search: show teams with opponents and round
        for m in matches:
            match_id = m.get('id')
            if str(match_id) in added_match_ids:
                continue
                
            team1 = m.get('team1') or "TBD"
            team2 = m.get('team2') or "TBD"
            p1_id = m.get('player1_id')
            p2_id = m.get('player2_id')
            round_name = m.get('round_name', f"Round {m.get('round')}")
            
            opt1_name = f"{team1} (vs {team2}) - {round_name}"
            opt1_val = f"{match_id}:{p1_id}:{team1}:{p1_id}"
            if not current_lower or current_lower in opt1_name.lower() or current_lower in team1.lower():
                choices.append(app_commands.Choice(name=opt1_name[:100], value=opt1_val[:100]))
                
            opt2_name = f"{team2} (vs {team1}) - {round_name}"
            opt2_val = f"{match_id}:{p2_id}:{team2}:{p1_id}"
            if not current_lower or current_lower in opt2_name.lower() or current_lower in team2.lower():
                choices.append(app_commands.Choice(name=opt2_name[:100], value=opt2_val[:100]))
                
            if len(choices) >= 25:
                break
                
        return choices[:25]
    except Exception as e:
        print(f"Error in upload_score_winner_autocomplete: {e}")
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
    is_edit = "Edit" in action_title
    title_emoji = EMOJIS.get('gear', '⚙️') if is_edit else EMOJIS.get('trophy', '🏆')
    embed = discord.Embed(
        title=f"{title_emoji} {action_title}: {t_data['name']}",
        description="A tournament configuration has been updated/registered on this server." if is_edit else "A new tournament has been registered on this server.",
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
                def _process_thumbnail(p):
                    with Image.open(p) as img:
                        img.thumbnail((200, 200), Image.Resampling.LANCZOS)
                        tb = io.BytesIO()
                        fmt = img.format if img.format else "PNG"
                        img.save(tb, format=fmt)
                        tb.seek(0)
                    e = os.path.splitext(p)[1].lower() or ".png"
                    return tb, f"thumbnail{e}"

                thumb_bytes, file_name = await asyncio.to_thread(_process_thumbnail, template_path)
                if thumb_bytes:
                    embed.set_thumbnail(url=f"attachment://{file_name}")
                    file = discord.File(fp=thumb_bytes, filename=file_name)
                    thumb_str = f"Template: {os.path.basename(template_path)} (Channel: {chan_mention('thumbnail')})"
                else:
                    thumb_str = f"Default (Channel: {chan_mention('thumbnail')})"
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
    attendance_channel="Channel for staff check-ins",
    rules_channel="Channel for tournament rules",
    deadline_channel="Channel for round deadlines",
    challonge_logs="Channel for Challonge bracket logs",
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
    attendance_channel: Optional[discord.TextChannel] = None,
    rules_channel: Optional[discord.TextChannel] = None,
    deadline_channel: Optional[discord.TextChannel] = None,
    challonge_logs: Optional[discord.TextChannel] = None,
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
    if attendance_channel:  t_data["attendance"] = attendance_channel.id
    if rules_channel:       t_data["rules"] = rules_channel.id
    if deadline_channel:    t_data["deadline"] = deadline_channel.id
    if challonge_logs:      t_data["challonge_logs"] = challonge_logs.id
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
    attendance_channel="Attendance channel",
    rules_channel="Rules channel",
    deadline_channel="Deadline channel",
    challonge_logs="Challonge logs channel",
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
    attendance_channel: Optional[discord.TextChannel] = None,
    rules_channel: Optional[discord.TextChannel] = None,
    deadline_channel: Optional[discord.TextChannel] = None,
    challonge_logs: Optional[discord.TextChannel] = None,
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
    if attendance_channel: t_data["attendance"] = attendance_channel.id
    if rules_channel:      t_data["rules"] = rules_channel.id
    if deadline_channel:   t_data["deadline"] = deadline_channel.id
    if challonge_logs:     t_data["challonge_logs"] = challonge_logs.id
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
            delete_scheduled_deadline(dl_id)

    if supabase_client:
        try:
            supabase_client.table("Matches").delete().eq("Guild_ID", str(interaction.guild_id)).eq("Tournament_ID", t_id_clean).execute()
            supabase_client.table("Tournaments").delete().eq("Guild_ID", str(interaction.guild_id)).eq("Tournament_ID", t_id_clean).execute()
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
        title=f"{EMOJIS.get('trophy', '🏆')} Server Tournaments [{len(tournaments)}]",
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

    @discord.ui.button(emoji=LEFT_BUTTON_EMOJI, style=discord.ButtonStyle.primary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
        await self.update_page(interaction)

    @discord.ui.button(emoji=RIGHT_BUTTON_EMOJI, style=discord.ButtonStyle.primary)
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
        title=f"{EMOJIS['recorder']} {link_label} Added",
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
        title=f"{EMOJIS['recorder']} {link_type.name} Updated",
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
        title=f"{EMOJIS['recorder']} Recording Link Deleted",
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

        # Don't show challonge id and show only whatever event is created
        if ev_id.startswith("challonge_"):
            continue

        if tournament:
            ev_t = str(ev_data.get('tournament') or '').strip().lower()
            ev_t_id = str(ev_data.get('tournament_id') or '').strip().lower()
            sel = str(tournament).strip().lower()

            all_t = load_guild_tournaments(interaction.guild.id)
            t_cfg = all_t.get(tournament) or all_t.get(sel)
            if not t_cfg:
                for tid, cfg in all_t.items():
                    if cfg.get('name', '').strip().lower() == sel or tid.strip().lower() == sel:
                        t_cfg = cfg
                        break

            t_names = [sel]
            if t_cfg:
                if t_cfg.get('name'): t_names.append(t_cfg['name'].strip().lower())
                if t_cfg.get('id'): t_names.append(t_cfg['id'].strip().lower())

            match_found = any(c and (c == ev_t or c in ev_t or ev_t in c or c == ev_t_id or c in ev_t_id) for c in t_names)
            if not match_found and (ev_t or ev_t_id):
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
                name=f"📌 {m_name}",
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
    try:
        g_id = interaction.guild_id
        choices = []
        current_lower = (current or "").strip().lower()
        for dl_id, dl_data in list(scheduled_deadlines.items()):
            if not isinstance(dl_data, dict):
                continue
            dl_gid = dl_data.get('guild_id')
            if dl_gid is None or str(dl_gid) == str(g_id):
                rnd = str(dl_data.get('round', 'Unknown'))
                t_name = str(dl_data.get('tournament', ''))
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
                note_str = str(dl_data.get('note', ''))
                
                parts = []
                if t_name:
                    parts.append(t_name)
                parts.append(rnd)
                if dt_str:
                    parts.append(f"({dt_str})")
                label = " - ".join(parts).strip() if parts else str(dl_id)
                if not label:
                    label = str(dl_id)
                
                search_target = f"{label} {dl_id} {rnd} {t_name} {note_str}".lower()
                if not current_lower or current_lower in search_target:
                    choices.append(app_commands.Choice(name=label[:100], value=dl_id[:100]))
        return choices[:25]
    except Exception as e:
        print(f"Error in deadline_autocomplete: {e}")
        return []


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

    target_dl_id = deadline.strip()
    dl_data = scheduled_deadlines.get(target_dl_id)
    if not dl_data:
        g_id = str(interaction.guild.id)
        dl_term = deadline.strip().lower()
        for d_id, d_data in scheduled_deadlines.items():
            if not isinstance(d_data, dict):
                continue
            if not d_data.get('guild_id') or str(d_data.get('guild_id')) == g_id:
                r_name = str(d_data.get('round', '')).strip().lower()
                t_name = str(d_data.get('tournament', '')).strip().lower()
                if (dl_term in d_id.lower() or
                    dl_term == r_name or
                    dl_term in r_name or
                    r_name in dl_term or
                    (t_name and dl_term in t_name)):
                    target_dl_id = d_id
                    dl_data = d_data
                    break

    if not dl_data:
        await interaction.response.send_message("❌ Deadline not found. Please check `/deadline list` or type the round name (e.g. `1` or `Round 1`).", ephemeral=True)
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

    save_scheduled_deadline(target_dl_id, dl_data)
    schedule_deadline_tasks(interaction.client, target_dl_id)

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

    target_dl_id = deadline.strip()
    dl_data = scheduled_deadlines.get(target_dl_id)
    if not dl_data:
        g_id = str(interaction.guild.id)
        dl_term = deadline.strip().lower()
        for d_id, d_data in scheduled_deadlines.items():
            if not isinstance(d_data, dict):
                continue
            if not d_data.get('guild_id') or str(d_data.get('guild_id')) == g_id:
                r_name = str(d_data.get('round', '')).strip().lower()
                t_name = str(d_data.get('tournament', '')).strip().lower()
                if (dl_term in d_id.lower() or
                    dl_term == r_name or
                    dl_term in r_name or
                    r_name in dl_term or
                    (t_name and dl_term in t_name)):
                    target_dl_id = d_id
                    dl_data = d_data
                    break

    if not dl_data:
        await interaction.response.send_message("❌ Deadline not found. Please check `/deadline list` or type the round name (e.g. `1` or `Round 1`).", ephemeral=True)
        return

    round_name = dl_data.get('round', 'Unknown')
    cancel_deadline_tasks(target_dl_id)
    delete_scheduled_deadline(target_dl_id)

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
# MATCH ROOM EMBED BUILDER & AUTO ROOM CREATION
# ===========================================================================================

class MatchReadyView(discord.ui.View):
    def __init__(self, team1_name: str, team2_name: str, captain1_id: Optional[int] = None, captain2_id: Optional[int] = None):
        super().__init__(timeout=None)
        self.team1_name = team1_name or "Team 1"
        self.team2_name = team2_name or "Team 2"
        self.captain1_id = captain1_id
        self.captain2_id = captain2_id
        self.team1_ready = False
        self.team2_ready = False

    @discord.ui.button(label="Team 1 Ready", emoji=CONFIRM_PRESENCE_BUTTON_EMOJI, style=discord.ButtonStyle.primary, custom_id="match_ready_btn_t1")
    async def team1_ready_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_cap1 = (self.captain1_id and interaction.user.id == self.captain1_id)
        if not (is_cap1 or is_admin or is_staff(interaction.user)):
            await interaction.response.send_message(f"❌ Only the captain of **{self.team1_name}** or Staff can mark Team 1 ready.", ephemeral=True)
            return

        self.team1_ready = not self.team1_ready
        if self.team1_ready:
            button.style = discord.ButtonStyle.success
            button.emoji = VERIFIED_BUTTON_EMOJI
            button.label = f"{self.team1_name[:15]} Ready"
            status_text = f"🟢 **{self.team1_name}** ({interaction.user.mention}) is **READY**!"
        else:
            button.style = discord.ButtonStyle.primary
            button.emoji = CONFIRM_PRESENCE_BUTTON_EMOJI
            button.label = f"{self.team1_name[:15]} Ready"
            status_text = f"⚪ **{self.team1_name}** is no longer marked ready."

        await interaction.response.edit_message(view=self)
        await interaction.followup.send(status_text)

        if self.team1_ready and self.team2_ready:
            await interaction.channel.send("🎉 **BOTH TEAMS ARE READY!** Good luck with your match! ⚔️")

    @discord.ui.button(label="Team 2 Ready", emoji=CONFIRM_PRESENCE_BUTTON_EMOJI, style=discord.ButtonStyle.primary, custom_id="match_ready_btn_t2")
    async def team2_ready_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_cap2 = (self.captain2_id and interaction.user.id == self.captain2_id)
        if not (is_cap2 or is_admin or is_staff(interaction.user)):
            await interaction.response.send_message(f"❌ Only the captain of **{self.team2_name}** or Staff can mark Team 2 ready.", ephemeral=True)
            return

        self.team2_ready = not self.team2_ready
        if self.team2_ready:
            button.style = discord.ButtonStyle.success
            button.emoji = VERIFIED_BUTTON_EMOJI
            button.label = f"{self.team2_name[:15]} Ready"
            status_text = f"🟢 **{self.team2_name}** ({interaction.user.mention}) is **READY**!"
        else:
            button.style = discord.ButtonStyle.primary
            button.emoji = CONFIRM_PRESENCE_BUTTON_EMOJI
            button.label = f"{self.team2_name[:15]} Ready"
            status_text = f"⚪ **{self.team2_name}** is no longer marked ready."

        await interaction.response.edit_message(view=self)
        await interaction.followup.send(status_text)

        if self.team1_ready and self.team2_ready:
            await interaction.channel.send("🎉 **BOTH TEAMS ARE READY!** Good luck with your match! ⚔️")

def create_match_room_embed(
    guild: discord.Guild,
    tournament_name: str,
    team1_name: str,
    team2_name: str,
    round_name: str,
    captain1_mention: str,
    captain2_mention: str,
    captain1_ign_or_id: Optional[str] = None,
    captain2_ign_or_id: Optional[str] = None,
    captain1_game_name: Optional[str] = None,
    captain2_game_name: Optional[str] = None,
    group_name: Optional[str] = None,
    match_id: Optional[Union[str, int]] = None,
    rules_channel_id: Optional[Union[int, str]] = None,
    deadline_channel_id: Optional[Union[int, str]] = None,
    rules_link: Optional[str] = None,
    deadline_link: Optional[str] = None,
    helper_role: Optional[discord.Role] = None,
    org_name: Optional[str] = None,
    is_1v1: bool = False,
) -> tuple[str, discord.Embed]:
    """
    Constructs the notification ping content and the rich green 'Match Room Created' embed matching the reference design.
    """
    # 1. Build notification ping content (triggers push notifications & unread badges)
    pings = []
    if captain1_mention and "<@" in str(captain1_mention):
        pings.append(str(captain1_mention).strip())
    if captain2_mention and "<@" in str(captain2_mention):
        pings.append(str(captain2_mention).strip())

    # 2. Resolve clean display titles (Game Name / IGN for 1v1, Team Name for 2v2/3v3/5v5)
    def clean_name_for_title(raw_name: str, ign_val: Optional[str], default_label: str) -> str:
        cand = str(raw_name or "").strip()
        ign_clean = str(ign_val or "").strip() if (ign_val and "<@" not in str(ign_val)) else ""

        # If cand is raw mention <@123...>
        if cand.startswith("<@") and cand.endswith(">"):
            uid = extract_discord_id_from_text(cand)
            if uid and guild:
                mem = guild.get_member(uid)
                if mem:
                    return mem.display_name
            if ign_clean:
                return ign_clean
            return default_label

        if is_1v1:
            if ign_clean and (not cand or cand.lower() in ("team 1", "team 2", "player 1", "player 2", "n/a", "none") or "<@" in cand):
                return ign_clean
            if cand and "<@" not in cand:
                return cand
            if ign_clean:
                return ign_clean
            return default_label
        else:
            if cand and "<@" not in cand:
                return cand
            if ign_clean:
                return ign_clean
            return default_label

    p1_title = clean_name_for_title(team1_name, captain1_ign_or_id, "Player 1" if is_1v1 else "Team 1")
    p2_title = clean_name_for_title(team2_name, captain2_ign_or_id, "Player 2" if is_1v1 else "Team 2")

    ping_content = " ".join(pings) if pings else f"**Match:** {p1_title} vs {p2_title}"

    # 3. Match Room Created Embed (Vibrant green border matching screenshot: #2ECC71)
    embed = discord.Embed(
        title=f"{EMOJIS['player']} Match Room Created",
        color=discord.Color(0x2ECC71)
    )

    t_name = tournament_name or "Tournament"
    grp_str = str(group_name).strip() if (group_name and str(group_name).strip() and str(group_name).lower() != "none") else "N/A"
    c_mentions_line = f"{captain1_mention} {captain2_mention}".strip()

    desc_lines = [
        f"**{p1_title} {EMOJIS['vs']} {p2_title}**\n",
        f"{EMOJIS['trophy']} **Tournament:** {t_name}",
        f"**Group:** {grp_str} | **Round:** {round_name}"
    ]
    if c_mentions_line:
        desc_lines.append(c_mentions_line)

    embed.description = "\n".join(desc_lines)

    # Clean IGN / ID values for fields
    c1_raw_ign = str(captain1_ign_or_id or '').strip()
    c2_raw_ign = str(captain2_ign_or_id or '').strip()
    clean_c1_id = re.sub(r'<@!?\d+>', '', c1_raw_ign).strip()
    clean_c2_id = re.sub(r'<@!?\d+>', '', c2_raw_ign).strip()

    # In field headers: use actual Game Name (IGN) if provided, otherwise fallback to title
    p1_field_title = str(captain1_game_name).strip() if (captain1_game_name and str(captain1_game_name).strip() and "<@" not in str(captain1_game_name)) else p1_title
    p2_field_title = str(captain2_game_name).strip() if (captain2_game_name and str(captain2_game_name).strip() and "<@" not in str(captain2_game_name)) else p2_title

    # Team 1 / Player 1 Field
    p1_label = "Player 1" if is_1v1 else "Team 1"
    if clean_c1_id:
        embed.add_field(
            name=f"{EMOJIS['captain']} **{p1_label}:** {p1_field_title}",
            value=f"{EMOJIS['captain']} Captain: `{clean_c1_id}`",
            inline=False
        )
    elif captain1_mention and "<@" in str(captain1_mention):
        embed.add_field(
            name=f"{EMOJIS['captain']} **{p1_label}:** {p1_field_title}",
            value=f"{EMOJIS['captain']} Captain: {captain1_mention}",
            inline=False
        )
    else:
        embed.add_field(
            name=f"{EMOJIS['captain']} **{p1_label}:** {p1_field_title}",
            value=f"{EMOJIS['captain']} Captain: `N/A`",
            inline=False
        )

    # Team 2 / Player 2 Field
    p2_label = "Player 2" if is_1v1 else "Team 2"
    if clean_c2_id:
        embed.add_field(
            name=f"{EMOJIS['captain']} **{p2_label}:** {p2_field_title}",
            value=f"{EMOJIS['captain']} Captain: `{clean_c2_id}`",
            inline=False
        )
    elif captain2_mention and "<@" in str(captain2_mention):
        embed.add_field(
            name=f"{EMOJIS['captain']} **{p2_label}:** {p2_field_title}",
            value=f"{EMOJIS['captain']} Captain: {captain2_mention}",
            inline=False
        )
    else:
        embed.add_field(
            name=f"{EMOJIS['captain']} **{p2_label}:** {p2_field_title}",
            value=f"{EMOJIS['captain']} Captain: `N/A`",
            inline=False
        )

    # Rules / Deadline / Action Notice
    rules_val = f"<#{rules_channel_id}>" if rules_channel_id else (f"[Rules Channel]({rules_link})" if rules_link else "Not Set")
    deadline_val = f"<#{deadline_channel_id}>" if deadline_channel_id else (f"[Deadline Channel]({deadline_link})" if deadline_link else "Not Set")
    helper_mention = helper_role.mention if helper_role else "@Helper Team"
    helper_badge = EMOJIS.get('helpers', '')
    helper_str = f"{helper_badge} {helper_mention}".strip()

    info_lines = [
        f"📖 **Rules:** {rules_val}",
        f"📅 **Deadline:** {deadline_val}",
        f"{EMOJIS['helpers']} Please decide on a schedule and ping {helper_str}."
    ]
    embed.add_field(
        name="\u200b",
        value="\n".join(info_lines),
        inline=False
    )

    # Footer
    m_id_str = str(match_id) if match_id else "N/A"
    organization = org_name or (get_org_name(guild.id) if guild else "Tournament Bot")
    embed.set_footer(text=f"Match ID: {m_id_str} | {organization}")

    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return ping_content, embed


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
        sheet_link = (
            t_cfg.get('google_sheet_link')
            or t_cfg.get('captains_sheet_link')
            or t_cfg.get('sheet_link')
            or cfg.get('player_info_link')
            or cfg.get('google_sheet_link')
        )
        
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
            
            # Lookup captain in dictionary flexibly (exact, stripped, lowercase, or alphanumeric)
            def get_captain_entry(tname: str):
                if not tname or not captains_dict:
                    return None
                if tname in captains_dict:
                    return captains_dict[tname]
                if tname.strip() in captains_dict:
                    return captains_dict[tname.strip()]
                t_lower = tname.strip().lower()
                if t_lower in captains_dict:
                    return captains_dict[t_lower]
                clean_t = re.sub(r'[^a-zA-Z0-9]', '', tname).lower()
                if clean_t in captains_dict:
                    return captains_dict[clean_t]
                for k, v in captains_dict.items():
                    k_str = str(k).strip().lower()
                    if k_str == t_lower:
                        return v
                    clean_k = re.sub(r'[^a-zA-Z0-9]', '', str(k)).lower()
                    if clean_k and clean_t and (clean_k == clean_t or clean_k in clean_t or clean_t in clean_k):
                        return v
                return None

            c1_entry = get_captain_entry(team1)
            c2_entry = get_captain_entry(team2)

            c1_raw = c1_entry.get('discord') if isinstance(c1_entry, dict) else (c1_entry or "")
            c2_raw = c2_entry.get('discord') if isinstance(c2_entry, dict) else (c2_entry or "")
            c1_uid = c1_entry.get('discord_id') if isinstance(c1_entry, dict) else None
            c2_uid = c2_entry.get('discord_id') if isinstance(c2_entry, dict) else None
            c1_ign = c1_entry.get('ign') if isinstance(c1_entry, dict) else ""
            c2_ign = c2_entry.get('ign') if isinstance(c2_entry, dict) else ""
            c1_game_name = c1_entry.get('game_name') if isinstance(c1_entry, dict) else ""
            c2_game_name = c2_entry.get('game_name') if isinstance(c2_entry, dict) else ""

            if not c1_uid and c1_raw:
                c1_uid = extract_discord_id_from_text(c1_raw)
            if not c2_uid and c2_raw:
                c2_uid = extract_discord_id_from_text(c2_raw)

            async def resolve_member_and_mention(raw: str, uid_hint: Optional[int] = None) -> tuple[Optional[discord.Member], str, Optional[int]]:
                uid = uid_hint
                clean_raw = str(raw).strip() if raw else ""
                
                if not uid and clean_raw:
                    uid = extract_discord_id_from_text(clean_raw)
                    
                if uid:
                    member = guild.get_member(uid)
                    if not member:
                        try:
                            member = await guild.fetch_member(uid)
                        except Exception:
                            member = None
                    mention_str = member.mention if member else f"<@{uid}>"
                    return member, mention_str, uid

                if not clean_raw:
                    return None, "", None

                name_to_search = clean_raw
                if name_to_search.startswith('@'):
                    name_to_search = name_to_search[1:].strip()
                if '#' in name_to_search:
                    parts = name_to_search.split('#', 1)
                    name_to_search = parts[0].strip()

                name_lower = name_to_search.lower()

                # Local guild member cache search
                for member in guild.members:
                    if (member.name.lower() == name_lower or
                        (member.global_name and member.global_name.lower() == name_lower) or
                        member.display_name.lower() == name_lower):
                        return member, member.mention, member.id

                # Query Discord gateway for uncached members
                try:
                    found_members = await guild.query_members(query=name_to_search, limit=5)
                    for member in found_members:
                        if (member.name.lower() == name_lower or
                            (member.global_name and member.global_name.lower() == name_lower) or
                            member.display_name.lower() == name_lower):
                            return member, member.mention, member.id
                    if found_members:
                        member = found_members[0]
                        return member, member.mention, member.id
                except Exception:
                    pass

                return None, clean_raw, None

            captain1, c1_mention, c1_uid = await resolve_member_and_mention(c1_raw, uid_hint=c1_uid)
            captain2, c2_mention, c2_uid = await resolve_member_and_mention(c2_raw, uid_hint=c2_uid)

            # Fallback mention if ID exists
            if not c1_mention or "<@" not in c1_mention:
                if c1_uid:
                    c1_mention = f"<@{c1_uid}>"
                else:
                    found_id = extract_discord_id_from_text(team1) or extract_discord_id_from_text(c1_ign)
                    if found_id:
                        c1_uid = found_id
                        c1_mention = f"<@{found_id}>"

            if not c2_mention or "<@" not in c2_mention:
                if c2_uid:
                    c2_mention = f"<@{c2_uid}>"
                else:
                    found_id = extract_discord_id_from_text(team2) or extract_discord_id_from_text(c2_ign)
                    if found_id:
                        c2_uid = found_id
                        c2_mention = f"<@{found_id}>"

            # Fallback IGN / ID values
            if not c1_ign:
                c1_ign = captain1.name if captain1 else (c1_raw or team1)
            if not c2_ign:
                c2_ign = captain2.name if captain2 else (c2_raw or team2)
            
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
                # Overflow check: search other match categories in the server
                for c in guild.categories:
                    if c not in categories and len(c.channels) < 49 and any(kw in c.name.lower() for kw in ['match', 'ticket', 'open', 'round']):
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

                if c1_uid:
                    c1_target = captain1 or discord.Object(id=c1_uid)
                    overwrites[c1_target] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                elif captain1:
                    overwrites[captain1] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

                if c2_uid:
                    c2_target = captain2 or discord.Object(id=c2_uid)
                    overwrites[c2_target] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                elif captain2:
                    overwrites[captain2] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    
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
                    'team1_captain': captain1.id if captain1 else (c1_uid if c1_uid else None),
                    'team2_captain': captain2.id if captain2 else (c2_uid if c2_uid else None),
                    'team1_name': team1,
                    'team2_name': team2
                }
                save_scheduled_events()
                try:
                    await save_event_to_supabase(event_id, scheduled_events[event_id])
                except Exception as db_err:
                    print(f"Error syncing auto-room event to Supabase: {db_err}")
                
                rules_ch_id = t_cfg.get('rules')
                deadline_ch_id = t_cfg.get('deadline')
                org_name = cfg.get('organization_name') or get_org_name(guild.id)

                ping_content, room_embed = create_match_room_embed(
                    guild=guild,
                    tournament_name=t_cfg.get('name', 'Tournament'),
                    team1_name=team1,
                    team2_name=team2,
                    round_name=round_name,
                    captain1_mention=c1_mention,
                    captain2_mention=c2_mention,
                    captain1_ign_or_id=c1_ign,
                    captain2_ign_or_id=c2_ign,
                    captain1_game_name=c1_game_name,
                    captain2_game_name=c2_game_name,
                    group_name=None,
                    match_id=match_id,
                    rules_channel_id=rules_ch_id,
                    deadline_channel_id=deadline_ch_id,
                    rules_link=rules_link,
                    deadline_link=deadline_link,
                    helper_role=helper_team_role,
                    org_name=org_name,
                    is_1v1=is_1v1
                )
                
                await new_ch.send(content=ping_content, embed=room_embed)
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

        # Check Category Monitors for Capacity
        for cat in categories:
            cat_key = f"{guild.id}:{cat.id}"
            if cat_key in category_monitors:
                mon = category_monitors[cat_key]
                thresh = mon.get("threshold", 45)
                if len(cat.channels) >= thresh:
                    try:
                        p_id = mon.get("ping_target_id")
                        is_r = mon.get("is_role", False)
                        p_mention = f"<@&{p_id}>" if is_r else f"<@{p_id}>"
                        ch_id = mon.get("alert_channel_id")
                        alert_ch = guild.get_channel(ch_id) or guild.system_channel
                        if alert_ch:
                            warn_embed = discord.Embed(
                                title="⚠️ Category Capacity Alert",
                                description=f"Category **{cat.name}** has reached **{len(cat.channels)} / 50** channels (Threshold: `{thresh}`).\nPlease clear or rotate ticket categories before hitting Discord's 50-channel limit.",
                                color=discord.Color.orange(),
                                timestamp=discord.utils.utcnow()
                            )
                            warn_embed.set_footer(text=f"{guild.name} • Category Monitor")
                            await alert_ch.send(content=f"🔔 {p_mention}", embed=warn_embed)
                    except Exception as mon_err:
                        print(f"Error sending category monitor alert: {mon_err}")

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
        title=f"{EMOJIS.get('gear', '⚙️')} Automatic Room Creation",
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
        title=f"{EMOJIS.get('loading', '🎫')} Auto Room Sweep Complete",
        description=f"Created **{created_count}** new match room ticket(s) for **{target_cfg.get('name')}**.",
        color=discord.Color.green() if created_count > 0 else discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    if created_count == 0:
        embed.description = f"🎉 All open matches for **{target_cfg.get('name')}** already have tickets created!"
    embed.set_footer(text=f"{interaction.guild.name} • Auto Room System")
    await msg.edit(content=None, embed=embed)

@auto_room_group.command(name="start", description="Start automatic room creation and the background loop")
@app_commands.describe(tournament="Tournament to start auto rooms for (optional)")
@app_commands.autocomplete(tournament=tournament_autocomplete)
@with_guild_context
async def auto_room_start_cmd(interaction: discord.Interaction, tournament: Optional[str] = None):
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

    target_cfg['auto_room_creation'] = True
    all_tournaments[target_key] = target_cfg
    save_guild_tournaments(guild_id, all_tournaments)

    start_auto_room_loop(interaction.client, guild_id)

    embed = discord.Embed(
        title="⚙️ Automatic Room Creation",
        description=f"Auto room creation for **{target_cfg.get('name')}** is now **ENABLED ✅**.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="🔄 Background Sweep",
        value="Bot will automatically poll Challonge for open matches every 5 minutes and create ticket channels.",
        inline=False
    )
    embed.set_footer(text=f"{interaction.guild.name} • Auto Room System")
    await interaction.response.send_message(embed=embed)

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
        title=f"{EMOJIS.get('gear', '⚙️')} Auto Room Creation Status",
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
        sheet = t.get('google_sheet_link') or t.get('captains_sheet_link') or t.get('sheet_link') or "Not Set"
        
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
        title=f"{EMOJIS.get('caution', '⚠️')} Bulk Delete Category Channels Confirmation",
        description=(
            f"Are you sure you want to delete **all {len(channels_to_delete)} channel(s)** in category **{category.name}**?\n\n"
            f"⚠️ **Warning:** This action is permanent and cannot be undone! Any chat logs or open match tickets in these channels will be removed."
        ),
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name=f"{EMOJIS.get('folder', '📁')} Target Category", value=f"{category.name} (`{category.id}`)", inline=True)
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
        title=f"{EMOJIS.get('trashcan', '🗑️')} Category Channels Bulk Deleted",
        description=f"**{interaction.user.mention}** bulk deleted **{deleted_count}** channel(s) from category **{category.name}**.",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    if failed_count > 0:
        log_embed.add_field(name="Failed", value=f"{failed_count} channel(s)", inline=True)
    await log_bot_activity(interaction.guild, log_embed)

    result_embed = discord.Embed(
        title=f"{EMOJIS.get('wrong', '✅')} Category Cleared",
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

    from core.state import GUILD_CONFIG_CACHE, RULES_CACHE, STAFF_STATS_CACHE, TOURNAMENTS_CACHE, CHALLONGE_MATCHES_CACHE
    GUILD_CONFIG_CACHE.clear()
    RULES_CACHE.clear()
    STAFF_STATS_CACHE.clear()
    TOURNAMENTS_CACHE.clear()
    CHALLONGE_MATCHES_CACHE.clear()

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
            
            t_cfg = get_active_tournament_config(interaction.guild_id) if interaction.guild_id else None
            tourney_name = t_cfg.get('name') if t_cfg else get_tournament_name(interaction)
            rules_ch_id = t_cfg.get('rules') if t_cfg else None
            deadline_ch_id = t_cfg.get('deadline') if t_cfg else None
            
            helper_team_role = None
            if t_cfg and t_cfg.get('helper_role_id'):
                try: helper_team_role = discord.utils.get(interaction.guild.roles, id=int(t_cfg['helper_role_id']))
                except Exception: pass
            if not helper_team_role:
                helper_id = ROLE_IDS.get('helper_team')
                if helper_id:
                    try: helper_team_role = discord.utils.get(interaction.guild.roles, id=int(helper_id))
                    except Exception: pass

            c1_ign = team_1 if team_1 else captain1.name
            c2_ign = team_2 if team_2 else captain2.name
            org_name = get_org_name(interaction.guild_id) if interaction.guild_id else None

            player_format = t_cfg.get('player_info_format') if t_cfg else ''
            is_1v1_cmd = ("1" in str(player_format) and "vs" in str(player_format)) or not (team_1 and team_2)

            ping_content, room_embed = create_match_room_embed(
                guild=interaction.guild,
                tournament_name=tourney_name,
                team1_name=t1_name,
                team2_name=t2_name,
                round_name=round,
                captain1_mention=captain1.mention,
                captain2_mention=captain2.mention,
                captain1_ign_or_id=c1_ign,
                captain2_ign_or_id=c2_ign,
                group_name=bracket,
                match_id="N/A",
                rules_channel_id=rules_ch_id,
                deadline_channel_id=deadline_ch_id,
                rules_link=get_link_rules(interaction),
                deadline_link=get_link_deadline(interaction),
                helper_role=helper_team_role,
                org_name=org_name,
                is_1v1=is_1v1_cmd
            )

            await channel.send(content=ping_content, embed=room_embed)

        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=False)

    @app_commands.command(name="upload-score", description="Upload match score to Challonge bracket (Judge/Organizer only)")
    @app_commands.describe(
        winner="Select the match and the winning team from the list",
        winner_score="Score of the winning team (e.g. 2)",
        loser_score="Score of the losing team (e.g. 1)"
    )
    @app_commands.autocomplete(winner=upload_score_winner_autocomplete)
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
        if permission_level not in ["organizer", "owner", "judge"] and not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.followup.send("❌ You need **Head Organizer** or **Judge/Staff** role to upload scores.", ephemeral=False)
            return

        try:
            parts = winner.split(":")
            if len(parts) < 3:
                await interaction.followup.send("❌ Invalid selection. Please select a match from the autocomplete dropdown list.", ephemeral=False)
                return
            match_id = parts[0]
            winner_participant_id = parts[1]
            if len(parts) >= 4:
                winner_name = ":".join(parts[2:-1])
                player1_id = str(parts[-1])
            else:
                winner_name = parts[2]
                player1_id = None
        except Exception:
            await interaction.followup.send("❌ Error parsing the selection. Please use the autocomplete list.", ephemeral=False)
            return

        t_cfg = get_active_tournament_config(interaction.guild.id) if interaction.guild else None
        if not t_cfg and interaction.guild:
            tournaments = load_guild_tournaments(interaction.guild.id)
            if len(tournaments) == 1:
                t_cfg = next(iter(tournaments.values()))
            else:
                for tid, cfg in tournaments.items():
                    if (cfg.get('challonge_bracket_link') or cfg.get('id')) and cfg.get('key'):
                        t_cfg = cfg
                        break

        bracket_link = (t_cfg.get('challonge_bracket_link') or t_cfg.get('id')) if t_cfg else get_bracket_link(interaction)
        api_key = t_cfg.get('key') if t_cfg else get_bracket_api_key(interaction)

        if not bracket_link:
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
            embed.add_field(name=f"{EMOJIS['trophy']} Score", value=f"**{winner_score}** – {loser_score}", inline=True)
            embed.add_field(name="🆔 Match ID", value=f"`{match_id}`", inline=True)
            embed.add_field(name="👤 Winner Team", value=f"**{winner_name}** (`{winner_participant_id}`)", inline=True)
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Uploaded by {interaction.user.display_name}")
            await interaction.followup.send(embed=embed, ephemeral=False)

            bot_log_embed = discord.Embed(
                title=f"{EMOJIS['trophy']} Score Uploaded to Challonge",
                description=f"Judge **{interaction.user.display_name}** successfully uploaded match score (Event ID: `{match_id}`): **{winner_name}** won!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            bot_log_embed.add_field(name="Score", value=f"**{winner_score}** – {loser_score}", inline=True)
            bot_log_embed.set_footer(text=f"Uploaded by {interaction.user.display_name}")
            await log_bot_activity(interaction.guild, bot_log_embed)

            # Auto-check next round open match rooms
            if t_cfg and t_cfg.get('auto_room_creation') and interaction.guild:
                asyncio.create_task(auto_create_open_tickets_for_tournament(interaction.guild, t_cfg))
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
            html_content = await asyncio.to_thread(generate_html_transcript, message_channel, messages_list, guild, closed_by=interaction.user)
            text_content = await asyncio.to_thread(generate_text_transcript, message_channel, messages_list, guild, closed_by=interaction.user)

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

            # Audit Log for Ticket Close
            try:
                close_log_embed = discord.Embed(
                    title=f"🔒 Ticket Closed: #{message_channel.name}",
                    description=(
                        f"**Closed By:** {interaction.user.mention}\n"
                        f"**Channel:** {message_channel.mention}\n"
                        f"**Messages:** `{len(messages_list)}`\n"
                        f"**Attachments:** `{attachment_count}`"
                    ),
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                close_log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
                await log_bot_activity(interaction.guild, close_log_embed)
            except Exception:
                pass
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

        chan_name = interaction.channel.name
        chan_id = interaction.channel.id
        guild = interaction.guild

        # Audit Log for Ticket Delete
        try:
            del_log_embed = discord.Embed(
                title=f"🗑️ Ticket Deleted: #{chan_name}",
                description=f"**Deleted By:** {interaction.user.mention}\n**Channel Name:** `#{chan_name}` (`{chan_id}`)",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            del_log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
            await log_bot_activity(guild, del_log_embed)
        except Exception:
            pass

        await interaction.response.send_message("🗑️ Deleting this ticket channel in 3 seconds...")
        await asyncio.sleep(3)
        try:
            await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user.name}")
        except Exception as e:
            print(f"Error deleting channel: {e}")

    @app_commands.command(name="add_member", description="Add a member to this ticket channel")
    @app_commands.describe(member="The member to add into this ticket channel")
    @with_guild_context
    async def add_member_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ This command can only be used in server text channels.", ephemeral=True)
            return

        perms = interaction.channel.permissions_for(interaction.user)
        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user) and not perms.send_messages:
            await interaction.response.send_message("❌ You do not have permission to add members to this ticket.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                reason=f"Added to ticket by {interaction.user.name}"
            )
            embed = discord.Embed(
                title="👤 Member Added to Ticket",
                description=f"{member.mention} has been added to this ticket channel by {interaction.user.mention}.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Ticket Manager")
            await interaction.response.send_message(embed=embed)

            # Audit Log
            log_embed = discord.Embed(
                title="👤 Member Added to Ticket",
                description=f"**Action By:** {interaction.user.mention}\n**Member Added:** {member.mention} (`{member.id}`)\n**Channel:** {interaction.channel.mention} (`#{interaction.channel.name}`)",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
            await log_bot_activity(interaction.guild, log_embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to add member: {e}", ephemeral=True)

    @app_commands.command(name="remove_member", description="Remove a member from this ticket channel")
    @app_commands.describe(member="The member to remove from this ticket channel")
    @with_guild_context
    async def remove_member_cmd(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ This command can only be used in server text channels.", ephemeral=True)
            return

        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to remove members from this ticket.", ephemeral=True)
            return

        try:
            await interaction.channel.set_permissions(member, overwrite=None, reason=f"Removed from ticket by {interaction.user.name}")
            embed = discord.Embed(
                title="👤 Member Removed from Ticket",
                description=f"{member.mention} has been removed from this ticket channel by {interaction.user.mention}.",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Ticket Manager")
            await interaction.response.send_message(embed=embed)

            # Audit Log
            log_embed = discord.Embed(
                title="👤 Member Removed from Ticket",
                description=f"**Action By:** {interaction.user.mention}\n**Member Removed:** {member.mention} (`{member.id}`)\n**Channel:** {interaction.channel.mention} (`#{interaction.channel.name}`)",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
            await log_bot_activity(interaction.guild, log_embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed to remove member: {e}", ephemeral=True)

    @app_commands.command(name="assign_role", description="Assign a role to all participants from a tournament or Google Sheet")
    @app_commands.describe(
        role="The role to assign to participants",
        tournament="Tournament to assign roles for (optional if sheet_link or server sheet is set)",
        sheet_link="Optional direct Google Sheet link to read participants from",
        id_header="Optional sheet column header for Discord IDs (e.g., Discord ID, Developer ID, UID)",
        dry_run="If True, simulates role assignment without making actual changes"
    )
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    @with_guild_context
    async def assign_role_cmd(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
        tournament: Optional[str] = None,
        sheet_link: Optional[str] = None,
        id_header: Optional[str] = None,
        dry_run: Optional[bool] = False
    ):
        if not interaction.guild:
            await interaction.response.send_message("❌ Server only.", ephemeral=True)
            return

        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to assign tournament roles.", ephemeral=True)
            return

        # Check Bot Permissions
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ I do not have the **Manage Roles** permission in this server. Please grant me Manage Roles in server settings.", ephemeral=True)
            return

        if interaction.guild.me.top_role <= role:
            await interaction.response.send_message(
                f"❌ Cannot assign {role.mention} because it is higher than or equal to my highest role ({interaction.guild.me.top_role.mention}).\n"
                f"Please move the bot's role above {role.name} in Server Settings > Roles.",
                ephemeral=True
            )
            return

        guild = interaction.guild
        guild_id = guild.id
        cfg = get_guild_config(guild_id)

        target_t = None
        target_sheet_link = sheet_link.strip() if sheet_link else None

        if tournament:
            tournaments = load_guild_tournaments(guild_id)
            for k, v in tournaments.items():
                if v.get('name', '').lower() == tournament.lower() or k.lower() == tournament.lower():
                    target_t = v
                    break
            if not target_t:
                await interaction.response.send_message(f"❌ Tournament `{tournament}` not found.", ephemeral=True)
                return
            if not target_sheet_link:
                target_sheet_link = (
                    target_t.get('google_sheet_link')
                    or target_t.get('captains_sheet_link')
                    or target_t.get('sheet_link')
                )

        if not target_sheet_link:
            # Check active tournament config
            active_t = get_active_tournament_config(guild_id)
            if active_t:
                target_sheet_link = (
                    active_t.get('google_sheet_link')
                    or active_t.get('captains_sheet_link')
                    or active_t.get('sheet_link')
                )
                if not target_t:
                    target_t = active_t

        if not target_sheet_link:
            # Fall back to global server player info sheet or google_sheet_link
            target_sheet_link = cfg.get('player_info_link') or cfg.get('google_sheet_link')

        if not target_sheet_link:
            await interaction.response.send_message(
                "❌ No Google Sheet found to read participants from.\n"
                "Please specify `sheet_link`, select a `tournament` with a configured sheet, or configure the server sheet with `/config_player_information`.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=False)

        sheet_name_display = target_t.get('name') if target_t else "Participant Sheet"
        msg = await interaction.followup.send(f"⏳ Reading Google Sheet for **{sheet_name_display}**...")

        match = re.search(r'/d/([a-zA-Z0-9-_]+)', target_sheet_link)
        if not match:
            await msg.edit(content="❌ Invalid Google Sheet URL. Make sure it is a valid Google Sheets link.")
            return

        sheet_id = match.group(1)
        gid_match = re.search(r'[#&?]gid=([0-9]+)', target_sheet_link)
        gid = gid_match.group(1) if gid_match else None
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        if gid:
            url += f"&gid={gid}"

        try:
            resp = await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()
            reader = list(csv.reader(io.StringIO(resp.text)))
        except Exception as e:
            await msg.edit(content=f"❌ Failed to fetch Google Sheet: {e}\nMake sure the Google Sheet link sharing is set to **'Anyone with the link can view'**.")
            return

        if not reader:
            await msg.edit(content="❌ The Google Sheet appears to be empty.")
            return

        h_row = [h.strip().lower() for h in reader[0]]
        val_cols = []

        if id_header:
            clean_hdr = id_header.strip().lower()
            for i, h in enumerate(h_row):
                if clean_hdr in h or h in clean_hdr:
                    val_cols.append(i)

        if not val_cols:
            id_keywords = [
                'developer id', 'developers id', 'discord id', 'discord_id',
                'discord uid', 'uid', 'user id', 'captain id', 'player id', 'discord'
            ]
            exclude_keywords = ['username', 'user name', 'display name', 'game id', 'ign']
            for i, h in enumerate(h_row):
                if any(x in h for x in id_keywords) and not any(x in h for x in exclude_keywords):
                    val_cols.append(i)

        extracted_targets = []
        seen_targets = set()

        if val_cols:
            for row in reader[1:]:
                for col_idx in val_cols:
                    if col_idx < len(row):
                        raw_cell = row[col_idx].strip()
                        if raw_cell:
                            found_ids = re.findall(r'\b(\d{17,20})\b', raw_cell)
                            if found_ids:
                                for fid in found_ids:
                                    if fid not in seen_targets:
                                        seen_targets.add(fid)
                                        extracted_targets.append(fid)
                            else:
                                clean_val = raw_cell.lstrip('@')
                                if clean_val and clean_val.lower() not in seen_targets:
                                    seen_targets.add(clean_val.lower())
                                    extracted_targets.append(clean_val)
        else:
            # Fallback: search all cells in the sheet for Discord snowflake IDs
            for row in reader[1:]:
                for cell in row:
                    found_ids = re.findall(r'\b(\d{17,20})\b', cell)
                    for fid in found_ids:
                        if fid not in seen_targets:
                            seen_targets.add(fid)
                            extracted_targets.append(fid)

        if not extracted_targets:
            await msg.edit(content="❌ No participant entries or Discord IDs found in the sheet.\nMake sure the sheet contains Discord IDs or specify `id_header`.")
            return

        await msg.edit(content=f"⏳ Found **{len(extracted_targets)}** participant(s). Processing role assignment...")

        assigned_count = 0
        already_had_count = 0
        failed_count = 0
        not_found_count = 0
        last_error = None

        for idx, raw_target in enumerate(extracted_targets):
            clean_target = str(raw_target).strip().lstrip('@')
            id_m = re.search(r'\b(\d{17,20})\b', clean_target)
            member = None

            if id_m:
                uid = int(id_m.group(1))
                member = guild.get_member(uid)
                if not member:
                    try:
                        member = await guild.fetch_member(uid)
                    except discord.NotFound:
                        member = None
                    except Exception:
                        pass
            else:
                for m in guild.members:
                    if m.name.lower() == clean_target.lower() or m.display_name.lower() == clean_target.lower():
                        member = m
                        break
                if not member:
                    try:
                        found = await guild.query_members(query=clean_target, limit=5)
                        for m in found:
                            if m.name.lower() == clean_target.lower() or m.display_name.lower() == clean_target.lower():
                                member = m
                                break
                    except Exception:
                        pass

            if not member:
                not_found_count += 1
                continue

            if role in member.roles:
                already_had_count += 1
                continue

            if not dry_run:
                try:
                    reason_t = sheet_name_display
                    await member.add_roles(role, reason=f"Participant in {reason_t} assigned by {interaction.user.name}")
                    assigned_count += 1
                    await asyncio.sleep(0.35)
                except Exception as e:
                    last_error = str(e)
                    print(f"Error adding role to {member.display_name}: {e}")
                    failed_count += 1
            else:
                assigned_count += 1

            if (idx + 1) % 10 == 0 or (idx + 1) == len(extracted_targets):
                try:
                    await msg.edit(content=f"⏳ {'[DRY RUN] ' if dry_run else ''}Processed **{idx+1}/{len(extracted_targets)}** players...")
                except Exception:
                    pass

        summary_embed = discord.Embed(
            title=f"👥 {'[DRY RUN] ' if dry_run else ''}Role Assignment Complete",
            description=f"Assigned role {role.mention} for **{sheet_name_display}**.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        summary_embed.add_field(name="📊 Total Processed", value=f"`{len(extracted_targets)}`", inline=True)
        summary_embed.add_field(name="✅ Newly Assigned", value=f"`{assigned_count}`", inline=True)
        summary_embed.add_field(name="⏩ Already Had Role", value=f"`{already_had_count}`", inline=True)
        if not_found_count > 0:
            summary_embed.add_field(name="❓ Not Found in Server", value=f"`{not_found_count}`", inline=True)
        if failed_count > 0:
            err_val = f"`{failed_count}`"
            if last_error:
                err_val += f"\n*(Last error: {last_error})*"
            summary_embed.add_field(name="❌ Errors", value=err_val, inline=True)

        summary_embed.set_footer(text=f"{interaction.guild.name} • Participant Roles")
        await msg.edit(content=None, embed=summary_embed)

    @app_commands.command(name="reopen", description="Reopen a closed ticket room and move it back to active tournament categories")
    @with_guild_context
    async def reopen_room_cmd(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("❌ Server text channels only.", ephemeral=True)
            return

        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to reopen tickets.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)
        channel = interaction.channel
        guild = interaction.guild

        t_cfg = get_active_tournament_config(guild.id)
        open_category = None
        if t_cfg:
            for i in range(1, 5):
                cat_id = t_cfg.get(f'ticket_open_category_{i}') or t_cfg.get(f'Open_Category_{i}_ID')
                if cat_id:
                    try:
                        cat = guild.get_channel(int(cat_id))
                        if cat and len(cat.channels) < 49:
                            open_category = cat
                            break
                    except Exception:
                        pass

        if not open_category:
            tournaments = load_guild_tournaments(guild.id)
            for _, tdata in tournaments.items():
                for i in range(1, 5):
                    cat_id = tdata.get(f'ticket_open_category_{i}') or tdata.get(f'Open_Category_{i}_ID')
                    if cat_id:
                        try:
                            cat = guild.get_channel(int(cat_id))
                            if cat and len(cat.channels) < 49:
                                open_category = cat
                                break
                        except Exception:
                            pass
                if open_category:
                    break

        clean_name = channel.name
        for pfx in ["closed-", "done-", "🔴-", "✅-"]:
            if clean_name.startswith(pfx):
                clean_name = clean_name[len(pfx):]
                break

        try:
            if open_category:
                await channel.edit(
                    name=clean_name,
                    category=open_category,
                    sync_permissions=True,
                    reason=f"Ticket reopened by {interaction.user.name}"
                )
            else:
                await channel.edit(name=clean_name, reason=f"Ticket reopened by {interaction.user.name}")

            embed = discord.Embed(
                title="🔓 Ticket Reopened",
                description=f"This ticket has been reopened by {interaction.user.mention} and moved back to active match channels.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text=f"{ORGANIZATION_NAME} • Ticket Manager")
            await interaction.followup.send(embed=embed)

            log_embed = discord.Embed(
                title="🔓 Ticket Reopened",
                description=f"Ticket #{channel.name} was reopened by {interaction.user.mention}.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await log_bot_activity(guild, log_embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Failed to reopen channel: {e}")




async def setup(bot: commands.Bot):
    bot.tree.add_command(tournament_group)
    bot.tree.add_command(link_group)
    bot.tree.add_command(deadline_group)
    bot.tree.add_command(auto_room_group)
    bot.tree.add_command(clear_group)
    await bot.add_cog(Tournaments(bot))

