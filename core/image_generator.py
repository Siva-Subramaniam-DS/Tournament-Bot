import os
import io
import re
import random
import glob
import tempfile
import unicodedata
import datetime
from pathlib import Path
from typing import Optional, Union, List

import requests
import discord
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont, ImageOps

from core.config import BASE_DIR, GAME_ALIASES, ORGANIZATION_NAME
from core.database import load_guild_tournaments, get_thumbnail_url_from_channel


# ===========================================================================================
# GOOGLE FONTS & LOCAL FONT LOADERS
# ===========================================================================================

def download_google_font(font_family: str, font_style: str = "regular", font_weight: str = "400") -> Optional[str]:
    """Download a font from Google Fonts API and return the local temporary file path."""
    try:
        api_url = f"https://fonts.googleapis.com/css2?family={font_family.replace(' ', '+')}:wght@{font_weight}"
        if font_style != "regular":
            api_url += f"&style={font_style}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        css_content = response.text
        font_urls = re.findall(r'url\((https://[^)]+\.woff2?)\)', css_content)
        
        if not font_urls:
            return None
        
        font_url = font_urls[0]
        font_response = requests.get(font_url, timeout=15)
        font_response.raise_for_status()
        
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.woff2')
        temp_file.write(font_response.content)
        temp_file.close()
        return temp_file.name
        
    except Exception as e:
        print(f"Error downloading Google Font {font_family}: {e}")
        return None

def get_font_with_fallbacks(font_name: str, size: int, font_style: str = "regular") -> ImageFont.FreeTypeFont:
    """Get a font using local fonts first, then Google Fonts as fallback."""
    fonts_dir = "/home/container/Fonts"
    if not os.path.exists(fonts_dir):
        if os.path.exists("/home/container/fonts"):
            fonts_dir = "/home/container/fonts"
        else:
            fonts_dir = os.path.join(BASE_DIR, "Fonts")
    font_candidates = []
    
    # 1. Try local fonts FIRST (from Fonts/ folder)
    if font_name in ("Geoform", "geoform", "DS-Digital"):
        if font_style == "bold":
            local_fonts = [
                str(Path(fonts_dir) / "geoform" / "Geoform-Bold.otf"),
                str(Path(fonts_dir) / "geoform" / "Geoform.otf"),
                str(Path(fonts_dir) / "geoform" / "Geoform-BoldItalic.otf"),
            ]
        else:
            local_fonts = [
                str(Path(fonts_dir) / "geoform" / "Geoform.otf"),
                str(Path(fonts_dir) / "geoform" / "Geoform-Bold.otf"),
                str(Path(fonts_dir) / "geoform" / "Geoform-BoldItalic.otf"),
            ]
    else:
        local_fonts = []
        if font_name == "Capture it":
            local_fonts.append(str(Path(fonts_dir) / "capture_it" / "Capture it.ttf"))
        elif font_name == "Square One":
            local_fonts.extend([
                str(Path(fonts_dir) / "square_one_2" / "Square One Bold.ttf"),
                str(Path(fonts_dir) / "square_one_2" / "Square One.ttf"),
            ])
            
        all_other_fonts = [
            str(Path(fonts_dir) / "geoform" / "Geoform-Bold.otf"),
            str(Path(fonts_dir) / "geoform" / "Geoform.otf"),
            str(Path(fonts_dir) / "capture_it" / "Capture it.ttf"),
            str(Path(fonts_dir) / "square_one_2" / "Square One Bold.ttf"),
            str(Path(fonts_dir) / "square_one_2" / "Square One.ttf"),
        ]
        for f_path in all_other_fonts:
            if f_path not in local_fonts:
                local_fonts.append(f_path)
    # 1. Check local fonts FIRST
    for font_path in local_fonts:
        try:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        except Exception:
            continue

    # 2. Try Google Fonts as fallback
    try:
        google_font_path = download_google_font(font_name, font_style)
        if google_font_path and os.path.exists(google_font_path):
            return ImageFont.truetype(google_font_path, size)
    except Exception:
        pass
    
    # 3. Try standard system fonts
    system_fonts = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf", 
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/trebucbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for font_path in system_fonts:
        try:
            if os.path.exists(font_path):
                return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    
    try:
        return ImageFont.load_default(size=size)
    except:
        return ImageFont.load_default()

