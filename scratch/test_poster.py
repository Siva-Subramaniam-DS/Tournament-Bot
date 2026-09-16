import os
import sys
sys.path.insert(0, os.path.abspath("."))
import shutil

from core.image_generator import create_esports_match_poster, get_thumbnail_layer_path

thumb_path = get_thumbnail_layer_path()
print(f"Thumbnail Layer Path: {thumb_path}")

out = create_esports_match_poster(
    template_path=thumb_path,
    round_label="GROUP B • ROUND 3",
    team1_name="TEASAN21",
    team2_name="HOKAGE_141",
    utc_time="04:00 UTC",
    date_str="15/09/2026",
    server_name="ETERNAL ESPORTS ASIA",
    tournament_title="ETERNAL FRIGATE CHAMPIONSHIP S3"
)

print(f"Generated: {out}")
if out and os.path.exists(out):
    dest = "sample_thumbnail.png"
    shutil.copyfile(out, dest)
    print(f"Copied to {dest}")
    curr_art_dir = r"C:\Users\Sivap\.gemini\antigravity-ide\brain\aa4c1123-4a62-41c1-be37-c9ca20097361\sample_thumbnail.png"
    shutil.copyfile(out, curr_art_dir)
    print("Copied to current artifact directory.")
