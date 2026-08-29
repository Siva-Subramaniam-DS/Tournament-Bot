import os
import io
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
    get_guild_staff_stats, save_guild_staff_stats
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
            print("🔄 Syncing slash commands...")
            synced = await asyncio.wait_for(self.bot.tree.sync(), timeout=30.0)
            print(f"✅ Synced {len(synced)} command(s)")
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
                    closed_category_id = CHANNEL_IDS.get("closed_tickets_category") or CHANNEL_IDS.get("closed_ticket_1")
                    closed_category = message.guild.get_channel(int(closed_category_id)) if closed_category_id else None
                    
                    await message.channel.send("⏳ Generating transcript, please wait...")
                    transcript_lines = []
                    async for m in message.channel.history(limit=1000, oldest_first=True):
                        time_str = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        c = m.clean_content or "[Attachment/Embed]"
                        transcript_lines.append(f"[{time_str}] {m.author.display_name}: {c}")
                    
                    transcript_content = "\n".join(transcript_lines)
                    transcript_file_local = discord.File(io.BytesIO(transcript_content.encode('utf-8')), filename=f"transcript_{message.channel.name}.txt")
                    await message.channel.send("📄 Transcript of this ticket:", file=transcript_file_local)
                    
                    transcript_channel = None
                    t_cfg = get_active_tournament_config(message.guild.id)
                    if t_cfg and t_cfg.get('transcript'):
                        transcript_channel = message.guild.get_channel(int(t_cfg['transcript']))
                    if not transcript_channel and CHANNEL_IDS.get("transcript"):
                        try:
                            transcript_channel = message.guild.get_channel(int(CHANNEL_IDS["transcript"]))
                        except Exception: pass
                        
                    if transcript_channel:
                        transcript_file_record = discord.File(io.BytesIO(transcript_content.encode('utf-8')), filename=f"transcript_{message.channel.name}.txt")
                        await transcript_channel.send(f"📋 Transcript for closed ticket `{message.channel.name}` (closed by {message.author.display_name}):", file=transcript_file_record)
                    
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
