import io
import re
import html
import base64
import requests
import datetime
from typing import List, Tuple, Dict, Any, Optional

import discord


def escape_html(text: Any) -> str:
    if text is None:
        return ""
    return html.escape(str(text))


def get_image_data_uri(url: str, filename: str) -> str:
    """Download image and convert to Base64 data URI so images never expire in transcripts."""
    if not url:
        return ""
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if resp.status_code == 200 and len(resp.content) <= 8 * 1024 * 1024:
            fn_lower = filename.lower()
            mime = "image/png"
            if fn_lower.endswith(".jpg") or fn_lower.endswith(".jpeg"):
                mime = "image/jpeg"
            elif fn_lower.endswith(".gif"):
                mime = "image/gif"
            elif fn_lower.endswith(".webp"):
                mime = "image/webp"
            b64 = base64.b64encode(resp.content).decode("utf-8")
            return f"data:{mime};base64,{b64}"
    except Exception:
        pass
    return url



def format_discord_markdown(text: str, guild: Optional[discord.Guild] = None) -> str:
    if not text:
        return ""

    # Placeholders for code blocks to prevent markdown parsing inside code
    code_blocks = []
    def save_code_block(match):
        code_blocks.append(match.group(0))
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"

    # Save triple backtick code blocks
    text = re.sub(r'```(?:[a-zA-Z0-9_-]+)?\n?(.*?)```', save_code_block, text, flags=re.DOTALL)
    
    # Save single backtick inline code
    inline_codes = []
    def save_inline_code(match):
        inline_codes.append(match.group(1))
        return f"__INLINE_CODE_{len(inline_codes)-1}__"
    
    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # Escape raw HTML
    text = escape_html(text)

    # Custom Discord Emojis: <a:name:id> or <:name:id>
    def replace_custom_emoji(match):
        animated = match.group(1) == "a"
        name = match.group(2)
        emoji_id = match.group(3)
        ext = "gif" if animated else "png"
        return f'<img class="custom-emoji" src="https://cdn.discordapp.com/emojis/{emoji_id}.{ext}" alt=":{name}:" title=":{name}:">'
    text = re.sub(r'&lt;(a)?:([a-zA-Z0-9_]+):(\d+)&gt;', replace_custom_emoji, text)

    # User mentions <@123456789> or <@!123456789>
    def replace_user_mention(match):
        uid = int(match.group(1))
        name = f"User ({uid})"
        if guild:
            member = guild.get_member(uid)
            if member:
                name = member.display_name
        return f'<span class="mention">@{escape_html(name)}</span>'
    text = re.sub(r'&lt;@!?(\d+)&gt;', replace_user_mention, text)

    # Role mentions <@&123456789>
    def replace_role_mention(match):
        rid = int(match.group(1))
        rname = f"Role ({rid})"
        if guild:
            role = guild.get_role(rid)
            if role:
                rname = role.name
        return f'<span class="mention role-mention">@{escape_html(rname)}</span>'
    text = re.sub(r'&lt;@&amp;(\d+)&gt;', replace_role_mention, text)

    # Channel mentions <#123456789>
    def replace_channel_mention(match):
        cid = int(match.group(1))
        cname = f"channel-{cid}"
        if guild:
            ch = guild.get_channel(cid)
            if ch:
                cname = ch.name
        return f'<span class="mention channel-mention">#{escape_html(cname)}</span>'
    text = re.sub(r'&lt;#(\d+)&gt;', replace_channel_mention, text)

    # Bold: **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Italic: *text* or _text_
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(r'(?<!_)_([^_]+)_(?!_)', r'<em>\1</em>', text)
    # Underline: __text__
    text = re.sub(r'__(.+?)__', r'<u>\1</u>', text)
    # Strikethrough: ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
    # Spoiler: ||text||
    text = re.sub(r'\|\|(.+?)\|\|', r'<span class="spoiler">\1</span>', text)

    # URLs: [label](url) or naked https://...
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', text)
    text = re.sub(r'(?<!href=")(?<!">)(https?://[^\s<]+)', r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', text)

    # Blockquotes: > text or >>> text
    lines = text.split('\n')
    in_quote = False
    new_lines = []
    for line in lines:
        if line.startswith('&gt;&gt;&gt; '):
            new_lines.append(f'<blockquote>{line[14:]}')
            in_quote = True
        elif line.startswith('&gt; '):
            new_lines.append(f'<blockquote>{line[5:]}</blockquote>')
        else:
            if in_quote and not line.strip():
                new_lines.append('</blockquote>')
                in_quote = False
            new_lines.append(line)
    if in_quote:
        new_lines.append('</blockquote>')
    text = '\n'.join(new_lines)

    # Restore inline code
    for i, code in enumerate(inline_codes):
        text = text.replace(f"__INLINE_CODE_{i}__", f'<code>{escape_html(code)}</code>')

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        m = re.match(r'```(?:([a-zA-Z0-9_-]+))?\n?(.*?)```', block, flags=re.DOTALL)
        if m:
            lang = m.group(1) or ""
            code_content = m.group(2)
            lang_attr = f' class="language-{escape_html(lang)}"' if lang else ''
            text = text.replace(f"__CODE_BLOCK_{i}__", f'<pre><code{lang_attr}>{escape_html(code_content)}</code></pre>')

    # Convert newlines to <br> (outside pre tags)
    parts = text.split('<pre>')
    formatted_parts = [parts[0].replace('\n', '<br>')]
    for p in parts[1:]:
        sub = p.split('</pre>')
        if len(sub) == 2:
            formatted_parts.append('<pre>' + sub[0] + '</pre>' + sub[1].replace('\n', '<br>'))
        else:
            formatted_parts.append('<pre>' + p)
    text = ''.join(formatted_parts)

    return text


def build_html_embed(embed: discord.Embed, guild: Optional[discord.Guild] = None) -> str:
    color_hex = f"#{embed.color.value:06x}" if embed.color and embed.color.value else "#202225"
    html_out = [f'<div class="embed-box" style="border-left-color: {color_hex};">']
    html_out.append('<div class="embed-grid">')

    # Author
    if embed.author and embed.author.name:
        html_out.append('<div class="embed-author">')
        if embed.author.icon_url:
            html_out.append(f'<img src="{escape_html(embed.author.icon_url)}" class="embed-author-icon" alt="">')
        if embed.author.url:
            html_out.append(f'<a href="{escape_html(embed.author.url)}" target="_blank" class="embed-author-name">{escape_html(embed.author.name)}</a>')
        else:
            html_out.append(f'<span class="embed-author-name">{escape_html(embed.author.name)}</span>')
        html_out.append('</div>')

    # Title
    if embed.title:
        html_out.append('<div class="embed-title">')
        if embed.url:
            html_out.append(f'<a href="{escape_html(embed.url)}" target="_blank">{escape_html(embed.title)}</a>')
        else:
            html_out.append(escape_html(embed.title))
        html_out.append('</div>')

    # Description
    if embed.description:
        html_out.append(f'<div class="embed-description">{format_discord_markdown(embed.description, guild)}</div>')

    # Fields
    if embed.fields:
        html_out.append('<div class="embed-fields">')
        for f in embed.fields:
            inline_cls = " embed-field-inline" if f.inline else ""
            html_out.append(f'<div class="embed-field{inline_cls}">')
            html_out.append(f'<div class="embed-field-name">{escape_html(f.name)}</div>')
            html_out.append(f'<div class="embed-field-value">{format_discord_markdown(f.value, guild)}</div>')
            html_out.append('</div>')
        html_out.append('</div>')

    # Image
    if embed.image and embed.image.url:
        html_out.append(f'<div class="embed-image"><a href="{escape_html(embed.image.url)}" target="_blank"><img src="{escape_html(embed.image.url)}" alt="Embed Image"></a></div>')

    # Thumbnail
    if embed.thumbnail and embed.thumbnail.url:
        html_out.append(f'<div class="embed-thumbnail"><a href="{escape_html(embed.thumbnail.url)}" target="_blank"><img src="{escape_html(embed.thumbnail.url)}" alt="Thumbnail"></a></div>')

    # Footer
    if embed.footer and embed.footer.text:
        html_out.append('<div class="embed-footer">')
        if embed.footer.icon_url:
            html_out.append(f'<img src="{escape_html(embed.footer.icon_url)}" class="embed-footer-icon" alt="">')
        footer_text = escape_html(embed.footer.text)
        if embed.timestamp:
            ts_str = embed.timestamp.strftime("%Y-%m-%d %H:%M UTC")
            footer_text += f" • {ts_str}"
        html_out.append(f'<span class="embed-footer-text">{footer_text}</span>')
        html_out.append('</div>')

    html_out.append('</div></div>')
    return ''.join(html_out)


def generate_html_transcript(
    channel: discord.TextChannel,
    messages: List[discord.Message],
    guild: discord.Guild,
    closed_by: Optional[discord.Member] = None
) -> str:
    guild_name = guild.name if guild else "Discord Server"
    guild_icon = guild.icon.url if (guild and guild.icon) else "https://cdn.discordapp.com/embed/avatars/0.png"
    channel_name = channel.name if channel else "ticket-channel"
    now_str = datetime.datetime.utcnow().strftime("%B %d, %Y at %H:%M UTC")
    msg_count = len(messages)

    attachment_count = sum(len(m.attachments) for m in messages)
    participants = {}
    for m in messages:
        if m.author.id not in participants:
            participants[m.author.id] = m.author

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transcript #{escape_html(channel_name)} - {escape_html(guild_name)}</title>
    <style>
        :root {{
            --bg-primary: #313338;
            --bg-secondary: #2b2d31;
            --bg-tertiary: #1e1f22;
            --text-normal: #dbdee1;
            --text-muted: #949ba4;
            --text-link: #00a8fc;
            --header-primary: #f2f3f5;
            --brand: #5865f2;
            --font: 'gg sans', 'Whitney', 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }}
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            background-color: var(--bg-primary);
            color: var(--text-normal);
            font-family: var(--font);
            font-size: 15px;
            line-height: 1.375;
            padding: 0;
            margin: 0;
        }}
        .header {{
            background-color: var(--bg-secondary);
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding: 20px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }}
        .header-left {{
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .header-icon {{
            width: 48px;
            height: 48px;
            border-radius: 16px;
            object-fit: cover;
            border: 2px solid rgba(255,255,255,0.1);
        }}
        .header-title {{
            font-size: 20px;
            font-weight: 700;
            color: var(--header-primary);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .header-subtitle {{
            font-size: 13px;
            color: var(--text-muted);
            margin-top: 4px;
        }}
        .header-stats {{
            display: flex;
            gap: 16px;
            font-size: 13px;
            color: var(--text-muted);
        }}
        .stat-badge {{
            background: var(--bg-tertiary);
            padding: 6px 12px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .chat-container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 24px 20px 60px 20px;
        }}
        .message-group {{
            display: flex;
            margin-top: 18px;
            padding: 2px 10px;
            border-radius: 6px;
            transition: background-color 0.1s;
        }}
        .message-group:hover {{
            background-color: rgba(0, 0, 0, 0.08);
        }}
        .avatar-column {{
            width: 48px;
            margin-right: 16px;
            flex-shrink: 0;
        }}
        .avatar {{
            width: 40px;
            height: 40px;
            border-radius: 50%;
            object-fit: cover;
            background-color: var(--bg-tertiary);
            cursor: pointer;
        }}
        .message-content {{
            flex: 1;
            min-width: 0;
        }}
        .message-header {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            margin-bottom: 4px;
        }}
        .author-name {{
            font-size: 15px;
            font-weight: 600;
            color: var(--header-primary);
            cursor: pointer;
        }}
        .bot-badge {{
            background-color: var(--brand);
            color: #ffffff;
            font-size: 10px;
            font-weight: 700;
            padding: 1px 4px;
            border-radius: 3px;
            text-transform: uppercase;
            line-height: 1.2;
        }}
        .timestamp {{
            font-size: 12px;
            color: var(--text-muted);
        }}
        .message-text {{
            word-wrap: break-word;
            color: var(--text-normal);
            font-size: 14.5px;
        }}
        .mention {{
            background-color: rgba(88, 101, 242, 0.3);
            color: #c9cdfb;
            padding: 1px 5px;
            border-radius: 3px;
            font-weight: 500;
        }}
        .custom-emoji {{
            width: 22px;
            height: 22px;
            vertical-align: -5px;
            margin: 0 1px;
        }}
        a {{
            color: var(--text-link);
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        pre {{
            background-color: var(--bg-tertiary);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 4px;
            padding: 10px 12px;
            margin: 6px 0;
            overflow-x: auto;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 13px;
        }}
        code {{
            background-color: var(--bg-tertiary);
            padding: 2px 5px;
            border-radius: 3px;
            font-family: 'Consolas', 'Courier New', monospace;
            font-size: 13px;
        }}
        blockquote {{
            border-left: 4px solid #4e5058;
            padding-left: 12px;
            margin: 4px 0;
            color: var(--text-muted);
        }}
        .spoiler {{
            background-color: #1e1f22;
            color: transparent;
            border-radius: 3px;
            padding: 0 4px;
            cursor: pointer;
            user-select: none;
        }}
        .spoiler:hover {{
            background-color: rgba(255, 255, 255, 0.1);
            color: var(--text-normal);
        }}
        .attachments-container {{
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
        }}
        .attachment-card {{
            border-radius: 8px;
            overflow: hidden;
            background-color: var(--bg-secondary);
            border: 1px solid rgba(255, 255, 255, 0.08);
            max-width: 520px;
        }}
        .attachment-img {{
            max-width: 500px;
            max-height: 380px;
            display: block;
            border-radius: 6px;
            cursor: pointer;
            transition: transform 0.15s ease;
        }}
        .attachment-img:hover {{
            opacity: 0.95;
        }}
        .file-attachment {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 14px;
            background: var(--bg-secondary);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            font-size: 13px;
        }}
        .file-icon {{
            font-size: 20px;
        }}
        .embed-box {{
            background-color: var(--bg-secondary);
            border-left: 4px solid var(--brand);
            border-radius: 4px;
            padding: 12px 16px;
            margin-top: 8px;
            max-width: 600px;
            font-size: 13.5px;
        }}
        .embed-author {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
            font-size: 13px;
            font-weight: 600;
        }}
        .embed-author-icon {{
            width: 22px;
            height: 22px;
            border-radius: 50%;
        }}
        .embed-title {{
            font-size: 15px;
            font-weight: 700;
            color: var(--header-primary);
            margin-bottom: 6px;
        }}
        .embed-description {{
            margin-bottom: 8px;
            color: var(--text-normal);
            line-height: 1.4;
        }}
        .embed-fields {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
            margin-top: 8px;
        }}
        .embed-field-name {{
            font-weight: 700;
            color: var(--header-primary);
            font-size: 12.5px;
            margin-bottom: 2px;
        }}
        .embed-field-value {{
            color: var(--text-normal);
            font-size: 13px;
        }}
        .embed-image img {{
            max-width: 100%;
            border-radius: 4px;
            margin-top: 8px;
        }}
        .embed-thumbnail img {{
            max-width: 80px;
            max-height: 80px;
            border-radius: 4px;
            float: right;
            margin-left: 12px;
        }}
        .embed-footer {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 10px;
            font-size: 11.5px;
            color: var(--text-muted);
        }}
        .embed-footer-icon {{
            width: 18px;
            height: 18px;
            border-radius: 50%;
        }}
        .reply-bar {{
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 4px;
            padding-left: 28px;
            position: relative;
        }}
        .reply-bar::before {{
            content: "";
            position: absolute;
            left: 10px;
            top: 6px;
            width: 14px;
            height: 8px;
            border-left: 2px solid #4e5058;
            border-top: 2px solid #4e5058;
            border-top-left-radius: 4px;
        }}
        .footer-note {{
            text-align: center;
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
        }}
    </style>
</head>
<body>
    <header class="header">
        <div class="header-left">
            <img src="{escape_html(guild_icon)}" class="header-icon" alt="{escape_html(guild_name)}">
            <div>
                <div class="header-title">#{escape_html(channel_name)}</div>
                <div class="header-subtitle">{escape_html(guild_name)} • Closed at {escape_html(now_str)}</div>
            </div>
        </div>
        <div class="header-stats">
            <div class="stat-badge">💬 {msg_count} Messages</div>
            <div class="stat-badge">📷 {attachment_count} Attachments</div>
            <div class="stat-badge">👥 {len(participants)} Participants</div>
        </div>
    </header>

    <main class="chat-container">
"""

    last_author_id = None
    last_timestamp = None

    for m in messages:
        author = m.author
        author_name = author.display_name
        author_avatar = author.display_avatar.url if hasattr(author, 'display_avatar') else "https://cdn.discordapp.com/embed/avatars/0.png"
        is_bot = author.bot
        ts_str = m.created_at.strftime("%Y-%m-%d %H:%M:%S")

        # Check if consecutive message from same author within 5 minutes
        is_consecutive = (
            last_author_id == author.id and
            last_timestamp and
            (m.created_at - last_timestamp).total_seconds() < 300
        )

        message_html = []

        if not is_consecutive:
            message_html.append('<div class="message-group">')
            message_html.append(f'<div class="avatar-column"><img src="{escape_html(author_avatar)}" class="avatar" alt="{escape_html(author_name)}"></div>')
            message_html.append('<div class="message-content">')
            message_html.append('<div class="message-header">')
            message_html.append(f'<span class="author-name">{escape_html(author_name)}</span>')
            if is_bot:
                message_html.append('<span class="bot-badge">BOT</span>')
            message_html.append(f'<span class="timestamp">{escape_html(ts_str)}</span>')
            message_html.append('</div>')
        else:
            message_html.append('<div class="message-group" style="margin-top: 2px;">')
            message_html.append('<div class="avatar-column"></div>')
            message_html.append('<div class="message-content">')

        # Text Content
        if m.content:
            message_html.append(f'<div class="message-text">{format_discord_markdown(m.content, guild)}</div>')

        # Attachments (Images, Videos, Files)
        if m.attachments:
            message_html.append('<div class="attachments-container">')
            for att in m.attachments:
                fn_lower = att.filename.lower()
                is_img = any(fn_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp'])
                is_vid = any(fn_lower.endswith(ext) for ext in ['.mp4', '.webm', '.mov'])
                size_kb = max(1, att.size // 1024)

                if is_img:
                    img_src = get_image_data_uri(att.url, att.filename)
                    message_html.append(f'''
                    <div class="attachment-card">
                        <a href="{escape_html(att.url)}" target="_blank" title="Click to view full image ({escape_html(att.filename)})">
                            <img src="{escape_html(img_src)}" class="attachment-img" alt="{escape_html(att.filename)}">
                        </a>
                    </div>
                    ''')

                elif is_vid:
                    message_html.append(f'''
                    <div class="attachment-card">
                        <video controls style="max-width: 480px; max-height: 320px; border-radius: 6px;">
                            <source src="{escape_html(att.url)}">
                            Your browser does not support video.
                        </video>
                    </div>
                    ''')
                else:
                    message_html.append(f'''
                    <div class="file-attachment">
                        <span class="file-icon">📄</span>
                        <div>
                            <a href="{escape_html(att.url)}" target="_blank" style="font-weight: 600;">{escape_html(att.filename)}</a>
                            <div style="font-size: 11px; color: var(--text-muted);">{size_kb} KB</div>
                        </div>
                    </div>
                    ''')
            message_html.append('</div>')

        # Embeds
        if m.embeds:
            for emb in m.embeds:
                message_html.append(build_html_embed(emb, guild))

        message_html.append('</div></div>')

        html_template += ''.join(message_html) + '\n'

        last_author_id = author.id
        last_timestamp = m.created_at

    closed_by_name = closed_by.display_name if closed_by else "Staff"
    html_template += f"""
        <div class="footer-note">
            Ticket #{escape_html(channel_name)} transcript generated by Tournament Bot • Closed by {escape_html(closed_by_name)}
        </div>
    </main>
</body>
</html>
"""
    return html_template


def generate_text_transcript(
    channel: discord.TextChannel,
    messages: List[discord.Message],
    guild: discord.Guild,
    closed_by: Optional[discord.Member] = None
) -> str:
    lines = []
    guild_name = guild.name if guild else "Discord Server"
    channel_name = channel.name if channel else "ticket-channel"
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    closed_by_str = closed_by.display_name if closed_by else "Staff"

    lines.append("=" * 80)
    lines.append(f"TRANSCRIPT FOR TICKET CHANNEL: #{channel_name}")
    lines.append(f"SERVER: {guild_name}")
    lines.append(f"EXPORT DATE: {now_str}")
    lines.append(f"CLOSED BY: {closed_by_str}")
    lines.append(f"TOTAL MESSAGES: {len(messages)}")
    lines.append("=" * 80)
    lines.append("")

    for m in messages:
        time_str = m.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author_str = f"{m.author.display_name} ({m.author.name})"
        content = m.clean_content or ""
        
        lines.append(f"[{time_str}] {author_str}:")
        if content:
            for c_line in content.split('\n'):
                lines.append(f"  {c_line}")

        if m.attachments:
            for att in m.attachments:
                size_kb = max(1, att.size // 1024)
                lines.append(f"  📎 [Attachment: {att.filename} ({size_kb} KB)] -> {att.url}")

        if m.embeds:
            for emb in m.embeds:
                emb_title = emb.title or "Embed"
                emb_desc = emb.description or ""
                lines.append(f"  📋 [Embed: {emb_title}] {emb_desc}")
                for f in emb.fields:
                    lines.append(f"     • {f.name}: {f.value}")
                if emb.image and emb.image.url:
                    lines.append(f"     📷 Image: {emb.image.url}")

        lines.append("")

    return "\n".join(lines)


async def build_transcript_files(
    channel: discord.TextChannel,
    closed_by: Optional[discord.Member] = None,
    limit: int = 1000
) -> Tuple[discord.File, discord.File, Dict[str, Any]]:
    messages = []
    async for m in channel.history(limit=limit, oldest_first=True):
        messages.append(m)

    guild = channel.guild
    html_content = generate_html_transcript(channel, messages, guild, closed_by=closed_by)
    text_content = generate_text_transcript(channel, messages, guild, closed_by=closed_by)

    clean_chan_name = re.sub(r'[^a-zA-Z0-9_\-]', '', channel.name).lower() or "ticket"
    html_filename = f"transcript_{clean_chan_name}.html"
    text_filename = f"transcript_{clean_chan_name}.txt"

    html_file = discord.File(io.BytesIO(html_content.encode('utf-8')), filename=html_filename)
    text_file = discord.File(io.BytesIO(text_content.encode('utf-8')), filename=text_filename)

    attachment_count = sum(len(m.attachments) for m in messages)
    stats = {
        "message_count": len(messages),
        "attachment_count": attachment_count,
        "participant_count": len(set(m.author.id for m in messages)),
        "channel_name": channel.name,
        "html_filename": html_filename,
        "text_filename": text_filename
    }

    return html_file, text_file, stats