def sanitize_username_for_poster(username: str) -> str:
    """Convert Discord display names to poster-friendly ASCII by stripping emojis and fancy Unicode."""
    try:
        normalized = unicodedata.normalize('NFKD', str(username))
        ascii_only = normalized.encode('ascii', 'ignore').decode('ascii')
        ascii_only = re.sub(r"[^\x20-\x7E]", "", ascii_only)
        ascii_only = re.sub(r"\s+", " ", ascii_only).strip()
        return ascii_only if ascii_only else "Player"
    except Exception:
        return str(username) if username else "Player"


# ===========================================================================================
# TEMPLATE FOLDER RESOLUTION & AUTOCOMPLETE
# ===========================================================================================

def get_templates_base_path() -> str:
    """Resolve the absolute Templates directory path."""
    for p in ["/home/container/templates", "/home/container/Templates", os.path.join(BASE_DIR, "Templates"), os.path.join(BASE_DIR, "templates")]:
        if os.path.exists(p):
            return p
    return os.path.join(BASE_DIR, "Templates")

def get_available_game_templates() -> List[str]:
    """Return a sorted list of all available game template folders."""
    base = get_templates_base_path()
    if not os.path.exists(base):
        return []
    try:
        subdirs = [
            d for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d)) and not d.startswith(".") and not d.startswith("__")
        ]
        return sorted(subdirs)
    except Exception as e:
        print(f"Error listing game template folders: {e}")
        return []

async def game_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    try:
        games = get_available_game_templates()
        if not games:
            games = [
                "Modern Warship", "BGMI", "Free Fire", "Valorant",
                "Call of Duty Mobile", "Mobile Legends", "Counter Strike 2",
                "Apex Legends", "Fortnite", "Rocket League", "Dota 2",
                "Brawl Stars", "Clash Royale", "Rainbow Six Siege", "Warzone"
            ]
        choices = []
        for g in games:
            if current.lower() in g.lower():
                choices.append(app_commands.Choice(name=g, value=g))
        return choices[:25]
    except Exception as e:
        print(f"Error in game_autocomplete: {e}")
        return []

async def tournament_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    if not interaction.guild_id:
        return []
    try:
        tournaments = load_guild_tournaments(interaction.guild_id)
        choices = []
        for t_id, t_cfg in tournaments.items():
            name = t_cfg.get('name', t_id)
            if current.lower() in name.lower() or current.lower() in t_id.lower():
                choices.append(app_commands.Choice(name=name, value=t_id))
        return choices[:25]
    except Exception as e:
        print(f"Error in tournament_autocomplete: {e}")
        return []

