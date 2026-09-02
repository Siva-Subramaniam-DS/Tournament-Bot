import os
import io
import re
import csv
import json
import asyncio
from typing import Optional, List, Union

import discord
from discord import app_commands
from discord.ext import commands
import requests

from core.config import (
    BASE_DIR, BRAND_COLOR, BOT_OWNER_ID, ORGANIZATION_NAME,
    DEFAULT_CHANNEL_IDS, DEFAULT_ROLE_IDS
)
from core.state import (
    current_guild_id, with_guild_context, is_authorized_to_configure,
    is_staff, has_organizer_permission, GUILD_CONFIG_CACHE,
    get_default_config, PLAYER_INFO_LINK, PLAYER_INFO_FORMAT,
    CHANNEL_IDS, get_org_name
)
from core.database import (
    supabase_client, get_guild_config, save_guild_config,
    get_active_tournament_config, fetch_discord_channel_safe,
    log_bot_activity
)

# ===========================================================================================
# SHEET COLUMN HELPERS
# ===========================================================================================

_1V1_FIELDS = [
    "Player Discord ID",
    "Player Game Name",
    "Player Game ID",
    "Player Title"
]

_TEAM_PLAYER_FIELDS_TEMPLATE = [
    "Player {n} Discord ID",
    "Player {n} Game Name",
    "Player {n} Game ID",
    "Player {n} Title"
]

def get_ordinals(n: int) -> list:
    if 11 <= (n % 100) <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    num_str = f"{n}{suffix}"
    words = {
        1: ["first", "1st"],
        2: ["second", "2nd"],
        3: ["third", "3rd"],
        4: ["fourth", "4th"],
        5: ["fifth", "5th"],
        6: ["sixth", "6th"],
        7: ["seventh", "7th"],
        8: ["eighth", "8th"],
        9: ["ninth", "9th"],
        10: ["tenth", "10th"]
    }
    result = [num_str, f"{n}"]
    if n in words:
        result.extend(words[n])
    return list(dict.fromkeys(result))

def get_player_aliases(n: int, attr_type: str) -> list:
    ordinals = get_ordinals(n)
    prefixes = []
    for ord_val in ordinals:
        prefixes.extend([
            f"{ord_val} player",
            f"{ord_val}player",
            f"player {ord_val}",
            f"player{ord_val}",
            f"p{ord_val}",
            f"p {ord_val}"
        ])
    prefixes = list(dict.fromkeys(prefixes))
    
    if attr_type == "Discord ID":
        suffixes = [
            "discord developers i'd", "discord developers id", "discord developer id",
            "developer id", "discord id", "discord", "discord tag", "discord username",
            "discord user name", "username", "user name"
        ]
    elif attr_type == "Game Name":
        suffixes = [
            "in game name", "in-game name", "ign", "game name", "name",
            "in-game name (for example", "ign (for example"
        ]
    elif attr_type == "Game ID":
        suffixes = [
            "game i'd", "game id", "in game id", "in-game id", "uid", "id",
            "riot id", "in-game id (for example", "uid (for example"
        ]
    elif attr_type == "Title":
        suffixes = ["in game title", "in-game title", "title", "rank", "role"]
    else:
        suffixes = []
        
    aliases = []
    for p in prefixes:
        for s in suffixes:
            aliases.append(f"{p} {s}")
            aliases.append(f"{p}{s}")
            
    if attr_type == "Discord ID":
        aliases.extend([f"player{n} discord developer id", f"player {n} discord developer id", f"player {n} developer id", f"player{n} developer id", f"p{n} discord developer id", f"p{n} developer id", f"player{n} discord id", f"player {n} discord", f"player {n} id", f"player{n} id", f"p{n} discord id", f"p{n} discord", f"player {n}"])
    elif attr_type == "Game Name":
        aliases.extend([f"player{n} in-game name", f"player {n} in-game name", f"p{n} in-game name", f"player{n} game name", f"player {n} ign", f"player {n} name", f"player{n} ign", f"p{n} game name", f"p{n} ign", f"p{n} name"])
    elif attr_type == "Game ID":
        aliases.extend([f"player{n} in-game id", f"player {n} in-game id", f"p{n} in-game id", f"player{n} game id", f"player {n} game id", f"player {n} uid", f"player{n} uid", f"p{n} game id", f"p{n} uid"])
    elif attr_type == "Title":
        aliases.extend([f"player{n} in-game title", f"player {n} in-game title", f"p{n} in-game title", f"player{n} title", f"player {n} rank", f"player{n} rank", f"p{n} title", f"p{n} rank"])
        
    return list(dict.fromkeys(aliases))

def _col_index(header: list, name: str) -> int:
    if not name:
        return -1
    name_clean = " ".join(name.lower().split())
    for i, h in enumerate(header):
        h_clean = " ".join(h.lower().split())
        if h_clean == name_clean:
            return i
    for i, h in enumerate(header):
        h_clean = " ".join(h.lower().split())
        if name_clean in h_clean:
            return i
    name_nospace = "".join(name_clean.split())
    for i, h in enumerate(header):
        h_nospace = "".join(h.lower().split())
        if name_nospace in h_nospace:
            return i
    return -1


