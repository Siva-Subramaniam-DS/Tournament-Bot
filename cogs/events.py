import os
import io
import re
import glob
import json
import random
import asyncio
import datetime
import tempfile
from pathlib import Path
from typing import Optional, List, Union, Any

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View
import pytz
from PIL import Image

from core.config import (
    BASE_DIR, BRAND_COLOR, BOT_OWNER_ID, ORGANIZATION_NAME,
    GAME_ALIASES, DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS
)
from core.state import (
    current_guild_id, with_guild_context, is_authorized_to_configure,
    is_staff, has_organizer_permission, has_event_create_permission,
    has_event_result_permission, get_user_permission_level, get_org_name,
    get_tournament_name, get_system_name, get_bracket_link,
    ROLE_IDS, CHANNEL_IDS, scheduled_events, save_scheduled_events,
    scheduled_deadlines, reminder_tasks, cleanup_tasks,
    is_event_over, resolve_event_names
)
from core.database import (
    supabase_client, load_guild_tournaments, save_guild_tournaments,
    get_guild_config, get_active_tournament_config,
    save_event_to_supabase, log_bot_activity, sheetdb_post,
    update_staff_stats, get_guild_staff_stats, save_guild_staff_stats
)

from core.image_generator import (
    get_random_template, create_event_poster, create_esports_match_poster,
    get_thumbnail_url_from_channel, get_thumbnail_layer_path
)
from core.emojis import EMOJIS
from cogs.staff import (
    TakeScheduleButton, StaffConfirmationView, StaffReplacementView,
    remove_judge_assignment, add_judge_assignment, get_staff_emoji
)
from cogs.tournaments import (
    tournament_autocomplete, game_autocomplete, match_autocomplete,
    find_event_by_name_or_id
)

# ===========================================================================================
# HELPERS
# ===========================================================================================

def format_round_heading(round_val) -> str:
    if not round_val:
        return "Round Not Set"
    round_str = str(round_val).strip()
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

def calculate_time_difference(event_datetime: datetime.datetime, user_timezone: str = None) -> dict:
    current_time = datetime.datetime.utcnow()
    time_diff = event_datetime - current_time
    minutes_remaining = int(time_diff.total_seconds() / 60)
    utc_time_str = event_datetime.strftime("%H:%M utc, %d/%m")
    
    local_timezone = pytz.timezone(user_timezone) if user_timezone else pytz.timezone('Asia/Kolkata')
    local_time = event_datetime.replace(tzinfo=pytz.UTC).astimezone(local_timezone)
    local_time_formatted = local_time.strftime("%A, %d %B, %Y %H:%M")
    
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

def find_tournament_config(guild_id: int, tournament_name_or_id: str) -> Optional[dict]:
    if not guild_id or not tournament_name_or_id:
        return None
    tournaments = load_guild_tournaments(guild_id)
    clean_target = str(tournament_name_or_id).strip().lower()
    if clean_target in tournaments:
        return tournaments[clean_target]
    for t_id, t_cfg in tournaments.items():
        if str(t_cfg.get('name', '')).strip().lower() == clean_target:
            return t_cfg
    for t_id, t_cfg in tournaments.items():
        if clean_target in t_id.lower() or clean_target in str(t_cfg.get('name', '')).lower() or str(t_cfg.get('name', '')).lower() in clean_target:
            return t_cfg
    return None

def get_tournament_schedule_channel(guild: discord.Guild, tournament: str = None) -> Optional[discord.TextChannel]:
    if not guild:
        return None
    keys = ['schedule', 'take_schedule', 'schedule_channel', 'Schedule_Channel_ID', 'schedule_channel_id', 'take_schedule_channel_id']
    if tournament:
        t_cfg = find_tournament_config(guild.id, tournament)
        if t_cfg:
            for k in keys:
                if t_cfg.get(k):
                    try:
                        ch = guild.get_channel(int(t_cfg[k]))
                        if ch: return ch
                    except: pass
    t_cfg = get_active_tournament_config(guild.id)
    if t_cfg:
        for k in keys:
            if t_cfg.get(k):
                try:
                    ch = guild.get_channel(int(t_cfg[k]))
                    if ch: return ch
                except: pass
    cfg = get_guild_config(guild.id)
    global_channels = cfg.get('channel_ids', {})
    for k in keys:
        sch_id = global_channels.get(k) or cfg.get(k)
        if sch_id:
            try:
                ch = guild.get_channel(int(sch_id))
                if ch: return ch
            except: pass
    return None

def get_tournament_results_channel(guild: discord.Guild, tournament: str = None) -> Optional[discord.TextChannel]:
    if not guild:
        return None
    keys = ['result', 'results', 'results_channel', 'Result_Channel_ID', 'result_channel_id', 'results_channel_id']
    if tournament:
        t_cfg = find_tournament_config(guild.id, tournament)
        if t_cfg:
            for k in keys:
                if t_cfg.get(k):
                    try:
                        ch = guild.get_channel(int(t_cfg[k]))
                        if ch: return ch
                    except: pass
    t_cfg = get_active_tournament_config(guild.id)
    if t_cfg:
        for k in keys:
            if t_cfg.get(k):
                try:
                    ch = guild.get_channel(int(t_cfg[k]))
                    if ch: return ch
                except: pass
    cfg = get_guild_config(guild.id)
    global_channels = cfg.get('channel_ids', {})
    for k in keys:
        res_id = global_channels.get(k) or cfg.get(k)
        if res_id:
            try:
                ch = guild.get_channel(int(res_id))
                if ch: return ch
            except: pass
    return None

def get_tournament_attendance_channel(guild: discord.Guild, tournament: str = None) -> Optional[discord.TextChannel]:
    if not guild:
        return None
    keys = ['attendance', 'staff_attendance', 'attendance_channel', 'Attendance_Channel_ID', 'attendance_channel_id', 'staff_attendance_channel_id']
    if tournament:
        t_cfg = find_tournament_config(guild.id, tournament)
        if t_cfg:
            for k in keys:
                if t_cfg.get(k):
                    try:
                        ch = guild.get_channel(int(t_cfg[k]))
                        if ch: return ch
                    except: pass
    t_cfg = get_active_tournament_config(guild.id)
    if t_cfg:
        for k in keys:
            if t_cfg.get(k):
                try:
                    ch = guild.get_channel(int(t_cfg[k]))
                    if ch: return ch
                except: pass
    cfg = get_guild_config(guild.id)
    global_channels = cfg.get('channel_ids', {})
    for k in keys:
        att_id = global_channels.get(k) or cfg.get(k)
        if att_id:
            try:
                ch = guild.get_channel(int(att_id))
                if ch: return ch
            except: pass
    return None


async def resolve_embed_thumbnail(guild_id: int, embed: discord.Embed, fallback_to_captain_avatar: Optional[discord.Member] = None) -> tuple[Optional[discord.File], bool]:
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

    default_logo_path = os.path.join(BASE_DIR, "tournament_bot_logo.png")
    if os.path.exists(default_logo_path):
        try:
            with open(default_logo_path, "rb") as f:
                logo_data = f.read()
            embed.set_thumbnail(url="attachment://tournament_bot_logo.png")
            file_obj = discord.File(fp=io.BytesIO(logo_data), filename="tournament_bot_logo.png")
            return file_obj, True
        except Exception as e:
            print(f"Error loading default logo: {e}")

    if fallback_to_captain_avatar and hasattr(fallback_to_captain_avatar, 'display_avatar'):
        embed.set_thumbnail(url=fallback_to_captain_avatar.display_avatar.url)
        return None, False

    return None, False

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
        if general_link: link_lines.append(f"{rec_emoji} **Recording:** {format_links_markdown(general_link, 'Link')}")
        if rec_link:     link_lines.append(f"{rec_emoji} **Recorder VOD:** {format_links_markdown(rec_link, 'Link')}")
        if jdg_link:     link_lines.append(f"{jdg_emoji} **Judge VOD:** {format_links_markdown(jdg_link, 'Link')}")
        
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

    # Also update ticket channel embed if available
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

async def update_results_message_embed(guild: discord.Guild, ev_data: dict) -> bool:
    res_msg_id = ev_data.get('results_message_id')
    res_chan_id = ev_data.get('results_channel_id')
    if not res_msg_id or not res_chan_id or not guild:
        return False
    try:
        channel = guild.get_channel(int(res_chan_id))
        if not channel:
            channel = await guild.fetch_channel(int(res_chan_id))
        msg = await channel.fetch_message(int(res_msg_id))
        if not msg or not msg.embeds:
            return False

        orig_embed = msg.embeds[0]
        w_name = ev_data.get('team1_name', 'Unknown')
        l_name = ev_data.get('team2_name', 'Unknown')
        w_score = ev_data.get('winner_score', 0)
        l_score = ev_data.get('loser_score', 0)
        dq_status = ev_data.get('disqualified')
        remarks = ev_data.get('remarks', 'ggwp')

        w_disp = f"{w_name} (Disqualified)" if dq_status in ("Winner", "Both") else w_name
        l_disp = f"{l_name} (Disqualified)" if dq_status in ("Loser", "Both") else l_name

        winner_badge = EMOJIS.get('winner', '🏆')
        orig_embed.title = f"{winner_badge} {w_disp} 🆚 {l_disp}"

        judge_val = ev_data.get('judge')
        recorder_val = ev_data.get('recorder')

        judge_mention = getattr(judge_val, 'mention', None) or (f"<@{judge_val}>" if str(judge_val).isdigit() else str(judge_val or "Unknown"))
        judge_name = getattr(judge_val, 'name', None) or (ev_data.get('result_judge') or str(judge_val or "Unknown"))
        staff_text = f"{EMOJIS.get('helpers', '👥')} **Staffs**\n▪ {EMOJIS.get('judge', '⚖️')} Judge: {judge_mention}" + (f" ({judge_name})" if judge_name and judge_name not in judge_mention else "")

        if recorder_val:
            rec_mention = getattr(recorder_val, 'mention', None) or (f"<@{recorder_val}>" if str(recorder_val).isdigit() else str(recorder_val))
            rec_name = getattr(recorder_val, 'name', None) or str(recorder_val)
            staff_text += f"\n▪ {EMOJIS.get('recorder', '📹')} Recorder: {rec_mention}" + (f" ({rec_name})" if rec_name and rec_name not in rec_mention else "")

        t1_cap = ev_data.get('team1_captain')
        t2_cap = ev_data.get('team2_captain')
        t1_cap_mention = getattr(t1_cap, 'mention', None) or (f"<@{t1_cap}>" if str(t1_cap).isdigit() else f"**{w_name}**")
        t2_cap_mention = getattr(t2_cap, 'mention', None) or (f"<@{t2_cap}>" if str(t2_cap).isdigit() else f"**{l_name}**")
        if dq_status in ("Winner", "Both"): t1_cap_mention += " (Disqualified)"
        if dq_status in ("Loser", "Both"):  t2_cap_mention += " (Disqualified)"

        captains_text = f"{EMOJIS.get('captain', '👑')} **Captains**\n- Team1 Captain: {t1_cap_mention}\n- Team2 Captain: {t2_cap_mention}"
        results_text = f"{EMOJIS.get('trophy', '🏆')} **Results**\n{winner_badge} {w_name} ({w_score}) {EMOJIS.get('vs', 'vs')} ({l_score}) {l_name} {EMOJIS.get('skull', '💀')}"

        ss_field = None
        rec_field = None
        for f in orig_embed.fields:
            if "Screenshots of Result" in (f.value or "") or "Screenshots" in (f.name or ""):
                ss_field = f
            elif "Recordings / VODs" in (f.name or "") or "Recording Link" in (f.name or ""):
                rec_field = f

        orig_embed.clear_fields()
        orig_embed.add_field(name="", value=captains_text, inline=False)
        orig_embed.add_field(name="", value=results_text, inline=False)
        orig_embed.add_field(name="", value=staff_text, inline=False)
        if rec_field:
            orig_embed.add_field(name=rec_field.name, value=rec_field.value, inline=rec_field.inline)
        orig_embed.add_field(name="📝 Remarks", value=remarks, inline=False)
        if ss_field:
            orig_embed.add_field(name=ss_field.name, value=ss_field.value, inline=ss_field.inline)

        await msg.edit(embed=orig_embed)
        return True
    except Exception as e:
        print(f"Error updating result message embed: {e}")
        return False
    except Exception as e:
        print(f"Error updating result message embed: {e}")
        return False

