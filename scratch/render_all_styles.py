import os
import sys
import math
import shutil
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(BASE_DIR, "Fonts")

def load_font(family: str, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    fam = family.lower()
    paths = []
    if "capture" in fam:
        paths.append(os.path.join(FONTS_DIR, "capture_it", "Capture it.ttf"))
    elif "ds" in fam or "digital" in fam:
        paths.extend([
            os.path.join(FONTS_DIR, "ds_digital", "DS-DIGIB.TTF"),
            os.path.join(FONTS_DIR, "ds_digital", "DS-DIGI.TTF")
        ])
    elif "geoform" in fam:
        paths.extend([
            os.path.join(FONTS_DIR, "geoform", "Geoform-Bold.otf"),
            os.path.join(FONTS_DIR, "geoform", "Geoform.otf")
        ])
    elif "square" in fam:
        paths.extend([
            os.path.join(FONTS_DIR, "square_one_2", "Square One Bold.ttf"),
            os.path.join(FONTS_DIR, "square_one_2", "Square One.ttf")
        ])
    else:  # default rajdhani
        paths.extend([
            os.path.join(FONTS_DIR, "rajdhani", "Rajdhani-Bold.ttf"),
            os.path.join(FONTS_DIR, "rajdhani", "Rajdhani-SemiBold.ttf")
        ])
        
    paths.extend([
        os.path.join(FONTS_DIR, "rajdhani", "Rajdhani-Bold.ttf"),
        os.path.join(FONTS_DIR, "geoform", "Geoform-Bold.otf"),
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf"
    ])
    
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def draw_outlined_text(draw: ImageDraw.Draw, xy: tuple, text: str, font, fill: tuple, outline_fill: tuple, outline_width: int = 3):
    x, y = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_fill)
    draw.text((x, y), text, font=font, fill=fill)

def get_base_crop(template_path: str, target_w: int = 1920, target_h: int = 1080) -> Image.Image:
    with Image.open(template_path) as raw:
        bg = raw.convert('RGBA')
        bw, bh = bg.size
        scale = max(target_w / bw, target_h / bh)
        new_bw = int(bw * scale)
        new_bh = int(bh * scale)
        bg = bg.resize((new_bw, new_bh), Image.Resampling.LANCZOS)
        crop_x = (new_bw - target_w) // 2
        crop_y = (new_bh - target_h) // 2
        return bg.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))

def paste_circular_logo(canvas: Image.Image, logo_path: str, center_xy: tuple, size: int = 100, border_color: tuple = (255, 255, 255, 220), border_width: int = 3):
    if not logo_path or not os.path.exists(logo_path):
        return
    cx, cy = center_xy
    try:
        with Image.open(logo_path) as logo_raw:
            logo = logo_raw.convert('RGBA')
            logo = logo.resize((size, size), Image.Resampling.LANCZOS)
            
            mask = Image.new('L', (size * 2, size * 2), 0)
            m_draw = ImageDraw.Draw(mask)
            m_draw.ellipse((0, 0, size * 2, size * 2), fill=255)
            mask = mask.resize((size, size), Image.Resampling.LANCZOS)
            
            x0 = cx - size // 2
            y0 = cy - size // 2
            canvas.paste(logo, (x0, y0), mask)
            
            if border_width > 0:
                draw = ImageDraw.Draw(canvas)
                draw.ellipse([(x0, y0), (x0 + size, y0 + size)], outline=border_color, width=border_width)
    except Exception as e:
        print(f"Error drawing logo: {e}")