def extract_player_fields(header: list, row: list, is_captain: bool = False, player_num: int = None, guild: discord.Guild = None) -> dict:
    if is_captain:
        tag_aliases = [
            "captain discord tag", "captain discord username", "captain tag", "captain username",
            "captain discord user name", "discord tag", "discord username", "tag", "username", "discord handle"
        ]
        id_aliases = [
            "captain discord developers i'd", "captain discord developers id", "captain discord developer id",
            "captain developer id", "discord developer id", "developer id", "captain discord id",
            "captain discord", "captain id", "discord id", "captain", "captain's discord", "id"
        ]
        name_aliases = [
            "captain in game name", "captain in-game name", "captain ign", "captain game name",
            "captain name", "captain's ign", "captain's name", "in game name", "in-game name",
            "game name", "ign", "in-game name (for example", "in game nickname", "in-game nickname",
            "game nickname", "nickname", "character name", "account name", "player tag", "game tag", "name"
        ]
        game_id_aliases = [
            "captain game i'd", "captain game id", "captain in-game id", "captain in game id",
            "captain uid", "captain's game id", "game i'd", "game id", "in-game id", "in game id",
            "uid", "riot id", "id"
        ]
        title_aliases = [
            "captain title", "captain in-game title", "captain in game title", "captain rank",
            "captain's title", "title", "in-game title", "in game title", "rank", "role"
        ]
    elif player_num is not None and player_num > 1:
        n = player_num
        tag_aliases = [
            f"player {n} discord tag", f"player{n} discord tag", f"player {n} discord username",
            f"player{n} discord username", f"player {n} tag", f"p{n} tag", f"p{n} discord tag",
            f"player {n} username", f"p{n} username", f"player {n} discord user name"
        ]
        id_aliases = get_player_aliases(n, "Discord ID")
        name_aliases = get_player_aliases(n, "Game Name")
        game_id_aliases = get_player_aliases(n, "Game ID")
        title_aliases = get_player_aliases(n, "Title")
    else:
        tag_aliases = [
            "player discord tag", "player discord username", "player tag", "player username",
            "player discord user name", "discord tag", "discord username", "tag", "username", "discord handle"
        ]
        id_aliases = [
            "player discord developers i'd", "player discord developers id", "player discord developer id",
            "discord developer id", "developer id", "player discord id", "discord id", "player discord",
            "discord tag", "discord name", "discord", "discord developers i'd", "discord developers id",
            "discord developer id", "player discord username", "discord username", "id"
        ]
        name_aliases = [
            "player in game name", "player in-game name", "in game name", "in-game name",
            "game name", "player name", "ign", "player ign", "in-game name (for example",
            "in game nickname", "in-game nickname", "game nickname", "nickname", "character name",
            "account name", "player tag", "game tag", "name"
        ]
        game_id_aliases = [
            "player game i'd", "player game id", "game i'd", "game id", "player game id",
            "player id", "uid", "riot id", "player in-game id", "in-game id (for example",
            "in-game id", "in game id", "id"
        ]
        title_aliases = [
            "player title", "title", "rank", "role", "player in-game title", "in-game title", "in game title"
        ]

    sl_aliases = ["sl", "sl.", "sl no", "s.no", "sno", "serial", "sr no", "sr. no", "sr.no", "#", "no"]
    group_aliases = ["group choice", "group", "group preference", "bracket", "grp choice", "grp"]

    def _find_val(aliases_list):
        for alias in aliases_list:
            col = _col_index(header, alias)
            if col != -1 and col < len(row):
                v = row[col].strip()
                if v:
                    return v
        return ""

    raw_id = _find_val(id_aliases)
    raw_name = _find_val(name_aliases)
    raw_game_id = _find_val(game_id_aliases)
    raw_title = _find_val(title_aliases)
    raw_tag = _find_val(tag_aliases)
    raw_sl = _find_val(sl_aliases)
    raw_group = _find_val(group_aliases)

    from core.database import extract_discord_id_from_text

    clean_id = ""
    member = None
    if raw_id:
        found_uid = extract_discord_id_from_text(raw_id)
        if found_uid:
            clean_id = str(found_uid)
            if guild:
                member = guild.get_member(found_uid)
        else:
            clean_id = raw_id

    # If member not yet found by ID, search guild members by tag or name
    if guild and not member:
        tag_to_check = (raw_tag or raw_id or "").strip()
        if tag_to_check.startswith('@'):
            tag_to_check = tag_to_check[1:].strip()
        if '#' in tag_to_check:
            tag_to_check = tag_to_check.split('#')[0].strip()
        if tag_to_check:
            tag_lower = tag_to_check.lower()
            for m in guild.members:
                if (m.name.lower() == tag_lower or 
                    (m.global_name and m.global_name.lower() == tag_lower) or 
                    m.display_name.lower() == tag_lower):
                    member = m
                    clean_id = str(m.id)
                    break

    if not raw_tag and member:
        raw_tag = member.name

    return {
        "sl": raw_sl or "None",
        "discord_tag": raw_tag or "None",
        "discord_id": clean_id or raw_id or "None",
        "game_name": raw_name or "None",
        "game_id": raw_game_id or "None",
        "title": raw_title or "None",
        "group_choice": raw_group or "None",
        "member": member,
        "raw_id": raw_id
    }

def format_player_block_quote(section_header: str, data: dict, emoji: str = "💂", is_captain: bool = True) -> list:
    lines = [f"{emoji} **{section_header}**"]
    
    # SL Number
    sl_val = data.get('sl')
    if sl_val and sl_val != "None":
        lines.append(f"> **SL.:** `{sl_val}`")

    # Discord Username
    d_tag = data.get('discord_tag')
    if d_tag and d_tag != "None":
        lines.append(f"> **Discord Username:** `{d_tag}`")
    elif data.get('member'):
        lines.append(f"> **Discord Username:** `{data['member'].name}`")

    # Discord ID
    d_id = data.get('discord_id')
    if d_id and d_id != "None":
        lines.append(f"> **Discord ID:** `{d_id}`")

    # Verification
    member = data.get('member')
    role_label = "Captain" if is_captain else "Player"
    if member:
        lines.append(f"> **Verification ({role_label}):** 🟢 In server")
    elif d_id and d_id != "None" and d_id.isdigit():
        lines.append(f"> **Verification ({role_label}):** 🔴 Not in server")
    else:
        lines.append(f"> **Verification ({role_label}):** ⚪ Pending")

    # Game Name
    g_name = data.get('game_name')
    if g_name and g_name != "None":
        lines.append(f"> **Game Name:** `{g_name}`")

    # Game ID
    g_id = data.get('game_id')
    if g_id and g_id != "None":
        lines.append(f"> **Game ID:** `{g_id}`")

    # Title
    title_val = data.get('title')
    if title_val and title_val != "None":
        lines.append(f"> **Title:** `{title_val}`")

    # Group Choice
    grp_val = data.get('group_choice')
    if grp_val and grp_val != "None":
        lines.append(f"> **Group Choice:** `{grp_val}`")

    return lines


