import os
import sys
sys.path.insert(0, os.path.abspath("."))
user_site = os.path.expanduser(r"~\AppData\Roaming\Python\Python311\site-packages")
if os.path.exists(user_site) and user_site not in sys.path:
    sys.path.insert(0, user_site)

from core.image_generator import create_esports_match_poster, create_event_poster, get_random_template

template = get_random_template("Modern Warship")
print(f"Selected template: {template}")

poster = create_esports_match_poster(
    template_path=template,
    round_label="GROUP B • ROUND 3",
    team1_name="TEASAN21",
    team2_name="HOKAGE_141",
    utc_time="04:00 UTC",
    date_str="13/09/2026",
    server_name="ETERNAL ESPORTS ASIA",
    tournament_title="ETERNAL FRIGATE CHAMPIONSHIP S3"
)
print(f"Esports poster created at: {poster}")
assert poster and os.path.exists(poster), "Poster file does not exist!"
print("Verification passed successfully!")
