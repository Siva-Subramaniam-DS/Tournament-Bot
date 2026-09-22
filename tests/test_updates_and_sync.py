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
            def clear_fields(self):
                self.fields.clear()
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
        class MockChoice:
            def __init__(self, name="", value=""):
                self.name = name
                self.value = value
            def __class_getitem__(cls, item):
                return cls
        class MockView:
            def __init__(self, timeout=180):
                self.timeout = timeout
                self.children = []
                for attr in dir(self.__class__):
                    val = getattr(self.__class__, attr, None)
                    if getattr(val, '__discord_ui_button__', False):
                        btn = MagicMock()
                        btn.custom_id = getattr(val, 'custom_id', attr)
                        btn.disabled = getattr(val, 'disabled', False)
                        btn.label = getattr(val, 'label', '')
                        btn.style = getattr(val, 'style', 1)
                        setattr(self, attr, btn)
                        self.children.append(btn)

        def mock_button(*args, **kwargs):
            def decorator(func):
                func.__discord_ui_button__ = True
                func.custom_id = kwargs.get('custom_id')
                func.disabled = kwargs.get('disabled', False)
                func.label = kwargs.get('label', '')
                func.style = kwargs.get('style', 1)
                return func
            return decorator

        mock_discord.ui = MagicMock()
        mock_discord.ui.View = MockView
        mock_discord.ui.button = mock_button
        mock_discord.ButtonStyle = MagicMock()
        mock_discord.ButtonStyle.primary = 1
        mock_discord.ButtonStyle.secondary = 2
        mock_discord.app_commands = MagicMock()
        mock_discord.app_commands.Choice = MockChoice
        mock_discord.ext = MagicMock()
        mock_discord.ext.commands = MagicMock()
        sys.modules['discord'] = mock_discord
        sys.modules['discord.ui'] = mock_discord.ui
        sys.modules['discord.app_commands'] = mock_discord.app_commands
        sys.modules['discord.ext'] = mock_discord.ext
        sys.modules['discord.ext.commands'] = mock_discord.ext.commands