async def sync_player_info_to_channel(guild: discord.Guild, sheet_link: str, format_str: str, channel: discord.TextChannel):
    sheet_match = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_link)
    if not sheet_match:
        return False, "Invalid Google Sheet link."
    
    sheet_id = sheet_match.group(1)
    gid_match = re.search(r'[#&?]gid=([0-9]+)', sheet_link)
    gid = gid_match.group(1) if gid_match else None
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid:
        url += f"&gid={gid}"
    
    try:
        try:
            await channel.purge(limit=100)
        except Exception as purge_err:
            print(f"Failed to purge participant channel: {purge_err}")

        resp = await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        rows = list(csv.reader(io.StringIO(resp.text)))
        
        if not rows:
            return False, "Google Sheet is empty."
            
        header = rows[0]
        is_1v1 = (format_str == "1 vs 1")
        
        team_size = 5
        if not is_1v1:
            try:
                match = re.search(r'\d+', format_str)
                team_size = int(match.group()) if match else 5
            except:
                pass

        org_name = get_org_name(guild.id) if guild else "Fanplay APAC"
        t_cfg = get_active_tournament_config(guild.id) if guild else None
        tourney_title = (t_cfg.get('name') if t_cfg else None) or "Tournament"

        posted_count = 0
        for idx, row in enumerate(rows[1:], start=1):
            if not row or all(not cell.strip() for cell in row):
                continue

            # Seed extraction
            seed_val = ""
            col_seed = _col_index(header, "Seed")
            if col_seed == -1:
                for alias in ["seed", "seed number", "seed #", "seeding", "team seed"]:
                    col_seed = _col_index(header, alias)
                    if col_seed != -1: break
            if col_seed != -1 and col_seed < len(row):
                seed_val = row[col_seed].strip()

            if is_1v1:
                p_data = extract_player_fields(header, row, is_captain=False, guild=guild)
                if p_data.get('sl') == "None":
                    p_data['sl'] = str(idx)

                member = p_data['member']
                if not member and p_data['discord_id'] != "None" and p_data['discord_id'].isdigit():
                    try:
                        member = await guild.fetch_member(int(p_data['discord_id']))
                        p_data['member'] = member
                        if p_data['discord_tag'] == "None" and member:
                            p_data['discord_tag'] = member.name
                    except:
                        pass

                title_name = p_data['game_name'] if p_data['game_name'] != 'None' else (p_data['discord_tag'] if p_data['discord_tag'] != 'None' else "Player Information")

                desc_lines = []
                if member:
                    desc_lines.append(f"💂 {member.mention}\n")
                elif p_data.get('discord_id') and p_data['discord_id'] != 'None' and p_data['discord_id'].isdigit():
                    desc_lines.append(f"💂 <@{p_data['discord_id']}>\n")
                elif p_data.get('discord_tag') and p_data['discord_tag'] != 'None':
                    desc_lines.append(f"💂 **@{p_data['discord_tag']}**\n")

                desc_lines.extend(format_player_block_quote("Captain details" if is_1v1 else "Player details", p_data, emoji="💂", is_captain=True))

                embed = discord.Embed(
                    title=f"🏆 {title_name}",
                    description="\n".join(desc_lines),
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                if member and hasattr(member, 'display_avatar'):
                    embed.set_thumbnail(url=member.display_avatar.url)
                elif member and member.avatar:
                    embed.set_thumbnail(url=member.avatar.url)
                elif guild and guild.icon:
                    embed.set_thumbnail(url=guild.icon.url)

                footer_parts = [org_name, tourney_title]
                if seed_val:
                    footer_parts.append(f"Seed #{seed_val}")
                embed.set_footer(text=" • ".join(footer_parts))
                await channel.send(embed=embed)

            else:
                tn_val = ""
                tn_col = _col_index(header, "Team Name")
                if tn_col == -1:
                    for alias in ["teamname", "team", "clan name", "clan"]:
                        tn_col = _col_index(header, alias)
                        if tn_col != -1:
                            break
                if tn_col != -1 and tn_col < len(row):
                    tn_val = row[tn_col].strip()

                cap_data = extract_player_fields(header, row, is_captain=True, guild=guild)
                if cap_data.get('sl') == "None":
                    cap_data['sl'] = str(idx)

                member = cap_data['member']
                if not member and cap_data['discord_id'] != "None" and cap_data['discord_id'].isdigit():
                    try:
                        member = await guild.fetch_member(int(cap_data['discord_id']))
                        cap_data['member'] = member
                        if cap_data['discord_tag'] == "None" and member:
                            cap_data['discord_tag'] = member.name
                    except:
                        pass

                team_title = tn_val or (cap_data['game_name'] if cap_data['game_name'] != 'None' else "Team Information")

                desc_lines = []
                if member:
                    desc_lines.append(f"💂 {member.mention}\n")
                elif cap_data.get('discord_id') and cap_data['discord_id'] != 'None' and cap_data['discord_id'].isdigit():
                    desc_lines.append(f"💂 <@{cap_data['discord_id']}>\n")
                elif cap_data.get('discord_tag') and cap_data['discord_tag'] != 'None':
                    desc_lines.append(f"💂 **@{cap_data['discord_tag']}**\n")

                desc_lines.extend(format_player_block_quote("Captain details", cap_data, emoji="💂", is_captain=True))

                for n in range(2, team_size + 1):
                    pn_data = extract_player_fields(header, row, is_captain=False, player_num=n, guild=guild)
                    if any(pn_data[k] != "None" for k in ["discord_tag", "discord_id", "game_name", "game_id", "title"]):
                        desc_lines.append("")
                        desc_lines.extend(format_player_block_quote(f"Player {n} details", pn_data, emoji="👥", is_captain=False))

                embed = discord.Embed(
                    title=f"🏆 {team_title}",
                    description="\n".join(desc_lines),
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                if member and hasattr(member, 'display_avatar'):
                    embed.set_thumbnail(url=member.display_avatar.url)
                elif member and member.avatar:
                    embed.set_thumbnail(url=member.avatar.url)
                elif guild and guild.icon:
                    embed.set_thumbnail(url=guild.icon.url)

                footer_parts = [org_name, tourney_title]
                if seed_val:
                    footer_parts.append(f"Seed #{seed_val}")
                embed.set_footer(text=" • ".join(footer_parts))
                await channel.send(embed=embed)

            posted_count += 1
            await asyncio.sleep(0.5)
            
        return True, f"Successfully parsed Google Sheet and posted **{posted_count}** player/team details to {channel.mention}."
    except Exception as e:
        print(f"Error syncing player information sheet: {e}")
        return False, f"Failed to sync sheet: {str(e)}"



# ===========================================================================================
# OWNER CONFIRMATION VIEW
# ===========================================================================================

class OwnerConfirmationView(discord.ui.View):
    def __init__(self, callback_coro, action_description: str, requester: discord.Member):
        super().__init__(timeout=120)
        self.callback_coro = callback_coro
        self.action_description = action_description
        self.requester = requester

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != BOT_OWNER_ID:
            await interaction.response.send_message("❌ Only the **Bot Owner** can approve this sensitive action.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Deletion", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            await self.callback_coro(interaction)
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(content=f"✅ **Action Confirmed**: {self.action_description} (approved by Bot Owner)", view=None)
        except Exception as e:
            print(f"Error executing owner confirmed action: {e}")
            await interaction.followup.send(f"❌ Error executing action: {e}", ephemeral=False)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"❌ **Action Cancelled**: {self.action_description} was cancelled.", view=None)


# ===========================================================================================
# SETTINGS APP COMMAND GROUP
# ===========================================================================================

settings_group = app_commands.Group(name="settings", description="Manage guild settings (Roles, Branding, and Links)")

async def update_settings_logic(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    organizer_role: Optional[discord.Role] = None,
    helper_role: Optional[discord.Role] = None,
    judge_role: Optional[discord.Role] = None,
    recorder_role: Optional[discord.Role] = None,
    staff_role: Optional[discord.Role] = None,
    players_role: Optional[discord.Role] = None,
    server_name: Optional[str] = None,
    tournament_bot_name: Optional[str] = None,
    server_logo: Optional[discord.Attachment] = None
):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=False)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to manage settings. Only the **Bot Owner**, **Administrators**, or members with the **Head Organizer** role can use this.", ephemeral=False)
        return
        
    cfg = get_guild_config(interaction.guild.id)
    updates = []
    
    role_mapping = {
        'head_organizer': admin_role,
        'organizer': organizer_role,
        'helper_team': helper_role,
        'judge': judge_role,
        'recorder': recorder_role,
        'staff': staff_role,
        'players': players_role
    }
    
    for key, role_obj in role_mapping.items():
        if role_obj is not None:
            cfg['role_ids'][key] = role_obj.id
            updates.append(f"• **{key.replace('_', ' ').title()} Role:** {role_obj.mention}")
            
    if server_name is not None:
        cfg['organization_name'] = server_name.strip()
        updates.append(f"• **Server Name:** {server_name.strip()}")
    if tournament_bot_name is not None:
        cfg['tournament_system_name'] = tournament_bot_name.strip()
        updates.append(f"• **Tournament Bot Name:** {tournament_bot_name.strip()}")
        
    if server_logo is not None:
        try:
            if server_logo.content_type and server_logo.content_type.startswith("image/"):
                logo_data = await server_logo.read()
                filename = f"server_logo_{interaction.guild.id}.png"
                with open(filename, "wb") as f:
                    f.write(logo_data)
                cfg['server_logo_path'] = filename
                updates.append("• **Server Logo:** Updated successfully")
            else:
                updates.append("⚠️ **Server Logo:** Uploaded file is not a valid image")
        except Exception as logo_err:
            print(f"Error saving server logo: {logo_err}")
            updates.append(f"❌ **Server Logo:** Failed to save logo: {logo_err}")
        
    if not updates:
        if interaction.response.is_done():
            await interaction.followup.send("⚠️ No parameters were provided. Settings remain unchanged.", ephemeral=False)
        else:
            await interaction.response.send_message("⚠️ No parameters were provided. Settings remain unchanged.", ephemeral=False)
        return
        
    save_guild_config(interaction.guild.id, cfg)
    
    log_embed = discord.Embed(
        title="⚙️ Server Settings Updated",
        description=f"Server settings have been updated:\n\n" + "\n".join(updates),
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )
    log_embed.set_footer(text=f"Updated by {interaction.user.display_name}")
    await log_bot_activity(interaction.guild, log_embed)
    
    embed = discord.Embed(
        title="✅ Settings Updated",
        description=f"Successfully updated settings for **{cfg.get('organization_name', 'Tournament Organizer')}**:\n\n" + "\n".join(updates),
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.set_footer(text=f"Configured by {interaction.user.display_name}")
    
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=False)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=False)


