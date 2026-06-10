import os
import sys
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
client = create_client(url, key)

guild_id = "1303670721796640799"

print("=== GuildConfig ===")
resp = client.table("GuildConfig").select("*").eq("Guild_ID", guild_id).execute()
for row in resp.data:
    for k, v in row.items():
        print(f"  {k}: {v}")

print("\n=== Tournaments ===")
resp = client.table("Tournaments").select("*").eq("Guild_ID", guild_id).execute()
for row in resp.data:
    print(f"Tournament: {row.get('Tournament_ID')} ({row.get('Tournament_Name')})")
    for k, v in row.items():
        if k not in ('Tournament_ID', 'Guild_ID', 'Tournament_Name'):
            print(f"  {k}: {v}")
