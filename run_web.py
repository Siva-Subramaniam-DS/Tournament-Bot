"""
Tournament Bot - Web Portal & Monetization Server Entrypoint
Usage: python run_web.py
"""

import sys
import os

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web_server.app import app
from web_server.config import PORT, HOST

if __name__ == "__main__":
    print("=" * 65)
    print("🏆 TOURNAMENT BOT - WEB PORTAL & MONETIZATION")
    print(f"🌐 Server running at: http://{HOST}:{PORT}")
    print(f"🎮 Discord OAuth Callback: http://{HOST}:{PORT}/api/auth/discord/callback")
    print("=" * 65)
    app.run(host=HOST, port=PORT, debug=True)
