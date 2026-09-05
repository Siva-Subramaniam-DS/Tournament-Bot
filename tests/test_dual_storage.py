import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import core.database as db

class TestDualStorage(unittest.TestCase):
    def setUp(self):
        self.test_guild_id = 999888777
        self.test_guild_str = str(self.test_guild_id)

    def test_guild_config_dual_storage(self):
        sample_cfg = db.get_default_config()
        sample_cfg['organization_name'] = "Test Organization"
        sample_cfg['role_ids']['judge'] = 111222333
        sample_cfg['channel_ids']['take_schedule'] = 444555666
        
        # Save config
        db.save_guild_config(self.test_guild_id, sample_cfg)
        
        # Check local JSON
        self.assertTrue(os.path.exists('guild_configs.json'))
        with open('guild_configs.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn(self.test_guild_str, data)
        self.assertEqual(data[self.test_guild_str]['organization_name'], "Test Organization")
        self.assertEqual(data[self.test_guild_str]['role_ids']['judge'], 111222333)
        self.assertEqual(data[self.test_guild_str]['channel_ids']['take_schedule'], 444555666)

    def test_player_and_team_dual_storage(self):
        # Test player
        p_entry = db.save_player_data(123456789, ign="ProPlayer99", game_id="UID_999", title="Champion")
        self.assertTrue(os.path.exists('players.json'))
        with open('players.json', 'r', encoding='utf-8') as f:
            players = json.load(f)
        self.assertIn("123456789", players)
        self.assertEqual(players["123456789"]["IGN"], "ProPlayer99")
        self.assertEqual(players["123456789"]["Game_ID"], "UID_999")
        self.assertEqual(players["123456789"]["Title"], "Champion")

        # Test team
        t_entry = db.save_team_data(123456789, team_name="Alpha Wolves", tournament_id="tourn_test_1")
        self.assertTrue(os.path.exists('teams.json'))
        with open('teams.json', 'r', encoding='utf-8') as f:
            teams = json.load(f)
        self.assertIn("123456789", teams)
        self.assertEqual(teams["123456789"]["Team_Name"], "Alpha Wolves")
        self.assertEqual(teams["123456789"]["Tournament_ID"], "tourn_test_1")

    def test_staff_stats_dual_storage(self):
        stats = {
            "555666777": {
                "name": "TestStaff",
                "judge_count": 5,
                "recorder_count": 3,
                "total_count": 8
            }
        }
        db.save_guild_staff_stats(self.test_guild_id, stats)
        self.assertTrue(os.path.exists('staff_stats.json'))
        with open('staff_stats.json', 'r', encoding='utf-8') as f:
            all_stats = json.load(f)
        self.assertIn(self.test_guild_str, all_stats)
        self.assertEqual(all_stats[self.test_guild_str]["555666777"]["judge_count"], 5)
        self.assertEqual(all_stats[self.test_guild_str]["555666777"]["recorder_count"], 3)
        self.assertEqual(all_stats[self.test_guild_str]["555666777"]["total_count"], 8)

    def test_scheduled_deadlines_dual_storage(self):
        import datetime
        dl_id = "test_dl_tourn_1"
        dl_data = {
            "guild_id": self.test_guild_id,
            "tournament": "Tourn1",
            "tournament_id": "tourn_id_1",
            "round": "Round 1",
            "deadline_dt": datetime.datetime.utcnow()
        }
        db.save_scheduled_deadline(dl_id, dl_data)
        self.assertTrue(os.path.exists('scheduled_deadlines.json'))
        with open('scheduled_deadlines.json', 'r', encoding='utf-8') as f:
            dls = json.load(f)
        self.assertIn(dl_id, dls)
        self.assertEqual(dls[dl_id]["tournament_id"], "tourn_id_1")

        # Now delete deadline
        db.delete_scheduled_deadline(dl_id)
        with open('scheduled_deadlines.json', 'r', encoding='utf-8') as f:
            dls_after = json.load(f)
        self.assertNotIn(dl_id, dls_after)

    def test_schema_columns_alignment(self):
        # Parse supabase_update_queries.sql to collect table columns
        sql_path = os.path.join(os.path.dirname(__file__), '..', 'supabase_update_queries.sql')
        self.assertTrue(os.path.exists(sql_path), "supabase_update_queries.sql must exist")
        
        with open(sql_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        import re
        table_columns = {}

        # 1. Parse CREATE TABLE blocks
        table_blocks = re.findall(r'CREATE TABLE IF NOT EXISTS\s+"?(\w+)"?\s*\((.*?)\);', sql_content, re.IGNORECASE | re.DOTALL)
        for tbl, block in table_blocks:
            tbl_cols = set()
            for line in block.split('\n'):
                line = line.strip()
                col_match = re.match(r'^"?(\w+)"?\s+[A-Za-z]', line)
                if col_match and col_match.group(1).upper() not in ("PRIMARY", "FOREIGN", "CONSTRAINT", "UNIQUE"):
                    tbl_cols.add(col_match.group(1).lower())
            table_columns[tbl.lower()] = tbl_cols

        # 2. Parse ALTER TABLE blocks (supports multiple ADD COLUMN clauses per ALTER TABLE)
        alter_blocks = re.findall(r'ALTER TABLE\s+"?(\w+)"?\s+(.*?);', sql_content, re.IGNORECASE | re.DOTALL)
        for tbl, block in alter_blocks:
            tbl_lower = tbl.lower()
            if tbl_lower not in table_columns:
                table_columns[tbl_lower] = set()
            cols = re.findall(r'ADD COLUMN IF NOT EXISTS\s+"?(\w+)"?', block, re.IGNORECASE)
            for c in cols:
                table_columns[tbl_lower].add(c.lower())

        # Test GuildConfig payload
        cfg = db.get_default_config()
        # Verify columns in table_columns['guildconfig']
        expected_gc_cols = ['guild_id', 'admin_role_id', 'organizer_role_id', 'helper_role_id', 'judge_role_id', 'recorder_role_id', 'staff_role_id', 'players_role_id', 'organization_name', 'schedule_channel_id', 'results_channel_id', 'bot_logs_channel_id']
        for col in expected_gc_cols:
            self.assertIn(col, table_columns.get('guildconfig', set()), f"Column {col} missing in GuildConfig schema")

        # Test Tournaments columns
        expected_t_cols = ['tournament_id', 'guild_id', 'tournament_name', 'state', 'game', 'auto_room_creation', 'attendance_channel_id', 'schedule_channel_id', 'result_channel_id']
        for col in expected_t_cols:
            self.assertIn(col, table_columns.get('tournaments', set()), f"Column {col} missing in Tournaments schema")

        # Test Matches columns
        expected_m_cols = ['match_id', 'tournament_id', 'team1_id', 'team2_id', 'team1_score', 'team2_score', 'status', 'winner_id', 'remarks', 'disqualified']
        for col in expected_m_cols:
            self.assertIn(col, table_columns.get('matches', set()), f"Column {col} missing in Matches schema")

        # Test MatchStaff columns
        expected_ms_cols = ['match_id', 'user_id', 'name', 'role', 'confirmed']
        for col in expected_ms_cols:
            self.assertIn(col, table_columns.get('matchstaff', set()), f"Column {col} missing in MatchStaff schema")

        # Test StaffStats columns
        expected_ss_cols = ['guild_id', 'user_id', 'name', 'judge_count', 'recorder_count', 'total_count', 'timestamp']
        for col in expected_ss_cols:
            self.assertIn(col, table_columns.get('staffstats', set()), f"Column {col} missing in StaffStats schema")

        # Test Deadlines columns
        expected_dl_cols = ['tournament_id', 'guild_id', 'round', 'deadline_time']
        for col in expected_dl_cols:
            self.assertIn(col, table_columns.get('deadlines', set()), f"Column {col} missing in Deadlines schema")

        # Test Players columns
        expected_p_cols = ['player_id', 'discord_id', 'ign', 'game_id', 'title']
        for col in expected_p_cols:
            self.assertIn(col, table_columns.get('players', set()), f"Column {col} missing in Players schema")

        # Test Teams columns
        expected_tm_cols = ['team_id', 'tournament_id', 'team_name', 'captain_id']
        for col in expected_tm_cols:
            self.assertIn(col, table_columns.get('teams', set()), f"Column {col} missing in Teams schema")

    def tearDown(self):
        # Clean up test artifacts from JSON
        if os.path.exists('guild_configs.json'):
            try:
                with open('guild_configs.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if self.test_guild_str in data:
                    del data[self.test_guild_str]
                with open('guild_configs.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
            except Exception:
                pass

        if os.path.exists('players.json'):
            try:
                with open('players.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if "123456789" in data:
                    del data["123456789"]
                with open('players.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

        if os.path.exists('teams.json'):
            try:
                with open('teams.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if "123456789" in data:
                    del data["123456789"]
                with open('teams.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

        if os.path.exists('staff_stats.json'):
            try:
                with open('staff_stats.json', 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if self.test_guild_str in data:
                    del data[self.test_guild_str]
                with open('staff_stats.json', 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass

if __name__ == '__main__':
    unittest.main()
