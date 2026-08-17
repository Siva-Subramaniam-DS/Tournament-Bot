"""
Helper CLI to create or update Super Admin credentials for the Web Portal.
Usage:
    python scripts/create_master_user.py <username> <password> [role] [discord_id]
"""

import sys
import os

# Set UTF-8 encoding for Windows consoles
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web_server.auth import hash_password
from web_server.database import save_web_user

def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/create_master_user.py <username> <password> [role] [discord_id]")
        print("Example: python scripts/create_master_user.py admin MyStrongPass123! super_admin 1303887060754497569")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]
    role = sys.argv[3] if len(sys.argv) > 3 else "super_admin"
    discord_id = sys.argv[4] if len(sys.argv) > 4 else None

    pw_hash = hash_password(password)
    save_web_user(username, pw_hash, role=role, discord_id=discord_id)
    print("=" * 55)
    print(f"[OK] Success! Master user '{username}' created with role '{role}'.")
    if discord_id:
        print(f"[*] Linked Discord ID: {discord_id}")
    print("[-] Login at: http://localhost:8000/login -> Master Credentials")
    print("=" * 55)

if __name__ == "__main__":
    main()