import asyncio
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
        match_time = datetime.datetime.now(pytz.UTC) + datetime.timedelta(days=2)

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

    def test_staff_stats_type_safety_and_updates(self):
        from core.database import (
            get_guild_staff_stats, save_guild_staff_stats,
            update_staff_stats, decrement_staff_stats
        )
        import os, json

        guild_id = 888777666
        # Pre-populate stats with string and int values
        raw_stats = {
            "111": {
                "user_id": 111,
                "name": "JudgeOnly",
                "judge_count": "5",
                "recorder_count": "0",
                "judge_and_recorder_count": 0,
                "total_count": "5"
            },
            "222": {
                "user_id": 222,
                "name": "BothRoles",
                "judge_count": 0,
                "recorder_count": 0,
                "judge_and_recorder_count": "3",
                "total_count": "6"
            }
        }
        save_guild_staff_stats(guild_id, raw_stats)

        # 1. Verify get_guild_staff_stats parses strings to safe integers
        stats = get_guild_staff_stats(guild_id)
        self.assertIsInstance(stats["111"]["judge_count"], int)
        self.assertEqual(stats["111"]["judge_count"], 5)
        self.assertEqual(stats["111"]["total_count"], 5)
        self.assertIsInstance(stats["222"]["judge_and_recorder_count"], int)
        self.assertEqual(stats["222"]["judge_and_recorder_count"], 3)
        self.assertEqual(stats["222"]["total_count"], 6)

        # 2. Update staff stats for user 111 as recorder (should increment recorder_count)
        update_staff_stats(111, "recorder", guild_id=guild_id)
        stats = get_guild_staff_stats(guild_id)
        self.assertEqual(stats["111"]["recorder_count"], 1)
        self.assertEqual(stats["111"]["total_count"], 6)

        # 3. Update staff stats for user 333 as judge_and_recorder (both roles)
        update_staff_stats(333, "judge_and_recorder", guild_id=guild_id)
        stats = get_guild_staff_stats(guild_id)
        self.assertEqual(stats["333"]["judge_and_recorder_count"], 1)
        self.assertEqual(stats["333"]["total_count"], 1)

        # 4. Decrement staff stats for user 111
        decrement_staff_stats(111, "recorder", guild_id=guild_id)
        stats = get_guild_staff_stats(guild_id)
        self.assertEqual(stats["111"]["recorder_count"], 0)
        self.assertEqual(stats["111"]["total_count"], 5)

        # Clean up test artifact
        if os.path.exists('staff_stats.json'):
            try:
                with open('staff_stats.json', 'r', encoding='utf-8') as f:
                    all_stats = json.load(f)
                all_stats.pop(str(guild_id), None)
                with open('staff_stats.json', 'w', encoding='utf-8') as f:
                    json.dump(all_stats, f)
            except Exception:
                pass

    def test_link_choices_only_recorder_and_judge(self):
        # Inspect choices registered on app_commands.choices
        choice_calls = discord.app_commands.choices.call_args_list
        found_link_type_calls = 0
        for call in choice_calls:
            kwargs = call.kwargs or (call[1] if len(call) > 1 else {})
            if "link_type" in kwargs:
                found_link_type_calls += 1
                choices = kwargs["link_type"]
                choice_names = [getattr(c, 'name', str(c)) for c in choices]
                choice_values = [getattr(c, 'value', str(c)) for c in choices]
                # Must contain Recorder and Judge, and NOT General
                self.assertIn("recorder", choice_values)
                self.assertIn("judge", choice_values)
                self.assertNotIn("general", choice_values)
                for name in choice_names:
                    self.assertNotIn("general", name.lower())
        self.assertGreaterEqual(found_link_type_calls, 3)

    def test_supabase_time_not_overwriting_local_datetime(self):
        import asyncio
        from core.database import load_scheduled_events_from_supabase
        from core.state import scheduled_events

        future_dt = datetime.datetime.now(pytz.UTC) + datetime.timedelta(days=2)
        scheduled_events["test_match_time"] = {
            'guild_id': 12345,
            'match_name': 'Test vs Time',
            'datetime': future_dt,
            'status': 'scheduled'
        }

        # Mock supabase client query returning match without Scheduled_Time
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.execute.return_value.data = [
            {
                'id': 'test_match_time',
                'Match_ID': 'test_match_time',
                'Guild_ID': '12345',
                'Scheduled_Time': None,
                'Date': None,
                'Status': 'scheduled'
            }
        ]

        import core.database as db
        orig_sb = db.supabase_client
        db.supabase_client = mock_sb
        try:
            asyncio.run(load_scheduled_events_from_supabase())
            # Local valid datetime must NOT have been overwritten with datetime.now()!
            self.assertEqual(scheduled_events["test_match_time"]['datetime'], future_dt)
        finally:
            db.supabase_client = orig_sb
    def test_update_results_embed_with_links_formatting(self):
        from core.database import update_results_embed_with_links
        guild = MagicMock()
        guild.id = 12345
        channel = MagicMock()
        msg = MagicMock()
        
        embed = discord.Embed(title="🏆 Team A vs Team B")
        embed.add_field(name="👑 Captains", value="Captains text", inline=False)
        embed.add_field(name="🏆 Results", value="Results text", inline=False)
        embed.add_field(name="👥 Staffs", value="Staffs text", inline=False)
        embed.add_field(name="📝 Remarks", value="ggwp", inline=False)
        embed.add_field(name="📸 Screenshots of Result", value="SS-1", inline=False)
        msg.embeds = [embed]
        msg.edit_calls = []
        async def mock_fetch(msg_id):
            return msg
        async def mock_edit(**kwargs):
            msg.edit_calls.append(kwargs)
            return True
        channel.fetch_message = mock_fetch
        msg.edit = mock_edit
        guild.get_channel.return_value = channel

        ev_data = {
            'results_message_id': 999111,
            'results_channel_id': 888222,
            'recorder_link': 'https://youtube.com/watch?v=12345',
            'judge_link': 'https://youtube.com/watch?v=67890'
        }

        asyncio.run(update_results_embed_with_links(guild, ev_data))
        self.assertTrue(len(msg.edit_calls) > 0)
        edited_embed = msg.edit_calls[0]['embed']
        field_names = [f.name for f in edited_embed.fields]
        self.assertTrue(any("Recordings / VODs" in fn for fn in field_names))
        # Ensure Remarks is still in embed
        self.assertIn("📝 Remarks", field_names)

    def test_staff_work_tab_view_initialization(self):
        from cogs.staff import StaffWorkTabView
        embed_overview = discord.Embed(title="Overview")
        embed_judge = discord.Embed(title="Judges")
        embed_rec = discord.Embed(title="Recorders")
        embed_both = discord.Embed(title="Both")
        
        embeds_dict = {
            "overview": embed_overview,
            "judge": embed_judge,
            "recorder": embed_rec,
            "both": embed_both
        }
        view = StaffWorkTabView(12345678, embeds_dict, default_tab="overview")
        self.assertEqual(view.current_tab, "overview")
        self.assertEqual(len(view.children), 4)

    def test_staff_stats_hosting_sync_and_persistence(self):
        import os
        import json
        import asyncio
        from core.database import load_all_staff_stats_from_supabase, STAFF_STATS_CACHE, get_guild_staff_stats

        test_guild = 999888777
        test_user = "123456789"
        mock_data = {
            str(test_guild): {
                test_user: {
                    "name": "SuperStaff",
                    "judge_count": 7,
                    "recorder_count": 4,
                    "judge_and_recorder_count": 2,
                    "total_count": 13,
                    "last_active": "2026-09-22T07:00:00"
                }
            }
        }
        # Save mock data to staff_stats.json
        with open('staff_stats.json', 'w', encoding='utf-8') as f:
            json.dump(mock_data, f)

        try:
            # Run the sync function
            asyncio.run(load_all_staff_stats_from_supabase())
            
            # Verify cache has been populated from hosting database JSON
            stats = get_guild_staff_stats(test_guild)
            self.assertIn(test_user, stats)
            self.assertEqual(stats[test_user]["judge_count"], 7)
            self.assertEqual(stats[test_user]["recorder_count"], 4)
            self.assertEqual(stats[test_user]["judge_and_recorder_count"], 2)
            self.assertEqual(stats[test_user]["total_count"], 13)
        finally:
            # Clean up test entry
            if str(test_guild) in STAFF_STATS_CACHE:
                del STAFF_STATS_CACHE[str(test_guild)]
            with open('staff_stats.json', 'w', encoding='utf-8') as f:
                json.dump({}, f)

    def test_take_schedule_button_2min_cutoff(self):
        import pytz
        from cogs.staff import TakeScheduleButton
        from core.state import scheduled_events

        ev_id = "test_cutoff_event"
        now = datetime.datetime.now(pytz.UTC)

        # Case 1: Event in the future (not started)
        scheduled_events[ev_id] = {
            'datetime': now + datetime.timedelta(minutes=30),
            'judge': None,
            'recorder': None
        }
        view_future = TakeScheduleButton(ev_id, None, None)
        self.assertFalse(view_future._is_event_started())
        for child in view_future.children:
            if child.custom_id and "take_schedule" in child.custom_id:
                self.assertFalse(child.disabled)
                self.assertEqual(child.label, "Take Schedule")
            elif child.custom_id and "record" in child.custom_id:
                self.assertFalse(child.disabled)
                self.assertEqual(child.label, "Record")

        # Case 2: Event started 1 min ago (within 2-minute window)
        scheduled_events[ev_id]['datetime'] = now - datetime.timedelta(minutes=1)
        view_within_2m = TakeScheduleButton(ev_id, None, None)
        self.assertFalse(view_within_2m._is_event_started())

        # Case 3: Event started 3 mins ago (past 2-minute window) - Neither claimed
        scheduled_events[ev_id]['datetime'] = now - datetime.timedelta(minutes=3)
        view_past_cutoff = TakeScheduleButton(ev_id, None, None)
        self.assertTrue(view_past_cutoff._is_event_started())
        for child in view_past_cutoff.children:
            self.assertTrue(child.disabled)
            self.assertEqual(child.label, "Closed")

        # Case 4: Event started 3 mins ago - Judge was taken, but Record was not
        mock_judge = MagicMock()
        mock_judge.display_name = "JudgeUser"
        mock_judge.id = 111222
        scheduled_events[ev_id]['judge'] = mock_judge
        scheduled_events[ev_id]['recorder'] = None
        view_judge_taken = TakeScheduleButton(ev_id, None, None)
        for child in view_judge_taken.children:
            if child.custom_id and "take_schedule" in child.custom_id:
                self.assertTrue(child.disabled)
                self.assertEqual(child.label, "🙋 Assigned")
            elif child.custom_id and "record" in child.custom_id:
                self.assertTrue(child.disabled)
                self.assertEqual(child.label, "Closed")

        # Cleanup
        del scheduled_events[ev_id]

    def test_work_counted_only_on_result(self):
        from core.database import update_staff_stats, get_guild_staff_stats, STAFF_STATS_CACHE

        test_guild = 888777666
        STAFF_STATS_CACHE[str(test_guild)] = {}

        mock_user = MagicMock()
        mock_user.id = 555666
        mock_user.display_name = "JudgeWorker"

        # 1. Update stats for judge on result
        update_staff_stats(mock_user, "judge", test_guild)
        stats = get_guild_staff_stats(test_guild)
        self.assertEqual(stats[str(mock_user.id)]["judge_count"], 1)
        self.assertEqual(stats[str(mock_user.id)]["recorder_count"], 0)
        self.assertEqual(stats[str(mock_user.id)]["total_count"], 1)

        # 2. Update stats for recorder on result
        update_staff_stats(mock_user, "recorder", test_guild)
        stats = get_guild_staff_stats(test_guild)
        self.assertEqual(stats[str(mock_user.id)]["judge_count"], 1)
        self.assertEqual(stats[str(mock_user.id)]["recorder_count"], 1)
        self.assertEqual(stats[str(mock_user.id)]["total_count"], 2)

        # Cleanup
        if str(test_guild) in STAFF_STATS_CACHE:
            del STAFF_STATS_CACHE[str(test_guild)]

    def test_close_unassigned_schedule_buttons(self):
        import pytz
        import asyncio
        from core.state import scheduled_events
        from cogs.events import close_unassigned_schedule_buttons

        ev_id = "test_close_btns_event"
        now = datetime.datetime.now(pytz.UTC)
        scheduled_events[ev_id] = {
            'datetime': now - datetime.timedelta(minutes=5),
            'judge': None,
            'recorder': None,
            'schedule_channel_id': 12345,
            'schedule_message_id': 67890,
            'team1_captain': None,
            'team2_captain': None
        }

        guild = MagicMock()
        channel = MagicMock()
        msg = MagicMock()
        msg.edit_calls = []

        async def mock_fetch_msg(mid):
            return msg

        async def mock_edit(**kwargs):
            msg.edit_calls.append(kwargs)
            return True

        channel.fetch_message = mock_fetch_msg
        msg.edit = mock_edit
        guild.get_channel.return_value = channel

        asyncio.run(close_unassigned_schedule_buttons(ev_id, guild))
        self.assertEqual(len(msg.edit_calls), 1)
        edited_view = msg.edit_calls[0].get('view')
        self.assertIsNotNone(edited_view)
        for child in edited_view.children:
            self.assertTrue(child.disabled)
            self.assertEqual(child.label, "Closed")

        # Cleanup
        del scheduled_events[ev_id]

if __name__ == '__main__':
    unittest.main()



