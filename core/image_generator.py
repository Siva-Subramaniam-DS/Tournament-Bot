import os
import io
import re
import math
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
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter, ImageChops, ImageEnhance

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
    if font_name.lower() in ("rajdhani",):
        if font_style == "bold":
            local_fonts = [
                str(Path(fonts_dir) / "rajdhani" / "Rajdhani-Bold.ttf"),
                str(Path(fonts_dir) / "rajdhani" / "Rajdhani-SemiBold.ttf"),
                str(Path(fonts_dir) / "geoform" / "Geoform-Bold.otf"),
            ]
        else:
            local_fonts = [
                str(Path(fonts_dir) / "rajdhani" / "Rajdhani-SemiBold.ttf"),
                str(Path(fonts_dir) / "rajdhani" / "Rajdhani-Bold.ttf"),
                str(Path(fonts_dir) / "geoform" / "Geoform.otf"),
            ]
    elif font_name in ("Geoform", "geoform", "DS-Digital"):
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
            str(Path(fonts_dir) / "rajdhani" / "Rajdhani-Bold.ttf"),
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
            if "(" in t_id and "[" in t_id:
                continue
            name = t_cfg.get('name', t_id)
            if current.lower() in name.lower() or current.lower() in t_id.lower():
                choices.append(app_commands.Choice(name=name, value=t_id))
        return choices[:25]
    except Exception as e:
        print(f"Error in tournament_autocomplete: {e}")
        return []