def get_random_template(game_or_mode: str = None) -> Optional[str]:
    """Get a random template image from the Templates folder or a specific game subfolder."""
    template_path = get_templates_base_path()

    if not os.path.exists(template_path):
        fallback_banners = ["tournament_bot_banner.png", "banner.png"]
        for fb in fallback_banners:
            fb_path = os.path.join(BASE_DIR, fb)
            if os.path.exists(fb_path):
                return fb_path
        return None

    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif']
    
    def get_images_in_dir(folder_path):
        files = []
        if os.path.exists(folder_path):
            for ext in image_extensions:
                files.extend(glob.glob(os.path.join(folder_path, ext)))
                files.extend(glob.glob(os.path.join(folder_path, ext.upper())))
        return list(dict.fromkeys(files))

    # 1. Match game subfolder
    if game_or_mode and str(game_or_mode).strip():
        raw_term = str(game_or_mode).strip()
        search_term = raw_term.lower()
        canonical_game = GAME_ALIASES.get(search_term, raw_term)
        canonical_lower = canonical_game.lower()

        try:
            subdirs = [d for d in os.listdir(template_path) if os.path.isdir(os.path.join(template_path, d))]
            matched_folder = None
            
            for d in subdirs:
                if d.lower() == canonical_lower or d.lower() == search_term or d.lower().replace(" ", "") == search_term.replace(" ", ""):
                    matched_folder = os.path.join(template_path, d)
                    break
            
            if not matched_folder:
                for d in subdirs:
                    if d.lower() in search_term or search_term in d.lower() or d.lower() in canonical_lower or canonical_lower in d.lower():
                        matched_folder = os.path.join(template_path, d)
                        break

            if matched_folder:
                game_images = get_images_in_dir(matched_folder)
                if game_images:
                    return random.choice(game_images)
        except Exception as e:
            print(f"Error checking game template folder for '{game_or_mode}': {e}")

    # 2. Root templates folder images
    root_images = get_images_in_dir(template_path)
    if root_images:
        return random.choice(root_images)

    # 3. Any subfolder fallback
    all_subfolder_images = []
    try:
        for entry in os.listdir(template_path):
            full_entry = os.path.join(template_path, entry)
            if os.path.isdir(full_entry):
                all_subfolder_images.extend(get_images_in_dir(full_entry))
    except Exception as e:
        print(f"Error scanning subfolders in Templates: {e}")

    if all_subfolder_images:
        return random.choice(all_subfolder_images)

    # 4. Fallback root banner
    fallback_banners = ["tournament_bot_banner.png", "banner.png"]
    for fb in fallback_banners:
        fb_path = os.path.join(BASE_DIR, fb)
        if os.path.exists(fb_path):
            return fb_path

    return None


# ===========================================================================================
# MATCH BANNER / POSTER GENERATOR WITH TOP-RIGHT SERVER LOGO
# ===========================================================================================

