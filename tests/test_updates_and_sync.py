import unittest
import datetime
import sys
from unittest.mock import MagicMock

# Mock pytz if not installed
if 'pytz' not in sys.modules:
    try:
        import pytz
    except ImportError:
        mock_pytz = MagicMock()
        mock_pytz.UTC = datetime.timezone.utc
        mock_pytz.timezone.return_value = datetime.timezone.utc
        sys.modules['pytz'] = mock_pytz

# Mock discord if not installed
if 'discord' not in sys.modules:
    try:
        import discord
    except ImportError:
        mock_discord = MagicMock()
        class MockField:
            def __init__(self, name, value, inline=True):
                self.name = name
                self.value = value
                self.inline = inline

        class MockEmbed:
            def __init__(self, title="", description="", color=None, timestamp=None):
                self.title = title
                self.description = description
                self.color = color
                self.timestamp = timestamp
                self.fields = []
            def add_field(self, name, value, inline=True):
                self.fields.append(MockField(name, value, inline))
            def set_footer(self, text=None, icon_url=None):
                pass
            def set_thumbnail(self, url=None):
                pass

        mock_discord.Embed = MockEmbed
        mock_discord.Color = MagicMock()
        mock_discord.Color.green.return_value = 0x00FF00
        mock_discord.Color.gold.return_value = 0xFFD700
        mock_discord.Color.blue.return_value = 0x0000FF
        mock_discord.Color.red.return_value = 0xFF0000
        mock_discord.Color.orange.return_value = 0xFFA500
        mock_discord.utils = MagicMock()
        mock_discord.utils.utcnow.return_value = datetime.datetime.now(datetime.timezone.utc)
        mock_discord.app_commands = MagicMock()
        mock_discord.ext = MagicMock()
        mock_discord.ext.commands = MagicMock()
        sys.modules['discord'] = mock_discord
        sys.modules['discord.app_commands'] = mock_discord.app_commands
        sys.modules['discord.ext'] = mock_discord.ext
        sys.modules['discord.ext.commands'] = mock_discord.ext.commands
for mod in ['dotenv', 'requests', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'supabase']:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()
import pytz
import discord

from core.state import is_event_over, check_staff_schedule_conflict, scheduled_events
from core.database import format_links_markdown
from cogs.tournaments import create_match_room_embed
from cogs.settings import extract_player_fields, format_player_field_value, format_player_block_quote

class TestTournamentBotUpdates(unittest.TestCase):

    def setUp(self):
        scheduled_events.clear()

    def test_is_event_over_status(self):
        self.assertTrue(is_event_over({'status': 'completed'}))
        self.assertTrue(is_event_over({'status': 'closed'}))
        self.assertTrue(is_event_over({'status': 'finished'}))
        self.assertTrue(is_event_over({'results_message_id': '123456789'}))
        self.assertTrue(is_event_over({'winner_score': 2, 'loser_score': 0}))
        self.assertFalse(is_event_over({'status': 'scheduled'}))

    def test_is_event_over_datetime(self):
        past_dt = datetime.datetime.now(pytz.UTC) - datetime.timedelta(hours=5)
        future_dt = datetime.datetime.now(pytz.UTC) + datetime.timedelta(hours=2)
        self.assertTrue(is_event_over({'datetime': past_dt}))
        self.assertFalse(is_event_over({'datetime': future_dt}))

    def test_format_links_markdown(self):
        # Single link
        single = format_links_markdown("https://youtube.com/watch?v=123")
        self.assertEqual(single, "[Watch Here](https://youtube.com/watch?v=123)")

        # Multiple links (up to 5)
        multi_input = "https://link1.com, https://link2.com, https://link3.com"
        formatted = format_links_markdown(multi_input)
        self.assertEqual(formatted, "[Link1](https://link1.com), [Link2](https://link2.com), [Link3](https://link3.com)")

        # None / Empty
        self.assertEqual(format_links_markdown(""), "")

    def test_check_staff_schedule_conflict(self):
        guild_id = 12345
        user_id = 99999
        match_time = datetime.datetime(2026, 9, 17, 14, 0, tzinfo=pytz.UTC)

        scheduled_events["ev1"] = {
            'guild_id': guild_id,
            'match_name': 'Match A vs B',
            'datetime': match_time,
            'judge': user_id,
            'status': 'scheduled'
        }

        # 1. Exact same time -> Conflict!
        has_conflict, conf_ev = check_staff_schedule_conflict(guild_id, user_id, "ev2", match_time)
        self.assertTrue(has_conflict)
        self.assertEqual(conf_ev.get('match_name'), 'Match A vs B')

        # 2. Within 15 minutes -> Conflict!
        fifteen_mins_later = match_time + datetime.timedelta(minutes=15)
        has_conflict, _ = check_staff_schedule_conflict(guild_id, user_id, "ev2", fifteen_mins_later)
        self.assertTrue(has_conflict)

        # 3. 2 hours later -> No conflict
        two_hours_later = match_time + datetime.timedelta(hours=2)
        has_conflict, _ = check_staff_schedule_conflict(guild_id, user_id, "ev2", two_hours_later)
        self.assertFalse(has_conflict)

        # 4. Same event ID check -> No self-conflict
        has_conflict, _ = check_staff_schedule_conflict(guild_id, user_id, "ev1", match_time)
        self.assertFalse(has_conflict)

    def test_create_match_room_embed_game_name_and_id(self):
        guild = MagicMock()
        guild.name = "Test Guild"
        guild.icon = None

        ping_content, embed = create_match_room_embed(
            guild=guild,
            tournament_name="Grand Championship",
            team1_name="Team Alpha",
            team2_name="Team Beta",
            round_name="Finals",
            captain1_mention="<@111>",
            captain2_mention="<@222>",
            captain1_game_name="ShadowNinja",
            captain2_game_name="DragonSlayer",
            captain1_game_id="NINJA#999",
            captain2_game_id="DRAGON#123",
            org_name="Tournament Org"
        )

        field_values = "\n".join(f.value for f in embed.fields)

        self.assertIn("Game Name:", field_values)
        self.assertIn("Game ID:", field_values)
        self.assertIn("ShadowNinja", field_values)
        self.assertIn("NINJA#999", field_values)
        self.assertNotIn("Captain:", field_values)

    def test_extract_player_fields_discord_aliases(self):
        header = ["SL", "Discord", "Game Name", "Game ID", "Title"]
        row = ["1", "1046462446738980904", "ProGamer", "12345", "Challenger"]

        p_data = extract_player_fields(header, row, is_captain=True)
        self.assertEqual(p_data["discord_id"], "1046462446738980904")
        self.assertEqual(p_data["game_name"], "ProGamer")
        self.assertEqual(p_data["game_id"], "12345")

        val = format_player_field_value(p_data, is_captain=True)
        self.assertIn("<@1046462446738980904>", val)

if __name__ == '__main__':
    unittest.main()
