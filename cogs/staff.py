import os
import json
import asyncio
import datetime
from typing import Optional, List, Union

import pytz
import discord
from discord import app_commands
from discord.ext import commands

from core.config import (
    BASE_DIR, BRAND_COLOR, BOT_OWNER_ID, ORGANIZATION_NAME,
    DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS
)
from core.state import (
    current_guild_id, with_guild_context, is_authorized_to_configure,
    is_staff, has_organizer_permission, get_user_permission_level,
    get_org_name, ROLE_IDS, CHANNEL_IDS, scheduled_events,
    save_scheduled_events, staff_stats, save_staff_stats,
    reset_staff_stats, judge_assignments,
    tournament_rules, get_current_rules, set_rules_content
)
from core.database import (
    supabase_client, load_guild_tournaments, get_guild_config,
    get_active_tournament_config, log_bot_activity, sheetdb_post,
    get_guild_staff_stats, save_guild_staff_stats, tournament_autocomplete
)
from core.emojis import EMOJIS, get_staff_emoji



# ===========================================================================================
# STAFF HELPER FUNCTIONS
# ===========================================================================================

def remove_field_by_name(embed: discord.Embed, name: str) -> bool:
    try:
        fields = list(embed.fields)
        target = name.strip().lower()
        for idx, field in enumerate(fields):
            fn = field.name.strip().lower()
            if fn == target or ("judge" in target and "judge" in fn) or ("recorder" in target and "recorder" in fn):
                embed.remove_field(idx)
                return True
        return False
    except Exception as e:
        print(f"Error removing field {name}: {e}")
        return False

def update_judge_field(embed: discord.Embed, judge: discord.Member, recorder: Optional[discord.Member] = None) -> bool:
    try:
        remove_field_by_name(embed, "Judge")
        remove_field_by_name(embed, "Recorder")
        
        judge_value = judge.mention if judge else "⏳ Waiting..."
        embed.add_field(name=f"{EMOJIS['judge']} Judge", value=judge_value, inline=True)
        
        if recorder:
            recorder_value = recorder.mention if hasattr(recorder, 'mention') else f"<@{recorder}>"
            embed.add_field(name=f"{EMOJIS['recorder']} Recorder", value=recorder_value, inline=True)
        
        return True
    except Exception as e:
        print(f"Error updating judge field: {e}")
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

def add_judge_assignment(judge_id: int, event_id: str):
    if judge_id not in judge_assignments:
        judge_assignments[judge_id] = []
    judge_assignments[judge_id].append(event_id)

def remove_judge_assignment(judge_id: int, event_id: str):
    if judge_id in judge_assignments and event_id in judge_assignments[judge_id]:
        judge_assignments[judge_id].remove(event_id)
        if not judge_assignments[judge_id]:
            del judge_assignments[judge_id]


# ===========================================================================================
# STAFF CONFIRMATION AND REPLACEMENT SYSTEM
# ===========================================================================================

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
        
        self.judge_member = ev.get('judge')
        self.recorder_member = ev.get('recorder')
        
        dt = ev.get('datetime')
        is_too_late = False
        
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            now = datetime.datetime.now(pytz.UTC)
            seconds_until = (dt - now).total_seconds()
            
            if seconds_until < 600:
                is_too_late = True
        
        if self.judge_member:
            is_confirmed = ev.get('judge_confirmed', False)
            if is_confirmed:
                btn_label = "Confirmed"
                btn_emoji = discord.PartialEmoji(name="White_Verification", id=1544979996395970560, animated=True)
                btn_style = discord.ButtonStyle.green
                btn_disabled = True
            elif is_too_late:
                btn_label = "Too Late - Replacement Needed"
                btn_emoji = "❌"
                btn_style = discord.ButtonStyle.red
                btn_disabled = True
            else:
                btn_label = "Confirm Presence"
                btn_emoji = discord.PartialEmoji(name="judge", id=1544980903871127645)
                btn_style = discord.ButtonStyle.gray
                btn_disabled = False
            
            btn = discord.ui.Button(label=btn_label, emoji=btn_emoji, style=btn_style, custom_id=f"confirm_judge_{self.event_id}")
            btn.callback = self.confirm_judge_callback
            btn.disabled = btn_disabled
            self.add_item(btn)
            
        if self.recorder_member:
            is_confirmed = ev.get('recorder_confirmed', False)
            if is_confirmed:
                btn_label = "Confirmed"
                btn_emoji = discord.PartialEmoji(name="White_Verification", id=1544979996395970560, animated=True)
                btn_style = discord.ButtonStyle.blurple
                btn_disabled = True
            elif is_too_late:
                btn_label = "Too Late - Replacement Needed"
                btn_emoji = "❌"
                btn_style = discord.ButtonStyle.red
                btn_disabled = True
            else:
                btn_label = "Confirm Presence"
                btn_emoji = discord.PartialEmoji(name="camera", id=1544981791566331924)
                btn_style = discord.ButtonStyle.gray
                btn_disabled = False
            
            btn = discord.ui.Button(label=btn_label, emoji=btn_emoji, style=btn_style, custom_id=f"confirm_recorder_{self.event_id}")
            btn.callback = self.confirm_recorder_callback
            btn.disabled = btn_disabled
            self.add_item(btn)

    @with_guild_context
    async def confirm_judge_callback(self, interaction: discord.Interaction):
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=False)
            return
            
        self.judge_member = ev.get('judge')
        assigned_judge_id = getattr(self.judge_member, 'id', self.judge_member)
        if str(interaction.user.id) != str(assigned_judge_id):
            await interaction.response.send_message("❌ You are not the assigned judge for this event.", ephemeral=False)
            return
            
        dt = ev.get('datetime')
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            now = datetime.datetime.now(pytz.UTC)
            seconds_until = (dt - now).total_seconds()
            if seconds_until < 600:
                await interaction.response.send_message(
                    "❌ Too late to confirm presence. It's less than 10 minutes before match start.\nA staff replacement request will be posted shortly.",
                    ephemeral=False
                )
                return
                
        ev['judge_confirmed'] = True
        ev['judge_confirmation_time'] = datetime.datetime.utcnow().isoformat()
        save_scheduled_events()
        
        self.update_buttons()
        
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
        await interaction.followup.send(f"{EMOJIS['attendance_done']} You have confirmed your presence as Judge!", ephemeral=False)
        
        log_embed = discord.Embed(
            title=f"{EMOJIS['judge']} Judge Presence Confirmed",
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
            await interaction.response.send_message("❌ Event not found.", ephemeral=False)
            return
            
        self.recorder_member = ev.get('recorder')
        assigned_recorder_id = getattr(self.recorder_member, 'id', self.recorder_member)
        if str(interaction.user.id) != str(assigned_recorder_id):
            await interaction.response.send_message("❌ You are not the assigned recorder for this event.", ephemeral=False)
            return
            
        dt = ev.get('datetime')
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            now = datetime.datetime.now(pytz.UTC)
            seconds_until = (dt - now).total_seconds()
            if seconds_until < 600:
                await interaction.response.send_message(
                    "❌ Too late to confirm presence. It's less than 10 minutes before match start.\nA staff replacement request will be posted shortly.",
                    ephemeral=False
                )
                return
                
        ev['recorder_confirmed'] = True
        ev['recorder_confirmation_time'] = datetime.datetime.utcnow().isoformat()
        save_scheduled_events()
        
        self.update_buttons()
        
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
        await interaction.followup.send(f"{EMOJIS['attendance_done']} You have confirmed your presence as Recorder!", ephemeral=False)
        
        log_embed = discord.Embed(
            title=f"{EMOJIS['recorder']} Recorder Presence Confirmed",
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
            btn_label = "Replaced" if is_replaced else "Replace Judge"
            btn_emoji = discord.PartialEmoji(name="judge", id=1544980903871127645)
            btn_style = discord.ButtonStyle.green if is_replaced else discord.ButtonStyle.primary
            btn = discord.ui.Button(label=btn_label, emoji=btn_emoji, style=btn_style, disabled=is_replaced, custom_id=f"replace_judge_{self.event_id}")
            btn.callback = self.replace_judge_callback
            self.add_item(btn)
            
        if self.replace_recorder:
            is_replaced = ev.get('recorder_replaced', False)
            btn_label = "Replaced" if is_replaced else "Replace Recorder"
            btn_emoji = discord.PartialEmoji(name="Cameramanremove", id=1545321785388437584)
            btn_style = discord.ButtonStyle.green if is_replaced else discord.ButtonStyle.primary
            btn = discord.ui.Button(label=btn_label, emoji=btn_emoji, style=btn_style, disabled=is_replaced, custom_id=f"replace_recorder_{self.event_id}")
            btn.callback = self.replace_recorder_callback
            self.add_item(btn)

    @with_guild_context
    async def replace_judge_callback(self, interaction: discord.Interaction):
        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_admin or is_owner):
            await interaction.response.send_message("❌ You do not have the required role to replace the judge.", ephemeral=False)
            return
            
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=False)
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
        
        try:
            sched_chan_id = ev.get('schedule_channel_id')
            sched_msg_id = ev.get('schedule_message_id')
            if sched_chan_id and sched_msg_id:
                sched_chan = interaction.guild.get_channel(sched_chan_id)
                if sched_chan:
                    sched_msg = await sched_chan.fetch_message(sched_msg_id)
                    if sched_msg:
                        sched_embed = sched_msg.embeds[0]
                        current_recorder = ev.get('recorder')
                        update_judge_field(sched_embed, interaction.user, current_recorder)
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
        await interaction.followup.send("✅ You have successfully replaced the judge for this match!", ephemeral=False)
        
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
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_admin or is_owner):
            await interaction.response.send_message("❌ You do not have the required role to replace the recorder.", ephemeral=False)
            return
            
        ev = scheduled_events.get(self.event_id)
        if not ev:
            await interaction.response.send_message("❌ Event not found.", ephemeral=False)
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
        
        try:
            sched_chan_id = ev.get('schedule_channel_id')
            sched_msg_id = ev.get('schedule_message_id')
            if sched_chan_id and sched_msg_id:
                sched_chan = interaction.guild.get_channel(sched_chan_id)
                if sched_chan:
                    sched_msg = await sched_chan.fetch_message(sched_msg_id)
                    if sched_msg:
                        sched_embed = sched_msg.embeds[0]
                        remove_field_by_name(sched_embed, "Recorder")
                        sched_embed.add_field(name=f"{EMOJIS['recorder']} Recorder", value=interaction.user.mention, inline=True)
                        sched_view = TakeScheduleButton(self.event_id, ev.get('team1_captain'), ev.get('team2_captain'), event_ch)
                        await sched_msg.edit(embed=sched_embed, view=sched_view)
        except Exception as e:
            print(f"Error updating schedule message after recorder replacement: {e}")
        
        if interaction.message.embeds:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(name=f"{EMOJIS['cameraman_in']} New Recorder Assigned", value=f"{interaction.user.mention} has taken over recording this match.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{EMOJIS['cameraman_in']} You have successfully replaced the recorder for this match!", ephemeral=False)
        
        log_embed = discord.Embed(
            title=f"{EMOJIS['cameraman_out']} Recorder Replaced",
            description=f"New Recorder **{interaction.user.display_name}** took over recording for match (Event ID: `{self.event_id}`).",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Replaced by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)
        if event_ch:
            emoji = get_staff_emoji(event_ch.guild, "recorder")
            await event_ch.send(f"{interaction.user.mention} assigned as **recorder** {emoji}")


