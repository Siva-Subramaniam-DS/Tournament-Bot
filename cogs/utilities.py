import os
import json
import random
import asyncio
import datetime
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands

from core.config import BASE_DIR, BRAND_COLOR, ORGANIZATION_NAME
from core.state import (
    current_guild_id, with_guild_context, get_user_permission_level,
    get_org_name
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
    del recurring_embeds_store[guild_key]
    save_recurring_embeds(recurring_embeds_store)
    reply = discord.Embed(
        title=f"🗑️ Recurring Embed Deleted — `{embed_id_clean}`",
        description="Removed and will no longer auto-post.",
        color=discord.Color.red(), timestamp=discord.utils.utcnow()
    )
    reply.set_footer(text=f"Deleted by {interaction.user.display_name}")
    await interaction.response.send_message(embed=reply, ephemeral=False)


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
    await bot.add_cog(Utilities(bot))