def create_event_poster(
    template_path: str, 
    round_label: str, 
    team1_captain: str, 
    team2_captain: str, 
    utc_time: str, 
    date_str: str = None, 
    server_name: str = "Tournament Organizer",
    server_logo_path: Optional[str] = None
) -> Optional[str]:
    """
    Create event poster with text overlays and Top-Right Server Logo badge.
    """
    try:
        if not os.path.exists(template_path):
            print(f"Template file not found: {template_path}")
            return None
            
        with Image.open(template_path) as img:
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            
            # Standard dimensions for crisp Discord display
            max_width, max_height = 800, 600
            width, height = img.size
            
            if width > max_width or height > max_height:
                ratio = min(max_width / width, max_height / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            poster = img.copy()
            draw = ImageDraw.Draw(poster)
            width, height = poster.size
            
            # Proportional font sizes
            title_size = int(height * 0.10)
            round_size = int(height * 0.14)
            vs_size = int(height * 0.09)
            time_size = int(height * 0.07)
            
            try:
                font_title = get_font_with_fallbacks("Capture it", title_size, "bold")
                font_round = get_font_with_fallbacks("Geoform", round_size, "bold")
                font_vs = get_font_with_fallbacks("Capture it", vs_size, "bold")
                font_time = get_font_with_fallbacks("Geoform", time_size, "bold")
            except Exception:
                font_title = ImageFont.load_default()
                font_round = ImageFont.load_default()
                font_vs = ImageFont.load_default()
                font_time = ImageFont.load_default()
            
            text_color = (255, 255, 255)
            outline_color = (0, 0, 0)
            yellow_color = (255, 255, 0)
            
            def draw_text_with_outline(text, x, y, font, text_color=text_color, use_yellow=False):
                x, y = int(x), int(y)
                final_text_color = yellow_color if use_yellow else text_color
                outline_width = 4
                for dx in range(-outline_width, outline_width + 1):
                    for dy in range(-outline_width, outline_width + 1):
                        if dx != 0 or dy != 0:
                            try:
                                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
                            except Exception:
                                pass
                try:
                    draw.text((x, y), text, font=font, fill=final_text_color)
                except Exception:
                    pass

            # ----------------------------------------------------
            # 1. OVERLAY SERVER LOGO IN TOP-RIGHT CORNER
            # ----------------------------------------------------
            logo_applied = False
            if server_logo_path and os.path.exists(server_logo_path):
                try:
                    with Image.open(server_logo_path) as logo_img:
                        if logo_img.mode != 'RGBA':
                            logo_img = logo_img.convert('RGBA')
                        
                        badge_size = int(height * 0.16) # ~90-100px on 600px height
                        logo_img = logo_img.resize((badge_size, badge_size), Image.Resampling.LANCZOS)
                        
                        # Create circular mask with anti-aliasing
                        mask = Image.new('L', (badge_size * 2, badge_size * 2), 0)
                        mask_draw = ImageDraw.Draw(mask)
                        mask_draw.ellipse((0, 0, badge_size * 2, badge_size * 2), fill=255)
                        mask = mask.resize((badge_size, badge_size), Image.Resampling.LANCZOS)
                        
                        # Paste circular logo in top-right
                        logo_x = width - badge_size - int(width * 0.03)
                        logo_y = int(height * 0.04)
                        
                        poster.paste(logo_img, (logo_x, logo_y), mask)
                        
                        # Draw gold/white circular badge border
                        draw.ellipse(
                            [(logo_x - 1, logo_y - 1), (logo_x + badge_size + 1, logo_y + badge_size + 1)],
                            outline=(255, 215, 0, 230), # Gold ring
                            width=3
                        )
                        logo_applied = True
                except Exception as logo_err:
                    print(f"Error applying top-right server logo on poster: {logo_err}")

            # ----------------------------------------------------
            # 2. SERVER NAME TEXT (Top Center)
            # ----------------------------------------------------
            try:
                server_text = server_name
                server_bbox = draw.textbbox((0, 0), server_text, font=font_title)
                server_width = server_bbox[2] - server_bbox[0]
                
                # If logo is on top-right, leave safety margin on right side
                max_text_width = width * 0.75 if logo_applied else width * 0.90
                temp_font = font_title
                temp_size = title_size
                while server_width > max_text_width and temp_size > 10:
                    temp_size -= 2
                    try:
                        temp_font = get_font_with_fallbacks("Capture it", temp_size, "bold")
                    except Exception:
                        temp_font = ImageFont.load_default()
                    server_bbox = draw.textbbox((0, 0), server_text, font=temp_font)
                    server_width = server_bbox[2] - server_bbox[0]
                
                font_title = temp_font
                # Center within available header area
                server_x = (width - server_width) // 2
                server_y = int(height * 0.08)
                draw_text_with_outline(server_text, server_x, server_y, font_title)
            except Exception as e:
                print(f"Error adding server name: {e}")

            # ----------------------------------------------------
            # 3. ROUND TEXT (Center Top - Yellow)
            # ----------------------------------------------------
            try:
                round_text = f"ROUND {round_label}"
                round_bbox = draw.textbbox((0, 0), round_text, font=font_round)
                round_width = round_bbox[2] - round_bbox[0]
                round_x = (width - round_width) // 2
                round_y = int(height * 0.35)
                draw_text_with_outline(round_text, round_x, round_y, font_round, use_yellow=True)
            except Exception as e:
                print(f"Error adding round text: {e}")

            # ----------------------------------------------------
            # 4. CAPTAIN VS CAPTAIN TEXT (Center)
            # ----------------------------------------------------
            try:
                left_name_text = sanitize_username_for_poster(team1_captain)
                vs_core = " VS "
                right_name_text = sanitize_username_for_poster(team2_captain)

                left_box = draw.textbbox((0, 0), left_name_text, font=font_vs)
                vs_box = draw.textbbox((0, 0), vs_core, font=font_vs)
                right_box = draw.textbbox((0, 0), right_name_text, font=font_vs)
                total_width = (left_box[2] - left_box[0]) + (vs_box[2] - vs_box[0]) + (right_box[2] - right_box[0])
                
                temp_font_vs = font_vs
                temp_vs_size = vs_size
                while total_width > width * 0.95 and temp_vs_size > 10:
                    temp_vs_size -= 2
                    try:
                        temp_font_vs = get_font_with_fallbacks("Capture it", temp_vs_size, "bold")
                    except Exception:
                        temp_font_vs = ImageFont.load_default()
                    left_box = draw.textbbox((0, 0), left_name_text, font=temp_font_vs)
                    vs_box = draw.textbbox((0, 0), vs_core, font=temp_font_vs)
                    right_box = draw.textbbox((0, 0), right_name_text, font=temp_font_vs)
                    total_width = (left_box[2] - left_box[0]) + (vs_box[2] - vs_box[0]) + (right_box[2] - right_box[0])
                
                font_vs = temp_font_vs
                current_x = (width - total_width) // 2
                vs_y = int(height * 0.55)

                draw_text_with_outline(left_name_text, current_x, vs_y, font_vs)
                current_x += (left_box[2] - left_box[0])
                draw_text_with_outline(vs_core, current_x, vs_y, font_vs, use_yellow=False)
                current_x += (vs_box[2] - vs_box[0])
                draw_text_with_outline(right_name_text, current_x, vs_y, font_vs)
            except Exception as e:
                print(f"Error adding VS text: {e}")

            # ----------------------------------------------------
            # 5. DATE (Optional) & UTC TIME (Bottom)
            # ----------------------------------------------------
            if date_str:
                try:
                    date_text = f"DATE:  {date_str}"
                    date_bbox = draw.textbbox((0, 0), date_text, font=font_time)
                    date_width = date_bbox[2] - date_bbox[0]
                    date_x = (width - date_width) // 2
                    date_y = int(height * 0.72)
                    draw_text_with_outline(date_text, date_x, date_y, font_time)
                except Exception as e:
                    print(f"Error adding date: {e}")

            try:
                time_text = f"TIME:  {utc_time}"
                time_bbox = draw.textbbox((0, 0), time_text, font=font_time)
                time_width = time_bbox[2] - time_bbox[0]
                time_x = (width - time_width) // 2
                time_y = int(height * 0.82) if date_str else int(height * 0.75)
                draw_text_with_outline(time_text, time_x, time_y, font_time)
            except Exception as e:
                print(f"Error adding time: {e}")

            # Save generated poster to temp file
            output_path = os.path.join(BASE_DIR, f"temp_poster_{int(datetime.datetime.now().timestamp())}.png")
            poster.save(output_path, "PNG")
            return output_path

    except Exception as e:
        print(f"Critical error creating poster: {e}")
        return None


# ===========================================================================================
# ID CARD GENERATION
# ===========================================================================================

def convert_google_drive_url(url: str) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        return url
    file_id = None
    file_id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if file_id_match:
        file_id = file_id_match.group(1)
    if not file_id:
        id_match = re.search(r'[?&]id=([a-zA-Z0-9-_]+)', url)
        if id_match:
            file_id = id_match.group(1)
    if not file_id:
        folder_match = re.search(r'/folders/([a-zA-Z0-9-_]+)', url)
        if folder_match:
            file_id = folder_match.group(1)
    if file_id:
        return f"https://drive.google.com/uc?export=view&id={file_id}"
    return url

def create_id_card_image(user_data: dict, discord_user: discord.Member, org_name: str = "Tournament Organizer") -> io.BytesIO:
    card_width = 800
    card_height = 500
    img = Image.new('RGB', (card_width, card_height), color='#1a1a2e')
    draw = ImageDraw.Draw(img)
    for i in range(card_height):
        r = int(26 + (i / card_height) * 10)
        g = int(26 + (i / card_height) * 20)
        b = int(46 + (i / card_height) * 30)
        draw.rectangle([(0, i), (card_width, i + 1)], fill=(r, g, b))
    
    border_width = 4
    draw.rectangle(
        [(border_width, border_width), (card_width - border_width, card_height - border_width)],
        outline='#FFD700',
        width=border_width
    )
    
    title_font = get_font_with_fallbacks("Arial", 40, "bold")
    heading_font = get_font_with_fallbacks("Arial", 24, "bold")
    text_font = get_font_with_fallbacks("Arial", 20)
    
    header_y = 20
    draw.text((card_width // 2, header_y), f"{org_name} ID CARD", fill='#FFD700', font=title_font, anchor='mt')
    
    logo_size = 150
    logo_x = 50
    logo_y = 100
    logo_path = os.path.join(BASE_DIR, "tournament_bot_logo.png")
    try:
        if os.path.exists(logo_path):
            logo_img = Image.open(logo_path)
            if logo_img.mode != 'RGBA':
                logo_img = logo_img.convert('RGBA')
            logo_img.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
            logo_width, logo_height = logo_img.size
            logo_paste_x = logo_x + (logo_size - logo_width) // 2
            logo_paste_y = logo_y + (logo_size - logo_height) // 2
            if logo_img.mode == 'RGBA':
                img.paste(logo_img, (logo_paste_x, logo_paste_y), logo_img)
            else:
                img.paste(logo_img, (logo_paste_x, logo_paste_y))
            draw.rectangle([(logo_x - 2, logo_y - 2), (logo_x + logo_size + 2, logo_y + logo_size + 2)], outline='#FFD700', width=2)
        else:
            draw.rectangle([(logo_x, logo_y), (logo_x + logo_size, logo_y + logo_size)], outline='#FFD700', width=3)
            org_initials = "".join([w[0] for w in str(org_name).split() if w])[:4].upper() or "LOGO"
            draw.text((logo_x + logo_size // 2, logo_y + logo_size // 2), org_initials, fill='#FFD700', font=heading_font, anchor='mm')
    except Exception:
        draw.rectangle([(logo_x, logo_y), (logo_x + logo_size, logo_y + logo_size)], outline='#FFD700', width=3)
        org_initials = "".join([w[0] for w in str(org_name).split() if w])[:4].upper() or "LOGO"
        draw.text((logo_x + logo_size // 2, logo_y + logo_size // 2), org_initials, fill='#FFD700', font=heading_font, anchor='mm')
    
    screenshot_size = 120
    screenshot_x = logo_x
    screenshot_y = logo_y + logo_size + 20
    if user_data.get('screenshot_url'):
        try:
            screenshot_url = convert_google_drive_url(user_data['screenshot_url'])
            screenshot_response = requests.get(screenshot_url, timeout=10)
            if screenshot_response.status_code == 200:
                screenshot_img = Image.open(io.BytesIO(screenshot_response.content)).convert('RGB')
                screenshot_img = screenshot_img.resize((screenshot_size, screenshot_size), Image.Resampling.LANCZOS)
                img.paste(screenshot_img, (screenshot_x, screenshot_y))
                draw.rectangle([(screenshot_x - 2, screenshot_y - 2), (screenshot_x + screenshot_size + 2, screenshot_y + screenshot_size + 2)], outline='#FFD700', width=2)
        except Exception as e:
            print(f"Error loading screenshot: {e}")
    
    info_x = 250
    info_y = 120
    line_height = 40
    current_y = info_y
    
    draw.text((info_x, current_y), "Discord Tag:", fill='#FFD700', font=heading_font)
    draw.text((info_x + 180, current_y), user_data.get('discord_tag', 'N/A') or 'N/A', fill='#FFFFFF', font=text_font)
    current_y += line_height
    
    draw.text((info_x, current_y), "Game Name:", fill='#FFD700', font=heading_font)
    draw.text((info_x + 180, current_y), user_data.get('game_name', 'N/A') or 'N/A', fill='#FFFFFF', font=text_font)
    current_y += line_height
    
    draw.text((info_x, current_y), "Game ID:", fill='#FFD700', font=heading_font)
    draw.text((info_x + 180, current_y), str(user_data.get('game_id', 'N/A') or 'N/A'), fill='#FFFFFF', font=text_font)
    current_y += line_height
    
    if user_data.get('real_name'):
        draw.text((info_x, current_y), "Real Name:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), user_data.get('real_name', 'N/A'), fill='#FFFFFF', font=text_font)
        current_y += line_height
    
    if user_data.get('country'):
        draw.text((info_x, current_y), "Country:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), user_data.get('country', 'N/A'), fill='#FFFFFF', font=text_font)
        current_y += line_height
    
    if user_data.get('title'):
        draw.text((info_x, current_y), "Title:", fill='#FFD700', font=heading_font)
        draw.text((info_x + 180, current_y), user_data.get('title', 'N/A'), fill='#FFFFFF', font=text_font)
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    img_byte_arr.seek(0)
    return img_byte_arr