async def send_ten_minute_reminder(event_id: str, team1_captain: Any, team2_captain: Any, judge: Optional[Any], event_channel: discord.TextChannel, match_time: datetime.datetime):
    try:
        if not event_channel:
            return

        resolved_judge = judge
        resolved_team1_captain = team1_captain
        resolved_team2_captain = team2_captain
        resolved_recorder = None
        
        if event_id in scheduled_events:
            ev_data = scheduled_events[event_id]
            if ev_data.get('judge'): resolved_judge = ev_data.get('judge')
            if ev_data.get('recorder'): resolved_recorder = ev_data.get('recorder')
            if ev_data.get('team1_captain'): resolved_team1_captain = ev_data.get('team1_captain')
            if ev_data.get('team2_captain'): resolved_team2_captain = ev_data.get('team2_captain')

        t1_id = getattr(resolved_team1_captain, 'id', resolved_team1_captain)
        t2_id = getattr(resolved_team2_captain, 'id', resolved_team2_captain)
        j_id = getattr(resolved_judge, 'id', resolved_judge) if resolved_judge else None
        r_id = getattr(resolved_recorder, 'id', resolved_recorder) if resolved_recorder else None

        embed = discord.Embed(
            title="⏰ 10-MINUTE MATCH REMINDER",
            description="**Your tournament match is starting in 10 minutes!**",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        _mt_utc = match_time if match_time.tzinfo else match_time.replace(tzinfo=datetime.timezone.utc)
        embed.add_field(name="🕒 Match Time", value=f"<t:{int(_mt_utc.timestamp())}:F>", inline=False)
        
        t1_ping = f"<@{t1_id}>" if t1_id and str(t1_id).strip().isdigit() else "Team 1 Captain"
        t2_ping = f"<@{t2_id}>" if t2_id and str(t2_id).strip().isdigit() else "Team 2 Captain"
        embed.add_field(name="👥 Team Captains", value=f"{t1_ping} vs {t2_ping}", inline=False)
        if j_id and str(j_id).strip().isdigit():
            embed.add_field(name=f"{EMOJIS['judge']} Judge", value=f"<@{j_id}>", inline=True)
        if r_id and str(r_id).strip().isdigit():
            embed.add_field(name=f"{EMOJIS['recorder']} Recorder", value=f"<@{r_id}>", inline=True)
        embed.add_field(name="📝 Action Required", value="Please prepare for the match and join the designated channel.", inline=False)
        embed.set_footer(text="Tournament Management System")

        file = None
        if event_id in scheduled_events:
            ev_data = scheduled_events[event_id]
            poster_image = ev_data.get('poster_path')
            if poster_image and os.path.exists(poster_image):
                try:
                    file = discord.File(poster_image, filename="event_poster.png")
                    embed.set_image(url="attachment://event_poster.png")
                except Exception as e:
                    print(f"Error loading poster image for reminder: {e}")

        pings_list = []
        if j_id and str(j_id).strip().isdigit(): pings_list.append(f"<@{j_id}>")
        if r_id and str(r_id).strip().isdigit(): pings_list.append(f"<@{r_id}>")
        if t1_id and str(t1_id).strip().isdigit(): pings_list.append(f"<@{t1_id}>")
        if t2_id and str(t2_id).strip().isdigit(): pings_list.append(f"<@{t2_id}>")
        pings = " ".join(pings_list)
        notification_text = f"🔔 **MATCH REMINDER**\n\n{pings}\n\nYour match starts in **10 minutes**!"

        if file:
            await event_channel.send(content=notification_text, embed=embed, file=file)
        else:
            await event_channel.send(content=notification_text, embed=embed)
    except Exception as e:
        print(f"Error sending 10-minute reminder: {e}")

async def schedule_ten_minute_reminder(event_id: str, team1_captain: Any, team2_captain: Any, judge: Optional[Any], event_channel: discord.TextChannel, match_time: datetime.datetime):
    try:
        now = datetime.datetime.now(pytz.UTC)
        if match_time.tzinfo is None:
            match_time = match_time.replace(tzinfo=pytz.UTC)
            
        reminder_time_20 = match_time - datetime.timedelta(minutes=20)
        reminder_time_10 = match_time - datetime.timedelta(minutes=10)
        
        async def combined_reminder_task():
            g_id = None
            if event_id in scheduled_events:
                g_id = scheduled_events[event_id].get('guild_id')
                if g_id: current_guild_id.set(g_id)
                    
            delay_20 = (reminder_time_20 - datetime.datetime.now(pytz.UTC)).total_seconds()
            if delay_20 > 0:
                await asyncio.sleep(delay_20)
            
            if g_id: current_guild_id.set(g_id)
                
            if event_id in scheduled_events:
                now_check = datetime.datetime.now(pytz.UTC)
                if now_check < match_time:
                    ev_data = scheduled_events[event_id]
                    j = ev_data.get('judge')
                    r = ev_data.get('recorder')
                    
                    if not j:
                        try:
                            j_role = ROLE_IDS.get('judge')
                            j_ping = f"<@&{j_role}>" if j_role else "**@Judge**"
                            await event_channel.send(f"⚠️ {j_ping} **URGENT:** Match starts in 20 mins and NO JUDGE is assigned!")
                        except Exception as e: pass
                    
                    if not r:
                        try:
                            r_role = ROLE_IDS.get('recorder')
                            r_ping = f"<@&{r_role}>" if r_role else "**@Recorder**"
                            await event_channel.send(f"⚠️ {r_ping} **URGENT:** Match starts in 20 mins and NO RECORDER is assigned!")
                        except Exception as e: pass
                    
                    if j or r:
                        try:
                            def resolve_member_obj(user_or_id):
                                if not user_or_id:
                                    return None
                                if isinstance(user_or_id, (discord.Member, discord.User)):
                                    return user_or_id
                                uid_str = str(user_or_id).strip()
                                if uid_str.isdigit() and event_channel and event_channel.guild:
                                    return event_channel.guild.get_member(int(uid_str))
                                return None

                            j_m = resolve_member_obj(j)
                            r_m = resolve_member_obj(r)
                            
                            pings = []
                            for target in (j_m or j, r_m or r):
                                if target:
                                    tid = getattr(target, 'id', target)
                                    if tid and str(tid).strip().isdigit():
                                        pings.append(f"<@{tid}>")

                            embed = discord.Embed(
                                title="Staff Confirmation Required",
                                description="Please confirm your presence for the upcoming match.",
                                color=discord.Color.orange(),
                                timestamp=discord.utils.utcnow()
                            )
                            embed.add_field(name="⏰ Window", value="You have **10 minutes** to confirm before auto-replacement triggers.")
                            view = StaffConfirmationView(event_id, j_m, r_m)
                            await event_channel.send(content=" ".join(pings), embed=embed, view=view)
                        except Exception as e:
                            print(f"Error sending staff confirmation: {e}")
            
            delay_10 = (reminder_time_10 - datetime.datetime.now(pytz.UTC)).total_seconds()
            if delay_10 > 0:
                await asyncio.sleep(delay_10)
                
            if g_id: current_guild_id.set(g_id)
                
            if event_id in scheduled_events:
                now_check = datetime.datetime.now(pytz.UTC)
                if now_check < match_time:
                    try:
                        ev_data = scheduled_events[event_id]
                        t1 = ev_data.get('team1_captain')
                        t2 = ev_data.get('team2_captain')
                        j_val = ev_data.get('judge')
                        
                        def resolve_member_obj_local(user_or_id):
                            if not user_or_id: return None
                            if isinstance(user_or_id, (discord.Member, discord.User)): return user_or_id
                            uid_str = str(user_or_id).strip()
                            if uid_str.isdigit() and event_channel and event_channel.guild:
                                return event_channel.guild.get_member(int(uid_str))
                            return None

                        t1_m = resolve_member_obj_local(t1) or t1
                        t2_m = resolve_member_obj_local(t2) or t2
                        j_m = resolve_member_obj_local(j_val) or j_val
                        await send_ten_minute_reminder(event_id, t1_m, t2_m, j_m, event_channel, match_time)
                    except Exception as e:
                        print(f"Failed to send 10-min player reminder: {e}")

        if event_id in reminder_tasks:
            reminder_tasks[event_id].cancel()

        reminder_tasks[event_id] = asyncio.create_task(combined_reminder_task())
    except Exception as e:
        print(f"Error scheduling reminders for event {event_id}: {e}")

async def schedule_event_cleanup(event_id: str, delay_hours: int = 1, delay_minutes: int = None, keep_event_data: bool = False):
    try:
        if event_id not in scheduled_events:
            return
        
        delay_seconds = delay_minutes * 60 if delay_minutes is not None else delay_hours * 3600

        async def cleanup_task():
            try:
                await asyncio.sleep(delay_seconds)
                data = scheduled_events.get(event_id)
                if not data: return
                
                if keep_event_data:
                    data['status'] = 'completed'
                    data['cleanup_timestamp'] = datetime.datetime.utcnow().isoformat()
                    save_scheduled_events()
                else:
                    del scheduled_events[event_id]
                    save_scheduled_events()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"Error in cleanup task: {e}")

        if event_id in cleanup_tasks:
            try: cleanup_tasks[event_id].cancel()
            except Exception: pass

        cleanup_tasks[event_id] = asyncio.create_task(cleanup_task())
    except Exception as e:
        print(f"Error scheduling cleanup: {e}")


