import os
import sys
user_site = os.path.expanduser(r"~\AppData\Roaming\Python\Python311\site-packages")
if os.path.exists(user_site) and user_site not in sys.path:
    sys.path.insert(0, user_site)
import math
import requests
import tempfile
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

BASE_DIR = r"c:\Users\Sivap\Documents\Discord Bots\Tournament Bot"

def download_google_font(font_family: str, font_weight: str = "700") -> str:
    try:
        api_url = f"https://fonts.googleapis.com/css2?family={font_family.replace(' ', '+')}:wght@{font_weight}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(api_url, headers=headers, timeout=10)
        res.raise_for_status()
        urls = re.findall(r'url\((https://[^)]+\.(?:ttf|woff2?))\)', res.text)
        if urls:
            font_res = requests.get(urls[0], timeout=15)
            font_res.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.ttf')
            tmp.write(font_res.content)
            tmp.close()
            return tmp.name
    except Exception as e:
        print(f"Failed to fetch {font_family}: {e}")
    return None

def get_font(font_name: str, size: int, style: str = "regular"):
    fonts_dir = os.path.join(BASE_DIR, "Fonts")
    if font_name == "Rajdhani":
        gf = download_google_font("Rajdhani", "700" if style == "bold" else "600")
        if gf and os.path.exists(gf):
            return ImageFont.truetype(gf, size)
    elif font_name == "Teko":
        gf = download_google_font("Teko", "700" if style == "bold" else "600")
        if gf and os.path.exists(gf):
            return ImageFont.truetype(gf, size)
    elif font_name == "Bebas Neue":
        gf = download_google_font("Bebas Neue", "400")
        if gf and os.path.exists(gf):
            return ImageFont.truetype(gf, size)
    elif font_name == "Geoform":
        p = os.path.join(fonts_dir, "geoform", "Geoform-Bold.otf" if style == "bold" else "Geoform.otf")
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    elif font_name == "Square One":
        p = os.path.join(fonts_dir, "square_one_2", "Square One Bold.ttf" if style == "bold" else "Square One.ttf")
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    elif font_name == "Capture it":
        p = os.path.join(fonts_dir, "capture_it", "Capture it.ttf")
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    
    for sys_font in ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arial.ttf"]:
        if os.path.exists(sys_font):
            return ImageFont.truetype(sys_font, size)
    return ImageFont.load_default()

def draw_vertical_gradient(width, height, top_color, bottom_color):
    """Generate a vertical 2-color gradient RGBA image."""
    base = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    for y in range(height):
        factor = y / max(1, height - 1)
        r = int(top_color[0] + factor * (bottom_color[0] - top_color[0]))
        g = int(top_color[1] + factor * (bottom_color[1] - top_color[1]))
        b = int(top_color[2] + factor * (bottom_color[2] - top_color[2]))
        a = int(top_color[3] + factor * (bottom_color[3] - top_color[3])) if len(top_color) > 3 else 255
        draw.line([(0, y), (width, y)], fill=(r, g, b, a))
    return base

def draw_gradient_text(canvas: Image.Image, text: str, font: ImageFont.FreeTypeFont, xy: tuple, top_color: tuple, bottom_color: tuple, shadow=True, shadow_offset=(3, 4), shadow_color=(0, 0, 0, 180), anchor=None):
    """Render text with a smooth vertical linear gradient and optional soft drop shadow."""
    x, y = xy
    dummy = Image.new('RGBA', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy)
    bbox = dummy_draw.textbbox((0, 0), text, font=font, anchor=anchor)
    w = max(1, bbox[2] - bbox[0])
    h = max(1, bbox[3] - bbox[1])
    
    pad = 10
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