@settings_group.command(name="add", description="Add server-wide settings: configure server roles and branding details")
@app_commands.describe(
    admin_role="Admin / Head Organizer role",
    organizer_role="Organizer role",
    helper_role="Helper Team / Staff role",
    judge_role="Judge role",
    recorder_role="Recorder role",
    staff_role="General staff role (fallback)",
    players_role="Players role",
    server_name="Name of your esports organization/server",
    tournament_bot_name="Branding name for the tournament system",
    server_logo="Upload your server logo image"
)
@with_guild_context
async def settings_add(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    organizer_role: Optional[discord.Role] = None,
    helper_role: Optional[discord.Role] = None,
    judge_role: Optional[discord.Role] = None,
    recorder_role: Optional[discord.Role] = None,
    staff_role: Optional[discord.Role] = None,
    players_role: Optional[discord.Role] = None,
    server_name: Optional[str] = None,
    tournament_bot_name: Optional[str] = None,
    server_logo: Optional[discord.Attachment] = None
):
    await update_settings_logic(
        interaction=interaction,
        admin_role=admin_role,
        organizer_role=organizer_role,
        helper_role=helper_role,
        judge_role=judge_role,
        recorder_role=recorder_role,
        staff_role=staff_role,
        players_role=players_role,
        server_name=server_name,
        tournament_bot_name=tournament_bot_name,
        server_logo=server_logo
    )


@settings_group.command(name="edit", description="Edit server-wide settings: update server roles and branding details")
@app_commands.describe(
    admin_role="Admin / Head Organizer role",
    organizer_role="Organizer role",
    helper_role="Helper Team / Staff role",
    judge_role="Judge role",
    recorder_role="Recorder role",
    staff_role="General staff role (fallback)",
    players_role="Players role",
    server_name="Name of your esports organization/server",
    tournament_bot_name="Branding name for the tournament system",
    server_logo="Upload your server logo image"
)
@with_guild_context
async def settings_edit(
    interaction: discord.Interaction,
    admin_role: Optional[discord.Role] = None,
    organizer_role: Optional[discord.Role] = None,
    helper_role: Optional[discord.Role] = None,
    judge_role: Optional[discord.Role] = None,
    recorder_role: Optional[discord.Role] = None,
    staff_role: Optional[discord.Role] = None,
    players_role: Optional[discord.Role] = None,
    server_name: Optional[str] = None,
    tournament_bot_name: Optional[str] = None,
    server_logo: Optional[discord.Attachment] = None
):
    await update_settings_logic(
        interaction=interaction,
        admin_role=admin_role,
        organizer_role=organizer_role,
        helper_role=helper_role,
        judge_role=judge_role,
        recorder_role=recorder_role,
        staff_role=staff_role,
        players_role=players_role,
        server_name=server_name,
        tournament_bot_name=tournament_bot_name,
        server_logo=server_logo
    )


