import sys
import os
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web_server.app import app
from web_server.auth import hash_password, verify_password, create_access_token, decode_access_token
from web_server.database import get_sponsors, get_affiliate_products

class TestWebPortal(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_password_hashing(self):
        password = "SecurePassword2026!"
        pw_hash = hash_password(password)
        self.assertTrue(verify_password(pw_hash, password))
        self.assertFalse(verify_password(pw_hash, "WrongPassword"))

    def test_jwt_token_engine(self):
        payload = {"sub": "admin", "role": "super_admin", "is_super_admin": True}
        token = create_access_token(payload)
        decoded = decode_access_token(token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.get("sub"), "admin")
        self.assertEqual(decoded.get("role"), "super_admin")

    def test_public_pages(self):
        # Home page
        res = self.app.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"TOURNAMENT BOT", res.data)

        # Login page
        res = self.app.get("/login")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Tournament Access Portal", res.data)

    def test_public_api(self):
        # Tournaments API
        res = self.app.get("/api/public/tournaments")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

        # Sponsors API
        res = self.app.get("/api/public/sponsors")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

        # Affiliates API
        res = self.app.get("/api/public/affiliates")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")

    def test_master_login_flow(self):
        # Invalid credentials
        res = self.app.post("/api/auth/master-login", json={
            "username": "Hokageadmin",
            "password": "wrong_password_here"
        })
        self.assertEqual(res.status_code, 401)

        # Valid Hokageadmin credentials
        res = self.app.post("/api/auth/master-login", json={
            "username": "Hokageadmin",
            "password": "MyHokageadmin2004"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        token = data.get("token")
        self.assertIsNotNone(token)

        # Access protected dashboard with session cookie
        self.app.set_cookie("access_token", token)
        dash_res = self.app.get("/dashboard")
        self.assertEqual(dash_res.status_code, 200)
        self.assertIn(b"Organizer Command Center", dash_res.data)

    def test_guild_config_and_command_api(self):
        # Login as Hokageadmin
        res = self.app.post("/api/auth/master-login", json={
            "username": "Hokageadmin",
            "password": "MyHokageadmin2004"
        })
        token = res.get_json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        # Fetch config
        cfg_res = self.app.get("/api/organizer/guild-config?guild_id=1303670721796640799", headers=headers)
        self.assertEqual(cfg_res.status_code, 200)
        self.assertEqual(cfg_res.get_json().get("status"), "success")

        # Execute command
        cmd_res = self.app.post("/api/organizer/execute-command", json={
            "command": "!test_webhook",
            "guild_id": "1303670721796640799"
        }, headers=headers)
        self.assertEqual(cmd_res.status_code, 200)
        self.assertIn("SYSTEM_HEALTH", cmd_res.get_json().get("log_output"))

        # Create tournament from studio
        studio_res = self.app.post("/api/organizer/tournaments/create", json={
            "tournament_name": "Modern Warships Cup",
            "guild_id": "1303670721796640799",
            "game_category": "Modern Warships",
            "bracket_type": "single_elimination",
            "format": "5 vs 5",
            "participants": ["Team Alpha", "Team Beta"]
        }, headers=headers)
        self.assertEqual(studio_res.status_code, 200)
        t_data = studio_res.get_json()
        self.assertEqual(t_data.get("status"), "success")
        t_id = t_data.get("tournament", {}).get("Tournament_ID")

        # Sync tournament bracket link
        sync_res = self.app.post(f"/api/organizer/tournaments/{t_id}/sync-link", json={
            "bracket_link": f"/tournament/{t_id}"
        }, headers=headers)
        self.assertEqual(sync_res.status_code, 200)
        self.assertEqual(sync_res.get_json().get("status"), "success")

        # Update tournament
        update_res = self.app.put(f"/api/organizer/tournaments/{t_id}", json={
            "Tournament_Name": "Modern Warships Pro League",
            "State": "COMPLETED"
        }, headers=headers)
        self.assertEqual(update_res.status_code, 200)
        self.assertEqual(update_res.get_json().get("status"), "success")

        # Delete tournament
        del_res = self.app.delete(f"/api/organizer/tournaments/{t_id}", headers=headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.get_json().get("status"), "success")

    def test_challonge_api_endpoint(self):
        # Login as Hokageadmin
        res = self.app.post("/api/auth/master-login", json={
            "username": "Hokageadmin",
            "password": "MyHokageadmin2004"
        })
        token = res.get_json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        # Test validation when no API key is provided
        c_res = self.app.post("/api/organizer/challonge/create", json={
            "tournament_name": "MW Test Challonge"
        }, headers=headers)
        self.assertIn(c_res.status_code, (400, 500))

    def test_sponsor_click_redirect(self):
        sponsors = get_sponsors()
        if sponsors and len(sponsors) > 0:
            sp_id = sponsors[0]["id"]
            res = self.app.get(f"/api/public/click/{sp_id}")
            self.assertEqual(res.status_code, 302)

if __name__ == "__main__":
    unittest.main()


