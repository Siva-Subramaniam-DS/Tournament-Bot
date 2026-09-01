import os
import io
import re
import json
import asyncio
import datetime
from typing import Optional

import discord
from discord.ext import commands
import pytz

from core.config import (
    BASE_DIR, BOT_OWNER_ID, ORGANIZATION_NAME,
    DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS
)
from core.state import (
    current_guild_id, with_guild_context,
    ROLE_IDS, CHANNEL_IDS, scheduled_events, save_scheduled_events,
    scheduled_deadlines, reminder_tasks, cleanup_tasks
)
from core.database import (
    supabase_client, load_guild_tournaments, get_guild_config,
    get_active_tournament_config, get_guild_rules, save_guild_rules,
    get_guild_staff_stats, save_guild_staff_stats, log_bot_activity
)
from core.transcript import (
    generate_html_transcript, generate_text_transcript, build_transcript_files
)

from cogs.staff import (
    TakeScheduleButton, StaffConfirmationView, StaffReplacementView
)
from cogs.events import schedule_ten_minute_reminder


class Listeners(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"✅ Bot is online as {self.bot.user}")
        print(f"🆔 Bot ID: {self.bot.user.id}")
        print(f"📊 Connected to {len(self.bot.guilds)} guild(s)")

        # Reschedule reminders and register persistent views
        now_utc = datetime.datetime.now(pytz.UTC)
        for ev_id, ev_data in list(scheduled_events.items()):
            dt = ev_data.get('datetime')
            ch_id = ev_data.get('channel_id')
            
            try:
                t1 = ev_data.get('team1_captain')
                t2 = ev_data.get('team2_captain')
                j = ev_data.get('judge')
                r = ev_data.get('recorder')
                
                self.bot.add_view(TakeScheduleButton(ev_id, t1, t2))
                self.bot.add_view(StaffConfirmationView(ev_id, j, r))
                
                j_confirmed = ev_data.get('judge_confirmed', False)
                r_confirmed = ev_data.get('recorder_confirmed', False)
                j_replaced = ev_data.get('judge_replaced', False)
                r_replaced = ev_data.get('recorder_replaced', False)
                
                replace_j = bool(j and not j_confirmed) or j_replaced
                replace_r = bool(r and not r_confirmed) or r_replaced
                
                self.bot.add_view(StaffReplacementView(ev_id, replace_j, replace_r))
            except Exception as view_err:
                print(f"Error registering persistent views for {ev_id}: {view_err}")
                
            if dt and ch_id:
                if isinstance(dt, str):
                    try:
                        dt = datetime.datetime.fromisoformat(dt)
                        ev_data['datetime'] = dt
                    except Exception:
                        pass
                if isinstance(dt, datetime.datetime):
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=pytz.UTC)
                    if dt > now_utc:
                        try:
                            ch_id_int = int(ch_id)
                            channel = self.bot.get_channel(ch_id_int)
                            if not channel:
                                try:
                                    channel = await self.bot.fetch_channel(ch_id_int)
                                except Exception:
                                    channel = None
                            if channel:
                                asyncio.create_task(schedule_ten_minute_reminder(
                                    ev_id,
                                    ev_data.get('team1_captain'),
                                    ev_data.get('team2_captain'),
                                    ev_data.get('judge'),
                                    channel,
                                    dt
                                ))
                        except Exception as rem_err:
                            print(f"Error rescheduling reminder for {ev_id}: {rem_err}")

        # Startup sweep for old events
        try:
            for ev_id, data in list(scheduled_events.items()):
                dt = data.get('datetime')
                if isinstance(dt, datetime.datetime):
                    age_days = (datetime.datetime.now() - dt.replace(tzinfo=None)).days
                    if age_days >= 7:
                        if ev_id in reminder_tasks:
                            try:
                                reminder_tasks[ev_id].cancel()
                                del reminder_tasks[ev_id]
                            except Exception:
                                pass
                        del scheduled_events[ev_id]
            save_scheduled_events()
        except Exception as e:
            print(f"Startup sweep error: {e}")

        # Command sync
        try:
            print("🔄 Syncing slash commands globally...")
            synced = await asyncio.wait_for(self.bot.tree.sync(), timeout=30.0)
            print(f"✅ Synced {len(synced)} global command(s)")
            for g in self.bot.guilds:
                try:
                    self.bot.tree.copy_global_to(guild=g)
                    await self.bot.tree.sync(guild=g)
                    print(f"  └─ Synced commands instantly to guild: {g.name} ({g.id})")
                except Exception as g_err:
                    print(f"  └─ Guild sync error for {g.name}: {g_err}")
        except asyncio.TimeoutError:
            print("⚠️ Command sync timed out, but bot will continue running")
        except Exception as e:
            print(f"❌ Error syncing commands: {e}")

        print("🎯 Bot is ready to receive commands!")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return
        if not message.guild:
            return

        current_guild_id.set(message.guild.id)

        content = message.content.strip()
        command = content.lower()

        # Admin command to immediately sync slash commands to the current server
        if command in ['!sync', '$sync', '.sync']:
            is_owner = message.author.id == BOT_OWNER_ID
            is_admin = message.author.guild_permissions.administrator if hasattr(message.author, 'guild_permissions') else False
            if is_owner or is_admin:
                msg = await message.channel.send("⏳ Syncing slash commands for this server and globally...")
                try:
                    self.bot.tree.copy_global_to(guild=message.guild)
                    synced_guild = await self.bot.tree.sync(guild=message.guild)
                    synced_global = await self.bot.tree.sync()
                    await msg.edit(content=f"✅ Successfully synced **{len(synced_guild)}** commands instantly to **{message.guild.name}** (and **{len(synced_global)}** globally)!\n💡 *Tip: If commands don't show up immediately, press `Ctrl + R` (or restart Discord) to refresh your client cache.*")
                except Exception as e:
                    await msg.edit(content=f"❌ Sync failed: {e}")
                return

        # Ticket status prefix commands (?sh, ?dq, ?dd, ?ho, $close, $delete)
        if command in ['?sh', '?dq', '?dd', '?ho', '$close', '$delete']:

            is_owner = message.author.id == BOT_OWNER_ID
            is_admin = message.author.guild_permissions.administrator if hasattr(message.author, 'guild_permissions') else False
            has_role = False
            
            if hasattr(message.author, 'roles'):
                head_org_id = ROLE_IDS.get("head_organizer")
                helper_team_id = ROLE_IDS.get("helper_team")
                judge_id_val = ROLE_IDS.get("judge")
                recorder_id_val = ROLE_IDS.get("recorder")
                staff_id_val = ROLE_IDS.get("staff")
                head_org = discord.utils.get(message.author.roles, id=head_org_id) if head_org_id else None
                helper_team = discord.utils.get(message.author.roles, id=helper_team_id) if helper_team_id else None
                judge = discord.utils.get(message.author.roles, id=judge_id_val) if judge_id_val else None
                recorder = discord.utils.get(message.author.roles, id=recorder_id_val) if recorder_id_val else None
                staff = discord.utils.get(message.author.roles, id=staff_id_val) if staff_id_val else None
                has_role = bool(head_org or helper_team or judge or recorder or staff)
                
            if not (is_owner or is_admin or has_role):
                try: await message.delete()
                except Exception: pass
                return

            if command == '$close':
                try:
                    await message.channel.send("⏳ Generating rich HTML & Text transcript, please wait...")
                    
                    messages_list = []
                    async for m in message.channel.history(limit=2000, oldest_first=True):
                        messages_list.append(m)

                    guild = message.guild
                    clean_chan_name = re.sub(r'[^a-zA-Z0-9_\-]', '', message.channel.name).lower() or "ticket"
                    html_content = generate_html_transcript(message.channel, messages_list, guild, closed_by=message.author)
                    text_content = generate_text_transcript(message.channel, messages_list, guild, closed_by=message.author)

                    html_filename = f"transcript_{clean_chan_name}.html"
                    text_filename = f"transcript_{clean_chan_name}.txt"

                    html_file_local = discord.File(io.BytesIO(html_content.encode('utf-8')), filename=html_filename)
                    text_file_local = discord.File(io.BytesIO(text_content.encode('utf-8')), filename=text_filename)

                    attachment_count = sum(len(m.attachments) for m in messages_list)

                    await message.channel.send(
                        f"📄 **Transcript of `{message.channel.name}`** ({len(messages_list)} messages, {attachment_count} attachments):\n"
                        f"• Open the `.html` file in any browser for full Discord chat with images & embeds!\n"
                        f"• Open the `.txt` file for a text log with image URLs.",
                        files=[html_file_local, text_file_local]
                    )

                    # Resolve transcript log channel
                    transcript_channel = None
                    t_cfg = get_active_tournament_config(message.guild.id)
                    if t_cfg:
                        for k in ['transcript', 'transcript_logs', 'transcript_channel_id', 'Transcript_Channel_ID']:
                            if t_cfg.get(k):
                                try:
                                    transcript_channel = message.guild.get_channel(int(t_cfg[k])) or await message.guild.fetch_channel(int(t_cfg[k]))
                                    if transcript_channel: break
                                except Exception: pass

                    if not transcript_channel:
                        tournaments = load_guild_tournaments(message.guild.id)
                        for _, tdata in tournaments.items():
                            for k in ['transcript', 'transcript_logs', 'transcript_channel_id', 'Transcript_Channel_ID']:
                                if tdata.get(k):
                                    try:
                                        transcript_channel = message.guild.get_channel(int(tdata[k])) or await message.guild.fetch_channel(int(tdata[k]))
                                        if transcript_channel: break
                                    except Exception: pass
                            if transcript_channel: break

                    if not transcript_channel:
                        cfg = get_guild_config(message.guild.id)
                        for k in ['transcript_logs', 'transcript', 'transcript_channel_id', 'Transcript_Channel_ID']:
                            t_id = cfg.get('channel_ids', {}).get(k) or cfg.get(k)
                            if t_id:
                                try:
                                    transcript_channel = message.guild.get_channel(int(t_id)) or await message.guild.fetch_channel(int(t_id))
                                    if transcript_channel: break
                                except Exception: pass

                    if transcript_channel:
                        html_file_rec = discord.File(io.BytesIO(html_content.encode('utf-8')), filename=html_filename)
                        text_file_rec = discord.File(io.BytesIO(text_content.encode('utf-8')), filename=text_filename)

                        summary_embed = discord.Embed(
                            title=f"📋 Ticket Closed: #{message.channel.name}",
                            description=(
                                f"**Closed by:** {message.author.mention}\n"
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
                                    closed_category = message.guild.get_channel(int(t_cfg[k]))
                                    if closed_category: break
                                except Exception: pass
                    if not closed_category:
                        tournaments = load_guild_tournaments(message.guild.id)
                        for _, tdata in tournaments.items():
                            for k in ['closed_ticket_1', 'closed_ticket_2', 'closed_tickets_category', 'closed_category']:
                                if tdata.get(k):
                                    try:
                                        closed_category = message.guild.get_channel(int(tdata[k]))
                                        if closed_category: break
                                    except Exception: pass
                            if closed_category: break
                    if not closed_category:
                        cfg = get_guild_config(message.guild.id)
                        for k in ['closed_tickets_category', 'closed_category']:
                            c_id = cfg.get('channel_ids', {}).get(k) or cfg.get(k)
                            if c_id:
                                try:
                                    closed_category = message.guild.get_channel(int(c_id))
                                    if closed_category: break
                                except Exception: pass

                    if closed_category:
                        await message.channel.edit(
                            category=closed_category,
                            sync_permissions=True,
                            reason=f"Ticket closed by {message.author.name}"
                        )
                        await message.channel.send("🔒 Ticket closed and moved to closed category. Use `$delete` to permanently delete it.")
                    else:
                        await message.channel.send("🔒 Ticket closed.")
                except Exception as e:
                    print(f"Error closing ticket: {e}")
                return


            elif command == '$delete':
                try:
                    await message.channel.delete(reason=f"Ticket deleted by {message.author.name}")
                except Exception as e:
                    print(f"Error deleting channel: {e}")
                return

            try:
                channel = message.channel
                new_prefix = "🟢" if command == '?sh' else "🔴" if command == '?dq' else "✅" if command == '?dd' else "🟡"
                clean_name = channel.name
                for p in ["🟢", "🔴", "✅", "🟡"]:
                    if clean_name.startswith(p):
                        clean_name = clean_name[len(p):].lstrip("-").lstrip()
                        break
                new_name = f"{new_prefix}-{clean_name}"
                await channel.edit(name=new_name)
                try: await message.delete()
                except Exception: pass
            except Exception as e:
                print(f"Error renaming channel for prefix: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Listeners(bot))