@settings_group.command(name="show", description="Display the current bot settings for this server")
@with_guild_context
async def settings_show(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=False)
        return

    cfg = get_guild_config(interaction.guild.id)
    role_ids = cfg.get("role_ids", {})
    guild = interaction.guild

    def get_role_str(key):
        rid = role_ids.get(key)
        if not rid:
            return "`Not Set`"
        role = guild.get_role(int(rid))
        return role.mention if role else f"`ID: {rid}`"

    def get_setting_str(key, default="Not Set"):
        val = cfg.get(key)
        if not val:
            return f"`{default}`"
        if key == "player_info_link":
            return f"[Link]({val})" if str(val).startswith("http") else f"`{val}`"
        return f"`{val}`"

    embed = discord.Embed(
        title="⚙️ Current Bot Settings",
        description="Here are the configured roles, branding details, and links for this server.",
        color=discord.Color(BRAND_COLOR),
        timestamp=discord.utils.utcnow()
    )

    roles_value = (
        f"👑 **Admin:** {get_role_str('head_organizer')}\n"
        f"🛡️ **Organizer:** {get_role_str('organizer')}\n"
        f"👥 **Helper:** {get_role_str('helper_team')}\n"
        f"⚖️ **Judge:** {get_role_str('judge')}\n"
        f"🎥 **Recorder:** {get_role_str('recorder')}\n"
        f"📝 **Staff:** {get_role_str('staff')}\n"
        f"🎮 **Players:** {get_role_str('players')}"
    )
    embed.add_field(name="👥 Roles", value=roles_value, inline=False)

    branding_value = (
        f"🏢 **Server Name:** {get_setting_str('organization_name', 'Tournament Server')}\n"
        f"⚙️ **Tournament Bot Name:** {get_setting_str('tournament_system_name', 'Tournament Bot')}"
    )
    embed.add_field(name="🏆 Branding & Links", value=branding_value, inline=False)

    logo_filename = cfg.get('server_logo_path')
    if not logo_filename or not os.path.exists(logo_filename):
        logo_filename = "tournament_bot_logo.png" if os.path.exists("tournament_bot_logo.png") else None

    if logo_filename:
        embed.set_thumbnail(url="attachment://server_logo.png")
    
    embed.set_footer(
        text=f"Requested by {interaction.user.display_name}",
        icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
    )

    file = None
    if logo_filename:
        file = discord.File(logo_filename, filename="server_logo.png")

    if file:
        await interaction.response.send_message(embed=embed, file=file, ephemeral=False)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=False)