def create_esports_thumbnail(
    template_path: str,
    tournament_title: str,
    round_label: str,
    team1_name: str,
    team2_name: str,
    match_date: str,
    match_time: str,
    server_info: str,
    server_logo_path: str = None,
    output_path: str = "esports_thumbnail_test.png"
):
    target_w, target_h = 1920, 1080
    
    # 1. Base background: load and cover crop to 1920x1080
    with Image.open(template_path) as bg:
        bg = bg.convert('RGBA')
        bw, bh = bg.size
        scale = max(target_w / bw, target_h / bh)
        new_bw = int(bw * scale)
        new_bh = int(bh * scale)
        bg = bg.resize((new_bw, new_bh), Image.Resampling.LANCZOS)
        crop_x = (new_bw - target_w) // 2
        crop_y = (new_bh - target_h) // 2
        bg = bg.crop((crop_x, crop_y, crop_x + target_w, crop_y + target_h))
    
    # 2. Add cinematic vignette & darkening overlay
    dark_overlay = Image.new('RGBA', (target_w, target_h), (5, 8, 16, 115))
    bg = Image.alpha_composite(bg, dark_overlay)
    
    # Top & bottom subtle gradient darkness
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

    # 3. Corner Brackets [ ]
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

    # 4. Top Centered Logo
    logo_size = 110
    logo_cx = target_w // 2
    logo_cy = 88
    
    glow_radius = logo_size // 2 + 16
    glow_layer = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.ellipse(
        [(logo_cx - glow_radius, logo_cy - glow_radius), (logo_cx + glow_radius, logo_cy + glow_radius)],
        fill=(0, 210, 255, 60)
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(12))
    bg = Image.alpha_composite(bg, glow_layer)
    draw = ImageDraw.Draw(bg)

    if server_logo_path and os.path.exists(server_logo_path):
        try:
            with Image.open(server_logo_path) as s_logo:
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

    # 5. Tournament Title (Below Logo)
    font_title = get_font("Rajdhani", 64, "bold")
    title_text = str(tournament_title).strip().upper()
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_w = title_bbox[2] - title_bbox[0]
    
    current_title_size = 64
    while title_w > 1500 and current_title_size > 30:
        current_title_size -= 2
        font_title = get_font("Rajdhani", current_title_size, "bold")
        title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
        title_w = title_bbox[2] - title_bbox[0]

    title_x = (target_w - title_w) // 2
    title_y = 160
    
    top_title_col = (255, 110, 115, 255)
    bot_title_col = (255, 195, 95, 255)
    draw_gradient_text(bg, title_text, font_title, (title_x, title_y), top_title_col, bot_title_col, shadow=True, shadow_offset=(2, 4), shadow_color=(0, 0, 0, 220))
    draw = ImageDraw.Draw(bg)

    # 6. Group / Round Pill Capsule
    capsule_text = str(round_label).strip().upper()
    font_capsule = get_font("Rajdhani", 26, "bold")
    cap_bbox = draw.textbbox((0, 0), capsule_text, font=font_capsule)
    cap_tw = cap_bbox[2] - cap_bbox[0]
    cap_th = cap_bbox[3] - cap_bbox[1]
    
    cap_pad_x = 36
    cap_h = 44
    cap_w = cap_tw + cap_pad_x * 2
    cap_x0 = (target_w - cap_w) // 2
    cap_y0 = 244
    cap_x1 = cap_x0 + cap_w
    cap_y1 = cap_y0 + cap_h
    
    pill_layer = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))
    pill_draw = ImageDraw.Draw(pill_layer)
    pill_draw.rounded_rectangle([(cap_x0, cap_y0), (cap_x1, cap_y1)], radius=22, fill=(16, 22, 34, 220), outline=(200, 165, 110, 180), width=2)
    bg = Image.alpha_composite(bg, pill_layer)
    draw = ImageDraw.Draw(bg)
    
    cap_tx = (target_w - cap_tw) // 2
    cap_ty = cap_y0 + (cap_h - cap_th) // 2 - 2
    draw.text((cap_tx, cap_ty), capsule_text, font=font_capsule, fill=(245, 240, 230, 255))

    # 7. Versus Middle Block (Player 1  /  VS  /  Player 2)
    vs_center_y = 510
    font_vs = get_font("Rajdhani", 125, "bold")
    font_names = get_font("Rajdhani", 72, "bold")
    
    vs_text = "VS"
    vs_bbox = draw.textbbox((0, 0), vs_text, font=font_vs)
    vs_w = vs_bbox[2] - vs_bbox[0]
    vs_h = vs_bbox[3] - vs_bbox[1]
    vs_x = (target_w - vs_w) // 2
    vs_y = vs_center_y - vs_h // 2 - 12
    
    t1_clean = str(team1_name).strip().upper()
    t2_clean = str(team2_name).strip().upper()
    
    t1_bbox = draw.textbbox((0, 0), t1_clean, font=font_names)
    t2_bbox = draw.textbbox((0, 0), t2_clean, font=font_names)
    t1_w = t1_bbox[2] - t1_bbox[0]
    t2_w = t2_bbox[2] - t2_bbox[0]
    
    name_size = 72
    while (t1_w > 560 or t2_w > 560) and name_size > 28:
        name_size -= 2
        font_names = get_font("Rajdhani", name_size, "bold")
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
    
    # Left slash `/`
    slash_draw.line([(left_slash_x - 12, sy_bot), (left_slash_x + 12, sy_top)], fill=(255, 130, 95, 240), width=4)
    # Right slash `/`
    slash_draw.line([(right_slash_x - 12, sy_bot), (right_slash_x + 12, sy_top)], fill=(255, 185, 80, 240), width=4)
    
    bg = Image.alpha_composite(bg, slash_layer)
    draw = ImageDraw.Draw(bg)

    # VS Text
    top_vs_col = (255, 115, 105, 255)
    bot_vs_col = (255, 195, 70, 255)
    draw_gradient_text(bg, vs_text, font_vs, (vs_x, vs_y), top_vs_col, bot_vs_col, shadow=True, shadow_offset=(3, 5), shadow_color=(0, 0, 0, 240))
    draw = ImageDraw.Draw(bg)

    # 8. Bottom Info Glassmorphic Card (DATE | TIME | SERVER)
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

    font_hud_label = get_font("Geoform", 19, "bold")
    font_hud_val = get_font("Geoform", 28, "bold")
    font_hud_server = get_font("Geoform", 23, "bold")

    # Column 1: DATE
    col1_cx = card_x0 + col_w // 2
    lbl_date = "DATE"
    b_l1 = draw.textbbox((0, 0), lbl_date, font=font_hud_label)
    draw.text((col1_cx - (b_l1[2] - b_l1[0]) // 2, card_y0 + 30), lbl_date, font=font_hud_label, fill=(160, 175, 195, 255))
    
    val_date = str(match_date).upper()
    b_v1 = draw.textbbox((0, 0), val_date, font=font_hud_val)
    draw.text((col1_cx - (b_v1[2] - b_v1[0]) // 2, card_y0 + 72), val_date, font=font_hud_val, fill=(255, 255, 255, 255))

    # Column 2: TIME
    col2_cx = card_x0 + col_w + col_w // 2
    lbl_time = "TIME"
    b_l2 = draw.textbbox((0, 0), lbl_time, font=font_hud_label)
    draw.text((col2_cx - (b_l2[2] - b_l2[0]) // 2, card_y0 + 30), lbl_time, font=font_hud_label, fill=(160, 175, 195, 255))
    
    val_time = str(match_time).upper()
    b_v2 = draw.textbbox((0, 0), val_time, font=font_hud_val)
    draw.text((col2_cx - (b_v2[2] - b_v2[0]) // 2, card_y0 + 72), val_time, font=font_hud_val, fill=(255, 255, 255, 255))

    # Column 3: SERVER
    col3_cx = card_x0 + col_w * 2 + col_w // 2
    lbl_server = "SERVER"
    b_l3 = draw.textbbox((0, 0), lbl_server, font=font_hud_label)
    draw.text((col3_cx - (b_l3[2] - b_l3[0]) // 2, card_y0 + 30), lbl_server, font=font_hud_label, fill=(160, 175, 195, 255))
    
    val_server = str(server_info).upper().strip()
    b_v3 = draw.textbbox((0, 0), val_server, font=font_hud_server)
    max_server_w = col_w - 40
    curr_s_font = font_hud_server
    if (b_v3[2] - b_v3[0]) > max_server_w:
        while (b_v3[2] - b_v3[0]) > max_server_w and len(val_server) > 8:
            val_server = val_server[:-4] + "..."
            b_v3 = draw.textbbox((0, 0), val_server, font=curr_s_font)
            
    draw.text((col3_cx - (b_v3[2] - b_v3[0]) // 2, card_y0 + 74), val_server, font=curr_s_font, fill=(255, 255, 255, 255))

    bg = bg.convert('RGB')
    bg.save(output_path, "JPEG", quality=95)
    print(f"Esports thumbnail generated successfully at {output_path}")
    return output_path

if __name__ == "__main__":
    template = os.path.join(BASE_DIR, "Templates", "Modern Warship", "101_1920x1080.jpg")
    logo = os.path.join(BASE_DIR, "server_logo_1084589736917737522.png")
    out = os.path.join(BASE_DIR, "scratch", "test_output.jpg")
    create_esports_thumbnail(
        template_path=template,
        tournament_title="ETERNAL FRIGATE CHAMPIONSHIP S3",
        round_label="GROUP B  •  ROUND 3",
        team1_name="TEASAN21",
        team2_name="HOKAGE_141",
        match_date="SUNDAY, 13-09-26",
        match_time="04:00 UTC",
        server_info="ETERNAL ESPORTS ASIA",
        server_logo_path=logo,
        output_path=out
    )
