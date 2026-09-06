import os
import io
import csv
import re
import datetime
from typing import Optional, List

import discord
from discord import app_commands
from discord.ext import commands

from core.config import ORGANIZATION_NAME, BRAND_COLOR
from core.state import (
    current_guild_id, with_guild_context,
    is_authorized_to_configure, is_staff
)
from core.database import (
    load_banned_players, get_banned_player, is_game_id_banned,
    add_banned_player, remove_banned_player, log_bot_activity
)
from core.emojis import EMOJIS


ban_group = app_commands.Group(name="ban", description="Manage tournament player bans and game ID restrictions")


def extract_game_ids(raw_text: str) -> List[str]:
    """Extract and deduplicate game IDs from raw text, comma/space/newline separated."""
    tokens = re.split(r'[\r\n,;\t ]+', raw_text)
    cleaned = []
    seen = set()
    for t in tokens:
        item = t.strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            cleaned.append(item)
    return cleaned


@ban_group.command(name="check", description="Check if one or more Game IDs are banned (paste text or upload txt/csv)")
@app_commands.describe(
    game_ids="Paste Game IDs separated by commas, spaces, or newlines",
    file="Upload a .txt or .csv file containing Game IDs"
)
@with_guild_context
async def ban_check(
    interaction: discord.Interaction,
    game_ids: Optional[str] = None,
    file: Optional[discord.Attachment] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not game_ids and not file:
        await interaction.response.send_message(
            "⚠️ Please provide Game IDs either by typing them in `game_ids` or uploading a `.txt` / `.csv` file.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=False)

    all_ids_to_check = []

    if game_ids:
        all_ids_to_check.extend(extract_game_ids(game_ids))

    if file:
        try:
            content_bytes = await file.read()
            text_content = content_bytes.decode('utf-8', errors='ignore')
            
            # If CSV, check for headers or parse column 0
            if file.filename.lower().endswith('.csv'):
                reader = csv.reader(io.StringIO(text_content))
                for row in reader:
                    if not row:
                        continue
                    # First column or check if header
                    val = row[0].strip()
                    if val.lower() in ('game_id', 'game id', 'gameid', 'id', 'player id'):
                        continue
                    if val:
                        all_ids_to_check.append(val)
            else:
                all_ids_to_check.extend(extract_game_ids(text_content))
        except Exception as file_err:
            await interaction.followup.send(f"❌ Failed to read attached file: {file_err}", ephemeral=True)
            return

    # Deduplicate while preserving order
    seen = set()
    unique_ids = []
    for gid in all_ids_to_check:
        gid_clean = str(gid).strip()
        if gid_clean and gid_clean.lower() not in seen:
            seen.add(gid_clean.lower())
            unique_ids.append(gid_clean)

    if not unique_ids:
        await interaction.followup.send("⚠️ No valid Game IDs could be extracted from your input.", ephemeral=True)
        return

    # Check against database
    banned_found = []
    clean_ids = []

    for gid in unique_ids:
        ban_rec = get_banned_player(gid)
        if ban_rec:
            banned_found.append((gid, ban_rec))
        else:
            clean_ids.append(gid)

    caution_emoji = EMOJIS.get('caution', '⚠️')
    verified_emoji = EMOJIS.get('verified', '✅')
    wrong_emoji = EMOJIS.get('wrong', '❌')

    if banned_found:
        embed = discord.Embed(
            title=f"{caution_emoji} Ban Check Results: Banned Players Found!",
            description=f"Checked **{len(unique_ids)}** Game ID(s). Found **{len(banned_found)}** banned player(s).",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )

        banned_lines = []
        for gid, rec in banned_found[:20]:
            reason = rec.get('reason') or "Tournament Ban"
            d_user = f"<@{rec.get('discord_user_id')}>" if rec.get('discord_user_id') else rec.get('discord_username') or "*No Discord linked*"
            banned_lines.append(f"• `{gid}` — {d_user} | Reason: *{reason}*")

        if len(banned_found) > 20:
            banned_lines.append(f"*... and {len(banned_found) - 20} more banned player(s)*")

        embed.add_field(name=f"{wrong_emoji} Banned IDs ({len(banned_found)})", value="\n".join(banned_lines), inline=False)

        if clean_ids:
            clean_sample = ", ".join(f"`{cid}`" for cid in clean_ids[:15])
            if len(clean_ids) > 15:
                clean_sample += f" *(+{len(clean_ids) - 15} more)*"
            embed.add_field(name=f"{verified_emoji} Clean IDs ({len(clean_ids)})", value=clean_sample, inline=False)

        embed.set_footer(text=f"{ORGANIZATION_NAME} • Ban Registry")
        await interaction.followup.send(embed=embed, ephemeral=False)
    else:
        embed = discord.Embed(
            title=f"{verified_emoji} Ban Check Passed: All Clean!",
            description=f"Checked **{len(unique_ids)}** Game ID(s). **None** of them are on the banned list.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        sample = ", ".join(f"`{cid}`" for cid in unique_ids[:20])
        if len(unique_ids) > 20:
            sample += f" *(+{len(unique_ids) - 20} more)*"
        embed.add_field(name="Checked Game IDs", value=sample, inline=False)
        embed.set_footer(text=f"{ORGANIZATION_NAME} • Ban Registry")
        await interaction.followup.send(embed=embed, ephemeral=False)


@ban_group.command(name="player", description="Add a player to the tournament ban list (Organizer/Admin only)")
@app_commands.describe(
    game_id="Game ID of the player to ban",
    user="Optional: Discord member/user to link with the ban",
    reason="Reason for the ban (e.g. Cheating, Toxic Behavior, Multi-accounting)"
)
@with_guild_context
async def ban_player(
    interaction: discord.Interaction,
    game_id: str,
    user: Optional[discord.User] = None,
    reason: Optional[str] = "Tournament Ban"
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to manage player bans.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    gid_clean = game_id.strip()
    existing = get_banned_player(gid_clean)
    if existing:
        await interaction.followup.send(
            f"⚠️ Game ID `{gid_clean}` is **already banned**! Reason: *{existing.get('reason', 'Tournament Ban')}*.",
            ephemeral=False
        )
        return

    record = await add_banned_player(
        game_id=gid_clean,
        discord_user_id=user.id if user else None,
        discord_username=str(user) if user else None,
        reason=reason,
        banned_by=interaction.user.id,
        guild_id=interaction.guild.id
    )

    embed = discord.Embed(
        title="🚫 Player Banned from Tournaments",
        description=f"Player with Game ID `{gid_clean}` has been banned.",
        color=discord.Color.red(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🎮 Game ID", value=f"`{gid_clean}`", inline=True)
    embed.add_field(name="👤 Discord User", value=user.mention if user else "*Not linked*", inline=True)
    embed.add_field(name="⚖️ Reason", value=reason or "Tournament Ban", inline=False)
    embed.add_field(name="👑 Banned By", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Ban Registry")
    await interaction.followup.send(embed=embed, ephemeral=False)

    # Audit Log
    try:
        log_embed = discord.Embed(
            title="🚫 Player Banned",
            description=(
                f"**Game ID:** `{gid_clean}`\n"
                f"**Discord User:** {user.mention if user else 'N/A'} (`{user.id if user else 'N/A'}`)\n"
                f"**Reason:** {reason}\n"
                f"**Action By:** {interaction.user.mention}"
            ),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception:
        pass


@ban_group.command(name="revoke", description="Revoke / unban a player by Game ID or Discord user (Organizer/Admin only)")
@app_commands.describe(
    game_id="Game ID to unban",
    user="Discord user to unban"
)
@with_guild_context
async def ban_revoke(
    interaction: discord.Interaction,
    game_id: Optional[str] = None,
    user: Optional[discord.User] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ You do not have permission to revoke player bans.", ephemeral=True)
        return

    if not game_id and not user:
        await interaction.response.send_message("⚠️ Please provide either a `game_id` or `user` to revoke the ban.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    removed = await remove_banned_player(
        game_id=game_id.strip() if game_id else None,
        discord_user_id=user.id if user else None
    )

    if not removed:
        target_label = f"Game ID `{game_id}`" if game_id else f"User {user.mention}"
        await interaction.followup.send(f"⚠️ No active ban record found for {target_label}.", ephemeral=False)
        return

    embed = discord.Embed(
        title="✅ Player Ban Revoked",
        description=f"Ban record for Game ID `{removed.get('game_id', 'Unknown')}` has been removed.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🎮 Game ID", value=f"`{removed.get('game_id', 'N/A')}`", inline=True)
    if removed.get('discord_user_id'):
        embed.add_field(name="👤 Discord User", value=f"<@{removed['discord_user_id']}>", inline=True)
    embed.add_field(name="👑 Revoked By", value=interaction.user.mention, inline=True)
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Ban Registry")
    await interaction.followup.send(embed=embed, ephemeral=False)

    # Audit Log
    try:
        user_mention_str = f"<@{removed['discord_user_id']}>" if removed.get('discord_user_id') else 'N/A'
        log_embed = discord.Embed(
            title="✅ Ban Revoked",
            description=(
                f"**Game ID:** `{removed.get('game_id')}`\n"
                f"**Discord User:** {user_mention_str}\n"
                f"**Revoked By:** {interaction.user.mention}"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"{ORGANIZATION_NAME} • Audit Log")
        await log_bot_activity(interaction.guild, log_embed)
    except Exception:
        pass


@ban_group.command(name="list", description="Download the full list of banned players as CSV (Organizers only)")
@with_guild_context
async def ban_list(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
        await interaction.response.send_message("❌ Only Organizers and Staff can download the ban list.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    bans = load_banned_players()
    if not bans:
        await interaction.followup.send("ℹ️ The ban registry is currently empty. No players are banned.", ephemeral=True)
        return

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Game_ID", "Discord_User_ID", "Discord_Username", "Reason", "Banned_At", "Banned_By"])

    for _, rec in bans.items():
        writer.writerow([
            rec.get('game_id', ''),
            rec.get('discord_user_id', ''),
            rec.get('discord_username', ''),
            rec.get('reason', ''),
            rec.get('banned_at', ''),
            rec.get('banned_by', '')
        ])

    csv_bytes = output.getvalue().encode('utf-8')
    file = discord.File(io.BytesIO(csv_bytes), filename=f"banned_players_{interaction.guild.id}.csv")

    embed = discord.Embed(
        title="📥 Ban List Export",
        description=f"Exported **{len(bans)}** banned player record(s) to CSV.",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Confidential Ban List")
    await interaction.followup.send(embed=embed, file=file, ephemeral=True)


@ban_group.command(name="import", description="Bulk import Game IDs into ban registry from CSV or TXT file (Organizers only)")
@app_commands.describe(
    file="Upload a .txt or .csv file containing Game IDs (e.g. exported from Excel)",
    default_reason="Default reason to assign to imported bans"
)
@with_guild_context
async def ban_import(
    interaction: discord.Interaction,
    file: discord.Attachment,
    default_reason: Optional[str] = "Tournament Ban"
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return

    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ Only Head Organizers or Administrators can bulk import bans.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=False)

    try:
        content_bytes = await file.read()
        text_content = content_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to read file: {e}", ephemeral=True)
        return

    ids_to_import = []
    if file.filename.lower().endswith('.csv'):
        reader = csv.reader(io.StringIO(text_content))
        for row in reader:
            if not row:
                continue
            val = row[0].strip()
            if val.lower() in ('game_id', 'game id', 'gameid', 'id', 'player id'):
                continue
            if val:
                ids_to_import.append(val)
    else:
        ids_to_import = extract_game_ids(text_content)

    # Deduplicate
    seen = set()
    unique_ids = []
    for gid in ids_to_import:
        c = gid.strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            unique_ids.append(c)

    if not unique_ids:
        await interaction.followup.send("⚠️ No Game IDs found in the uploaded file.", ephemeral=True)
        return

    added_count = 0
    already_banned = 0

    for gid in unique_ids:
        if is_game_id_banned(gid):
            already_banned += 1
        else:
            await add_banned_player(
                game_id=gid,
                reason=default_reason or "Tournament Ban",
                banned_by=interaction.user.id,
                guild_id=interaction.guild.id
            )
            added_count += 1

    embed = discord.Embed(
        title="📥 Bulk Ban Import Complete",
        description=(
            f"Successfully processed **{len(unique_ids)}** Game ID(s) from `{file.filename}`.\n\n"
            f"• **Newly Banned:** `{added_count}`\n"
            f"• **Already on Ban List:** `{already_banned}`"
        ),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"{ORGANIZATION_NAME} • Ban Registry")
    await interaction.followup.send(embed=embed, ephemeral=False)


class Bans(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot


async def setup(bot: commands.Bot):
    bot.tree.add_command(ban_group)
    await bot.add_cog(Bans(bot))
