import os
import io
import re
import json
import random
import asyncio
import datetime
from typing import Optional, List, Union, Any

import discord
from discord import app_commands
from discord.ext import commands

from core.config import BASE_DIR, BRAND_COLOR, ORGANIZATION_NAME, BOT_OWNER_ID
from core.state import (
    current_guild_id, with_guild_context, get_user_permission_level,
    get_org_name, is_authorized_to_configure, is_staff,
    category_monitors, save_category_monitors
)
from core.database import log_bot_activity


NOTION_HELP_URL = "https://elated-chartreuse-9a7.notion.site/Tournament-Bot-Help-Guide-37c8a2e4cbdf80af8e87d6a03b7db8e5"
RECURRING_EMBEDS_FILE = os.path.join(BASE_DIR, "recurring_embeds.json")

def load_recurring_embeds() -> dict:
    try:
        if os.path.exists(RECURRING_EMBEDS_FILE):
            with open(RECURRING_EMBEDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[RecurringEmbeds] Error loading: {e}")
    return {}

def save_recurring_embeds(data: dict):
    try:
        with open(RECURRING_EMBEDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[RecurringEmbeds] Error saving: {e}")

recurring_embeds_store: dict = load_recurring_embeds()


# ===========================================================================
# EMBED BUILDER MODALS & VIEW
# ===========================================================================

class EmbedBuilderView(discord.ui.View):
    """Persistent interactive embed builder with all editor buttons."""

    def __init__(self, interaction: discord.Interaction, target_channel: discord.TextChannel):
        super().__init__(timeout=300)
        self.author_interaction = interaction
        self.target_channel = target_channel

        self.embed_title: str = ""
        self.embed_description: str = "Your description here. This is a placeholder."
        self.embed_color: int = 0x5865F2
        self.embed_thumbnail: str = ""
        self.embed_image: str = ""
        self.embed_author_name: str = ""
        self.embed_author_icon: str = ""
        self.embed_footer: str = ""
        self.link_buttons: list = []
        self.content: str = ""

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.embed_title or None,
            description=self.embed_description or None,
            color=self.embed_color,
        )
        if self.embed_thumbnail:
            embed.set_thumbnail(url=self.embed_thumbnail)
        if self.embed_image:
            embed.set_image(url=self.embed_image)
        if self.embed_author_name:
            embed.set_author(
                name=self.embed_author_name,
                icon_url=self.embed_author_icon or discord.utils.MISSING
            )
        if self.embed_footer:
            embed.set_footer(text=self.embed_footer)
        return embed

    def build_view_with_links(self) -> discord.ui.View:
        v = discord.ui.View()
        for btn in self.link_buttons:
            v.add_item(discord.ui.Button(label=btn["label"], url=btn["url"], style=discord.ButtonStyle.link))
        return v

    async def refresh(self, interaction: discord.Interaction):
        try:
            await interaction.response.edit_message(
                content="🎨 **Design your embed:**",
                embed=self.build_embed(),
                view=self
            )
        except Exception:
            try:
                await interaction.message.edit(
                    content="🎨 **Design your embed:**",
                    embed=self.build_embed(),
                    view=self
                )
            except Exception:
                pass

    @discord.ui.button(label="📝 Edit Embed", style=discord.ButtonStyle.primary, row=0)
    async def edit_embed_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        modal = EmbedEditModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🖼️ Edit Images", style=discord.ButtonStyle.primary, row=0)
    async def edit_images_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        modal = EmbedImagesModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🎨 Edit Color", style=discord.ButtonStyle.primary, row=0)
    async def edit_color_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        modal = EmbedColorModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔗 Link Button", style=discord.ButtonStyle.primary, row=0)
    async def link_button_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        modal = EmbedLinkButtonModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="👤 Edit Author", style=discord.ButtonStyle.secondary, row=1)
    async def edit_author_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        modal = EmbedAuthorModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="✅ Send Message", style=discord.ButtonStyle.success, row=1)
    async def send_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return

        final_embed = self.build_embed()
        final_view = self.build_view_with_links() if self.link_buttons else None

        try:
            if final_view and len(final_view.children) > 0:
                await self.target_channel.send(content=self.content or None, embed=final_embed, view=final_view)
            else:
                await self.target_channel.send(content=self.content or None, embed=final_embed)

            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content=f"✅ Embed sent to {self.target_channel.mention}!",
                embed=None,
                view=self
            )
        except discord.Forbidden:
            await interaction.response.send_message(f"❌ I don't have permission to send messages in {self.target_channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error sending embed: {e}", ephemeral=True)

    @discord.ui.button(label="💬 Add Content", style=discord.ButtonStyle.secondary, row=1)
    async def add_content_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        modal = EmbedContentModal(self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.danger, row=1)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_interaction.user.id:
            await interaction.response.send_message("❌ Only the command author can use this.", ephemeral=True)
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="🗑️ Embed builder cancelled.", embed=None, view=self)