@settings_group.command(name="clean", description="Reset all bot configurations and data to defaults for this server")
@with_guild_context
async def settings_clean(interaction: discord.Interaction):
    if not interaction.guild:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=False)
        return
        
    if not is_authorized_to_configure(interaction):
        await interaction.response.send_message("❌ You do not have permission to clean settings. Only the **Bot Owner**, **Administrators**, or members with the **Head Organizer** role can use this.", ephemeral=False)
        return
        
    async def do_clean(confirm_interaction: discord.Interaction):
        guild_id = interaction.guild.id
        guild_id_str = str(guild_id)
        
        GUILD_CONFIG_CACHE[guild_id_str] = get_default_config()
            
        if supabase_client:
            try:
                supabase_client.table("GuildConfig").delete().eq("Guild_ID", guild_id_str).execute()
            except Exception as e:
                print(f"[Supabase] Error resetting GuildConfig table: {e}")
                    
        if os.path.exists('guild_configs.json'):
            try:
                with open('guild_configs.json', 'r', encoding='utf-8') as f:
                    all_configs = json.load(f)
                if guild_id_str in all_configs:
                    del all_configs[guild_id_str]
                    with open('guild_configs.json', 'w', encoding='utf-8') as f:
                        json.dump(all_configs, f, indent=4)
            except Exception as e:
                print(f"Error cleaning guild_configs.json: {e}")

        log_embed = discord.Embed(
            title="🧹 Server Settings Cleaned",
            description="All bot settings and server configurations have been completely reset.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Triggered by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)

        embed = discord.Embed(
            title="🧹 Settings Cleaned",
            description="All bot settings and configurations have been reset to default for this server.",
            color=discord.Color.orange(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text=f"Cleaned by {interaction.user.display_name}")
        await confirm_interaction.followup.send(embed=embed, ephemeral=False)

    if interaction.user.id == BOT_OWNER_ID:
        class SelfConfirmView(discord.ui.View):
            def __init__(self):
                super().__init__(timeout=60)
            @discord.ui.button(label="✅ Yes, Clean Everything", style=discord.ButtonStyle.danger)
            async def confirm(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.defer()
                await do_clean(button_interaction)
                await button_interaction.message.edit(content="✅ Cleaned server settings.", view=None)
            @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, button_interaction: discord.Interaction, button: discord.ui.Button):
                await button_interaction.response.edit_message(content="Cancelled.", view=None)
        await interaction.response.send_message("⚠️ **WARNING**: This will permanently reset all configurations for this server! Are you sure?", view=SelfConfirmView(), ephemeral=False)
    else:
        view = OwnerConfirmationView(do_clean, f"Clean all settings for server **{interaction.guild.name}**", interaction.user)
        await interaction.response.send_message(
            content=f"⚠️ <@{BOT_OWNER_ID}> **Owner Deletion Confirmation Required!**\n"
                    f"{interaction.user.mention} requested to reset/clean bot settings for this server.\n"
                    f"Please confirm or cancel below.",
            view=view
        )


# ===========================================================================================
# SETTINGS COG
# ===========================================================================================

class Settings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="config_player_information", description="Configure player information Google Sheet link, format, and participant channel")
    @app_commands.describe(
        sheet_link="Google Sheet link containing player or team details",
        format="The tournament format (e.g. 1 vs 1, 5 vs 5)",
        participant_channel="The channel where player/team information will be automatically posted and updated"
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(name="1 vs 1", value="1 vs 1"),
            app_commands.Choice(name="2 vs 2", value="2 vs 2"),
            app_commands.Choice(name="3 vs 3", value="3 vs 3"),
            app_commands.Choice(name="4 vs 4", value="4 vs 4"),
            app_commands.Choice(name="5 vs 5", value="5 vs 5")
        ]
    )
    @with_guild_context
    async def config_player_info_command(
        self,
        interaction: discord.Interaction,
        sheet_link: str,
        format: app_commands.Choice[str],
        participant_channel: discord.TextChannel
    ):
        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=False)
            return
            
        if not is_authorized_to_configure(interaction):
            await interaction.response.send_message("❌ You do not have permission to configure player information.", ephemeral=False)
            return
            
        await interaction.response.defer(ephemeral=False)
        
        cfg = get_guild_config(interaction.guild.id)
        cfg['player_info_link'] = sheet_link.strip()
        cfg['player_info_format'] = format.value
        cfg['player_info_participant_channel_id'] = participant_channel.id
        
        save_guild_config(interaction.guild.id, cfg)
        
        log_embed = discord.Embed(
            title="⚙️ Player Info Configured",
            description=(
                f"**Sheet Link:** [Link]({sheet_link.strip()})\n"
                f"**Format:** {format.value}\n"
                f"**Participant Channel:** {participant_channel.mention}"
            ),
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        log_embed.set_footer(text=f"Configured by {interaction.user.display_name}")
        await log_bot_activity(interaction.guild, log_embed)
        
        success, msg = await sync_player_info_to_channel(interaction.guild, sheet_link.strip(), format.value, participant_channel)
        if success:
            await interaction.followup.send(f"✅ Configuration saved!\n{msg}", ephemeral=False)
        else:
            await interaction.followup.send(f"⚠️ Configuration saved, but sync failed: {msg}", ephemeral=False)

    @app_commands.command(name="player_information", description="Look up player or team info from the configured Google Sheet")
    @app_commands.describe(user="The player or team captain to look up")
    @with_guild_context
    async def player_information_command(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer()

        link_str = str(PLAYER_INFO_LINK)
        if not link_str:
            await interaction.followup.send(
                "❌ Player info sheet is not configured yet. Ask an organizer to configure it in `/settings`."
            )
            return

        sheet_match = re.search(r'/d/([a-zA-Z0-9-_]+)', link_str)
        if not sheet_match:
            await interaction.followup.send("❌ Invalid Google Sheet link in config.")
            return

        sheet_id = sheet_match.group(1)
        gid_match = re.search(r'[#&?]gid=([0-9]+)', link_str)
        gid = gid_match.group(1) if gid_match else None
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        if gid:
            url += f"&gid={gid}"

        try:
            resp = await asyncio.to_thread(requests.get, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.raise_for_status()
            resp.encoding = 'utf-8'
            rows = list(csv.reader(io.StringIO(resp.text)))

            if not rows:
                await interaction.followup.send("❌ The player info sheet is empty.")
                return

            header = rows[0]
            user_id_str = str(user.id)
            user_mention = f"<@{user.id}>"

            found_row = None
            for row in rows[1:]:
                for cell in row:
                    cell_clean = cell.strip()
                    if user_id_str in cell_clean or user_mention in cell_clean:
                        found_row = row
                        break
                if found_row:
                    break

            if found_row is None:
                await interaction.followup.send(
                    f"❌ {user.mention} was not found in the player information sheet.\n"
                    f"Make sure their Discord ID is recorded in the sheet."
                )
                return

            info_format = str(PLAYER_INFO_FORMAT)
            is_1v1 = (info_format == "1 vs 1")

            # Seed extraction
            seed_val = ""
            col_seed = _col_index(header, "Seed")
            if col_seed == -1:
                for alias in ["seed", "seed number", "seed #", "seeding", "team seed"]:
                    col_seed = _col_index(header, alias)
                    if col_seed != -1: break
            if col_seed != -1 and col_seed < len(found_row):
                seed_val = found_row[col_seed].strip()

            if is_1v1:
                p_data = extract_player_fields(header, found_row, is_captain=False, guild=interaction.guild)
                if user:
                    p_data['member'] = user
                    if p_data['discord_tag'] == "None":
                        p_data['discord_tag'] = user.name
                    if p_data['discord_id'] == "None":
                        p_data['discord_id'] = str(user.id)

                title_name = p_data['game_name'] if p_data['game_name'] != 'None' else (p_data['discord_tag'] if p_data['discord_tag'] != 'None' else user.display_name)

                desc_lines = []
                desc_lines.append(f"💂 {user.mention}\n")
                desc_lines.extend(format_player_block_quote("Captain details" if is_1v1 else "Player details", p_data, emoji="💂"))

                pi_embed = discord.Embed(
                    title=f"🏆 {title_name}",
                    description="\n".join(desc_lines),
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                if user.display_avatar:
                    pi_embed.set_thumbnail(url=user.display_avatar.url)
                elif user.avatar:
                    pi_embed.set_thumbnail(url=user.avatar.url)
                elif interaction.guild and interaction.guild.icon:
                    pi_embed.set_thumbnail(url=interaction.guild.icon.url)

                footer_parts = [ORGANIZATION_NAME, "Player Info"]
                if seed_val:
                    footer_parts.append(f"Seed #{seed_val}")
                footer_parts.append(f"Requested by {interaction.user.display_name}")
                pi_embed.set_footer(text=" • ".join(footer_parts))
                await interaction.followup.send(embed=pi_embed)

            else:
                try:
                    match = re.search(r'\d+', info_format)
                    team_size = int(match.group()) if match else 5
                except Exception:
                    team_size = 5

                tn_val = ""
                tn_col = _col_index(header, "Team Name")
                if tn_col == -1:
                    for alias in ["teamname", "team", "clan name", "clan"]:
                        tn_col = _col_index(header, alias)
                        if tn_col != -1:
                            break
                if tn_col != -1 and tn_col < len(found_row):
                    tn_val = found_row[tn_col].strip()

                cap_data = extract_player_fields(header, found_row, is_captain=True, guild=interaction.guild)
                if user:
                    cap_data['member'] = user
                    if cap_data['discord_tag'] == "None":
                        cap_data['discord_tag'] = user.name
                    if cap_data['discord_id'] == "None":
                        cap_data['discord_id'] = str(user.id)

                team_title = tn_val or (cap_data['game_name'] if cap_data['game_name'] != 'None' else f"Team {user.display_name}")

                desc_lines = []
                desc_lines.append(f"💂 {user.mention}\n")
                desc_lines.extend(format_player_block_quote("Captain details", cap_data, emoji="💂"))

                for n in range(2, team_size + 1):
                    pn_data = extract_player_fields(header, found_row, is_captain=False, player_num=n, guild=interaction.guild)
                    if any(pn_data[k] != "None" for k in ["discord_tag", "discord_id", "game_name", "game_id", "title"]):
                        desc_lines.append("")
                        desc_lines.extend(format_player_block_quote(f"Player {n} details", pn_data, emoji="👥"))

                ti_embed = discord.Embed(
                    title=f"🏆 {team_title}",
                    description="\n".join(desc_lines),
                    color=discord.Color.gold(),
                    timestamp=discord.utils.utcnow()
                )
                if user.display_avatar:
                    ti_embed.set_thumbnail(url=user.display_avatar.url)
                elif user.avatar:
                    ti_embed.set_thumbnail(url=user.avatar.url)
                elif interaction.guild and interaction.guild.icon:
                    ti_embed.set_thumbnail(url=interaction.guild.icon.url)

                footer_parts = [ORGANIZATION_NAME, "Team Info"]
                if seed_val:
                    footer_parts.append(f"Seed #{seed_val}")
                footer_parts.append(f"Requested by {interaction.user.display_name}")
                ti_embed.set_footer(text=" • ".join(footer_parts))
                await interaction.followup.send(embed=ti_embed)

        except Exception as e:
            print(f"Error fetching player information: {e}")
            await interaction.followup.send("❌ Error fetching player info from the configured Google Sheet.")


    @app_commands.command(name="player_edit", description="Edit a player's or team's name/details in the posted participant list and database")
    @app_commands.describe(
        user="The player or captain whose participant entry to edit",
        field="The field to update",
        new_value="The new corrected value",
        channel="The participant channel where info was posted (optional)"
    )
    @app_commands.choices(
        field=[
            app_commands.Choice(name="🎮 Game Name / IGN", value="game_name"),
            app_commands.Choice(name="🆔 Game ID / UID", value="game_id"),
            app_commands.Choice(name="👑 Team Name", value="team_name"),
            app_commands.Choice(name="🎖️ Title / Rank", value="title"),
            app_commands.Choice(name="👤 Discord Mention / ID", value="discord_id")
        ]
    )
    @with_guild_context
    async def player_edit_command(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        field: app_commands.Choice[str],
        new_value: str,
        channel: Optional[discord.TextChannel] = None
    ):
        if not interaction.guild:
            await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=False)
            return

        if not is_authorized_to_configure(interaction) and not is_staff(interaction.user):
            await interaction.response.send_message("❌ You do not have permission to edit player details.", ephemeral=False)
            return

        await interaction.response.defer(ephemeral=False)

        target_channel = channel
        if not target_channel:
            cfg = get_guild_config(interaction.guild.id)
            p_chan_id = cfg.get('player_info_participant_channel_id')
            if p_chan_id:
                target_channel = await fetch_discord_channel_safe(interaction.guild, p_chan_id, self.bot)
        if not target_channel:
            t_cfg = get_active_tournament_config(interaction.guild.id)
            if t_cfg:
                p_chan_id = t_cfg.get('participant') or t_cfg.get('Participant_Channel_ID')
                if p_chan_id:
                    target_channel = await fetch_discord_channel_safe(interaction.guild, p_chan_id, self.bot)
        if not target_channel:
            target_channel = interaction.channel

        found_msg = None
        target_embed = None
        u_id_str = str(user.id)
        u_name_lower = user.name.lower()
        u_display_lower = user.display_name.lower()

        try:
            if target_channel and hasattr(target_channel, "history"):
                async for msg in target_channel.history(limit=150):
                    if msg.author.id == self.bot.user.id and msg.embeds:
                        for emb in msg.embeds:
                            emb_str = (emb.description or "") + " " + (emb.title or "")
                            for f in emb.fields:
                                emb_str += " " + f.name + " " + f.value
                            if u_id_str in emb_str or f"<@{user.id}>" in emb_str or u_name_lower in emb_str.lower() or u_display_lower in emb_str.lower():
                                found_msg = msg
                                target_embed = emb
                                break
                        if found_msg:
                            break
        except Exception as e:
            print(f"Error searching participant messages: {e}")

        old_val_display = "—"
        updated_embed = False

        if found_msg and target_embed:
            new_embed = target_embed.copy()
            field_type = field.value
            clean_val = new_value.strip()

            if field_type == "team_name":
                # Update title if it has Team name
                if new_embed.title:
                    old_val_display = new_embed.title.replace("🏆", "").strip()
                    new_embed.title = f"🏆 {clean_val}"
                    updated_embed = True
                if new_embed.description and "**Team Name:**" in new_embed.description:
                    old_matches = re.findall(r'\*\*Team Name:\*\*\s*`?([^`\n]+)`?', new_embed.description)
                    if old_matches:
                        old_val_display = old_matches[0]
                    new_embed.description = re.sub(
                        r'(\*\*Team Name:\*\*\s*)`?[^`\n]+`?',
                        f"\\1`{clean_val}`",
                        new_embed.description
                    )
                    updated_embed = True
                for idx, f in enumerate(new_embed.fields):
                    if "team" in f.name.lower() or "team name" in f.value.lower():
                        old_val_display = f.value
                        new_embed.set_field_at(idx, name=f.name, value=re.sub(r'(\*\*Team Name:\*\*\s*)`?[^`\n]+`?', f"\\1`{clean_val}`", f.value), inline=f.inline)
                        updated_embed = True

            elif field_type == "game_name":
                if new_embed.description:
                    old_m = re.findall(r'\*\*Game Name:\*\*\s*`?([^`\n]+)`?', new_embed.description, flags=re.IGNORECASE)
                    if old_m:
                        old_val_display = old_m[0]
                    new_embed.description = re.sub(
                        r'(\*\*Game Name:\*\*\s*)`?[^`\n]+`?',
                        f"\\1`{clean_val}`",
                        new_embed.description,
                        flags=re.IGNORECASE
                    )
                    updated_embed = True
                if new_embed.title and not any(kw in new_embed.title.lower() for kw in ["team", "information"]):
                    new_embed.title = f"🏆 {clean_val}"
                    updated_embed = True
                for idx, f in enumerate(new_embed.fields):
                    if "game name" in f.value.lower() or "ign" in f.value.lower() or "game name" in f.name.lower():
                        old_m = re.findall(r'(\*\*Game Name:\*\*\s*)`?([^`\n]+)`?', f.value, flags=re.IGNORECASE)
                        if old_m:
                            old_val_display = old_m[0][1]
                        new_val_str = re.sub(r'(\*\*Game Name:\*\*\s*)`?[^`\n]+`?', f"\\1`{clean_val}`", f.value, flags=re.IGNORECASE)
                        new_embed.set_field_at(idx, name=f.name, value=new_val_str, inline=f.inline)
                        updated_embed = True
                        break

            elif field_type == "game_id":
                if new_embed.description:
                    old_m = re.findall(r'\*\*Game ID:\*\*\s*`?([^`\n]+)`?', new_embed.description, flags=re.IGNORECASE)
                    if old_m:
                        old_val_display = old_m[0]
                    new_embed.description = re.sub(
                        r'(\*\*Game ID:\*\*\s*)`?[^`\n]+`?',
                        f"\\1`{clean_val}`",
                        new_embed.description,
                        flags=re.IGNORECASE
                    )
                    updated_embed = True
                for idx, f in enumerate(new_embed.fields):
                    if "game id" in f.value.lower() or "uid" in f.value.lower():
                        old_m = re.findall(r'(\*\*Game ID:\*\*\s*)`?([^`\n]+)`?', f.value, flags=re.IGNORECASE)
                        if old_m:
                            old_val_display = old_m[0][1]
                        new_val_str = re.sub(r'(\*\*Game ID:\*\*\s*)`?[^`\n]+`?', f"\\1`{clean_val}`", f.value, flags=re.IGNORECASE)
                        new_embed.set_field_at(idx, name=f.name, value=new_val_str, inline=f.inline)
                        updated_embed = True
                        break

            elif field_type == "title":
                if new_embed.description:
                    old_m = re.findall(r'\*\*Title:\*\*\s*`?([^`\n]+)`?', new_embed.description, flags=re.IGNORECASE)
                    if old_m:
                        old_val_display = old_m[0]
                    new_embed.description = re.sub(
                        r'(\*\*Title:\*\*\s*)`?[^`\n]+`?',
                        f"\\1`{clean_val}`",
                        new_embed.description,
                        flags=re.IGNORECASE
                    )
                    updated_embed = True
                for idx, f in enumerate(new_embed.fields):
                    if "title" in f.value.lower() or "rank" in f.value.lower():
                        old_m = re.findall(r'(\*\*Title:\*\*\s*)`?([^`\n]+)`?', f.value, flags=re.IGNORECASE)
                        if old_m:
                            old_val_display = old_m[0][1]
                        new_val_str = re.sub(r'(\*\*Title:\*\*\s*)`?[^`\n]+`?', f"\\1`{clean_val}`", f.value, flags=re.IGNORECASE)
                        new_embed.set_field_at(idx, name=f.name, value=new_val_str, inline=f.inline)
                        updated_embed = True
                        break

            elif field_type == "discord_id":
                clean_digits = re.sub(r'[^0-9]', '', clean_val)
                mention_clean = f"<@{clean_digits}>" if clean_digits else clean_val
                if new_embed.description:
                    old_m = re.findall(r'\*\*Discord ID:\*\*\s*`?([^`\n]+)`?', new_embed.description, flags=re.IGNORECASE)
                    if old_m:
                        old_val_display = old_m[0]
                    new_embed.description = re.sub(
                        r'(\*\*Discord ID:\*\*\s*)`?[^`\n]+`?',
                        f"\\1`{clean_digits or clean_val}`",
                        new_embed.description,
                        flags=re.IGNORECASE
                    )
                    new_embed.description = re.sub(
                        r'💂\s*<@!?\d+>',
                        f"💂 {mention_clean}",
                        new_embed.description
                    )
                    updated_embed = True
                for idx, f in enumerate(new_embed.fields):
                    if "discord id" in f.value.lower() or "discord id" in f.name.lower():
                        old_val_display = f.value
                        new_val_str = re.sub(r'(\*\*Discord ID:\*\*\s*)[^\n]+', f"\\1{mention_clean}", f.value, flags=re.IGNORECASE)
                        new_embed.set_field_at(idx, name=f.name, value=new_val_str, inline=f.inline)
                        updated_embed = True
                        break

            if updated_embed:
                try:
                    await found_msg.edit(embed=new_embed)
                except Exception as e:
                    print(f"Failed to edit participant message: {e}")

        if supabase_client:
            try:
                if field.value == "game_name":
                    await asyncio.to_thread(
                        lambda: supabase_client.table("Players").update({"IGN": new_value.strip()}).eq("Discord_ID", str(user.id)).execute()
                    )
                elif field.value == "game_id":
                    await asyncio.to_thread(
                        lambda: supabase_client.table("Players").update({"Game_ID": new_value.strip()}).eq("Discord_ID", str(user.id)).execute()
                    )
                elif field.value == "title":
                    await asyncio.to_thread(
                        lambda: supabase_client.table("Players").update({"Title": new_value.strip()}).eq("Discord_ID", str(user.id)).execute()
                    )
                elif field.value == "team_name":
                    await asyncio.to_thread(
                        lambda: supabase_client.table("Teams").update({"Team_Name": new_value.strip()}).eq("Captain_ID", str(user.id)).execute()
                    )
            except Exception as e:
                print(f"[Supabase] Player edit sync note: {e}")

        reply_embed = discord.Embed(
            title="✏️ Player Information Updated",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        reply_embed.add_field(name="👤 Player / Captain", value=user.mention, inline=True)
        reply_embed.add_field(name="📝 Field Changed", value=field.name, inline=True)
        reply_embed.add_field(name="🔄 Value", value=f"`{old_val_display}` ➔ `{new_value.strip()}`", inline=False)
        if found_msg and target_channel:
            reply_embed.add_field(
                name="📍 Participant List",
                value=f"[Jump to Updated Entry in {target_channel.mention}]({found_msg.jump_url})",
                inline=False
            )
        reply_embed.set_footer(text=f"Updated by {interaction.user.display_name}")
        await interaction.followup.send(embed=reply_embed, ephemeral=False)

    @app_commands.command(name="test_channels", description="Test if bot can access configured channels (Organizer only)")
    @with_guild_context
    async def test_channels_command(self, interaction: discord.Interaction):
        if not has_organizer_permission(interaction):
            await interaction.response.send_message(
                "❌ You need to be **Bot Owner** or **Head Organizer** to use this command.",
                ephemeral=False
            )
            return
        
        embed = discord.Embed(
            title="🔍 Channel Access Test",
            description="Testing bot access to configured channels...",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        for channel_name, channel_id in CHANNEL_IDS.items():
            channel = interaction.guild.get_channel(channel_id) if channel_id else None
            
            if channel:
                perms = channel.permissions_for(interaction.guild.me)
                can_send = perms.send_messages
                can_embed = perms.embed_links
                can_attach = perms.attach_files
                can_mention = perms.mention_everyone
                
                status = "✅" if (can_send and can_embed) else "⚠️"
                details = f"Channel: {channel.mention}\n"
                details += f"• Send Messages: {'✅' if can_send else '❌'}\n"
                details += f"• Embed Links: {'✅' if can_embed else '❌'}\n"
                details += f"• Attach Files: {'✅' if can_attach else '❌'}\n"
                details += f"• Mention Everyone: {'✅' if can_mention else '❌'}"
                
                embed.add_field(
                    name=f"{status} {channel_name.replace('_', ' ').title()}",
                    value=details,
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"❌ {channel_name.replace('_', ' ').title()}",
                    value=f"Channel ID `{channel_id}` not found!\nThe channel may have been deleted or the ID is wrong.",
                    inline=False
                )
        
        embed.set_footer(text=f"{ORGANIZATION_NAME}")
        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    bot.tree.add_command(settings_group)
    await bot.add_cog(Settings(bot))