class TakeScheduleButton(discord.ui.View):
    def __init__(self, event_id: str, team1_captain: discord.Member, team2_captain: discord.Member, event_channel: discord.TextChannel = None):
        super().__init__(timeout=None)
        self.event_id = event_id
        self.team1_captain = team1_captain
        self.team2_captain = team2_captain
        self.event_channel = event_channel
        self._taking_schedule = False

        ev = scheduled_events.get(event_id, {})
        self.judge = ev.get('judge')
        self.recorder = ev.get('recorder')

        for child in self.children:
            if child.custom_id == "take_schedule_btn" or (child.custom_id and child.custom_id.startswith("take_schedule_")):
                child.custom_id = f"take_schedule_{event_id}"
                if self.judge:
                    child.label = "🙋 Assigned"
                    child.style = discord.ButtonStyle.green
                    child.disabled = True
                    child.emoji = None
            elif child.custom_id == "record_btn" or (child.custom_id and child.custom_id.startswith("record_")):
                child.custom_id = f"record_{event_id}"
                if self.recorder:
                    child.label = "📹 Assigned"
                    child.style = discord.ButtonStyle.green
                    child.disabled = True
                    child.emoji = None

    def _is_event_started(self) -> bool:
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
        if self._is_event_started():
            for child in self.children:
                child.disabled = True
            try: await interaction.message.edit(view=self)
            except Exception: pass
            await interaction.response.send_message("❌ This event has already started. Buttons are now disabled.", ephemeral=False)
            return

        if self._taking_schedule:
            await interaction.response.send_message("⏳ Another judge is currently taking this schedule. Please wait.", ephemeral=False)
            return

        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_owner or is_admin):
            await interaction.response.send_message("❌ You do not have the required role to take this schedule.", ephemeral=False)
            return

        if self.judge:
            await interaction.response.send_message(f"❌ This schedule has already been taken by {self.judge.display_name}.", ephemeral=False)
            return

        original_label = button.label
        original_style = button.style
        original_disabled = button.disabled
        original_emoji = button.emoji

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
            return

        try:
            ev = scheduled_events.get(self.event_id, {})
            if ev.get('judge'):
                button.label = original_label
                button.style = original_style
                button.disabled = original_disabled
                button.emoji = original_emoji
                await interaction.message.edit(view=self)
                j_val = ev.get('judge')
                j_name = getattr(j_val, 'display_name', str(j_val))
                await interaction.followup.send(f"❌ This schedule has already been taken by {j_name}.", ephemeral=False)
                return

            self.judge = interaction.user
            add_judge_assignment(interaction.user.id, self.event_id)

            button.label = "🙋 Assigned"
            button.style = discord.ButtonStyle.green
            button.disabled = True
            button.emoji = None

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            update_embed_title_with_checkmark(embed)
            
            current_recorder = ev.get('recorder')
            update_judge_field(embed, interaction.user, current_recorder)

            await interaction.message.edit(embed=embed, view=self)
            await interaction.followup.send("✅ You have successfully taken this schedule!", ephemeral=False)
            
            log_embed = discord.Embed(
                title="⚖️ Schedule Claimed",
                description=f"Judge **{interaction.user.display_name}** claimed match schedule (Event ID: `{self.event_id}`).",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            log_embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
            await log_bot_activity(interaction.guild, log_embed)

            if self.event_id in scheduled_events:
                scheduled_events[self.event_id]['judge'] = self.judge
                save_scheduled_events()

            if self.event_channel:
                try:
                    await self.event_channel.set_permissions(
                        interaction.user,
                        read_messages=True, send_messages=True, view_channel=True,
                        embed_links=True, attach_files=True, read_message_history=True
                    )
                    emoji = get_staff_emoji(self.event_channel.guild, "judge")
                    await self.event_channel.send(content=f"{interaction.user.mention} assigned as **judge** {emoji}")
                except Exception as perm_err:
                    print(f"Error giving judge ticket channel access: {perm_err}")

        except Exception as e:
            print(f"Error in take_schedule: {e}")
            button.label = original_label
            button.style = original_style
            button.disabled = original_disabled
            button.emoji = original_emoji
            try: await interaction.message.edit(view=self)
            except Exception: pass
        finally:
            self._taking_schedule = False

    @discord.ui.button(label="Record", style=discord.ButtonStyle.blurple, emoji=discord.PartialEmoji(name="camera", id=1544981791566331924), custom_id="record_btn")
    @with_guild_context
    async def record_schedule(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._is_event_started():
            for child in self.children:
                child.disabled = True
            try: await interaction.message.edit(view=self)
            except Exception: pass
            await interaction.response.send_message("❌ This event has already started. Buttons are now disabled.", ephemeral=False)
            return

        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"])
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"])
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"])
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"])
        has_allowed_role = any([head_organizer_role, helper_team_role, judge_role, recorder_role, staff_role])
        if not (has_allowed_role or is_owner or is_admin):
            await interaction.response.send_message("❌ You do not have the required role to record this schedule.", ephemeral=False)
            return

        ev = scheduled_events.get(self.event_id, {})
        if ev.get('recorder'):
            r_val = ev.get('recorder')
            r_name = getattr(r_val, 'display_name', str(r_val))
            await interaction.response.send_message(f"❌ This match already has a recorder assigned: {r_name}.", ephemeral=False)
            return

        self.recorder = interaction.user
        ev['recorder'] = interaction.user
        save_scheduled_events()

        button.label = "Assigned"
        button.style = discord.ButtonStyle.green
        button.disabled = True
        button.emoji = discord.PartialEmoji(name="camera", id=1544981791566331924)

        embed = interaction.message.embeds[0]
        remove_field_by_name(embed, "Recorder")
        embed.add_field(name=f"{EMOJIS['recorder']} Recorder", value=interaction.user.mention, inline=True)

        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send("✅ You have successfully claimed recorder for this match!", ephemeral=False)

        if self.event_channel:
            try:
                await self.event_channel.set_permissions(
                    interaction.user,
                    read_messages=True, send_messages=True, view_channel=True,
                    embed_links=True, attach_files=True, read_message_history=True
                )
                emoji = get_staff_emoji(self.event_channel.guild, "recorder")
                await self.event_channel.send(content=f"{interaction.user.mention} assigned as **recorder** {emoji}")
            except Exception as perm_err:
                print(f"Error giving recorder ticket channel access: {perm_err}")


# ===========================================================================================
# LEADERBOARD VIEWS
# ===========================================================================================

class JudgeLeaderboardView(discord.ui.View):
    def __init__(self, show_reset: bool = False):
        super().__init__(timeout=300)
        if not show_reset:
            self.clear_items()
    
    @discord.ui.button(label="🔄 Reset Leaderboard", style=discord.ButtonStyle.danger, emoji="🔄")
    @with_guild_context
    async def reset_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"])
        if not head_organizer_role and not (interaction.guild and interaction.user.guild_permissions.administrator) and interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ You need **Head Organizer** role to reset the leaderboard.", ephemeral=False)
            return
        
        confirm_view = ConfirmResetView()
        await interaction.response.send_message(
            "⚠️ **WARNING**: This will permanently reset staff statistics!\nAre you sure you want to reset the staff leaderboard?",
            view=confirm_view,
            ephemeral=False
        )

class ConfirmResetView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
    
    @discord.ui.button(label="✅ Yes, Reset", style=discord.ButtonStyle.danger, emoji="✅")
    @with_guild_context
    async def confirm_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            reset_staff_stats()
            await interaction.response.edit_message(
                content="✅ **Staff leaderboard has been reset successfully!**",
                view=None
            )
        except Exception as e:
            print(f"Error resetting staff leaderboard: {e}")
            await interaction.response.edit_message(
                content="❌ **Error resetting leaderboard.**",
                view=None
            )
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    @with_guild_context
    async def cancel_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="✅ **Reset cancelled.**", view=None)


# ===========================================================================================
# STAFF COMMAND GROUP
# ===========================================================================================

staff_group = app_commands.Group(name="staff", description="Manage tournament staff roles and workload stats")

@staff_group.command(name="recruit", description="Recruit a member to one or more staff roles")
@app_commands.describe(
    member="The discord member to recruit",
    role="Primary role to assign",
    role_2="Optional 2nd role to assign",
    role_3="Optional 3rd role to assign",
    role_4="Optional 4th role to assign",
    role_5="Optional 5th role to assign"
)
@with_guild_context
async def staff_recruit(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role,
    role_2: Optional[discord.Role] = None,
    role_3: Optional[discord.Role] = None,
    role_4: Optional[discord.Role] = None,
    role_5: Optional[discord.Role] = None
):
    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to recruit staff.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    roles_to_add = []
    for r in [role, role_2, role_3, role_4, role_5]:
        if r and r not in roles_to_add and r not in member.roles:
            if interaction.guild and interaction.guild.me.top_role > r:
                roles_to_add.append(r)

    if not roles_to_add:
        already = [r.mention for r in [role, role_2, role_3, role_4, role_5] if r and r in member.roles]
        if already:
            await interaction.followup.send(f"⚠️ {member.mention} already has role(s): {', '.join(already)}")
        else:
            await interaction.followup.send("⚠️ No valid roles could be assigned (check bot role hierarchy).")
        return

    try:
        await member.add_roles(*roles_to_add, reason=f"Recruited by {interaction.user}")
        assigned_role_text = ", ".join(r.mention for r in roles_to_add)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Failed to add Discord role(s): {e}", ephemeral=False)
        return

    embed = discord.Embed(
        title="📋 Staff Recruitment Updated",
        description=f"Successfully assigned {len(roles_to_add)} staff role(s) to {member.mention}",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="👤 Staff Member", value=f"{member.mention} (`{member.display_name}`)", inline=True)
    embed.add_field(name="🛡️ Assigned Role(s)", value=assigned_role_text, inline=True)
    embed.add_field(name="👑 Recruited By", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Management")
    await interaction.followup.send(embed=embed, ephemeral=False)

    # Audit Log
    try:
        log_embed = discord.Embed(
            title="📋 Staff Recruited",
            description=f"**Target Member:** {member.mention} (`{member.id}`)\n**Roles Added:** {assigned_role_text}\n**Recruited By:** {interaction.user.mention}",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception:
        pass


@staff_group.command(name="fire", description="Remove one or more staff roles from a member")
@app_commands.describe(
    member="The discord member to remove staff role(s) from",
    role="Primary role to remove",
    role_2="Optional 2nd role to remove",
    role_3="Optional 3rd role to remove",
    role_4="Optional 4th role to remove",
    role_5="Optional 5th role to remove"
)
@with_guild_context
async def staff_fire(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role,
    role_2: Optional[discord.Role] = None,
    role_3: Optional[discord.Role] = None,
    role_4: Optional[discord.Role] = None,
    role_5: Optional[discord.Role] = None
):
    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to remove staff.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    roles_to_remove = []
    for r in [role, role_2, role_3, role_4, role_5]:
        if r and r not in roles_to_remove and r in member.roles:
            if interaction.guild and interaction.guild.me.top_role > r:
                roles_to_remove.append(r)

    if not roles_to_remove:
        await interaction.followup.send(f"⚠️ {member.mention} does not have any of the specified roles or bot lacks role hierarchy permission.")
        return

    try:
        await member.remove_roles(*roles_to_remove, reason=f"Removed by {interaction.user}")
        removed_role_text = ", ".join(r.mention for r in roles_to_remove)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Failed to remove Discord role(s): {e}", ephemeral=False)
        return

    embed = discord.Embed(
        title="⚠️ Staff Removal Updated",
        description=f"Successfully removed {len(roles_to_remove)} staff role(s) from {member.mention}",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="👤 Staff Member", value=f"{member.mention} (`{member.display_name}`)", inline=True)
    embed.add_field(name="🛡️ Removed Role(s)", value=removed_role_text, inline=True)
    embed.add_field(name="👑 Action By", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Staff Management")
    await interaction.followup.send(embed=embed, ephemeral=False)

    # Audit Log
    try:
        log_embed = discord.Embed(
            title="⚠️ Staff Role(s) Removed",
            description=f"**Target Member:** {member.mention} (`{member.id}`)\n**Roles Removed:** {removed_role_text}\n**Action By:** {interaction.user.mention}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception:
        pass


async def render_staff_work_count(
    interaction: discord.Interaction,
    tournament: Optional[str] = None,
    default_wins: Optional[str] = "Including",
    member: Optional[discord.Member] = None
):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=False)

    guild = interaction.guild
    if not guild:
        await interaction.followup.send("❌ This command can only be used in a server.", ephemeral=True)
        return

    tournaments = load_guild_tournaments(guild.id)
    target_t_id = None
    target_t_name = "All Active Tournaments"
    dw_setting = default_wins or "Including"
    
    if tournament:
        t_clean = tournament.strip().lower()
        if t_clean in tournaments:
            target_t_id = t_clean
            target_t_name = tournaments[t_clean].get('name') or t_clean
        else:
            for tid, tcfg in tournaments.items():
                if tcfg.get('name', '').lower() == t_clean:
                    target_t_id = tid
                    target_t_name = tcfg.get('name') or tid
                    break
            if not target_t_id:
                for tid, tcfg in tournaments.items():
                    if t_clean in tid.lower() or t_clean in tcfg.get('name', '').lower() or tcfg.get('name', '').lower() in t_clean:
                        target_t_id = tid
                        target_t_name = tcfg.get('name') or tid
                        break
            if not target_t_id:
                target_t_name = tournament
                target_t_id = tournament

    judges = {}
    recorders = {}
    judge_and_recorders = {}

    for ev_id, ev_data in scheduled_events.items():
        if ev_data.get('guild_id') and str(ev_data.get('guild_id')) != str(guild.id):
            continue
            
        if target_t_id and target_t_name != "All Active Tournaments":
            ev_t_id = str(ev_data.get('tournament_id') or '').lower()
            ev_t_name = str(ev_data.get('tournament') or '').lower()
            t_id_clean = str(target_t_id).lower()
            t_name_clean = str(target_t_name).lower()
            
            matched = (
                ev_t_id == t_id_clean or
                ev_t_name == t_id_clean or
                ev_t_name == t_name_clean or
                t_name_clean in ev_t_name or
                ev_t_name in t_name_clean or
                t_id_clean in ev_t_name
            )
            if not matched:
                continue
                
        if dw_setting == "Excluded" and ev_data.get('disqualified'):
            continue

            
        rnd = str(ev_data.get('round') or 'R1')
        
        j_val = ev_data.get('judge') or ev_data.get('result_judge')
        r_val = ev_data.get('recorder')
        
        j_uid = str(getattr(j_val, 'id', j_val)) if j_val else None
        r_uid = str(getattr(r_val, 'id', r_val)) if r_val else None
        
        # Dual Role: Same person took BOTH Judge and Recorder on this exact match
        if j_uid and r_uid and j_uid == r_uid:
            u_name = getattr(j_val, 'name', getattr(r_val, 'name', ev_data.get('judge_name', ev_data.get('recorder_name', f"User_{j_uid}"))))
            if j_uid not in judge_and_recorders:
                judge_and_recorders[j_uid] = {'matches': set(), 'rounds': set(), 'name': u_name}
            judge_and_recorders[j_uid]['matches'].add(ev_id)
            judge_and_recorders[j_uid]['rounds'].add(rnd)
            if hasattr(j_val, 'name'):
                judge_and_recorders[j_uid]['name'] = j_val.name
        else:
            # Solo Judge (No recorder or different recorder)
            if j_uid:
                u_name = getattr(j_val, 'name', ev_data.get('judge_name', f"User_{j_uid}"))
                if j_uid not in judges:
                    judges[j_uid] = {'matches': set(), 'rounds': set(), 'name': u_name}
                judges[j_uid]['matches'].add(ev_id)
                judges[j_uid]['rounds'].add(rnd)
                if hasattr(j_val, 'name'):
                    judges[j_uid]['name'] = j_val.name
            
            # Solo Recorder (No judge or different judge)
            if r_uid:
                u_name = getattr(r_val, 'name', ev_data.get('recorder_name', f"User_{r_uid}"))
                if r_uid not in recorders:
                    recorders[r_uid] = {'matches': set(), 'rounds': set(), 'name': u_name}
                recorders[r_uid]['matches'].add(ev_id)
                recorders[r_uid]['rounds'].add(rnd)
                if hasattr(r_val, 'name'):
                    recorders[r_uid]['name'] = r_val.name

    known_user_ids = set(judges.keys()) | set(recorders.keys()) | set(judge_and_recorders.keys())
    guild_stats = get_guild_staff_stats(guild.id)
    for u_id, s_data in guild_stats.items():
        if u_id in known_user_ids:
            continue
            
        j_cnt = s_data.get('judge_count', 0)
        r_cnt = s_data.get('recorder_count', 0)
        jr_cnt = s_data.get('judge_and_recorder_count', 0)
        s_name = s_data.get('name', f"User_{u_id}")
        
        if not target_t_id:
            if jr_cnt > 0 and u_id not in judge_and_recorders:
                fake_matches = {f"stat_jr_{i}" for i in range(jr_cnt)}
                fake_rounds = {f"rnd_{i//2}" for i in range(jr_cnt)}
                judge_and_recorders[u_id] = {'matches': fake_matches, 'rounds': fake_rounds, 'name': s_name}

            if j_cnt > 0 and u_id not in judges and u_id not in judge_and_recorders:
                fake_matches = {f"stat_j_{i}" for i in range(j_cnt)}
                fake_rounds = {f"rnd_{i//2}" for i in range(j_cnt)}
                judges[u_id] = {'matches': fake_matches, 'rounds': fake_rounds, 'name': s_name}
                
            if r_cnt > 0 and u_id not in recorders and u_id not in judge_and_recorders:
                fake_matches = {f"stat_r_{i}" for i in range(r_cnt)}
                fake_rounds = {f"rnd_{i//2}" for i in range(r_cnt)}
                recorders[u_id] = {'matches': fake_matches, 'rounds': fake_rounds, 'name': s_name}

    if member:
        target_uid = str(member.id)
        judges = {k: v for k, v in judges.items() if k == target_uid}
        recorders = {k: v for k, v in recorders.items() if k == target_uid}
        judge_and_recorders = {k: v for k, v in judge_and_recorders.items() if k == target_uid}

    def format_staff_entry(idx, u_id, data):
        m_obj = guild.get_member(int(u_id)) if u_id.isdigit() else None
        if m_obj:
            mention = m_obj.mention
            uname = m_obj.name
        else:
            mention = f"<@{u_id}>" if u_id.isdigit() else f"@{u_id}"
            uname = data.get('name', u_id)
            
        m_count = len(data['matches'])
        r_count = len(data['rounds'])
        return f"{idx}. {mention} **{uname}** - {m_count} matches ( {r_count} rounds)"

    org_name = ORGANIZATION_NAME
    header_embed = discord.Embed(
        title="✔️ Staff Work Count",
        color=discord.Color(0x2F3136),
        timestamp=discord.utils.utcnow()
    )
    header_embed.add_field(name=f"{EMOJIS['trophy']} Tournament", value=target_t_name, inline=False)
    header_embed.add_field(name="🥀 Default Wins", value=dw_setting, inline=False)
    header_embed.add_field(name="👑 Requested By", value=interaction.user.mention, inline=False)
    
    t_slug = target_t_name.replace(' ', '_')
    header_embed.set_footer(text=f"{org_name} · {t_slug}")

    sorted_judges = sorted(judges.items(), key=lambda x: (len(x[1]['matches']), len(x[1]['rounds'])), reverse=True)
    judges_embed = discord.Embed(title=f"{EMOJIS['judge']} Judges", color=discord.Color.red())
    if sorted_judges:
        judges_embed.description = "\n".join([format_staff_entry(i, uid, d) for i, (uid, d) in enumerate(sorted_judges, 1)][:25])
    else:
        judges_embed.description = "*No judge activity recorded.*"

    sorted_recorders = sorted(recorders.items(), key=lambda x: (len(x[1]['matches']), len(x[1]['rounds'])), reverse=True)
    recorders_embed = discord.Embed(title=f"{EMOJIS['recorder']} Recorders", color=discord.Color.green())
    if sorted_recorders:
        recorders_embed.description = "\n".join([format_staff_entry(i, uid, d) for i, (uid, d) in enumerate(sorted_recorders, 1)][:25])
    else:
        recorders_embed.description = "*No recorder activity recorded.*"

    sorted_combined = sorted(judge_and_recorders.items(), key=lambda x: (len(x[1]['matches']), len(x[1]['rounds'])), reverse=True)
    combined_embed = discord.Embed(title=f"{EMOJIS['judge']} {EMOJIS['recorder']} Judge & Recorder", color=discord.Color.blue())
    if sorted_combined:
        combined_embed.description = "\n".join([format_staff_entry(i, uid, d) for i, (uid, d) in enumerate(sorted_combined, 1)][:25])
    else:
        combined_embed.description = "*No judge & recorder activity recorded.*"

    await interaction.followup.send(embeds=[header_embed, judges_embed, recorders_embed, combined_embed], ephemeral=False)



@staff_group.command(name="work", description="View staff match count and activity statistics")
@app_commands.describe(
    tournament="Select tournament to filter (optional)",
    default_wins="Include or exclude default wins / DQs",
    member="Optional staff member to filter"
)
@app_commands.autocomplete(tournament=tournament_autocomplete)
@app_commands.choices(
    default_wins=[
        app_commands.Choice(name="Including", value="Including"),
        app_commands.Choice(name="Excluded", value="Excluded"),
    ]
)
@with_guild_context
async def staff_work_cmd(

    interaction: discord.Interaction,
    tournament: Optional[str] = None,
    default_wins: Optional[app_commands.Choice[str]] = None,
    member: Optional[discord.Member] = None
):
    dw_val = default_wins.value if default_wins else "Including"
    await render_staff_work_count(interaction, tournament=tournament, default_wins=dw_val, member=member)


# ===========================================================================================
# AVAILABLE EVENTS INTERACTIVE CLAIM VIEW
# ===========================================================================================

class AvailableEventsClaimSelect(discord.ui.Select):
    def __init__(self, unassigned_events: list, guild: discord.Guild):
        options = []
        for idx, (ev_id, data) in enumerate(unassigned_events[:25], start=1):
            team1_name = data.get('team1_name') or "Team 1"
            team2_name = data.get('team2_name') or "Team 2"
            round_label = data.get('round', 'Round')
            time_str = data.get('time_str', 'N/A')
            date_str = data.get('date_str', 'N/A')
            
            lbl = f"{idx}. {team1_name} vs {team2_name}"
            if len(lbl) > 100:
                lbl = lbl[:97] + "..."
            desc = f"{round_label} • {time_str}, {date_str}"
            if len(desc) > 100:
                desc = desc[:97] + "..."
                
            options.append(discord.SelectOption(
                label=lbl,
                description=desc,
                value=str(ev_id),
                emoji="⚖️"
            ))
        super().__init__(
            placeholder="👉 Select a match from this list to claim as Judge...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="available_events_claim_select"
        )
        self.unassigned_events = unassigned_events

    async def callback(self, interaction: discord.Interaction):
        ev_id = self.values[0]
        ev = scheduled_events.get(ev_id)
        if not ev:
            await interaction.response.send_message("❌ This match could not be found or has already expired.", ephemeral=True)
            return

        is_admin = interaction.guild and interaction.user.guild_permissions.administrator
        is_owner = interaction.user.id == BOT_OWNER_ID
        head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"]) if interaction.user else None
        helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"]) if interaction.user else None
        judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"]) if interaction.user else None
        recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"]) if interaction.user else None
        staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"]) if interaction.user else None
        has_allowed_role = any([head_organizer_role, helper_team_role, judge_role, recorder_role, staff_role])

        if not (has_allowed_role or is_owner or is_admin):
            await interaction.response.send_message("❌ You do not have the required staff/judge role to claim this match.", ephemeral=True)
            return

        if ev.get('judge'):
            j_val = ev.get('judge')
            j_name = getattr(j_val, 'display_name', str(j_val))
            await interaction.response.send_message(f"❌ This match was already claimed by **{j_name}**.", ephemeral=True)
            return

        # Check if match already started
        dt = ev.get('datetime')
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
            if datetime.datetime.now(pytz.UTC) >= dt:
                await interaction.response.send_message("❌ This match has already started and can no longer be claimed.", ephemeral=True)
                return

        # Assign judge
        ev['judge'] = interaction.user
        add_judge_assignment(interaction.user.id, ev_id)
        save_scheduled_events()

        t1_name = ev.get('team1_name') or "Team 1"
        t2_name = ev.get('team2_name') or "Team 2"

        # Update original schedule message if accessible
        try:
            ch_id = ev.get('schedule_channel_id') or ev.get('channel_id')
            msg_id = ev.get('schedule_message_id')
            if ch_id and msg_id and interaction.guild:
                sched_ch = interaction.guild.get_channel(int(ch_id)) or await interaction.guild.fetch_channel(int(ch_id))
                if sched_ch:
                    orig_msg = await sched_ch.fetch_message(int(msg_id))
                    if orig_msg and orig_msg.embeds:
                        orig_embed = orig_msg.embeds[0]
                        orig_embed.color = discord.Color.green()
                        update_embed_title_with_checkmark(orig_embed)
                        update_judge_field(orig_embed, interaction.user, ev.get('recorder'))
                        
                        t1_cap = ev.get('team1_captain')
                        t2_cap = ev.get('team2_captain')
                        new_view = TakeScheduleButton(ev_id, t1_cap, t2_cap, sched_ch)
                        await orig_msg.edit(embed=orig_embed, view=new_view)
        except Exception as update_err:
            print(f"Could not update original schedule message: {update_err}")

        # Send notification to match channel if present
        try:
            match_ch_id = ev.get('channel_id')
            if match_ch_id and interaction.guild:
                match_ch = interaction.guild.get_channel(int(match_ch_id)) or await interaction.guild.fetch_channel(int(match_ch_id))
                if match_ch:
                    emoji = get_staff_emoji(interaction.guild, "judge")
                    await match_ch.send(f"{interaction.user.mention} assigned as **judge** {emoji}")
        except Exception as notify_err:
            print(f"Could not send match channel notification: {notify_err}")

        # Log activity
        log_embed = discord.Embed(
            title="⚖️ Schedule Claimed via /available_events",
            description=f"Judge **{interaction.user.display_name}** claimed match **{t1_name} vs {t2_name}** (Event ID: `{ev_id}`).",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Claimed by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)

        # Refresh the current available events message
        remaining = [item for item in self.unassigned_events if item[0] != ev_id and not scheduled_events.get(item[0], {}).get('judge')]
        
        if not remaining:
            new_embed = discord.Embed(
                title="📝 Available Events",
                description="✅ All events currently have a judge assigned!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            await interaction.response.edit_message(embed=new_embed, view=None)
        else:
            new_embed = discord.Embed(
                title="📝 Available Events",
                description="Events without a judge. Select a match below to claim it immediately!",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            new_lines = []
            for idx, (e_id, e_data) in enumerate(remaining[:25], start=1):
                r_lbl = e_data.get('round', 'Round')
                d_str = e_data.get('date_str', 'N/A')
                t_str = e_data.get('time_str', 'N/A')
                c_id = e_data.get('schedule_channel_id') or e_data.get('channel_id')
                m_id = e_data.get('schedule_message_id')
                tm1_name = e_data.get('team1_name') or "Team 1"
                tm2_name = e_data.get('team2_name') or "Team 2"
                m_link = f"https://discord.com/channels/{interaction.guild.id}/{c_id}/{m_id}" if (c_id and m_id) else None
                m_info = f"**{tm1_name}** vs **{tm2_name}**"
                if m_link:
                    line = f"{idx}. {m_info} • {r_lbl} • {t_str}, {d_str}\n   [🔗 **Jump to Schedule Message**]({m_link})"
                else:
                    line = f"{idx}. {m_info} • {r_lbl} • {t_str}, {d_str}"
                new_lines.append(line)
            new_embed.add_field(name=f"Available ({len(remaining)})", value="\n\n".join(new_lines), inline=False)
            new_embed.set_footer(text="Select an open match from the dropdown below to claim it as Judge.")
            new_view = AvailableEventsClaimView(remaining, interaction.guild)
            await interaction.response.edit_message(embed=new_embed, view=new_view)

        await interaction.followup.send(f"✅ You have successfully claimed match **{t1_name} vs {t2_name}** as Judge!", ephemeral=False)


class AvailableEventsClaimView(discord.ui.View):
    def __init__(self, unassigned_events: list, guild: discord.Guild):
        super().__init__(timeout=300)
        self.add_item(AvailableEventsClaimSelect(unassigned_events, guild))


# ===========================================================================================
# STAFF COG
# ===========================================================================================

class Staff(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="staff-update", description="Update a staff member's match count in the leaderboard")
    @app_commands.describe(
        staff_member="The staff member to update",
        role="Role to update (Judge, Recorder, or Judge & Recorder)",
        action="Add, Subtract, or Set the count",
        amount="The number of matches to add, subtract, or set to"
    )
    @app_commands.choices(
        role=[
            app_commands.Choice(name="Judge", value="judge"),
            app_commands.Choice(name="Recorder", value="recorder"),
            app_commands.Choice(name="Judge & Recorder", value="judge_and_recorder")
        ],
        action=[
            app_commands.Choice(name="Add (+)", value="add"),
            app_commands.Choice(name="Subtract (-)", value="subtract"),
            app_commands.Choice(name="Set (=)", value="set")
        ]
    )
    @with_guild_context
    async def staff_update_cmd(
        self,
        interaction: discord.Interaction,
        staff_member: discord.Member,
        role: app_commands.Choice[str],
        action: app_commands.Choice[str],
        amount: int
    ):
        if not has_organizer_permission(interaction):
            await interaction.response.send_message("❌ You need **Head Organizer** role to update staff statistics.", ephemeral=False)
            return

        if amount < 0 and action.value != "subtract":
            await interaction.response.send_message("❌ Amount cannot be negative.", ephemeral=False)
            return

        guild_id = interaction.guild.id
        stats = get_guild_staff_stats(guild_id)
        uid = str(staff_member.id)
        if uid not in stats:
            stats[uid] = {'name': staff_member.display_name, 'judge_count': 0, 'recorder_count': 0, 'judge_and_recorder_count': 0, 'last_activity': None}
        else:
            stats[uid]['name'] = staff_member.display_name

        role_key = f"{role.value}_count"
        current_count = stats[uid].get(role_key, 0)
        
        if action.value == "add":
            new_count = current_count + amount
        elif action.value == "subtract":
            new_count = max(0, current_count - amount)
        else:
            new_count = max(0, amount)

        stats[uid][role_key] = new_count
        stats[uid]['total_count'] = (
            stats[uid].get('judge_count', 0) + 
            stats[uid].get('recorder_count', 0) + 
            stats[uid].get('judge_and_recorder_count', 0)
        )
        stats[uid]['last_activity'] = datetime.datetime.utcnow().isoformat()
        save_guild_staff_stats(guild_id, stats)

        await interaction.response.send_message(f"✅ Successfully updated **{staff_member.display_name}**'s {role.name} count from {current_count} to **{new_count}**.", ephemeral=False)
        
        try:
            action_symbol = "+" if action.value == "add" else ("-" if action.value == "subtract" else "=")
            su_log_embed = discord.Embed(
                title="📊 Staff Stats Updated",
                color=discord.Color.blurple(),
                timestamp=discord.utils.utcnow()
            )
            su_log_embed.add_field(name="👤 Staff Member", value=staff_member.mention, inline=True)
            su_log_embed.add_field(name="🏷️ Role", value=role.name, inline=True)
            su_log_embed.add_field(name="🔧 Change", value=f"`{action_symbol}{amount}` ({current_count} → **{new_count}**)", inline=True)
            su_log_embed.add_field(
                name="📊 New Totals",
                value=(
                    f"⚖️ Judge: **{stats[uid].get('judge_count', 0)}**\n"
                    f"🎥 Recorder: **{stats[uid].get('recorder_count', 0)}**\n"
                    f"🎥🧑‍⚖️ Judge & Recorder: **{stats[uid].get('judge_and_recorder_count', 0)}**\n"
                    f"✅ Total: **{stats[uid].get('total_count', 0)}**"
                ),
                inline=False
            )
            su_log_embed.set_footer(text=f"Updated by {interaction.user.display_name} • ID: {interaction.user.id}")
            await log_bot_activity(interaction.guild, su_log_embed)
        except Exception as log_err:
            print(f"Error logging staff-update: {log_err}")

    async def _handle_available_events(self, interaction: discord.Interaction):
        try:
            is_owner = interaction.user.id == BOT_OWNER_ID if interaction.user else False
            is_admin = interaction.guild and interaction.user.guild_permissions.administrator if (interaction.user and interaction.guild) else False
            head_organizer_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["head_organizer"]) if interaction.user else None
            helper_team_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["helper_team"]) if interaction.user else None
            judge_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["judge"]) if interaction.user else None
            recorder_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["recorder"]) if interaction.user else None
            staff_role = discord.utils.get(interaction.user.roles, id=ROLE_IDS["staff"]) if interaction.user else None

            if not (head_organizer_role or helper_team_role or judge_role or recorder_role or staff_role or is_owner or is_admin):
                await interaction.response.send_message("❌ You need Organizer, Helper, Judge, or Staff role to view unassigned events.", ephemeral=False)
                return

            unassigned = []
            for event_id, data in scheduled_events.items():
                if str(data.get('guild_id')) != str(interaction.guild.id):
                    continue
                if data.get('status') == 'completed':
                    continue
                if not data.get('judge'):
                    unassigned.append((event_id, data))

            if not unassigned:
                await interaction.response.send_message("✅ All events currently have a judge assigned.", ephemeral=False)
                return

            try:
                unassigned.sort(key=lambda x: x[1].get('datetime') or datetime.datetime.max)
            except Exception:
                pass

            embed = discord.Embed(
                title="📝 Available Events",
                description="Events without a judge. Use the direct links or select from the dropdown below to claim immediately!",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )

            lines = []
            for idx, (ev_id, data) in enumerate(unassigned[:25], start=1):
                round_label = data.get('round', 'Round')
                date_str = data.get('date_str', 'N/A')
                time_str = data.get('time_str', 'N/A')
                ch_id = data.get('schedule_channel_id') or data.get('channel_id')
                msg_id = data.get('schedule_message_id')
                team1 = data.get('team1_captain')
                team2 = data.get('team2_captain')
                team1_name = data.get('team1_name') or (getattr(team1, 'name', 'Unknown') if team1 else 'Unknown')
                team2_name = data.get('team2_name') or (getattr(team2, 'name', 'Unknown') if team2 else 'Unknown')

                link = None
                try:
                    if interaction.guild and ch_id and msg_id:
                        link = f"https://discord.com/channels/{interaction.guild.id}/{ch_id}/{msg_id}"
                except Exception:
                    link = None

                match_info = f"**{team1_name}** vs **{team2_name}**"
                if link:
                    line = f"{idx}. {match_info} • {round_label} • {time_str}, {date_str}\n   [🔗 **Click here to jump to schedule**]({link})"
                else:
                    line = f"{idx}. {match_info} • {round_label} • {time_str}, {date_str}"
                lines.append(line)

            embed.add_field(name=f"Available ({len(unassigned)})", value="\n\n".join(lines), inline=False)
            embed.set_footer(text="Select an open match from the dropdown below to claim it as Judge instantly.")
            
            view = AvailableEventsClaimView(unassigned, interaction.guild)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        except Exception as e:
            print(f"Error in available_events: {e}")
            await interaction.response.send_message("❌ An error occurred while fetching available events.", ephemeral=False)

    @app_commands.command(name="available_events", description="List events without a judge assigned with interactive claim buttons (Judges/Organizers)")
    @with_guild_context
    async def available_events_cmd(self, interaction: discord.Interaction):
        await self._handle_available_events(interaction)

    @app_commands.command(name="unassigned_schedule", description="List all scheduled matches needing a judge with interactive claim menu")
    @with_guild_context
    async def unassigned_schedule_cmd(self, interaction: discord.Interaction):
        await self._handle_available_events(interaction)

    @app_commands.command(name="unassigned", description="Shortcut to list unassigned tournament matches")
    @with_guild_context
    async def unassigned_cmd(self, interaction: discord.Interaction):
        await self._handle_available_events(interaction)

    @app_commands.command(name="reassign", description="Resign from an event as Judge or Recorder and notify other staff to take it")
    @with_guild_context
    async def reassign_cmd(self, interaction: discord.Interaction):
        permission_level = get_user_permission_level(interaction.user.roles, interaction.user.id)
        if permission_level not in ["judge", "recorder", "organizer", "owner", "helper"]:
            await interaction.response.send_message("❌ You do not have permission to use /reassign.", ephemeral=False)
            return

        user_events = []
        for event_id, event_data in scheduled_events.items():
            if str(event_data.get('guild_id')) != str(interaction.guild.id):
                continue
            judge_val = event_data.get('judge')
            recorder_val = event_data.get('recorder')
            user_role = None
            
            if judge_val:
                try:
                    j_id = int(getattr(judge_val, 'id', judge_val))
                    if j_id == interaction.user.id:
                        user_role = "Judge"
                except (ValueError, TypeError):
                    if str(getattr(judge_val, 'id', judge_val)) == str(interaction.user.id):
                        user_role = "Judge"
            
            if recorder_val and not user_role:
                try:
                    r_id = int(getattr(recorder_val, 'id', recorder_val))
                    if r_id == interaction.user.id:
                        user_role = "Recorder"
                except (ValueError, TypeError):
                    if str(getattr(recorder_val, 'id', recorder_val)) == str(interaction.user.id):
                        user_role = "Recorder"
            
            if user_role:
                user_events.append((event_id, event_data, user_role))

        if not user_events:
            await interaction.response.send_message("❌ You are not assigned to any events as Judge or Recorder.", ephemeral=False)
            return

        class EventReassignView(discord.ui.View):
            def __init__(self, parent_bot: commands.Bot):
                super().__init__(timeout=120)
                self.parent_bot = parent_bot

            @discord.ui.select(
                placeholder="Select an event to resign from...",
                options=[
                    discord.SelectOption(
                        label=f"{role}: {event_data.get('round', 'Round')} — {event_data.get('date_str', '')}",
                        description=f"{event_data.get('time_str', 'Time')} | {event_data.get('tournament', '')}",
                        value=f"{event_id}:{role}"
                    )
                    for idx, (event_id, event_data, role) in enumerate(user_events[:25])
                ]
            )
            async def select_event(self, select_interaction: discord.Interaction, select: discord.ui.Select):
                if select_interaction.guild:
                    current_guild_id.set(select_interaction.guild.id)
                
                selected_value = select.values[0]
                selected_event_id, role_type = selected_value.split(":", 1)
                
                event_data = scheduled_events.get(selected_event_id)
                if not event_data:
                    await select_interaction.response.send_message("❌ Event not found.", ephemeral=False)
                    return

                dt = event_data.get('datetime')
                if isinstance(dt, str):
                    try: dt = datetime.datetime.fromisoformat(dt)
                    except Exception: dt = None
                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=pytz.UTC)
                    time_until = dt - datetime.datetime.now(pytz.UTC)
                    if 0 < time_until.total_seconds() < 20 * 60:
                        await select_interaction.response.send_message(
                            "❌ Cannot resign — this event starts in less than 20 minutes. Contact an organizer.", ephemeral=False
                        )
                        return

                old_staff = interaction.user
                if role_type == "Judge":
                    event_data['judge'] = None
                    event_data['judge_confirmed'] = False
                    remove_judge_assignment(interaction.user.id, selected_event_id)
                else:
                    event_data['recorder'] = None
                    event_data['recorder_confirmed'] = False
                
                save_scheduled_events()

                # Remove old staff permissions from the match ticket channel
                ticket_ch_id = event_data.get('channel_id')
                if ticket_ch_id and select_interaction.guild:
                    ticket_ch = select_interaction.guild.get_channel(ticket_ch_id)
                    if ticket_ch:
                        try:
                            await ticket_ch.set_permissions(old_staff, overwrite=None, reason=f"Staff resigned from match as {role_type}")
                        except Exception as e:
                            print(f"Error removing permissions for resigned staff from ticket room: {e}")

                sched_ch_id = event_data.get('schedule_channel_id') or event_data.get('channel_id')
                msg_id = event_data.get('schedule_message_id')
                sched_channel = self.parent_bot.get_channel(sched_ch_id) if sched_ch_id else None

                t1 = event_data.get('team1_captain')
                t2 = event_data.get('team2_captain')
                
                if sched_channel and msg_id:
                    try:
                        msg = await sched_channel.fetch_message(msg_id)
                        if msg and msg.embeds:
                            embed = msg.embeds[0]
                            if role_type == "Judge":
                                remove_field_by_name(embed, "Judge")
                                recorder = event_data.get('recorder')
                                if not recorder:
                                    embed.add_field(name=f"{EMOJIS['judge']} Judge", value="⏳ Waiting...", inline=True)
                            else:
                                remove_field_by_name(embed, "Recorder")
                                judge = event_data.get('judge')
                                if not judge:
                                    embed.add_field(name=f"{EMOJIS['recorder']} Recorder", value="⏳ Waiting...", inline=True)
                            
                            embed.color = discord.Color.blue()
                            if embed.title and embed.title.startswith("✅"):
                                embed.title = embed.title[1:]
                            new_view = TakeScheduleButton(selected_event_id, t1, t2, sched_channel)
                            await msg.edit(embed=embed, view=new_view)
                    except Exception as e:
                        print(f"Failed to restore schedule message: {e}")

                    role_key = 'judge' if role_type == "Judge" else 'recorder'
                    cfg = get_guild_config(select_interaction.guild.id) if select_interaction.guild else {}
                    role_ping_id = cfg.get('role_ids', {}).get(role_key) or ROLE_IDS.get(role_key)
                    if not role_ping_id and select_interaction.guild:
                        for r in select_interaction.guild.roles:
                            if r.name.lower() == role_key:
                                role_ping_id = r.id
                                break

                    notify_embed = discord.Embed(
                        title=f"🔄 {role_type} Needed — Schedule Open",
                        description=f"**{old_staff.display_name}** has resigned from {role_type.lower()}ing this match.\n\nA replacement {role_type.lower()} is required! Please click the appropriate button on the event post.",
                        color=discord.Color.orange(),
                        timestamp=discord.utils.utcnow()
                    )
                    notify_embed.add_field(
                        name="📋 Match Details",
                        value=f"**Tournament:** {event_data.get('tournament', 'N/A')}\n**Round:** {event_data.get('round', 'N/A')}\n**Date/Time:** {event_data.get('date_str', '')} at {event_data.get('time_str', '')}",
                        inline=False
                    )
                    notify_embed.set_footer(text=f"{ORGANIZATION_NAME} • Reassign System")
                    try:
                        content_str = f"⚠️ <@&{role_ping_id}> — A {role_type.lower()} is needed for this match!" if role_ping_id else f"⚠️ Attention Staff — A replacement {role_type.lower()} is needed for this match!"
                        await sched_channel.send(
                            content=content_str,
                            embed=notify_embed
                        )
                    except Exception as e:
                        print(f"Error sending reassign notification: {e}")

                # Audit Log
                try:
                    reassign_log_embed = discord.Embed(
                        title=f"🔄 Staff Resigned from Match: {role_type}",
                        description=(
                            f"**Staff Member:** {old_staff.mention} (`{old_staff.id}`)\n"
                            f"**Role:** {role_type}\n"
                            f"**Tournament:** {event_data.get('tournament', 'N/A')}\n"
                            f"**Round:** {event_data.get('round', 'N/A')}\n"
                            f"**Match:** {event_data.get('team1_name', '')} vs {event_data.get('team2_name', '')}"
                        ),
                        color=discord.Color.orange(),
                        timestamp=discord.utils.utcnow()
                    )
                    reassign_log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
                    await log_bot_activity(select_interaction.guild, reassign_log_embed)
                except Exception:
                    pass

                await select_interaction.response.send_message(
                    f"✅ You have been removed from the schedule as {role_type}. Staff have been notified.", ephemeral=False
                )
                self.stop()

        await interaction.response.send_message("Select the event you want to resign from:", view=EventReassignView(self.bot), ephemeral=False)

    @app_commands.command(name="exchange", description="Exchange a Judge or Recorder for an event")
    @app_commands.describe(
        role="Role to exchange",
        old_user="The old staff member removing access from",
        new_user="The new staff member granting access to"
    )
    @app_commands.choices(
        role=[
            app_commands.Choice(name="Judge", value="judge"),
            app_commands.Choice(name="Recorder", value="recorder")
        ]
    )
    @with_guild_context
    async def exchange_cmd(self, interaction: discord.Interaction, role: app_commands.Choice[str], old_user: discord.Member, new_user: discord.Member):
        permission_level = get_user_permission_level(interaction.user.roles, interaction.user.id, interaction.guild_id)
        if permission_level not in ["helper", "organizer", "owner"]:
            await interaction.response.send_message("❌ You need **Head Organizer**, **Head Helper** or **Helper Team** role to exchange staff.", ephemeral=False)
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
            await interaction.response.send_message(f"⚠️ No events in this channel are assigned to {old_user.mention} as a {role.name}.", ephemeral=False)
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
                try: remove_judge_assignment(old_user.id, ev_id)
                except Exception: pass
                add_judge_assignment(new_user.id, ev_id)
            else:
                data['recorder'] = new_user

            save_scheduled_events()
            updated_count += 1
            
        await interaction.response.send_message(f"✅ {new_user.mention} is now the **{role.name}** for {updated_count} event(s), replacing {old_user.mention}.", ephemeral=False)


async def setup(bot: commands.Bot):
    bot.tree.add_command(staff_group)
    await bot.add_cog(Staff(bot))