# ===========================================================================================
# EVENTS COG
# ===========================================================================================

class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="event", description="Base event command helper")
    @app_commands.describe(action="Select event action")
    @app_commands.choices(action=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="result", value="result")
    ])
    @with_guild_context
    async def event_base(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        await interaction.response.send_message(f"Please use `/event-{action.value}` with the appropriate parameters.", ephemeral=False)

    @app_commands.command(name="event-create", description="Creates an event (Head Organizer/Head Helper/Helper Team only)")
    @app_commands.describe(
        team_1_captain="Captain of team 1",
        team_2_captain="Captain of team 2", 
        hour="Hour of the event (0-23)",
        minute="Minute of the event (0-59)",
        date="Date of the event",
        month="Month of the event",
        round="Round label",
        tournament="Tournament name (e.g. King of the Seas, Summer Cup, etc.)",
        team_1_name="Optional name of team 1",
        team_2_name="Optional name of team 2",
        judge="Optional: Directly assign a Judge",
        recorder="Optional: Directly assign a Recorder",
        remarks="Optional: Remarks (e.g. starting soon, spot match)"
    )
    @app_commands.autocomplete(tournament=tournament_autocomplete)
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
        self,
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
        judge: Optional[discord.Member] = None,
        recorder: Optional[discord.Member] = None,
        remarks: Optional[str] = None
    ):
        await interaction.response.defer(ephemeral=False)
        
        if not has_event_create_permission(interaction):
            await interaction.followup.send("❌ You need **Head Organizer**, **Head Helper** or **Helper Team** role to create events.", ephemeral=False)
            return
        
        if not (0 <= hour <= 23):
            await interaction.followup.send("❌ Hour must be between 0 and 23", ephemeral=False)
            return
        if not (1 <= date <= 31):
            await interaction.followup.send("❌ Date must be between 1 and 31", ephemeral=False)
            return
        if not (1 <= month <= 12):
            await interaction.followup.send("❌ Month must be between 1 and 12", ephemeral=False)
            return
        if not (0 <= minute <= 59):
            await interaction.followup.send("❌ Minute must be between 0 and 59", ephemeral=False)
            return

        event_id = f"event_{int(datetime.datetime.now().timestamp())}"
        current_year = datetime.datetime.now().year
        event_datetime = datetime.datetime(current_year, month, date, hour, minute)
        
        now_utc = datetime.datetime.now(pytz.UTC)
        event_datetime_utc = event_datetime.replace(tzinfo=pytz.UTC)
        time_until_event = (event_datetime_utc - now_utc).total_seconds() / 60

        time_info = calculate_time_difference(event_datetime)
        round_label = round.value if isinstance(round, app_commands.Choice) else str(round)
        group_label = group.value if group and isinstance(group, app_commands.Choice) else None
        
        # Resolve tournament configurations (id, name, mode, game)
        t_configs = load_guild_tournaments(interaction.guild_id) if interaction.guild_id else {}
        clean_t_id = tournament.strip().lower()
        t_data_hint = t_configs.get(clean_t_id, {})
        if not t_data_hint:
            for tid, cfg in t_configs.items():
                if cfg.get('name', '').strip().lower() == clean_t_id or tid.strip().lower() == clean_t_id:
                    t_data_hint = cfg
                    clean_t_id = tid
                    break

        mode = t_data_hint.get('mode')
        game_hint = t_data_hint.get('game') or t_data_hint.get('name') or tournament
        tournament_display = t_data_hint.get('name') or tournament

        t1_final_name = team_1_name or (team_1_captain.display_name if hasattr(team_1_captain, 'display_name') else (team_1_captain.name if hasattr(team_1_captain, 'name') else str(team_1_captain)))
        t2_final_name = team_2_name or (team_2_captain.display_name if hasattr(team_2_captain, 'display_name') else (team_2_captain.name if hasattr(team_2_captain, 'name') else str(team_2_captain)))

        try:
            scheduled_events[event_id] = {
                'guild_id': interaction.guild.id if interaction.guild else None,
                'title': f"Round {round_label} Match",
                'datetime': event_datetime,
                'time_str': time_info['utc_time'],
                'date_str': f"{date:02d}/{month:02d}",
                'round': round_label,
                'group': group_label,
                'minutes_left': time_info['minutes_remaining'],
                'tournament': clean_t_id,
                'tournament_id': clean_t_id,
                'mode': mode,
                'game': game_hint,
                'judge': judge,
                'recorder': recorder,
                'remarks': remarks,
                'channel_id': interaction.channel.id,
                'team1_captain': team_1_captain,
                'team2_captain': team_2_captain,
                'team1_name': t1_final_name,
                'team2_name': t2_final_name,
                'team1_captain_name': team_1_captain.display_name if hasattr(team_1_captain, 'display_name') else str(team_1_captain),
                'team2_captain_name': team_2_captain.display_name if hasattr(team_2_captain, 'display_name') else str(team_2_captain),
                'match_name': f"{t1_final_name} vs {t2_final_name}",
                'status': 'scheduled'
            }
            save_scheduled_events(event_id)

            if judge:
                add_judge_assignment(judge.id, event_id)
                try:
                    await interaction.channel.set_permissions(
                        judge,
                        read_messages=True, send_messages=True, view_channel=True,
                        embed_links=True, attach_files=True, read_message_history=True
                    )
                    j_emoji = get_staff_emoji(interaction.guild, "judge")
                    await interaction.channel.send(content=f"{judge.mention} assigned as **judge** {j_emoji}")
                except Exception as e:
                    print(f"Error setting judge channel permissions: {e}")

            if recorder:
                try:
                    await interaction.channel.set_permissions(
                        recorder,
                        read_messages=True, send_messages=True, view_channel=True,
                        embed_links=True, attach_files=True, read_message_history=True
                    )
                    r_emoji = get_staff_emoji(interaction.guild, "recorder")
                    await interaction.channel.send(content=f"{recorder.mention} assigned as **recorder** {r_emoji}")
                except Exception as e:
                    print(f"Error setting recorder channel permissions: {e}")

            asyncio.create_task(sheetdb_post("Events", {
                "Guild_ID":          str(interaction.guild.id) if interaction.guild else "",
                "Timestamp":         datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "Event_ID":          event_id,
                "Tournament":        tournament_display,
                "Round":             round_label,
                "Group":             group_label or "",
                "Date":              f"{date:02d}/{month:02d}",
                "UTC_Time":          time_info['utc_time'],
                "Team1_Captain_ID":  str(team_1_captain.id),
                "Team1_Captain_Name": team_1_name if team_1_name else team_1_captain.name,
                "Team2_Captain_ID":  str(team_2_captain.id),
                "Team2_Captain_Name": team_2_name if team_2_name else team_2_captain.name,
                "Judge_ID":          str(judge.id) if judge else "",
                "Judge_Name":        judge.name if judge else "",
                "Recorder_ID":       str(recorder.id) if recorder else "",
                "Recorder_Name":     recorder.name if recorder else "",
                "Remarks":           remarks or "",
                "Channel_ID":        str(interaction.channel.id),
                "Status":            "Scheduled",
                "Created_By_ID":     str(interaction.user.id),
                "Created_By_Name":   interaction.user.name
            }))
            
            template_image = get_thumbnail_layer_path() or get_random_template(game_or_mode=game_hint)
            poster_image = None
            
            if template_image:
                try:
                    t1_poster = team_1_name if team_1_name else team_1_captain.name
                    t2_poster = team_2_name if team_2_name else team_2_captain.name
                    cfg = get_guild_config(interaction.guild.id) if interaction.guild else {}
                    org_name = cfg.get('organization_name') or (interaction.guild.name if interaction.guild else "Tournament Organizer")
                    server_logo = cfg.get('server_logo_path')
                    stage_label = f"{group_label} • ROUND {round_label}" if group_label else f"ROUND {round_label}"
                    
                    poster_image = await asyncio.to_thread(
                        create_event_poster,
                        template_image, 
                        stage_label, 
                        t1_poster, 
                        t2_poster, 
                        time_info['utc_time_simple'],
                        f"{date:02d}/{month:02d}/{current_year}",
                        server_name=org_name,
                        server_logo_path=server_logo,
                        tournament_title=tournament_display
                    )
                    if poster_image:
                        scheduled_events[event_id]['poster_path'] = poster_image
                        save_scheduled_events(event_id)
                except Exception as e:
                    print(f"Error creating poster: {e}")

            # Scheduled event in Discord
            try:
                event_datetime_aware = event_datetime.replace(tzinfo=datetime.timezone.utc)
                now_aware = datetime.datetime.now(datetime.timezone.utc)
                if event_datetime_aware <= now_aware:
                    event_datetime_aware = now_aware + datetime.timedelta(seconds=15)
                end_time_aware = event_datetime_aware + datetime.timedelta(minutes=45)
                
                t1_disp = team_1_name if team_1_name else team_1_captain.name
                t2_disp = team_2_name if team_2_name else team_2_captain.name
                
                image_bytes = None
                if poster_image and os.path.exists(poster_image):
                    with open(poster_image, 'rb') as img_f:
                        image_bytes = img_f.read()
                        
                scheduled_event = await interaction.guild.create_scheduled_event(
                    name=f"{t1_disp} vs {t2_disp}",
                    description=f"🏆 Tournament: {tournament_display}\n🔄 Round: {format_round_heading(round_label)}",
                    start_time=event_datetime_aware,
                    end_time=end_time_aware,
                    entity_type=discord.EntityType.external,
                    privacy_level=discord.PrivacyLevel.guild_only,
                    location=interaction.guild.name,
                    image=image_bytes
                )
                if scheduled_event:
                    scheduled_events[event_id]['scheduled_event_id'] = scheduled_event.id
                    save_scheduled_events(event_id)
            except Exception as e:
                print(f"Failed to create Discord scheduled event: {e}")

            t1_disp = team_1_name if team_1_name else team_1_captain.name
            t2_disp = team_2_name if team_2_name else team_2_captain.name
            embed = discord.Embed(
                title=f"🏆 {t1_disp} 🆚 {t2_disp}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            thumb_file, is_local_thumb = await resolve_embed_thumbnail(interaction.guild_id, embed, fallback_to_captain_avatar=team_1_captain)

            timestamp = int(event_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())
            event_details = f"**Tournament:** {tournament_display}\n"
            if mode: event_details += f"**Mode:** {mode}\n"
            event_details += f"**UTC Time:** {time_info['utc_time']}\n"
            event_details += f"**Local Time:** <t:{timestamp}:F> (<t:{timestamp}:R>)\n"
            event_details += f"**Round:** {format_round_heading(round_label)}\n"
            if group_label: event_details += f"**Group:** {group_label}\n"
            event_details += f"**Channel:** {interaction.channel.mention}"
            
            embed.add_field(name="📋 Event Details", value=event_details, inline=False)
            embed.add_field(name="\u200b", value="\u200b", inline=False)
            
            captains_text = f"**Captains**\n"
            captains_text += f"- Team1 Captain: {team_1_captain.mention} ({team_1_captain.name})" + (f" (Team: **{team_1_name}**)\n" if team_1_name else "\n")
            captains_text += f"- Team2 Captain: {team_2_captain.mention} ({team_2_captain.name})" + (f" (Team: **{team_2_name}**)" if team_2_name else "")
            embed.add_field(name="👑 Team Captains", value=captains_text, inline=False)
            embed.add_field(name="\u200b", value="\u200b", inline=False)

            if judge or recorder:
                staff_text = ""
                if judge:
                    staff_text += f"- **Judge:** {judge.mention}\n"
                if recorder:
                    staff_text += f"- **Recorder:** {recorder.mention}\n"
                embed.add_field(name="⚖️ Assigned Staff", value=staff_text.strip(), inline=False)
                embed.add_field(name="\u200b", value="\u200b", inline=False)

            if remarks:
                embed.add_field(name="💬 Remarks", value=remarks, inline=False)
                embed.add_field(name="\u200b", value="\u200b", inline=False)

            embed.add_field(name="👤 Created By", value=interaction.user.mention, inline=False)
            
            files_to_send = []
            if poster_image and os.path.exists(poster_image):
                try:
                    with open(poster_image, 'rb') as f:
                        poster_data = f.read()
                    file_obj = discord.File(fp=io.BytesIO(poster_data), filename="event_poster.png")
                    embed.set_image(url="attachment://event_poster.png")
                    files_to_send.append(file_obj)
                except Exception as e:
                    print(f"Error loading poster image: {e}")
                    
            if is_local_thumb and thumb_file and not poster_image:
                files_to_send.append(thumb_file)

            embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
            
            take_schedule_view = TakeScheduleButton(event_id, team_1_captain, team_2_captain, interaction.channel)
            await interaction.followup.send("✅ Event created and posted to both channels! Reminder will ping captains 10 minutes before start.", ephemeral=False)
            
            try:
                schedule_channel = get_tournament_schedule_channel(interaction.guild, clean_t_id) or interaction.channel
                staff_role_id = ROLE_IDS.get('staff') or ROLE_IDS.get('judge')
                staff_ping = f"<@&{staff_role_id}>" if staff_role_id else "@Staff"
                
                if files_to_send:
                    schedule_files = []
                    for file_obj in files_to_send:
                        file_obj.fp.seek(0)
                        schedule_files.append(discord.File(fp=io.BytesIO(file_obj.fp.read()), filename=file_obj.filename))
                    schedule_message = await schedule_channel.send(content=staff_ping, embed=embed, files=schedule_files, view=take_schedule_view)
                else:
                    schedule_message = await schedule_channel.send(content=staff_ping, embed=embed, view=take_schedule_view)
                    
                scheduled_events[event_id]['schedule_message_id'] = schedule_message.id
                scheduled_events[event_id]['schedule_channel_id'] = schedule_channel.id
                save_scheduled_events(event_id)
            except Exception as e:
                print(f"Error posting in schedule channel: {e}")

            try:
                if files_to_send:
                    current_files = []
                    for file_obj in files_to_send:
                        file_obj.fp.seek(0)
                        current_files.append(discord.File(fp=io.BytesIO(file_obj.fp.read()), filename=file_obj.filename))
                    await interaction.channel.send(embed=embed, files=current_files)
                else:
                    await interaction.channel.send(embed=embed)

                await schedule_ten_minute_reminder(event_id, team_1_captain, team_2_captain, None, interaction.channel, event_datetime)
            except Exception as e:
                print(f"Error posting in current channel: {e}")

        except Exception as e:
            print(f"Unhandled error in event_create: {e}")
            import traceback
            await interaction.followup.send(f"❌ An error occurred while creating the event: {e}", ephemeral=False)

    @app_commands.command(name="event-result", description="Add event results (Staff/Judge/Recorder/Helper)")
    @app_commands.describe(
        winner="Winner of the event (optional if team name is provided)",
        winner_score="Winner's score",
        loser="Loser of the event (optional if team name is provided)", 
        loser_score="Loser's score",
        tournament="Tournament name (e.g., The Zumwalt S2)",
        round="Round name (e.g., Semi-Final, Final, Quarter-Final)",
        group="Group assignment (A-J) - optional",
        remarks="Remarks about the match (e.g., ggwp, close match)",
        judge="Staff member who judged the match (optional, defaults to you)",
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
        ss_7="Screenshot 7 (upload)"
    )
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    @app_commands.choices(
        group=[
            app_commands.Choice(name="Group A", value="Group A"),
            app_commands.Choice(name="Group B", value="Group B"),
            app_commands.Choice(name="Group C", value="Group C"),
            app_commands.Choice(name="Group D", value="Group D"),
            app_commands.Choice(name="Group E", value="Group E"),
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
        self,
        interaction: discord.Interaction,
        winner_score: int,
        loser_score: int,
        tournament: str,
        round: str,
        winner: discord.Member = None,
        loser: discord.Member = None,
        group: app_commands.Choice[str] = None,
        remarks: str = "ggwp",
        judge: discord.Member = None,
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
        ss_7: discord.Attachment = None
    ):
        await interaction.response.defer(ephemeral=False)
        
        if not has_event_result_permission(interaction):
            await interaction.followup.send("❌ You need **Head Organizer**, **Judge**, **Recorder**, or **Helper/Staff** role to post event results.", ephemeral=False)
            return

        if not winner and not winner_team_name:
            await interaction.followup.send("❌ Please provide either a **Winner Member** or a **Winner Team Name**.", ephemeral=False)
            return
        if not loser and not loser_team_name:
            await interaction.followup.send("❌ Please provide either a **Loser Member** or a **Loser Team Name**.", ephemeral=False)
            return
        if winner_score < 0 or loser_score < 0:
            await interaction.followup.send("❌ Scores cannot be negative", ephemeral=False)
            return

        t_cfg_found = find_tournament_config(interaction.guild.id, tournament)
        t_display_name = t_cfg_found.get('name') if t_cfg_found else tournament

        group_label = group.value if group and isinstance(group, app_commands.Choice) else None
        w_name = winner_team_name if winner_team_name else (winner.name if winner else "Unknown")
        l_name = loser_team_name if loser_team_name else (loser.name if loser else "Unknown")
        w_mention = winner.mention if winner else f"**{winner_team_name}**"
        l_mention = loser.mention if loser else f"**{loser_team_name}**"
        dq_status = disqualified.value if disqualified and isinstance(disqualified, app_commands.Choice) else disqualified

        w_display_name = f"{w_name} (Disqualified)" if dq_status in ("Winner", "Both") else w_name
        l_display_name = f"{l_name} (Disqualified)" if dq_status in ("Loser", "Both") else l_name
        w_display_mention = f"{w_mention} (Disqualified)" if dq_status in ("Winner", "Both") else w_mention
        l_display_mention = f"{l_mention} (Disqualified)" if dq_status in ("Loser", "Both") else l_mention

        actual_judge = judge or interaction.user

        # 1. Locate or register event in scheduled_events early so links and metadata are preserved
        matched_ev_id = None
        for ev_id, ev_d in scheduled_events.items():
            if str(ev_d.get('channel_id')) == str(interaction.channel.id):
                matched_ev_id = ev_id
                break
        if not matched_ev_id:
            matched_ev_id = f"res_{interaction.id}"
            scheduled_events[matched_ev_id] = {
                'guild_id': interaction.guild.id,
                'channel_id': interaction.channel.id
            }
        ev_data = scheduled_events[matched_ev_id]
        ev_data.update({
            'tournament': t_display_name,
            'tournament_id': str(t_cfg_found.get('id', '')) if t_cfg_found else '',
            'round': round,
            'team1_name': w_name,
            'team2_name': l_name,
            'winner_score': winner_score,
            'loser_score': loser_score,
            'judge': actual_judge,
            'result_judge': actual_judge.name,
            'recorder': recorder,
            'match_name': f"{w_name} vs {l_name}",
            'status': 'completed',
            'completed_at': datetime.datetime.utcnow().isoformat()
        })

        now_utc = datetime.datetime.now(pytz.UTC)
        timestamp = int(now_utc.timestamp())
        
        embed_description = f"**Result UTC Time:** {now_utc.strftime('%Y-%m-%d %H:%M')}\n"
        embed_description += f"**Result Local Time:** <t:{timestamp}:f> (<t:{timestamp}:R>)\n\n"
        embed_description += f"**Tournament:** {t_display_name}\n"
        embed_description += f"**Round:** {format_round_heading(round)}"
        if group_label: embed_description += f"\n**Group:** {group_label}"
        embed_description += f"\n\n**Channel:** {interaction.channel.mention}"
        
        winner_badge = EMOJIS.get('winner', '🏆')

        embed = discord.Embed(
            title=f"{winner_badge} {w_display_name} 🆚 {l_display_name}",
            description=embed_description,
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        await resolve_embed_thumbnail(interaction.guild.id, embed)

        captains_text = f"{EMOJIS.get('captain', '👑')} **Captains**\n- Team1 Captain: {w_display_mention}" + (f" ({winner.name})" if winner else "") + f"\n- Team2 Captain: {l_display_mention}" + (f" ({loser.name})" if loser else "")
        embed.add_field(name="", value=captains_text, inline=False)
        
        results_text = f"{EMOJIS.get('trophy', '🏆')} **Results**\n{winner_badge} {w_name} ({winner_score}) {EMOJIS.get('vs', 'vs')} ({loser_score}) {l_name} {EMOJIS.get('skull', '💀')}"
        embed.add_field(name="", value=results_text, inline=False)
        
        staff_text = f"{EMOJIS.get('helpers', '👥')} **Staffs**\n▪ {EMOJIS.get('judge', '⚖️')} Judge: {actual_judge.mention}" + (f" ({actual_judge.name})" if actual_judge else "")
        if recorder: staff_text += f"\n▪ {EMOJIS.get('recorder', '📹')} Recorder: {recorder.mention}" + (f" ({recorder.name})" if recorder else "")
        embed.add_field(name="", value=staff_text, inline=False)

        # Include recording / VOD links if already uploaded on this event
        rec_emoji = EMOJIS.get('recorder', '📹')
        jdg_emoji = EMOJIS.get('judge', '⚖️')
        general_link = ev_data.get('recording_link')
        rec_link = ev_data.get('recorder_link')
        jdg_link = ev_data.get('judge_link')
        link_lines = []
        if general_link: link_lines.append(f"{rec_emoji} **Recording:** {format_links_markdown(general_link, 'Link')}")
        if rec_link:     link_lines.append(f"{rec_emoji} **Recorder VOD:** {format_links_markdown(rec_link, 'Link')}")
        if jdg_link:     link_lines.append(f"{jdg_emoji} **Judge VOD:** {format_links_markdown(jdg_link, 'Link')}")
        if link_lines:
            embed.add_field(name=f"{rec_emoji} Recordings / VODs", value="\n".join(link_lines), inline=False)

        embed.add_field(name="📝 Remarks", value=remarks, inline=False)
        
        screenshots = [ss_1, ss_2, ss_3, ss_4, ss_5, ss_6, ss_7]
        raw_screenshots = []
        screenshot_names = []
        for i, ss in enumerate(screenshots, 1):
            if ss:
                try:
                    b = await ss.read()
                    fn = f"SS-{i}_{ss.filename}"
                    raw_screenshots.append((fn, b))
                    screenshot_names.append(f"SS-{i}")
                except Exception as e:
                    print(f"Error reading screenshot {i}: {e}")

        if screenshot_names:
            embed.add_field(name="", value=f"{EMOJIS.get('folder', '📸')} **Screenshots of Result ({len(screenshot_names)} images)**\n📷 {' • '.join(screenshot_names)}", inline=False)

        embed.set_footer(text=f"Result uploaded by {interaction.user.name} · {now_utc.strftime('%d-%m-%Y %H:%M')}")

        # Credit staff stats from the result based on staff mentioned
        is_both = (
            actual_judge and recorder and 
            str(getattr(actual_judge, 'id', actual_judge)) == str(getattr(recorder, 'id', recorder))
        )
        if is_both:
            update_staff_stats(actual_judge, "judge_and_recorder", interaction.guild.id)
            ev_data['recorder_credited'] = True
        else:
            if actual_judge:
                update_staff_stats(actual_judge, "judge", interaction.guild.id)
            if recorder:
                update_staff_stats(recorder, "recorder", interaction.guild.id)
                ev_data['recorder_credited'] = True

        # Post in results channel and save message ID for VOD link updates
        res_msg = None
        results_channel = get_tournament_results_channel(interaction.guild, tournament)
        if results_channel:
            if raw_screenshots:
                files = [discord.File(fp=io.BytesIO(b), filename=fn) for fn, b in raw_screenshots]
                res_msg = await results_channel.send(embed=embed, files=files)
            else:
                res_msg = await results_channel.send(embed=embed)
            if res_msg:
                ev_data['results_message_id'] = res_msg.id
                ev_data['results_channel_id'] = results_channel.id

        # Post in ticket channel and record ticket_results_message_id
        ticket_msg = None
        if raw_screenshots:
            files = [discord.File(fp=io.BytesIO(b), filename=fn) for fn, b in raw_screenshots]
            ticket_msg = await interaction.channel.send(embed=embed, files=files)
        else:
            ticket_msg = await interaction.channel.send(embed=embed)
        if ticket_msg:
            ev_data['ticket_results_message_id'] = ticket_msg.id

        save_scheduled_events()
        asyncio.create_task(save_event_to_supabase(matched_ev_id, ev_data))

        # Check if links already exist on event and update results embed
        if ev_data.get('recorder_link') or ev_data.get('judge_link'):
            await update_results_embed_with_links(interaction.guild, ev_data)

        # Post Staff Attendance Log
        staff_attendance_channel = get_tournament_attendance_channel(interaction.guild, tournament)
        if staff_attendance_channel:
            try:
                att_embed = discord.Embed(
                    title=f"{EMOJIS['attendance_done']} Staff Attendance Log",
                    description=(
                        f"🏅 **{w_name}** vs **{l_name}**\n"
                        f"**Tournament:** {t_display_name}\n"
                        f"**Round:** {round}"
                        + (f"\n**Group:** {group_label}" if group_label else "")
                    ),
                    color=discord.Color(BRAND_COLOR),
                    timestamp=discord.utils.utcnow()
                )
                w_att_text = winner.mention if winner else f"**{w_name}**"
                l_att_text = loser.mention if loser else f"**{l_name}**"
                if dq_status in ("Winner", "Both"):
                    w_att_text += " (Disqualified)"
                if dq_status in ("Loser", "Both"):
                    l_att_text += " (Disqualified)"

                att_embed.add_field(
                    name=f"{winner_badge} Result",
                    value=f"**Winner/Team 1:** {w_att_text} `({winner_score})`\n**Loser/Team 2:** {l_att_text} `({loser_score})`",
                    inline=False
                )
                staff_val = f"{EMOJIS['judge']} **Judge:** {actual_judge.mention}"
                if recorder:
                    staff_val += f"\n{EMOJIS['recorder']} **Recorder:** {recorder.mention}"
                att_embed.add_field(name="👥 Staff on Duty", value=staff_val, inline=False)
                att_embed.add_field(name="📝 Remarks", value=remarks, inline=False)
                att_embed.set_footer(text=f"{ORGANIZATION_NAME} • Attendance")
                await staff_attendance_channel.send(embed=att_embed)
            except Exception as e:
                print(f"Error posting in Staff Attendance channel: {e}")

        # Retain completed match in scheduled_events JSON for links, stats, and result editing (7 days)
        asyncio.create_task(schedule_event_cleanup(matched_ev_id, delay_hours=168, keep_event_data=True))

        await interaction.followup.send(f"{EMOJIS['attendance_done']} Event results processed and posted successfully!", ephemeral=False)


    @app_commands.command(name="event-edit", description="Edit the event in this ticket channel")
    @app_commands.describe(
        team_1_captain="Captain of team 1 (optional)",
        team_2_captain="Captain of team 2 (optional)", 
        hour="Hour of the event (0-23) (optional)",
        minute="Minute of the event (0-59) (optional)",
        date="Date of the event (optional)",
        month="Month of the event (optional)",
        round="Round label (optional)",
        tournament="Tournament name (optional)",
        team_1_name="Optional name of team 1",
        team_2_name="Optional name of team 2"
    )
    @app_commands.autocomplete(tournament=tournament_autocomplete)
    @with_guild_context
    async def event_edit_cmd(
        self,
        interaction: discord.Interaction,
        team_1_captain: discord.Member = None,
        team_2_captain: discord.Member = None,
        hour: int = None,
        minute: int = None,
        date: int = None,
        month: int = None,
        round: str = None,
        tournament: str = None,
        team_1_name: str = None,
        team_2_name: str = None
    ):
        await interaction.response.defer(ephemeral=False)
        if not has_event_create_permission(interaction):
            await interaction.followup.send("❌ You don't have permission to edit events.", ephemeral=False)
            return

        current_channel_id = interaction.channel.id
        event_to_edit = None
        event_id = None
        for ev_id, ev_data in scheduled_events.items():
            if ev_data.get('channel_id') == current_channel_id:
                event_to_edit = ev_data
                event_id = ev_id
                break

        if not event_to_edit:
            await interaction.followup.send("❌ No event found in this ticket channel.", ephemeral=False)
            return

        # Check if at least one field is provided
        if not any([team_1_captain, team_2_captain, hour is not None, minute is not None, date is not None, month is not None, round, tournament, team_1_name is not None, team_2_name is not None]):
            await interaction.followup.send("❌ Please provide at least one field to update.", ephemeral=False)
            return

        # Validate inputs if provided
        if hour is not None and not (0 <= hour <= 23):
            await interaction.followup.send("❌ Hour must be between 0 and 23", ephemeral=False)
            return
        if minute is not None and not (0 <= minute <= 59):
            await interaction.followup.send("❌ Minute must be between 0 and 59", ephemeral=False)
            return
        if date is not None and not (1 <= date <= 31):
            await interaction.followup.send("❌ Date must be between 1 and 31", ephemeral=False)
            return
        if month is not None and not (1 <= month <= 12):
            await interaction.followup.send("❌ Month must be between 1 and 12", ephemeral=False)
            return

        old_datetime = event_to_edit.get('datetime')
        if isinstance(old_datetime, str):
            try: old_datetime = datetime.datetime.fromisoformat(old_datetime)
            except Exception: old_datetime = None
        old_time_str = event_to_edit.get('time_str', '')

        current_datetime = old_datetime or datetime.datetime.now()
        current_hour = hour if hour is not None else current_datetime.hour
        current_minute = minute if minute is not None else current_datetime.minute
        current_date = date if date is not None else current_datetime.day
        current_month = month if month is not None else current_datetime.month

        time_was_changed = any([hour is not None, minute is not None, date is not None, month is not None])
        new_datetime = datetime.datetime(datetime.datetime.now().year, current_month, current_date, current_hour, current_minute)
        time_info = calculate_time_difference(new_datetime)

        if team_1_captain:
            event_to_edit['team1_captain'] = team_1_captain
            event_to_edit['team1_captain_name'] = team_1_captain.display_name if hasattr(team_1_captain, 'display_name') else str(team_1_captain)
        if team_2_captain:
            event_to_edit['team2_captain'] = team_2_captain
            event_to_edit['team2_captain_name'] = team_2_captain.display_name if hasattr(team_2_captain, 'display_name') else str(team_2_captain)
        if team_1_name is not None:
            event_to_edit['team1_name'] = team_1_name
        if team_2_name is not None:
            event_to_edit['team2_name'] = team_2_name

        if time_was_changed:
            event_to_edit['datetime'] = new_datetime
            event_to_edit['time_str'] = time_info['utc_time']
            event_to_edit['date_str'] = f"{current_date:02d}/{current_month:02d}"
            event_to_edit['minutes_left'] = time_info['minutes_remaining']

        if round:
            event_to_edit['round'] = round
            event_to_edit['title'] = f"Round {round} Match"

        if tournament:
            t_configs = load_guild_tournaments(interaction.guild_id) if interaction.guild_id else {}
            clean_t_id = tournament.strip().lower()
            t_data_hint = t_configs.get(clean_t_id, {})
            if not t_data_hint:
                for tid, cfg in t_configs.items():
                    if cfg.get('name', '').strip().lower() == clean_t_id or tid.strip().lower() == clean_t_id:
                        t_data_hint = cfg
                        clean_t_id = tid
                        break
            event_to_edit['tournament'] = clean_t_id
            event_to_edit['tournament_id'] = clean_t_id
            if t_data_hint.get('mode'):
                event_to_edit['mode'] = t_data_hint.get('mode')
            if t_data_hint.get('game'):
                event_to_edit['game'] = t_data_hint.get('game')

        # Resolve updated names and captain members
        t1_cap = event_to_edit.get('team1_captain')
        t2_cap = event_to_edit.get('team2_captain')
        t1_disp = event_to_edit.get('team1_name') or (t1_cap.display_name if hasattr(t1_cap, 'display_name') else getattr(t1_cap, 'name', 'Team 1'))
        t2_disp = event_to_edit.get('team2_name') or (t2_cap.display_name if hasattr(t2_cap, 'display_name') else getattr(t2_cap, 'name', 'Team 2'))
        event_to_edit['match_name'] = f"{t1_disp} vs {t2_disp}"

        t1_cap_member = t1_cap if isinstance(t1_cap, discord.Member) else (interaction.guild.get_member(int(t1_cap)) if (interaction.guild and str(t1_cap).isdigit()) else None)
        t2_cap_member = t2_cap if isinstance(t2_cap, discord.Member) else (interaction.guild.get_member(int(t2_cap)) if (interaction.guild and str(t2_cap).isdigit()) else None)
        judge_val = event_to_edit.get('judge')
        judge_member = judge_val if isinstance(judge_val, discord.Member) else (interaction.guild.get_member(int(judge_val)) if (interaction.guild and str(judge_val).isdigit()) else None)
        recorder_val = event_to_edit.get('recorder')
        recorder_member = recorder_val if isinstance(recorder_val, discord.Member) else (interaction.guild.get_member(int(recorder_val)) if (interaction.guild and str(recorder_val).isdigit()) else None)

        save_scheduled_events()

        # Update poster image if template exists
        cfg = get_guild_config(interaction.guild.id) if interaction.guild else {}
        server_logo = cfg.get('server_logo_path')
        tournament_label = event_to_edit.get('tournament') or 'Tournament'
        t_confs = load_guild_tournaments(interaction.guild.id) if interaction.guild else {}
        if tournament_label.lower() in t_confs:
            tournament_display = t_confs[tournament_label.lower()].get('name') or tournament_label
        else:
            tournament_display = tournament_label

        template_image = get_thumbnail_layer_path() or get_random_template(game_or_mode=event_to_edit.get('game') or tournament_label)
        poster_image = None
        if template_image:
            try:
                # Remove old poster if exists
                old_poster = event_to_edit.get('poster_path')
                if old_poster and os.path.exists(old_poster):
                    try: os.remove(old_poster)
                    except Exception: pass

                round_label = event_to_edit.get('round', 'R1')
                group_label = event_to_edit.get('group')
                stage_label = f"{group_label} • ROUND {round_label}" if group_label else f"ROUND {round_label}"
                org_name = cfg.get('organization_name') or (interaction.guild.name if interaction.guild else "Tournament Organizer")
                poster_image = await asyncio.to_thread(
                    create_event_poster,
                    template_image,
                    stage_label,
                    t1_disp,
                    t2_disp,
                    time_info['utc_time_simple'],
                    f"{new_datetime.day:02d}/{new_datetime.month:02d}/{new_datetime.year}",
                    server_name=org_name,
                    server_logo_path=server_logo,
                    tournament_title=tournament_display
                )
                if poster_image:
                    event_to_edit['poster_path'] = poster_image
                    save_scheduled_events()
            except Exception as e:
                print(f"Error updating poster in event-edit: {e}")

        # 1. Update Discord Scheduled Event if present
        disc_ev_id = event_to_edit.get('scheduled_event_id')
        if disc_ev_id and interaction.guild:
            try:
                disc_ev = interaction.guild.get_scheduled_event(int(disc_ev_id))
                if not disc_ev:
                    disc_ev = await interaction.guild.fetch_scheduled_event(int(disc_ev_id))
                if disc_ev:
                    event_datetime_aware = new_datetime.replace(tzinfo=datetime.timezone.utc)
                    now_aware = datetime.datetime.now(datetime.timezone.utc)
                    if event_datetime_aware <= now_aware:
                        event_datetime_aware = now_aware + datetime.timedelta(seconds=15)
                    end_time_aware = event_datetime_aware + datetime.timedelta(minutes=45)

                    round_info = event_to_edit.get('round', 'Round')
                    desc_str = f"🏆 Tournament: {tournament_display}\n🔄 Round: {format_round_heading(round_info)}"
                    img_bytes = None
                    if poster_image and os.path.exists(poster_image):
                        try:
                            with open(poster_image, 'rb') as f_img:
                                img_bytes = f_img.read()
                        except Exception: pass

                    kwargs = {
                        "name": f"{t1_disp} vs {t2_disp}",
                        "description": desc_str,
                        "start_time": event_datetime_aware,
                        "end_time": end_time_aware,
                        "location": interaction.guild.name
                    }
                    if img_bytes:
                        kwargs["image"] = img_bytes
                    try:
                        await disc_ev.edit(**kwargs)
                    except Exception:
                        kwargs.pop("image", None)
                        await disc_ev.edit(**kwargs)
            except Exception as e:
                print(f"Failed to update Discord scheduled event: {e}")

        # 2. Reschedule 10-Minute Reminder
        if event_id in reminder_tasks:
            try: reminder_tasks[event_id].cancel()
            except Exception: pass
        try:
            await schedule_ten_minute_reminder(event_id, t1_cap_member, t2_cap_member, judge_member, interaction.channel, new_datetime)
        except Exception as e:
            print(f"Error rescheduling reminder: {e}")

        # 3. Post Time Changed notification in channel if time was modified
        if time_was_changed:
            try:
                old_ts_val = int(old_datetime.replace(tzinfo=datetime.timezone.utc).timestamp()) if old_datetime else None
                new_ts_val = int(new_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())
                old_time_display = f"<t:{old_ts_val}:F>" if old_ts_val else (old_time_str or "Unknown")
                new_time_display = f"<t:{new_ts_val}:F>"

                pings = []
                if t1_cap_member: pings.append(t1_cap_member.mention)
                elif t1_cap: pings.append(f"<@{getattr(t1_cap, 'id', t1_cap)}>")
                if t2_cap_member: pings.append(t2_cap_member.mention)
                elif t2_cap: pings.append(f"<@{getattr(t2_cap, 'id', t2_cap)}>")
                if judge_member: pings.append(judge_member.mention)
                elif judge_val: pings.append(f"<@{getattr(judge_val, 'id', judge_val)}>")
                if recorder_member: pings.append(recorder_member.mention)
                elif recorder_val: pings.append(f"<@{getattr(recorder_val, 'id', recorder_val)}>")

                ping_text = " ".join(pings) if pings else ""
                tc_embed = discord.Embed(
                    title="⏰ Match Time Updated",
                    description="The scheduled time for this match has been **updated**.\nPlease take note of the new schedule.",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow()
                )
                tc_embed.add_field(name="🗓️ Old Time", value=old_time_display, inline=True)
                tc_embed.add_field(name="🆕 New Time", value=f"{new_time_display} (<t:{new_ts_val}:R>)", inline=True)
                tc_embed.add_field(name="⚔️ Match", value=f"**{t1_disp}** vs **{t2_disp}**", inline=False)
                tc_embed.set_footer(text=f"{cfg.get('organization_name', ORGANIZATION_NAME)} • Match Rescheduled")
                if ping_text:
                    await interaction.channel.send(content=f"📣 {ping_text}", embed=tc_embed)
                else:
                    await interaction.channel.send(embed=tc_embed)
            except Exception as e:
                print(f"Error sending time-changed notification: {e}")

        # 4. Update the `#take-schedule` message in schedule channel
        try:
            take_schedule_view = TakeScheduleButton(event_id, t1_cap_member or t1_cap, t2_cap_member or t2_cap, interaction.channel)
            schedule_embed = discord.Embed(
                title=f"🏆 {t1_disp} 🆚 {t2_disp}",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            thumb_file, is_local_thumb = await resolve_embed_thumbnail(interaction.guild_id, schedule_embed, fallback_to_captain_avatar=t1_cap_member)
            timestamp = int(new_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())
            round_lbl = event_to_edit.get('round', 'R1')
            grp_lbl = event_to_edit.get('group')

            event_details = f"**Tournament:** {tournament_display}\n"
            if event_to_edit.get('mode'): event_details += f"**Mode:** {event_to_edit.get('mode')}\n"
            event_details += f"**UTC Time:** {time_info['utc_time']}\n"
            event_details += f"**Local Time:** <t:{timestamp}:F> (<t:{timestamp}:R>)\n"
            event_details += f"**Round:** {format_round_heading(round_lbl)}\n"
            if grp_lbl: event_details += f"**Group:** {grp_lbl}\n"
            event_details += f"**Channel:** {interaction.channel.mention}"

            schedule_embed.add_field(name="📋 Event Details", value=event_details, inline=False)
            schedule_embed.add_field(name="\u200b", value="\u200b", inline=False)

            t1_ping = t1_cap_member.mention if t1_cap_member else f"<@{getattr(t1_cap, 'id', t1_cap)}>"
            t2_ping = t2_cap_member.mention if t2_cap_member else f"<@{getattr(t2_cap, 'id', t2_cap)}>"
            t1_name_val = event_to_edit.get('team1_name')
            t2_name_val = event_to_edit.get('team2_name')
            cap_text = f"**Captains**\n- Team1 Captain: {t1_ping}" + (f" (Team: **{t1_name_val}**)\n" if t1_name_val else "\n")
            cap_text += f"- Team2 Captain: {t2_ping}" + (f" (Team: **{t2_name_val}**)" if t2_name_val else "")
            schedule_embed.add_field(name="👑 Team Captains", value=cap_text, inline=False)
            schedule_embed.add_field(name="\u200b", value="\u200b", inline=False)

            if judge_val or recorder_val:
                staff_info = ""
                if judge_val:
                    j_mention = judge_member.mention if judge_member else f"<@{getattr(judge_val, 'id', judge_val)}>"
                    staff_info += f"- **Judge:** {j_mention}\n"
                if recorder_val:
                    r_mention = recorder_member.mention if recorder_member else f"<@{getattr(recorder_val, 'id', recorder_val)}>"
                    staff_info += f"- **Recorder:** {r_mention}\n"
                schedule_embed.add_field(name="⚖️ Assigned Staff", value=staff_info.strip(), inline=False)
                schedule_embed.add_field(name="\u200b", value="\u200b", inline=False)

            schedule_embed.add_field(name="👤 Created/Updated By", value=interaction.user.mention, inline=False)
            schedule_embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")

            files_to_send = []
            if poster_image and os.path.exists(poster_image):
                try:
                    with open(poster_image, 'rb') as f_p:
                        p_data = f_p.read()
                    f_obj = discord.File(fp=io.BytesIO(p_data), filename="event_poster.png")
                    schedule_embed.set_image(url="attachment://event_poster.png")
                    files_to_send.append(f_obj)
                except Exception as e:
                    print(f"Error loading poster for schedule update: {e}")

            if is_local_thumb and thumb_file and not poster_image:
                files_to_send.append(thumb_file)

            clean_t_id = event_to_edit.get('tournament', '')
            schedule_channel = get_tournament_schedule_channel(interaction.guild, clean_t_id) or interaction.channel
            old_sched_msg_id = event_to_edit.get('schedule_message_id')
            old_sched_chan_id = event_to_edit.get('schedule_channel_id')

            edited_in_place = False
            # Edit existing schedule message in-place if it exists
            if old_sched_msg_id and interaction.guild:
                try:
                    ch_to_use = schedule_channel
                    if old_sched_chan_id:
                        ch_to_use = interaction.guild.get_channel(int(old_sched_chan_id)) or await interaction.guild.fetch_channel(int(old_sched_chan_id))
                    if ch_to_use:
                        old_msg = await ch_to_use.fetch_message(int(old_sched_msg_id))
                        if old_msg:
                            if files_to_send:
                                sched_files = []
                                for fo in files_to_send:
                                    fo.fp.seek(0)
                                    sched_files.append(discord.File(fp=io.BytesIO(fo.fp.read()), filename=fo.filename))
                                await old_msg.edit(embed=schedule_embed, attachments=sched_files, view=take_schedule_view)
                            else:
                                await old_msg.edit(embed=schedule_embed, view=take_schedule_view)
                            edited_in_place = True
                except Exception as edit_err:
                    print(f"Could not edit schedule message in-place: {edit_err}")

            if not edited_in_place:
                staff_role_id = ROLE_IDS.get('staff') or ROLE_IDS.get('judge')
                staff_ping = f"<@&{staff_role_id}>" if staff_role_id else "@Staff"
                if files_to_send:
                    sched_files = []
                    for fo in files_to_send:
                        fo.fp.seek(0)
                        sched_files.append(discord.File(fp=io.BytesIO(fo.fp.read()), filename=fo.filename))
                    new_sched_msg = await schedule_channel.send(content=staff_ping, embed=schedule_embed, files=sched_files, view=take_schedule_view)
                else:
                    new_sched_msg = await schedule_channel.send(content=staff_ping, embed=schedule_embed, view=take_schedule_view)

                if new_sched_msg:
                    event_to_edit['schedule_message_id'] = new_sched_msg.id
                    event_to_edit['schedule_channel_id'] = schedule_channel.id
                    save_scheduled_events()
        except Exception as e:
            print(f"Error updating schedule channel message: {e}")

        # 5. Sync to Supabase
        try:
            await save_event_to_supabase(event_id, event_to_edit)
        except Exception as e:
            print(f"Error syncing updated event to Supabase: {e}")

        # Confirmation message
        summary_lines = [f"⚔️ **Match:** {t1_disp} vs {t2_disp}"]
        if time_was_changed:
            summary_lines.append(f"⏰ **Time:** <t:{int(new_datetime.replace(tzinfo=datetime.timezone.utc).timestamp())}:F>")
        if round:
            summary_lines.append(f"🔄 **Round:** {round}")
        if tournament:
            summary_lines.append(f"🏆 **Tournament:** {tournament_display}")

        embed_confirm = discord.Embed(
            title="✅ Event Details Updated",
            description="\n".join(summary_lines),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed_confirm.set_footer(text=f"{ORGANIZATION_NAME} • Event Management")
        await interaction.followup.send(embed=embed_confirm, ephemeral=False)

    @app_commands.command(name="event-delete", description="Delete a scheduled event")
    @with_guild_context
    async def event_delete_cmd(self, interaction: discord.Interaction):
        if not has_event_create_permission(interaction):
            await interaction.response.send_message("❌ Permission denied.", ephemeral=False)
            return

        guild_events = []
        for ev_id, ev_data in scheduled_events.items():
            if str(ev_data.get('guild_id')) != str(interaction.guild.id):
                continue
            if is_event_over(ev_data):
                continue
            t1, t2 = resolve_event_names(ev_data, interaction.guild)
            round_label = ev_data.get('round') or 'Round'
            time_part = ev_data.get('time_str') or ev_data.get('date_str') or ""
            desc = f"{round_label} • {time_part}" if time_part else f"{round_label}"
            guild_events.append(
                discord.SelectOption(
                    label=f"{t1} vs {t2}"[:100],
                    description=desc[:100],
                    value=ev_id
                )
            )

        if not guild_events:
            await interaction.response.send_message("❌ No active scheduled events found to delete.", ephemeral=False)
            return

        class EventDeleteView(View):
            def __init__(self):
                super().__init__(timeout=60)
                self.select_event.options = guild_events[:25]

            @discord.ui.select(placeholder="Select an event to delete...", options=guild_events[:25])
            async def select_event(self, select_interaction: discord.Interaction, select: discord.ui.Select):
                selected_event_id = select.values[0]
                ev_to_delete = scheduled_events.get(selected_event_id, {})
                t1_d, t2_d = resolve_event_names(ev_to_delete, select_interaction.guild)
                
                # Cancel/Disable the schedule announcement message in schedule channel
                sch_ch_id = ev_to_delete.get('schedule_channel_id')
                sch_msg_id = ev_to_delete.get('schedule_message_id')
                if sch_ch_id and sch_msg_id and select_interaction.guild:
                    try:
                        sch_channel = select_interaction.guild.get_channel(int(sch_ch_id))
                        if not sch_channel:
                            sch_channel = await select_interaction.guild.fetch_channel(int(sch_ch_id))
                        if sch_channel:
                            sch_msg = await sch_channel.fetch_message(int(sch_msg_id))
                            if sch_msg:
                                cancelled_embed = sch_msg.embeds[0] if sch_msg.embeds else discord.Embed()
                                cancelled_embed.title = f"🛑 Event Cancelled / Deleted — {t1_d} vs {t2_d}"
                                cancelled_embed.color = discord.Color.red()
                                cancelled_embed.description = f"⚠️ This match has been cancelled/deleted by {select_interaction.user.mention}."
                                await sch_msg.edit(embed=cancelled_embed, view=None)
                    except Exception as sch_err:
                        print(f"Error updating schedule message on event delete: {sch_err}")

                # Cancel Discord scheduled event if present
                disc_ev_id = ev_to_delete.get('scheduled_event_id')
                if disc_ev_id and select_interaction.guild:
                    try:
                        disc_ev = select_interaction.guild.get_scheduled_event(int(disc_ev_id))
                        if disc_ev:
                            await disc_ev.delete()
                    except Exception:
                        pass

                # Remove active judge assignment
                j_assigned = ev_to_delete.get('judge')
                if j_assigned:
                    j_uid = getattr(j_assigned, 'id', j_assigned)
                    if j_uid and str(j_uid).strip().isdigit():
                        try:
                            remove_judge_assignment(int(j_uid), selected_event_id)
                        except Exception:
                            pass

                ev_to_delete['status'] = 'cancelled'
                if selected_event_id in scheduled_events:
                    del scheduled_events[selected_event_id]
                    save_scheduled_events()
                if selected_event_id in reminder_tasks:
                    reminder_tasks[selected_event_id].cancel()

                # Also mark or delete in Supabase if client exists
                if supabase_client:
                    try:
                        await asyncio.to_thread(
                            lambda: supabase_client.table("Matches").update({"Status": "cancelled"}).eq("Match_ID", selected_event_id).execute()
                        )
                    except Exception:
                        pass

                await select_interaction.response.edit_message(
                    content=f"✅ Event **{t1_d} vs {t2_d}** (`{selected_event_id}`) has been deleted.",
                    embed=None,
                    view=None
                )

        await interaction.response.send_message("Select an event to delete:", view=EventDeleteView(), ephemeral=False)

    @app_commands.command(name="general_tie_breaker", description="To break a tie between two teams using the highest total score")
    @app_commands.describe(
        tm1_name="Name of team 1",
        tm1_score="Total score of team 1",
        tm2_name="Name of team 2",
        tm2_score="Total score of team 2"
    )
    @with_guild_context
    async def general_tie_breaker(
        self,
        interaction: discord.Interaction,
        tm1_score: int,
        tm2_score: int,
        tm1_name: str = "Alpha",
        tm2_name: str = "Bravo"
    ):
        if tm1_score > tm2_score:
            winner = tm1_name
            winner_total = tm1_score
            loser = tm2_name
            loser_total = tm2_score
        elif tm2_score > tm1_score:
            winner = tm2_name
            winner_total = tm2_score
            loser = tm1_name
            loser_total = tm1_score
        else:
            winner = "TIE"
            winner_total = tm1_score
            loser_total = tm2_score

        embed = discord.Embed(
            title="⚔️ Tie Breaker Result",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        if winner == "TIE":
            embed.add_field(name="🤝 Result", value=f"**STILL TIED!** Both teams scored {winner_total} points.")
        else:
            embed.add_field(name=f"{EMOJIS['trophy']} Winner", value=f"**{winner}** wins with {winner_total} points against **{loser}** ({loser_total} points)!")
        await interaction.response.send_message(embed=embed)


    @app_commands.command(name="event-result-edit", description="Edit a previously posted match result (Head Organizer/Judge/Staff)")
    @app_commands.describe(
        match="Select the match to edit (type name or ID to search)",
        winner="Updated winner member (optional)",
        winner_team_name="Updated winner team name (optional)",
        loser="Updated loser member (optional)",
        loser_team_name="Updated loser team name (optional)",
        winner_score="Updated winner score (optional)",
        loser_score="Updated loser score (optional)",
        remarks="Updated match remarks (optional)",
        disqualified="Update disqualification status (optional)",
        judge="Updated judge member (optional)",
        recorder="Updated recorder member (optional)"
    )
    @app_commands.choices(
        disqualified=[
            app_commands.Choice(name="Winner Disqualified", value="Winner"),
            app_commands.Choice(name="Loser Disqualified", value="Loser"),
            app_commands.Choice(name="Both Disqualified (0:0)", value="Both"),
            app_commands.Choice(name="None (Clear DQ)", value="None"),
        ]
    )
    @app_commands.autocomplete(match=match_autocomplete)
    @with_guild_context
    async def event_result_edit_cmd(
        self,
        interaction: discord.Interaction,
        match: str,
        winner: discord.Member = None,
        winner_team_name: str = None,
        loser: discord.Member = None,
        loser_team_name: str = None,
        winner_score: int = None,
        loser_score: int = None,
        remarks: str = None,
        disqualified: app_commands.Choice[str] = None,
        judge: discord.Member = None,
        recorder: discord.Member = None
    ):
        await handle_event_result_edit(
            interaction, match, winner, winner_team_name, loser, loser_team_name,
            winner_score, loser_score, remarks, disqualified, judge, recorder
        )

    @app_commands.command(name="thumbnail-create", description="Generate a high-end esports match thumbnail poster (1920x1080)")
    @app_commands.describe(
        tournament_title="Tournament Championship Title (e.g. ETERNAL FRIGATE CHAMPIONSHIP S3)",
        stage_round="Stage & Round (e.g. GROUP B • ROUND 3)",
        team1="Name of Team or Player 1 (e.g. TEASAN21)",
        team2="Name of Team or Player 2 (e.g. HOKAGE_141)",
        time="Match Time (e.g. 04:00 UTC)",
        date="Match Date (e.g. 13/09/2026 or SUNDAY, 13-09-26)",
        server="Server or Host Name (e.g. ETERNAL ESPORTS ASIA)",
        game="Game Category for background artwork (e.g. Modern Warship)"
    )
    @app_commands.autocomplete(game=game_autocomplete)
    @with_guild_context
    async def thumbnail_create_cmd(
        self,
        interaction: discord.Interaction,
        tournament_title: str,
        stage_round: str,
        team1: str,
        team2: str,
        time: str = "04:00 UTC",
        date: str = None,
        server: str = None,
        game: str = "Modern Warship"
    ):
        await interaction.response.defer(ephemeral=False)
        cfg = get_guild_config(interaction.guild.id) if interaction.guild else {}
        server_name = server or cfg.get('organization_name') or (interaction.guild.name if interaction.guild else "Tournament Organizer")
        server_logo = cfg.get('server_logo_path')
        template_img = get_random_template(game_or_mode=game)
        
        poster_path = await asyncio.to_thread(
            create_esports_match_poster,
            template_path=template_img,
            round_label=stage_round,
            team1_name=team1,
            team2_name=team2,
            utc_time=time,
            date_str=date,
            server_name=server_name,
            server_logo_path=server_logo,
            tournament_title=tournament_title
        )
        
        if not poster_path or not os.path.exists(poster_path):
            await interaction.followup.send("❌ Failed to generate thumbnail poster.", ephemeral=True)
            return
            
        file = discord.File(poster_path, filename="match_thumbnail.png")
        embed = discord.Embed(
            title=f"🎮 {tournament_title}",
            description=f"**{team1}** vs **{team2}**\n🏆 **Stage:** `{stage_round}`\n⏰ **Time:** `{time}`\n📅 **Date:** `{date or 'Today'}`",
            color=0x2ecc71
        )
        embed.set_image(url="attachment://match_thumbnail.png")
        embed.set_footer(text=f"Resolution: 1920x1080 • Generated for {server_name}")
        await interaction.followup.send(file=file, embed=embed)


async def handle_event_result_edit(
    interaction: discord.Interaction,
    match: str,
    winner: discord.Member = None,
    winner_team_name: str = None,
    loser: discord.Member = None,
    loser_team_name: str = None,
    winner_score: int = None,
    loser_score: int = None,
    remarks: str = None,
    disqualified: app_commands.Choice[str] = None,
    judge: discord.Member = None,
    recorder: discord.Member = None
):
    await interaction.response.defer(ephemeral=False)
    if not has_event_result_permission(interaction):
        await interaction.followup.send("❌ You need **Head Organizer**, **Judge**, **Recorder**, or **Helper/Staff** role to edit match results.", ephemeral=False)
        return

    ev_id, ev_data = find_event_by_name_or_id(interaction.guild.id, match)
    if not ev_id or not ev_data:
        await interaction.followup.send("❌ Match not found. Please select from the autocomplete dropdown or provide a valid Match ID/Name.", ephemeral=False)
        return

    if not any([winner, winner_team_name, loser, loser_team_name, winner_score is not None, loser_score is not None, remarks, disqualified, judge, recorder]):
        await interaction.followup.send("❌ Please provide at least one field to update.", ephemeral=False)
        return

    changes = []
    if winner:
        ev_data['team1_captain'] = winner.id
        ev_data['team1_name'] = winner.display_name
        changes.append(f"Winner: {winner.mention}")
    if winner_team_name:
        ev_data['team1_name'] = winner_team_name
        changes.append(f"Winner Team: `{winner_team_name}`")
    if loser:
        ev_data['team2_captain'] = loser.id
        ev_data['team2_name'] = loser.display_name
        changes.append(f"Loser: {loser.mention}")
    if loser_team_name:
        ev_data['team2_name'] = loser_team_name
        changes.append(f"Loser Team: `{loser_team_name}`")
    if winner_score is not None:
        ev_data['winner_score'] = winner_score
        changes.append(f"Winner Score: `{winner_score}`")
    if loser_score is not None:
        ev_data['loser_score'] = loser_score
        changes.append(f"Loser Score: `{loser_score}`")
    if remarks:
        ev_data['remarks'] = remarks
        changes.append(f"Remarks: `{remarks}`")
    if disqualified:
        if disqualified.value == "None":
            ev_data.pop('disqualified', None)
            changes.append("Disqualified: `Cleared`")
        else:
            ev_data['disqualified'] = disqualified.value
            changes.append(f"Disqualified: `{disqualified.name}`")

    guild_id = interaction.guild.id
    if judge:
        old_judge = ev_data.get('judge')
        ev_data['judge'] = judge
        ev_data['result_judge'] = judge.name
        changes.append(f"Judge: {judge.mention}")
        if old_judge and getattr(old_judge, 'id', old_judge) != judge.id:
            old_j_id = str(getattr(old_judge, 'id', old_judge))
            stats = get_guild_staff_stats(guild_id)
            if old_j_id in stats:
                stats[old_j_id]['judge_count'] = max(0, int(stats[old_j_id].get('judge_count', 1)) - 1)
                save_guild_staff_stats(guild_id, stats)
            update_staff_stats(judge, "judge", guild_id)

    if recorder:
        old_rec = ev_data.get('recorder')
        ev_data['recorder'] = recorder
        changes.append(f"Recorder: {recorder.mention}")
        if old_rec and getattr(old_rec, 'id', old_rec) != recorder.id:
            old_r_id = str(getattr(old_rec, 'id', old_rec))
            stats = get_guild_staff_stats(guild_id)
            if old_r_id in stats:
                stats[old_r_id]['recorder_count'] = max(0, int(stats[old_r_id].get('recorder_count', 1)) - 1)
                save_guild_staff_stats(guild_id, stats)
            update_staff_stats(recorder, "recorder", guild_id)
            ev_data['recorder_credited'] = True

    t1_n = ev_data.get('team1_name') or 'Team 1'
    t2_n = ev_data.get('team2_name') or 'Team 2'
    ev_data['match_name'] = f"{t1_n} vs {t2_n}"

    save_scheduled_events()
    asyncio.create_task(save_event_to_supabase(ev_id, ev_data))

    embed_note = ""
    try:
        updated = await update_results_message_embed(interaction.guild, ev_data)
        if updated:
            embed_note = "\n✅ Result message in results channel was automatically updated!"
    except Exception as e:
        print(f"Error updating result embed in event_result_edit: {e}")

    result_embed = discord.Embed(
        title=f"✅ Match Result Edited — `{ev_id}`",
        description=f"**Match:** {ev_data.get('match_name')}\n\n" + "\n".join(f"• {c}" for c in changes) + embed_note,
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    result_embed.set_footer(text=f"{ORGANIZATION_NAME} • Match Result Edit")
    await interaction.followup.send(embed=result_embed, ephemeral=False)

    log_embed = discord.Embed(
        title="✏️ Match Result Edited",
        description=f"**{interaction.user.display_name}** edited result for `{ev_id}` ({ev_data.get('match_name')}).\n\n" + "\n".join(f"• {c}" for c in changes),
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.set_footer(text=f"Edited by {interaction.user.display_name}")
    await log_bot_activity(interaction.guild, log_embed)


result_group = app_commands.Group(name="result", description="Manage tournament match results")

@result_group.command(name="edit", description="Edit a previously posted match result (Head Organizer/Judge/Staff)")
@app_commands.describe(
    match="Select the match to edit (type name or ID to search)",
    winner="Updated winner member (optional)",
    winner_team_name="Updated winner team name (optional)",
    loser="Updated loser member (optional)",
    loser_team_name="Updated loser team name (optional)",
    winner_score="Updated winner score (optional)",
    loser_score="Updated loser score (optional)",
    remarks="Updated match remarks (optional)",
    disqualified="Update disqualification status (optional)",
    judge="Updated judge member (optional)",
    recorder="Updated recorder member (optional)"
)
@app_commands.choices(
    disqualified=[
        app_commands.Choice(name="Winner Disqualified", value="Winner"),
        app_commands.Choice(name="Loser Disqualified", value="Loser"),
        app_commands.Choice(name="Both Disqualified (0:0)", value="Both"),
        app_commands.Choice(name="None (Clear DQ)", value="None"),
    ]
)
@app_commands.autocomplete(match=match_autocomplete)
@with_guild_context
async def result_edit(
    interaction: discord.Interaction,
    match: str,
    winner: discord.Member = None,
    winner_team_name: str = None,
    loser: discord.Member = None,
    loser_team_name: str = None,
    winner_score: int = None,
    loser_score: int = None,
    remarks: str = None,
    disqualified: app_commands.Choice[str] = None,
    judge: discord.Member = None,
    recorder: discord.Member = None
):
    await handle_event_result_edit(
        interaction, match, winner, winner_team_name, loser, loser_team_name,
        winner_score, loser_score, remarks, disqualified, judge, recorder
    )


async def setup(bot: commands.Bot):
    bot.tree.add_command(result_group)
    await bot.add_cog(Events(bot))