# ===========================================================================================
# OPTION 1: MODERN TACTICAL / STEEL VANGUARD (Naval Esports & Modern Warships)
# ===========================================================================================
def render_option1_tactical(template_path, logo_path, title, round_str, team1, team2, date_str, time_str, server_str):
    w, h = 1920, 1080
    bg = get_base_crop(template_path, w, h)
    
    # 1. Vignette & subtle edge darkening for contrast
    vignette = Image.new('RGBA', (w, h), (8, 12, 20, 105))
    bg = Image.alpha_composite(bg, vignette)
    
    fade = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    f_draw = ImageDraw.Draw(fade)
    for y in range(240):
        a = int(140 * (1.0 - y / 240))
        f_draw.line([(0, y), (w, y)], fill=(4, 8, 14, a))
    for y in range(820, h):
        a = int(165 * ((y - 820) / (h - 820)))
        f_draw.line([(0, y), (w, y)], fill=(4, 8, 14, a))
    bg = Image.alpha_composite(bg, fade)
    draw = ImageDraw.Draw(bg)
    
    # 2. Header: Logo + Title + Chevron Round Tag
    logo_size = 96
    paste_circular_logo(bg, logo_path, (w // 2, 78), size=logo_size, border_color=(235, 185, 80, 240), border_width=3)
    draw = ImageDraw.Draw(bg)
    
    font_title = load_font("geoform", 54, bold=True)
    t_bbox = draw.textbbox((0, 0), title, font=font_title)
    tw = t_bbox[2] - t_bbox[0]
    draw_outlined_text(draw, ((w - tw) // 2, 142), title, font_title, fill=(255, 255, 255, 255), outline_fill=(5, 10, 18, 255), outline_width=3)
    
    # Round: Tactical Chevron Badge
    font_round = load_font("rajdhani", 22, bold=True)
    round_text = f"//  {round_str.upper()}  //"
    r_bbox = draw.textbbox((0, 0), round_text, font=font_round)
    rw, rh = r_bbox[2] - r_bbox[0], r_bbox[3] - r_bbox[1]
    
    badge_w = rw + 44
    badge_h = 36
    bx0 = (w - badge_w) // 2
    by0 = 215
    bx1 = bx0 + badge_w
    by1 = by0 + badge_h
    
    badge_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(badge_layer)
    b_draw.rectangle([(bx0, by0), (bx1, by1)], fill=(16, 22, 35, 230), outline=(225, 180, 75, 220), width=2)
    # Corner cuts
    cut = 7
    b_draw.polygon([(bx0, by0), (bx0 + cut, by0), (bx0, by0 + cut)], fill=(225, 180, 75, 255))
    b_draw.polygon([(bx1, by1), (bx1 - cut, by1), (bx1, by1 - cut)], fill=(225, 180, 75, 255))
    bg = Image.alpha_composite(bg, badge_layer)
    draw = ImageDraw.Draw(bg)
    
    draw.text((bx0 + (badge_w - rw) // 2, by0 + (badge_h - rh) // 2 - 2), round_text, font=font_round, fill=(245, 215, 120, 255))
    
    # 3. Main Center: Balanced Symmetric Tactical Team Plates
    vs_cy = 505
    font_vs = load_font("geoform", 64, bold=True)
    vs_text = "VS"
    v_bbox = draw.textbbox((0, 0), vs_text, font=font_vs)
    vw, vh = v_bbox[2] - v_bbox[0], v_bbox[3] - v_bbox[1]
    
    font_name = load_font("geoform", 58, bold=True)
    t1_b = draw.textbbox((0, 0), team1, font=font_name)
    t2_b = draw.textbbox((0, 0), team2, font=font_name)
    t1_w = t1_b[2] - t1_b[0]
    t2_w = t2_b[2] - t2_b[0]
    
    name_size = 58
    while (t1_w > 540 or t2_w > 540) and name_size > 24:
        name_size -= 2
        font_name = load_font("geoform", name_size, bold=True)
        t1_b = draw.textbbox((0, 0), team1, font=font_name)
        t2_b = draw.textbbox((0, 0), team2, font=font_name)
        t1_w = t1_b[2] - t1_b[0]
        t2_w = t2_b[2] - t2_b[0]
        
    plate_w = max(480, max(t1_w, t2_w) + 80)
    plate_h = 84
    gap_from_center = 75
    
    # Team 1 Plate (Left)
    p1_x1 = (w // 2) - gap_from_center
    p1_x0 = p1_x1 - plate_w
    p1_y0 = vs_cy - plate_h // 2
    p1_y1 = p1_y0 + plate_h
    
    # Team 2 Plate (Right)
    p2_x0 = (w // 2) + gap_from_center
    p2_x1 = p2_x0 + plate_w
    p2_y0 = vs_cy - plate_h // 2
    p2_y1 = p2_y0 + plate_h
    
    plates_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(plates_layer)
    # Slate backing
    p_draw.rectangle([(p1_x0, p1_y0), (p1_x1, p1_y1)], fill=(14, 18, 30, 225), outline=(55, 70, 98, 180), width=2)
    p_draw.rectangle([(p1_x0, p1_y0), (p1_x0 + 7, p1_y1)], fill=(240, 70, 70, 255))
    
    p_draw.rectangle([(p2_x0, p2_y0), (p2_x1, p2_y1)], fill=(14, 18, 30, 225), outline=(55, 70, 98, 180), width=2)
    p_draw.rectangle([(p2_x1 - 7, p2_y0), (p2_x1, p2_y1)], fill=(40, 180, 250, 255))
    
    # VS Center Shield
    vs_shield_w = 90
    vs_shield_h = 76
    vs_sx0 = (w - vs_shield_w) // 2
    vs_sy0 = vs_cy - vs_shield_h // 2
    p_draw.rectangle([(vs_sx0, vs_sy0), (vs_sx0 + vs_shield_w, vs_sy0 + vs_shield_h)], fill=(18, 24, 38, 240), outline=(225, 180, 75, 220), width=2)
    
    bg = Image.alpha_composite(bg, plates_layer)
    draw = ImageDraw.Draw(bg)
    
    # Names centered within their respective plates
    t1_x = p1_x0 + (plate_w - t1_w) // 2
    t1_y = vs_cy - (t1_b[3] - t1_b[1]) // 2 - 4
    draw.text((t1_x + 2, t1_y + 2), team1, font=font_name, fill=(0, 0, 0, 220))
    draw.text((t1_x, t1_y), team1, font=font_name, fill=(255, 255, 255, 255))
    
    t2_x = p2_x0 + (plate_w - t2_w) // 2
    t2_y = vs_cy - (t2_b[3] - t2_b[1]) // 2 - 4
    draw.text((t2_x + 2, t2_y + 2), team2, font=font_name, fill=(0, 0, 0, 220))
    draw.text((t2_x, t2_y), team2, font=font_name, fill=(255, 255, 255, 255))
    
    # VS text
    vx = (w - vw) // 2
    vy = vs_cy - vh // 2 - 5
    draw_outlined_text(draw, (vx, vy), vs_text, font_vs, fill=(255, 210, 80, 255), outline_fill=(0, 0, 0, 240), outline_width=3)
    
    # 4. Match Details Card (Low-Profile Steel HUD Bar)
    bar_w = 1140
    bar_h = 105
    bar_x0 = (w - bar_w) // 2
    bar_y0 = 785
    bar_x1 = bar_x0 + bar_w
    bar_y1 = bar_y0 + bar_h
    
    hud_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    h_draw = ImageDraw.Draw(hud_layer)
    h_draw.rectangle([(bar_x0, bar_y0), (bar_x1, bar_y1)], fill=(12, 16, 26, 235), outline=(190, 155, 80, 190), width=2)
    
    cm = 10
    h_draw.line([(bar_x0, bar_y0 + cm), (bar_x0 + cm, bar_y0)], fill=(255, 210, 90, 255), width=2)
    h_draw.line([(bar_x1 - cm, bar_y0), (bar_x1, bar_y0 + cm)], fill=(255, 210, 90, 255), width=2)
    h_draw.line([(bar_x0, bar_y1 - cm), (bar_x0 + cm, bar_y1)], fill=(255, 210, 90, 255), width=2)
    h_draw.line([(bar_x1 - cm, bar_y1), (bar_x1, bar_y1 - cm)], fill=(255, 210, 90, 255), width=2)
    
    col_w = bar_w // 3
    div1_x = bar_x0 + col_w
    div2_x = bar_x0 + col_w * 2
    h_draw.line([(div1_x, bar_y0 + 16), (div1_x, bar_y1 - 16)], fill=(55, 70, 95, 200), width=2)
    h_draw.line([(div2_x, bar_y0 + 16), (div2_x, bar_y1 - 16)], fill=(55, 70, 95, 200), width=2)
    bg = Image.alpha_composite(bg, hud_layer)
    draw = ImageDraw.Draw(bg)
    
    font_lbl = load_font("rajdhani", 18, bold=True)
    font_val = load_font("geoform", 23, bold=True)
    
    # Col 1: DATE
    cx1 = bar_x0 + col_w // 2
    b1_lbl = draw.textbbox((0, 0), "DATE", font=font_lbl)
    draw.text((cx1 - (b1_lbl[2] - b1_lbl[0]) // 2, bar_y0 + 18), "DATE", font=font_lbl, fill=(155, 175, 200, 255))
    b1_val = draw.textbbox((0, 0), date_str, font=font_val)
    draw.text((cx1 - (b1_val[2] - b1_val[0]) // 2, bar_y0 + 52), date_str, font=font_val, fill=(255, 255, 255, 255))
    
    # Col 2: TIME
    cx2 = bar_x0 + col_w + col_w // 2
    b2_lbl = draw.textbbox((0, 0), "TIME", font=font_lbl)
    draw.text((cx2 - (b2_lbl[2] - b2_lbl[0]) // 2, bar_y0 + 18), "TIME", font=font_lbl, fill=(155, 175, 200, 255))
    b2_val = draw.textbbox((0, 0), time_str, font=font_val)
    draw.text((cx2 - (b2_val[2] - b2_val[0]) // 2, bar_y0 + 52), time_str, font=font_val, fill=(255, 255, 255, 255))
    
    # Col 3: SERVER
    cx3 = bar_x0 + col_w * 2 + col_w // 2
    b3_lbl = draw.textbbox((0, 0), "SERVER", font=font_lbl)
    draw.text((cx3 - (b3_lbl[2] - b3_lbl[0]) // 2, bar_y0 + 18), "SERVER", font=font_lbl, fill=(155, 175, 200, 255))
    b3_val = draw.textbbox((0, 0), server_str, font=font_val)
    draw.text((cx3 - (b3_val[2] - b3_val[0]) // 2, bar_y0 + 52), server_str, font=font_val, fill=(255, 255, 255, 255))
    
    return bg.convert('RGB')


# ===========================================================================================
# OPTION 2: CLEAN ARENA BROADCAST (Tier-1 Esports / VCT / BLAST Style)
# ===========================================================================================
def render_option2_broadcast(template_path, logo_path, title, round_str, team1, team2, date_str, time_str, server_str):
    w, h = 1920, 1080
    bg = get_base_crop(template_path, w, h)
    
    overlay = Image.new('RGBA', (w, h), (6, 10, 18, 125))
    bg = Image.alpha_composite(bg, overlay)
    draw = ImageDraw.Draw(bg)
    
    # 1. Header: Logo + Broadcast Tag + Title + Pill
    logo_size = 90
    paste_circular_logo(bg, logo_path, (w // 2, 80), size=logo_size, border_color=(255, 255, 255, 200), border_width=2)
    draw = ImageDraw.Draw(bg)
    
    font_sub = load_font("rajdhani", 19, bold=True)
    sub_text = "OFFICIAL TOURNAMENT BROADCAST"
    sb = draw.textbbox((0, 0), sub_text, font=font_sub)
    draw.text(((w - (sb[2] - sb[0])) // 2, 142), sub_text, font=font_sub, fill=(175, 190, 210, 240))
    
    font_title = load_font("rajdhani", 54, bold=True)
    tb = draw.textbbox((0, 0), title, font=font_title)
    tw = tb[2] - tb[0]
    draw.text(((w - tw) // 2 + 2, 175 + 2), title, font=font_title, fill=(0, 0, 0, 220))
    draw.text(((w - tw) // 2, 175), title, font=font_title, fill=(255, 255, 255, 255))
    
    font_round = load_font("rajdhani", 22, bold=True)
    r_text = round_str.upper()
    rb = draw.textbbox((0, 0), r_text, font=font_round)
    rw, rh = rb[2] - rb[0], rb[3] - rb[1]
    pw, ph = rw + 38, 36
    px0 = (w - pw) // 2
    py0 = 245
    pill_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill_layer)
    p_draw.rounded_rectangle([(px0, py0), (px0 + pw, py0 + ph)], radius=18, fill=(18, 25, 40, 220), outline=(255, 255, 255, 110), width=1)
    bg = Image.alpha_composite(bg, pill_layer)
    draw = ImageDraw.Draw(bg)
    draw.text((px0 + (pw - rw) // 2, py0 + (ph - rh) // 2 - 2), r_text, font=font_round, fill=(240, 245, 255, 255))
    
    # 2. Center Versus Block (Floating with Symmetrical Balance)
    vs_cy = 510
    font_vs = load_font("rajdhani", 85, bold=True)
    vs_text = "VS"
    vb = draw.textbbox((0, 0), vs_text, font=font_vs)
    vw, vh = vb[2] - vb[0], vb[3] - vb[1]
    
    font_name = load_font("rajdhani", 74, bold=True)
    t1_b = draw.textbbox((0, 0), team1, font=font_name)
    t2_b = draw.textbbox((0, 0), team2, font=font_name)
    t1_w = t1_b[2] - t1_b[0]
    t2_w = t2_b[2] - t2_b[0]
    
    name_size = 74
    while (t1_w > 560 or t2_w > 560) and name_size > 28:
        name_size -= 2
        font_name = load_font("rajdhani", name_size, bold=True)
        t1_b = draw.textbbox((0, 0), team1, font=font_name)
        t2_b = draw.textbbox((0, 0), team2, font=font_name)
        t1_w = t1_b[2] - t1_b[0]
        t2_w = t2_b[2] - t2_b[0]
        
    center_gap = 65
    t1_x = (w // 2) - center_gap - t1_w
    t1_y = vs_cy - (t1_b[3] - t1_b[1]) // 2 - 6
    
    t2_x = (w // 2) + center_gap
    t2_y = vs_cy - (t2_b[3] - t2_b[1]) // 2 - 6
    
    for off in [(2, 2), (4, 4), (0, 3), (3, 0)]:
        draw.text((t1_x + off[0], t1_y + off[1]), team1, font=font_name, fill=(0, 0, 0, 200))
        draw.text((t2_x + off[0], t2_y + off[1]), team2, font=font_name, fill=(0, 0, 0, 200))
    draw.text((t1_x, t1_y), team1, font=font_name, fill=(255, 255, 255, 255))
    draw.text((t2_x, t2_y), team2, font=font_name, fill=(255, 255, 255, 255))
    
    # Broadcast baseline accent bars
    draw.line([(t1_x + t1_w - 110, vs_cy + 44), (t1_x + t1_w, vs_cy + 44)], fill=(245, 80, 80, 240), width=4)
    draw.line([(t2_x, vs_cy + 44), (t2_x + 110, vs_cy + 44)], fill=(60, 180, 255, 240), width=4)
    
    # VS Center
    vx = (w - vw) // 2
    vy = vs_cy - vh // 2 - 10
    draw.text((vx + 3, vy + 3), vs_text, font=font_vs, fill=(0, 0, 0, 220))
    draw.text((vx, vy), vs_text, font=font_vs, fill=(255, 195, 75, 255))
    
    # 3. Lower Third Broadcast Banner
    banner_w = 1220
    banner_h = 96
    bx0 = (w - banner_w) // 2
    by0 = 800
    bx1 = bx0 + banner_w
    by1 = by0 + banner_h
    
    b_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    b_draw = ImageDraw.Draw(b_layer)
    b_draw.rounded_rectangle([(bx0, by0), (bx1, by1)], radius=14, fill=(10, 14, 24, 220), outline=(50, 65, 90, 180), width=1)
    
    col_w = banner_w // 3
    d1 = bx0 + col_w
    d2 = bx0 + col_w * 2
    b_draw.line([(d1, by0 + 16), (d1, by1 - 16)], fill=(255, 255, 255, 45), width=1)
    b_draw.line([(d2, by0 + 16), (d2, by1 - 16)], fill=(255, 255, 255, 45), width=1)
    bg = Image.alpha_composite(bg, b_layer)
    draw = ImageDraw.Draw(bg)
    
    font_blbl = load_font("rajdhani", 18, bold=True)
    font_bval = load_font("rajdhani", 28, bold=True)
    
    # Col 1: DATE
    cx1 = bx0 + col_w // 2
    l1 = draw.textbbox((0, 0), "MATCH DATE", font=font_blbl)
    draw.text((cx1 - (l1[2] - l1[0]) // 2, by0 + 18), "MATCH DATE", font=font_blbl, fill=(150, 170, 195, 255))
    v1 = draw.textbbox((0, 0), date_str, font=font_bval)
    draw.text((cx1 - (v1[2] - v1[0]) // 2, by0 + 48), date_str, font=font_bval, fill=(255, 255, 255, 255))
    
    # Col 2: TIME
    cx2 = bx0 + col_w + col_w // 2
    l2 = draw.textbbox((0, 0), "MATCH TIME", font=font_blbl)
    draw.text((cx2 - (l2[2] - l2[0]) // 2, by0 + 18), "MATCH TIME", font=font_blbl, fill=(150, 170, 195, 255))
    v2 = draw.textbbox((0, 0), time_str, font=font_bval)
    draw.text((cx2 - (v2[2] - v2[0]) // 2, by0 + 48), time_str, font=font_bval, fill=(255, 255, 255, 255))
    
    # Col 3: SERVER
    cx3 = bx0 + col_w * 2 + col_w // 2
    l3 = draw.textbbox((0, 0), "SERVER HOST", font=font_blbl)
    draw.text((cx3 - (l3[2] - l3[0]) // 2, by0 + 18), "SERVER HOST", font=font_blbl, fill=(150, 170, 195, 255))
    v3 = draw.textbbox((0, 0), server_str, font=font_bval)
    draw.text((cx3 - (v3[2] - v3[0]) // 2, by0 + 48), server_str, font=font_bval, fill=(255, 255, 255, 255))
    
    return bg.convert('RGB')


# ===========================================================================================
# OPTION 3: CLASSIC LEGACY ENHANCED (Original Tourney Master Style Remastered in 1080p)
# ===========================================================================================
def render_option3_classic(template_path, logo_path, title, round_str, team1, team2, date_str, time_str, server_str):
    w, h = 1920, 1080
    bg = get_base_crop(template_path, w, h)
    
    dark = Image.new('RGBA', (w, h), (0, 0, 0, 75))
    bg = Image.alpha_composite(bg, dark)
    draw = ImageDraw.Draw(bg)
    
    # 1. Server / Tournament Title at Top (Capture it Font with thick black outline)
    font_title = load_font("capture", 76, bold=True)
    tb = draw.textbbox((0, 0), title, font=font_title)
    tw = tb[2] - tb[0]
    draw_outlined_text(draw, ((w - tw) // 2, 95), title, font_title, fill=(255, 255, 255, 255), outline_fill=(0, 0, 0, 255), outline_width=5)
    
    # 2. Round in Big Yellow (Capture It)
    font_round = load_font("capture", 62, bold=True)
    round_full = round_str.upper()
    rb = draw.textbbox((0, 0), round_full, font=font_round)
    rw = rb[2] - rb[0]
    draw_outlined_text(draw, ((w - rw) // 2, 260), round_full, font_round, fill=(255, 225, 0, 255), outline_fill=(0, 0, 0, 255), outline_width=5)
    
    # 3. Main Center Line: Team 1  VS  Team 2 (All aligned horizontally)
    font_vs = load_font("capture", 68, bold=True)
    
    t1_text = team1.upper()
    vs_text = " VS "
    t2_text = team2.upper()
    
    b1 = draw.textbbox((0, 0), t1_text, font=font_vs)
    bv = draw.textbbox((0, 0), vs_text, font=font_vs)
    b2 = draw.textbbox((0, 0), t2_text, font=font_vs)
    
    w1 = b1[2] - b1[0]
    wv = bv[2] - bv[0]
    w2 = b2[2] - b2[0]
    
    total_w = w1 + wv + w2
    vs_size = 68
    while total_w > 1650 and vs_size > 28:
        vs_size -= 2
        font_vs = load_font("capture", vs_size, bold=True)
        b1 = draw.textbbox((0, 0), t1_text, font=font_vs)
        bv = draw.textbbox((0, 0), vs_text, font=font_vs)
        b2 = draw.textbbox((0, 0), t2_text, font=font_vs)
        w1 = b1[2] - b1[0]
        wv = bv[2] - bv[0]
        w2 = b2[2] - b2[0]
        total_w = w1 + wv + w2
        
    start_x = (w - total_w) // 2
    center_y = 510
    
    draw_outlined_text(draw, (start_x, center_y), t1_text, font_vs, fill=(255, 255, 255, 255), outline_fill=(0, 0, 0, 255), outline_width=5)
    draw_outlined_text(draw, (start_x + w1, center_y), vs_text, font_vs, fill=(255, 215, 0, 255), outline_fill=(0, 0, 0, 255), outline_width=5)
    draw_outlined_text(draw, (start_x + w1 + wv, center_y), t2_text, font_vs, fill=(255, 255, 255, 255), outline_fill=(0, 0, 0, 255), outline_width=5)
    
    # 4. Classic Bottom Details (Date & Time in DS-Digital, Server in Capture It)
    font_digital = load_font("ds_digital", 52, bold=True)
    
    d_text = f"DATE:  {date_str}"
    db = draw.textbbox((0, 0), d_text, font=font_digital)
    dw = db[2] - db[0]
    draw_outlined_text(draw, ((w - dw) // 2, 730), d_text, font_digital, fill=(255, 255, 255, 255), outline_fill=(0, 0, 0, 255), outline_width=4)
    
    t_text = f"TIME:  {time_str}"
    tb2 = draw.textbbox((0, 0), t_text, font=font_digital)
    tw2 = tb2[2] - tb2[0]
    draw_outlined_text(draw, ((w - tw2) // 2, 815), t_text, font_digital, fill=(255, 255, 255, 255), outline_fill=(0, 0, 0, 255), outline_width=4)
    
    font_srv = load_font("capture", 36, bold=True)
    s_text = f"SERVER:  {server_str}"
    sb = draw.textbbox((0, 0), s_text, font=font_srv)
    sw = sb[2] - sb[0]
    draw_outlined_text(draw, ((w - sw) // 2, 905), s_text, font_srv, fill=(255, 225, 0, 255), outline_fill=(0, 0, 0, 255), outline_width=4)
    
    return bg.convert('RGB')


# ===========================================================================================
# OPTION 4: DARK NEO-MINIMALIST (Ultra-Sleek Modern Esports)
# ===========================================================================================
def render_option4_minimal(template_path, logo_path, title, round_str, team1, team2, date_str, time_str, server_str):
    w, h = 1920, 1080
    bg = get_base_crop(template_path, w, h)
    
    matte = Image.new('RGBA', (w, h), (8, 12, 18, 135))
    bg = Image.alpha_composite(bg, matte)
    draw = ImageDraw.Draw(bg)
    
    # 1. Header: Minimal Emblem + Title
    logo_size = 80
    paste_circular_logo(bg, logo_path, (w // 2, 80), size=logo_size, border_color=(255, 255, 255, 160), border_width=2)
    draw = ImageDraw.Draw(bg)
    
    font_title = load_font("rajdhani", 46, bold=True)
    tb = draw.textbbox((0, 0), title, font=font_title)
    tw = tb[2] - tb[0]
    draw.text(((w - tw) // 2, 140), title, font=font_title, fill=(255, 255, 255, 255))
    
    font_round = load_font("rajdhani", 20, bold=True)
    r_text = f"—  {round_str.upper()}  —"
    rb = draw.textbbox((0, 0), r_text, font=font_round)
    rw = rb[2] - rb[0]
    draw.text(((w - rw) // 2, 195), r_text, font=font_round, fill=(185, 195, 210, 230))
    
    # 2. Main Minimal Center Block
    vs_cy = 495
    font_name = load_font("rajdhani", 70, bold=True)
    t1_b = draw.textbbox((0, 0), team1, font=font_name)
    t2_b = draw.textbbox((0, 0), team2, font=font_name)
    t1_w = t1_b[2] - t1_b[0]
    t2_w = t2_b[2] - t2_b[0]
    
    name_size = 70
    while (t1_w > 560 or t2_w > 560) and name_size > 26:
        name_size -= 2
        font_name = load_font("rajdhani", name_size, bold=True)
        t1_b = draw.textbbox((0, 0), team1, font=font_name)
        t2_b = draw.textbbox((0, 0), team2, font=font_name)
        t1_w = t1_b[2] - t1_b[0]
        t2_w = t2_b[2] - t2_b[0]
        
    center_space = 80
    t1_x = (w // 2) - center_space - t1_w
    t1_y = vs_cy - (t1_b[3] - t1_b[1]) // 2 - 4
    
    t2_x = (w // 2) + center_space
    t2_y = vs_cy - (t2_b[3] - t2_b[1]) // 2 - 4
    
    draw.text((t1_x + 2, t1_y + 2), team1, font=font_name, fill=(0, 0, 0, 180))
    draw.text((t1_x, t1_y), team1, font=font_name, fill=(255, 255, 255, 255))
    
    draw.text((t2_x + 2, t2_y + 2), team2, font=font_name, fill=(0, 0, 0, 180))
    draw.text((t2_x, t2_y), team2, font=font_name, fill=(255, 255, 255, 255))
    
    # Thin divider + circle VS badge
    div_layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d_draw = ImageDraw.Draw(div_layer)
    d_draw.line([(w // 2, vs_cy - 70), (w // 2, vs_cy + 70)], fill=(255, 255, 255, 60), width=1)
    
    cr = 28
    d_draw.ellipse([(w // 2 - cr, vs_cy - cr), (w // 2 + cr, vs_cy + cr)], fill=(20, 24, 32, 240), outline=(255, 255, 255, 120), width=2)
    bg = Image.alpha_composite(bg, div_layer)
    draw = ImageDraw.Draw(bg)
    
    font_vs = load_font("rajdhani", 24, bold=True)
    vb = draw.textbbox((0, 0), "VS", font=font_vs)
    draw.text((w // 2 - (vb[2] - vb[0]) // 2, vs_cy - (vb[3] - vb[1]) // 2 - 2), "VS", font=font_vs, fill=(255, 255, 255, 255))
    
    # 3. Floating Bottom Info Strip
    font_meta = load_font("rajdhani", 26, bold=True)
    meta_text = f"DATE: {date_str}   •   TIME: {time_str}   •   SERVER: {server_str}"
    mb = draw.textbbox((0, 0), meta_text, font=font_meta)
    mw, mh = mb[2] - mb[0], mb[3] - mb[1]
    
    pw, ph = mw + 60, 50
    px0 = (w - pw) // 2
    py0 = 820
    pill = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    p_draw = ImageDraw.Draw(pill)
    p_draw.rounded_rectangle([(px0, py0), (px0 + pw, py0 + ph)], radius=25, fill=(15, 18, 25, 220), outline=(255, 255, 255, 60), width=1)
    bg = Image.alpha_composite(bg, pill)
    draw = ImageDraw.Draw(bg)
    
    draw.text((px0 + (pw - mw) // 2, py0 + (ph - mh) // 2 - 2), meta_text, font=font_meta, fill=(230, 235, 245, 255))
    
    return bg.convert('RGB')


if __name__ == "__main__":
    template = os.path.join(BASE_DIR, "Templates", "Modern Warship", "MW_bundle_e2_eventpassbundlemwwg24_0.75_1920x1080.png")
    logo = os.path.join(BASE_DIR, "server_logo_1084589736917737522.png")
    if not os.path.exists(logo):
        logo = os.path.join(BASE_DIR, "tournament_bot_logo.png")
        
    title = "THE LEE SHORE"
    round_str = "ROUND 3"
    team1 = "SUKAMIEGORENG"
    team2 = "MADARA8_0"
    date_str = "MONDAY, 14-09-26"
    time_str = "12:00 UTC"
    server_str = "FANPLAY MALAYSIA"
    
    scratch_dir = os.path.join(BASE_DIR, "scratch")
    os.makedirs(scratch_dir, exist_ok=True)
    
    artifact_dir = r"C:\Users\Sivap\.gemini\antigravity-ide\brain\41ac2cb9-0ec0-4593-9ac8-a5c64b450f51"
    
    print("Generating Option 1 on SeaBrotherhood...")
    img1 = render_option1_tactical(template, logo, title, round_str, team1, team2, date_str, time_str, server_str)
    out1 = os.path.join(scratch_dir, "option1_tactical.png")
    img1.save(out1, "PNG")
    if os.path.exists(artifact_dir):
        shutil.copy(out1, os.path.join(artifact_dir, "option1_tactical.png"))
        
    print("Generating Option 2 on SeaBrotherhood...")
    img2 = render_option2_broadcast(template, logo, title, round_str, team1, team2, date_str, time_str, server_str)
    out2 = os.path.join(scratch_dir, "option2_broadcast.png")
    img2.save(out2, "PNG")
    if os.path.exists(artifact_dir):
        shutil.copy(out2, os.path.join(artifact_dir, "option2_broadcast.png"))
        
    print("Generating Option 3 on SeaBrotherhood...")
    img3 = render_option3_classic(template, logo, title, round_str, team1, team2, date_str, time_str, server_str)
    out3 = os.path.join(scratch_dir, "option3_classic.png")
    img3.save(out3, "PNG")
    if os.path.exists(artifact_dir):
        shutil.copy(out3, os.path.join(artifact_dir, "option3_classic.png"))
        
    print("Generating Option 4 on SeaBrotherhood...")
    img4 = render_option4_minimal(template, logo, title, round_str, team1, team2, date_str, time_str, server_str)
    out4 = os.path.join(scratch_dir, "option4_minimal.png")
    img4.save(out4, "PNG")
    if os.path.exists(artifact_dir):
        shutil.copy(out4, os.path.join(artifact_dir, "option4_minimal.png"))
        
    print("ALL 4 ON EXACT SEABROTHERHOOD GENERATED SUCCESSFULLY!")