class EmbedEditModal(discord.ui.Modal, title="📝 Edit Embed"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.embed_title = discord.ui.TextInput(
            label="Title",
            placeholder="Enter embed title (leave blank for none)",
            default=builder.embed_title,
            max_length=256,
            required=False
        )
        self.embed_description = discord.ui.TextInput(
            label="Description",
            placeholder="Enter embed description...",
            default=builder.embed_description,
            style=discord.TextStyle.paragraph,
            max_length=4000,
            required=False
        )
        self.embed_footer = discord.ui.TextInput(
            label="Footer",
            placeholder="Enter footer text (leave blank for none)",
            default=builder.embed_footer,
            max_length=2048,
            required=False
        )
        self.add_item(self.embed_title)
        self.add_item(self.embed_description)
        self.add_item(self.embed_footer)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.embed_title = self.embed_title.value.strip()
        self.builder.embed_description = self.embed_description.value.strip()
        self.builder.embed_footer = self.embed_footer.value.strip()
        await self.builder.refresh(interaction)


class EmbedImagesModal(discord.ui.Modal, title="🖼️ Edit Images"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.thumbnail = discord.ui.TextInput(
            label="Thumbnail URL (small image, top-right)",
            placeholder="https://example.com/thumbnail.png",
            default=builder.embed_thumbnail,
            required=False
        )
        self.image = discord.ui.TextInput(
            label="Main Image URL (large image, bottom)",
            placeholder="https://example.com/image.png",
            default=builder.embed_image,
            required=False
        )
        self.add_item(self.thumbnail)
        self.add_item(self.image)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.embed_thumbnail = self.thumbnail.value.strip()
        self.builder.embed_image = self.image.value.strip()
        await self.builder.refresh(interaction)


class EmbedColorModal(discord.ui.Modal, title="🎨 Edit Color"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        current_hex = f"{builder.embed_color:06X}"
        self.color_input = discord.ui.TextInput(
            label="Hex Color (without #)",
            placeholder="e.g. FF5733 or 5865F2",
            default=current_hex,
            max_length=6,
            min_length=3,
            required=True
        )
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.color_input.value.strip().lstrip("#")
        try:
            self.builder.embed_color = int(raw, 16)
        except ValueError:
            await interaction.response.send_message("❌ Invalid hex color. Please use format like `FF5733`.", ephemeral=True)
            return
        await self.builder.refresh(interaction)


class EmbedLinkButtonModal(discord.ui.Modal, title="🔗 Add Link Button"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.btn_label = discord.ui.TextInput(
            label="Button Label",
            placeholder="e.g. Visit Website",
            max_length=80,
            required=True
        )
        self.btn_url = discord.ui.TextInput(
            label="Button URL",
            placeholder="https://example.com",
            required=True
        )
        self.add_item(self.btn_label)
        self.add_item(self.btn_url)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.btn_url.value.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            await interaction.response.send_message("❌ URL must start with `http://` or `https://`.", ephemeral=True)
            return
        if len(self.builder.link_buttons) >= 5:
            await interaction.response.send_message("❌ Maximum of **5 link buttons** allowed.", ephemeral=True)
            return
        self.builder.link_buttons.append({"label": self.btn_label.value.strip(), "url": url})
        await interaction.response.send_message(
            f"✅ Link button **{self.btn_label.value.strip()}** added. Total: {len(self.builder.link_buttons)}/5",
            ephemeral=True
        )


class EmbedAuthorModal(discord.ui.Modal, title="👤 Edit Author"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.author_name = discord.ui.TextInput(
            label="Author Name",
            placeholder="e.g. Tournament Admin",
            default=builder.embed_author_name,
            max_length=256,
            required=False
        )
        self.author_icon = discord.ui.TextInput(
            label="Author Icon URL (optional)",
            placeholder="https://example.com/avatar.png",
            default=builder.embed_author_icon,
            required=False
        )
        self.add_item(self.author_name)
        self.add_item(self.author_icon)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.embed_author_name = self.author_name.value.strip()
        self.builder.embed_author_icon = self.author_icon.value.strip()
        await self.builder.refresh(interaction)


class EmbedContentModal(discord.ui.Modal, title="💬 Add Content"):
    def __init__(self, builder: EmbedBuilderView):
        super().__init__()
        self.builder = builder
        self.content_input = discord.ui.TextInput(
            label="Content (plain text above embed)",
            placeholder="e.g. @everyone Check this out!",
            default=builder.content,
            style=discord.TextStyle.paragraph,
            max_length=2000,
            required=False
        )
        self.add_item(self.content_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.builder.content = self.content_input.value
        await interaction.response.send_message("✅ Content updated.", ephemeral=True)


# ===========================================================================
# COMMAND GROUPS: PURGE & RECURRING
# ===========================================================================

purge_group = app_commands.Group(name="purge", description="Delete messages from a channel")

@purge_group.command(name="all", description="Delete ALL messages in the current channel")
@with_guild_context
async def purge_all(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    channel = interaction.channel
    deleted = 0
    try:
        while True:
            msgs = await channel.purge(limit=100)
            deleted += len(msgs)
            if len(msgs) < 100:
                break
            await asyncio.sleep(1)
    except discord.Forbidden:
        await interaction.followup.send("❌ No permission to delete messages here.", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        return
    confirm = await channel.send(embed=discord.Embed(
        title="🗑️ Channel Purged",
        description=f"Deleted **{deleted}** messages.\n*Self-destructing in 5 seconds...*",
        color=discord.Color.red(), timestamp=discord.utils.utcnow()
    ).set_footer(text=f"Purged by {interaction.user.display_name}"))
    await asyncio.sleep(5)
    try: await confirm.delete()
    except Exception: pass
    await interaction.followup.send(f"✅ Purged **{deleted}** messages from {channel.mention}.", ephemeral=True)


@purge_group.command(name="amount", description="Delete a specified number of messages (1-1000)")
@app_commands.describe(count="Number of messages to delete (1-1000)")
@with_guild_context
async def purge_amount(interaction: discord.Interaction, count: int):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
        return
    if count < 1 or count > 1000:
        await interaction.response.send_message("❌ Provide a number between **1** and **1000**.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    channel = interaction.channel
    deleted = 0
    remaining = count
    try:
        while remaining > 0:
            batch = min(remaining, 100)
            msgs = await channel.purge(limit=batch)
            deleted += len(msgs)
            remaining -= len(msgs)
            if len(msgs) < batch:
                break
            await asyncio.sleep(1)
    except discord.Forbidden:
        await interaction.followup.send("❌ No permission to delete messages here.", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        return
    confirm = await channel.send(embed=discord.Embed(
        title="🗑️ Messages Purged",
        description=f"Deleted **{deleted}** message(s).\n*Self-destructing in 5 seconds...*",
        color=discord.Color.orange(), timestamp=discord.utils.utcnow()
    ).set_footer(text=f"Purged by {interaction.user.display_name}"))
    await asyncio.sleep(5)
    try: await confirm.delete()
    except Exception: pass
    await interaction.followup.send(f"✅ Deleted **{deleted}** message(s) from {channel.mention}.", ephemeral=True)


@purge_group.command(name="word", description="Delete messages containing a specific word or phrase")
@app_commands.describe(keyword="Word or phrase to search and delete")
@with_guild_context
async def purge_word(interaction: discord.Interaction, keyword: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
        return
    if not keyword.strip():
        await interaction.response.send_message("❌ Please provide a keyword.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    channel = interaction.channel
    keyword_lower = keyword.strip().lower()
    deleted = 0
    try:
        def contains_keyword(msg: discord.Message) -> bool:
            return keyword_lower in msg.content.lower()
        checked = 0
        while checked < 1000:
            msgs = await channel.purge(limit=100, check=contains_keyword)
            deleted += len(msgs)
            checked += 100
            if len(msgs) == 0:
                break
            await asyncio.sleep(1)
    except discord.Forbidden:
        await interaction.followup.send("❌ No permission to delete messages here.", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)
        return
    confirm = await channel.send(embed=discord.Embed(
        title="🗑️ Keyword Purge Complete",
        description=f"Deleted **{deleted}** message(s) containing `{keyword}`.\n*Self-destructing in 5 seconds...*",
        color=discord.Color.orange(), timestamp=discord.utils.utcnow()
    ).set_footer(text=f"Purged by {interaction.user.display_name}"))
    await asyncio.sleep(5)
    try: await confirm.delete()
    except Exception: pass
    await interaction.followup.send(f"✅ Deleted **{deleted}** message(s) matching `{keyword}` from {channel.mention}.", ephemeral=True)


recurring_group = app_commands.Group(name="recurring", description="Manage recurring embeds in channels")
recurring_embed_subgroup = app_commands.Group(name="embed", description="Manage recurring embeds", parent=recurring_group)

@recurring_embed_subgroup.command(name="set", description="Set a new recurring embed that auto-posts at a set interval")
@app_commands.describe(
    embed_id="Unique ID for this embed (e.g. rules_reminder)",
    channel="Channel to post the embed in",
    title="Embed title",
    description="Embed body text",
    interval_hours="How often to re-post (in hours). Default: 24",
    color="Hex color code (e.g. FF5733). Default: Discord blurple"
)
@with_guild_context
async def recurring_embed_set(
    interaction: discord.Interaction,
    embed_id: str,
    channel: discord.TextChannel,
    title: str,
    description: str,
    interval_hours: float = 24.0,
    color: Optional[str] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
        return
    if interval_hours < 0.5:
        await interaction.response.send_message("❌ Minimum interval is **0.5 hours** (30 minutes).", ephemeral=True)
        return
    embed_id_clean = embed_id.strip().lower().replace(" ", "_")
    guild_key = f"{interaction.guild_id}:{embed_id_clean}"
    color_val = 0x5865F2
    if color:
        try: color_val = int(color.lstrip("#").lstrip("0x"), 16)
        except ValueError: pass
    recurring_embeds_store[guild_key] = {
        "guild_id": str(interaction.guild_id),
        "channel_id": str(channel.id),
        "title": title,
        "description": description,
        "interval_hours": interval_hours,
        "color": color_val,
        "created_by": str(interaction.user.id),
        "last_posted": None
    }
    save_recurring_embeds(recurring_embeds_store)
    reply = discord.Embed(
        title=f"✅ Recurring Embed Set — `{embed_id_clean}`",
        description=(
            f"**Channel:** {channel.mention}\n"
            f"**Interval:** Every **{interval_hours:.1f}h**\n"
            f"**Title:** {title}\n\n"
            "The embed will post automatically at the configured interval."
        ),
        color=discord.Color.green(), timestamp=discord.utils.utcnow()
    )
    reply.set_footer(text=f"Set by {interaction.user.display_name}")
    await interaction.response.send_message(embed=reply, ephemeral=False)


@recurring_embed_subgroup.command(name="edit", description="Edit an existing recurring embed")
@app_commands.describe(
    embed_id="ID of the recurring embed to edit",
    title="New title (leave blank to keep current)",
    description="New description (leave blank to keep current)",
    interval_hours="New interval in hours (leave blank to keep current)",
    channel="New channel (leave blank to keep current)"
)
@with_guild_context
async def recurring_embed_edit(
    interaction: discord.Interaction,
    embed_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    interval_hours: Optional[float] = None,
    channel: Optional[discord.TextChannel] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
        return
    embed_id_clean = embed_id.strip().lower().replace(" ", "_")
    guild_key = f"{interaction.guild_id}:{embed_id_clean}"
    if guild_key not in recurring_embeds_store:
        await interaction.response.send_message(f"❌ No recurring embed found with ID `{embed_id_clean}`.", ephemeral=True)
        return
    cfg = recurring_embeds_store[guild_key]
    changes = []
    if title:
        cfg["title"] = title; changes.append(f"**Title:** {title}")
    if description:
        cfg["description"] = description; changes.append("**Description:** updated")
    if interval_hours is not None:
        if interval_hours < 0.5:
            await interaction.response.send_message("❌ Minimum interval is **0.5 hours**.", ephemeral=True)
            return
        cfg["interval_hours"] = interval_hours; changes.append(f"**Interval:** every {interval_hours:.1f}h")
    if channel:
        cfg["channel_id"] = str(channel.id); changes.append(f"**Channel:** {channel.mention}")
    if not changes:
        await interaction.response.send_message("ℹ️ No changes provided — embed unchanged.", ephemeral=True)
        return
    recurring_embeds_store[guild_key] = cfg
    save_recurring_embeds(recurring_embeds_store)
    reply = discord.Embed(
        title=f"✏️ Recurring Embed Updated — `{embed_id_clean}`",
        description="\n".join(f"• {c}" for c in changes),
        color=discord.Color.blue(), timestamp=discord.utils.utcnow()
    )
    reply.set_footer(text=f"Edited by {interaction.user.display_name}")
    await interaction.response.send_message(embed=reply, ephemeral=False)


@recurring_embed_subgroup.command(name="delete", description="Delete a recurring embed and stop it from posting")
@app_commands.describe(embed_id="ID of the recurring embed to delete")
@with_guild_context
async def recurring_embed_delete(interaction: discord.Interaction, embed_id: str):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
        await interaction.response.send_message("❌ You need **Manage Messages** permission.", ephemeral=True)
        return
    embed_id_clean = embed_id.strip().lower().replace(" ", "_")
    guild_key = f"{interaction.guild_id}:{embed_id_clean}"
    if guild_key not in recurring_embeds_store:
        await interaction.response.send_message(f"❌ No recurring embed found with ID `{embed_id_clean}`.", ephemeral=True)
        return
    reply = discord.Embed(
        title=f"🗑️ Recurring Embed Deleted — `{embed_id_clean}`",
        description="Removed and will no longer auto-post.",
        color=discord.Color.red(), timestamp=discord.utils.utcnow()
    )
    reply.set_footer(text=f"Deleted by {interaction.user.display_name}")
    await interaction.response.send_message(embed=reply, ephemeral=False)


# ===========================================================================
# ROLE MANAGEMENT GROUP (/role remove all)
# ===========================================================================

role_group = app_commands.Group(name="role", description="Manage guild member roles")
role_remove_subgroup = app_commands.Group(name="remove", description="Remove roles from members", parent=role_group)

@role_remove_subgroup.command(name="all", description="Remove a specified role from all members in the server")
@app_commands.describe(role="The role to remove from all members")
@with_guild_context
async def role_remove_all_cmd(interaction: discord.Interaction, role: discord.Role):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_roles or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Manage Roles** permission to use this command.", ephemeral=True)
        return
    if interaction.guild.me.top_role <= role:
        await interaction.response.send_message(f"❌ Cannot manage {role.mention} because it is higher than or equal to my highest role ({interaction.guild.me.top_role.mention}).", ephemeral=True)
        return

    members_with_role = [m for m in interaction.guild.members if role in m.roles]
    if not members_with_role:
        await interaction.response.send_message(f"ℹ️ No members currently have the role {role.mention}.", ephemeral=True)
        return

    class ConfirmRoleRemoveView(discord.ui.View):
        def __init__(self, author_id: int):
            super().__init__(timeout=60.0)
            self.author_id = author_id
            self.confirmed = False

        async def interaction_check(self, inter: discord.Interaction) -> bool:
            if inter.user.id != self.author_id:
                await inter.response.send_message("❌ Only the command author can confirm.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label=f"Confirm & Remove from {len(members_with_role)} members", style=discord.ButtonStyle.danger, emoji="⚠️")
        async def confirm(self, inter: discord.Interaction, btn: discord.ui.Button):
            self.confirmed = True
            self.stop()
            for c in self.children: c.disabled = True
            await inter.response.edit_message(view=self)

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
        async def cancel(self, inter: discord.Interaction, btn: discord.ui.Button):
            self.confirmed = False
            self.stop()
            for c in self.children: c.disabled = True
            await inter.response.edit_message(content="❌ Role removal cancelled.", embed=None, view=self)

    confirm_embed = discord.Embed(
        title="⚠️ Bulk Role Removal Confirmation",
        description=f"Are you sure you want to remove {role.mention} from **{len(members_with_role)} member(s)**?",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    confirm_embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    view = ConfirmRoleRemoveView(interaction.user.id)
    await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=False)

    await view.wait()
    if not view.confirmed:
        return

    status_msg = await interaction.followup.send(f"⏳ Removing {role.mention} from {len(members_with_role)} member(s)...")

    removed_count = 0
    failed_count = 0
    for idx, m in enumerate(members_with_role):
        try:
            await m.remove_roles(role, reason=f"Bulk role removal by {interaction.user.name}")
            removed_count += 1
            if (idx + 1) % 10 == 0 or (idx + 1) == len(members_with_role):
                try:
                    await status_msg.edit(content=f"⏳ Removed from **{removed_count}/{len(members_with_role)}** members...")
                except Exception:
                    pass
            await asyncio.sleep(0.35)
        except Exception as e:
            print(f"Error removing role from {m.display_name}: {e}")
            failed_count += 1

    res_embed = discord.Embed(
        title="✅ Role Removal Complete",
        description=f"Successfully removed {role.mention} from **{removed_count}** member(s).",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    if failed_count > 0:
        res_embed.add_field(name="Failed", value=f"{failed_count} members", inline=True)
    res_embed.set_footer(text=f"{interaction.guild.name} • Role Manager")
    await status_msg.edit(content=None, embed=res_embed)


# ===========================================================================
# NICKNAME MANAGEMENT GROUP (/nickname reset)
# ===========================================================================

nickname_group = app_commands.Group(name="nickname", description="Manage member nicknames")

@nickname_group.command(name="reset", description="Reset a user's server display name to their username")
@app_commands.describe(member="Member whose nickname to reset (defaults to yourself)")
@with_guild_context
async def nickname_reset_cmd(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return

    target = member or interaction.user
    if target != interaction.user and not (interaction.user.guild_permissions.manage_nicknames or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Manage Nicknames** permission to reset other members' nicknames.", ephemeral=True)
        return

    if target != interaction.guild.owner and interaction.guild.me.top_role <= target.top_role and target != interaction.user:
        await interaction.response.send_message(f"❌ Cannot change nickname for {target.mention} because their role is higher than or equal to my highest role.", ephemeral=True)
        return

    try:
        old_nick = target.display_name
        await target.edit(nick=None, reason=f"Nickname reset by {interaction.user.name}")
        embed = discord.Embed(
            title="🏷️ Nickname Reset",
            description=f"Reset server display name for {target.mention} (`{old_nick}` ➔ `{target.name}`).",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Reset by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to reset nickname: {e}", ephemeral=True)


# ===========================================================================
# CHANNEL MANAGEMENT GROUP (/channel lock, /channel unlock, /channel add)
# ===========================================================================

channel_group = app_commands.Group(name="channel", description="Manage channel access and moderation")

@channel_group.command(name="lock", description="Prevent regular members from sending messages in a channel")
@app_commands.describe(channel="Channel to lock (defaults to current channel)")
@with_guild_context
async def channel_lock_cmd(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Manage Channels** permission to use this command.", ephemeral=True)
        return

    target_ch = channel or interaction.channel
    try:
        overwrites = target_ch.overwrites_for(interaction.guild.default_role)
        overwrites.send_messages = False
        overwrites.send_messages_in_threads = False
        await target_ch.set_permissions(interaction.guild.default_role, overwrite=overwrites, reason=f"Channel locked by {interaction.user.name}")

        embed = discord.Embed(
            title="🔒 Channel Locked",
            description="This channel has been locked. Regular members can no longer send messages.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Locked by {interaction.user.display_name}")
        await target_ch.send(embed=embed)
        if target_ch != interaction.channel:
            await interaction.response.send_message(f"🔒 Locked {target_ch.mention} successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to lock channel: {e}", ephemeral=True)

@channel_group.command(name="unlock", description="Allow regular members to send messages again")
@app_commands.describe(channel="Channel to unlock (defaults to current channel)")
@with_guild_context
async def channel_unlock_cmd(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Manage Channels** permission to use this command.", ephemeral=True)
        return

    target_ch = channel or interaction.channel
    try:
        overwrites = target_ch.overwrites_for(interaction.guild.default_role)
        overwrites.send_messages = None
        overwrites.send_messages_in_threads = None
        await target_ch.set_permissions(interaction.guild.default_role, overwrite=overwrites, reason=f"Channel unlocked by {interaction.user.name}")

        embed = discord.Embed(
            title="🔓 Channel Unlocked",
            description="This channel has been unlocked. Members can send messages again.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Unlocked by {interaction.user.display_name}")
        await target_ch.send(embed=embed)
        if target_ch != interaction.channel:
            await interaction.response.send_message(f"🔓 Unlocked {target_ch.mention} successfully.", ephemeral=True)
        else:
            await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to unlock channel: {e}", ephemeral=True)

@channel_group.command(name="add", description="Add a user or role to the channel")
@app_commands.describe(
    user="The user to add to this channel (optional)",
    role="The role to add to this channel (optional)",
    channel="The channel to add to (defaults to current channel)"
)
@with_guild_context
async def channel_add_cmd(
    interaction: discord.Interaction,
    user: Optional[discord.Member] = None,
    role: Optional[discord.Role] = None,
    channel: Optional[discord.TextChannel] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.manage_channels or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Manage Channels** permission to use this command.", ephemeral=True)
        return

    target = user or role
    if not target:
        await interaction.response.send_message("❌ Please specify either a `user` or a `role` to add.", ephemeral=True)
        return

    target_ch = channel or interaction.channel
    try:
        overwrites = target_ch.overwrites_for(target)
        overwrites.view_channel = True
        overwrites.send_messages = True
        overwrites.read_message_history = True
        await target_ch.set_permissions(target, overwrite=overwrites, reason=f"Added by {interaction.user.name}")

        embed = discord.Embed(
            title="✅ Channel Access Granted",
            description=f"Added {target.mention} to {target_ch.mention} with view and send permissions.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Added by {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to add to channel: {e}", ephemeral=True)


# ===========================================================================
# TIMEOUT MODERATION GROUP (/timeout add, /timeout remove)
# ===========================================================================

def parse_duration(duration_str: str) -> Optional[datetime.timedelta]:
    m = re.match(r'^(\d+)\s*([smhdw])$', duration_str.strip().lower())
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)
    if unit == 's': return datetime.timedelta(seconds=val)
    elif unit == 'm': return datetime.timedelta(minutes=val)
    elif unit == 'h': return datetime.timedelta(hours=val)
    elif unit == 'd': return datetime.timedelta(days=val)
    elif unit == 'w': return datetime.timedelta(weeks=val)
    return None

timeout_group = app_commands.Group(name="timeout", description="Manage user timeouts and moderation")

@timeout_group.command(name="add", description="Timeout a user")
@app_commands.describe(
    user="The user to timeout",
    duration="Timeout duration (e.g. 5m, 1h, 1d, 7d, max 28d)",
    reason="Reason for the timeout"
)
@with_guild_context
async def timeout_add_cmd(
    interaction: discord.Interaction,
    user: discord.Member,
    duration: str,
    reason: Optional[str] = "No reason provided"
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Timeout Members** permission to use this command.", ephemeral=True)
        return

    td = parse_duration(duration)
    if not td or td.total_seconds() < 10 or td.total_seconds() > 28 * 86400:
        await interaction.response.send_message("❌ Invalid duration. Please provide a duration between `10s` and `28d` (e.g. `10m`, `2h`, `1d`, `7d`).", ephemeral=True)
        return

    if user == interaction.guild.owner or (interaction.guild.me.top_role <= user.top_role and user != interaction.user):
        await interaction.response.send_message(f"❌ Cannot timeout {user.mention} due to role hierarchy.", ephemeral=True)
        return

    try:
        until_dt = discord.utils.utcnow() + td
        await user.timeout(until_dt, reason=f"{reason} (by {interaction.user.name})")

        embed = discord.Embed(
            title="⏳ User Timed Out",
            description=f"{user.mention} has been timed out until <t:{int(until_dt.timestamp())}:F> (<t:{int(until_dt.timestamp())}:R>).",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 User", value=f"{user.display_name} (`{user.id}`)", inline=True)
        embed.add_field(name="⏱️ Duration", value=duration, inline=True)
        embed.add_field(name="📌 Reason", value=reason, inline=False)
        embed.set_footer(text=f"Moderator: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to timeout user: {e}", ephemeral=True)

@timeout_group.command(name="remove", description="Remove timeout from a user")
@app_commands.describe(user="The user to remove timeout from", reason="Reason for removing timeout")
@with_guild_context
async def timeout_remove_cmd(interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = "Timeout removed by staff"):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.moderate_members or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Timeout Members** permission to use this command.", ephemeral=True)
        return

    try:
        await user.timeout(None, reason=f"{reason} (by {interaction.user.name})")
        embed = discord.Embed(
            title="✅ Timeout Removed",
            description=f"Timeout has been removed for {user.mention}.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👤 User", value=f"{user.display_name} (`{user.id}`)", inline=True)
        embed.add_field(name="📌 Reason", value=reason, inline=False)
        embed.set_footer(text=f"Moderator: {interaction.user.display_name}")
        await interaction.response.send_message(embed=embed)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to remove timeout: {e}", ephemeral=True)


# ===========================================================================
# CATEGORY MONITOR GROUP (/categorymonitor set, view, remove)
# ===========================================================================

categorymonitor_group = app_commands.Group(name="categorymonitor", description="Monitor category channel counts and thresholds")

@categorymonitor_group.command(name="set", description="Set up or update category monitoring")
@app_commands.describe(
    category="The category to monitor",
    pingtarget="Role or user to alert when threshold is reached",
    threshold="Channel count threshold to alert (default: 45)",
    alert_channel="Channel to post warning alert (defaults to current channel)"
)
@with_guild_context
async def categorymonitor_set_cmd(
    interaction: discord.Interaction,
    category: discord.CategoryChannel,
    pingtarget: Union[discord.Role, discord.Member],
    threshold: Optional[int] = 45,
    alert_channel: Optional[discord.TextChannel] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    if threshold < 1 or threshold > 50:
        await interaction.response.send_message("❌ Threshold must be between 1 and 50 channels (Discord max limit is 50).", ephemeral=True)
        return

    target_alert_ch = alert_channel or interaction.channel
    guild_id = str(interaction.guild.id)
    cat_key = f"{guild_id}:{category.id}"

    category_monitors[cat_key] = {
        "guild_id": guild_id,
        "category_id": category.id,
        "category_name": category.name,
        "ping_target_id": pingtarget.id,
        "is_role": isinstance(pingtarget, discord.Role),
        "threshold": threshold,
        "alert_channel_id": target_alert_ch.id,
        "set_by": interaction.user.id
    }
    save_category_monitors()

    embed = discord.Embed(
        title="📊 Category Monitor Configured",
        description=f"Now monitoring category **{category.name}**.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="📁 Category", value=f"{category.name} (`{category.id}`)", inline=True)
    embed.add_field(name="📈 Current Channels", value=f"**{len(category.channels)} / 50**", inline=True)
    embed.add_field(name="⚠️ Alert Threshold", value=f"**{threshold}** channels", inline=True)
    embed.add_field(name="🔔 Ping Target", value=pingtarget.mention, inline=True)
    embed.add_field(name="📢 Alert Channel", value=target_alert_ch.mention, inline=True)
    embed.set_footer(text=f"Configured by {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

@categorymonitor_group.command(name="view", description="View current category monitoring settings")
@with_guild_context
async def categorymonitor_view_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    active = [v for k, v in category_monitors.items() if v.get("guild_id") == guild_id]

    if not active:
        await interaction.response.send_message("ℹ️ No active category monitors configured for this server. Use `/categorymonitor set`.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📊 Active Category Monitors",
        description=f"Server: **{interaction.guild.name}**\nTotal Monitored Categories: **{len(active)}**",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    for mon in active:
        cat_id = mon.get("category_id")
        cat = interaction.guild.get_channel(cat_id)
        c_count = len(cat.channels) if cat else "N/A"
        thresh = mon.get("threshold", 45)
        p_id = mon.get("ping_target_id")
        is_r = mon.get("is_role", False)
        p_mention = f"<@&{p_id}>" if is_r else f"<@{p_id}>"
        ch_id = mon.get("alert_channel_id")
        val = (
            f"• **Channel Count:** `{c_count} / 50`\n"
            f"• **Threshold:** `{thresh}` channels\n"
            f"• **Alert Target:** {p_mention}\n"
            f"• **Alert Channel:** <#{ch_id}>"
        )
        embed.add_field(name=f"📁 {cat.name if cat else mon.get('category_name')}", value=val, inline=False)

    embed.set_footer(text=f"{interaction.guild.name} • Category Monitor")
    await interaction.response.send_message(embed=embed)

@categorymonitor_group.command(name="remove", description="Remove category monitoring")
@app_commands.describe(category="The category to remove monitoring for")
@with_guild_context
async def categorymonitor_remove_cmd(interaction: discord.Interaction, category: discord.CategoryChannel):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    guild_id = str(interaction.guild.id)
    cat_key = f"{guild_id}:{category.id}"
    if cat_key in category_monitors:
        del category_monitors[cat_key]
        save_category_monitors()
        await interaction.response.send_message(f"✅ Removed monitoring for category **{category.name}**.")
    else:
        await interaction.response.send_message(f"❌ Category **{category.name}** is not currently monitored.", ephemeral=True)


# ===========================================================================
# AVATAR & SERVER INFO/BANLIST COMMANDS
# ===========================================================================

@app_commands.command(name="avatar", description="Get the avatar of a user")
@app_commands.describe(user="The user to get the avatar of (defaults to yourself)")
@with_guild_context
async def avatar_cmd(interaction: discord.Interaction, user: Optional[discord.User] = None):
    target = user or interaction.user
    avatar_url = target.display_avatar.url

    embed = discord.Embed(
        title=f"🖼️ Avatar — {target.display_name}",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )
    embed.set_image(url=avatar_url)
    
    links = [
        f"[PNG]({target.display_avatar.with_format('png').url})",
        f"[JPG]({target.display_avatar.with_format('jpeg').url})",
        f"[WEBP]({target.display_avatar.with_format('webp').url})"
    ]
    if target.display_avatar.is_animated():
        links.append(f"[GIF]({target.display_avatar.with_format('gif').url})")

    embed.description = " • ".join(links)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)


server_group = app_commands.Group(name="server", description="Server utilities and information")

@server_group.command(name="info", description="Get information about the server")
@with_guild_context
async def server_info_cmd(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return

    g = interaction.guild
    created_ts = int(g.created_at.timestamp())
    members = g.members
    humans = sum(1 for m in members if not m.bot)
    bots = sum(1 for m in members if m.bot)

    embed = discord.Embed(
        title=f"🏛️ Server Info — {g.name}",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )
    if g.icon:
        embed.set_thumbnail(url=g.icon.url)
    if g.banner:
        embed.set_image(url=g.banner.url)

    embed.add_field(name="👑 Owner", value=f"{g.owner.mention if g.owner else 'Unknown'}", inline=True)
    embed.add_field(name="🆔 Server ID", value=f"`{g.id}`", inline=True)
    embed.add_field(name="📅 Created", value=f"<t:{created_ts}:F> (<t:{created_ts}:R>)", inline=True)
    embed.add_field(name="👥 Members", value=f"**{g.member_count}** ({humans} Humans, {bots} Bots)", inline=True)
    embed.add_field(name="🛡️ Roles", value=f"`{len(g.roles)}` roles", inline=True)
    embed.add_field(name="💬 Channels", value=f"`{len(g.text_channels)}` Text, `{len(g.voice_channels)}` Voice, `{len(g.categories)}` Categories", inline=True)
    embed.add_field(name="🚀 Boost Status", value=f"Level **{g.premium_tier}** ({g.premium_subscription_count} Boosts)", inline=True)
    embed.add_field(name="🔒 Verification", value=f"{str(g.verification_level).title()}", inline=True)

    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)

@server_group.command(name="banlist", description="Generate a list of all banned users")
@app_commands.describe(format="Output format (embed or file, default: embed)")
@with_guild_context
async def server_banlist_cmd(interaction: discord.Interaction, format: Optional[str] = "embed"):
    if not interaction.guild:
        await interaction.response.send_message("❌ Server only.", ephemeral=True)
        return
    if not (interaction.user.guild_permissions.ban_members or interaction.user.guild_permissions.administrator or interaction.user.id == BOT_OWNER_ID):
        await interaction.response.send_message("❌ You need **Ban Members** permission to view the banlist.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    try:
        bans = [ban async for ban in interaction.guild.bans(limit=1000)]
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to fetch bans: {e}")
        return

    if not bans:
        await interaction.followup.send("🕊️ There are no banned users in this server.")
        return

    if format == "file" or len(bans) > 20:
        lines = ["ID,Username,Reason"]
        for b in bans:
            u = b.user
            r = b.reason or "No reason provided"
            lines.append(f'"{u.id}","{u.name}","{r.replace(chr(34), chr(39))}"')
        csv_data = "\n".join(lines)
        file = discord.File(io.BytesIO(csv_data.encode('utf-8')), filename=f"banlist_{interaction.guild.id}.csv")
        await interaction.followup.send(f"📋 Banned users list for **{interaction.guild.name}** ({len(bans)} users):", file=file)
    else:
        embed = discord.Embed(
            title=f"🔨 Banned Users ({len(bans)})",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        for b in bans[:20]:
            r = b.reason or "No reason provided"
            embed.add_field(name=f"{b.user.name} (`{b.user.id}`)", value=f"Reason: {r}", inline=False)
        embed.set_footer(text=f"{interaction.guild.name} • Banlist")
        await interaction.followup.send(embed=embed)


# ===========================================================================
# UTILITIES COG
# ===========================================================================

class Utilities(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.recurring_task = asyncio.create_task(self.recurring_embed_loop())


    def cog_unload(self):
        if self.recurring_task and not self.recurring_task.done():
            self.recurring_task.cancel()

    async def recurring_embed_loop(self):
        try:
            await self.bot.wait_until_ready()
        except Exception:
            return
        print("[RecurringEmbeds] Background loop started.")

        while not self.bot.is_closed():
            now = datetime.datetime.utcnow()
            to_update = {}
            for embed_id, cfg in list(recurring_embeds_store.items()):
                try:
                    interval_hours = float(cfg.get("interval_hours", 24))
                    last_posted_str = cfg.get("last_posted")
                    last_posted = datetime.datetime.fromisoformat(last_posted_str) if last_posted_str else datetime.datetime.min
                    if (now - last_posted).total_seconds() < interval_hours * 3600:
                        continue
                    channel_id = int(cfg.get("channel_id", 0))
                    channel = self.bot.get_channel(channel_id)
                    if not channel:
                        try: channel = await self.bot.fetch_channel(channel_id)
                        except Exception: continue
                    color_raw = cfg.get("color", 0x5865F2)
                    color_val = int(color_raw, 16) if isinstance(color_raw, str) else int(color_raw)
                    embed = discord.Embed(
                        title=cfg.get("title", "📢 Announcement"),
                        description=cfg.get("description", ""),
                        color=color_val,
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_footer(text=f"📅 Recurring — every {interval_hours:.0f}h")
                    await channel.send(embed=embed)
                    cfg["last_posted"] = now.isoformat()
                    to_update[embed_id] = cfg
                    print(f"[RecurringEmbeds] ✅ Posted '{embed_id}'")
                except Exception as e:
                    print(f"[RecurringEmbeds] Error on {embed_id}: {e}")
            if to_update:
                recurring_embeds_store.update(to_update)
                save_recurring_embeds(recurring_embeds_store)
            await asyncio.sleep(60)

    @app_commands.command(name="help", description="Show all available bot commands and guide")
    @with_guild_context
    async def help_command(self, interaction: discord.Interaction):
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
            bot_icon = self.bot.user.display_avatar.url if self.bot.user.display_avatar else None
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
                print(f"Error logging help command: {log_err}")

        except Exception as e:
            print(f"Error in help command: {e}")
            await interaction.response.send_message("❌ An error occurred while generating help.", ephemeral=False)

    @app_commands.command(name="info", description="Display bot information and statistics")
    @with_guild_context
    async def info_command(self, interaction: discord.Interaction):
        try:
            total_members = sum(g.member_count for g in self.bot.guilds if g.member_count)
            total_channels = sum(len(g.channels) for g in self.bot.guilds)
            
            embed = discord.Embed(
                title=f"ℹ️ {ORGANIZATION_NAME} Bot Information",
                description="Tournament management bot for esports competitions",
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            
            embed.add_field(
                name="🤖 Bot Details",
                value=f"**Name:** {self.bot.user.name}\n"
                      f"**ID:** {self.bot.user.id}\n"
                      f"**Latency:** {round(self.bot.latency * 1000)}ms",
                inline=True
            )
            embed.add_field(
                name="📊 Bot Statistics",
                value=f"**Servers:** {len(self.bot.guilds)}\n"
                      f"**Users:** {total_members:,}\n"
                      f"**Channels:** {total_channels:,}",
                inline=True
            )
            if interaction.guild:
                embed.add_field(
                    name="🏠 Current Server",
                    value=f"**Name:** {interaction.guild.name}\n"
                          f"**Members:** {interaction.guild.member_count:,}\n"
                          f"**Created:** {interaction.guild.created_at.strftime('%d/%m/%Y')}",
                    inline=True
                )
            
            total_commands = len(self.bot.tree.get_commands())
            embed.add_field(
                name="⚙️ Commands",
                value=f"**Total Commands:** {total_commands}\n"
                      f"**Categories:** Tournament, Event Management, Staff, Utility, Settings",
                inline=False
            )
            embed.add_field(
                name="🏆 Organization",
                value=f"{ORGANIZATION_NAME}",
                inline=False
            )
            if self.bot.user.avatar:
                embed.set_thumbnail(url=self.bot.user.avatar.url)
            embed.set_footer(text=f"Requested by {interaction.user.name}")
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f"❌ An error occurred: {str(e)}", ephemeral=False)

    @app_commands.command(name="time", description="Get a random match time from fixed 30-min slots (10:00-19:00 UTC)")
    @with_guild_context
    async def time_command(self, interaction: discord.Interaction):
        slots = [
            "10:00 UTC", "10:30 UTC", "11:00 UTC", "11:30 UTC",
            "12:00 UTC", "12:30 UTC", "13:00 UTC", "13:30 UTC",
            "14:00 UTC", "14:30 UTC", "15:00 UTC", "15:30 UTC",
            "16:00 UTC", "16:30 UTC", "17:00 UTC", "17:30 UTC",
            "18:00 UTC", "18:30 UTC", "19:00 UTC",
        ]
        chosen_time = random.choice(slots)
        slots_display = "  ".join(slots)
        
        embed = discord.Embed(
            title="⏰ Match Time (30‑min slots)",
            description=f"**Your random match time:** `{chosen_time}`",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🕒 Available Slots", value=slots_display, inline=False)
        embed.add_field(name="📅 Range", value="From **10:00** to **19:00 UTC** (every 30 minutes)", inline=False)
        embed.set_footer(text=f"Match Time Generator • {ORGANIZATION_NAME}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="maps", description="Randomly select 3, 5, or 7 maps for gameplay")
    @app_commands.describe(count="Number of maps to select (3, 5, or 7)")
    @with_guild_context
    async def maps_command(self, interaction: discord.Interaction, count: int):
        maps_list = [
            "New Storm (2024)", "Arid Frontier", "Islands of Iceland",
            "Unexplored Rocks", "Arctic", "Lost City", "Polar Frontier",
            "Hidden Dragon", "Monstrous Maelstrom", "Two Samurai",
            "Stone Peaks", "Viking Bay", "Rising Fortress", "Greenlands", "Old Storm"
        ]
        if count not in [3, 5, 7]:
            await interaction.response.send_message("❌ Please select 3, 5, or 7 maps only.", ephemeral=False)
            return
        
        selected_maps = random.sample(maps_list, count)
        embed = discord.Embed(
            title=f"🗺️ Random Map Selection {ORGANIZATION_NAME}",
            description=f"**Randomly selected {count} map(s):**",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        selected_maps_text = "\n".join([f"• {map_name}" for map_name in selected_maps])
        embed.add_field(name=f"🎯 Selected Maps ({count})", value=selected_maps_text, inline=False)
        embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="choose", description="Randomly choose from a list of options")
    @app_commands.describe(options="List of options separated by commas")
    @with_guild_context
    async def choose_command(self, interaction: discord.Interaction, options: str):
        option_list = [option.strip() for option in options.split(',') if option.strip()]
        if len(option_list) < 2:
            await interaction.response.send_message("❌ Please provide at least 2 options separated by commas.", ephemeral=False)
            return
        if len(option_list) > 20:
            await interaction.response.send_message("❌ Too many options! Please provide 20 or fewer options.", ephemeral=False)
            return
        chosen_option = random.choice(option_list)
        embed = discord.Embed(
            title="🎲 Random Choice",
            description=f"**Selected:** {chosen_option}",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow()
        )
        options_text = "\n".join([f"• {option}" for option in option_list])
        embed.add_field(name=f"📋 Available Options ({len(option_list)})", value=options_text, inline=False)
        embed.set_footer(text=f"Powered by • {ORGANIZATION_NAME}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="embed", description="Design and send a custom embed to any channel")
    @app_commands.describe(channel="The channel to send the embed to")
    @with_guild_context
    async def embed_builder(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild:
            await interaction.response.send_message("❌ Server only.", ephemeral=True)
            return
        if not (interaction.user.guild_permissions.manage_messages or interaction.user.guild_permissions.administrator):
            await interaction.response.send_message("❌ You need **Manage Messages** permission to use this command.", ephemeral=True)
            return

        view = EmbedBuilderView(interaction, channel)
        for item in view.children:
            if hasattr(item, 'label') and "Send Message" in (item.label or ""):
                item.label = f"✅ Send Message to → 🛡️ {channel.name.upper()}"
                break

        preview_embed = discord.Embed(
            description="Your description here. This is a placeholder.",
            color=0x5865F2
        )
        await interaction.response.send_message(
            content="🎨 **Design your embed:**",
            embed=preview_embed,
            view=view,
            ephemeral=False
        )


async def setup(bot: commands.Bot):
    bot.tree.add_command(purge_group)
    bot.tree.add_command(recurring_group)
    bot.tree.add_command(role_group)
    bot.tree.add_command(nickname_group)
    bot.tree.add_command(channel_group)
    bot.tree.add_command(timeout_group)
    bot.tree.add_command(categorymonitor_group)
    bot.tree.add_command(avatar_cmd)
    bot.tree.add_command(server_group)
    await bot.add_cog(Utilities(bot))