def get_thumbnail_layer_path() -> Optional[str]:
    """Resolve the absolute path to Templates/Thumbnail Layer.png if available."""
    base = get_templates_base_path()
    candidates = [
        os.path.join(base, "Thumbnail Layer.png"),
        os.path.join(base, "thumbnail layer.png"),
        os.path.join(BASE_DIR, "Templates", "Thumbnail Layer.png"),
        os.path.join(BASE_DIR, "templates", "Thumbnail Layer.png"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

def get_random_template(game_or_mode: str = None) -> Optional[str]:
    """Get a random template image from the Templates folder or a specific game subfolder."""
    # If no game specified or generic match, prioritize Thumbnail Layer.png if present
    thumb_layer = get_thumbnail_layer_path()
    if not game_or_mode and thumb_layer:
        return thumb_layer
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
# PROCEDURAL GRAPHICS HELPERS (GRADIENTS, GLOWS, TEXT DRAWING)
# ===========================================================================================

def draw_vertical_gradient(width: int, height: int, top_color: tuple, bottom_color: tuple) -> Image.Image:
    """Generate a vertical 2-color gradient RGBA image."""
    base = Image.new('RGBA', (max(1, width), max(1, height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    for y in range(height):
        factor = y / max(1, height - 1)
        r = int(top_color[0] + factor * (bottom_color[0] - top_color[0]))
        g = int(top_color[1] + factor * (bottom_color[1] - top_color[1]))
        b = int(top_color[2] + factor * (bottom_color[2] - top_color[2]))
        a = int(top_color[3] + factor * (bottom_color[3] - top_color[3])) if len(top_color) > 3 and len(bottom_color) > 3 else 255
        draw.line([(0, y), (width, y)], fill=(r, g, b, a))
    return base

def draw_gradient_text(canvas: Image.Image, text: str, font: ImageFont.FreeTypeFont, xy: tuple, top_color: tuple, bottom_color: tuple, shadow=True, shadow_offset=(3, 4), shadow_color=(0, 0, 0, 200), anchor=None):
    """Render text with a smooth vertical linear gradient and optional soft drop shadow."""
    x, y = xy
    dummy = Image.new('RGBA', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy)
    bbox = dummy_draw.textbbox((0, 0), text, font=font, anchor=anchor)
    w = max(1, bbox[2] - bbox[0])
    h = max(1, bbox[3] - bbox[1])
    
    pad = 12
    mask_w = w + pad * 2
    mask_h = h + pad * 2
    text_mask = Image.new('L', (mask_w, mask_h), 0)
    mask_draw = ImageDraw.Draw(text_mask)
    
    text_draw_x = pad - bbox[0]
    text_draw_y = pad - bbox[1]
    mask_draw.text((text_draw_x, text_draw_y), text, font=font, fill=255, anchor=anchor)
    
    if shadow:
        shadow_mask = text_mask.filter(ImageFilter.GaussianBlur(3))
        shadow_layer = Image.new('RGBA', (mask_w, mask_h), shadow_color)
        canvas.paste(shadow_layer, (int(x + bbox[0] - pad + shadow_offset[0]), int(y + bbox[1] - pad + shadow_offset[1])), shadow_mask)

    gradient = draw_vertical_gradient(mask_w, mask_h, top_color, bottom_color)
    canvas.paste(gradient, (int(x + bbox[0] - pad), int(y + bbox[1] - pad)), text_mask)

def format_display_date(date_str: Optional[str]) -> str:
    """Format date string into clean 'DAY, DD-MM-YY' display string."""
    if not date_str or not str(date_str).strip():
        return datetime.datetime.now(datetime.timezone.utc).strftime("%A, %d-%m-%y").upper()
    raw = str(date_str).strip()
    try:
        parts = re.split(r'[/.-]', raw)
        if len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 100:
                year += 2000
            dt = datetime.date(year, month, day)
            return dt.strftime("%A, %d-%m-%y").upper()
    except Exception:
        pass
    return raw.upper()

# ===========================================================================================
# MODERN ESPORTS MATCH POSTER GENERATOR (1920x1080)
# ===========================================================================================

def create_esports_match_poster(
    template_path: str,
    round_label: str,
    team1_name: str,
    team2_name: str,
    utc_time: str,
    date_str: Optional[str] = None,
    server_name: str = "Tournament Organizer",
    server_logo_path: Optional[str] = None,
    tournament_title: Optional[str] = None
) -> Optional[str]:
    """
    Create a 1920x1080 esports match thumbnail matching modern competitive broadcast aesthetics:
    - Automatically incorporates Templates/Thumbnail Layer.png with cinematic arena spotlights & 3D metallic VS
    - Composites game background seamlessly when game template is provided
    - Illuminated left and right team spotlight zones with futuristic glow baselines
    - Luminous top emblem & championship gradient typography
    - Translucent capsule badge for Group / Round info
    - Glassmorphic bottom HUD card with 3-column partitioned layout (DATE | TIME | SERVER)
    """
    try:
        target_w, target_h = 1920, 1080
        thumb_layer = get_thumbnail_layer_path()
        use_spotlight_layer = False

        if thumb_layer and os.path.exists(thumb_layer):
            # Sample 1: Pure Thumbnail Layer stage background
            with Image.open(thumb_layer) as tl_raw:
                bg = tl_raw.convert('RGBA').resize((target_w, target_h), Image.Resampling.LANCZOS)
            use_spotlight_layer = True

        if not use_spotlight_layer:
            if not template_path or not os.path.exists(template_path):
                fallback = get_random_template()
                if fallback and os.path.exists(fallback):
                    template_path = fallback
                else:
                    print(f"Template image not found: {template_path}")
                    return None

            # 1. Base background: load and cover crop to 1920x1080
            with Image.open(template_path) as bg_raw:
                bg = bg_raw.convert('RGBA')
                bw, bh = bg.size
                scale = max(target_w / bw, target_h / bh)
                new_bw = int(bw * scale)
                new_bh = int(bh * scale)
                bg = bg.resize((new_bw, new_bh), Image.Resampling.LANCZOS)
                crop_x = (new_bw - target_w) // 2
                crop_y = (new_bh - target_h) // 2
                bg = bg.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))

            # 2. Add cinematic vignette & darkening overlay for text contrast
            dark_overlay = Image.new('RGBA', (target_w, target_h), (5, 8, 16, 115))
            bg = Image.alpha_composite(bg, dark_overlay)

            grad_layer = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
            grad_draw = ImageDraw.Draw(grad_layer)
            for y in range(260):
                alpha = int(140 * (1 - y / 260))
                grad_draw.line([(0, y), (target_w, y)], fill=(2, 4, 10, alpha))
            for y in range(800, target_h):
                alpha = int(160 * ((y - 800) / (target_h - 800)))
                grad_draw.line([(0, y), (target_w, y)], fill=(2, 4, 10, alpha))
            bg = Image.alpha_composite(bg, grad_layer)

        draw = ImageDraw.Draw(bg)

        # 3. Corner Reticle Brackets [ ] (Only for legacy fallback templates without spotlight stage)
        if not use_spotlight_layer:
            corner_color = (235, 85, 75, 230)
            c_margin = 48
            c_len = 65
            c_thick = 4

            # Top-Left ┌
            draw.line([(c_margin, c_margin), (c_margin + c_len, c_margin)], fill=corner_color, width=c_thick)
            draw.line([(c_margin, c_margin), (c_margin, c_margin + c_len)], fill=corner_color, width=c_thick)
            # Top-Right ┐
            draw.line([(target_w - c_margin, c_margin), (target_w - c_margin - c_len, c_margin)], fill=corner_color, width=c_thick)
            draw.line([(target_w - c_margin, c_margin), (target_w - c_margin, c_margin + c_len)], fill=corner_color, width=c_thick)
            # Bottom-Left └
            draw.line([(c_margin, target_h - c_margin), (c_margin + c_len, target_h - c_margin)], fill=corner_color, width=c_thick)
            draw.line([(c_margin, target_h - c_margin), (c_margin, target_h - c_margin - c_len)], fill=corner_color, width=c_thick)
            # Bottom-Right ┘
            draw.line([(target_w - c_margin, target_h - c_margin), (target_w - c_margin - c_len, target_h - c_margin)], fill=corner_color, width=c_thick)
            draw.line([(target_w - c_margin, target_h - c_margin), (target_w - c_margin, target_h - c_margin - c_len)], fill=corner_color, width=c_thick)

        # 4. Top-Right Corner Logo (Medium Size ~160px)
        logo_size = 160
        margin_right = 65
        margin_top = 45
        logo_cx = target_w - margin_right - logo_size // 2
        logo_cy = margin_top + logo_size // 2

        # Fallback logo if not specified
        effective_logo = server_logo_path
        if not effective_logo or not os.path.exists(effective_logo):
            for candidate in glob.glob(os.path.join(BASE_DIR, "server_logo_*.png")) + [os.path.join(BASE_DIR, "tournament_bot_logo.png")]:
                if os.path.exists(candidate):
                    effective_logo = candidate
                    break

        if effective_logo and os.path.exists(effective_logo):
            try:
                # Ambient cyan/blue outer glow halo
                glow_radius = logo_size // 2 + 20
                glow_layer = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
                glow_draw = ImageDraw.Draw(glow_layer)
                glow_draw.ellipse(
                    [(logo_cx - glow_radius, logo_cy - glow_radius), (logo_cx + glow_radius, logo_cy + glow_radius)],
                    fill=(0, 210, 255, 80)
                )
                glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(16))
                bg = Image.alpha_composite(bg, glow_layer)
                draw = ImageDraw.Draw(bg)

                with Image.open(effective_logo) as s_logo:
                    s_logo = s_logo.convert('RGBA')
                    s_logo = s_logo.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

                    c_mask = Image.new('L', (logo_size * 2, logo_size * 2), 0)
                    c_draw = ImageDraw.Draw(c_mask)
                    c_draw.ellipse((0, 0, logo_size * 2, logo_size * 2), fill=255)
                    c_mask = c_mask.resize((logo_size, logo_size), Image.Resampling.LANCZOS)

                    logo_x = logo_cx - logo_size // 2
                    logo_y = logo_cy - logo_size // 2
                    bg.paste(s_logo, (logo_x, logo_y), c_mask)

                    draw.ellipse(
                        [(logo_x - 2, logo_y - 2), (logo_x + logo_size + 2, logo_y + logo_size + 2)],
                        outline=(0, 220, 255, 230),
                        width=3
                    )
            except Exception as e:
                print(f"Error drawing logo: {e}")

        # 5. Tournament Title (Upper Centered Header)
        raw_title = tournament_title if tournament_title else server_name
        title_text = str(raw_title).strip().upper()
        init_title_size = 58 if use_spotlight_layer else 64
        font_title = get_font_with_fallbacks("Rajdhani", init_title_size, "bold")
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_w = title_bbox[2] - title_bbox[0]
        title_h = title_bbox[3] - title_bbox[1]

        current_title_size = init_title_size
        while title_w > 1350 and current_title_size > 28:
            current_title_size -= 2
            font_title = get_font_with_fallbacks("Rajdhani", current_title_size, "bold")
            title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
            title_w = title_bbox[2] - title_bbox[0]
            title_h = title_bbox[3] - title_bbox[1]

        title_x = (target_w - title_w) // 2
        title_y = 90 if use_spotlight_layer else 100

        top_title_col = (255, 110, 115, 255)
        bot_title_col = (255, 195, 95, 255)
        draw_gradient_text(bg, title_text, font_title, (title_x, title_y), top_title_col, bot_title_col, shadow=True, shadow_offset=(2, 4), shadow_color=(0, 0, 0, 220))
        draw = ImageDraw.Draw(bg)

        # 6. Group / Round Pill Capsule
        raw_capsule = str(round_label or "ROUND 1").strip().upper()
        if "•" not in raw_capsule and "-" in raw_capsule:
            capsule_text = raw_capsule.replace("-", " • ")
        elif "ROUND" not in raw_capsule:
            capsule_text = f"ROUND {raw_capsule}"
        else:
            capsule_text = raw_capsule

        font_capsule = get_font_with_fallbacks("Rajdhani", 24 if use_spotlight_layer else 26, "bold")
        cap_bbox = draw.textbbox((0, 0), capsule_text, font=font_capsule)
        cap_tw = cap_bbox[2] - cap_bbox[0]
        cap_th = cap_bbox[3] - cap_bbox[1]

        cap_pad_x = 32 if use_spotlight_layer else 36
        cap_h = 38 if use_spotlight_layer else 44
        cap_w = cap_tw + cap_pad_x * 2
        cap_x0 = (target_w - cap_w) // 2
        cap_y0 = title_y + title_h + 26
        cap_x1 = cap_x0 + cap_w
        cap_y1 = cap_y0 + cap_h

        pill_layer = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
        pill_draw = ImageDraw.Draw(pill_layer)
        pill_draw.rounded_rectangle([(cap_x0, cap_y0), (cap_x1, cap_y1)], radius=cap_h // 2, fill=(12, 18, 30, 225), outline=(0, 210, 255, 180) if use_spotlight_layer else (200, 165, 110, 180), width=2)
        bg = Image.alpha_composite(bg, pill_layer)
        draw = ImageDraw.Draw(bg)

        cap_tx = (target_w - cap_tw) // 2
        cap_ty = cap_y0 + (cap_h - cap_th) // 2 - 2
        draw.text((cap_tx, cap_ty), capsule_text, font=font_capsule, fill=(245, 240, 230, 255))

        # 7. Versus Middle Block (Player 1  /  VS  /  Player 2)
        t1_clean = sanitize_username_for_poster(team1_name).upper()
        t2_clean = sanitize_username_for_poster(team2_name).upper()

        if use_spotlight_layer:
            # Spotlight Layout: Left Spotlight (x=450) and Right Spotlight (x=1460)
            # The 3D metallic VS and light slash are already present in Thumbnail Layer.png!
            font_names = get_font_with_fallbacks("Rajdhani", 76, "bold")
            font_tag = get_font_with_fallbacks("Rajdhani", 22, "bold")

            # Fit team names inside spotlight width (~520px max)
            name_size = 76
            t1_b = draw.textbbox((0, 0), t1_clean, font=font_names)
            t2_b = draw.textbbox((0, 0), t2_clean, font=font_names)
            while ((t1_b[2] - t1_b[0]) > 520 or (t2_b[2] - t2_b[0]) > 520) and name_size > 28:
                name_size -= 2
                font_names = get_font_with_fallbacks("Rajdhani", name_size, "bold")
                t1_b = draw.textbbox((0, 0), t1_clean, font=font_names)
                t2_b = draw.textbbox((0, 0), t2_clean, font=font_names)

            t1_w, t1_h = t1_b[2] - t1_b[0], t1_b[3] - t1_b[1]
            t2_w, t2_h = t2_b[2] - t2_b[0], t2_b[3] - t2_b[1]

            t1_cx = 450
            t2_cx = 1460
            vs_cy = 515

            t1_x = t1_cx - t1_w // 2
            t1_y = vs_cy - t1_h // 2
            t2_x = t2_cx - t2_w // 2
            t2_y = vs_cy - t2_h // 2

            # Team 1 Tag & Name under Left Spotlight
            tag1 = "TEAM ALPHA"
            tb1 = draw.textbbox((0, 0), tag1, font=font_tag)
            draw.text((t1_cx - (tb1[2] - tb1[0]) // 2, t1_y - 36), tag1, font=font_tag, fill=(0, 220, 255, 230))
            draw.text((t1_x + 3, t1_y + 4), t1_clean, font=font_names, fill=(0, 0, 0, 220))
            draw.text((t1_x, t1_y), t1_clean, font=font_names, fill=(255, 255, 255, 255))

            # Team 2 Tag & Name under Right Spotlight
            tag2 = "TEAM BRAVO"
            tb2 = draw.textbbox((0, 0), tag2, font=font_tag)
            draw.text((t2_cx - (tb2[2] - tb2[0]) // 2, t2_y - 36), tag2, font=font_tag, fill=(255, 185, 75, 230))
            draw.text((t2_x + 3, t2_y + 4), t2_clean, font=font_names, fill=(0, 0, 0, 220))
            draw.text((t2_x, t2_y), t2_clean, font=font_names, fill=(255, 255, 255, 255))


        else:
            # Standard procedural VS and slashes layout
            vs_center_y = 510
            font_vs = get_font_with_fallbacks("Rajdhani", 125, "bold")
            font_names = get_font_with_fallbacks("Rajdhani", 72, "bold")

            vs_text = "VS"
            vs_bbox = draw.textbbox((0, 0), vs_text, font=font_vs)
            vs_w = vs_bbox[2] - vs_bbox[0]
            vs_h = vs_bbox[3] - vs_bbox[1]
            vs_x = (target_w - vs_w) // 2
            vs_y = vs_center_y - vs_h // 2 - 12

            t1_bbox = draw.textbbox((0, 0), t1_clean, font=font_names)
            t2_bbox = draw.textbbox((0, 0), t2_clean, font=font_names)
            t1_w = t1_bbox[2] - t1_bbox[0]
            t2_w = t2_bbox[2] - t2_bbox[0]

            name_size = 72
            while (t1_w > 560 or t2_w > 560) and name_size > 28:
                name_size -= 2
                font_names = get_font_with_fallbacks("Rajdhani", name_size, "bold")
                t1_bbox = draw.textbbox((0, 0), t1_clean, font=font_names)
                t2_bbox = draw.textbbox((0, 0), t2_clean, font=font_names)
                t1_w = t1_bbox[2] - t1_bbox[0]
                t2_w = t2_bbox[2] - t2_bbox[0]

            slash_gap = 26
            slash_h = 75

            left_slash_x = vs_x - slash_gap
            right_slash_x = vs_x + vs_w + slash_gap

            t1_x = left_slash_x - slash_gap - t1_w
            t1_y = vs_center_y - (t1_bbox[3] - t1_bbox[1]) // 2 - 8

            t2_x = right_slash_x + slash_gap
            t2_y = vs_center_y - (t2_bbox[3] - t2_bbox[1]) // 2 - 8

            # Draw Player 1 Name
            draw.text((t1_x + 3, t1_y + 3), t1_clean, font=font_names, fill=(0, 0, 0, 180))
            draw.text((t1_x, t1_y), t1_clean, font=font_names, fill=(255, 255, 255, 255))

            # Team 1 glowing underline fading to left
            t1_line_y = vs_center_y + 44
            for lx in range(int(t1_x), int(t1_x + t1_w)):
                prog = (lx - t1_x) / max(1, t1_w)
                alpha = int(220 * prog)
                draw.line([(lx, t1_line_y), (lx, t1_line_y + 2)], fill=(255, 110, 110, alpha))

            # Draw Player 2 Name
            draw.text((t2_x + 3, t2_y + 3), t2_clean, font=font_names, fill=(0, 0, 0, 180))
            draw.text((t2_x, t2_y), t2_clean, font=font_names, fill=(255, 255, 255, 255))

            # Team 2 glowing underline fading to right
            t2_line_y = vs_center_y + 44
            for lx in range(int(t2_x), int(t2_x + t2_w)):
                prog = 1.0 - ((lx - t2_x) / max(1, t2_w))
                alpha = int(220 * prog)
                draw.line([(lx, t2_line_y), (lx, t2_line_y + 2)], fill=(255, 185, 75, alpha))

            # Slashes: Both leaning forward `/` with gradient
            slash_layer = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
            slash_draw = ImageDraw.Draw(slash_layer)

            sy_top = vs_center_y - slash_h // 2
            sy_bot = vs_center_y + slash_h // 2

            slash_draw.line([(left_slash_x - 12, sy_bot), (left_slash_x + 12, sy_top)], fill=(255, 130, 95, 240), width=4)
            slash_draw.line([(right_slash_x - 12, sy_bot), (right_slash_x + 12, sy_top)], fill=(255, 185, 80, 240), width=4)

            bg = Image.alpha_composite(bg, slash_layer)
            draw = ImageDraw.Draw(bg)

            # VS Text
            top_vs_col = (255, 115, 105, 255)
            bot_vs_col = (255, 195, 70, 255)
            draw_gradient_text(bg, vs_text, font_vs, (vs_x, vs_y), top_vs_col, bot_vs_col, shadow=True, shadow_offset=(3, 5), shadow_color=(0, 0, 0, 240))
            draw = ImageDraw.Draw(bg)

        # 8. Bottom Info Section
        if use_spotlight_layer:
            # Clean Aligned Bottom Timing Section (NO BOX - Big, high-impact esports typography)
            col_cx = [450, 960, 1460]
            bot_y = 818
            div1_x = int((col_cx[0] + col_cx[1]) / 2)  # 705
            div2_x = int((col_cx[1] + col_cx[2]) / 2)  # 1210

            div_y_top = bot_y - 8
            div_y_bot = bot_y + 88
            for dx in [div1_x, div2_x]:
                for dy in range(div_y_top, div_y_bot):
                    prog = math.sin((dy - div_y_top) / (div_y_bot - div_y_top) * math.pi)
                    alpha = int(120 * prog)
                    draw.line([(dx, dy), (dx, dy)], fill=(255, 255, 255, alpha), width=1)

            font_hud_label = get_font_with_fallbacks("Rajdhani", 24, "bold")
            font_hud_val = get_font_with_fallbacks("Rajdhani", 46, "bold")
            font_hud_server = get_font_with_fallbacks("Rajdhani", 34, "bold")

            # Column 1: DATE (aligned under Left Spotlight at x=450)
            lbl_date = "DATE"
            val_date = format_display_date(date_str)
            b_l1 = draw.textbbox((0, 0), lbl_date, font=font_hud_label)
            b_v1 = draw.textbbox((0, 0), val_date, font=font_hud_val)
            draw.text((col_cx[0] - (b_l1[2] - b_l1[0]) // 2, bot_y), lbl_date, font=font_hud_label, fill=(0, 215, 255, 230))
            draw.text((col_cx[0] - (b_v1[2] - b_v1[0]) // 2 + 3, bot_y + 32 + 3), val_date, font=font_hud_val, fill=(0, 0, 0, 230))
            draw.text((col_cx[0] - (b_v1[2] - b_v1[0]) // 2, bot_y + 32), val_date, font=font_hud_val, fill=(255, 255, 255, 255))

            # Column 2: TIME (aligned under Center VS at x=960)
            lbl_time = "TIME"
            raw_time = str(utc_time or "00:00 UTC").strip().upper()
            val_time = raw_time if "UTC" in raw_time or "GMT" in raw_time else f"{raw_time} UTC"
            b_l2 = draw.textbbox((0, 0), lbl_time, font=font_hud_label)
            b_v2 = draw.textbbox((0, 0), val_time, font=font_hud_val)
            draw.text((col_cx[1] - (b_l2[2] - b_l2[0]) // 2, bot_y), lbl_time, font=font_hud_label, fill=(0, 215, 255, 230))
            draw.text((col_cx[1] - (b_v2[2] - b_v2[0]) // 2 + 3, bot_y + 32 + 3), val_time, font=font_hud_val, fill=(0, 0, 0, 230))
            draw.text((col_cx[1] - (b_v2[2] - b_v2[0]) // 2, bot_y + 32), val_time, font=font_hud_val, fill=(255, 255, 255, 255))

            # Column 3: SERVER (aligned under Right Spotlight at x=1460)
            lbl_server = "SERVER"
            val_server = str(server_name or "OFFICIAL SERVER").upper().strip()
            b_l3 = draw.textbbox((0, 0), lbl_server, font=font_hud_label)
            b_v3 = draw.textbbox((0, 0), val_server, font=font_hud_server)
            max_server_w = 420
            curr_s_font = font_hud_server
            if (b_v3[2] - b_v3[0]) > max_server_w:
                while (b_v3[2] - b_v3[0]) > max_server_w and len(val_server) > 8:
                    val_server = val_server[:-4] + "..."
                    b_v3 = draw.textbbox((0, 0), val_server, font=curr_s_font)

            draw.text((col_cx[2] - (b_l3[2] - b_l3[0]) // 2, bot_y), lbl_server, font=font_hud_label, fill=(0, 215, 255, 230))
            draw.text((col_cx[2] - (b_v3[2] - b_v3[0]) // 2 + 3, bot_y + 36 + 3), val_server, font=font_hud_server, fill=(0, 0, 0, 230))
            draw.text((col_cx[2] - (b_v3[2] - b_v3[0]) // 2, bot_y + 36), val_server, font=font_hud_server, fill=(255, 255, 255, 255))

        else:
            # Fallback legacy boxed card for templates without spotlights
            card_w = 980
            card_h = 145
            card_x0 = (target_w - card_w) // 2
            card_y0 = 745
            card_x1 = card_x0 + card_w
            card_y1 = card_y0 + card_h

            card_surface = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
            c_draw = ImageDraw.Draw(card_surface)
            c_draw.rounded_rectangle([(card_x0, card_y0), (card_x1, card_y1)], radius=20, fill=(12, 18, 30, 215))

            border_mask = Image.new('L', (target_w, target_h), 0)
            b_draw = ImageDraw.Draw(border_mask)
            b_draw.rounded_rectangle([(card_x0, card_y0), (card_x1, card_y1)], radius=20, outline=255, width=2)

            border_grad = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
            bg_draw = ImageDraw.Draw(border_grad)
            for gx in range(card_x0, card_x1):
                f = (gx - card_x0) / max(1, card_w)
                r = int(255 * (1 - f) + 245 * f)
                g = int(90 * (1 - f) + 195 * f)
                b = int(140 * (1 - f) + 90 * f)
                bg_draw.line([(gx, card_y0), (gx, card_y1)], fill=(r, g, b, 190))

            card_surface.paste(border_grad, (0, 0), border_mask)
            bg = Image.alpha_composite(bg, card_surface)
            draw = ImageDraw.Draw(bg)

            col_w = card_w // 3
            div1_x = card_x0 + col_w
            div2_x = card_x0 + col_w * 2

            div_y_pad = 22
            for dy in range(card_y0 + div_y_pad, card_y1 - div_y_pad):
                factor = math.sin((dy - (card_y0 + div_y_pad)) / (card_h - div_y_pad * 2) * math.pi)
                alpha = int(90 * factor)
                draw.line([(div1_x, dy), (div1_x, dy)], fill=(255, 255, 255, alpha))
                draw.line([(div2_x, dy), (div2_x, dy)], fill=(255, 255, 255, alpha))

            font_hud_label = get_font_with_fallbacks("Rajdhani", 19, "bold")
            font_hud_val = get_font_with_fallbacks("Rajdhani", 28, "bold")
            font_hud_server = get_font_with_fallbacks("Rajdhani", 23, "bold")

            # Column 1: DATE
            col1_cx = card_x0 + col_w // 2
            lbl_date = "DATE"
            b_l1 = draw.textbbox((0, 0), lbl_date, font=font_hud_label)
            draw.text((col1_cx - (b_l1[2] - b_l1[0]) // 2, card_y0 + 30), lbl_date, font=font_hud_label, fill=(160, 175, 195, 255))

            val_date = format_display_date(date_str)
            b_v1 = draw.textbbox((0, 0), val_date, font=font_hud_val)
            draw.text((col1_cx - (b_v1[2] - b_v1[0]) // 2, card_y0 + 72), val_date, font=font_hud_val, fill=(255, 255, 255, 255))

            # Column 2: TIME
            col2_cx = card_x0 + col_w + col_w // 2
            lbl_time = "TIME"
            b_l2 = draw.textbbox((0, 0), lbl_time, font=font_hud_label)
            draw.text((col2_cx - (b_l2[2] - b_l2[0]) // 2, card_y0 + 30), lbl_time, font=font_hud_label, fill=(160, 175, 195, 255))

            raw_time = str(utc_time or "00:00 UTC").strip().upper()
            val_time = raw_time if "UTC" in raw_time or "GMT" in raw_time else f"{raw_time} UTC"
            b_v2 = draw.textbbox((0, 0), val_time, font=font_hud_val)
            draw.text((col2_cx - (b_v2[2] - b_v2[0]) // 2, card_y0 + 72), val_time, font=font_hud_val, fill=(255, 255, 255, 255))

            # Column 3: SERVER
            col3_cx = card_x0 + col_w * 2 + col_w // 2
            lbl_server = "SERVER"
            b_l3 = draw.textbbox((0, 0), lbl_server, font=font_hud_label)
            draw.text((col3_cx - (b_l3[2] - b_l3[0]) // 2, card_y0 + 30), lbl_server, font=font_hud_label, fill=(160, 175, 195, 255))

            val_server = str(server_name or "OFFICIAL SERVER").upper().strip()
            b_v3 = draw.textbbox((0, 0), val_server, font=font_hud_server)
            max_server_w = col_w - 40
            curr_s_font = font_hud_server
            if (b_v3[2] - b_v3[0]) > max_server_w:
                while (b_v3[2] - b_v3[0]) > max_server_w and len(val_server) > 8:
                    val_server = val_server[:-4] + "..."
                    b_v3 = draw.textbbox((0, 0), val_server, font=curr_s_font)

            draw.text((col3_cx - (b_v3[2] - b_v3[0]) // 2, card_y0 + 74), val_server, font=curr_s_font, fill=(255, 255, 255, 255))

        # Save generated poster to temp file
        output_path = os.path.join(BASE_DIR, f"temp_poster_{int(datetime.datetime.now().timestamp())}.png")
        bg = bg.convert('RGB')
        bg.save(output_path, "PNG")
        return output_path

    except Exception as e:
        print(f"Critical error creating esports poster: {e}")
        return None

def create_event_poster(
    template_path: str, 
    round_label: str, 
    team1_captain: str, 
    team2_captain: str, 
    utc_time: str, 
    date_str: str = None, 
    server_name: str = "Tournament Organizer",
    server_logo_path: Optional[str] = None,
    tournament_title: Optional[str] = None
) -> Optional[str]:
    """Backward-compatible wrapper routing directly to modern esports match poster generator."""
    return create_esports_match_poster(
        template_path=template_path,
        round_label=round_label,
        team1_name=team1_captain,
        team2_name=team2_captain,
        utc_time=utc_time,
        date_str=date_str,
        server_name=server_name,
        server_logo_path=server_logo_path,
        tournament_title=tournament_title
    )


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
